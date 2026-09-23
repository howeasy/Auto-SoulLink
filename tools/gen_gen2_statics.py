"""Source/ROM catalog of scripted wild battles, including inactive callers.

Inventories source declarations, not runtime events. Byte witnesses are unique
matches within a source-label span, not qualified CPU instruction boundaries.
"""
from __future__ import annotations

import csv
import re

if __package__:
    from .gen2_source_data import rom_offset
    from .gen_gen2_area_map import build_area_map, source_lines
    from .gen_gen2_charmap import code, run_cli, verify_table
    from .gen_gen2_items import item_ids
    from .gen_gen2_species import const_block, const_blocks, parse_species_constants
else:
    from gen2_source_data import rom_offset
    from gen_gen2_area_map import build_area_map, source_lines
    from gen_gen2_charmap import code, run_cli, verify_table
    from gen_gen2_items import item_ids
    from gen_gen2_species import const_block, const_blocks, parse_species_constants


def arguments(text):
    return [part.strip() for part in next(csv.reader([text], skipinitialspace=True))]


def values(ctx):
    species, _ = parse_species_constants(ctx.read_source("constants/pokemon_constants.asm"))
    items, _ = item_ids(ctx.read_source("constants/item_constants.asm"))
    result = {**species, **{name: key for key, name in items.items()}}
    result.update(const_block(ctx.read_source("constants/move_constants.asm"), "NO_MOVE"))
    result.update(const_block(ctx.read_source("constants/trainer_data_constants.asm"), "TRAINERTYPE_NORMAL"))
    for block in const_blocks(ctx.read_source("constants/npc_trade_constants.asm")):
        result.update(block)
    egg = re.search(r"^DEF EGG_LEVEL EQU (\d+)\s*$", ctx.read_source("constants/battle_constants.asm"), re.M)
    if egg is None:
        raise ValueError("missing EGG_LEVEL")
    result["EGG_LEVEL"] = int(egg[1])
    return result


def number(token, names):
    if token in names:
        return names[token]
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"\$[0-9a-fA-F]+", token):
        return int(token[1:], 16)
    raise ValueError(f"unresolved source value: {token}")


def byte(token, names):
    value = number(token, names)
    if not 0 <= value <= 255:
        raise ValueError(f"not a byte: {token}")
    return value


def command_ids(ctx):
    result, index, macro = {}, None, False
    for raw in ctx.read_source("macros/scripts/events.asm").splitlines():
        line = code(raw)
        if line.startswith("MACRO "):
            macro = True
        elif line == "ENDM":
            macro = False
        elif not macro:
            if line.startswith("const_def"):
                index = int(line.split()[1], 0) if len(line.split()) > 1 else 0
            elif match := re.fullmatch(r"const (\w+_command)", line):
                if index is None or match[1] in result:
                    raise ValueError("invalid command enumeration")
                result[match[1].removesuffix("_command")] = index
                index += 1
    if not {"loadwildmon", "givepoke", "giveegg", "trade", "startbattle", "catchtutorial"} <= result.keys():
        raise ValueError("incomplete script command enumeration")
    return result


def script_rows(ctx, operations):
    """Map-file occurrence inventory retaining global/local symbol scopes."""
    found = []
    for path in sorted((ctx.source_dir / "maps").glob("*.asm")):
        raw = path.read_text(encoding="utf-8")
        if not any(re.search(rf"^\s*{re.escape(op)}(?:\s|$)", raw, re.M) for op in operations):
            continue
        relative = path.relative_to(ctx.source_dir).as_posix()
        lines = list(source_lines(ctx.read_source(relative), ctx.title))
        global_label, label, block, blocks = None, None, [], []
        for line_number, line in lines:
            match = re.fullmatch(r"([A-Za-z_][\w]*|\.[\w]+):{0,2}", line)
            if match and (":" in line or line.startswith(".")):
                if label:
                    blocks.append((label, block))
                name = match[1]
                if name.startswith("."):
                    if global_label is None:
                        raise ValueError("local label without parent")
                    label = global_label + name
                else:
                    global_label = label = name
                block = []
            else:
                block.append((line_number, line))
        if label:
            blocks.append((label, block))
        for index, (label, block) in enumerate(blocks):
            for line_number, line in block:
                op, _, rest = line.partition(" ")
                if op in operations:
                    if label not in ctx.symbols:
                        raise ValueError(f"missing script symbol {label}")
                    found.append({"path": relative, "line": line_number, "map_name": path.stem,
                                  "label": label, "operation": op, "arguments": arguments(rest),
                                  "block": block, "next_labels": [n for n, _ in blocks[index + 1:] if n in ctx.symbols],
                                  "source_text": raw})
    if not found:
        raise ValueError(f"empty command inventory for {operations}")
    return found


