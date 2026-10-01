"""Owner ruling 40 (card EMERALD-TOWNS): the six Hoenn towns the Emerald area map never named.

E5-CITYLINK gave Mauville City an area of its own (ruling 28) because it has no wild encounters:
pret's gWildMonHeaders (src/data/wild_encounters.json) lists no encounter map for it, so the wild
loop in tools/gen_area_map.py never named it, and the trainer generator's nearest-area BFS
(tools/gen_gen3_trainers.py::area_of_map) walked straight out of Wattson's gym to Route 110 and
hid the gym trainers inside that route's list. Rustboro, Forttree, Littleroot, Oldale, Fallarbor and
Verdanturf had the identical gap -- the six remaining MAP_TYPE_CITY/TOWN maps in
gMapGroup_TownsAndRoutes that gWildMonHeaders does not cover -- and ruling 40 extends the same
backfill to them.

One test per town, each pinned to pret facts rather than to the pack's own output:

  * the premise: the town's MAP_ id is absent from gWildMonHeaders, which is the whole reason it
    needed a backfill at all;
  * the mapGroup:mapNum key comes from data/maps/map_groups.json order, so a key that drifted out
    of the pack fails here instead of silently pointing at a route;
  * the area_id must equal the MAPSEC display name from
    src/data/region_map/region_map_sections.json, lowercased -- the rule the wild loop already
    uses, so an invented or Kanto-flavoured name fails here;
  * one interior of the town must now RESOLVE to the town through area_of_map()'s BFS. That is
    the defect itself: before the backfill the walk left town and stopped on a route
    (test_gen3_trainers_emerald.py::test_wattson_is_filed_under_mauville_city_not_route_110 is
    the same mechanism for Mauville, ::test_roxanne for Rustboro).

The two gym towns additionally pin the trainers the BFS used to mis-file, including what the
Upcoming Key Trainers panel shows (DATA["trainers_by_area"]), since that list is the consumer the
RC defect was reported through.

Needs the pret/pokeemerald checkout (.cache/pret/pokeemerald); skips when absent, same pattern
as tests/unit/test_gen3_emerald_areas.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools"))

import gen3_pret  # noqa: E402
import gen_area_map as gam  # noqa: E402
import gen_gen3_trainers as gent  # noqa: E402

PACK = ROOT / "data/games/gen3_emerald"
AREA = json.loads((PACK / "area_map.json").read_text(encoding="utf-8"))
DATA = json.loads((PACK / "emerald_trainers.json").read_text(encoding="utf-8"))
TRAINERS = DATA["trainers"]


@pytest.fixture(scope="module")
def pret():
    """The pinned pret/pokeemerald checkout; skips when absent, fails at the wrong commit."""
    return gen3_pret.require_emerald(gen3_pret.find_emerald())


@pytest.fixture(scope="module")
def facts(pret):
    """Everything the town tests check, read from pret once.

    folder -> 'group:num' | MAPSEC | group name | map json, MAPSEC -> display name, the MAP_* ids
    gWildMonHeaders covers, and MAP_* -> area id through the generator's own BFS.
    """
    def load(rel):
        return json.loads((pret / rel).read_text(encoding="utf-8"))

    maps = gent.map_jsons(pret)
    groups = load("data/maps/map_groups.json")
    key_of_folder, mapsec_of_folder, group_of_folder = {}, {}, {}
    for g, gname in enumerate(groups["group_order"]):
        for n, folder in enumerate(groups[gname]):
            key_of_folder[folder] = f"{g}:{n}"
            mapsec_of_folder[folder] = maps[folder]["region_map_section"]
            group_of_folder[folder] = gname
    headers = next(g for g in load("src/data/wild_encounters.json")["wild_encounter_groups"]
                   if g["label"] == "gWildMonHeaders")
    return {
        "key": key_of_folder, "mapsec": mapsec_of_folder, "group": group_of_folder, "maps": maps,
        "towns_and_routes": groups["group_order"][0],
        "name": {s["id"]: s["name"]
                 for s in load("src/data/region_map/region_map_sections.json")["map_sections"]},
        "wild": {e["map"] for e in headers["encounters"]},
        "resolved": gent.area_of_map(maps, gent.map_keys(pret), AREA),
    }


def _snake(display_name: str) -> str:
    """The MAPSEC-display-name -> area_id rule, written out again on purpose: the pack must satisfy
    pret's name, not merely agree with the generator that read it (gen_area_map._mapsec_to_snake)."""
    return re.sub(r"[^A-Za-z0-9]+", "_", display_name).strip("_").lower()


