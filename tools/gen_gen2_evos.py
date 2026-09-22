#!/usr/bin/env python3
"""Generate Gen 2 evolution edges/families and branch parameters from ASM + ROM.

`evolutions` and lowest-NatDex `family` preserve the existing Gen 1 consumer
shape. `methods` retains every source branch and its engine conditions. These
are cartridge facts, not proof of runtime acquisition or trade qualification.
"""
from __future__ import annotations

import hashlib
import re

if __package__:
    from .gen2_source_data import ROOT, load_context, rom_offset
    from .gen_gen2_species import (
        const_block,
        guard_context,
        number,
        require,
        source_inputs,
        write_packs,
    )
else:
    from gen2_source_data import ROOT, load_context, rom_offset
    from gen_gen2_species import (
        const_block,
        guard_context,
        number,
        require,
        source_inputs,
        write_packs,
    )


def parse_evolution_source(text):
    result, active = {}, None
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        match = re.fullmatch(r"(\w+EvosAttacks):", line)
        if match:
            require(active is None, "unterminated source evolution block")
            require(match[1] not in result, "duplicate source evolution label")
            active = match[1]
            result[active] = []
        elif active and line:
            if line == "db 0":
                active = None
            else:
                require(line.startswith("db EVOLVE_"), f"unsupported source evolution row: {line}")
                result[active].append(([part.strip() for part in line[3:].split(",")], line_number))
    require(active is None, "unterminated source evolution block")
    return result


def evolution_families(edges):
    parent = {sid: sid for sid in range(1, 252)}

    def find(sid):
        while sid != parent[sid]:
            parent[sid] = parent[parent[sid]]
            sid = parent[sid]
        return sid

    for sid, targets in edges.items():
        require(sid in parent and len(targets) == len(set(targets)), "invalid/duplicate evolution source")
        for target in targets:
            require(target in parent and target != sid, "invalid evolution target")
            left, right = find(sid), find(target)
            parent[max(left, right)] = min(left, right)
    return {str(sid): find(sid) for sid in parent}


def _method_rules(engine):
    # The selected commits have identical decision code through .proceed. Pin the
    # source landmarks that justify the descriptive constraints below.
    for needle in ("cp EVOLVE_TRADE", "cp EVOLVE_ITEM", "cp EVOLVE_LEVEL", "cp EVOLVE_HAPPINESS",
                   "cp LINK_TIMECAPSULE", "cp HAPPINESS_TO_EVOLVE", "cp TR_MORNDAY", "cp NITE_F",
                   "call IsMonHoldingEverstone", "ld [wTempMonItem], a"):
        require(needle in engine, f"source evolution engine contract missing: {needle}")
    item_block = engine.split("\n.item\n", 1)[1].split("\n.level\n", 1)[0]
    require("IsMonHoldingEverstone" not in item_block, "source item Everstone behavior changed")
    return {
        "LEVEL": {"requires_link_mode_zero": True, "requires_force_evolution_zero": True,
                  "everstone_blocks": True},
        "ITEM": {"requires_link_mode_zero": True, "requires_force_evolution_nonzero": True,
                 "everstone_blocks": False},
        "TRADE": {"requires_link_mode_nonzero": True, "everstone_blocks": True,
                  "operand_ff_means": "NO_HELD_ITEM_REQUIREMENT"},
        "HAPPINESS": {"requires_link_mode_zero": True, "requires_force_evolution_zero": True,
                      "everstone_blocks": True},
        "STAT": {"requires_link_mode_zero": True, "requires_force_evolution_zero": True,
                 "everstone_blocks": True, "comparison_operands": "CURRENT_ATTACK_AND_DEFENSE"},
    }


