#!/usr/bin/env python3
"""Generate selected Gen 2 species facts from pinned ASM, checked against built ROMs.

The index/national mapping and species object follow existing pack consumers.
Egg and invalid indices are separate from ordinary species. No runtime admission.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if __package__:
    from .gen2_source_data import ROOT, load_context, rom_offset
else:
    from gen2_source_data import ROOT, load_context, rom_offset

TITLES = ("crystal", "gold", "silver")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(text):
    text = text.strip()
    return int(text[1:], 16) if text.startswith("$") else int(text)


def const_blocks(text):
    """Parse the numbered const blocks used by these pinned species/item tables."""
    blocks, current, value = [], None, 0
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        match = re.fullmatch(r"const_def(?:\s+([^,]+))?", line)
        if match:
            value = number(match[1]) if match[1] else 0
            current = {}
            blocks.append(current)
        elif current is not None:
            match = re.fullmatch(r"const\s+([A-Z][A-Z0-9_]*)", line)
            if match:
                require(match[1] not in current, "duplicate source constant")
                current[match[1]] = value
                value += 1
            elif line.startswith("const_skip"):
                tokens = line.split()
                value += number(tokens[1]) if len(tokens) == 2 else 1
            elif line.startswith("const_next "):
                value = number(line.split()[1])
    return blocks


def const_block(text, member):
    matches = [block for block in const_blocks(text) if member in block]
    require(len(matches) == 1, f"missing/ambiguous source constant block: {member}")
    return matches[0]


def parse_species_constants(text):
    values = const_block(text, "BULBASAUR")
    ordinary = {name: value for name, value in values.items() if name != "EGG"}
    require(set(ordinary.values()) == set(range(1, 252)) and len(ordinary) == 251,
            "source species must be exactly 1..251")
    require(ordinary.get("BULBASAUR") == 1 and ordinary.get("CELEBI") == 251
            and values.get("EGG") == 253, "source species/egg boundary changed")
    return ordinary, values["EGG"]


def guard_context(ctx, title):
    artifact = {"crystal": "pokecrystal", "gold": "pokegold", "silver": "pokesilver"}[title]
    require(ctx.title == title and ctx.artifact == artifact, "wrong selected source artifact")
    source = ctx.lock["outputs"][artifact]["source"]
    require(ctx.source_commit == ctx.lock["sources"][source]["commit"], "source commit mismatch")


def source_inputs(ctx):
    names, egg = parse_species_constants(ctx.read_source("constants/pokemon_constants.asm"))
    data = ctx.read_source("constants/pokemon_data_constants.asm")
    return names, egg, data


def _gender_constants(ctx, data):
    require('DEF percent EQUS "* $ff / 100"' in ctx.read_source("macros/data.asm"),
            "source percent macro changed")
    result = {}
    for name, expr in re.findall(r"^DEF (GENDER_\w+)\s+EQU\s+([^;\r\n]+)", data, re.M):
        expr = expr.strip()
        match = re.fullmatch(r"(\d+) percent(?:\s*([+-])\s*(\d+))?", expr)
        if match:
            value = int(match[1]) * 255 // 100
            if match[2]:
                value += int(match[3]) * (1 if match[2] == "+" else -1)
        else:
            value = number(expr)
        result[name] = value & 255
    return result


def _name_bytes(ctx):
    text = ctx.read_source("data/pokemon/names.asm")
    names = re.findall(r'^\s*dname "([^"\n]*)"\s*$', text, re.M)
    require(len(names) == 256, "source names table must contain all 256 entries")
    # Unown/ASCII maps are declared inside pushc/popc; their terminators must not
    # overwrite the default game's @ byte.
    charmap, depth = {}, 0
    for raw in ctx.read_source("constants/charmap.asm").splitlines():
        line = raw.split(";", 1)[0].strip()
        if line == "pushc":
            depth += 1
        elif line == "popc":
            depth -= 1
            require(depth >= 0, "source charmap stack underflow")
        elif depth == 0:
            match = re.match(r'charmap "([^"\n]+)",\s*\$([0-9a-fA-F]{2})\b', line)
            if match:
                charmap[match[1]] = int(match[2], 16)
    require(depth == 0, "source charmap stack unclosed")
    match = re.search(r"^DEF NAME_LENGTH\s+EQU\s+(\d+)\s*$",
                      ctx.read_source("constants/text_constants.asm"), re.M)
    require(match is not None, "source NAME_LENGTH missing")
    width = int(match[1]) - 1
    require("def n = NAME_LENGTH - 1" in ctx.read_source("macros/data.asm"), "source dname changed")
    start = rom_offset(*ctx.symbol("PokemonNames"))
    for index, name in enumerate(names):
        require(len(name) <= width and all(char in charmap for char in name), "source name encoding unsupported")
        encoded = bytes([charmap[char] for char in name] + [charmap["@"]] * (width - len(name)))
        require(ctx.rom[start + index * width:start + (index + 1) * width] == encoded,
                f"ROM/source name mismatch at species {index + 1}")
    return names, {"symbol": "PokemonNames", "flat": start, "record_size": width, "entries": len(names)}


def build(title, root=ROOT):
    require(title in TITLES, "unsupported selected title")
    ctx = load_context(title, root=root)
    guard_context(ctx, title)
    consts, egg, data = source_inputs(ctx)
    types = const_block(ctx.read_source("constants/type_constants.asm"), "NORMAL")
    growth = const_block(data, "GROWTH_MEDIUM_FAST")
    groups = const_block(data, "EGG_MONSTER")
    items = const_block(ctx.read_source("constants/item_constants.asm"), "NO_ITEM")
    values = {**consts, **types, **growth, **groups, **items, **_gender_constants(ctx, data)}
    names, names_table = _name_bytes(ctx)
    source_table = ctx.read_source("data/pokemon/base_stats.asm")
    files = re.findall(r'^INCLUDE "(data/pokemon/base_stats/[^"\n]+)"', source_table, re.M)
    require(len(files) == 251, "source base stats inventory changed")
    base = ctx.symbol("wCurBaseData")
    end = ctx.symbol("wCurBaseDataEnd")
    require(base.bank == end.bank, "base-data struct crosses banks")
    width = end.address - base.address
    require("assert wCurBaseDataEnd - wCurBaseData == BASE_DATA_SIZE" in ctx.read_source("ram/wram.asm"),
            "source base-data size assertion missing")
    require(0 < width <= 255, "invalid base-data record size")
    offsets = {name: ctx.symbol(name).address - base.address for name in
               ("wBaseGrowthRate", "wBaseEggGroups")}
    start = rom_offset(*ctx.symbol("BaseData"))
    species = {}
    for sid, path in enumerate(files, 1):
        text = ctx.read_source(path)
        rows = [line.split(";", 1)[0].strip()[3:].strip() for line in text.splitlines()
                if line.split(";", 1)[0].strip().startswith("db ")]
        require(len(rows) == 11, f"unsupported base stats source shape: {path}")

        def decode(row):
            result = []
            for token in row.split(","):
                token = token.strip()
                require(token in values or re.fullmatch(r"-?\d+|\$[\da-fA-F]+", token),
                        f"unresolved source token {token}")
                result.append(values[token] if token in values else number(token))
            return result

        prefix = bytes(value for row in rows[:10] for value in decode(row))
        raw = ctx.rom[start + (sid - 1) * width:start + sid * width]
        require(len(raw) == width and len(prefix) == 17 and prefix[0] == sid
                and raw[:len(prefix)] == prefix, f"ROM/source base stats mismatch: {path}")
        growth_id = decode(rows[10])[0]
        egg_match = re.search(r"^\s*dn\s+(EGG_\w+),\s*(EGG_\w+)", text, re.M)
        require(egg_match is not None, f"source egg groups missing: {path}")
        egg_ids = [groups[egg_match[1]], groups[egg_match[2]]]
        require(raw[offsets["wBaseGrowthRate"]] == growth_id
                and raw[offsets["wBaseEggGroups"]] == (egg_ids[0] << 4 | egg_ids[1]),
                f"ROM/source growth/egg mismatch: {path}")
        type_ids = decode(rows[2])
        species[str(sid)] = {
            "const": rows[0], "name": names[sid - 1], "national_dex": sid,
            "classification": "ordinary",
            "base_stats": dict(zip(("hp", "attack", "defense", "speed", "special_attack", "special_defense"),
                                   decode(rows[1]), strict=True)),
            "types": [token.strip() for token in rows[2].split(",")], "type_ids": type_ids,
            "catch_rate": decode(rows[3])[0], "base_exp": decode(rows[4])[0],
            "held_item_ids": decode(rows[5]), "gender_ratio": decode(rows[6])[0],
            "egg_cycles": decode(rows[8])[0], "growth_rate": rows[10], "growth_rate_id": growth_id,
            "egg_groups": [egg_match[1], egg_match[2]], "egg_group_ids": egg_ids,
        }
    return {
        "generator": "tools/gen_gen2_species.py", "schema": "gen2-species-v1",
        "source": ctx.source_record(), "evidence_level": "SOURCE", "title": title,
        "index_to_national": {str(sid): sid for sid in range(1, 252)}, "species": species,
        "egg": {"index": egg, "name": names[egg - 1], "classification": "egg", "national_dex": None},
        "invalid_indices": [sid for sid in range(256) if sid not in range(1, 252) and sid != egg],
        "tables": {"base_data": {"symbol": "BaseData", "flat": start, "record_size": width,
                                  "entries": len(files)}, "names": names_table},
        "source_files": ["constants/pokemon_constants.asm", "constants/pokemon_data_constants.asm",
                         "data/pokemon/base_stats.asm", "data/pokemon/base_stats/*.asm",
                         "data/pokemon/names.asm", "constants/charmap.asm", "ram/wram.asm"],
    }


def write_packs(build_fn, filename, argv=None):
    parser = argparse.ArgumentParser(description=f"Generate source-qualified Gen 2 {filename}")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or args.root / "data/games"
    try:
        pending = []
        for title in TITLES:
            pack = build_fn(title, root=args.root)
            data = (json.dumps(pack, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            path = out_dir / f"gen2_{title}" / filename
            if args.check:
                require(path.exists() and path.read_bytes() == data, f"{path}: stale or missing")
            else:
                pending.append((path, data))
        for path, data in pending:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        print(f"{filename}: all three selected titles verified (SOURCE only)")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Gen 2 {filename} refused: {exc}", file=sys.stderr)
        return 1


def main(argv=None):
    return write_packs(build, "species_index.json", argv)


if __name__ == "__main__":
    raise SystemExit(main())
