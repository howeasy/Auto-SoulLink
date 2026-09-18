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


def test_purergb_area_map_collapses_three_gift_buildings_into_wild_areas():
    """Named and asserted, not a silent gotcha: unlike vanilla (each gift building gets its
    own area id — "celadon_mansion_roof" is never "celadon_city"), pureRGB's area_map.json
    collapses Celadon Mansion Roof House / Celadon Hotel / Game Corner into "celadon_city",
    the fossil rooms into "cinnabar_island", and Oak's Lab into "pallet_town" — and all
    three of those outdoor buckets carry real wild tables in this pack. The adapter (below)
    must never call one of these three a gift area: doing so would dead-zone real wild grass
    the same way Route 4 briefly did for vanilla (tests/unit/test_gen1_gift_areas.py).
    """
    encounters = json.loads((REPO / "data" / "games" / "gen1_purergb" / "encounter_tables.json")
                            .read_text(encoding="utf-8"))
    wild = {k for k, v in encounters.get("purered", {}).items() if v}
    gift_areas, _ = derive_gift_sets(_gifts("gen1_purergb"), _area_map("gen1_purergb"))
    assert wild & gift_areas == {"celadon_city", "cinnabar_island", "pallet_town"}


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


def test_pure_adapter_recognises_narrative_gift_areas(pure_adapter):
    """Only the gift areas that carry NO wild table of their own are safe to wire live
    (mt_moon_pokecenter, saffron_city, silph_co) -- the three collapsed-with-wild buckets
    (celadon_city, cinnabar_island, pallet_town, previous test) are deliberately withheld."""
    gift_areas, fixed_areas = derive_gift_sets(_gifts("gen1_purergb"), _area_map("gen1_purergb"))
    safe = gift_areas - {"celadon_city", "cinnabar_island", "pallet_town"}
    assert safe == {"mt_moon_pokecenter", "saffron_city", "silph_co"}
    for area in safe:
        assert pure_adapter.is_gift_area(area), f"{area!r} has a gift site but isn't recognised"
    for area in fixed_areas & safe:
        assert pure_adapter.is_fixed_species_gift(area)


def test_pure_adapter_withholds_wild_carrying_collapsed_gift_buildings(pure_adapter):
    for area in ("celadon_city", "cinnabar_island", "pallet_town"):
        assert not pure_adapter.is_gift_area(area), (
            f"{area!r} carries a real wild table in this pack; calling it a gift area "
            f"would dead-zone that wild grass (state.py:_handle_area_enter)")


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
