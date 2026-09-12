"""The explode binding of the battle instruction authority (P5 as built, P11): source pins, footprint,
decision, server verification and the Lua executor, always next to the faint binding it shares its
two sites with. No emulator runs: the Lua executor is driven against the same stubbed bus as the
faint tests, and the server settles every row the executor produced.
"""
import json

import pytest

from server import battle_force_authority as auth, instruction_authority as generic
from server.protocol_journal import JournalError
from tests.unit.test_battle_force_authority import (  # noqa: F401
    BINDING,
    COMMAND,
    DEATH,
    HOST,
    MEMBER,
    OFFSET,
    OWNER,
    VARIANTS,
    arm,
    authority,
    bus,
    evidence,
    finish,
    load,
    probe,
    run_frame,
    state,
    verify,
)
from tests.unit.test_battle_force_window_analysis import census, pinned, routine  # noqa: F401
from tests.unit.test_client_state_store import runtime  # noqa: F401

EXPLODE_COMMAND = {**COMMAND, "body": {**COMMAND["body"], "cmd": "force_explode"}}
SLOTS_BEFORE = ([0x21, 0x27, 0, 0], [0x23, 0x1E, 0, 0])  # state(): TACKLE 35 PP, TAIL WHIP 30 PP, two empty slots
TRANSFORMED_REASON = "transformed battle mon keeps the copied moveset"


# ---------------------------------------------------------------- source pins


def test_move_slot_addresses_and_the_engine_paths_the_binding_relies_on_are_pinned(pinned):  # noqa: F811
    p = pinned
    a = auth.ANCHORS[p.title]["addresses"]
    assert (p.sym["wBattleMonMoves"][1], p.sym["wBattleMonPP"][1]) == (a["wBattleMonMoves"], a["wBattleMonPP"])
    assert a["wBattleMonMoves"] - a["wBattleMonSpecies"] == 8 and a["wBattleMonPP"] - a["wBattleMonSpecies"] == 25  # battle struct layout
    # SelectMenuItem re-derives wPlayerSelectedMove from the chosen slot on every confirm: all four slots must explode...
    assert ("\tld a, [wCurrentMenuItem]\n\tld hl, wBattleMonMoves\n\tld c, a\n\tld b, $0\n\tadd hl, bc\n\tld a, [hl]\n"
            "\tld [wPlayerSelectedMove], a\n\txor a\n\tret\n") in p.core
    # ...and refuses a slot whose PP is 0, so PP 5 keeps every slot selectable
    assert "\tld hl, wBattleMonPP\n\tld a, [wCurrentMenuItem]\n\tld c, a\n\tld b, $0\n\tadd hl, bc\n\tld a, [hl]\n\tand PP_MASK\n\tjr z, .noPP\n" in p.core
    # GetCurrentMove loads wPlayerSelectedMove with no membership check; ExecutePlayerMove skips a used turn before it
    assert "\tld a, [wPlayerSelectedMove]\n.selected\n\tld [wNameListIndex], a\n\tdec a\n\tld hl, Moves\n" in routine(p.core, "GetCurrentMove")
    head = routine(p.core, "ExecutePlayerMove")
    assert "\tld a, [wActionResultOrTookBattleTurn]\n\tand a" in head and "\tjp nz, ExecutePlayerMoveDone\n" in head
    # the self-KO is the engine's own ExplodeEffect (HP zeroed even on a miss); PP is decremented by wPlayerMoveListIndex only
    effects = (p.root / "engine/battle/effects.asm").read_text(encoding="utf-8")
    assert "ExplodeEffect:\n\tld hl, wBattleMonHP\n" in effects and ".faintUser\n\txor a\n\tld [hli], a ; set the mon's HP to 0\n\tld [hli], a\n" in effects
    assert "\tld a, [wPlayerMoveListIndex] ; which move (0, 1, 2, 3) did we use?\n" in (p.root / "engine/battle/decrement_pp.asm").read_text(encoding="utf-8")
    assert "\tconst EXPLOSION    ; 99\n" in (p.root / "constants/move_constants.asm").read_text(encoding="utf-8") and auth.EXPLOSION == 0x99


