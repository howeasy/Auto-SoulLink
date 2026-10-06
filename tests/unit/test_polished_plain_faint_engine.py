"""F0: native Polished faint consumption, on the committed overlay's real bytes.

MODEL only: flat WRAM/HRAM, no banking, interrupts, timing or animation. The
traps below are boundary observers, never implementations of the predicate
under test. Source references are to Polished v3.2.3 (3fa43192): home/battle.asm
230-239, 601-618; engine/battle/core.asm 666-823 and CheckPlayerPartyForFitPkmn.
Absent cached release ROM skips; missing/wrong committed artifacts fail.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from patch.tools.make_ups import ups_apply
from tests.unit.polished_sm83 import SM83

ROOT = Path(__file__).resolve().parents[2]
RELEASE = (Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work"))
           / "cache/polished/release/polishedcrystal-3.2.3.gbc")


@pytest.fixture(scope="module")
def engine():
    if not RELEASE.is_file():
        pytest.skip(f"pinned Polished release ROM absent: {RELEASE}")
    clean = RELEASE.read_bytes()
    lock = json.loads((ROOT / "data/polished_sources.lock.json").read_text())
    assert hashlib.sha1(clean).hexdigest() == lock["outputs"]["polishedcrystal"]["sha1"]
    rom = ups_apply(clean, (ROOT / "patch/dist/SLink-Polished.ups").read_bytes())
    provenance = json.loads((ROOT / "data/polished/overlay_provenance.json").read_text())
    assert hashlib.sha1(rom).hexdigest() == provenance["output"]["sha1"]
    symbols = {name: (int(bank, 16), int(addr, 16)) for bank, addr, name in re.findall(
        r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)$",
        (ROOT / "data/polished/polished_slink.sym").read_text(), re.M)}
    return rom, symbols


def addr(engine, name):
    return engine[1][name][1]


def machine(engine, entry):
    bank, _ = engine[1][entry]
    m = SM83(engine[0], bank=bank or 1,
             hrombank=addr(engine, "hROMBank"))
    # Native farcalls restore the shadow byte, not the mapper's Python value.
    put(m, engine, "hROMBank", bank or 1)
    return m


def trap(m, engine, name, callback):
    bank, pc = engine[1][name]
    m.trap(pc, callback, bank=bank if bank else None)


def put(m, engine, name, value):
    m.poke(addr(engine, name), value)


def run(m, engine, name):
    result = m.call_routine(addr(engine, name))
    assert result.returned and result.sp_delta == 0
    return result


def mutate(m, engine, name, offset, before, after):
    """A pinned local mutation, not a search for an arbitrary matching opcode."""
    bank, pc = engine[1][name]
    flat = pc if bank == 0 else bank * 0x4000 + pc - 0x4000
    assert m.mem.rom[flat + offset:flat + offset + len(before)] == before
    assert len(before) == len(after)
    m.mem.poke_rom(pc + offset, after, bank=bank)


@pytest.mark.parametrize("hp", [b"\0\0", b"\0\1", b"\1\0", b"\xff\xff"],
                         ids=["zero", "low-only", "high-only", "both"])
def test_has_player_fainted_reads_both_hp_bytes(engine, hp):
    m = machine(engine, "HasPlayerFainted")
    put(m, engine, "wBattleMonHP", hp)
    # Contrary party HP prevents accidentally proving a party-mirror predicate.
    put(m, engine, "wPartyMon1HP", b"\xff\xff" if hp == b"\0\0" else b"\0\0")
    result = run(m, engine, "HasPlayerFainted")
    assert result.zf == (hp == b"\0\0"), "HP zero predicate"
    assert not result.writes, "HP predicate must be read-only"


def test_control_or_to_and_breaks_the_hp_oracle(engine):
    m = machine(engine, "HasPlayerFainted")
    # ld hl,HP / ld a,[hli] / or [hl] / ret (home/battle.asm:613-618).
    mutate(m, engine, "HasPlayerFainted", 4, b"\xb6", b"\xa6")
    put(m, engine, "wBattleMonHP", b"\0\1")
    result = run(m, engine, "HasPlayerFainted")
    with pytest.raises(AssertionError, match="HP zero predicate"):
        assert not result.zf, "HP zero predicate"


def perform(engine, hp, *, remove_gate=False):
    m = machine(engine, "PerformMove")
    put(m, engine, "hBattleTurn", 0)  # player is the user
    put(m, engine, "wBattleMonHP", hp)
    put(m, engine, "wEnemyMonHP", b"\x00\x09")
    put(m, engine, "wBattleEnded", 0)
    seen = []
    # Run native battle-variable lookup, HasUserFainted and the actual JR gate.
    # Effects/graphics/ResolveFaints are OUTSIDE this move-gate assertion.
    for name in ("DoTurn", "TickDisableAfterMove", "LoadTileMapToTempTileMap", "ResolveFaints"):
        trap(m, engine, name, lambda _m, n=name: seen.append(n))
    if remove_gate:
        at = addr(engine, "PerformMove.end_protect")
        # farcall DoTurn is four bytes; preceding jr z is two bytes.
        offset = at - addr(engine, "PerformMove") - 6
        target = engine[1]["DoTurn"]
        assert m.mem.peek(at - 4, 4) == bytes((0xD7, target[1] & 255, target[1] >> 8, target[0]))
        mutate(m, engine, "PerformMove", offset, b"\x28\x04", b"\0\0")
    run(m, engine, "PerformMove")
    assert seen.count("ResolveFaints") == 1, "native fallthrough to ResolveFaints"
    assert seen.count("TickDisableAfterMove") == 1
    return seen.count("DoTurn")


@pytest.mark.parametrize("hp,turns", [(b"\0\0", 0), (b"\0\1", 1), (b"\1\0", 1)],
                         ids=["fainted", "alive-low", "alive-high"])
def test_perform_move_skips_only_the_fainted_users_turn(engine, hp, turns):
    assert perform(engine, hp) == turns, "DoTurn reachability"


def test_control_removed_hp_branch_calls_do_turn_for_a_corpse(engine):
    observed = perform(engine, b"\0\0", remove_gate=True)
    assert observed == 1
    with pytest.raises(AssertionError, match="DoTurn reachability"):
        assert observed == 0, "DoTurn reachability"


def resolve_visits(engine, first, *, bypass_selector=False):
    m = machine(engine, "ResolveFaints")
    put(m, engine, "hBattleTurn", 1)
    put(m, engine, "wWhichMonFaintedFirst", first)
    put(m, engine, "wBattleMode", 2)  # trainer, avoids wild victory music
    put(m, engine, "wEnemyMonHP", b"\0\1")
    seen = []
    trap(m, engine, "FaintUserPokemon",
         lambda cpu: seen.append(cpu.peek(addr(engine, "hBattleTurn"))[0]))
    # Scope is branch/order selection, NOT animation/copyback/whole-battle result.
    for name in ("UpdateBattleMonInParty", "UpdateEnemyMonInParty", "ResolveFaints.check_battle_over"):
        trap(m, engine, name, lambda _m: None)
    if bypass_selector:
        # ldh a,[turn]; push af; ld a,[first]; and a; jr z,.no_fainted_mons.
        offset = 7
        delta = addr(engine, "ResolveFaints.no_fainted_mons") - (addr(engine, "ResolveFaints") + offset + 2)
        mutate(m, engine, "ResolveFaints", offset, bytes((0x28, delta)), b"\0\0")
    run(m, engine, "ResolveFaints")
    assert m.peek(addr(engine, "hBattleTurn"))[0] == 1, "turn restored"
    assert m.peek(addr(engine, "wWhichMonFaintedFirst"))[0] == 0, "native flag reset"
    return seen


@pytest.mark.parametrize("first,expected", [(0, []), (1, [0, 1]), (2, [1, 0])],
                         ids=["no-pending", "player-first", "enemy-first"])
def test_resolve_faints_selects_native_faint_branches(engine, first, expected):
    assert resolve_visits(engine, first) == expected, "faint branch/order"


def test_control_bypassed_selector_invalidates_no_pending_oracle(engine):
    seen = resolve_visits(engine, 0, bypass_selector=True)
    assert len(seen) == 2
    with pytest.raises(AssertionError, match="faint branch/order"):
        assert seen == [], "faint branch/order"


def copyback(engine, slot, *, extend=False):
    m = machine(engine, "UpdateBattleMonInParty")
    stride = addr(engine, "wPartyMon2") - addr(engine, "wPartyMon1")
    assert stride == 48
    source = addr(engine, "wBattleMonLevel")
    size = addr(engine, "wBattleMonMaxHP") - source
    assert size == 5  # Level, Status, Unused, HP high, HP low; excludes MaxHP.
    start = addr(engine, "wPartyMon1")
    block = bytes((i * 17 + 11) & 255 for i in range(6 * stride))
    m.poke(start, block)
    payload = bytes((37, 8, 0xA7, 1, 0x23, 0xEE, 0xDD))
    m.poke(source, payload)
    put(m, engine, "wCurBattleMon", slot)
    put(m, engine, "wCurPartyMon", (slot + 1) % 6)  # wrong scratch index must be ignored
    if extend:
        # Native ld bc,5 immediately before rst CopyBytes and ret.
        end = addr(engine, "UpdateEnemyMonInParty")
        mutate(m, engine, "UpdateBattleMonInParty", end - addr(engine, "UpdateBattleMonInParty") - 5,
               b"\x01\x05\x00\xe7\xc9", b"\x01\x06\x00\xe7\xc9")
    result = run(m, engine, "UpdateBattleMonInParty")
    dst = addr(engine, "wPartyMon1Level") + slot * stride
    want = bytearray(block)
    want[dst - start:dst - start + size] = payload[:size]
    assert m.peek(source, len(payload)) == payload, "battle source unchanged"
    return m, result, start, bytes(want), dst, size


@pytest.mark.parametrize("slot", [0, 2, 5], ids=["first", "middle", "last"])
def test_copyback_updates_only_active_level_status_unused_hp(engine, slot):
    m, result, start, want, dst, size = copyback(engine, slot)
    assert m.peek(start, len(want)) == want, "exact party copyback"
    party_writes = [(a, v) for _, a, v in result.writes if start <= a < start + len(want)]
    assert party_writes == list(zip(range(dst, dst + size), m.peek(dst, size), strict=True))


def test_control_extended_copyback_clobbers_maxhp(engine):
    m, _, start, want, _, _ = copyback(engine, 2, extend=True)
    with pytest.raises(AssertionError, match="exact party copyback"):
        assert m.peek(start, len(want)) == want, "exact party copyback"


@pytest.mark.parametrize("hps,fit", [([0], False), ([1], True), ([256], True), ([0, 1], True),
                                    ([0, 0], False)],
                         ids=["last-fainted", "last-alive-low", "last-alive-high", "bench-survivor", "all-fainted"])
def test_native_party_fitness_uses_actual_party_hp(engine, hps, fit):
    m = machine(engine, "CheckPlayerPartyForFitPkmn")
    put(m, engine, "wPartyCount", len(hps))
    stride = addr(engine, "wPartyMon2") - addr(engine, "wPartyMon1")
    for slot, hp in enumerate(hps):
        m.poke(addr(engine, "wPartyMon1HP") + slot * stride, hp.to_bytes(2, "big"))
    # Active battle mirror is deliberately contrary: this routine reads party HP.
    put(m, engine, "wBattleMonHP", b"\0\1" if not fit else b"\0\0")
    result = run(m, engine, "CheckPlayerPartyForFitPkmn")
    assert (result.d != 0) == fit, "party fitness"


def loss_decision(engine, hps, mode, enemy_hp, *, bypass_fitness=False):
    m = machine(engine, "ResolveFaints.check_battle_over")
    put(m, engine, "wPartyCount", len(hps))
    stride = addr(engine, "wPartyMon2") - addr(engine, "wPartyMon1")
    for slot, hp in enumerate(hps):
        m.poke(addr(engine, "wPartyMon1HP") + slot * stride, hp.to_bytes(2, "big"))
    put(m, engine, "wBattleMode", mode)
    put(m, engine, "wEnemyMonHP", enemy_hp.to_bytes(2, "big"))
    put(m, engine, "wLinkMode", 0)
    put(m, engine, "wInBattleTowerBattle", 0)
    put(m, engine, "wBattleResult", 0xC0)
    calls = []
    # Only observe entering LostBattle; fitness and decision instructions are REAL.
    trap(m, engine, "LostBattle", lambda _m: calls.append("lost"))
    if bypass_fitness:
        # call fitness / ld a,d / and a / jr nz,.player_not_out.
        name = "ResolveFaints.check_battle_over"
        delta = addr(engine, "ResolveFaints.player_not_out") - (addr(engine, name) + 7)
        mutate(m, engine, name, 5, bytes((0x20, delta)), bytes((0x18, delta)))
    result = run(m, engine, "ResolveFaints.check_battle_over")
    return calls, m.peek(addr(engine, "wBattleResult"))[0], result


def assert_loss_decision(observed, lost):
    calls, battle_result, result = observed
    assert calls == (["lost"] if lost else []), "native loss decision"
    assert battle_result == (0xC1 if lost else 0xC0)
    if lost:
        assert result.cf


@pytest.mark.parametrize("hps,mode,enemy_hp,lost", [([0], 1, 1, True), ([0], 2, 1, True),
                                                    ([0, 1], 2, 1, False), ([0], 1, 0, True)],
                         ids=["wild-last", "trainer-last", "bench-survives", "wild-draw-is-loss"])
def test_native_last_party_loss_decision_not_the_lostbattle_body(engine, hps, mode, enemy_hp, lost):
    assert_loss_decision(loss_decision(engine, hps, mode, enemy_hp), lost)


def test_control_bypassed_fitness_branch_invalidates_last_mon_loss(engine):
    observed = loss_decision(engine, [0], 2, 1, bypass_fitness=True)
    assert observed[0] == []
    with pytest.raises(AssertionError, match="native loss decision"):
        assert_loss_decision(observed, True)


def test_full_faint_animation_whiteout_and_switch_are_not_model_proof():
    pytest.skip("MODEL-CANNOT: flat-memory SM83 has no WRAM/SRAM banking, interrupts, "
                "video/audio or timing; native animation, complete whiteout and switch lifecycle need live battle evidence")
