"""Battle-menu paths that bypass both pinned instruction sites, and the overworld fallback.

BATTLE_FORCE_FAINT_WINDOW.md §9: a linked mon's faint is written at ``loop_head`` (MainInBattleLoop+0)
or ``player_action`` (ExecutePlayerMove+0). A successful RUN / Poké Doll / capture leaves the loop
before either; a failed RUN, an ITEM use and a PKMN switch set ``wActionResultOrTookBattleTurn``
and still reach ExecutePlayerMove. These tests pin those pret facts (Red/Blue share pokered
lines; Yellow's are pokeyellow), the ROM bytes where a pattern is stable, the decision the
authority takes on a used-up turn, and the fallback's refusals. No emulator runs.
"""
import ast
import re
from pathlib import Path

import pytest

from server import (
    battle_force_authority as auth,
    gen1_held_faint,
    held_write_permit,
    instruction_authority as generic,
)
from server.gen1_run_config import create_runtime
from server.protocol_journal import JournalError
from tests.unit.test_battle_force_authority import (
    MEMBER,
    VARIANTS,
    authority,
    evidence,
    state,
    verify,
)
from tests.unit.test_battle_force_window_analysis import (  # noqa: F401
    census,
    lo_hi,
    local,
    pinned,
    rom_at,
    routine,
)
from tests.unit.test_gen1_engine_signal_runtime import deliver
from tests.unit.test_gen1_faint_runtime import paired, signal_batch
from tests.unit.test_gen1_held_faint import checkpoint, evidence as held_evidence
from tests.unit.test_gen1_sessions import contract

ROOT = Path(__file__).resolve().parents[2]
INSTRUCTION_MODULES = ("server/instruction_authority.py", "server/battle_force_authority.py",
                       "lua/instruction_executor.lua", "lua/battle_force_authority.lua")

# engine/battle/core.asm line -> exact source line. Red and Blue build from pokered, so they share a column.
CORE_LINES = {
    "menu_call":        ((305, 314), "\tcall DisplayBattleMenu ; show battle menu"),
    "menu_ret_c":       ((306, 315), "\tret c ; return if player ran from battle"),
    "menu_pokedoll":    ((307, 316), "\tld a, [wEscapedFromBattle]"),
    "menu_ret_nz":      ((309, 318), "\tret nz ; return if pokedoll was used to escape from battle"),
    "select_move":      ((323, 332), ".selectPlayerMove"),
    "select_move_read": ((324, 333), "\tld a, [wActionResultOrTookBattleTurn]"),
    "select_move_skip": ((326, 335), "\tjr nz, .selectEnemyMove"),
    "run_lose_turn":    ((1572, 1613), "\tld [wActionResultOrTookBattleTurn], a ; you lose your turn when you can't escape"),
    "run_can_escape":   ((1584, 1625), ".canEscape"),
    "run_result_2":     ((1587, 1628), "\tld a, $2"),
    "run_play_sound":   ((1602, 1643), ".playSound"),
    "run_result_write": ((1603, 1644), "\tld [wBattleResult], a"),
    "run_scf":          ((1610, 1651), "\tscf ; set carry"),
    "run_ret":          ((1611, 1652), "\tret"),
    "bag_result_read":  ((2257, 2361), "\tld a, [wActionResultOrTookBattleTurn]"),
    "bag_retry":        ((2259, 2363), "\tjp z, BagWasSelected ; if not, go back to the bag menu"),
    "item_no_capture":  ((2282, 2386), ".returnAfterUsingItem_NoCapture"),
    "item_clear_carry": ((2285, 2389), "\tand a ; reset carry"),
    "capture":          ((2288, 2392), ".returnAfterCapturingMon"),
    "capture_result":   ((2293, 2397), "\tld [wBattleResult], a"),
    "capture_scf":      ((2294, 2398), "\tscf ; set carry"),
    "switch_not_out":   ((2406, 2512), ".notAlreadyOut"),
    "switch_took_turn": ((2410, 2516), "\tld [wActionResultOrTookBattleTurn], a"),
    "exec_head":        ((3073, 3244), "ExecutePlayerMove:"),
    "exec_cannot_move": ((3079, 3250), "\tjp z, ExecutePlayerMoveDone ; if the player cannot move, skip most of their turn"),
    "exec_result_read": ((3086, 3257), "\tld a, [wActionResultOrTookBattleTurn]"),
    "exec_result_skip": ((3088, 3259), "\tjp nz, ExecutePlayerMoveDone"),
}
# engine/items/item_effects.asm: every in-battle ITEM use starts from action_result = 1 (UseItem_ line 3);
# only "item not used"/"item use failed" handlers clear it. Poké Doll additionally sets wEscapedFromBattle.
ITEM_LINES = {
    "use_item_init":  ((3, 3), "\tld [wActionResultOrTookBattleTurn], a ; initialise to success value"),
    "pokedoll":       ((1606, 1755), "ItemUsePokeDoll:"),
    "pokedoll_flag":  ((1611, 1760), "\tld [wEscapedFromBattle], a"),
}


