"""Card gen2-u1e-poison, O-33 fallback (owner-approved 2026-09-25): Gold's Route 31 Bug Catcher Wade leg is a
proven, deterministic LOSS with the driver as written (fsw-postrc-rr9/rr10, identical stall @51461 both
attempts, both party mons end up PSN). gold_synth_psn (tools/gen2_synth_fixtures.py PSN_RECIPES) appends a
BENCHED Sentret at PSN + 12/18 HP instead of touching the errand's own lead (fsw-postrc-psn1: pinning PSN onto
the lead in place fainted it IN the leg's own Route 29 catch battle -- ResidualDamage hits only the active
battler, C engine/battle/core.asm), so Gold's poison leg boots already poisoned and skips straight to the
"tick" phase (lua/tests/gen2_poison_inputs.lua PI.driver facts.start_phase) on its own Route 29 catch map -- no
travel, no hunt, no Wade. Crystal and Silver are untouched (still the natural wild-Weedle legs).

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
from tools import gen2_source_data, gen2_synth_fixtures as synth

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


def test_disclosure_lists_exactly_the_party_add_delta():
    _, disclosure = synth.build_named(NAME)
    fields = disclosure["fields"]
    non_checksum = {f["symbol"] for f in fields if f["symbol"] not in ("sChecksum", "sBackupChecksum")}
    assert non_checksum == {"wPartyCount", "wPartySpecies", "wPartyMon1", "wPartyMonOTs", "wPartyMonNicknames"}
    assert disclosure["edits"] == {"party_add": [{"species": "SENTRET", "level": 5,
                                                  "moves": ["SCRATCH", "DEFENSE_CURL"], "dvs": 0x4C29,
                                                  "hp": 12, "status": synth.PSN}]}
    # the base's own lead (slot 0) is never touched: its wPartyMon1 bytes do not appear among the changed fields
    mon1 = next(f for f in fields if f["symbol"] == "wPartyMon1")
    assert mon1["offset"] > 0, "the added mon must land after the existing party, never overwrite slot 0"


def test_added_mon_is_the_only_psn_and_the_lead_is_untouched():
    raw, _ = synth.build_named(NAME)
    base_raw = (FIX / "gold_battle_errand.SaveRAM").read_bytes()
    layout = codec.for_foundation("gold")
    base_party = codec.decode_saved_party(base_raw[:0x8000], layout, copy_name="primary")["mons"]
    party = codec.decode_saved_party(raw[:0x8000], layout, copy_name="primary")["mons"]
    assert len(party) == len(base_party) + 1
    psn = [i for i, mon in enumerate(party) if mon["status"] & synth.PSN]
    assert psn == [len(base_party)]   # only the appended mon
    for i, mon in enumerate(base_party):
        assert party[i] == mon, f"slot {i} (the played party) changed"
    added = party[-1]
    assert added["species_id"] == 161 and added["hp"] == 12 and added["max_hp"] == 18   # SENTRET


def test_party_add_rejects_overflowing_the_six_slot_party():
    raw = (FIX / "gold_battle_errand.SaveRAM").read_bytes()
    six = [{"species": "SENTRET", "level": 5, "moves": ["SCRATCH"], "dvs": 0x4C29}] * 6
    with pytest.raises(ValueError, match="1..\\(6 - the current party size\\)"):
        synth.build("gold", raw, {"party_add": six})


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
