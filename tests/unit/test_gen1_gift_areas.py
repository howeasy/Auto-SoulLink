"""Gift areas must not overlap wild areas, and grants must not share a bucket.

TWO DEFECTS, ONE FAMILY.

**Route 4 was an unlimited free-catch zone.** It sat in both `_GIFT_AREAS` and
`_FIXED_SPECIES_GIFTS` while being a real wild-grass route in all three variants.
The consequences were all silent:

  * `state.py:1104` returns early for gift areas, so Route 4 could never dead-zone;
  * `state.py:1507` sets `is_gift`, so `_check_link_violation` was skipped and the
    species, gender and type clauses did not apply;
  * `state.py:1140` never armed the Pokéball gate there;
  * `gen1_rby_client.lua` never emitted `no_catch` for it.

`test_no_gift_area_is_also_a_wild_area` is a single assertion that would have caught
this at the commit that introduced it.

**Unmapped grant maps collapsed into one shared area.** The client fell back to the
literal area `"gift"` whenever `resolve_area()` returned "", and TWO grant maps were
missing from `area_map.json` — MT_MOON_POKECENTER (map 68, the Magikarp salesman,
`pokered/scripts/MtMoonPokecenter.asm:47`) and CELADON_MANSION_ROOF_HOUSE (map 132,
the Eevee, `scripts/CeladonMansionRoofHouse.asm:15`). Both landed in that one bucket,
so a player's Magikarp could form a Soul Link pair with their partner's Eevee.

Note what is deliberately NOT separated: the two Fighting Dojo choices, and the two
Cinnabar fossils, share a map and therefore share an area id. That is correct — each
is ONE logical event where the two players pick independently, and they are supposed
to pair with each other.
"""
import json
import os

import pytest

from server.adapters.gen1_rby import (
    _FIXED_SPECIES_GIFTS,
    _GIFT_AREAS,
    Gen1Adapter,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AREA_MAP = os.path.join(REPO, "data", "games", "gen1_rby", "area_map.json")
ENCOUNTERS = os.path.join(REPO, "data", "games", "gen1_rby", "encounter_tables.json")


@pytest.fixture
def adapter():
    return Gen1Adapter()


def _areas():
    with open(AREA_MAP, encoding="utf-8") as f:
        return json.load(f)


def _encounters():
    with open(ENCOUNTERS, encoding="utf-8") as f:
        return json.load(f)


# ── the Route 4 class of bug ─────────────────────────────────────────────

@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_no_gift_area_is_also_a_wild_area(variant):
    """The one assertion that would have caught Route 4 at commit time."""
    wild = set(_encounters()[variant])
    overlap = sorted(wild & set(_GIFT_AREAS))
    assert not overlap, (
        f"{variant}: {overlap} are gift areas AND wild-encounter areas. A gift area "
        f"cannot dead-zone, skips every clause and never arms the Pokéball gate, so "
        f"this makes those routes unlimited free-catch zones."
    )


def test_route_4_is_not_a_gift_area(adapter):
    """Named explicitly so a future edit re-adding it fails with the reason."""
    assert not adapter.is_gift_area("route_4")
    assert not adapter.is_fixed_species_gift("route_4")


# ── the coupling that makes the exemption work at all ────────────────────

def test_fixed_species_gifts_are_all_gift_areas():
    """`gift_link_area` leaves an id alone only if it is ALREADY a gift area,
    otherwise it namespaces it to `gift_<area>` — and `is_fixed_species_gift` is
    checked after that rewrite (state.py:1330 then :1507). A member of
    _FIXED_SPECIES_GIFTS that is not also in _GIFT_AREAS silently stops exempting.
    """
    orphans = sorted(_FIXED_SPECIES_GIFTS - _GIFT_AREAS)
    assert not orphans, (
        f"{orphans} are fixed-species gifts but not gift areas, so gift_link_area "
        f"will rename them to gift_<area> and the exemption will never fire")


def test_fixed_species_gift_survives_the_namespace_rewrite(adapter):
    """End-to-end version of the above: the id the server actually checks."""
    for area in sorted(_FIXED_SPECIES_GIFTS):
        linked = adapter.gift_link_area(area)
        assert adapter.is_fixed_species_gift(linked), (
            f"{area!r} becomes {linked!r} after gift_link_area and then no longer "
            f"reads as a fixed-species gift")


# ── the shared-bucket bug ────────────────────────────────────────────────

@pytest.mark.parametrize("map_id,expected", [
    (68, "mt_moon_pokecenter"),      # Magikarp salesman
    (132, "celadon_mansion_roof"),   # Eevee
])
def test_scripted_grant_maps_are_mapped(map_id, expected):
    """An unmapped grant map makes the client fall back to a shared area id."""
    areas = _areas()
    assert str(map_id) in areas, (
        f"map {map_id} is a scripted-grant location and is missing from area_map.json, "
        f"so every grant there collapses into one shared bucket and cross-pairs")
    assert areas[str(map_id)]["area_id"] == expected


def test_the_two_grant_maps_do_not_share_an_area():
    """The concrete symptom: a Magikarp could pair with a partner's Eevee."""
    areas = _areas()
    assert areas["68"]["area_id"] != areas["132"]["area_id"]


def test_grant_maps_are_gift_areas(adapter):
    areas = _areas()
    for map_id in ("68", "132"):
        assert adapter.is_gift_area(areas[map_id]["area_id"])


# ── the client no longer uses a constant fallback ────────────────────────

def test_client_gift_fallback_is_per_map():
    """`area = "gift"` for any unmapped map is what created the shared bucket."""
    path = os.path.join(REPO, "lua", "gen1", "client.lua")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert 'area_id = "gift"' not in src, (
        "lua/gen1/client.lua assigns the bare constant \"gift\" as the area for an unmapped "
        "grant map; distinct events on distinct maps will cross-pair")
    assert '"gift_map_" .. tostring(pc.map)' in src, (
        "expected the per-map gift area fallback (gift_map_<id>)")


def test_per_map_gift_ids_are_gift_areas(adapter):
    """The fallback ids must still be recognised as gifts by the adapter, or the
    grant would be treated as a wild capture and consume an encounter slot."""
    assert adapter.is_gift_area("gift_map_68")
    assert adapter.is_gift_area("gift_map_255")


def test_per_map_gift_ids_are_named_by_their_map(adapter):
    """Live run 2026-09-22: the board showed the starter's area as "Gift Map 40"."""
    from server.adapters.gen1_purergb import Gen1PureRGBAdapter
    for a in (adapter, Gen1PureRGBAdapter()):
        assert a.area_display_name("gift_map_40") == "Oak's Lab — Gift"


# P8-2b: `M.GIFT_AREAS` in lua/games/gen1_rby.lua had no counterpart in the rewritten
# client, which suppresses no_catch on the ENGINE's answer (a battle that never started is
# not an encounter) rather than on a hardcoded area list -- see
# tests/unit/test_gen1_client.py::test_gift_mon_outside_battle_is_a_gift_capture_on_a_gift_area.
# The Python half of the invariant above (no gift area is also a wild area) is unchanged.
