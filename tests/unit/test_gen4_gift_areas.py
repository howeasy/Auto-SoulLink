"""Gen 4 (HGSS) gift areas -- the derived pack fact behind the client's `no_catch` exemption.

tools/gen_gen4_area_map.py emits `gift_areas` in data/games/gen4_hgss/area_map.json: the areas a
scripted starter/gift/egg/loan reaches where NO map in the area owns a wildEncounterBank. The client
drops `no_catch` for an area in `ids` (lua/gen4/poll_events.lua:415-418), so a list that covered a
route would swallow a genuine failed encounter.

Two independent checks live here on purpose:
  * the COMMITTED file, re-derived from locations.json's own `enc_bank` column -- a different parse
    (tools/gen_gen4_encounters / the locations block) from the one that produced the list, so this is
    not the generator agreeing with itself;
  * the GENERATOR, against the pinned pret/pokeheartgold clone: absent skips BY NAME, wrong commit
    FAILS (tests/unit/test_gen4_data_tools.py's convention).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen4_pins  # noqa: E402
import gen_gen4_area_map as base  # noqa: E402

DATA = ROOT / "data" / "games" / "gen4_hgss"
PIN = gen4_pins.SOURCE_COMMITS["pokeheartgold_citation"]

# The pinned pret's answer, written down so a silent re-derivation cannot slip through unnoticed, and
# read off data/games/gen4_hgss/locations.json's own `enc_bank` column -- an INDEPENDENT parse from the
# map_headers.h rows the generator used. Note what is NOT here: five of the areas a gift site sits in
# (new_bark_town 60/T20, pallet_town 49/T01, celadon_city 55/T07, cianwood_city 75/T24, violet_city
# 73/T22) own a wild-encounter map, so the split sends them to `on_wild_area` even though the site that
# found them is an interior with no bank of its own. The client exempts by AREA, so a wildcard in one
# interior would silence a real no_catch on the town's grass.
EXPECTED_IDS = {"goldenrod_city", "pewter_city", "saffron_city", "sinjoh_ruins"}
EXPECTED_ON_WILD = {
    "61": "new_bark_town", "101": "route_35", "117": "ilex_forest", "157": "violet_city",
    "158": "violet_city", "232": "cianwood_city", "236": "cianwood_city", "252": "mt_mortar",
    "288": "dragons_den", "382": "celadon_city", "505": "pallet_town",
}


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def clone() -> Path:
    try:
        path = base.locate_clone()
    except base.PretAbsent as exc:
        pytest.skip(f"pret/pokeheartgold @ {PIN[:8]} not available: {exc}")
    try:
        base.verify_clone(path)
    except base.PretMismatch as exc:
        pytest.fail(str(exc))
    return path


# -- the committed block, re-derived from locations.json's own enc_bank column -------------------
def test_the_shipped_gift_ids_and_the_on_wild_ones_are_the_derived_pair():
    block = load("area_map.json")["gift_areas"]
    assert set(block["ids"]) == EXPECTED_IDS
    assert block["on_wild_area"] == EXPECTED_ON_WILD


def test_every_shipped_gift_id_has_no_wild_encounter_map_anywhere_in_its_area():
    """enc_bank is read from locations.json, a DIFFERENT parse from the map_headers.h rows the list
    was derived from -- so a genuine wild map inside a listed area would show up here."""
    area_map, locs = load("area_map.json"), load("locations.json")
    for aid in area_map["gift_areas"]["ids"]:
        area = area_map["areas"][aid]
        wild = [m for m in area["maps"] + area["unused_maps"] if locs["locations"][str(m)]["enc_bank"]]
        assert wild == [], f"gift area {aid} owns wild-encounter maps {wild}"


def test_the_two_sides_partition_the_sites_and_the_rule_says_why():
    block = load("area_map.json")["gift_areas"]
    sites, on_wild = block["sites"], block["on_wild_area"]
    assert set(on_wild) <= set(sites), "an excluded site must still be a site the pack placed"
    assert {sites[m] for m in sites} == set(block["ids"]) | set(on_wild.values())
    assert set(on_wild.values()).isdisjoint(block["ids"]), "an area cannot be both sides of the split"
    assert "wildEncounterBank" in load("area_map.json")["rules"]["gift_areas"]
    assert block["acquisition"]["generator"] == "tools/gen_gen4_acquisition.py"


def test_the_daycare_egg_is_named_as_a_gift_catch_the_pack_cannot_place_on_a_map():
    """GiveDaycareEgg really is a gift catch (O-15) but is not a script_site, so it carries no map id
    and cannot reach `ids`. The file must say so by name rather than lose the fact silently -- and
    every site it DOES record must be keyed by a real map id, or the daycare would have to be one."""
    block = load("area_map.json")["gift_areas"]
    daycare = block["no_map_commands"]["GiveDaycareEgg"]
    assert daycare["sites"] == ["scr_seq_0265.s:101"] and "gift catch" in daycare["why"]
    assert all(k.isdigit() for k in block["sites"]), "every recorded gift site is placed on a map"


def test_the_pack_states_which_kinds_the_list_was_built_from():
    """zone_policy is the pack's own table, so the emitted kinds must be exactly its gift-zone kinds
    minus `static` -- a static is a WildBattle and must never be exempted from no_catch."""
    kinds = load("area_map.json")["gift_areas"]["acquisition"]["kinds"]
    assert set(kinds) == {"egg", "gift", "loan", "special_gift", "starter"}
    assert "static" not in kinds
    policy = load("acquisition.json")["zone_policy"]
    assert {k for k, v in policy.items() if v["zone"] == "gift"} - {"static"} == set(kinds)


# -- the fail-closed guard ----------------------------------------------------------------------
def _model(areas: dict[str, list[int]], banks: dict[int, str | None]):
    rows = {mid: {"enc_bank": bank} for mid, bank in banks.items()}
    return {"maps": SimpleNamespace(rows=rows),
            "areas": {aid: {"maps": ms, "unused_maps": []} for aid, ms in areas.items()}}


def test_the_guard_refuses_a_gift_area_that_covers_a_wild_encounter_map():
    """The whole point of the split, asserted directly: an area in `ids` that owns a wild map must
    RAISE rather than ship, because the client would drop a real no_catch there."""
    model = _model({"route_1": [1], "pallet_town": [2]}, {1: "GRASS", 2: None})
    with pytest.raises(base.GiftAreaOnWildMap, match="wild-encounter maps"):
        base.check_gift_ids(model, {"route_1", "pallet_town"})
    base.check_gift_ids(model, {"pallet_town"})            # the wild-less half is fine


def test_the_shipped_area_map_drives_the_shipped_producer():
    """End to end over the REAL files, no scratch pack: lua/gen4/inputs.lua's gift_area reads the very
    area_map.json this test just derived, so the list the generator writes is the list the client
    gets. A generator output the producer cannot read would be a silent run-wide dead-zone regression."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.ROOT_DIR, g.PROFILE = ROOT.as_posix(), "data/games/gen4_hgss/profile.json"
    lua.execute("""
        JSON = assert(dofile(ROOT_DIR .. "/lua/json_codec.lua"))
        INPUTS = assert(dofile(ROOT_DIR .. "/lua/gen4/inputs.lua"))
        gift, WHY = INPUTS.gift_area({ root = ROOT_DIR, json = JSON, pack_profile = PROFILE })
    """)
    assert g.gift is not None, f"the shipped pack refused its own gift list: {g.WHY}"
    ids = load("area_map.json")["gift_areas"]["ids"]
    assert [a for a in ids if g.gift(a) is not True] == [], ids
    assert g.gift("route_1") is False and g.gift("") is False