def line(p, text, key, table):
    lines, expected = table[key]
    number = lines[0] if p.title != "yellow" else lines[1]
    return text.splitlines()[number - 1], expected, number


def bank(p, name):
    return p.rom[census.flat(p.sym[name]) - (p.sym[name][1] - 0x4000):][:0x4000]  # the whole 16 KiB bank holding ``name``


def in_window(p, start, end, pattern):
    """Offsets (ROM addresses) of a bytes regex inside [start, end) of bank $0F."""
    rom = bank(p, start)
    lo, hi = p.sym[start][1] - 0x4000, p.sym[end][1] - 0x4000
    return [lo + m.start() + 0x4000 for m in re.finditer(pattern, rom[lo:hi], re.S)]


# ---------------------------------------------------------------- 1. source pins


def test_cited_core_and_item_lines_read_exactly_as_documented(pinned):  # noqa: F811
    p = pinned
    items = (p.root / "engine/items/item_effects.asm").read_text(encoding="utf-8")
    for key in CORE_LINES:
        got, expected, number = line(p, p.core, key, CORE_LINES)
        assert got == expected, (p.title, key, number, got)
    for key in ITEM_LINES:
        got, expected, number = line(p, items, key, ITEM_LINES)
        assert got == expected, (p.title, key, number, got)


