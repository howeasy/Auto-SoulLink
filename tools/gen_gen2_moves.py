"""Generate all 251 Gen 2 move rows, cross-checking source expansion against ROM."""
from __future__ import annotations

import json
import re

if __package__:
    from .gen_gen2_charmap import (
        constants,
        encode,
        integer,
        name_list,
        parse_charmap,
        run_cli,
        source_lines,
        verify_table,
    )
else:
    from gen_gen2_charmap import (
        constants,
        encode,
        integer,
        name_list,
        parse_charmap,
        run_cli,
        source_lines,
        verify_table,
    )


def type_names(ctx, values: dict[str, int]) -> dict[int, str]:
    """Expand the pinned type pointer table, including Crystal's explicit REPT."""
    labels, strings, repeat, repeat_rows = [], {}, None, 0
    for line in source_lines(ctx.read_source("data/types/names.asm")):
        if line in ("TypeNames:", "table_width 2"):
            continue
        if line.startswith("rept "):
            if repeat is not None:
                raise ValueError("nested type-name repetition")
            repeat, repeat_rows = integer(line[5:], values), 0
            if not 0 <= repeat <= 255:
                raise ValueError("invalid type-name repeat count")
        elif line == "endr":
            if repeat is None or repeat_rows != 1:
                raise ValueError("unsupported type-name repetition body")
            repeat = None
        elif match := re.fullmatch(r"dw\s+(\w+)", line):
            labels.extend([match[1]] * (repeat if repeat is not None else 1))
            repeat_rows += 1
        elif line.startswith("assert_table_length "):
            if len(labels) != integer(line.removeprefix("assert_table_length "), values):
                raise ValueError("type-name table count mismatch")
        elif match := re.fullmatch(r'(\w+):\s+db\s+("(?:\\.|[^"\\])*")', line):
            if match[1] in strings:
                raise ValueError("duplicate type-name label")
            strings[match[1]] = json.loads(match[2])
        else:
            raise ValueError(f"unsupported type-name source: {line}")
    if repeat is not None or len(labels) != values["TYPES_END"]:
        raise ValueError("type-name coverage mismatch")
    chars = parse_charmap(ctx.read_source("constants/charmap.asm"))
    bank = ctx.symbol("TypeNames").bank
    raw, names = bytearray(), {}
    for index, label in enumerate(labels):
        symbol, text = ctx.symbol(label), strings[label]
        if symbol.bank != bank or not text.endswith("@") or "@" in text[:-1]:
            raise ValueError("type-name pointer/terminator invalid")
        verify_table(ctx, label, encode(text, chars["encoding"]))
        raw.extend([symbol.address & 255, symbol.address >> 8])
        names[index] = text[:-1].title()
    verify_table(ctx, "TypeNames", bytes(raw))
    return names


def explicit_damage_effects(ctx, values: dict[str, int]) -> set[int]:
    """Power0 is not sufficient: OHKO and Bide scripts explicitly apply damage."""
    labels = []
    for line in source_lines(ctx.read_source("data/moves/effects_pointers.asm")):
        if line in ("MoveEffectsPointers:", "table_width 2"):
            continue
        if line == "assert_table_length NUM_MOVE_EFFECTS":
            if len(labels) != values["NUM_MOVE_EFFECTS"]:
                raise ValueError("move effect pointer count mismatch")
        elif match := re.fullmatch(r"dw\s+(\w+)", line):
            labels.append(match[1])
        else:
            raise ValueError(f"unsupported move-effect pointers: {line}")
    if len(labels) != values["NUM_MOVE_EFFECTS"]:
        raise ValueError("move effect pointer coverage mismatch")
    scripts, current = {}, None
    for line in source_lines(ctx.read_source("data/moves/effects.asm")):
        if line == 'INCLUDE "data/moves/effects_pointers.asm"':
            continue
        if match := re.fullmatch(r"(\w+):", line):
            current = match[1]
            if current in scripts:
                raise ValueError("duplicate effect script label")
            scripts[current] = []
        elif current and re.fullmatch(r"[a-z][a-z0-9_]*(?:\s+[^:]+)?", line):
            scripts[current].append(line)
        else:
            raise ValueError(f"unsupported move-effect script source: {line}")
    bank = ctx.symbol("MoveEffectsPointers").bank
    raw, damaging = bytearray(), set()
    for index, label in enumerate(labels):
        symbol = ctx.symbol(label)
        if symbol.bank != bank or label not in scripts:
            raise ValueError("move effect target missing/outside pointer bank")
        raw.extend([symbol.address & 255, symbol.address >> 8])
        if "applydamage" in scripts[label]:
            damaging.add(index)
    verify_table(ctx, "MoveEffectsPointers", bytes(raw))
    return damaging