def _town(facts, folder, area_id, interior_map_id):
    """The premise, pret's own key, the MAPSEC name, and the interior that must stop at the town."""
    map_id = facts["maps"][folder]["id"]
    assert map_id not in facts["wild"], f"{folder} ({map_id}) has wild encounters; it needs no backfill"
    key = facts["key"][folder]
    assert AREA.get(key) == area_id, (folder, key, AREA.get(key))
    assert _snake(facts["name"][facts["mapsec"][folder]]) == area_id
    assert facts["resolved"].get(interior_map_id) == area_id, (
        interior_map_id, facts["resolved"].get(interior_map_id))


# ── the two gym towns: the trainers the BFS used to file under a neighbouring route ───────────

def test_rustboro_city_owns_its_gym_and_roxanne(facts):
    # data/maps/RustboroCity/map.json:2,6 -- MAP_RUSTBORO_CITY / MAPSEC_RUSTBORO_CITY;
    # RustboroCity_Gym/map.json:88,95 warps back to the city.
    _town(facts, "RustboroCity", "rustboro_city", "MAP_RUSTBORO_CITY_GYM")
    # RustboroCity_Gym/scripts.inc:5,42,47,52 -- the only trainerbattle rows in the town
    for tid, const in ((265, "TRAINER_ROXANNE_1"), (320, "TRAINER_JOSH"),
                       (321, "TRAINER_TOMMY"), (571, "TRAINER_MARC")):
        assert (TRAINERS[str(tid)]["const"], TRAINERS[str(tid)]["area"]) == (const, "rustboro_city"), tid
    # the Upcoming Key Trainers panel: Roxanne is a key trainer and has left route_104
    assert 265 in DATA["trainers_by_area"]["rustboro_city"]
    assert 265 not in DATA["trainers_by_area"]["route_104"]
    # The Rustboro rival is fought on BOTH maps (Route104/scripts.inc:162 and
    # RustboroCity/scripts.inc:877), and a trainer fought on several maps takes the alphabetically
    # first of their areas (gen_gen3_trainers.py:450) -- so the six rival battles stay on
    # route_104 by that rule, not by oversight. Pinned here so the tie-break is a decision.
    for tid in (592, 593, 599, 600, 768, 769):
        assert TRAINERS[str(tid)]["area"] == "route_104", (tid, TRAINERS[str(tid)]["const"])


def test_fortree_city_owns_its_gym_and_winona(facts):
    # data/maps/FortreeCity/map.json:2,6 -- MAP_FORTREE_CITY / MAPSEC_FORTREE_CITY;
    # FortreeCity_Gym/map.json:127,134 warps back to the city.
    _town(facts, "FortreeCity", "fortree_city", "MAP_FORTREE_CITY_GYM")
    # FortreeCity_Gym/scripts.inc:20,72,77,82,87,92,97 -- the only trainerbattle rows in the town
    for tid, const in ((270, "TRAINER_WINONA_1"), (401, "TRAINER_JARED"), (402, "TRAINER_HUMBERTO"),
                       (404, "TRAINER_EDWARDO"), (654, "TRAINER_FLINT"), (655, "TRAINER_ASHLEY"),
                       (803, "TRAINER_DARIUS")):
        assert (TRAINERS[str(tid)]["const"], TRAINERS[str(tid)]["area"]) == (const, "fortree_city"), tid
    # rematch tiers fight where tier 1 does (gen_gen3_trainers.py:453-459)
    for tid in range(790, 794):
        assert TRAINERS[str(tid)]["area"] == "fortree_city", tid
    assert 270 in DATA["trainers_by_area"]["fortree_city"]
    assert 270 not in DATA["trainers_by_area"]["route_119"]