def witness(ctx, row, expected):
    bank, address = ctx.symbol(row["label"])
    start = rom_offset(bank, address)
    end = min(len(ctx.rom), (bank + 1) * 0x4000)
    for name in row["next_labels"]:
        other_bank, other_address = ctx.symbol(name)
        if other_bank == bank and other_address > address:
            end = min(end, rom_offset(other_bank, other_address))
            break
    segment = ctx.rom[start:end]
    matches = [i for i in range(len(segment)) if segment.startswith(expected, i)]
    if len(matches) != 1:
        raise ValueError(f"{row['path']}:{row['line']}: source/ROM witness missing or ambiguous")
    return {"kind": "unique_source_label_span", "symbol": row["label"],
            "bank": bank, "addr": address + matches[0], "flat": start + matches[0],
            "expected_hex": expected.hex(), "instruction_boundary": "UNQUALIFIED"}


def applicability(ctx, row):
    label, text = row["label"], row["source_text"]
    if ctx.title in ("gold", "silver") and "\tcheckver" in text:
        if (".Gold_" in label or ".Silver_" in label) and not re.search(r"checkver\s+iftrue \.Silver_Loop\b", text):
            raise ValueError("unresolved version menu dispatch")
        if ".Gold_" in label:
            return {"titles": ["gold"], "selected": ctx.title == "gold", "basis": "checkver Gold menu branch"}
        if ".Silver" in label:
            return {"titles": ["silver"], "selected": ctx.title == "silver", "basis": "checkver Silver branch"}
        block = [line for _, line in row["block"]]
        if "checkver" in block and "iftrue .Silver" in block:
            return {"titles": ["gold"], "selected": ctx.title == "gold", "basis": "checkver false fallthrough"}
    return {"titles": [ctx.title], "selected": True, "basis": "source occurrence; runtime reachability OPEN"}


def version_dispatch(ctx):
    if ctx.title == "crystal":
        return {"applicable": False}
    matches = [(line_no, int(match[1])) for line_no, line in
               source_lines(ctx.read_source("constants/misc_constants.asm"), ctx.title)
               if (match := re.fullmatch(r"DEF GS_VERSION EQU (\d+)", line))]
    if len(matches) != 1 or matches[0][1] != (0 if ctx.title == "gold" else 1):
        raise ValueError("unresolved Gold/Silver checkver value")
    line_no, value = matches[0]
    symbol = "Script_checkver.gs_version"
    offset = verify_table(ctx, symbol, bytes([value]))
    return {"applicable": True, "script_var": value, "symbol": symbol, "flat": offset,
            "source": source_ref(ctx, "constants/misc_constants.asm", line_no)}


def source_ref(ctx, path, line):
    return f"{ctx.lock['outputs'][ctx.artifact]['source']}@{ctx.source_commit} {path}:{line}"


# O-21 (docs/gen2/REVIEW_RECORD.md): Crystal's Tin Tower Suicune static
# (pokecrystal maps/TinTower1F.asm, TinTower1FSuicuneBattleScript.Next2) is a
# legend like the Gold/Silver roaming Suicune -- its area is legend_<species>
# and never claims the ordinary tin_tower map area for its capture. Keyed by
# source label so Gold/Silver, which have no such label, are untouched.
LEGEND_STATIC_OVERRIDES = {"TinTower1FSuicuneBattleScript.Next2": {"titles": ("crystal",), "species": 245}}


def legend_area_override(ctx, row, species):
    override = LEGEND_STATIC_OVERRIDES.get(row["label"])
    if override is None or ctx.title not in override["titles"]:
        return None
    if override["species"] != species:
        raise ValueError(f"legend static override species mismatch: {row['label']}")
    return f"legend_{species}"


# Specials whose engine asm writes wBattleType (pokecrystal engine/events/celebi.asm:54,296-299).
# ponytail: other specials are taken as not writing it; add a row when a pinned script needs one.
ASM_BATTLE_TYPES = {"CelebiShrineEvent": ("engine/events/celebi.asm", "CelebiEvent_SetBattleType")}