def test_explode_footprints_are_the_documented_eight_and_one_bytes_and_the_faint_binding_is_untouched():
    for variant in VARIANTS:
        a = auth.ANCHORS[variant]["addresses"]
        assert auth.explode_writes(variant, "loop_head") == ([{"address": a["wBattleMonMoves"] + i, "value": 0x99} for i in range(4)]
                                                              + [{"address": a["wBattleMonPP"] + i, "value": 5} for i in range(4)])
        assert auth.explode_writes(variant, "player_action") == [{"address": a["wPlayerSelectedMove"], "value": 0x99}]
        for site in auth.SITES:
            assert auth.sites(variant, auth.EXPLODE)[site]["writes"] == auth.explode_writes(variant, site)
            assert auth.sites(variant)[site]["writes"] == auth.sites(variant, auth.BINDING)[site]["writes"] == auth.active_writes(variant, site)
            assert not {w["address"] for w in auth.explode_writes(variant, site)} & {a["wBattleMonHP"], a["wBattleMonHP"] + 1}  # HP is the engine's to zero
            assert {k: v for k, v in auth.sites(variant, auth.EXPLODE)[site].items() if k != "writes"} == {k: v for k, v in auth.sites(variant)[site].items() if k != "writes"}
    assert auth.BINDINGS == {"force_faint": auth.BINDING, "force_explode": auth.EXPLODE} and auth.EXPLODE_PP == 5


# ---------------------------------------------------------------- server side


def explode_authority(variant, **host):
    proof = auth.prepare("a", EXPLODE_COMMAND, BINDING, DEATH, MEMBER, {**HOST, **host}, variant=variant)
    return auth.issue({"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": dict(proof.scope)}, proof)


def explode_evidence(variant, site, st=None, **over):
    return evidence(variant, site, st, binding=auth.EXPLODE, **over)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("site", auth.SITES)
def test_active_linked_mon_is_armed_to_explode_at_either_site(variant, site):
    a = explode_authority(variant)
    assert a["binding"] == auth.EXPLODE and a["uses"] == 1 and a["held"] is False and a["sites"][site]["writes"] == auth.explode_writes(variant, site)
    assert auth.decide(state(variant), MEMBER, variant, site, binding=auth.EXPLODE) == {"writes": auth.explode_writes(variant, site), "refusal": None, "outcome": "explode_armed"}
    assert auth.decide(state(variant), MEMBER, variant, site) == {"writes": auth.active_writes(variant, site), "refusal": None, "outcome": "fainted"}
    row = explode_evidence(variant, site)
    expected = [("21", "99"), ("27", "99"), ("00", "99"), ("00", "99"), ("23", "05"), ("1e", "05"), ("00", "05"), ("00", "05")] if site == "loop_head" else [("21", "99")]
    assert [(w["before_hex"], w["after_hex"]) for w in row["writes"]] == expected
    assert verify(a, row) == {"outcome": "explode_armed", "site": site, "reason": None}


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("site", auth.SITES)
def test_benched_linked_mon_gets_the_faint_bindings_party_write(variant, site):
    a = explode_authority(variant)
    st = state(variant, player_mon_number=0, battle_species=0x19, battle_dvs_hex="1111", party_status=0x08)
    decision = auth.decide(st, MEMBER, variant, site, binding=auth.EXPLODE)
    assert decision == auth.decide(st, MEMBER, variant, site) == {"writes": auth.benched_writes(variant, 2), "refusal": None, "outcome": "benched"}
    assert verify(a, explode_evidence(variant, site, st)) == {"outcome": "benched", "site": site, "reason": None}
    assert verify(a, explode_evidence(variant, site, state(variant, player_mon_number=0, party_hp_hex="0000")))["reason"] == "already fainted"


