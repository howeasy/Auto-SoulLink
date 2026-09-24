"""gen2_faint_active_trainer's B seed (O-33, coordinator ruling on the final sweep's C-C trainer FAIL): the errand base
with its starter at L10, so the replacement wins the Route 30 trainer fight. MODEL only, no emulator."""
from __future__ import annotations

import json
from pathlib import Path

from server.adapters import gen2_codec as codec
from tools import e2e_duo, gen2_synth_fixtures as synth

FIX = Path(__file__).resolve().parents[2] / "tests/fixtures/gen2"
SEEDS = {"crystal_synth_trainer_ot2": "crystal_battle_ot2_errand", "silver_synth_trainer": "silver_battle_errand"}
TOTODILE, SCRATCH, LEER, RAGE = 158, 10, 43, 99   # constants/pokemon_constants.asm, constants/move_constants.asm


def test_each_seed_is_its_errand_base_with_a_level_ten_starter():
    for name, base in SEEDS.items():
        raw, disclosure = synth.build_named(name)
        assert disclosure["base_fixture"] == base
        layout = codec.for_foundation(name.split("_")[0])
        party = codec.decode_saved_party(raw[:synth.CART], layout, copy_name="primary")["mons"]
        assert [(m["species_id"], m["level"], m["moves"], m["hp"] == m["max_hp"]) for m in party] == \
            [(TOTODILE, 10, [SCRATCH, LEER, RAGE, 0], True)]
        assert raw[synth.CART:] == (FIX / f"{base}.SaveRAM").read_bytes()[synth.CART:]   # the RTC trailer untouched


def test_committed_seeds_are_the_builders_output():
    assert set(synth.TRAINER_FIXTURES) == set(SEEDS)
    for name in SEEDS:
        raw, disclosure = synth.build_named(name)
        assert (FIX / f"{name}.SaveRAM").read_bytes() == raw
        assert json.loads((FIX / f"{name}.synth.json").read_text(encoding="utf-8")) == disclosure


def test_the_runner_stages_the_seed_for_b_only():
    assert e2e_duo.GEN2_TRAINER_FIXTURES == {
        "gen2_new": {"a": "crystal_battle_errand", "b": "crystal_synth_trainer_ot2"},
        "gen2_gold_silver": {"a": "gold_battle_errand", "b": "silver_synth_trainer"}}
    for game, name in (("gen2_new", "crystal_synth_trainer_ot2"), ("gen2_gold_silver", "silver_synth_trainer")):
        rows = e2e_duo.gen2_preflight(game=game, scenario="gen2_faint_active_trainer")
        assert "synth" not in rows["a"] and rows["a"]["name"] == e2e_duo.GEN2_TRAINER_FIXTURES[game]["a"]
        assert rows["b"]["synth"] == name and rows["b"]["name"] == SEEDS[name]   # boots through the PLAYED base
        assert rows["b"]["fixture"] == FIX / f"{name}.SaveRAM"
