#!/usr/bin/env python3
"""
tools/parse_map_names.py — Parse ROM map name extraction results.

Reads the JSON output from lua/test_map_names.lua and produces:
  1. data/rom_map_names.json  — complete mapGroup:mapNum → display name mapping
  2. Validation report comparing against existing area_map.json
  3. List of NEW maps discovered beyond vanilla FRLG (for RR/CFRU)
  4. Suggested updates for server/server.py _AREA_DISPLAY dict

Usage:
    python tools/parse_map_names.py [path_to_results_file]

If no path given, looks for lua/map_names_results.txt in the project root.
"""

import json
import os
import re
import sys


def find_results_file():
    """Locate the results file from test_map_names.lua."""
    candidates = [
        "lua/map_names_results.txt",
        "map_names_results.txt",
    ]
    if len(sys.argv) > 1:
        candidates.insert(0, sys.argv[1])

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def extract_json(text: str) -> dict:
    """Extract the JSON block between ===JSON_START=== and ===JSON_END=== markers."""
    start = text.find("===JSON_START===")
    end_ = text.find("===JSON_END===")
    if start == -1 or end_ == -1:
        raise ValueError("Could not find JSON markers in results file")
    json_text = text[start + len("===JSON_START==="):end_].strip()
    return json.loads(json_text)


def load_area_map() -> dict:
    """Load existing area_map.json for cross-reference."""
    path = "data/area_map.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def to_display_name(rom_name: str) -> str:
    """Clean ROM map name for display.

    ROM names from RR are already Title Case but may contain GBA encoding
    artifacts: {B3} = apostrophe, leading comma = é in "Pokémon".
    """
    if not rom_name:
        return rom_name

    # Fix GBA encoding artifacts
    name = rom_name.replace("{B3}", "'")  # apostrophe
    name = name.replace("Pok,mon", "Pokémon")  # é encoding artifact

    return name


def main():
    results_path = find_results_file()
    if not results_path:
        print("ERROR: Could not find results file.")
        print("Run lua/test_map_names.lua in BizHawk first, then try again.")
        print("Or pass the path explicitly: python tools/parse_map_names.py <path>")
        sys.exit(1)

    print(f"Reading: {results_path}")
    with open(results_path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    data = extract_json(text)
    maps = data["maps"]
    mapsec_names = data["mapsec_names"]
    metadata = data["metadata"]

    print(f"ROM: {metadata.get('rom_name', 'unknown')}")
    print(f"Groups: {metadata['detected_groups']} (vanilla: {metadata.get('vanilla_groups', '?')})")
    print(f"Maps: {metadata['total_maps']}")

    new_in_groups = metadata.get("new_maps_in_existing_groups", 0)
    new_groups = metadata.get("new_group_maps", 0)
    if new_in_groups + new_groups > 0:
        print(f"★ NEW maps: {new_in_groups + new_groups} "
              f"({new_in_groups} in existing groups, {new_groups} in new groups)")

    # Build mapGroup:mapNum → display name mapping
    name_map = {}
    new_map_entries = []
    for m in maps:
        key = f"{m['group']}:{m['num']}"
        display = to_display_name(m["name"])
        name_map[key] = {
            "name": display,
            "rom_name": m["name"],
            "mapsec": m["mapsec"],
            "cave": m["cave"],
            "weather": m["weather"],
            "map_type": m["map_type"],
        }
        if m.get("is_new"):
            new_map_entries.append({
                "key": key,
                "name": display,
                "rom_name": m["name"],
                "mapsec": m["mapsec"],
                "cave": m["cave"],
            })

    # Write complete name map
    out_path = "data/rom_map_names.json"
    with open(out_path, "w") as f:
        json.dump(name_map, f, indent=2, sort_keys=True)
    print(f"\nWritten: {out_path} ({len(name_map)} entries)")

    # Cross-reference with area_map.json
    area_map = load_area_map()
    print(f"\n{'='*60}")
    print("AREA MAP CROSS-REFERENCE")
    print(f"{'='*60}")

    covered = 0
    missing = []
    for key, area_id in sorted(area_map.items()):
        if key in name_map:
            covered += 1
        else:
            missing.append((key, area_id))

    print(f"  area_map.json entries: {len(area_map)}")
    print(f"  Covered by ROM data:  {covered}")
    if missing:
        print(f"  Missing from ROM:     {len(missing)}")
        for key, area_id in missing:
            print(f"    {key} ({area_id})")
    else:
        print("  ✓ All area_map entries have ROM names")

    # Report new maps not in area_map
    new_encounter_candidates = []
    for m in maps:
        key = f"{m['group']}:{m['num']}"
        if key not in area_map and m.get("is_new"):
            new_encounter_candidates.append(m)

    if new_encounter_candidates:
        print(f"\n{'='*60}")
        print("NEW MAPS (not in vanilla FRLG)")
        print(f"{'='*60}")
        for m in new_encounter_candidates:
            cave_str = ["none", "cave", "underwater"][m["cave"]] if m["cave"] <= 2 else f"unk{m['cave']}"
            print(f"  {m['group']}:{m['num']}  {to_display_name(m['name']):<25s}  "
                  f"cave={cave_str}  weather={m['weather']}  type={m['map_type']}")
        print(f"\n  Total: {len(new_encounter_candidates)} new maps to review.")
        print("  Maps with cave>0 or weather>0 likely have wild encounters.")

    # Generate suggested _AREA_DISPLAY updates
    print(f"\n{'='*60}")
    print("SUGGESTED _AREA_DISPLAY UPDATES")
    print(f"{'='*60}")
    print("  (Add these to server/server.py _AREA_DISPLAY dict)")
    print()

    # For each area_id in area_map, find the ROM display name
    area_display = {}
    for key, area_id in area_map.items():
        if key in name_map:
            rom_display = name_map[key]["name"]
            # Only suggest if different from auto-generated name
            auto_name = area_id.replace("_", " ").title()
            if rom_display != auto_name:
                if area_id not in area_display:
                    area_display[area_id] = rom_display

    for area_id in sorted(area_display):
        display = area_display[area_id]
        print(f'    "{area_id}": "{display}",')

    # Dump mapsec table for reference
    mapsec_path = "data/rom_mapsec_names.json"
    # Sort mapsec names by numeric key
    sorted_mapsec = dict(sorted(mapsec_names.items(), key=lambda x: int(x[0])))
    with open(mapsec_path, "w") as f:
        json.dump(sorted_mapsec, f, indent=2)
    print(f"\nWritten: {mapsec_path} ({len(mapsec_names)} mapsec names)")

    print("\nDone.")


if __name__ == "__main__":
    main()
