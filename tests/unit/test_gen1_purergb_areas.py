"""data/games/gen1_purergb/area_map.json + floor_labels.json contract.

Regenerate with `python tools/gen_gen1_area_map.py` (needs SLINK_PURERGB_SRC); these tests read
the committed JSON only, so they run without a pureRGB checkout.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "games" / "gen1_purergb"


def _areas() -> dict:
    return json.loads((DATA / "area_map.json").read_text(encoding="utf-8"))


def _floors() -> dict:
    return json.loads((DATA / "floor_labels.json").read_text(encoding="utf-8"))


def _encounters() -> dict:
    return json.loads((DATA / "encounter_tables.json").read_text(encoding="utf-8"))


def test_all_248_map_ids_present():
    areas = _areas()
    assert len(areas) == 248
    assert set(areas) == {str(i) for i in range(248)}


def test_every_row_has_area_id_and_name():
    for map_id, row in _areas().items():
        assert isinstance(row.get("area_id"), str) and row["area_id"], map_id
        assert isinstance(row.get("name"), str) and row["name"], map_id


# Nine multi-floor buildings collapse to one shared area id each (U10 "vanilla's dungeon
# collapse", read literally against vanilla's own area_map.json which also collapses Pokemon
# Mansion/Cerulean Cave/Rocket Hideout/Silph Co., not only the five U10 names by example).
_COLLAPSE_GROUPS = {
    "mt_moon": [59, 60, 61],                       # 1F, B1F, B2F
    "rock_tunnel": [82, 232],                       # 1F, B1F
    "seafoam_islands": [159, 160, 161, 162, 192],  # B1F..B4F, 1F
    "victory_road": [108, 194, 198],                # 1F, 2F, 3F
    "pokemon_tower": [142, 143, 144, 145, 146, 147, 148, 112],  # 1F..7F, B1F (no own table)
    "pokemon_mansion": [165, 214, 215, 216],        # 1F, 2F, 3F, B1F
    "cerulean_cave": [226, 227, 228],                # 2F, B1F, 1F
    "rocket_hideout": [199, 200, 201, 202, 203],    # B1F..B4F, Elevator
    "silph_co": [181, 207, 208, 209, 210, 211, 212, 213, 233, 234, 235, 236],
}


def test_dungeon_floors_collapse_to_one_area():
    areas = _areas()
    for area_id, map_ids in _COLLAPSE_GROUPS.items():
        got = {areas[str(m)]["area_id"] for m in map_ids}
        assert got == {area_id}, f"{area_id}: floors resolve to {got}, expected all {area_id!r}"


def test_mt_moon_and_rock_tunnel_pokecenters_keep_their_own_area():
    """The rest-stop pokecenter is its OWN area, not folded into an arbitrary floor -- matches
    vanilla's `mt_moon_pokecenter`/`rock_tunnel_pokecenter` rows."""
    areas = _areas()
    assert areas["68"]["area_id"] == "mt_moon_pokecenter"
    assert areas["81"]["area_id"] == "rock_tunnel_pokecenter"
    assert areas["68"]["area_id"] not in _COLLAPSE_GROUPS
    assert areas["81"]["area_id"] not in _COLLAPSE_GROUPS


def test_safari_zone_quadrants_do_not_collapse_into_each_other():
    """U10: Safari quadrants 'stay one area each' -- four distinct ids, not one Safari area."""
    areas = _areas()
    quadrant_map_ids = {"east": 217, "north": 218, "west": 219, "center": 220}
    ids = {q: areas[str(m)]["area_id"] for q, m in quadrant_map_ids.items()}
    assert len(set(ids.values())) == 4, ids
    for q, area_id in ids.items():
        assert area_id == f"safari_zone_{q}", (q, area_id)


def test_bills_garden_is_its_own_area():
    areas = _areas()
    bills_garden = [mid for mid, row in areas.items() if row["area_id"] == "bills_garden"]
    assert bills_garden, "no map resolves to the bills_garden area"
    for area_id in {areas[m]["area_id"] for m in bills_garden}:
        assert area_id == "bills_garden"


def test_floor_labels_only_cover_maps_with_their_own_wild_pointer():
    """Rocket Hideout / Silph Co. floors all point at the shared NothingWildMons sentinel, so
    none of them (nor Pokemon Tower's tableless B1F) earns a floor_labels.json suffix."""
    floors = _floors()
    no_suffix_maps = (_COLLAPSE_GROUPS["rocket_hideout"] + _COLLAPSE_GROUPS["silph_co"] + [112])
    for map_id in no_suffix_maps:
        assert str(map_id) not in floors, f"map {map_id} unexpectedly has a floor suffix"
    # every OTHER member of a >1-floor collapse group does get one
    for area_id, map_ids in _COLLAPSE_GROUPS.items():
        if area_id in ("rocket_hideout", "silph_co"):
            continue
        real_floors = [m for m in map_ids if m != 112]  # exclude pokemon_tower's tableless B1F
        for map_id in real_floors:
            assert str(map_id) in floors, f"{area_id} floor {map_id} has no floor_labels suffix"


def test_sea_routes_areas_carry_missingno():
    """Cinnabar Island / Route 19 / Route 20 share the SeaRoutesWildMons table: all 10 grass
    slots are MISSINGNO L120 (internal id 181, W1 census)."""
    areas = _areas()
    encounters = _encounters()["purered"]
    sea_route_map_ids = [9, 30, 31]  # CINNABAR_ISLAND, ROUTE_19, ROUTE_20
    area_ids = {areas[str(m)]["area_id"] for m in sea_route_map_ids}
    assert area_ids == {"cinnabar_island", "route_19", "route_20"}
    for area_id in area_ids:
        grass = encounters[area_id]["Grass"]
        assert any(e["species_id"] == 181 for e in grass), (
            f"{area_id}: Grass table missing MISSINGNO (internal id 181)")
        missingno = next(e for e in grass if e["species_id"] == 181)
        assert missingno["min_level"] == missingno["max_level"] == 120


def test_area_map_notes_json_is_a_sidecar_not_a_runtime_contract():
    """Every game_knowledge_override the generator kept is auditable, without corrupting
    area_map.json's {"<map_id>": {...}} shape (see the file's own docstring in the README)."""
    notes = json.loads((DATA / "area_map_notes.json").read_text(encoding="utf-8"))
    assert notes["notes"], "expected at least one recorded override"
    for row in notes["notes"]:
        assert set(row) >= {"map_id", "const", "rule", "area_id"}
