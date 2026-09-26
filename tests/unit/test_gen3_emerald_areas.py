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
import re
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


# Applied per-test below (not module-wide): the FRLG byte-identity guard needs no
# pret checkout and must still run when pret isn't present locally.
needs_pret = pytest.mark.skipif(
    not _pret_available(), reason="pokeemerald not cloned: .cache/pret/pokeemerald"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- FRLG must stay byte-identical (this file's own edits touched a shared tool) ---

def _lf(path):
    return path.read_bytes().replace(b"\r\n", b"\n")


def test_frlg_output_is_byte_identical_after_the_emerald_edit(tmp_path, monkeypatch):
    # Regenerate into a scratch dir (never over the committed files) and compare content;
    # line endings are the checkout's business, not the generator's.
    (tmp_path / "data" / "games" / "gen3_frlge").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    gam.generate_frlg()
    for committed in FRLG_FILES:
        fresh = tmp_path / committed.relative_to(_REPO)
        assert _lf(fresh) == _lf(committed), (
            f"generate_frlg() changed {committed.name} -- Emerald mode must be additive only")


# --- First falsifier: Hoenn names, never Kanto ---

@needs_pret
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

@needs_pret
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


@needs_pret
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


@needs_pret
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


# --- statics.json (task 3): every map key is real, every species citation checks out ---

def test_statics_every_map_key_is_a_known_location():
    """Every non-null statics.json 'map' is a real mapGroup:mapNum -- typo-proofing the
    hand-curated table against gen3_emerald_locations.lua, the same key space the
    server actually indexes into."""
    data = json.loads((_REPO / "data/games/gen3_emerald/statics.json").read_text())
    loc = _lua_table(_REPO / "data/games/gen3_emerald/gen3_emerald_locations.lua")
    for e in data["entries"]:
        if e["map"] is None:
            continue  # roamer: no fixed map, documented as a RECORDED LIMIT
        assert e["map"] in loc, f"{e['id']}: map {e['map']!r} is not in gen3_emerald_locations.lua"


_STATICS_SOURCE_PATTERN = re.compile(r"([A-Za-z0-9_./-]+\.(?:inc|json|c)):([0-9][0-9,\-]*)")


def _expand_line_range(rangespec: str) -> set[int]:
    lines: set[int] = set()
    for part in rangespec.split(","):
        if "-" in part:
            a, b = part.split("-")
            lines.update(range(int(a), int(b) + 1))
        else:
            lines.add(int(part))
    return lines


@needs_pret
def test_statics_sources_cite_the_species_on_the_stated_pret_lines():
    """Every 'path:a-b' citation in a statics.json 'source' string must be a real pret
    file, and the entry's species token(s) must actually appear on one of the exact
    cited lines -- not merely somewhere in the file. Mutation check: swap any entry's
    species for one that appears nowhere in its cited lines (e.g. SPECIES_ZUBAT) and
    this test goes red."""
    pret = Path(gam._find_pret_checkout("pokeemerald"))
    data = json.loads((_REPO / "data/games/gen3_emerald/statics.json").read_text())
    for e in data["entries"]:
        species = e["species"]
        if species is None:
            continue
        if isinstance(species, str):
            species = [species]
        segments = _STATICS_SOURCE_PATTERN.findall(e["source"])
        assert segments, f"{e['id']}: source has no parseable path:line-range citation"
        file_lines: dict[str, set[int]] = {}
        for path, rangespec in segments:
            fp = pret / path
            assert fp.is_file(), f"{e['id']}: cited file does not exist in pret: {path}"
            file_lines.setdefault(path, set()).update(_expand_line_range(rangespec))
        for sp in species:
            found = False
            for path, lines in file_lines.items():
                text_lines = (pret / path).read_text(encoding="utf-8").splitlines()
                if any(1 <= ln <= len(text_lines) and sp in text_lines[ln - 1] for ln in lines):
                    found = True
                    break
            assert found, f"{e['id']}: {sp} does not appear on any cited line ({segments})"


_STATICS_BATTLE_OR_GIVE_VERBS = (
    "givemon", "giveegg", "setwildbattle", "dowildbattle", "seteventmon",
    "scriptgivemon", "choosestarter", "initroamer", "giveeggfromdaycare",
)


@needs_pret
def test_statics_cited_lines_show_a_real_battle_or_give_not_just_a_cry():
    """A cited species reference is not enough on its own -- an NPC that only
    `playmoncry`s or flees (Fortree City / Lilycove House1 / Sootopolis House1 Kecleon,
    removed by this card) is not an encounter. Every entry's cited lines must also show
    one of the real battle/give script commands. First falsifier for card E1-AREA-2
    finding 1: this goes red on the three removed rows (species present via playmoncry,
    no setwildbattle/dowildbattle/givemon/giveegg/seteventmon/special anywhere cited)."""
    pret = Path(gam._find_pret_checkout("pokeemerald"))
    data = json.loads((_REPO / "data/games/gen3_emerald/statics.json").read_text())
    for e in data["entries"]:
        if e["species"] is None:
            continue
        segments = _STATICS_SOURCE_PATTERN.findall(e["source"])
        text_blob = []
        for path, rangespec in segments:
            fp = pret / path
            if not fp.is_file():
                continue
            text_lines = fp.read_text(encoding="utf-8").splitlines()
            for ln in _expand_line_range(rangespec):
                if 1 <= ln <= len(text_lines):
                    text_blob.append(text_lines[ln - 1].lower())
        blob = "\n".join(text_blob)
        assert any(v in blob for v in _STATICS_BATTLE_OR_GIVE_VERBS), (
            f"{e['id']}: cited lines show no battle/give verb "
            f"({_STATICS_BATTLE_OR_GIVE_VERBS}) -- not a real encounter"
        )


# --- full-table consistency (task 4) ---

def test_areas_lua_matches_area_map_json():
    """gen_area_map.py writes the same table twice (JSON for Python/tests, Lua for the
    client) -- they must describe the exact same mapping, or a generator change that
    only touches one output would go unnoticed."""
    area_json = json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text())
    area_lua = _lua_table(_REPO / "data/games/gen3_emerald/gen3_emerald_areas.lua")
    assert area_lua == area_json


# --- area-id collisions (task 5) ---

@needs_pret
def test_multi_key_area_id_groups_share_one_mapsec_or_a_documented_override():
    """Every area_id spanning more than one mapGroup:mapNum key must be a documented
    merge: all its maps share one pret MAPSEC (multi-floor dungeon), or the extra key is
    one of the explicit dive-to-host overrides in gen_area_map._EMERALD_DIVE_HOST. This
    is the generator's own collision guard, re-checked here against the committed
    output -- pret reuses MAPSEC display names across unrelated ids (11 different
    MAPSEC_UNDERWATER_* all display 'UNDERWATER'; MAPSEC_AQUA_HIDEOUT and
    MAPSEC_AQUA_HIDEOUT_OLD both display 'AQUA HIDEOUT'), so a merge that isn't one of
    these two documented cases is a real bug, not a coincidence."""
    pret = Path(gam._find_pret_checkout("pokeemerald"))
    with open(pret / "data/maps/map_groups.json", encoding="utf-8") as f:
        groups_data = json.load(f)
    folder_of_key: dict[str, str] = {}
    mapsec_of_folder: dict[str, str] = {}
    id_of_folder: dict[str, int] = {}
    for group_idx, group_name in enumerate(groups_data["group_order"]):
        for map_idx, folder in enumerate(groups_data[group_name]):
            folder_of_key[f"{group_idx}:{map_idx}"] = folder
            with open(pret / "data/maps" / folder / "map.json", encoding="utf-8") as mf:
                map_data = json.load(mf)
            mapsec_of_folder[folder] = map_data.get("region_map_section")
            id_of_folder[folder] = map_data["id"]
    folder_of_id = {v: k for k, v in id_of_folder.items()}

    dive_host_of_dive_folder = {
        folder_of_id[dive_id]: folder_of_id[host_id]
        for dive_id, host_id in gam._EMERALD_DIVE_HOST.items()
    }

    area = json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text())
    groups: dict[str, list[str]] = {}
    for key, area_id in area.items():
        groups.setdefault(area_id, []).append(key)

    checked_multi_key_groups = 0
    for area_id, keys in groups.items():
        if len(keys) < 2:
            continue
        checked_multi_key_groups += 1
        folders = [folder_of_key[k] for k in keys]
        identities = {mapsec_of_folder[dive_host_of_dive_folder.get(f, f)] for f in folders}
        assert len(identities) == 1, (
            f"area_id {area_id!r} groups keys {keys} (folders {folders}) across MAPSECs "
            f"{identities} -- not a single shared MAPSEC and not a documented dive-host override"
        )
    assert checked_multi_key_groups > 0, "expected at least one multi-key area_id group to check"


