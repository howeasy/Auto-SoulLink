"""Generate map identity labels and ROM-verified native landmark names per title.

An individual interior map has a source constant, not a unique native text name.
`name` is explicitly a mechanical source-constant label; `landmark_name` comes
from the cartridge text. Group:number is the key; ordinary maps are not merged.
"""
from __future__ import annotations

import json
import re

if __package__:
    from .gen_gen2_charmap import (
        constants,
        encode,
        integer,
        parse_charmap,
        run_cli,
        source_lines,
        table_bytes,
        verify_table,
    )
else:
    from gen_gen2_charmap import (
        constants,
        encode,
        integer,
        parse_charmap,
        run_cli,
        source_lines,
        table_bytes,
        verify_table,
    )


def map_constants(text: str) -> list[list[dict]]:
    groups, current, seen = [], None, set()
    for line in source_lines(text):
        if line in ("const_def", "DEF NUM_MAP_GROUPS EQU const_value"):
            continue
        if re.fullmatch(r"newgroup\s+\w+", line):
            if current is not None:
                raise ValueError("map group missing endgroup")
            current = []
            groups.append(current)
        elif line == "endgroup":
            if not current:
                raise ValueError("empty/unmatched map group")
            current = None
        elif match := re.fullmatch(r"map_const\s+(\w+),\s*(\d+),\s*(\d+)", line):
            if current is None or match[1] in seen:
                raise ValueError("map outside group or duplicate map constant")
            width, height = int(match[2]), int(match[3])
            if not 1 <= width <= 255 or not 1 <= height <= 255 or len(current) >= 255:
                raise ValueError("map dimension/count outside byte bounds")
            current.append({"constant": match[1], "width_blocks": width, "height_blocks": height})
            seen.add(match[1])
        else:
            raise ValueError(f"unsupported map constants: {line}")
    if current is not None or not groups or len(groups) > 255:
        raise ValueError("unterminated/invalid map groups")
    return groups


def map_rows(text: str) -> tuple[list[str], dict[str, list[list[str]]]]:
    pointers, groups, current = [], {}, None
    for line in source_lines(text):
        if line == "MapGroupPointers::" or line.startswith(("table_width ", "assert_table_length ")):
            continue
        if match := re.fullmatch(r"dw\s+(MapGroup_\w+)", line):
            pointers.append(match[1])
        elif match := re.fullmatch(r"(MapGroup_\w+):", line):
            current = match[1]
            if current in groups:
                raise ValueError("duplicate map group label")
            groups[current] = []
        elif line.startswith("map ") and current:
            row = [part.strip() for part in line[4:].split(",")]
            if len(row) != 8:
                raise ValueError("map header must have eight source arguments")
            groups[current].append(row)
        else:
            raise ValueError(f"unsupported map header source: {line}")
    if not pointers or len(pointers) != len(set(pointers)) or set(pointers) != set(groups):
        raise ValueError("map group pointer coverage mismatch")
    return pointers, groups


def landmarks(ctx, chars) -> dict[int, dict]:
    values = constants(ctx.read_source("constants/landmark_constants.asm"))
    entries, texts = [], {}
    for line in source_lines(ctx.read_source("data/maps/landmarks.asm")):
        if line in ("Landmarks:", "table_width 4"):
            continue
        if line.startswith("assert_table_length "):
            if len(entries) != integer(line.removeprefix("assert_table_length "), values):
                raise ValueError("landmark intermediate/final table count disagrees")
            continue
        if match := re.fullmatch(r"landmark\s+(-?\d+),\s*(-?\d+),\s*(\w+)", line):
            entries.append((int(match[1]) + 8, int(match[2]) + 16, match[3]))
        elif match := re.fullmatch(r'(\w+):\s+db\s+("(?:\\.|[^"\\])*")', line):
            if match[1] in texts:
                raise ValueError("duplicate landmark text label")
            texts[match[1]] = json.loads(match[2])
        else:
            raise ValueError(f"unsupported landmark source: {line}")
    if len(entries) != values["NUM_LANDMARKS"]:
        raise ValueError("landmark count mismatch")
    bank = ctx.symbol("Landmarks").bank
    raw, result = bytearray(), {}
    for index, (x, y, label) in enumerate(entries):
        name = texts[label]
        if not name.endswith("@") or "@" in name[:-1] or not 0 <= x <= 255 or not 0 <= y <= 255:
            raise ValueError("invalid landmark coordinate/terminator")
        symbol = ctx.symbol(label)
        if symbol.bank != bank:
            raise ValueError("landmark pointer targets another ROM bank")
        native = encode(name, chars["encoding"])
        if len(native) > 64:
            raise ValueError("landmark text exceeds bounded reader")
        verify_table(ctx, label, native)
        raw.extend([x, y, symbol.address & 255, symbol.address >> 8])
        result[index] = {"label": label, "native_name": name[:-1],
                         "name": name[:-1].replace("<BSP>", " ").replace("<WBR>", ""),
                         "x": x, "y": y, "bank": bank, "address": symbol.address}
    verify_table(ctx, "Landmarks", bytes(raw))
    return result