def move_rows(text: str) -> list[list[str]]:
    rows = []
    for line in source_lines(text):
        if line in ("Moves:", "table_width MOVE_LENGTH", "assert_table_length NUM_ATTACKS"):
            continue
        if not line.startswith("move "):
            raise ValueError(f"unsupported move source: {line}")
        row = [part.strip() for part in line.removeprefix("move ").split(",")]
        if len(row) != 7:
            raise ValueError("move requires seven fields")
        rows.append(row)
    if len(rows) != 251:
        raise ValueError(f"Moves: {len(rows)} rows != 251")
    return rows


def build(ctx) -> dict:
    """Generate ROM-verified move names, effects, type, power and raw probabilities."""
    names, table = name_list(ctx, "data/moves/names.asm", "MoveNames", "MOVE_NAME_LENGTH", 251)
    move_ids = constants(ctx.read_source("constants/move_constants.asm").split("; Battle animations")[0])
    if move_ids["NUM_ATTACKS"] != 251 or move_ids["NO_MOVE"] != 0 or move_ids["CANNOT_MOVE"] != 255:
        raise ValueError("move count/sentinel constants changed")
    types = constants(ctx.read_source("constants/type_constants.asm"))
    effects = constants(ctx.read_source("constants/move_effect_constants.asm"))
    names_by_type = type_names(ctx, types)
    zero_power_damage = explicit_damage_effects(ctx, effects)
    if not re.search(r"cp SPECIAL\s+jr nc, \.special", ctx.read_source("engine/battle/effect_commands.asm")):
        raise ValueError("native physical/special threshold branch changed")
    if not re.search(r'DEF percent EQUS "\* \$ff / 100"', ctx.read_source("macros/data.asm")):
        raise ValueError("unsupported native percent expansion")
    struct = ctx.read_source("constants/battle_constants.asm")
    match = re.search(r"rsreset\s+(DEF MOVE_ANIM[\s\S]*?DEF MOVE_LENGTH EQU _RS)", struct)
    if not match:
        raise ValueError("move record layout missing")
    layout = constants("rsreset\n" + match[1])
    fields = ("MOVE_ANIM", "MOVE_EFFECT", "MOVE_POWER", "MOVE_TYPE", "MOVE_ACC", "MOVE_PP", "MOVE_CHANCE")
    if [layout[name] for name in fields] != list(range(7)) or layout["MOVE_LENGTH"] != 7:
        raise ValueError("unsupported move record layout")
    values, raw, moves = {**move_ids, **types, **effects}, bytearray(), []
    for number, (name, row) in enumerate(zip(names, move_rows(ctx.read_source("data/moves/moves.asm")), strict=True), 1):
        animation, effect, power, type_id, accuracy, pp, chance = [integer(token, values) for token in row]
        if animation != number or not 0 <= pp <= 40 or not 0 <= accuracy <= 100 or not 0 <= chance <= 100:
            raise ValueError(f"move {number}: ID/PP/percentage bounds disagree")
        record = [animation, effect, power, type_id, accuracy * 255 // 100, pp, chance * 255 // 100]
        if any(not 0 <= value <= 255 for value in record):
            raise ValueError(f"move {number}: invalid record byte")
        raw.extend(record)
        split = ("Status" if power == 0 and effect not in zero_power_damage else
                 "Physical" if type_id < types["SPECIAL"] else "Special")
        moves.append({"id": number, "constant": row[0], "internal_name": row[0],
                              "name": name.title(), "native_name": name, "animation": animation,
                              "effect": effect, "effect_constant": row[1], "power": power,
                              "type": names_by_type[type_id], "type_id": type_id, "type_constant": row[3],
                              "split": split, "accuracy": accuracy, "accuracy_percent": accuracy,
                              "accuracy_byte": record[4], "pp": pp, "effect_chance": chance,
                              "effect_chance_percent": chance, "effect_chance_byte": record[6]})
    offset = verify_table(ctx, "Moves", bytes(raw))
    return {"schema": "gen2-moves-v1", "generator": "tools/gen_gen2_moves.py", "source": ctx.source_record(),
            "title": ctx.title, "tables": {"names": table, "moves": {"symbol": "Moves", "offset": offset, "rows": 251, "record_size": 7}},
            "split_source": {"special_type_threshold": types["SPECIAL"],
                             "status_rule": "zero power unless native effect script explicitly invokes applydamage",
                             "files": ["constants/type_constants.asm", "engine/battle/effect_commands.asm", "data/moves/effects_pointers.asm", "data/moves/effects.asm"]},
            "moves": moves, "sentinels": {"0": "NO_MOVE", "255": "CANNOT_MOVE"}}


def main(argv=None) -> int:
    return run_cli(argv, build, "moves.json")


if __name__ == "__main__":
    raise SystemExit(main())