@pytest.mark.parametrize("variant", VARIANTS)
def test_transformed_linked_mon_keeps_its_copied_moveset_but_the_committed_turn_still_explodes(variant):
    a = explode_authority(variant)
    st = state(variant, status3=auth.TRANSFORMED, battle_species=0x15, battle_dvs_hex="ffff", moves_hex="21212121", pp_hex="05050505")
    assert auth.decide(st, MEMBER, variant, "loop_head", binding=auth.EXPLODE) == {"writes": [], "refusal": TRANSFORMED_REASON}
    assert verify(a, explode_evidence(variant, "loop_head", st)) == {"outcome": "refused", "site": "loop_head", "reason": TRANSFORMED_REASON}
    assert auth.decide(st, MEMBER, variant, "player_action", binding=auth.EXPLODE) == {"writes": auth.explode_writes(variant, "player_action"), "refusal": None, "outcome": "explode_armed"}
    assert verify(a, explode_evidence(variant, "player_action", st))["outcome"] == "explode_armed"
    assert auth.decide(st, MEMBER, variant, "loop_head")["outcome"] == "fainted"  # the faint binding still faints a transformed linked mon


@pytest.mark.parametrize("variant", VARIANTS)
def test_a_turn_already_taken_refuses_the_action_site_coercion_only(variant):
    a = explode_authority(variant)
    st = state(variant, action_result=1)  # an item, switch attempt or failed run consumed the turn: ExecutePlayerMove skips the move
    assert auth.decide(st, MEMBER, variant, "player_action", binding=auth.EXPLODE) == {"writes": [], "refusal": "turn already taken"}
    assert verify(a, explode_evidence(variant, "player_action", st)) == {"outcome": "refused", "site": "player_action", "reason": "turn already taken"}
    assert auth.decide(st, MEMBER, variant, "loop_head", binding=auth.EXPLODE)["outcome"] == "explode_armed"  # at the loop head the flag is last turn's
    assert auth.decide(st, MEMBER, variant, "player_action")["outcome"] == "fainted"  # the faint binding's skip is still right on a used turn


@pytest.mark.parametrize("over,reason", [
    ({"is_in_battle": 0}, "not in a wild or trainer battle"),
    ({"battle_type": 2}, "no player mon in play"),
    ({"link_state": 4}, "link battle"),
    ({"party_ot_id_hex": "4321"}, "party slot is not the linked mon"),
    ({"battle_species": 0x85}, "active battle struct is not the linked mon"),
    ({"hp_hex": "0000"}, "already fainted"),
    ({"enemy_hp_hex": "0000"}, "enemy faint path"),
])
@pytest.mark.parametrize("site", auth.SITES)
def test_every_faint_refusal_refuses_the_explode_binding_with_the_same_reason(site, over, reason):
    st = state("red", **over)
    faint, explode = auth.decide(st, MEMBER, "red", site), auth.decide(st, MEMBER, "red", site, binding=auth.EXPLODE)
    assert faint == explode and faint["writes"] == [] and reason in faint["refusal"]
    assert verify(explode_authority("red"), explode_evidence("red", site, st))["outcome"] == "refused"


@pytest.mark.parametrize("mutate,match", [
    (lambda r, v: r["writes"][7].update(after_hex="fe"), "outside the authorized byte set"),  # one changed byte (the last PP)
    (lambda r, v: r["writes"][0].update(after_hex="21"), "outside the authorized byte set"),  # a move slot left as it was
    (lambda r, v: r["writes"].pop(), "exact authorized write set"),  # a missing PP write
    (lambda r, v: r["writes"].pop(0), "exact authorized write set"),  # a missing move write
    (lambda r, v: r["writes"][4].update(before_hex="00"), "outside the authorized byte set"),  # readback differs from the snapshot
    (lambda r, v: r["writes"][3].update(address=auth.ANCHORS[v]["addresses"]["wBattleMonMoves"] + 4), "outside the authorized byte set"),  # the DVs
    (lambda r, v: r["writes"].append({"address": auth.ANCHORS[v]["addresses"]["wBattleMonHP"] + 1, "before_hex": "37", "after_hex": "00"}), "exact authorized write set"),
    (lambda r, v: r["state"].update(moves_hex="2127"), "instruction state move slots"),
    (lambda r, v: r["state"].update(pp_hex="231E0000"), "instruction state move slots"),
    (lambda r, v: r["state"].pop("pp_hex"), "complete instruction state"),
])
@pytest.mark.parametrize("variant", VARIANTS)
def test_forged_explode_footprints_are_refused(variant, mutate, match):
    a = explode_authority(variant)
    row = explode_evidence(variant, "loop_head")
    mutate(row, variant)
    with pytest.raises(JournalError, match=match):
        verify(a, row)