def asm_body(text, label):
    lines = [line for raw in text.splitlines() if (line := code(raw))]
    start = lines.index(f"{label}:")
    end = next((i for i in range(start + 1, len(lines)) if re.fullmatch(r"\w+:", lines[i])), len(lines))
    return lines[start + 1:end]


def runtime_battle_type(ctx, row, types):
    """wBattleType when the catch finalizes: NORMAL (CleanUpBattleRAM) unless the script's
    loadvar, catchtutorial or a verified asm special writes it."""
    found = []
    for _, line in row["block"]:
        op, _, rest = line.partition(" ")
        if line.startswith("loadvar VAR_BATTLETYPE,"):
            found.append(arguments(rest)[1])
        elif op == "catchtutorial":
            found.append(rest)
        elif op == "special" and rest in ASM_BATTLE_TYPES:
            path, routine = ASM_BATTLE_TYPES[rest]
            text = ctx.read_source(path)
            setter = asm_body(text, routine)
            if f"call {routine}" not in asm_body(text, rest) or len(setter) != 3                     or not setter[0].startswith("ld a, BATTLETYPE_") or setter[1:] != ["ld [wBattleType], a", "ret"]:
                raise ValueError(f"unverified battle-type special: {rest}")
            found.append(setter[0].removeprefix("ld a, "))
    if len(found) > 1:
        raise ValueError(f"ambiguous runtime battle type: {row['label']}")
    return types[found[0] if found else "BATTLETYPE_NORMAL"]


def public_row(ctx, row, maps):
    location = maps.get(row["map_name"])
    if location is None:
        raise ValueError(f"map has no verified header: {row['map_name']}")
    return {"id": f"{row['map_name']}:{row['label']}:{row['line']}",
            "map_name": row["map_name"], "map_group": location["map_group"],
            "map_number": location["map_number"], "area_id": location["area_id"],
            "source": source_ref(ctx, row["path"], row["line"]), "script": row["label"],
            "applicability": applicability(ctx, row)}


def build(ctx):
    """Generate declared wild battles without claiming successful captures."""
    names, commands = values(ctx), command_ids(ctx)
    types = const_block(ctx.read_source("constants/battle_constants.asm"), "BATTLETYPE_NORMAL")
    maps = {row["map_name"]: row for row in build_area_map(ctx).values()}
    rows = []
    for row in script_rows(ctx, {"loadwildmon"}):
        if len(row["arguments"]) != 2:
            raise ValueError("unsupported loadwildmon arguments")
        species, level = [byte(arg, names) for arg in row["arguments"]]
        if not 1 <= species <= 251 or not 1 <= level <= 100:
            raise ValueError("invalid scripted species/level")
        after = [line for n, line in row["block"] if n > row["line"]]
        while after and after[0].startswith("loadvar VAR_BATTLETYPE,"):
            after.pop(0)
        tutorial = bool(after and after[0].startswith("catchtutorial "))
        if not tutorial and (not after or after[0] != "startbattle"):
            raise ValueError(f"unknown battle dispatch after {row['label']}")
        trap = any("BATTLETYPE_TRAP" in line for _, line in row["block"])
        entry = public_row(ctx, row, maps)
        entry.update(species=species, species_const=row["arguments"][0], level=level,
                     kind="tutorial" if tutorial else "scripted_trap_battle" if trap else "scripted_wild_battle",
                     battle_type=[line for _, line in row["block"] if line.startswith("loadvar VAR_BATTLETYPE,")],
                     runtime_battle_type=runtime_battle_type(ctx, row, types),
                     source_unused=bool(re.search(rf"^{re.escape(row['label'])}:.*;.*unreferenced", row["source_text"], re.M)),
                     capture_success="OPEN", finalization="OPEN")
        legend_area = legend_area_override(ctx, row, species)
        if legend_area is not None:
            entry["area_id"] = legend_area
        entry["rom"] = witness(ctx, row, bytes([commands["loadwildmon"], species, level]))
        rows.append(entry)
    return {"schema": "gen2-static-encounters-v1", "generator": "gen_gen2_statics.py",
            "source": ctx.source_record(), "version_dispatch": version_dispatch(ctx), "encounters": rows,
            "open_obligations": ["runtime_script_reachability", "capture_success_and_finalization",
                                 "byte_witnesses_are_not_CPU_signal_sites"]}


def main(argv=None):
    return run_cli(argv, build, "static_encounters.json")


if __name__ == "__main__":
    raise SystemExit(main())