def test_run_and_pokedoll_leave_the_loop_before_either_site(pinned):  # noqa: F811
    p = pinned
    loop = routine(p.core, "MainInBattleLoop")
    # (a) MainInBattleLoop Red 305-309 / Yellow 314-318: the menu's carry (a successful run) and
    # wEscapedFromBattle (Poké Doll) both `ret` out of the loop, so neither MainInBattleLoop+0 nor
    # ExecutePlayerMove+0 is executed again for this battle.
    assert "\tcall DisplayBattleMenu ; show battle menu\n\tret c ; return if player ran from battle\n" \
           "\tld a, [wEscapedFromBattle]\n\tand a\n\tret nz ; return if pokedoll was used to escape from battle\n" in loop
    escape = (b"\xcd" + lo_hi(p, "DisplayBattleMenu") + b"\xd8\xfa" + lo_hi(p, "wEscapedFromBattle") + b"\xa7\xc0")
    assert len(in_window(p, "MainInBattleLoop", "HandlePoisonBurnLeechSeed", re.escape(escape))) == 1
    # TryRunningFromBattle Red 1584-1611 / Yellow 1625-1652: .canEscape loads $2, .playSound stores it to
    # wBattleResult and the routine ends `scf; ret` -> DisplayBattleMenu returns carry to the loop.
    run = p.core[p.core.index("TryRunningFromBattle:"):p.core.index("CantEscapeText:")] + "CantEscapeText:\n"  # keep a label after .playSound
    assert local(run, ".canEscape").startswith("\tld a, [wLinkState]\n\tcp LINK_STATE_BATTLING\n\tld a, $2\n\tjr nz, .playSound\n")
    sound = local(run, ".playSound")
    assert sound.startswith("\tld [wBattleResult], a\n") and sound.rstrip().endswith("\tcall SaveScreenTilesToBuffer1\n\tscf ; set carry\n\tret")
    tail = (b"\xea" + re.escape(lo_hi(p, "wBattleResult")) + b"\x3e.\xcd" + re.escape(lo_hi(p, "PlaySoundWaitForCurrent")) + b"\x21" + re.escape(lo_hi(p, "GotAwayText"))
            + b"\xcd" + re.escape(lo_hi(p, "PrintText")) + b"\xcd" + re.escape(lo_hi(p, "WaitForSoundToFinish"))
            + b"\xcd" + re.escape(lo_hi(p, "SaveScreenTilesToBuffer1")) + b"\x37\xc9")
    assert len(in_window(p, "TryRunningFromBattle", "DisplayBattleMenu", tail)) == 1
    # Red 1571-1583 / Yellow 1612-1624: the failure branch stores 1 ("you lose your turn when you can't
    # escape"), prints, and returns with carry CLEAR (`and a; ret`) -> the loop continues to .selectPlayerMove.
    assert "\tld a, $1\n\tld [wActionResultOrTookBattleTurn], a ; you lose your turn when you can't escape\n\tld hl, CantEscapeText\n" in run
    assert "\tld [wForcePlayerToChooseMon], a\n\tcall SaveScreenTilesToBuffer1\n\tand a ; reset carry\n\tret\n.canEscape\n" in run
    fail = b"\x3e\x01\xea" + lo_hi(p, "wActionResultOrTookBattleTurn") + b"\x21" + lo_hi(p, "CantEscapeText") + b"\x18"
    assert len(in_window(p, "TryRunningFromBattle", "DisplayBattleMenu", re.escape(fail))) == 1
    # Poké Doll: item_effects.asm ItemUsePokeDoll Red 1606-1612 / Yellow 1755-1761 sets wEscapedFromBattle = 1.
    doll = routine((p.root / "engine/items/item_effects.asm").read_text(encoding="utf-8"), "ItemUsePokeDoll")
    assert doll.startswith("\tld a, [wIsInBattle]\n\tdec a\n\tjp nz, ItemUseNotTime\n\tld a, $01\n\tld [wEscapedFromBattle], a\n")


def test_capture_returns_carry_and_a_plain_item_use_returns_into_the_loop(pinned):  # noqa: F811
    p = pinned
    # (b) UseBagItem Red 2282-2295 / Yellow 2386-2399: .returnAfterUsingItem_NoCapture `and a; ret` (carry
    # clear, back into MainInBattleLoop) vs .returnAfterCapturingMon wBattleResult = 2 then `scf; ret`.
    bag = p.core[p.core.index("BagWasSelected:"):p.core.index("PartyMenuOrRockOrRun:")]
    # local() runs to the next GLOBAL label, so the no-capture block is read up to and including the capture label
    assert local(bag, ".returnAfterUsingItem_NoCapture").startswith("\tcall GBPalNormal\n\tand a ; reset carry\n\tret\n\n.returnAfterCapturingMon\n")
    assert local(bag, ".returnAfterCapturingMon").startswith("\tcall GBPalNormal\n\txor a\n\tld [wCapturedMonSpecies], a\n\tld a, $2\n"
                                                             "\tld [wBattleResult], a\n\tscf ; set carry\n\tret\n\n")
    tails = (b"\xcd" + lo_hi(p, "GBPalNormal") + b"\xa7\xc9" + b"\xcd" + lo_hi(p, "GBPalNormal") + b"\xaf\xea" + lo_hi(p, "wCapturedMonSpecies")
             + b"\x3e\x02\xea" + lo_hi(p, "wBattleResult") + b"\x37\xc9")
    assert len(in_window(p, "BagWasSelected", "PartyMenuOrRockOrRun", re.escape(tails))) == 1


