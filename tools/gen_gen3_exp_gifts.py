#!/usr/bin/env python3
"""Source-only gift, egg and scripted-static census for expansion/1.17.0.

Keeps declarations in source order; does not authorize checkpoint gift_areas or live routing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.gen_gen3_exp_trainers import _check_area_map_digest, enum_values
from tools.gen_area_map import _expansion_source_sha256
from tools.gen_gen3_trainers import area_of_map, map_jsons, map_keys, read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/games/gen3_exp/28877d73/expansion_gifts.json"
AREA_MAP = ROOT / "data/games/gen3_exp/28877d73/area_map.json"
SOURCE_COMMIT = "e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7"
CALL = re.compile(r"^\s*(givemon|giveegg|createmon|setwildbattle)\s+([^@]+?)(?:\s+@.*)?$")
NATIVE = re.compile(r"\b(ScriptGiveMon|ScriptGiveEgg)\s*\((.+)\)\s*;")
INCLUDE = re.compile(r'^\s*\.include "(data/(?:maps|scripts)/[^\"]+\.inc)"')


def split_arguments(text: str) -> list[str]:
    """Split C/assembly arguments at top-level commas, preserving nested calls and strings."""
    out, start, depth, quote, escape = [], 0, 0, None, False
    for i, char in enumerate(text):
        if escape:
            escape = False
        elif char == "\\" and quote:
            escape = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError(f"unbalanced arguments: {text}")
        elif char == "," and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
    if depth or quote:
        raise ValueError(f"unbalanced arguments: {text}")
    out.append(text[start:].strip())
    return out


def createmon_target(side: str) -> str:
    if side in ("B_SIDE_PLAYER", "0"):
        return "player"
    if side in ("B_SIDE_OPPONENT", "1"):
        return "opponent"
    return "runtime"


def classify_grant(opcode: str, args: list[str], status: str) -> tuple[str, str, str, str | None]:
    target = createmon_target(args[0]) if opcode == "createmon" else None
    kind = ("egg" if opcode in ("giveegg", "ScriptGiveEgg") else
            "static" if opcode == "setwildbattle" else
            "opponent_create" if target == "opponent" else
            "unresolved_create" if target == "runtime" else "gift")
    if target == "opponent":
        return kind, "excluded", "createmon targets opponent party, not a player grant", target
    if target == "runtime" and status == "active":
        return kind, "unknown", "createmon side is a runtime expression", target
    return kind, status, "", target


def _conditional_lines(path: Path, base: str):
    """Yield source lines with named condition; unknown grant conditions stay unknown."""
    stack: list[str] = []
    for number, content in enumerate(read(path).splitlines(), 1):
        stripped = content.strip()
        if m := re.match(r"^(?:\.|#)(if|ifdef|ifndef)\b\s*(.+)", stripped):
            stack.append(m[2].split("@", 1)[0].strip())
            continue
        if re.match(r"^(?:\.|#)else\b", stripped):
            if not stack:
                raise ValueError(f"unmatched else: {path}:{number}")
            stack[-1] = "!" + stack[-1] if not stack[-1].startswith("!") else stack[-1][1:]
            continue
        if re.match(r"^(?:\.|#)elif\b", stripped):
            if not stack:
                raise ValueError(f"unmatched elif: {path}:{number}")
            stack[-1] = "unknown:" + stripped
            continue
        if re.match(r"^(?:\.|#)endif\b", stripped):
            if not stack:
                raise ValueError(f"unmatched endif: {path}:{number}")
            stack.pop()
            continue
        conditions = [base, *stack]
        atoms = [part.strip() for condition in conditions for part in condition.split("&&")]
        if "mystery_gift_payload" in atoms or "IS_FRLG" in atoms or "!IS_EMERALD" in atoms:
            status = "excluded"
        elif any(c not in ("IS_EMERALD", "!IS_FRLG") for c in atoms):
            status = "unknown"
        else:
            status = "active"
        yield number, content, " && ".join(conditions), status
    if stack:
        raise ValueError(f"unterminated condition in {path}")


def script_closure(src: Path) -> dict[str, str]:
    """Transitive data script includes from both compiled event and external gift roots."""
    included: dict[str, str] = {}

    def visit(path: str, condition: str) -> None:
        previous = included.get(path)
        if previous is not None:
            if previous != condition:
                raise ValueError(f"script included under conflicting conditions: {path}")
            return
        file = src / path
        if not file.is_file():
            raise ValueError(f"included script missing: {path}")
        included[path] = condition
        for _, line, local_condition, _ in _conditional_lines(file, condition):
            if m := INCLUDE.match(line):
                visit(m[1], local_condition)

    for root, condition in (("data/event_scripts.s", "IS_EMERALD"),
                            ("data/mystery_gift.s", "mystery_gift_payload")):
        for _, line, local_condition, _ in _conditional_lines(src / root, condition):
            if m := INCLUDE.match(line):
                visit(m[1], local_condition)
    return included


def script_grants(path: Path, condition: str):
    for line, content, actual_condition, status in _conditional_lines(path, condition):
        if m := CALL.match(content):
            opcode, argtext = m.groups()
            yield {"line": line, "opcode": opcode, "arguments": split_arguments(argtext),
                   "condition": actual_condition, "status": status}


def build(src: Path) -> dict:
    src = src.resolve()
    commit = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
    if commit != SOURCE_COMMIT:
        raise ValueError(f"expansion source pin mismatch: {commit}")
    dirty = subprocess.check_output(["git", "-C", str(src), "status", "--porcelain",
                                     "--untracked-files=no"], text=True).strip()
    if dirty:
        raise ValueError(f"expansion source has tracked edits at pin: {dirty}")
    makefile = read(src / "Makefile")
    if not re.search(r"(?m)^GAME_VERSION\s*\?=\s*EMERALD\s*$", makefile) or not re.search(
            r"(?m)^DEBUG\s*\?=\s*0\s*$", makefile):
        raise ValueError("reference GAME_VERSION/DEBUG Makefile defaults differ")
    if not re.search(r"(?m)^#define DEBUG_OVERWORLD_MENU\s+DISABLED_ON_RELEASE\b",
                     read(src / "include/config/debug.h")):
        raise ValueError("reference debug-menu config differs")
    _check_area_map_digest(src, AREA_MAP)
    species_ids = enum_values(read(src / "include/constants/species.h"), "SPECIES_")
    keys = map_keys(src)
    maps = map_jsons(src)
    grouped = {name: m for name, m in maps.items() if m["id"] in keys}
    mapped = area_of_map(grouped, keys, json.loads(read(AREA_MAP)))
    includes = script_closure(src)
    rows = []

    def add(path: str, line: int, opcode: str, args: list[str], condition: str, status: str,
            note: str = "") -> None:
        kind, status, classification_note, target = classify_grant(opcode, args, status)
        if classification_note:
            note = classification_note
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
                     "map_id": map_id, "map_group_num": group_num, "area_id": area,
                     "gift_area": area if kind in ("gift", "egg") else None,
                     "target": target,
                     "unresolved_area": unresolved_area, "status": status,
                     "condition": condition, "note": note})

    # Preserve source-path/line order while scanning the full include closure.
    for path, base_condition in sorted(includes.items()):
        for grant in script_grants(src / path, base_condition):
            line, opcode, args = grant["line"], grant["opcode"], grant["arguments"]
            condition, status = grant["condition"], grant["status"]
            if path == "data/scripts/debug.inc":
                status, reason = "excluded", "DEBUG=0; debug interface is disabled in this reference build"
                condition = "DEBUG_OVERWORLD_MENU / DEBUG=0"
            elif status == "excluded" and "IS_FRLG" in condition:
                reason = "event_scripts.s IS_FRLG branch is false for EMERALD"
            elif status == "excluded" and "mystery_gift_payload" in condition:
                reason = "external mystery-gift payload, not an ordinary map script"
            elif status == "unknown":
                reason = "local compile condition was not evaluated for this reference build"
            else:
                reason = ""
            add(path, line, opcode, args, condition, status, reason)

    # Direct C callers bypass script macros. Exclude API definitions and the script dispatchers:
    # only concrete calls outside script_pokemon_util.c/scrcmd.c are declarations here.
    for path in ("src/battle_setup.c", "src/debug.c"):
        for line, content in enumerate(read(src / path).splitlines(), 1):
            m = NATIVE.search(content)
            if not m:
                continue
            opcode, argtext = m.groups()
            args = split_arguments(argtext)
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
            "area_map_inputs_sha256": _expansion_source_sha256(src),
            "scanned_files": sorted(includes),
            "scanned_sources_sha256": hashlib.sha256("".join(
                path + "\0" + read(src / path) for path in sorted(includes)).encode()).hexdigest(),
            "declarations": rows,
            "counts": {f"{status}_{kind}": count for (status, kind), count in sorted(counts.items())},
            "coverage": {
                "script_forms": ["givemon", "giveegg", "createmon", "setwildbattle"],
                "native_concrete_callers": ["src/battle_setup.c", "src/debug.c"],
                "source_roots": ["data/event_scripts.s", "data/mystery_gift.s"],
                "reference_config": {"GAME_VERSION": "EMERALD", "DEBUG": 0},
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
