#!/usr/bin/env python3
"""Generate title-specific map areas from pinned source and verified ROM headers.

Numeric keys preserve the area-map contract. Landmark membership collapses
floors, methods and times; the contest has its owner-approved separate area.
This generator establishes no acquisition events or runtime permissions.

`fishing_water` carries the accepted fishing-association rule (F6 in
docs/gen2/reviews/OMP_FISHING_ASSOCIATION_2026-09-22.md). A rod's own gate is the FACED
quadrant's collision permission plus the current map header's fish group, and no map
inherits another map's group; the flag is true when the map holds a water-permission
quadrant with a standable 4-neighbour. Blockdata, the tileset collision table and the
permission table come from the verified ROM -- the same bytes the engine loads -- and the
permission table's meaning is cross-checked against data/collision/collision_permissions.asm.
The header's fish group is checked separately by the adapter; the flag makes no
catchability claim on its own.

Known limits (U1-U2 in the same review): a standing tile supplied by a connection strip is
not modelled, so water reachable only from a connected neighbour's strip reads false;
walkable-region connectivity inside the map is not modelled either; and story-time blockdata
changes are not modelled at all.
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


def map_const_table(text, title):
    """Parse map_const entries into group order and per-map dimensions (32x32 blocks)."""
    groups, current, sizes, seen = [], None, {}, set()
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
            width, height = integer(width), integer(height)
            if not 1 <= width <= 255 or not 1 <= height <= 255:
                raise ValueError(f"map dimensions out of bounds: {name}")
            seen.add(name)
            sizes[name] = (width, height)
            current.append(name)
    if current is not None or not groups or len(groups) > 255:
        raise ValueError("incomplete/out-of-bounds map groups")
    if any(len(group) > 255 for group in groups):
        raise ValueError("map number exceeds byte")
    return groups, sizes


def map_constants(text, title):
    """Map group order; see map_const_table for the per-map dimensions."""
    return map_const_table(text, title)[0]


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


def far_bytes(ctx, bank, address, length, label):
    """Read `length` bytes at bank:address, with rom_bytes' bank and bounds refusals."""
    if __package__:
        from .gen2_source_data import rom_offset
    else:
        from gen2_source_data import rom_offset
    if length < 1 or (address & 0x3FFF) + length > 0x4000:
        raise ValueError(f"{label}: table crosses ROM bank")
    start = rom_offset(bank, address)
    if start + length > len(ctx.rom):
        raise ValueError(f"{label}: table outside ROM")
    return ctx.rom[start:start + length]


def source_equate(text, title, name):
    """One numeric `DEF <name> EQU <int>` from the pinned source."""
    for _, line in source_lines(text, title):
        if match := re.fullmatch(rf"DEF {name}\s+EQU\s+(.+)", line):
            return integer(match[1])
    raise ValueError(f"missing numeric equate: {name}")


def collision_names(text, title):
    """Collision bytes and permission values (constants/collision_constants.asm)."""
    result = {}
    for _, line in source_lines(text, title):
        if match := re.fullmatch(r"DEF ([A-Z_0-9]+)\s+EQU\s+(\$[0-9a-fA-F]+)", line):
            if match[1] in result:
                raise ValueError(f"duplicate collision constant: {match[1]}")
            result[match[1]] = integer(match[2])
    for required in ("COLL_FLOOR", "COLL_PIT", "LAND_TILE", "WATER_TILE", "WALL_TILE", "TALK",
                     "HI_NYBBLE_LEDGES", "HI_NYBBLE_SIDE_WALLS", "HI_NYBBLE_SIDE_BUOYS"):
        if required not in result:
            raise ValueError(f"missing collision constant: {required}")
    if result["COLL_FLOOR"] != 0:
        raise ValueError("COLL_FLOOR is not the first collision byte")
    return result


def collision_permissions(text, title, names):
    """CollisionPermissionTable, in COLL_* index order (data/collision/collision_permissions.asm)."""
    result = []
    for line_no, line in source_lines(text, title):
        if line.startswith("assert_table_length "):
            if integer(line.removeprefix("assert_table_length").strip()) != len(result):
                raise ValueError(f"line {line_no}: permission table length mismatch")
            continue
        if not line.startswith("db "):
            continue
        value = 0
        for part in line[3:].split("|"):
            token = part.strip()
            value |= names[token] if token in names else integer(token)
        result.append(value)
    if len(result) != 256 or result[names["COLL_FLOOR"]] != names["LAND_TILE"]:
        raise ValueError("collision permission table is not the 256-entry COLL_* table")
    return result


def _permission(permissions, collision):
    """Permission of a collision byte, refusing bytes the table cannot index."""
    if not 0 <= collision < len(permissions):
        raise ValueError(f"collision byte out of range: {collision}")
    return permissions[collision] & 0x0F