# --- pret tripwire (task 6) ---

@needs_pret
def test_pret_map_groups_has_the_shape_this_generator_assumes():
    """Tripwire on pret/pokeemerald's own map_groups.json: if a future pret bump ever
    reshuffles the group table, this is the first thing to go red, before a silently
    wrong area_id does."""
    pret = Path(gam._find_pret_checkout("pokeemerald"))
    with open(pret / "data/maps/map_groups.json", encoding="utf-8") as f:
        groups_data = json.load(f)
    assert len(groups_data["group_order"]) == 34
    assert groups_data["group_order"][24] == "gMapGroup_Dungeons"


# --- E3-GIFTLINK: every statics.json map is a NAMED area (the FR/LG oaks_lab / navel_rock shape) ---

_STATICS = _REPO / "data/games/gen3_emerald/statics.json"
_GIFT_KINDS = ("gift", "choice_gift", "fixed_gift")


def _emerald_area_map():
    return json.loads((_REPO / "data/games/gen3_emerald/area_map.json").read_text())


def _statics_rows():
    return json.loads(_STATICS.read_text())["entries"]


def test_producer_coverage_every_statics_map_is_in_the_area_map():
    """The client sends area_map[group:num] or "" and the server drops "": a statics.json map
    missing here is a gift/static that can never link (the NEXT-1 gap)."""
    area = _emerald_area_map()
    missing = [(r["id"], r["map"]) for r in _statics_rows() if r["map"] and r["map"] not in area]
    assert missing == []