# ── the four trainer-less towns: the area itself, which the client's lookup missed ──────────────

def test_littleroot_town_is_named(facts):
    # data/maps/LittlerootTown/map.json:2,6 -- MAP_LITTLEROOT_TOWN / MAPSEC_LITTLEROOT_TOWN
    # ("LITTLEROOT TOWN"); LittlerootTown_ProfessorBirchsLab/map.json:107,114 warps to the town.
    # The run's starting town: with no entry the client's first area_enter had nothing to send.
    _town(facts, "LittlerootTown", "littleroot_town", "MAP_LITTLEROOT_TOWN_PROFESSOR_BIRCHS_LAB")


def test_oldale_town_is_named(facts):
    # data/maps/OldaleTown/map.json:2,6 -- MAP_OLDALE_TOWN / MAPSEC_OLDALE_TOWN ("OLDALE TOWN");
    # OldaleTown_PokemonCenter_1F/map.json:76,83 warps to the town. Every Emerald fixture heals
    # here (tests/fixtures/gen3/README.md), so the whiteout landing tile had no area of its own.
    _town(facts, "OldaleTown", "oldale_town", "MAP_OLDALE_TOWN_POKEMON_CENTER_1F")


def test_fallarbor_town_is_named(facts):
    # data/maps/FallarborTown/map.json:2,6 -- MAP_FALLARBOR_TOWN / MAPSEC_FALLARBOR_TOWN
    # ("FALLARBOR TOWN"); FallarborTown_CozmosHouse/map.json:49,56 warps to the town.
    _town(facts, "FallarborTown", "fallarbor_town", "MAP_FALLARBOR_TOWN_COZMOS_HOUSE")


def test_verdanturf_town_is_named(facts):
    # data/maps/VerdanturfTown/map.json:2,6 -- MAP_VERDANTURF_TOWN / MAPSEC_VERDANTURF_TOWN
    # ("VERDANTURF TOWN"); VerdanturfTown_WandasHouse/map.json:88,95 warps to the town.
    _town(facts, "VerdanturfTown", "verdanturf_town", "MAP_VERDANTURF_TOWN_WANDAS_HOUSE")


# ── the ruling's scope: the backfill set, re-derived from pret ────────────────────────────────

def test_the_backfill_covers_every_unnamed_wild_less_town_and_nothing_else(facts):
    """Ruling 28 named Mauville, ruling 40 the other six. Lavaridge was already named in the
    area map; re-derive all wild-less towns from pret so a source update cannot silently drift
    the seven backfilled names or leave a new wild-less town unnamed."""
    derived = {folder for folder, map_json in facts["maps"].items()
               if facts["group"].get(folder) == facts["towns_and_routes"]
               and map_json["map_type"] in ("MAP_TYPE_CITY", "MAP_TYPE_TOWN")
               and map_json["id"] not in facts["wild"]}
    # LavaridgeTown (0:12) was already present before E5-CITYLINK; the tuple lists only the
    # seven names the wild loop and prior special cases left out.
    assert facts["key"]["LavaridgeTown"] == "0:12"
    assert AREA["0:12"] == "lavaridge_town"
    expected = set(gam._EMERALD_WILD_LESS_TOWNS) | {"LavaridgeTown"}
    assert derived == expected, sorted(derived ^ expected)
    # that group is map group 0, so the backfill can never reach a Kanto map, and every town is in
    # the committed pack under pret's own key
    assert all(facts["key"][folder].startswith("0:") for folder in derived)
    assert {AREA[facts["key"][folder]] for folder in derived} == {
        "mauville_city", "rustboro_city", "fortree_city", "littleroot_town", "oldale_town",
        "fallarbor_town", "verdanturf_town", "lavaridge_town"}