def test_item_and_switch_mark_the_turn_used_and_the_loop_still_calls_execute_player_move(pinned):  # noqa: F811
    p = pinned
    items = (p.root / "engine/items/item_effects.asm").read_text(encoding="utf-8")
    # (c) ITEM: UseItem_ line 3 (both titles) initialises wActionResultOrTookBattleTurn = 1; UseBagItem Red
    # 2257-2259 / Yellow 2361-2363 reads it back and only a cleared value ("item not used") returns to the bag.
    assert routine(items, "UseItem_").startswith("\tld a, 1\n\tld [wActionResultOrTookBattleTurn], a ; initialise to success value\n")
    assert items.count("ld [wActionResultOrTookBattleTurn], a ; item not used") >= 3
    assert items.count("ld [wActionResultOrTookBattleTurn], a ; item use failed") >= 3
    bag = p.core[p.core.index("UseBagItem:"):p.core.index("PartyMenuOrRockOrRun:")]
    assert "\tld a, [wActionResultOrTookBattleTurn]\n\tand a ; was the item used successfully?\n\tjp z, BagWasSelected" in bag
    read_back = b"\xfa" + lo_hi(p, "wActionResultOrTookBattleTurn") + b"\xa7\xca" + lo_hi(p, "BagWasSelected")
    assert len(in_window(p, "UseBagItem", "PartyMenuOrRockOrRun", re.escape(read_back))) == 1
    # PKMN: PartyMenuOrRockOrRun .notAlreadyOut Red 2406-2410 / Yellow 2512-2516 stores 1 right before SwitchPlayerMon.
    party = p.core[p.core.index("PartyMenuOrRockOrRun:"):p.core.index("SwitchPlayerMon:") + len("SwitchPlayerMon:")]
    assert local(party, ".notAlreadyOut").startswith("\tcall HasMonFainted\n\tjp z, .partyMonDeselected ; can't switch to fainted mon\n"
                                                     "\tld a, $1\n\tld [wActionResultOrTookBattleTurn], a\n\tcall GBPalWhiteOut\n")
    assert party.count("ld [wActionResultOrTookBattleTurn], a") == 1
    switch = (b"\xcd" + re.escape(lo_hi(p, "HasMonFainted")) + b"\xca..\x3e\x01\xea" + re.escape(lo_hi(p, "wActionResultOrTookBattleTurn"))
              + b"\xcd" + re.escape(lo_hi(p, "GBPalWhiteOut")))
    assert len(in_window(p, "PartyMenuOrRockOrRun", "SwitchPlayerMon", switch)) == 1
    # The loop: .selectPlayerMove Red 323-326 / Yellow 332-335 skips the move menu on a used turn, and the
    # only two `call ExecutePlayerMove` sites are still reached from .selectEnemyMove's ordering blocks.
    select = local(p.core, ".selectPlayerMove")
    assert select.startswith("\tld a, [wActionResultOrTookBattleTurn]\n\tand a ; has the player already used the turn"
                             " (e.g. by using an item, trying to run or switching pokemon)\n\tjr nz, .selectEnemyMove\n")
    skip = b"\xfa" + lo_hi(p, "wActionResultOrTookBattleTurn") + b"\xa7\x20"
    assert len(in_window(p, "MainInBattleLoop", "HandlePoisonBurnLeechSeed", re.escape(skip))) == 1
    loop_to_poison = p.core[p.core.index("MainInBattleLoop:"):p.core.index("HandlePoisonBurnLeechSeed:")]
    assert loop_to_poison.count("\tcall ExecutePlayerMove\n") == 2 and p.core.count("\tcall ExecutePlayerMove\n") == 2


