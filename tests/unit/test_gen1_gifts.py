"""data/games/gen1_*/gifts.json vs the runtime gift tables.

Vanilla's `_GIFT_AREAS`/`_FIXED_GIFTS` (server/adapters/gen1_rby.py) are hand-typed area-id
frozensets with no generator behind them. `tools/gen_gen1_gifts.py` reads the same narrative
grant scripts pret sourced those literals from and re-derives the same two sets from the
per-site facts it finds -- this file is the proof they still agree; it does not change what
Gen1Adapter reads at runtime (that stays the literals, unchanged).

Derivation, spelled out once: a map's gift sites route to one area via area_map.json. An
area is a GIFT area if any site maps into it. It is a FIXED-species gift area if the sites
mapping into it resolve to exactly one distinct KNOWN species (a site with `species: null` --
a choice, or a register-fed reveal like the fossil room -- never counts; two sites with two
different known species, like the two Fighting Dojo rooms or the six Game Corner prizes,
don't either -- the area itself isn't deterministic even though each site is).

`Gen1PureRGBAdapter` has no equivalent literal at all today (docs/purergb/PLAN.md A2): its
`is_gift_area`/`is_fixed_species_gift` are wired to read gifts.json directly (unioned with
the existing static-site check), so this file also covers that the wiring agrees with the
same derivation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.adapters.gen1_purergb import Gen1PureRGBAdapter
from server.adapters.gen1_rby import _FIXED_GIFTS, _GIFT_AREAS

REPO = Path(__file__).resolve().parents[2]


def _gifts(pack: str) -> list[dict]:
    return json.loads((REPO / "data" / "games" / pack / "gifts.json")
                      .read_text(encoding="utf-8"))["gifts"]


def _area_map(pack: str) -> dict[str, str]:
    raw = json.loads((REPO / "data" / "games" / pack / "area_map.json")
                     .read_text(encoding="utf-8"))
    return {k: v["area_id"] for k, v in raw.items()}


def derive_gift_sets(gifts: list[dict], area_by_map: dict[str, str]) -> tuple[set, set]:
    """(gift_areas, fixed_gift_areas), per this file's docstring derivation."""
    species_by_area: dict[str, set[int | None]] = {}
    for g in gifts:
        area = area_by_map[str(g["map_id"])]
        species_by_area.setdefault(area, set())
        species_by_area[area].add(g["species"] if g["fixed_species"] else None)
    gift_areas = set(species_by_area)
    fixed_areas = {area for area, species in species_by_area.items()
                  if species == {next(iter(species))} and next(iter(species)) is not None}
    return gift_areas, fixed_areas


# ── pret: the JSON must reproduce the literals it was derived from ──────────────────────────

def test_pret_gifts_reproduce_the_legacy_frozensets():
    gift_areas, fixed_areas = derive_gift_sets(_gifts("gen1_rby"), _area_map("gen1_rby"))
    assert gift_areas == set(_GIFT_AREAS)
    assert fixed_areas == set(_FIXED_GIFTS)


def test_pret_gifts_have_no_wild_area_overlap():
    """Same invariant test_gen1_gift_areas.py enforces on the literals: a generator bug that
    quietly turned a wild route into a "gift" would dead-zone it and skip every clause."""
    encounters = json.loads((REPO / "data" / "games" / "gen1_rby" / "encounter_tables.json")
                            .read_text(encoding="utf-8"))
    wild = set(encounters["red"])
    gift_areas, _ = derive_gift_sets(_gifts("gen1_rby"), _area_map("gen1_rby"))
    assert not (wild & gift_areas)


@pytest.mark.parametrize("g", _gifts("gen1_rby"), ids=lambda g: g["source"])
def test_pret_gift_species_is_a_national_dex_species_or_a_choice(g):
    if g["species"] is None:
        assert g["natdex"] is None
    else:
        assert 1 <= g["natdex"] <= 151


# ── purergb: no legacy literal to reproduce, but the file must be internally consistent ─────

def test_purergb_gifts_present_and_well_formed():
    gifts = _gifts("gen1_purergb")
    assert len(gifts) == 16
    for g in gifts:
        assert g["kind"] in ("starter", "fossil", "prize", "npc_gift")
        assert isinstance(g["fixed_species"], bool)
        if g["species"] is None:
            assert not g["fixed_species"]


# The seven gift interiors that used to inherit their town's area id, before
# tools/gen_gen1_area_map.py's `gift_building_own_area` rule gave each its own (the same thing
# vanilla does by hand for oaks_lab / celadon_mansion_roof / game_corner).
_GIFT_BUILDING_AREAS = {
    "OAKS_LAB": "oaks_lab",
    "CELADON_MANSION_ROOF_HOUSE": "celadon_mansion_roof_house",
    "GAME_CORNER_PRIZE_ROOM": "game_corner_prize_room",
    "CELADON_HOTEL": "celadon_hotel",
    "CINNABAR_LAB_FOSSIL_ROOM": "cinnabar_lab_fossil_room",
    "FIGHTING_DOJO": "fighting_dojo",
    "FOSSIL_GUYS_HOUSE": "fossil_guys_house",
}