def test_the_wrong_site_or_the_wrong_binding_never_verifies():
    a, faint = explode_authority("red"), authority("red")
    loop, action = explode_evidence("red", "loop_head"), explode_evidence("red", "player_action")
    with pytest.raises(JournalError, match="exact authorized write set"):  # the eight-byte footprint claimed at the action site
        verify(a, dict(action, writes=loop["writes"]))
    with pytest.raises(JournalError, match="exact authorized write set"):  # the one-byte footprint claimed at the loop head
        verify(a, dict(loop, writes=action["writes"]))
    with pytest.raises(JournalError, match="exact authorized write set"):  # the faint footprint under the explode authority
        verify(a, dict(loop, writes=evidence("red", "loop_head")["writes"]))
    with pytest.raises(JournalError, match="exact authorized write set"):  # explode bytes under the faint authority
        verify(faint, loop)
    with pytest.raises(JournalError, match="not the pinned instruction"):  # a loop_head row relabelled as the action site
        verify(a, dict(loop, site="player_action"))
    with pytest.raises(JournalError, match="not a battle force-faint authority"):
        verify({**a, "binding": "rby-battle-force-other"}, loop)


def test_the_command_selects_the_binding_and_the_challenge_rules_are_unchanged():
    proof = auth.prepare("a", EXPLODE_COMMAND, BINDING, DEATH, MEMBER, HOST, variant="red")
    faint = auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, HOST, variant="red")
    assert proof.binding == auth.EXPLODE and faint.binding == auth.BINDING and proof.scope["phase"] == faint.scope["phase"] == "battle_force_faint"
    assert dict(proof.scope) != dict(faint.scope)  # the scope digests the command body: an explode proof is the explode command's
    assert proof.member["variant"] == "red" and proof.frame == 1200 and proof.step == 9 and proof.count == 1
    with pytest.raises(JournalError, match="serves force_faint and force_explode only"):
        auth.prepare("a", {**COMMAND, "body": {**COMMAND["body"], "cmd": "memorialize"}}, BINDING, DEATH, MEMBER, HOST, variant="red")
    for death in ({**DEATH, "phase": "pending_memorial"}, {**DEATH, "peer": "b"}, None):
        with pytest.raises(JournalError, match="pending owned death"):
            auth.prepare("a", EXPLODE_COMMAND, BINDING, death, MEMBER, HOST, variant="red")
    issued = auth.issue({"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": dict(proof.scope)}, proof)
    assert issued["binding"] == auth.EXPLODE and issued["sites"] == auth.sites("red", auth.EXPLODE) and issued["addresses"] == auth.ANCHORS["red"]["addresses"]
    assert set(issued) == set(authority("red")) and issued["hook_frame_offset"] == auth.HOOK_FRAME_OFFSET == 0 and "frames" not in issued
    with pytest.raises(ValueError, match="scope differs"):  # the faint command's scope cannot issue the explode proof
        auth.issue({"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": dict(faint.scope)}, proof)
    other = generic.VerifiedInstructionAuthority(dict(proof.scope), proof.proof_digest, OWNER, 1200, 9, "rby-battle-force-other", {"variant": "red"})
    with pytest.raises(ValueError, match="verified battle instruction authority"):
        auth.issue({"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": dict(proof.scope)}, other)
    window = explode_authority("red", count=5)
    assert window["frames"] == {"first": 1200, "count": 5} and generic.window(window) == (1200, 5)
    inside = explode_evidence("red", "loop_head", frame=1202, step=11, hook_frame=1202 + OFFSET)
    assert verify(window, inside)["outcome"] == "explode_armed"
    with pytest.raises(JournalError, match="not from the authorized bounded step"):
        verify(window, dict(inside, step=9))
    with pytest.raises(JournalError, match="not from the authorized bounded step"):
        verify(explode_authority("red"), inside)  # a single-frame authority does not stretch
    with pytest.raises(JournalError, match="outside the authorized frame"):
        verify(window, dict(inside, hook_frame=1203 + OFFSET))
    with pytest.raises(JournalError, match="convention is unverified"):
        auth.verify_evidence({**explode_authority("red"), "hook_frame_offset": None}, explode_evidence("red", "loop_head"))


