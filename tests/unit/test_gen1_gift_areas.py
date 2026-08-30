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
import re

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
    path = os.path.join(REPO, "lua", "clients", "gen1_rby_client.lua")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert 'area = "gift"' not in src.replace('or "gift"', ""), (
        "gen1_rby_client.lua still assigns the bare constant \"gift\" as the area for "
        "an unmapped grant map; distinct events on distinct maps will cross-pair")
    assert "gift_map_%d" in src, (
        "expected the per-map gift area fallback (gift_map_<id>)")


def test_per_map_gift_ids_are_gift_areas(adapter):
    """The fallback ids must still be recognised as gifts by the adapter, or the
    grant would be treated as a wild capture and consume an encounter slot."""
    assert adapter.is_gift_area("gift_map_68")
    assert adapter.is_gift_area("gift_map_255")


# ── the two halves of the gift set must agree ────────────────────────────

def _lua_gift_areas():
    """Parse M.GIFT_AREAS out of lua/games/gen1_rby.lua.

    A parse, not an import: lupa is optional in this suite and a missing runtime would
    turn this into a skip, which reads exactly like a pass.
    """
    path = os.path.join(REPO, "lua", "games", "gen1_rby.lua")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"M\.GIFT_AREAS\s*=\s*\{(.*?)\n\}", src, re.S)
    assert m, "M.GIFT_AREAS not found in lua/games/gen1_rby.lua"
    return set(re.findall(r"^\s*(\w+)\s*=\s*true", m.group(1), re.M))


def test_the_lua_and_python_gift_sets_are_identical():
    """They enforce two halves of one rule and they silently drifted apart.

    Python's set drives dead-zoning, the ball gate and the clauses. The Lua set decides
    whether the client emits `no_catch` at all -- and `no_catch` is the ONLY producer of
    that event; nothing server-side generates one. So an area listed as a gift in Lua but
    not in Python can never dead-zone, however the Python side is configured.

    That is exactly what happened to route_4: removed from Python as the real grass route
    it is, left behind in Lua, and therefore re-attemptable forever with no test able to
    see it.
    """
    assert _lua_gift_areas() == set(_GIFT_AREAS), (
        "lua/games/gen1_rby.lua M.GIFT_AREAS and server/adapters/gen1_rby.py _GIFT_AREAS "
        "must list the same areas")


def test_no_lua_gift_area_is_a_wild_encounter_area():
    """The same invariant the Python set already has, applied to the half that
    actually suppresses no_catch."""
    with open(os.path.join(REPO, "data", "games", "gen1_rby",
                           "encounter_tables.json"), encoding="utf-8") as f:
        tables = json.load(f)
    lua_gifts = _lua_gift_areas()
    for variant, areas in tables.items():
        overlap = lua_gifts & set(areas)
        assert not overlap, (
            f"{variant}: {sorted(overlap)} are wild encounter areas but the Lua gift set "
            f"suppresses no_catch there, so they can never dead-zone")
