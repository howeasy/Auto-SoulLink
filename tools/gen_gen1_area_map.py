#!/usr/bin/env python3
"""
gen_gen1_area_map.py — Generate Gen 1 RBY area lookup tables for Lua.

Outputs:
  data/games/gen1_rby/gen1_rby_areas.lua      — mapId -> area_id lookup
  data/games/gen1_rby/gen1_rby_locations.lua  — area_id -> display name lookup

Source: data/games/gen1_rby/area_map.json

Run:
  python tools/gen_gen1_area_map.py
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREA_MAP_PATH = os.path.join(ROOT, "data", "games", "gen1_rby", "area_map.json")
AREAS_LUA_PATH = os.path.join(ROOT, "data", "games", "gen1_rby", "gen1_rby_areas.lua")
LOCATIONS_LUA_PATH = os.path.join(ROOT, "data", "games", "gen1_rby", "gen1_rby_locations.lua")


def main():
    with open(AREA_MAP_PATH, "r") as f:
        area_map = json.load(f)

    # ── gen1_rby_areas.lua ──
    lines = [
        "-- gen1_rby_areas.lua — Generated area lookup table for Gen 1 RBY",
        "-- mapId -> area_id (from data/games/gen1_rby/area_map.json)",
        "-- DO NOT EDIT — regenerate with: python tools/gen_gen1_area_map.py",
        "",
        "local T = {}",
        "",
    ]
    for map_id in sorted(area_map.keys(), key=lambda x: int(x)):
        entry = area_map[map_id]
        area_id = entry["area_id"]
        name = entry["name"]
        lines.append(
            f'T[{int(map_id):>3}] = "{area_id}"  -- 0x{int(map_id):02X} {name}'
        )
    lines += ["", "return T", ""]

    with open(AREAS_LUA_PATH, "w", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"Wrote {AREAS_LUA_PATH} ({len(area_map)} entries)")

    # ── gen1_rby_locations.lua ──
    seen: dict[str, str] = {}
    for map_id in sorted(area_map.keys(), key=lambda x: int(x)):
        entry = area_map[map_id]
        aid = entry["area_id"]
        if aid not in seen:
            seen[aid] = entry["name"]

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

    with open(LOCATIONS_LUA_PATH, "w", newline="\n") as f:
        f.write("\n".join(loc_lines))
    print(f"Wrote {LOCATIONS_LUA_PATH} ({len(seen)} unique areas)")


if __name__ == "__main__":
    main()
