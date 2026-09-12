#!/usr/bin/env python3
"""
gen_gen1_area_map.py — Generate Gen 1 RBY area lookup tables for Lua.

Outputs:
  data/games/gen1_rby/gen1_rby_areas.lua      — mapId -> area_id lookup
  data/games/gen1_rby/gen1_rby_locations.lua  — area_id -> display name lookup

Source: data/games/gen1_rby/area_map.json

Run:
  python tools/gen_gen1_area_map.py            # regenerate the two .lua files
  python tools/gen_gen1_area_map.py --check    # qualify area_map.json against pret

`--check` reads, for BOTH decomps (pokered with _RED/_BLUE, pokeyellow):
  constants/map_constants.asm   every area_map key must be a defined, non-UNUSED map id
  data/wild/grass_water.asm     every map with a real WildMons pointer must have an area
  data/wild/super_rod.asm       every map with a Super Rod group is listed (see below)
and that the two generated .lua files are what area_map.json produces today.

Super-Rod-only maps without an area are REPORTED, not failed: they are towns and indoor
maps (Viridian/Cerulean/Vermilion/Fuchsia City, Cerulean Gym, Vermilion Dock) with no
grass or surf table, and giving them an area_id creates a new rule unit -- a decision for
area_map.json's owner, not for a checker. Grass/surf maps without an area DO fail.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREA_MAP_PATH = os.path.join(ROOT, "data", "games", "gen1_rby", "area_map.json")
AREAS_LUA_PATH = os.path.join(ROOT, "data", "games", "gen1_rby", "gen1_rby_areas.lua")
LOCATIONS_LUA_PATH = os.path.join(ROOT, "data", "games", "gen1_rby", "gen1_rby_locations.lua")

_AREA_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def render(area_map: dict) -> tuple[str, str]:
    """(gen1_rby_areas.lua, gen1_rby_locations.lua) contents for an area_map dict."""
    lines = [
        "-- gen1_rby_areas.lua — Generated area lookup table for Gen 1 RBY",
        "-- mapId -> area_id (from data/games/gen1_rby/area_map.json)",
        "-- DO NOT EDIT — regenerate with: python tools/gen_gen1_area_map.py",
        "",
        "local T = {}",
        "",
    ]
    seen: dict[str, str] = {}
    for map_id in sorted(area_map.keys(), key=lambda x: int(x)):
        entry = area_map[map_id]
        area_id = entry["area_id"]
        name = entry["name"]
        lines.append(
            f'T[{int(map_id):>3}] = "{area_id}"  -- 0x{int(map_id):02X} {name}'
        )
        seen.setdefault(area_id, name)
    lines += ["", "return T", ""]

    loc_lines = [
        "-- gen1_rby_locations.lua — Generated location name lookup for Gen 1 RBY",
        "-- area_id -> display name (from data/games/gen1_rby/area_map.json)",
        "-- DO NOT EDIT — regenerate with: python tools/gen_gen1_area_map.py",
        "",
        "local T = {}",
        "",
    ]
    for aid in sorted(seen.keys()):
        loc_lines.append(f'T["{aid}"] = "{seen[aid]}"')
    loc_lines += ["", "return T", ""]
    return "\n".join(lines), "\n".join(loc_lines)


# ── --check: qualify area_map.json against pret ──────────────────────────────────────────
def parse_map_constants(path: str) -> list[str]:
    """map id -> constant name, in `map_const` order after `const_def` (no skips in Gen 1)."""
    out: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\s*map_const\s+([A-Z_0-9]+)\s*,", line)
            if m:
                out.append(m.group(1))
    return out


def wild_map_names(repo: str) -> tuple[list[str], list[str]]:
    """(grass/water map constants, super rod map constants) that carry wild data.

    grass_water.asm is positional (`dw Label` per map id) so its names come from the
    constants table; super_rod.asm names the map in every row in both title formats
    (`dbw MAP, .Group` in pokered, `db MAP, species, level x4` in pokeyellow).
    """
    consts = parse_map_constants(os.path.join(repo, "constants", "map_constants.asm"))
    grass_water: list[str] = []
    in_table = False
    idx = 0
    with open(os.path.join(repo, "data", "wild", "grass_water.asm"), encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            if line.startswith("WildDataPointers"):
                in_table = True
                continue
            if not in_table:
                continue
            if line.startswith("assert_table_length"):
                break
            m = re.match(r"^dw\s+([A-Za-z_0-9]+)\s*$", line)
            if m:
                if m.group(1) != "NothingWildMons":
                    grass_water.append(consts[idx])
                idx += 1
    super_rod: list[str] = []
    with open(os.path.join(repo, "data", "wild", "super_rod.asm"), encoding="utf-8") as f:
        for raw in f:
            m = re.match(r"^\s*dbw?\s+([A-Z][A-Z_0-9]+)\s*,", raw)
            if m and m.group(1) in consts:
                super_rod.append(m.group(1))
    return grass_water, super_rod


def check(area_map: dict, repos: dict[str, str]) -> tuple[list[str], list[str]]:
    """(failures, notes). Empty failures == area_map.json qualifies against every decomp."""
    failures: list[str] = []
    notes: list[str] = []

    for key, entry in area_map.items():
        if not isinstance(entry, dict) or not entry.get("name"):
            failures.append(f"map {key}: entry has no display name")
        elif not _AREA_ID_RE.match(entry.get("area_id") or ""):
            failures.append(f"map {key}: area_id {entry.get('area_id')!r} is not an identifier")
        if not key.isdigit():
            failures.append(f"map {key!r}: key is not a map id")

    consts_by_title = {t: parse_map_constants(os.path.join(r, "constants", "map_constants.asm"))
                       for t, r in repos.items()}
    for title, consts in consts_by_title.items():
        for key in area_map:
            if not key.isdigit():
                continue
            mid = int(key)
            if mid >= len(consts):
                failures.append(f"{title}: map {mid} is past the last map constant ({len(consts) - 1})")
            elif consts[mid].startswith("UNUSED_MAP_"):
                failures.append(f"{title}: map {mid} is {consts[mid]}")
        grass_water, super_rod = wild_map_names(repos[title])
        for name in grass_water:
            if str(consts.index(name)) not in area_map:
                failures.append(f"{title}: {name} ({consts.index(name)}) has a wild table but no area")
        # A Super Rod table is an encounter table: a fishable map without a rule area is a
        # failure, the same as a grass map without one (a catch there would be untracked).
        for name in super_rod:
            if str(consts.index(name)) not in area_map:
                failures.append(f"{title}: {name} ({consts.index(name)}) has a super rod table but no area")
        notes.append(f"{title}: {len(grass_water)} grass/water maps and {len(super_rod)} "
                     f"super rod maps carry wild data, every one mapped to an area")

    # Yellow-only ids, stated explicitly: pokeyellow appends SUMMER_BEACH_HOUSE and renames
    # one house; the ids the two decomps share must agree name for name.
    if {"pokered", "pokeyellow"} <= set(consts_by_title):
        red, yellow = consts_by_title["pokered"], consts_by_title["pokeyellow"]
        only_yellow = [f"{yellow[i]}({i})" for i in range(len(red), len(yellow))]
        renamed = [f"{i}: {red[i]} / {yellow[i]}" for i in range(min(len(red), len(yellow)))
                   if red[i] != yellow[i]]
        notes.append(f"yellow-only map ids: {', '.join(only_yellow) or 'none'}; "
                     f"renamed between decomps: {'; '.join(renamed) or 'none'}")
        for entry in only_yellow:
            mid = entry[entry.index("(") + 1:-1]
            if mid in area_map:
                notes.append(f"map {mid} is Yellow-only and mapped to {area_map[mid]['area_id']}")

    areas_lua, locations_lua = render({k: v for k, v in area_map.items() if isinstance(v, dict)})
    for path, want in ((AREAS_LUA_PATH, areas_lua), (LOCATIONS_LUA_PATH, locations_lua)):
        try:
            with open(path, encoding="utf-8") as f:   # universal newlines: CRLF checkouts pass
                have = f.read()
        except OSError:
            have = None
        if have != want:
            failures.append(f"{os.path.basename(path)} is stale; rerun tools/gen_gen1_area_map.py")
    return failures, notes


def find_repos() -> dict[str, str]:
    """Both decomps, located the way gen_gen1_encounters.py locates them."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from gen_gen1_encounters import _find_pret
    finally:
        sys.path.pop(0)
    return {"pokered": _find_pret("pokered"), "pokeyellow": _find_pret("pokeyellow")}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    with open(AREA_MAP_PATH, encoding="utf-8") as f:
        area_map = json.load(f)

    if "--check" in argv:
        repos = find_repos()
        missing = [r for r in repos.values() if not os.path.isdir(r)]
        if missing:
            sys.stderr.write(f"Missing pret repo(s): {missing}\n")
            return 1
        failures, notes = check(area_map, repos)
        for n in notes:
            print(n)
        if failures:
            print(f"FAIL: {len(failures)} problem(s) in area_map.json")
            for fl in failures:
                print(f"  {fl}")
            return 1
        print(f"OK: area_map.json ({len(area_map)} maps, "
              f"{len({v['area_id'] for v in area_map.values()})} areas) qualifies against "
              + ", ".join(repos))
        return 0

    areas_lua, locations_lua = render(area_map)
    with open(AREAS_LUA_PATH, "w", newline="\n", encoding="utf-8") as f:
        f.write(areas_lua)
    print(f"Wrote {AREAS_LUA_PATH} ({len(area_map)} entries)")
    with open(LOCATIONS_LUA_PATH, "w", newline="\n", encoding="utf-8") as f:
        f.write(locations_lua)
    print(f"Wrote {LOCATIONS_LUA_PATH} ({locations_lua.count('T[')} unique areas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