def test_the_pure_gift_areas_carry_no_wild_table():
    """Every gift map's area id is absent from encounter_tables.json — and every key of that file
    carries a real grass/water/fishing table (51 of them), so "absent" means "no wild data at
    all". This is what lets the adapter key gift areas straight off area_map.json: a gift area
    that coincided with a wild area would dead-zone that wild table on the first gift, the same
    way Route 4 briefly did for vanilla (tests/unit/test_gen1_gift_areas.py).

    The generator refuses to emit a map that violates it (tools/gen_gen1_area_map.py rule 3 +
    its overlap check); this pins the committed file.
    """
    encounters = json.loads((REPO / "data" / "games" / "gen1_purergb" / "encounter_tables.json")
                            .read_text(encoding="utf-8"))["purered"]
    wild = {area for area, tables in encounters.items() if any(tables.values())}
    assert len(wild) == 51, f"expected every one of the 51 keys to carry a table, got {sorted(wild)}"
    gift_areas, _ = derive_gift_sets(_gifts("gen1_purergb"), _area_map("gen1_purergb"))
    assert gift_areas & wild == set(), sorted(gift_areas & wild)

    areas = _area_map("gen1_purergb")
    for const, area_id in _GIFT_BUILDING_AREAS.items():
        maps = {str(g["map_id"]) for g in _gifts("gen1_purergb") if g["map_const"] == const}
        assert maps and {areas[m] for m in maps} == {area_id}, (const, maps)


# The exact facts docs/purergb/PLAN.md A2 named, so a re-run against a different pureRGB
# checkout that silently changed a species or level fails here with the specific mismatch.
_EXPECTED_PURERGB = {
    ("OAKS_LAB", None, 5), ("CELADON_MANSION_ROOF_HOUSE", 133, 25),
    ("CELADON_HOTEL", 131, 30), ("SILPH_CO_7F", 131, 40),
    ("CINNABAR_LAB_FOSSIL_ROOM", None, 30), ("FOSSIL_GUYS_HOUSE", None, 24),
    ("FOSSIL_GUYS_HOUSE", 142, 24), ("MT_MOON_POKECENTER", 129, 5),
    ("FIGHTING_DOJO", 106, 30), ("FIGHTING_DOJO", 107, 30),
    ("GAME_CORNER_PRIZE_ROOM", 124, 20), ("GAME_CORNER_PRIZE_ROOM", 125, 20),
    ("GAME_CORNER_PRIZE_ROOM", 114, 20), ("GAME_CORNER_PRIZE_ROOM", 147, 18),
    ("GAME_CORNER_PRIZE_ROOM", 132, 25), ("GAME_CORNER_PRIZE_ROOM", 137, 20),
}


def test_purergb_gifts_match_plan_a2():
    found = {(g["map_const"], g["natdex"], g["level"]) for g in _gifts("gen1_purergb")}
    assert found == _EXPECTED_PURERGB


# ── the pure adapter wiring ──────────────────────────────────────────────────────────────────

@pytest.fixture
def pure_adapter():
    return Gen1PureRGBAdapter(rom_type="PureRed")


def test_pure_adapter_recognises_every_gift_area(pure_adapter):
    """All nine areas a gift site routes into are live now: each gift building has its own id
    and none of them carries a wild table (previous test). The set is pinned so a map change
    cannot quietly add or drop a gift area."""
    gift_areas, fixed_areas = derive_gift_sets(_gifts("gen1_purergb"), _area_map("gen1_purergb"))
    assert gift_areas == {"oaks_lab", "celadon_mansion_roof_house", "game_corner_prize_room",
                          "celadon_hotel", "cinnabar_lab_fossil_room", "fossil_guys_house",
                          "fighting_dojo", "mt_moon_pokecenter", "silph_co"}
    assert fixed_areas == {"celadon_mansion_roof_house", "celadon_hotel", "mt_moon_pokecenter",
                           "silph_co"}
    for area in sorted(gift_areas):
        assert pure_adapter.is_gift_area(area), f"{area!r} has a gift site but isn't recognised"
    for area in sorted(fixed_areas):
        assert pure_adapter.is_fixed_species_gift(area)
    # a choice or a register-fed reveal (Oak's Lab starter, the fossil rooms, the two dojo
    # rooms, the six Game Corner prizes) is a gift area but never a fixed-species one
    for area in sorted(gift_areas - fixed_areas):
        assert not pure_adapter.is_fixed_species_gift(area), area


def test_pure_adapter_never_calls_a_wild_area_a_gift(pure_adapter):
    """The inverse guard, over every wild area rather than the three that used to be affected:
    the towns a gift building stands in (celadon_city, cinnabar_island, pallet_town) keep their
    own wild/fishing tables and must never be gift areas — a gift inside a building no longer
    speaks for the town it stands in (state.py:_handle_area_enter)."""
    encounters = json.loads((REPO / "data" / "games" / "gen1_purergb" / "encounter_tables.json")
                            .read_text(encoding="utf-8"))["purered"]
    for area in sorted(area for area, tables in encounters.items() if any(tables.values())):
        assert not pure_adapter.is_gift_area(area), (
            f"{area!r} carries a real wild/fishing table; calling it a gift area would "
            f"dead-zone it")
        assert not pure_adapter.is_fixed_species_gift(area), area


def test_pure_adapter_still_recognises_static_sites(pure_adapter):
    """The union must not have dropped the pre-existing static-site check."""
    statics = json.loads((REPO / "data" / "games" / "gen1_purergb" / "static_encounters.json")
                         .read_text(encoding="utf-8"))
    map_id, species_list = next(iter(statics["statics"].items()))
    species_pack = json.loads((REPO / "data" / "games" / "gen1_purergb" / "species_index.json")
                              .read_text(encoding="utf-8"))["species"]
    dex = species_pack[str(species_list[0])]["dex"]
    assert pure_adapter.is_gift_area(f"static_{map_id}_{dex}")


def test_pure_adapter_rejects_a_wild_area(pure_adapter):
    assert not pure_adapter.is_gift_area("route_1")
    assert not pure_adapter.is_fixed_species_gift("route_1")
