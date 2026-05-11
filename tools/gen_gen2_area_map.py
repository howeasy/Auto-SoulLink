#!/usr/bin/env python3
"""
gen_gen2_area_map.py — Generate Gen 2 Crystal area lookup tables for Lua.

Outputs:
  lua/gen2_crystal_areas.lua      — compositeId -> area_id lookup
  lua/gen2_crystal_locations.lua  — area_id -> display name lookup

Source: data/games/gen2_crystal/area_map.json

Composite ID = mapGroup * 256 + mapNumber (Crystal uses 2-byte map addressing).

Run:
  python tools/gen_gen2_area_map.py
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREA_MAP_PATH = os.path.join(ROOT, "data", "games", "gen2_crystal", "area_map.json")
AREAS_LUA_PATH = os.path.join(ROOT, "lua", "gen2_crystal_areas.lua")
LOCATIONS_LUA_PATH = os.path.join(ROOT, "lua", "gen2_crystal_locations.lua")


def main():
    with open(AREA_MAP_PATH, "r") as f:
        area_map = json.load(f)

    # ── gen2_crystal_areas.lua ──
    lines = [
        "-- gen2_crystal_areas.lua — Generated area lookup table for Gen 2 Crystal",
        "-- compositeId (mapGroup*256+mapNum) -> area_id",
        "-- Source: data/games/gen2_crystal/area_map.json",
        "-- DO NOT EDIT — regenerate with: python tools/gen_gen2_area_map.py",
        "",
        "local T = {}",
        "",
    ]
    for map_id in sorted(area_map.keys(), key=lambda x: int(x)):
        entry = area_map[map_id]
        area_id = entry["area_id"]
        name = entry["name"]
        cid = int(map_id)
        group = cid // 256
        num = cid % 256
        lines.append(
            f'T[{cid:>5}] = "{area_id}"'
            f"  -- G{group:>2} M{num:>2} {name}"
        )
    lines += ["", "return T", ""]

    with open(AREAS_LUA_PATH, "w", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"Wrote {AREAS_LUA_PATH} ({len(area_map)} entries)")

    # ── gen2_crystal_locations.lua ──
    seen: dict[str, str] = {}
    for map_id in sorted(area_map.keys(), key=lambda x: int(x)):
        entry = area_map[map_id]
        aid = entry["area_id"]
        if aid not in seen:
            seen[aid] = entry["name"]

    loc_lines = [
        "-- gen2_crystal_locations.lua — Generated location name lookup for Gen 2 Crystal",
        "-- area_id -> display name",
        "-- Source: data/games/gen2_crystal/area_map.json",
        "-- DO NOT EDIT — regenerate with: python tools/gen_gen2_area_map.py",
        "",
        "local T = {}",
        "",
    ]
    for aid in sorted(seen.keys()):
        loc_lines.append(f'T["{aid}"] = "{seen[aid]}"')
    loc_lines += ["", "return T", ""]

    with open(LOCATIONS_LUA_PATH, "w", newline="\n") as f:
        f.write("\n".join(loc_lines))
    print(f"Wrote {LOCATIONS_LUA_PATH} ({len(seen)} unique areas)")


if __name__ == "__main__":
    main()
