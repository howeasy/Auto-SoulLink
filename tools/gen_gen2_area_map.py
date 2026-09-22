#!/usr/bin/env python3
"""Generate title-specific map areas from pinned source and verified ROM headers.

Numeric keys preserve the area-map contract. Landmark membership collapses
floors, methods and times; the contest has its owner-approved separate area.
This generator establishes no acquisition events or runtime permissions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TITLES = ("crystal", "gold", "silver")


def source_lines(text, title):
    """Read the pinned data subset, preserving lines and selecting title branches."""
    stack = []
    active, macro = True, False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if line.startswith("MACRO "):
            if macro:
                raise ValueError(f"line {number}: nested macro")
            macro = True
            continue
        if line == "ENDM":
            macro = False
            continue
        if macro or not line:
            continue
        if match := re.fullmatch(r"(IF|ELIF) DEF\(_(GOLD|SILVER|CRYSTAL)\)", line):
            chosen = match[2].lower() == title
            if match[1] == "IF":
                stack.append([active, chosen])
                active = active and chosen
            else:
                if not stack:
                    raise ValueError("ELIF without IF")
                parent, matched = stack[-1]
                active = parent and not matched and chosen
                stack[-1][1] |= chosen
            continue
        if line == "ELSE":
            if not stack:
                raise ValueError("ELSE without IF")
            parent, matched = stack[-1]
            active = parent and not matched
            stack[-1][1] = True
            continue
        if line == "ENDC":
            if not stack:
                raise ValueError("ENDC without IF")
            active = stack.pop()[0]
            continue
        if line.startswith(("IF ", "ELIF ")):
            raise ValueError(f"unsupported source condition: {line}")
        if active:
            yield number, line
    if macro or stack:
        raise ValueError("unterminated source macro/conditional")


def integer(token):
    token = token.strip()
    if not re.fullmatch(r"-?(?:[0-9]+|\$[0-9a-fA-F]+)", token):
        raise ValueError(f"unsupported integer: {token}")
    return int(token[1:], 16) if token.startswith("$") else int(token)


def constants(text, prefix, title):
    """Read selected named constants from explicit numeric const_def sequences."""
    result, value = {}, None
    for _, line in source_lines(text, title):
        if line == "const_def" or line.startswith("const_def "):
            try:
                value = integer(line.removeprefix("const_def").strip() or "0")
            except ValueError:
                value = None
        elif line == "const_skip" or line.startswith("const_skip "):
            try:
                value = value + integer(line.removeprefix("const_skip").strip() or "1")
            except (TypeError, ValueError):
                value = None
        elif match := re.fullmatch(r"const ([A-Z_0-9]+)", line):
            name = match[1]
            if name.startswith(prefix):
                if value is None or name in result:
                    raise ValueError(f"unresolved/duplicate constant: {name}")
                result[name] = value
            if value is not None:
                value += 1
    if not result:
        raise ValueError(f"missing constants: {prefix}")
    return result


def map_constants(text, title):
    groups, current, seen = [], None, set()
    for line_no, line in source_lines(text, title):
        if line.startswith("newgroup "):
            if current is not None:
                raise ValueError("map group missing endgroup")
            current = []
            groups.append(current)
        elif line == "endgroup":
            if not current:
                raise ValueError("empty/missing map group")
            current = None
        elif line.startswith("map_const "):
            values = [part.strip() for part in line[10:].split(",")]
            if current is None or len(values) != 3 or values[0] in seen:
                raise ValueError(f"invalid map constant at line {line_no}")
            name, width, height = values
            if not 1 <= integer(width) <= 255 or not 1 <= integer(height) <= 255:
                raise ValueError(f"map dimensions out of bounds: {name}")
            seen.add(name)
            current.append(name)
    if current is not None or not groups or len(groups) > 255:
        raise ValueError("incomplete/out-of-bounds map groups")
    if any(len(group) > 255 for group in groups):
        raise ValueError("map number exceeds byte")
    return groups


def rom_bytes(ctx, symbol, length, delta=0):
    if __package__:
        from .gen2_source_data import rom_offset
    else:
        from gen2_source_data import rom_offset
    sym = ctx.symbol(symbol)
    start = rom_offset(sym.bank, sym.address) + delta
    if delta < 0 or length < 0 or (sym.address & 0x3fff) + delta + length > 0x4000:
        raise ValueError(f"{symbol}: table crosses ROM bank")
    if start + length > len(ctx.rom):
        raise ValueError(f"{symbol}: table outside ROM")
    return start, ctx.rom[start:start + length]


def build_area_map(ctx):
    groups = map_constants(ctx.read_source("constants/map_constants.asm"), ctx.title)
    landmark_source = ctx.read_source("constants/landmark_constants.asm").split("DEF NUM_LANDMARKS", 1)[0]
    landmarks = constants(landmark_source, "LANDMARK_", ctx.title)
    fish = constants(ctx.read_source("constants/map_data_constants.asm"), "FISHGROUP_", ctx.title)
    if set(landmarks.values()) != set(range(len(landmarks))) or set(fish.values()) != set(range(len(fish))):
        raise ValueError("landmark/fishing indexes are not contiguous")
    landmark_lines = list(source_lines(ctx.read_source("data/maps/landmarks.asm"), ctx.title))
    name_labels = [line.split(",")[-1].strip() for _, line in landmark_lines
                   if line.startswith("landmark ")]
    names = {}
    for _, line in landmark_lines:
        if match := re.fullmatch(r'(\w+):\s+db "([^"@]*)@"', line):
            names[match[1]] = match[2].replace("<BSP>", " ")
    if len(name_labels) != len(landmarks) or any(label not in names for label in name_labels):
        raise ValueError("missing/ambiguous landmark display names")

    header_lines = list(source_lines(ctx.read_source("data/maps/maps.asm"), ctx.title))
    pointers = [line[3:].strip() for _, line in header_lines if line.startswith("dw MapGroup_")]
    if len(pointers) != len(groups) or len(set(pointers)) != len(pointers):
        raise ValueError("map group pointer/count mismatch")
    _, pointer_bytes = rom_bytes(ctx, "MapGroupPointers", len(groups) * 2)
    headers, group = {}, None
    for line_no, line in header_lines:
        if line.endswith(":") and line[:-1] in pointers:
            group = line[:-1]
            headers[group] = []
        elif line.startswith("map "):
            fields = [part.strip() for part in line[4:].split(",")]
            if group is None or len(fields) != 8:
                raise ValueError(f"invalid map header at line {line_no}")
            headers[group].append((line_no, fields))

    result = {}
    rom_sha256 = hashlib.sha256(ctx.rom).hexdigest()
    for group_id, (pointer, map_names) in enumerate(zip(pointers, groups, strict=True), 1):
        rows = headers.get(pointer, [])
        if len(rows) != len(map_names):
            raise ValueError(f"{pointer}: header/constant count mismatch")
        sym = ctx.symbol(pointer)
        if int.from_bytes(pointer_bytes[2 * (group_id - 1):2 * group_id], "little") != sym.address:
            raise ValueError(f"{pointer}: ROM group pointer mismatch")
        if sym.bank != ctx.symbol("MapGroupPointers").bank:
            raise ValueError("map group pointers cross bank")
        for number, (map_const, (line_no, fields)) in enumerate(zip(map_names, rows, strict=True), 1):
            name, _, environment, landmark, _, _, _, fishing = fields
            if landmark not in landmarks or fishing not in fish:
                raise ValueError(f"{name}: unresolved landmark/fishing name")
            attrs = ctx.symbol(name + "_MapAttributes")
            flat, raw = rom_bytes(ctx, pointer, 9, (number - 1) * 9)
            if (raw[0] != attrs.bank or int.from_bytes(raw[3:5], "little") != attrs.address
                    or raw[5] != landmarks[landmark] or raw[8] != fish[fishing]):
                raise ValueError(f"{name}: source/header ROM mismatch")
            area_id = landmark.removeprefix("LANDMARK_").lower()
            if map_const == "NATIONAL_PARK_BUG_CONTEST":
                area_id = "national_park_contest"
            result[str(group_id * 256 + number)] = {
                "area_id": area_id, "name": names[name_labels[landmarks[landmark]]],
                "map_group": group_id, "map_number": number, "map_const": map_const,
                "map_name": name, "environment": environment,
                "landmark": landmarks[landmark], "landmark_const": landmark,
                "fishing_group": fish[fishing],
                "source": {"commit": ctx.source_commit, "artifact": ctx.artifact,
                           "file": "data/maps/maps.asm", "line": line_no,
                           "rom_sha256": rom_sha256, "header_flat": flat,
                           "header_hex": raw.hex()},
            }
    if not any(row["area_id"] == "national_park_contest" for row in result.values()):
        raise ValueError("contest map missing from source")
    return result


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def run_generator(argv, filename, builder):
    from tools.gen2_source_data import load_context
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", choices=(*TITLES, "all"), default="all")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    titles = TITLES if args.title == "all" else (args.title,)
    try:
        # Validate every requested title before publishing any output.
        outputs = [(args.root / "data/games" / f"gen2_{title}" / filename,
                    json_bytes(builder(load_context(title, root=args.root)))) for title in titles]
        stale = [str(path) for path, raw in outputs if not path.is_file() or path.read_bytes() != raw]
        if args.check and stale:
            raise ValueError("missing/stale generated output: " + ", ".join(stale))
        if not args.check:
            for path, raw in outputs:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        print(f"{'checked' if args.check else 'generated'} {len(outputs)} {filename} packs")
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1


def main(argv=None):
    return run_generator(argv, "area_map.json", build_area_map)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
