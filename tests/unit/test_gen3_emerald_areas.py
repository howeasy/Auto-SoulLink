"""Falsifiers for the Emerald area map / locations / statics generator (card E1-AREA).

tools/gen_area_map.py gained an Emerald mode that derives area_id and location
names from pret/pokeemerald's own JSON (map_groups.json, region_map_sections.json,
wild_encounters.json) instead of a hand-typed table like the FRLG one. The whole
point of doing it that way is to make a Kanto-name leak or a missing map
structurally impossible rather than merely unlikely -- these tests are the
falsifiers for that claim, plus the byte-identical proof the card requires
before touching a file FRLG also owns.

Needs the pret/pokeemerald checkout (`.cache/pret/pokeemerald`, PLAN.md's read-only
research pin) -- skips if it is not present locally, same pattern as the Emerald
codec tests' ROM skip.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "tools"))

import gen_area_map as gam  # noqa: E402
import gen_gen3_emerald_statics as gstatics  # noqa: E402

FRLG_FILES = [
    _REPO / "data/games/gen3_frlge/area_map.json",
    _REPO / "data/games/gen3_frlge/gen3_frlge_areas.lua",
    _REPO / "data/games/gen3_frlge/gen3_frlge_locations.lua",
]


def _pret_available() -> bool:
    try:
        gam._find_pret_checkout("pokeemerald")
    except FileNotFoundError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _pret_available(), reason="pret/pokeemerald checkout not present locally"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- FRLG must stay byte-identical (this file's own edits touched a shared tool) ---

def test_frlg_output_is_byte_identical_after_the_emerald_edit(monkeypatch):
    before = {p: _sha256(p) for p in FRLG_FILES}
    monkeypatch.chdir(_REPO)
    gam.generate_frlg()
    after = {p: _sha256(p) for p in FRLG_FILES}
    assert before == after, "generate_frlg() output changed -- Emerald mode must be additive only"


# --- First falsifier: Hoenn names, never Kanto ---

def test_littleroot_oldale_route101_resolve_to_hoenn_never_kanto():
    pret = gam._find_pret_checkout("pokeemerald")
    with open(Path(pret) / "data/maps/map_groups.json", encoding="utf-8") as f:
        groups_data = json.load(f)
    key_of_folder = {}
    for group_idx, group_name in enumerate(groups_data["group_order"]):
        for map_idx, folder in enumerate(groups_data[group_name]):
            key_of_folder[folder] = f"{group_idx}:{map_idx}"

    loc = _lua_table(_REPO / "data/games/gen3_emerald/gen3_emerald_locations.lua")
    area = json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text())

    kanto_markers = ("pallet", "viridian", "pewter", "cerulean", "vermilion", "celadon",
                      "fuchsia", "cinnabar", "saffron", "lavender", "kanto")

    assert loc[key_of_folder["LittlerootTown"]] == "littleroot_town"
    assert loc[key_of_folder["OldaleTown"]] == "oldale_town"
    assert area[key_of_folder["Route101"]] == "route_101"

    for key, name in loc.items():
        assert not any(k in name for k in kanto_markers), f"{key} -> {name} looks like a Kanto name"
    for key, name in area.items():
        assert not any(k in name for k in kanto_markers), f"{key} -> {name} looks like a Kanto name"


# --- Every wild_encounters.json map resolves to an area ---

def test_every_wild_encounter_map_has_an_area():
    pret = gam._find_pret_checkout("pokeemerald")
    with open(Path(pret) / "src/data/wild_encounters.json", encoding="utf-8") as f:
        wild_data = json.load(f)
    wild_group = next(g for g in wild_data["wild_encounter_groups"] if g["label"] == "gWildMonHeaders")
    wild_map_ids = {e["map"] for e in wild_group["encounters"]}

    with open(Path(pret) / "data/maps/map_groups.json", encoding="utf-8") as f:
        groups_data = json.load(f)
    key_of_folder = {}
    id_of_folder = {}
    for group_idx, group_name in enumerate(groups_data["group_order"]):
        for map_idx, folder in enumerate(groups_data[group_name]):
            key_of_folder[folder] = f"{group_idx}:{map_idx}"
            with open(Path(pret) / "data/maps" / folder / "map.json", encoding="utf-8") as mf:
                id_of_folder[folder] = json.load(mf)["id"]
    folder_of_id = {v: k for k, v in id_of_folder.items()}

    area = json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text())
    for map_id in wild_map_ids:
        key = key_of_folder[folder_of_id[map_id]]
        assert key in area, f"{map_id} ({key}) missing from area_map.json"
        assert area[key], f"{map_id} ({key}) has an empty area_id"


# --- FR vs E key collisions exist (proves per-title maps are needed) ---

def test_frlg_and_emerald_area_maps_collide_on_shared_keys():
    frlg = json.loads((_REPO / "data/games/gen3_frlge/area_map.json").read_text())
    emerald = json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text())
    shared_keys = set(frlg) & set(emerald)
    assert shared_keys, "expected FR and Emerald area_map.json to share some mapGroup:mapNum keys"
    disagreements = [k for k in shared_keys if frlg[k] != emerald[k]]
    assert disagreements, (
        "FR and Emerald area_map.json never disagree on a shared key -- "
        "if that ever becomes true a single shared table would work, but today it does not"
    )


# --- Emerald-specific merge defaults (PLAN.md section 0) ---

def test_multi_floor_dungeon_floors_merge_to_one_area_id():
    area = json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text())
    granite_cave_keys = [k for k, v in area.items() if v == "granite_cave"]
    assert len(granite_cave_keys) == 4  # 1F, B1F, B2F, StevensRoom


def test_safari_zone_stays_per_sub_area_not_merged():
    area = json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text())
    safari_ids = {v for v in area.values() if v.startswith("safari_zone")}
    assert safari_ids == {
        "safari_zone_north", "safari_zone_northeast", "safari_zone_northwest",
        "safari_zone_south", "safari_zone_southeast", "safari_zone_southwest",
    }


def test_dive_spots_merge_into_their_host_route():
    pret = gam._find_pret_checkout("pokeemerald")
    with open(Path(pret) / "data/maps/map_groups.json", encoding="utf-8") as f:
        groups_data = json.load(f)
    key_of_folder = {}
    for group_idx, group_name in enumerate(groups_data["group_order"]):
        for map_idx, folder in enumerate(groups_data[group_name]):
            key_of_folder[folder] = f"{group_idx}:{map_idx}"

    area = json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text())
    assert area[key_of_folder["Underwater_Route124"]] == "route_124"
    assert area[key_of_folder["Route124"]] == "route_124"
    assert area[key_of_folder["Underwater_Route126"]] == "route_126"
    assert area[key_of_folder["Route126"]] == "route_126"


def test_battle_pyramid_and_pike_are_excluded():
    """Frontier is out of scope (PLAN.md section 0); only gWildMonHeaders feeds the area map."""
    area_ids = set(json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text()).values())
    assert not any("pyramid" in a or "pike" in a for a in area_ids)


# --- statics.json (task 2) ---

def test_statics_entries_cite_a_pret_source_and_a_known_kind():
    data = json.loads((_REPO / "data/games/gen3_emerald/statics.json").read_text())
    entries = data["entries"]
    assert len(entries) >= 20
    valid_kinds = {"gift", "fixed_gift", "choice_gift", "static", "daycare"}
    for e in entries:
        assert e["kind"] in valid_kinds, e
        assert e["source"], f"{e['id']} has no pret citation"
        assert isinstance(e["bypass_clauses"], bool), e


def test_statics_bypass_clauses_match_the_plan_defaults():
    """PLAN.md section 0: Beldum/Wynaut egg/Castform/Mew/Deoxys bypass; starter/fossil (choice) do not."""
    data = json.loads((_REPO / "data/games/gen3_emerald/statics.json").read_text())
    by_id = {e["id"]: e for e in data["entries"]}
    for fixed_id in ("beldum", "wynaut_egg", "castform", "mew", "deoxys"):
        assert by_id[fixed_id]["bypass_clauses"] is True, fixed_id
    for choice_id in ("starter", "fossil"):
        assert by_id[choice_id]["bypass_clauses"] is False, choice_id
    for static_id in ("kyogre", "groudon", "rayquaza", "regirock", "regice", "registeel"):
        assert by_id[static_id]["bypass_clauses"] is False, static_id


def test_statics_generator_is_reproducible(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    gstatics.generate_statics()
    regenerated = json.loads((tmp_path / "data/games/gen3_emerald/statics.json").read_text())
    committed = json.loads((_REPO / "data/games/gen3_emerald/statics.json").read_text())
    assert regenerated == committed


def _lua_table(path: Path) -> dict[str, str]:
    """Tiny parser for this file's own generated shape: return { ["k"] = "v", ... }."""
    import re
    table = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r'\s*\["([^"]+)"\]\s*=\s*"([^"]*)",?\s*$', line)
        if m:
            table[m.group(1)] = m.group(2)
    return table