def test_the_derivation_sends_a_wild_area_to_on_wild_instead_of_raising():
    """The split itself, on a synthetic pack: a gift site in a wild area lands in on_wild_area and
    never in ids, so the guard above is a backstop and not the ordinary path."""
    model = _model({"route_1": [1], "pallet_town": [2]}, {1: "GRASS", 2: None})
    acq = {"zone_policy": {"gift": {"zone": "gift"}, "starter": {"zone": "gift"},
                           "static": {"zone": "gift"}, "roamer": {"zone": "roamer"}},
           "script_sites": [
               {"id": "a", "kind": "gift", "map_id": 1, "area": "route_1"},
               {"id": "b", "kind": "starter", "map_id": 2, "area": "pallet_town"},
               {"id": "c", "kind": "static", "map_id": 2, "area": "pallet_town"},
               {"id": "d", "kind": "roamer", "map_id": 1, "area": "route_1"},
           ]}
    block = base.gift_areas(model, acq)
    assert block["ids"] == ["pallet_town"] and block["on_wild_area"] == {"1": "route_1"}
    assert block["sites"] == {"1": "route_1", "2": "pallet_town"}, "roamer and static are not gift sites"
    base.check_gift_ids(model, block["ids"])


def test_a_second_site_in_the_same_area_does_not_flip_the_split():
    model = _model({"route_1": [1, 3]}, {1: "GRASS", 3: None})
    acq = {"zone_policy": {"gift": {"zone": "gift"}}, "script_sites": [
        {"id": "a", "kind": "gift", "map_id": 3, "area": "route_1"},
        {"id": "b", "kind": "gift", "map_id": 1, "area": "route_1"},
    ]}
    block = base.gift_areas(model, acq)
    assert block["ids"] == [] and block["on_wild_area"] == {"1": "route_1", "3": "route_1"}, \
        "the answer is a property of the AREA: a non-wild map in it does not buy an exemption"


def test_a_missing_acquisition_inventory_fails_rather_than_shipping_an_empty_list(tmp_path):
    """No evidence for which areas a scripted catch reaches is a FAIL, not a silent empty list: an
    empty `ids` would look exactly like the deliberate "no area is exempt" answer."""
    with pytest.raises(base.AcquisitionAbsent, match="acquisition.json"):
        base.load_acquisition(tmp_path / "acquisition.json")


def test_a_zone_policy_without_a_gift_kind_is_refused_rather_than_read_as_no_gift_areas():
    acq = {"zone_policy": {"wild": {"zone": "area"}, "roamer": {"zone": "roamer"}}, "script_sites": []}
    with pytest.raises(base.AcquisitionAbsent, match="no gift-zone kind"):
        base.gift_areas(_model({}, {}), acq)


# -- the generator, against the pinned clone -----------------------------------------------------
def test_the_generator_reproduces_the_committed_gift_block(clone):
    """Absent clone skips above; a clone at the wrong commit fails there. `--check` must agree."""
    produced = json.loads(base.build(clone)["area_map.json"])
    assert produced["gift_areas"] == load("area_map.json")["gift_areas"]


def test_the_generator_reads_the_pack_inventory_not_a_literal(clone):
    """A generator that hardcoded the nine ids would pass the test above on this pin and be wrong on
    the next one; move a gift site and the derivation has to move with it."""
    acq = load("acquisition.json")
    kinds = base.gift_kinds(acq)
    assert kinds and kinds <= set(acq["zone_policy"])
    assert all(acq["zone_policy"][k]["zone"] == "gift" and k != "static" for k in kinds)