def test_execute_player_move_checks_cannot_move_before_the_used_turn_and_both_skip_to_done(pinned):  # noqa: F811
    p = pinned
    a = auth.ANCHORS[p.title]
    # (d) ExecutePlayerMove Red 3073-3088 / Yellow 3244-3259: CANNOT_MOVE ($FF) skip first (the site's own
    # write), then wActionResultOrTookBattleTurn nonzero `jp nz, ExecutePlayerMoveDone`. Either way the
    # caller's HandlePoisonBurnLeechSeed sees wBattleMonHP = 0 and `jp z, HandlePlayerMonFainted`.
    head = routine(p.core, "ExecutePlayerMove")
    cannot = head.index("\tinc a\n\tjp z, ExecutePlayerMoveDone ; if the player cannot move, skip most of their turn\n")
    used = head.index("\tld a, [wActionResultOrTookBattleTurn]\n\tand a ; has the player already used the turn")
    assert cannot < used < head.index(".playerHasNoSpecialCondition")
    assert head[used:].splitlines()[2] == "\tjp nz, ExecutePlayerMoveDone"
    done = lo_hi(p, "ExecutePlayerMoveDone")
    expected = (b"\xaf\xe0\xf3\xfa" + lo_hi(p, "wPlayerSelectedMove") + b"\x3c\xca" + done  # xor a; ldh [hWhoseTurn]; ld a,[wPlayerSelectedMove]; inc a; jp z
                + b"\xaf\xea" + lo_hi(p, "wMoveMissed") + b"\xea" + lo_hi(p, "wMonIsDisobedient") + b"\xea" + lo_hi(p, "wMoveDidntMiss")
                + b"\x3e\x0a\xea" + lo_hi(p, "wDamageMultipliers")  # ld a, EFFECTIVE (10)
                + b"\xfa" + lo_hi(p, "wActionResultOrTookBattleTurn") + b"\xa7\xc2" + done)  # ld a,[wActionResult..]; and a; jp nz, Done
    assert rom_at(p, "ExecutePlayerMove", len(expected)) == expected
    assert expected.hex().startswith(a["player_action"]["expected_hex"])  # the authority pins the first 14 of these bytes
    assert "ASSERT CANNOT_MOVE == $ff" in head
    for block in (".playerMovesFirst", ".AIActionUsedEnemyFirst"):
        assert "\tcall ExecutePlayerMove\n" in local(p.core, block) and "\tcall HandlePoisonBurnLeechSeed\n\tjp z, HandlePlayerMonFainted\n" in local(p.core, block)


# ---------------------------------------------------------------- 2. decisions on a used-up turn


@pytest.mark.parametrize("variant", VARIANTS)
def test_used_turn_still_faints_the_active_linked_mon_at_player_action(variant):
    st = state(variant, action_result=1)  # item / switch-attempt / failed run already consumed the turn
    decision = auth.decide(st, MEMBER, variant, "player_action")
    assert decision == {"writes": auth.active_writes(variant, "player_action"), "refusal": None, "outcome": "fainted"}
    assert decision["writes"][2]["value"] == 0xFF  # CANNOT_MOVE: checked before the used-turn skip, so redundant but harmless
    assert verify(authority(variant), evidence(variant, "player_action", st)) == {"outcome": "fainted", "site": "player_action", "reason": None}


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("site", auth.SITES)
def test_completed_switch_benches_the_linked_mon_by_its_party_slot(variant, site):
    # after SwitchPlayerMon, wPlayerMonNumber names the newcomer and action_result is still 1
    st = state(variant, player_mon_number=4, action_result=1, battle_species=0x19, battle_dvs_hex="1111")
    decision = auth.decide(st, MEMBER, variant, site)
    assert decision == {"writes": auth.benched_writes(variant, MEMBER["slot"]), "refusal": None, "outcome": "benched"}
    assert verify(authority(variant), evidence(variant, site, st)) == {"outcome": "benched", "site": site, "reason": None}
    active = auth.ANCHORS[variant]["addresses"]
    assert not {active["wBattleMonHP"], active["wBattleMonHP"] + 1, active["wPlayerSelectedMove"]} & {w["address"] for w in decision["writes"]}


# ---------------------------------------------------------------- 3. fallback and no-reuse