def test_gift_maps_are_named_gift_areas_owned_by_no_wild_map_and_equal_the_packs_list():
    area = _emerald_area_map()
    gift_keys = {r["map"] for r in _statics_rows() if r["kind"] in _GIFT_KINDS}
    ids = {area[k] for k in gift_keys} - {"route_101"}          # the starter's wild route
    for gid in ids:                                              # a gift id covers only gift maps
        assert {k for k, v in area.items() if v == gid} <= gift_keys, gid
    wc = json.loads((_REPO / "data/games/gen3_emerald/write_checkpoint.json").read_text())
    assert wc["emerald"]["gift_areas"]["ids"] == sorted(ids)
    assert sorted(ids) == ["lavaridge_town", "mossdeep_city_stevens_house",
                           "route119_weather_institute_2f", "rustboro_city_devon_corp_2f"]


def test_static_battles_take_their_mapsec_area_like_navel_rock():
    area = _emerald_area_map()
    assert {k: area[k] for k in ("26:75", "26:87", "24:85", "24:103", "24:105", "24:6",
                                 "24:67", "24:68", "26:57", "26:58")} == {
        "26:75": "navel_rock", "26:87": "navel_rock", "24:85": "sky_pillar",
        "24:103": "marine_cave", "24:105": "terra_cave", "24:6": "desert_ruins",
        "24:67": "island_cave", "24:68": "ancient_tomb", "26:57": "faraway_island",
        "26:58": "birth_island"}


def test_the_daycare_egg_row_is_route_117_outdoors():
    (row,) = [r for r in _statics_rows() if r["id"] == "route_117_daycare_egg"]
    assert row["map"] == "0:32" and _emerald_area_map()["0:32"] == "route_117"
    assert "data/maps/Route117/map.json:65" in row["source"]


@needs_pret
def test_the_daycare_man_who_hands_the_egg_over_stands_on_route_117():
    pret = Path(gam._find_pret_checkout("pokeemerald"))
    lines = (pret / "data/maps/Route117/map.json").read_text(encoding="utf-8").splitlines()
    assert '"script": "Route117_EventScript_DaycareMan"' in lines[64]
    inc = (pret / "data/scripts/day_care.inc").read_text(encoding="utf-8").splitlines()
    assert inc[0].startswith("Route117_EventScript_DaycareMan::")
    assert "special GiveEggFromDaycare" in inc[36]


@needs_pret
def test_emerald_area_tables_are_reproducible(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    gam.generate_emerald()
    for name in ("area_map.json", "gen3_emerald_areas.lua", "gen3_emerald_locations.lua"):
        committed = _REPO / "data/games/gen3_emerald" / name
        assert _lf(tmp_path / "data/games/gen3_emerald" / name) == _lf(committed), name