# ---------------------------------------------------------------- lua executor


@pytest.fixture
def explode_probe(probe):  # noqa: F811
    probe.execute("X.close();X=require('battle_force_authority').new({owner_id=string.rep('a',32),held=function()return held end,name='rby-battle-force-explode'})")
    return probe


def hit_explode(lua, site, *, frame_delta=OFFSET):
    lua.execute(f"held=false;frame=frame+({frame_delta});pc=target.pc;hooks['slink-instruction-rby-battle-force-explode-{site}']();frame=frame-({frame_delta})")


def slots(lua, variant):
    a = auth.ANCHORS[variant]["addresses"]
    return [bus(lua, a["wBattleMonMoves"] + i) for i in range(4)], [bus(lua, a["wBattleMonPP"] + i) for i in range(4)]


def fresh(variant, frame, step, challenge):
    a = explode_authority(variant, frame=frame, step=step)
    a["challenge"] = challenge
    return a


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("site", auth.SITES)
def test_executor_writes_exactly_the_explode_footprint_and_the_server_settles_it(explode_probe, variant, site):
    lua = explode_probe
    a = explode_authority(variant)
    addr = auth.ANCHORS[variant]["addresses"]
    load(lua, variant, state(variant), site)
    arm(lua, a)
    hit_explode(lua, site)
    run_frame(lua)
    row = finish(lua)
    assert slots(lua, variant) == (([0x99] * 4, [5] * 4) if site == "loop_head" else SLOTS_BEFORE)
    assert bus(lua, addr["wPlayerSelectedMove"]) == (0x99 if site == "player_action" else 0x21)
    assert (bus(lua, addr["wBattleMonHP"]), bus(lua, addr["wBattleMonHP"] + 1)) == (0, 0x37) and bus(lua, addr["wPartyMon1HP"] + 89) == 0x37  # HP untouched
    assert bus(lua, addr["wBattleMonMoves"] + 4) == 0x9A and bus(lua, addr["wBattleMonPP"] + 4) == 0  # the DVs after the slots, and the byte after PP
    assert row["site"] == site and row["hook_frame"] == 1200 + OFFSET and row["state"]["moves_hex"] == "21270000" and row["state"]["pp_hex"] == "231e0000"
    assert verify(a, row) == {"outcome": "explode_armed", "site": site, "reason": None}
    assert lua.eval("X.status().armed") is False and lua.eval("X.status().last_step") == 9
    with pytest.raises(Exception, match="already used"):  # one use, exactly as the faint binding
        arm(lua, a)


@pytest.mark.parametrize("variant", VARIANTS)
def test_re_arming_after_the_loop_head_write_is_idempotent_and_the_menu_choice_reaches_the_action_site_as_explosion(explode_probe, variant):
    lua = explode_probe
    addr = auth.ANCHORS[variant]["addresses"]
    load(lua, variant, state(variant), "loop_head")
    arm(lua, explode_authority(variant))
    hit_explode(lua, "loop_head")
    run_frame(lua)
    finish(lua)
    again = fresh(variant, 1201, 10, "0" * 32)  # the move was stopped that turn (sleep, paralysis, RUN): the next window re-arms on the same bytes
    arm(lua, again)
    hit_explode(lua, "loop_head")
    run_frame(lua)
    row = finish(lua)
    assert all(w["before_hex"] == w["after_hex"] for w in row["writes"]) and row["state"]["moves_hex"] == "99999999" and row["state"]["pp_hex"] == "05050505"
    assert verify(again, row) == {"outcome": "explode_armed", "site": "loop_head", "reason": None}
    # the menu re-derived EXPLOSION from a rewritten slot: the action site finds $99 already selected and its one byte is a no-op too
    load(lua, variant, state(variant, moves_hex="99999999", pp_hex="05050505", selected_move=0x99), "player_action")
    action = fresh(variant, 1202, 11, "1" * 32)
    arm(lua, action)
    hit_explode(lua, "player_action")
    run_frame(lua)
    row = finish(lua)
    assert row["writes"] == [{"address": addr["wPlayerSelectedMove"], "before_hex": "99", "after_hex": "99"}] and row["state"]["selected_move"] == 0x99
    assert verify(action, row) == {"outcome": "explode_armed", "site": "player_action", "reason": None}