def test_held_faint_guard_is_in_source_and_checkpoint_refuses_a_battle_flag(pinned):  # noqa: F811
    source = (ROOT / "server/gen1_held_faint.py").read_text(encoding="utf-8")
    assert "intent['before']['battle_flag']!=0" in source and "held faint may only write the verified overworld party slot" in source
    point = checkpoint(pinned.title)
    gen1_held_faint.verify_checkpoint(point, pinned.title)
    flag = str(gen1_held_faint.PROFILES[pinned.title]["BATTLE_FLAG_ADDR"])
    assert flag == str(pinned.sym["wIsInBattle"][1])
    for value in (1, 2):
        with pytest.raises(JournalError, match="battle, text, script or serial owns the checkpoint"):
            gen1_held_faint.verify_checkpoint({**point, "system": {**point["system"], flag: value}}, pinned.title)


@pytest.mark.parametrize("variant", VARIANTS)
def test_held_faint_refuses_an_intent_prepared_inside_a_battle(tmp_path, variant):
    runtime = create_runtime(tmp_path, contract(variant, variant))
    try:
        owners = paired(runtime)
        deliver(runtime, "a", owners["a"], signal_batch(runtime, "a"))
        command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
        value = held_evidence(runtime, command)
        binding = runtime.gate.sessions["b"].metadata["control_binding"]
        assert isinstance(gen1_held_faint.verify("b", command, value, runtime.state().document(), binding), held_write_permit.VerifiedHeldWrite)
        before, after = value["intent"]["before"], value["intent"]["after"]
        # an internally consistent in-battle receipt (the active mon is the target, HP mirror 0 after) passes the
        # receipt validator and is stopped by gen1_held_faint's own battle_flag guard
        before.update(battle_flag=1, active_slot=0, battle_hp=int(before["party"][0][2:6], 16))
        after.update(battle_flag=1, active_slot=0, battle_hp=0)
        value["current"] = before
        with pytest.raises(JournalError, match="held faint may only write the verified overworld party slot"):
            gen1_held_faint.verify("b", command, value, runtime.state().document(), binding)
        # a bare battle_flag with no active battler is refused one layer earlier, by the receipt validator
        before.update(active_slot=None, battle_hp=None)
        with pytest.raises(JournalError, match="invalid active party slot"):
            gen1_held_faint.verify("b", command, value, runtime.state().document(), binding)
    finally:
        runtime.close()


def test_instruction_modules_never_touch_the_held_write_permit():
    for rel in INSTRUCTION_MODULES:
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert "VerifiedHeldWrite" not in source and "ttl_ms" not in source, rel
        if rel.endswith(".py"):
            tree = ast.parse(source)
            imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
                       {alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names}
            assert not any("held_write_permit" in (m or "") for m in imported), rel
            assert "held_write_permit" not in source.replace(ast.get_docstring(tree) or "", ""), rel  # the docstring may name it as untouched
        else:
            assert "held_write_permit" not in source and "permit" not in source, rel
    for variant in VARIANTS:
        issued = authority(variant)
        assert "ttl_ms" not in issued and issued["uses"] == 1 and issued["held"] is False
        assert issued["schema"] == generic.SCHEMA != held_write_permit.SCHEMA
        assert set(issued) == {"schema", "challenge", "scope", "proof_digest", "owner_id", "frame", "step", "uses", "held", "binding", "member", "sites", "addresses",
                           "hook_frame_offset"}  # the measured host convention travels with the authority; never a ttl


@pytest.mark.parametrize("held", [True, "false", 0, None])
def test_verify_envelope_refuses_any_claim_of_a_held_frame(held):
    a = authority("red")
    row = evidence("red", "loop_head", held=held)
    with pytest.raises(JournalError, match="cannot fire in a held frame"):
        generic.verify_envelope(a, row, hook_frame_offset=0)
    assert generic.verify_envelope(a, evidence("red", "loop_head"), hook_frame_offset=0) == "loop_head"