def build(title, root=ROOT):
    ctx = load_context(title, root=root)
    guard_context(ctx, title)
    species, _egg, data = source_inputs(ctx)
    methods = const_block(data, "EVOLVE_LEVEL")
    time = const_block(data, "TR_ANYTIME")
    comparison = const_block(data, "ATK_GT_DEF")
    items = const_block(ctx.read_source("constants/item_constants.asm"), "NO_ITEM")
    constants = {**species, **methods, **time, **comparison, **items}
    happiness = re.search(r"^DEF HAPPINESS_TO_EVOLVE\s+EQU\s+(\d+)", data, re.M)
    require(happiness is not None, "source happiness threshold missing")
    source = ctx.read_source("data/pokemon/evos_attacks.asm")
    blocks = parse_evolution_source(source)
    pointers_source = ctx.read_source("data/pokemon/evos_attacks_pointers.asm")
    labels = re.findall(r"^\s*dw\s+(\w+EvosAttacks)\s*$", pointers_source, re.M)
    require(len(labels) == 251 and len(set(labels)) == 251 and set(labels) == set(blocks),
            "source evolution pointer inventory mismatch")
    table_symbol = ctx.symbol("EvosAttacksPointers")
    table = rom_offset(*table_symbol)
    engine = ctx.read_source("engine/pokemon/evolve.asm")
    rules = _method_rules(engine)
    rows_by_species, edges = {}, {}
    for sid, label in enumerate(labels, 1):
        pointer = int.from_bytes(ctx.rom[table + (sid - 1) * 2:table + sid * 2], "little")
        symbol = ctx.symbol(label)
        require(symbol.bank == table_symbol.bank and pointer == symbol.address,
                f"ROM/source evolution pointer mismatch: {label}")
        offset = rom_offset(symbol.bank, pointer)
        encoded, rows = bytearray(), []
        for tokens, line_number in blocks[label]:
            method = tokens[0].removeprefix("EVOLVE_")
            require(method in rules and len(tokens) == (4 if method == "STAT" else 3),
                    f"source evolution method/shape unsupported: {label}")
            values = []
            for token in tokens:
                require(token in constants or re.fullmatch(r"-?\d+|\$[\da-fA-F]+", token),
                        f"unresolved source evolution token: {token}")
                values.append((constants[token] if token in constants else number(token)) & 255)
            require(values[-1] in range(1, 252), "source evolution target is not an ordinary species")
            target = values[-1]
            row = {"method": method, "method_id": values[0], "target": target}
            if method == "LEVEL":
                row["minimum_level"] = values[1]
            elif method == "ITEM":
                require(tokens[1] in items, "source evolution item missing")
                row.update(item=tokens[1], item_id=values[1])
            elif method == "TRADE":
                require(tokens[1] == "-1" or tokens[1] in items, "source trade item missing")
                needs_item = values[1] != 255
                row.update(held_item=tokens[1] if needs_item else None,
                           held_item_id=values[1] if needs_item else None,
                           consumes_held_item=needs_item, time_capsule_refused=needs_item)
            elif method == "HAPPINESS":
                require(tokens[1] in time, "source happiness time unsupported")
                row.update(minimum_happiness=int(happiness[1]), time={
                    "TR_ANYTIME": "ANYTIME", "TR_MORNDAY": "MORNING_OR_DAY", "TR_NITE": "NIGHT"
                }[tokens[1]])
            else:
                require(tokens[2] in comparison, "source stat comparison unsupported")
                row.update(minimum_level=values[1], comparison={
                    "ATK_GT_DEF": "ATTACK_GT_DEFENSE", "ATK_LT_DEF": "ATTACK_LT_DEFENSE",
                    "ATK_EQ_DEF": "ATTACK_EQ_DEFENSE"}[tokens[2]])
            row["evidence"] = {
                "source_file": "data/pokemon/evos_attacks.asm", "source_line": line_number,
                "symbol": label, "rom_offset": offset + len(encoded), "bytes_hex": bytes(values).hex(),
            }
            encoded.extend(values)
            rows.append(row)
        encoded.append(0)
        require(ctx.rom[offset:offset + len(encoded)] == encoded,
                f"ROM/source evolution bytes mismatch: {label}")
        if rows:
            rows_by_species[str(sid)] = rows
            edges[sid] = sorted({row["target"] for row in rows})
    return {
        "generator": "tools/gen_gen2_evos.py", "schema": "gen2-evolutions-v1",
        "source": ctx.source_record(), "evidence_level": "SOURCE", "title": title,
        "evolutions": {str(sid): targets for sid, targets in edges.items()},
        "family": evolution_families(edges), "methods": rows_by_species, "method_rules": rules,
        "engine_contract": {"source_file": "engine/pokemon/evolve.asm",
                            "source_text_sha256": hashlib.sha256(engine.encode("utf-8")).hexdigest(),
                            "entry_symbol": "EvolveAfterBattle_MasterLoop",
                            "evidence_level": "SOURCE", "runtime_qualification": "OPEN",
                            "time_capsule_product_scope": "EXCLUDED"},
        "tables": {"pointers": {"symbol": "EvosAttacksPointers", "rom_offset": table,
                                 "bank": table_symbol.bank, "entries": len(labels), "record_size": 2}},
        "source_files": ["constants/pokemon_constants.asm", "constants/pokemon_data_constants.asm",
                         "constants/item_constants.asm", "data/pokemon/evos_attacks_pointers.asm",
                         "data/pokemon/evos_attacks.asm", "engine/pokemon/evolve.asm"],
    }


def main(argv=None):
    return write_packs(build, "evolutions.json", argv)


if __name__ == "__main__":
    raise SystemExit(main())