@pytest.mark.parametrize("variant", VARIANTS)
def test_executor_benched_transformed_and_used_turn_branches_match_the_server(explode_probe, variant):
    lua = explode_probe
    addr = auth.ANCHORS[variant]["addresses"]
    load(lua, variant, state(variant, player_mon_number=0, battle_species=0x19, battle_dvs_hex="1111", party_status=0x08), "loop_head")
    arm(lua, explode_authority(variant))
    hit_explode(lua, "loop_head")
    run_frame(lua)
    row = finish(lua)
    assert bus(lua, addr["wPartyMon1HP"] + 88) == 0 and bus(lua, addr["wPartyMon1HP"] + 89) == 0 and bus(lua, addr["wPartyMon1Status"] + 88) == 0
    assert slots(lua, variant) == SLOTS_BEFORE and bus(lua, addr["wBattleMonHP"] + 1) == 0x37  # the active, unlinked mon is untouched
    assert verify(explode_authority(variant), row) == {"outcome": "benched", "site": "loop_head", "reason": None}
    b = fresh(variant, 1201, 10, "0" * 32)
    load(lua, variant, state(variant, status3=auth.TRANSFORMED, battle_species=0x15, battle_dvs_hex="ffff"), "loop_head")
    arm(lua, b)
    hit_explode(lua, "loop_head")
    run_frame(lua)
    row = finish(lua)
    assert row["writes"] == [] and row["refusal"] == TRANSFORMED_REASON and slots(lua, variant) == SLOTS_BEFORE
    assert verify(b, row) == {"outcome": "refused", "site": "loop_head", "reason": TRANSFORMED_REASON}
    c = fresh(variant, 1202, 11, "1" * 32)
    load(lua, variant, state(variant, action_result=1), "player_action")
    arm(lua, c)
    hit_explode(lua, "player_action")
    run_frame(lua)
    row = finish(lua)
    assert row["writes"] == [] and row["refusal"] == "turn already taken" and bus(lua, addr["wPlayerSelectedMove"]) == 0x21
    assert verify(c, row) == {"outcome": "refused", "site": "player_action", "reason": "turn already taken"}


def test_each_executor_refuses_the_other_bindings_authority_and_the_window_is_one_use(probe):  # noqa: F811
    lua = probe  # the faint executor
    load(lua, "red", state("red"), "loop_head")
    with pytest.raises(Exception, match="for this owner and binding"):
        arm(lua, explode_authority("red"))
    lua.execute("X.close();X=require('battle_force_authority').new({owner_id=string.rep('a',32),held=function()return held end,name='rby-battle-force-explode'})")
    with pytest.raises(Exception, match="for this owner and binding"):
        arm(lua, authority("red"))
    assert lua.eval("X.status().failed") is None and slots(lua, "red") == SLOTS_BEFORE
    a = explode_authority("red", count=5)
    rows = []
    for i in range(3):
        arm(lua, a)
        if i == 2:
            hit_explode(lua, "loop_head")
        run_frame(lua)
        rows.append(finish(lua))
    assert [r["site"] for r in rows] == [None, None, "loop_head"] and [(r["frame"], r["step"]) for r in rows] == [(1200, 9), (1201, 10), (1202, 11)]
    assert slots(lua, "red") == ([0x99] * 4, [5] * 4)
    settled = generic.verify_window(a, rows, verify_row=auth.verify_evidence, hook_frame_offset=OFFSET)
    assert settled == {"covered": [1200, 1202], "outcome": "explode_armed", "row": rows[2]}
    assert json.loads(lua.eval("JSON.encode(X.window_status('" + "f" * 32 + "'))")) == {"covered_from": 1200, "covered_to": 1202, "consumed": True}
    with pytest.raises(Exception, match="already used"):  # consumed: nothing more is stepped under this challenge
        arm(lua, a)
