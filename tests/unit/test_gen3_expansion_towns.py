"""Owner ruling 40 for the expansion build (card EXP-TOWNS): the seven Hoenn towns that have no
wild encounters of their own must be NAMED areas in data/games/gen3_exp/28877d73/area_map.json.

Same defect and same fix as the Emerald pack (tests/unit/test_gen3_emerald_towns.py,
tools/gen_area_map.py _EMERALD_WILD_LESS_TOWNS / E5-CITYLINK). Unnamed, the trainer generator's
nearest-area BFS (tools/gen_gen3_trainers.py::area_of_map) walks out of the town and files the gym
under a neighbouring route -- Roxanne under route_104, Wattson under route_110, Winona under
route_119 -- so the Rustboro / Mauville / Fortree trainer panels rendered with no trainers and
the calc Prep deep link had nothing to attach to (trainer panels are RC-mandatory).

Every fact is read from the pinned expansion checkout (SLINK_EXPANSION_SRC, e8bd1cd7), not from
the pack's own output. Skips when the checkout is absent; fails if it is at the wrong commit.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gen_area_map as gam  # noqa: E402
import gen_gen3_trainers as gent  # noqa: E402

PACK = ROOT / "data/games/gen3_exp/28877d73"
AREA = json.loads((PACK / "area_map.json").read_text(encoding="utf-8"))
DATA = json.loads((PACK / "gen3_exp_trainers.json").read_text(encoding="utf-8"))
TRAINERS = DATA["trainers"]
_PIN = json.loads((ROOT / "data/gen3_exp_sources.lock.json").read_text(encoding="utf-8"))["source"]["commit"]


@pytest.fixture(scope="module")
def src():
    env = os.environ.get("SLINK_EXPANSION_SRC")
    if not env or not Path(env).is_dir():
        pytest.skip(f"pokeemerald-expansion checkout not found (set SLINK_EXPANSION_SRC; pin {_PIN})")
    head = subprocess.run(["git", "-C", env, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert head == _PIN, f"{env} is at {head}, not the pin {_PIN}"
    return Path(env)


@pytest.fixture(scope="module")
def facts(src):
    def load(rel):
        return json.loads((src / rel).read_text(encoding="utf-8"))

    keys = gent.map_keys(src)
    # orphan maps (not in map_groups.json) have no key; area_of_map indexes keys[] for every map
    maps = {n: m for n, m in gent.map_jsons(src).items() if m["id"] in keys}
    groups = load("data/maps/map_groups.json")
    key_of_folder, group_of_folder = {}, {}
    for g, gname in enumerate(groups["group_order"]):
        for n, folder in enumerate(groups[gname]):
            key_of_folder[folder] = f"{g}:{n}"
            group_of_folder[folder] = gname
    headers = next(g for g in load("src/data/wild_encounters.json")["wild_encounter_groups"]
                   if g["label"] == "gWildMonHeaders")
    return {
        "key": key_of_folder, "group": group_of_folder, "maps": maps,
        "towns_and_routes": groups["group_order"][0],
        "name": {s["id"]: s.get("name")
                 for s in load("src/data/region_map/region_map_sections.json")["map_sections"]},
        "wild": {e["map"] for e in headers["encounters"]},
        "resolved": gent.area_of_map(maps, keys, AREA),
    }


def _snake(display_name: str) -> str:
    # the MAPSEC display name -> area_id rule, written out again on purpose (see the Emerald twin)
    return re.sub(r"[^A-Za-z0-9]+", "_", display_name).strip("_").lower()


def _town(facts, folder, area_id, key, interior_map_id):
    """Premise (no wild header), pret key, MAPSEC name, and an interior that must stop at the town."""
    m = facts["maps"][folder]
    assert m["id"] not in facts["wild"], f"{folder} has wild encounters; it needs no backfill"
    assert facts["key"][folder] == key
    assert AREA.get(key) == area_id, (folder, key, AREA.get(key))
    assert _snake(facts["name"][m["region_map_section"]]) == area_id
    assert facts["resolved"].get(interior_map_id) == area_id, (interior_map_id, facts["resolved"].get(interior_map_id))


def _areas(consts):
    by = {t["const"]: t.get("area") for t in TRAINERS.values()}
    return {c: by[c] for c in consts}


def test_rustboro_city_owns_its_gym_and_roxanne(facts):
    # data/maps/RustboroCity/map.json id MAP_RUSTBORO_CITY, group 0 index 3 (map_groups.json);
    # RustboroCity_Gym/scripts.inc:5,42,47,52 are the town's only trainerbattle rows.
    _town(facts, "RustboroCity", "rustboro_city", "0:3", "MAP_RUSTBORO_CITY_GYM")
    assert set(_areas(["TRAINER_ROXANNE_1", "TRAINER_JOSH", "TRAINER_TOMMY", "TRAINER_MARC",
                       "TRAINER_ROXANNE_2", "TRAINER_ROXANNE_5"]).values()) == {"rustboro_city"}
    assert 265 in DATA["trainers_by_area"]["rustboro_city"]
    assert 265 not in DATA["trainers_by_area"]["route_104"]


def test_mauville_city_owns_its_gym_and_wattson(facts):
    # MauvilleCity_Gym/scripts.inc:77,200,205,210,215,220 (Wattson, Kirk, Shawn, Ben, Vivian, Angelo);
    # rematches via trainerbattle_rematch_double at scripts.inc:135.
    _town(facts, "MauvilleCity", "mauville_city", "0:2", "MAP_MAUVILLE_CITY_GYM")
    consts = ["TRAINER_WATTSON_1", "TRAINER_WATTSON_5", "TRAINER_KIRK", "TRAINER_SHAWN",
              "TRAINER_BEN", "TRAINER_VIVIAN", "TRAINER_ANGELO"]
    assert set(_areas(consts).values()) == {"mauville_city"}
    assert 267 in DATA["trainers_by_area"]["mauville_city"]
    assert 267 not in DATA["trainers_by_area"]["route_110"]


def test_fortree_city_owns_its_gym_and_winona(facts):
    # FortreeCity_Gym/scripts.inc:21,68,73-98 (Winona, Jared, Edwardo, Flint, Ashley, Humberto, Darius)
    _town(facts, "FortreeCity", "fortree_city", "0:4", "MAP_FORTREE_CITY_GYM")
    consts = ["TRAINER_WINONA_1", "TRAINER_WINONA_5", "TRAINER_JARED", "TRAINER_EDWARDO",
              "TRAINER_FLINT", "TRAINER_ASHLEY", "TRAINER_HUMBERTO", "TRAINER_DARIUS"]
    assert set(_areas(consts).values()) == {"fortree_city"}
    assert 270 in DATA["trainers_by_area"]["fortree_city"]
    assert 270 not in DATA["trainers_by_area"]["route_119"]


@pytest.mark.parametrize("folder,area_id,key,interior", [
    # LittlerootTown_ProfessorBirchsLab is already a named gift area (EXP-GIFT-AREAS), so use the
    # house interior that is not in _EXP_GIFT_FOLDERS
    ("LittlerootTown", "littleroot_town", "0:9", "MAP_LITTLEROOT_TOWN_BRENDANS_HOUSE_1F"),
    ("OldaleTown", "oldale_town", "0:10", "MAP_OLDALE_TOWN_POKEMON_CENTER_1F"),
    ("FallarborTown", "fallarbor_town", "0:13", "MAP_FALLARBOR_TOWN_COZMOS_HOUSE"),
    ("VerdanturfTown", "verdanturf_town", "0:14", "MAP_VERDANTURF_TOWN_WANDAS_HOUSE"),
])
def test_trainerless_towns_are_named(facts, folder, area_id, key, interior):
    _town(facts, folder, area_id, key, interior)


def test_the_backfill_covers_every_unnamed_wild_less_town(facts):
    """Re-derive all wild-less Hoenn towns from the pin: a source update cannot leave one unnamed."""
    derived = {f for f, m in facts["maps"].items()
               if facts["group"].get(f) == facts["towns_and_routes"]
               and m["map_type"] in ("MAP_TYPE_CITY", "MAP_TYPE_TOWN") and m["id"] not in facts["wild"]}
    expected = set(gam._EMERALD_WILD_LESS_TOWNS) | {"LavaridgeTown"}
    assert derived == expected, sorted(derived ^ expected)
    assert all(facts["key"][f] in AREA for f in derived)
