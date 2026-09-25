"""Card gen2-u1e-poison, O-33 fallback (owner-approved 2026-09-25): Gold's Route 31 Bug Catcher Wade leg is a
proven, deterministic LOSS with the driver as written (fsw-postrc-rr9/rr10, identical stall @51461 both
attempts, both party mons end up PSN). gold_synth_psn (tools/gen2_synth_fixtures.py PSN_RECIPES) pins PSN + 8 HP
onto the errand's existing lead (Totodile) AND swaps its 15 POKE_BALLs for 5 MASTER_BALLs (the same swap
trade_evolve already makes): a first attempt that poisoned the lead with its stock Balls left it fighting a
long, multi-throw catch battle poisoned and fainting IN BATTLE (fsw-postrc-psn1, ResidualDamage on the active
battler every turn); a second attempt appended a benched third mon instead, which proved the poison/battle_faint
sites clean but broke the u1f leg's "closing whiteout" -- it needs the WHOLE (2-mon) party at 0 HP, and a
benched extra mon is never the one battle_faint's own driver brings down (fsw-postrc-psn2). MASTER_BALLs make
the catch a single first-throw turn, so the poisoned lead absorbs at most one hit's worth of damage before it
ends, and the party stays at exactly 2 members (Totodile + the one Route 29 catch, same as crystal/silver) all
the way to the closing whiteout. Gold's poison leg boots already poisoned and skips straight to the "tick" phase
(lua/tests/gen2_poison_inputs.lua PI.driver facts.start_phase) on its own Route 29 catch map -- no travel, no
hunt, no Wade. Crystal and Silver are untouched (still the natural wild-Weedle legs).

No emulator: fixture-build reproducibility, the disclosure's exact delta and Gold's leg selection are all
offline/pure checks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.adapters import gen2_codec as codec
from tests.live.test_gen2_frame_align import (
    POISON_HEAL,
    POISON_HUNT,
    POISON_PARK,
    POISON_ROUTE,
    POISON_TRAINER,
    poison_facts,
)
from tools import gen2_duo_oracles as oracles, gen2_source_data, gen2_synth_fixtures as synth

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/fixtures/gen2"
NAME = "gold_synth_psn"


# --- the fixture build -------------------------------------------------------------------------------------------

def test_committed_psn_fixture_is_the_builders_output():
    raw, disclosure = synth.build_named(NAME)
    assert (FIX / f"{NAME}.SaveRAM").read_bytes() == raw
    assert json.loads((FIX / f"{NAME}.synth.json").read_text(encoding="utf-8")) == disclosure
    assert disclosure["base_fixture"] == "gold_battle_errand"


def test_build_named_is_reproducible():
    a, _ = synth.build_named(NAME)
    b, _ = synth.build_named(NAME)
    assert a == b


def test_disclosure_lists_exactly_the_party_status_and_balls_delta():
    _, disclosure = synth.build_named(NAME)
    fields = disclosure["fields"]
    non_checksum = {f["symbol"] for f in fields if f["symbol"] not in ("sChecksum", "sBackupChecksum")}
    assert non_checksum == {"wBalls", "wPartyMon1"}   # wNumBalls stays 1 (one pocket entry either way)
    assert disclosure["edits"] == {"party_status": {"slot": 0, "status": synth.PSN, "hp": 8},
                                   "balls": [["MASTER_BALL", 5]]}
    # exactly the party struct's own MON_STATUS/MON_HP bytes differ inside that one 48-byte record: nothing
    # else (species, moves, DVs, stat exp, level, OT id, exp) moved.
    layout = codec.for_foundation("gold")
    mon1 = next(f for f in fields if f["symbol"] == "wPartyMon1")
    before = codec.decode_party_mon(bytes.fromhex(mon1["old_hex"]), layout, species_marker=bytes.fromhex(mon1["old_hex"])[0])
    after = codec.decode_party_mon(bytes.fromhex(mon1["new_hex"]), layout, species_marker=bytes.fromhex(mon1["new_hex"])[0])
    changed = {k for k in before if k != "raw_hex" and before[k] != after[k]}
    assert changed == {"status", "hp"}
    assert after["status"] == synth.PSN and after["hp"] == 8 and after["max_hp"] == before["max_hp"]


def test_party_stays_at_two_members_lead_plus_one_catch_for_the_closing_whiteout():
    """F.whiteout_problem (lua/tests/gen2_frame_align.lua) requires EVERY party slot at 0 HP; crystal/silver
    reach that because poison_faint + battle_faint together empty their 2-mon party. fsw-postrc-psn2's benched
    third mon broke this (a benched mon is never battle_faint's own target, so the party never fully empties):
    the fixture must add no party member, only touch the existing lone Totodile."""
    raw, _ = synth.build_named(NAME)
    layout = codec.for_foundation("gold")
    party = codec.decode_saved_party(raw[:0x8000], layout, copy_name="primary")["mons"]
    assert len(party) == 1   # the errand's own lone Totodile; the live catch adds the 2nd member
    assert party[0]["species_id"] == 158 and party[0]["status"] == synth.PSN and party[0]["hp"] == 8
    assert party[0]["max_hp"] == 20


def test_party_status_edit_rejects_a_slot_outside_the_party():
    raw = (FIX / "gold_battle_errand.SaveRAM").read_bytes()
    with pytest.raises(ValueError, match="slot outside"):
        synth.build("gold", raw, {"party_status": {"slot": 1, "status": synth.PSN, "hp": 1}})


def test_party_status_edit_rejects_hp_above_max():
    raw = (FIX / "gold_battle_errand.SaveRAM").read_bytes()
    with pytest.raises(ValueError, match="1..the slot's own MON_MAXHP"):
        synth.build("gold", raw, {"party_status": {"slot": 0, "status": synth.PSN, "hp": 99}})


def test_master_balls_replace_the_stock_poke_balls():
    raw, _ = synth.build_named(NAME)
    base_raw = (FIX / "gold_battle_errand.SaveRAM").read_bytes()
    layout = codec.for_foundation("gold")
    items = json.loads((ROOT / "data/games/gen2_gold/items.json").read_text(encoding="utf-8"))["items"]
    master_ball_id = next(int(i) for i, row in items.items() if row["constant"] == "MASTER_BALL")
    poke_ball_id = next(int(i) for i, row in items.items() if row["constant"] == "POKE_BALL")
    assert oracles._ball_pocket(base_raw[:0x8000], layout) == [(poke_ball_id, 15)]   # x15 (O-10), untouched base
    assert oracles._ball_pocket(raw[:0x8000], layout) == [(master_ball_id, 5)]


# --- Gold's leg selection ----------------------------------------------------------------------------------------

def test_gold_no_longer_travels_or_hunts_or_fights_a_trainer():
    assert POISON_ROUTE["gold"] == ()
    assert "gold" not in POISON_TRAINER
    assert "gold" not in POISON_HEAL
    assert POISON_HUNT["gold"] == "Route29" and POISON_PARK["gold"] == ({"x": 53, "y": 11}, {"x": 52, "y": 11})


def test_crystal_and_silver_keep_their_natural_route30_leg():
    for title in ("crystal", "silver"):
        assert POISON_ROUTE[title] and POISON_HUNT[title] == "Route30" and title in POISON_HEAL
        assert title not in POISON_TRAINER


def test_gold_poison_facts_start_in_tick_on_its_own_catch_map():
    ctx = gen2_source_data.load_context("gold", root=ROOT)
    facts = poison_facts(ctx)
    assert facts["start_phase"] == "tick" and facts["hunt_map"] == "Route29"
    assert facts["legs"] == [] and "heal" not in facts and "trainer" not in facts
    # the park pair really is floor on the live map, not just asserted inside poison_facts
    route29 = facts["maps"]["Route29"]
    for tile in facts["park"]:
        assert route29["grid"][tile["y"] * route29["width"] + tile["x"]] == 1


def test_crystal_poison_facts_keep_their_start_phase_unset():
    ctx = gen2_source_data.load_context("crystal", root=ROOT)
    facts = poison_facts(ctx)
    assert "start_phase" not in facts and facts["hunt_map"] == "Route30" and facts["legs"]
