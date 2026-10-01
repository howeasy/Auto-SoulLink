"""Vanilla Gen 3 wild encounters (clean FireRed/LeafGreen/Emerald) -- CARD WILD-VANILLA.

data/games/gen3_frlge/{firered,leafgreen}_encounters.json and
data/games/gen3_emerald/emerald_encounters.json are generated from pinned pret source by
tools/gen_gen3_wild.py, which reuses Gen3Adapter._rom_encounter_tables -- the same aggregation
the randomized/live-ROM ingest path already uses. Tests that read the pret clone skip by name
when it is absent and fail when it is at another commit (tests/unit/gen3_pret.py); the rest read
committed files only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen3_pret  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_gen3_wild as gen  # noqa: E402

from server.adapters.gen3_frlge import Gen3Adapter  # noqa: E402

FR = json.loads((ROOT / "data/games/gen3_frlge/firered_encounters.json").read_text(encoding="utf-8"))
LG = json.loads((ROOT / "data/games/gen3_frlge/leafgreen_encounters.json").read_text(encoding="utf-8"))
EM = json.loads((ROOT / "data/games/gen3_emerald/emerald_encounters.json").read_text(encoding="utf-8"))


def _pret_firered():
    return gen3_pret.require(gen3_pret.find())


def _pret_emerald():
    return gen3_pret.require_emerald(gen3_pret.find_emerald())


# ── generator determinism ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("game,data,pret", [
    ("firered", FR, _pret_firered), ("leafgreen", LG, _pret_firered), ("emerald", EM, _pret_emerald),
])
def test_generator_check_matches_committed_json(game, data, pret):
    root = pret()
    fresh = gen.dump(gen.build(root, game))
    assert fresh == gen.dump(data), f"{game}_encounters.json is stale: run python tools/gen_gen3_wild.py --game {game}"
    assert data["source"]["commit"] == gen.GAMES[game]["pin"]()


def test_firered_and_leafgreen_report_no_unmapped_maps_except_the_three_known_gaps():
    # Five Island Memorial Pillar, Sevault Canyon entrance, SS Anne exterior: encounters exist in
    # pret but data/games/gen3_frlge/area_map.json has no group:num entry for them. Not invented.
    known = {"fiveislandmemorialpillar", "sevenislandsevaultcanyonentrance", "ssanneexterior"}
    assert set(FR["unmapped_maps"]) == known
    assert set(LG["unmapped_maps"]) == known


def test_emerald_reports_no_unmapped_maps():
    assert EM["unmapped_maps"] == []


# ── pret-grounded spot checks (committed files only) ────────────────────────────────────────

def test_route_1_firered_is_pidgey_and_rattata():
    entries = {e["name"]: e for e in FR["encounters"]["route_1"]["Grass"]}
    assert set(entries) == {"Pidgey", "Rattata"}
    assert entries["Pidgey"]["rate"] == entries["Rattata"]["rate"] == 50


def test_route_4_firered_has_ekans_leafgreen_has_sandshrew():
    # pret pokefirered/src/data/wild_encounters.json: sRoute4_FireRed vs sRoute4_LeafGreen.
    fr_species = {e["name"] for e in FR["encounters"]["route_4"]["Grass"]}
    lg_species = {e["name"] for e in LG["encounters"]["route_4"]["Grass"]}
    assert "Ekans" in fr_species and "Sandshrew" not in fr_species
    assert "Sandshrew" in lg_species and "Ekans" not in lg_species


def test_emerald_route_101_is_wurmple_poochyena_zigzagoon():
    species = {e["name"] for e in EM["encounters"]["route_101"]["Grass"]}
    assert species == {"Wurmple", "Poochyena", "Zigzagoon"}


def test_altering_cave_uses_set_0():
    # sSixIslandAlteringCave_FireRed (unnumbered / first in file order) is all-Zubat; the other
    # 8 sets need VAR_ALTERING_CAVE_WILD_SET, which the display doesn't resolve (matches the
    # randomized-ingest display: test_gen3_emerald_rand.py "the display uses set 0").
    entries = FR["encounters"]["altering_cave"]["Grass"]
    assert {e["name"] for e in entries} == {"Zubat"}


# ── encounter_table() wiring: clean carts, randomized precedence, RR precedence ────────────

def test_clean_firered_returns_the_vanilla_table():
    a = Gen3Adapter(rom_type="firered", artifact_kind="clean")
    assert a.encounter_table("route_1") == FR["encounters"]["route_1"]


def test_clean_leafgreen_returns_leafgreens_own_table():
    a = Gen3Adapter(rom_type="leafgreen", artifact_kind="clean")
    assert a.encounter_table("route_4") == LG["encounters"]["route_4"]


def test_clean_emerald_returns_the_emerald_table():
    a = Gen3Adapter(rom_type="emerald", artifact_kind="clean")
    assert a.encounter_table("route_101") == EM["encounters"]["route_101"]


def test_area_with_no_wild_table_is_none():
    a = Gen3Adapter(rom_type="firered", artifact_kind="clean")
    assert a.encounter_table("oaks_lab") is None


def test_unrand_rand_cart_with_no_ingested_report_shows_nothing():
    # A randomized cart never falls back to the retail table -- same rule as trainer_info's
    # _frlg_trainer_table (retail parties beside a randomized cartridge are misinformation).
    a = Gen3Adapter(rom_type="firered", artifact_kind="rand")
    assert a.encounter_table("route_1") is None


def test_randomized_ingest_still_wins_over_the_vanilla_table():
    a = Gen3Adapter(rom_type="firered", artifact_kind="rand")
    a.use_rom_encounters({"route_1": {"Grass": [{"species_id": 1, "name": "Bulbasaur",
                                                   "rate": 100, "min_level": 5, "max_level": 5}]}})
    assert a.encounter_table("route_1") == {"Grass": [{"species_id": 1, "name": "Bulbasaur",
                                                        "rate": 100, "min_level": 5, "max_level": 5}]}


def test_rr_still_reads_rr_encounters_json_not_the_vanilla_table():
    from server.adapters.gen3_frlge import _RR_ENCOUNTERS

    a = Gen3Adapter(is_rr=True)
    # "route_1" exists in both tables with different content: RR's own (route_1 in RR_ENCOUNTERS
    # is a late-game postgame area, nothing like vanilla FireRed's Pidgey/Rattata) must win.
    assert a.encounter_table("route_1") == _RR_ENCOUNTERS["route_1"]
    assert a.encounter_table("route_1") != FR["encounters"]["route_1"]