def build(ctx) -> dict:
    """Generate every map group/number and validate its native landmark linkage."""
    grouped = map_constants(ctx.read_source("constants/map_constants.asm"))
    pointers, rows = map_rows(ctx.read_source("data/maps/maps.asm"))
    if len(grouped) != len(pointers):
        raise ValueError("map constant/header group counts disagree")
    layout_text = ctx.read_source("constants/map_data_constants.asm")
    sentinels = constants(layout_text.split("; map struct members")[0])
    if sentinels["MAPGROUP_NONE"] != 0 or sentinels["MAP_NONE"] != 0:
        raise ValueError("map group/number sentinel changed")
    layout = constants(layout_text[layout_text.index("rsreset"):layout_text.index("; map environments")])
    if layout["MAP_LENGTH"] != 9 or layout["MAP_LOCATION"] != 5:
        raise ValueError("unsupported map header layout")
    chars = parse_charmap(ctx.read_source("constants/charmap.asm"))
    places = landmarks(ctx, chars)
    landmark_ids = constants(ctx.read_source("constants/landmark_constants.asm"))
    pointer_bank = ctx.symbol("MapGroupPointers").bank
    pointer_data, maps = bytearray(), {}
    for group, (label, expected) in enumerate(zip(pointers, grouped, strict=True), 1):
        symbol = ctx.symbol(label)
        if symbol.bank != pointer_bank or len(rows[label]) != len(expected):
            raise ValueError("map group bank/row coverage mismatch")
        pointer_data.extend([symbol.address & 255, symbol.address >> 8])
        offset, data = table_bytes(ctx, label, 9 * len(expected))
        for number, (metadata, row) in enumerate(zip(expected, rows[label], strict=True), 1):
            if row[0].replace("_", "").upper() != metadata["constant"].replace("_", ""):
                raise ValueError(f"map {group}:{number}: constant/header order disagreement: {row[0]} vs {metadata['constant']}")
            record = data[(number - 1) * 9:number * 9]
            attributes = ctx.symbol(row[0] + "_MapAttributes")
            location = landmark_ids[row[3]]
            if record[0] != attributes.bank or int.from_bytes(record[3:5], "little") != attributes.address or record[5] != location:
                raise ValueError(f"map {group}:{number}: ROM header pointer/landmark disagrees")
            if location not in places:
                raise ValueError("map points beyond native landmarks")
            maps[f"{group}:{number}"] = {"group": group, "number": number, "encoded_id": group * 256 + number,
                **metadata, "name": metadata["constant"].replace("_", " "),
                "name_origin": "source constant humanization", "source_label": row[0],
                "header_offset": offset + (number - 1) * 9, "landmark_id": location,
                "landmark_name": places[location]["name"], "native_landmark_name": places[location]["native_name"]}
    verify_table(ctx, "MapGroupPointers", bytes(pointer_data))
    return {"schema": "gen2-map-names-v1", "generator": "tools/gen_gen2_map_names.py", "source": ctx.source_record(),
            "title": ctx.title, "key_format": "group:number", "maps": maps,
            "landmarks": {str(key): value for key, value in places.items()},
            "sentinels": {"0:0": "MAPGROUP_NONE/MAP_NONE"}}


def main(argv=None) -> int:
    return run_cli(argv, build, "map_names.json")


if __name__ == "__main__":
    raise SystemExit(main())
