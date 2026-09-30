#!/usr/bin/env python3
"""Source-only gift, egg and scripted-static census for expansion/1.17.0.

Keeps declarations in source order; does not authorize checkpoint gift_areas or live routing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.gen_gen3_exp_trainers import _check_area_map_digest, enum_values
from tools.gen_gen3_trainers import area_of_map, map_jsons, map_keys, read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/games/gen3_exp/28877d73/expansion_gifts.json"
AREA_MAP = ROOT / "data/games/gen3_exp/28877d73/area_map.json"
SOURCE_COMMIT = "e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7"
CALL = re.compile(r"^\s*(givemon|giveegg|createmon|setwildbattle)\s+([^@]+?)(?:\s+@.*)?$")
NATIVE = re.compile(r"\b(ScriptGiveMon|ScriptGiveEgg)\s*\((.+)\)\s*;")


def _included_scripts(src: Path) -> dict[str, str]:
    """Read the one top-level IS_FRLG assembly guard in event_scripts.s."""
    included = {}
    condition = "IS_EMERALD"
    for line in read(src / "data/event_scripts.s").splitlines():
        stripped = line.strip()
        if stripped == ".if IS_FRLG":
            condition = "IS_FRLG"
        elif stripped == ".endif" and condition == "IS_FRLG":
            condition = "IS_EMERALD"
        elif m := re.match(r'\.include "(data/(?:maps|scripts)/[^\"]+\.inc)"', stripped):
            included[m[1]] = condition
    return included


def build(src: Path) -> dict:
    src = src.resolve()
    commit = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
    if commit != SOURCE_COMMIT:
        raise ValueError(f"expansion source pin mismatch: {commit}")
    _check_area_map_digest(src, AREA_MAP)
    species_ids = enum_values(read(src / "include/constants/species.h"), "SPECIES_")
    keys = map_keys(src)
    maps = map_jsons(src)
    grouped = {name: m for name, m in maps.items() if m["id"] in keys}
    mapped = area_of_map(grouped, keys, json.loads(read(AREA_MAP)))
    includes = _included_scripts(src)
    rows = []

    def add(path: str, line: int, opcode: str, args: list[str], condition: str, status: str,
            note: str = "") -> None:
        kind = "egg" if opcode in ("giveegg", "ScriptGiveEgg") else (
            "static" if opcode == "setwildbattle" else "gift")
        species_index = 2 if opcode == "createmon" else 0
        species = args[species_index] if species_index < len(args) else ""
        if not species:
            raise ValueError(f"missing species argument: {path}:{line}")
        map_id = maps[Path(path).parent.name]["id"] if path.startswith("data/maps/") else None
        group_num = keys.get(map_id) if map_id else None
        area = mapped.get(map_id) if status == "active" and map_id else None
        unresolved_area = None
        if status == "active" and not area:
            unresolved_area = ("shared or native grant has runtime location" if not map_id
                               else "map has no mapped area in area_map/BFS graph")
        rows.append({"source": path, "line": line, "opcode": opcode, "kind": kind,
                     "arguments": args, "species": species,
                     "species_id": species_ids.get(species),
                     "species_resolution": "constant" if species in species_ids else "runtime expression",
                     "map_id": map_id, "map_group_num": group_num, "gift_area": area,
                     "unresolved_area": unresolved_area, "status": status,
                     "condition": condition, "note": note})

    # The include list is the compiled script surface, including declarations under IS_FRLG.
    # Keep physical source order by path/line, independent of assembly include order.
    script_paths = sorted(set(includes) | {"data/scripts/gift_pichu.inc"})
    for path in script_paths:
        file = src / path
        if not file.is_file():
            raise ValueError(f"included script missing: {path}")
        for line, content in enumerate(read(file).splitlines(), 1):
            m = CALL.match(content)
            if not m:
                continue
            opcode, argtext = m.groups()
            args = [x.strip() for x in argtext.split(",")]
            condition = includes.get(path, "mystery_gift_payload")
            if path == "data/scripts/debug.inc":
                status, reason = "excluded", "DEBUG=0; debug interface is disabled in this reference build"
                condition = "DEBUG_OVERWORLD_MENU / DEBUG=0"
            elif condition == "IS_FRLG":
                status, reason = "excluded", "event_scripts.s IS_FRLG branch is false for EMERALD"
            elif condition == "mystery_gift_payload":
                status, reason = "excluded", "external mystery-gift payload, not an ordinary map script"
            else:
                status, reason = "active", ""
            add(path, line, opcode, args, condition, status, reason)

    # Direct C callers bypass script macros. Exclude API definitions and the script dispatchers:
    # only concrete calls outside script_pokemon_util.c/scrcmd.c are declarations here.
    for path in ("src/battle_setup.c", "src/debug.c"):
        for line, content in enumerate(read(src / path).splitlines(), 1):
            m = NATIVE.search(content)
            if not m:
                continue
            opcode, argtext = m.groups()
            args = [x.strip() for x in argtext.split(",")]
            debug = path == "src/debug.c"
            add(path, line, opcode, args,
                "DEBUG_OVERWORLD_MENU / DEBUG=0" if debug else "EMERALD starter callback",
                "excluded" if debug else "active",
                "debug interface disabled in reference build" if debug else
                "starter species chosen at runtime; callback precedes first battle")

    rows.sort(key=lambda r: (r["source"], r["line"]))
    counts = Counter((r["status"], r["kind"]) for r in rows)
    return {"schema": "gen3-expansion-gifts-source-v1", "build": "28877d73",
            "source_commit": commit, "evidence": "SOURCE_ONLY", "live_verified": False,
            "area_map_source_sha256": re.search(r"source_sha256:\s*([0-9a-f]{64})",
                read(AREA_MAP.parent / "gen3_exp_areas.lua"))[1],
            "declarations": rows,
            "counts": {f"{status}_{kind}": count for (status, kind), count in sorted(counts.items())},
            "coverage": {
                "script_forms": ["givemon", "giveegg", "createmon", "setwildbattle"],
                "native_concrete_callers": ["src/battle_setup.c", "src/debug.c"],
                "limits": ["Kecleon shared script caller maps need expansion",
                           "Mystery-gift payload is external to ordinary map scripts",
                           "Runtime species expressions are retained unresolved",
                           "Other non-script acquisition paths need a separate audit"]}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=ROOT / ".cache/expansion-src")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    obj = build(args.src)
    text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUT.is_file() or read(OUT) != text:
            raise SystemExit(f"stale or absent: {OUT}")
        print(f"current: {OUT}")
    else:
        OUT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