def fishing_water(blocks, width, height, collision_table, permissions, constants):
    """True when a rod on this map can face water with a tile to stand on.

    Engine gate, both titles: FishFunction refuses unless the FACED quadrant's permission is
    WATER_TILE (engine/events/overworld.asm:1444-1463, home/map_objects.asm:88-108) and the
    current map header's fish group is non-zero (home/map.asm:2265-2277); block byte 0 is the
    engine's "no metatile" case and reads as wall (home/map.asm:1713-1716). A standing tile
    keeps LAND_TILE permission without a nybble GetMovementPermissions refuses
    (home/map.asm:1591-1650) and is one the player can occupy -- a hop ledge or a pit is never
    a standing tile. F6 in docs/gen2/reviews/OMP_FISHING_ASSOCIATION_2026-09-22.md.

    blocks: one metatile id per 32x32 block. collision_table: 4 collision bytes per metatile
    in TL, TR, BL, BR order (home/map.asm:1726-1734 selects by the tile's own parity).
    """
    if len(blocks) != width * height:
        raise ValueError("blockdata size differs from the map dimensions")
    land, water = constants["LAND_TILE"] & 0x0F, constants["WATER_TILE"] & 0x0F
    refused = (constants["HI_NYBBLE_LEDGES"], constants["HI_NYBBLE_SIDE_WALLS"],
               constants["HI_NYBBLE_SIDE_BUOYS"], constants["COLL_PIT"] & 0xF0)
    tiles_x, tiles_y = 2 * width, 2 * height
    for y in range(tiles_y):
        for x in range(tiles_x):
            metatile = blocks[(y // 2) * width + (x // 2)]
            if metatile == 0:
                continue
            if 4 * metatile + 4 > len(collision_table):
                raise ValueError(f"metatile {metatile} outside the tileset collision table")
            if _permission(permissions, collision_table[4 * metatile + (x & 1) + 2 * (y & 1)]) != water:
                continue
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if not (0 <= nx < tiles_x and 0 <= ny < tiles_y):
                    continue
                neighbour = blocks[(ny // 2) * width + (nx // 2)]
                if neighbour == 0 or 4 * neighbour + 4 > len(collision_table):
                    continue
                collision = collision_table[4 * neighbour + (nx & 1) + 2 * (ny & 1)]
                if _permission(permissions, collision) == land and (collision & 0xF0) not in refused:
                    return True
    return False


def build_area_map(ctx):
    groups, sizes = map_const_table(ctx.read_source("constants/map_constants.asm"), ctx.title)
    landmark_source = ctx.read_source("constants/landmark_constants.asm").split("DEF NUM_LANDMARKS", 1)[0]
    landmarks = constants(landmark_source, "LANDMARK_", ctx.title)
    fish = constants(ctx.read_source("constants/map_data_constants.asm"), "FISHGROUP_", ctx.title)
    if set(landmarks.values()) != set(range(len(landmarks))) or set(fish.values()) != set(range(len(fish))):
        raise ValueError("landmark/fishing indexes are not contiguous")
    tileset_source = ctx.read_source("constants/tileset_constants.asm")
    tilesets = constants(tileset_source, "TILESET_", ctx.title)
    tileset_length = source_equate(tileset_source, ctx.title, "TILESET_LENGTH")
    collisions = collision_names(ctx.read_source("constants/collision_constants.asm"), ctx.title)
    permissions = collision_permissions(ctx.read_source("data/collision/collision_permissions.asm"),
                                        ctx.title, collisions)
    if bytes(permissions) != rom_bytes(ctx, "CollisionPermissionTable", 256)[1]:
        raise ValueError("collision permission table differs between source and ROM")
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
            if landmark not in landmarks or fishing not in fish or fields[1] not in tilesets:
                raise ValueError(f"{name}: unresolved landmark/fishing/tileset name")
            attrs = ctx.symbol(name + "_MapAttributes")
            flat, raw = rom_bytes(ctx, pointer, 9, (number - 1) * 9)
            if (raw[0] != attrs.bank or int.from_bytes(raw[3:5], "little") != attrs.address
                    or raw[5] != landmarks[landmark] or raw[8] != fish[fishing]):
                raise ValueError(f"{name}: source/header ROM mismatch")
            if raw[1] != tilesets[fields[1]]:
                raise ValueError(f"{name}: source/header tileset mismatch")
            width, height = sizes[map_const]
            _, attr_raw = rom_bytes(ctx, name + "_MapAttributes", 6)
            blocks = ctx.symbol(name + "_Blocks")
            blocks_address = int.from_bytes(attr_raw[4:6], "little")
            if (attr_raw[2], attr_raw[1]) != (width, height):
                raise ValueError(f"{name}: map_const dimensions differ from the map attributes")
            if (blocks.bank, blocks.address) != (attr_raw[3], blocks_address):
                raise ValueError(f"{name}: blockdata pointer mismatch")
            blockdata = far_bytes(ctx, attr_raw[3], blocks_address, width * height,
                                  f"{name} blockdata")
            _, tileset = rom_bytes(ctx, "Tilesets", tileset_length, raw[1] * tileset_length)
            collision_table = far_bytes(ctx, tileset[6], int.from_bytes(tileset[7:9], "little"),
                                        4 * (max(blockdata) + 1), f"{name} tileset collision")
            area_id = landmark.removeprefix("LANDMARK_").lower()
            if map_const == "NATIONAL_PARK_BUG_CONTEST":
                area_id = "national_park_contest"
            result[str(group_id * 256 + number)] = {
                "area_id": area_id, "name": names[name_labels[landmarks[landmark]]],
                "map_group": group_id, "map_number": number, "map_const": map_const,
                "map_name": name, "environment": environment,
                "landmark": landmarks[landmark], "landmark_const": landmark,
                "fishing_group": fish[fishing],
                "fishing_water": fishing_water(blockdata, width, height, collision_table,
                                               permissions, collisions),
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
