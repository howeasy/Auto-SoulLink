"""Pinned Gen 2 script grants, egg reception, NPC trades and dynamic caller inventory.

Egg reception is not a capture; hatch policy is gift_daycare. The Mystery Egg
quest item is excluded. Source declarations and bounded byte witnesses do not
qualify runtime success, identity finalization, or persistence.
"""
from __future__ import annotations

import re

if __package__:
    from .gen_gen2_area_map import build_area_map, source_lines
    from .gen_gen2_charmap import constants, encode, parse_charmap, run_cli, verify_table
    from .gen_gen2_statics import (
        arguments,
        byte,
        command_ids,
        number,
        public_row,
        script_rows,
        source_ref,
        values,
        version_dispatch,
        witness,
    )
else:
    from gen_gen2_area_map import build_area_map, source_lines
    from gen_gen2_charmap import constants, encode, parse_charmap, run_cli, verify_table
    from gen_gen2_statics import (
        arguments,
        byte,
        command_ids,
        number,
        public_row,
        script_rows,
        source_ref,
        values,
        version_dispatch,
        witness,
    )


def fixed_name(name, width, encoding):
    raw = encode(name, encoding)
    if len(raw) > width or encoding["@"] in raw:
        raise ValueError("invalid padded native name")
    return raw + bytes([encoding["@"]]) * (width - len(raw))


def trade_data(ctx, names, encoding, lengths):
    rows, raw = [], bytearray()
    for line_no, line in source_lines(ctx.read_source("data/events/npc_trades.asm"), ctx.title):
        if line == "NPCTrades:" or line.startswith(("table_width ", "assert_table_length ")):
            continue
        if not line.startswith("npctrade "):
            raise ValueError(f"unsupported NPC trade source: {line}")
        args = arguments(line[len("npctrade "):])
        if len(args) != 10:
            raise ValueError("NPC trade must have ten fields")
        dialog, requested, offered = [byte(arg, names) for arg in args[:3]]
        dvs = [byte(arg, names) for arg in args[4:6]]
        item, ot_id, gender = byte(args[6], names), number(args[7], names), byte(args[9], names)
        if not 1 <= requested <= 251 or not 1 <= offered <= 251 or not 0 <= ot_id <= 65535:
            raise ValueError("invalid NPC trade identity")
        record = bytes([dialog, requested, offered]) + fixed_name(args[3], lengths["NAME_LENGTH"], encoding)
        record += bytes([*dvs, item]) + ot_id.to_bytes(2, "little")
        record += fixed_name(args[8], lengths["NAME_LENGTH"], encoding) + bytes([gender, 0])
        raw.extend(record)
        rows.append({"trade_id": len(rows), "kind": "npc_exchange", "requested_species": requested,
                     "offered_species": offered, "nickname": args[3], "dvs": dvs,
                     "item": item, "ot_id": ot_id, "ot_name": args[8], "requested_gender": gender,
                     "dialog_set": dialog, "record_hex": record.hex(),
                     "source": source_ref(ctx, "data/events/npc_trades.asm", line_no),
                     "level_source": "offered_mon_derived_from_player_exchange; runtime OPEN",
                     "success_finalization": "OPEN; trade flag precedes DoNPCTrade"})
    ids = sorted(value for key, value in names.items() if key.startswith("NPC_TRADE_"))
    if ids != list(range(len(rows))) or not rows:
        raise ValueError("NPC trade constant/table inventory mismatch")
    offset = verify_table(ctx, "NPCTrades", bytes(raw))
    return rows, {"symbol": "NPCTrades", "flat": offset, "length": len(raw)}


def odd_eggs(ctx, names, encoding, lengths):
    if ctx.title != "crystal":
        return {"applicable": False, "basis": "no Odd Egg feature in the selected Gold/Silver source"}
    text = ctx.read_source("data/events/odd_eggs.asm")
    expected_count = int(re.search(r"DEF NUM_ODD_EGGS EQU (\d+)", text)[1])
    state, total, thresholds, raw, records = None, 0, [], bytearray(), []
    for line_no, line in source_lines(text, ctx.title):
        if line == "OddEggProbabilities:":
            state = "probability"
        elif line == "OddEggs:":
            state = "eggs"
        elif line.startswith(("DEF ", "assert ", "assert_table_length ", "table_width ")):
            continue
        elif state == "probability" and line.startswith("odd_egg_prob "):
            total += number(line.split()[1], names)
            thresholds.append(total * 65535 // 100)
        elif state == "eggs":
            op, _, rest = line.partition(" ")
            fields = arguments(rest)
            if op == "dname":
                raw.extend(fixed_name(fields[0], lengths[fields[1]], encoding))
                records.append((line_no, bytes(raw)))
                raw.clear()
            elif op == "db":
                raw.extend(byte(arg, names) for arg in fields)
            elif op in ("dw", "bigdw", "bigdt"):
                for arg in fields:
                    raw.extend(number(arg, names).to_bytes(3 if op == "bigdt" else 2,
                                                         "little" if op == "dw" else "big"))
            elif op == "dn" and len(fields) % 2 == 0:
                digits = [number(arg, names) for arg in fields]
                if any(not 0 <= digit < 16 for digit in digits):
                    raise ValueError("invalid Odd Egg DV nibble")
                raw.extend((digits[i] << 4) | digits[i + 1] for i in range(0, len(digits), 2))
            else:
                raise ValueError(f"unsupported Odd Egg source: {line}")
        else:
            raise ValueError(f"unsupported Odd Egg source: {line}")
    width = ctx.symbol("wPartyMon2Species").address - ctx.symbol("wPartyMon1Species").address + lengths["MON_NAME_LENGTH"]
    if raw or total != 100 or len(records) != expected_count or len(thresholds) != expected_count:
        raise ValueError("incomplete Odd Egg table")
    if any(len(record) != width for _, record in records):
        raise ValueError("Odd Egg record stride mismatch")
    verify_table(ctx, "OddEggProbabilities", b"".join(value.to_bytes(2, "little") for value in thresholds))
    verify_table(ctx, "OddEggs", b"".join(record for _, record in records))
    return {"applicable": True, "record_length": width, "records": [
        {"index": index, "threshold": thresholds[index], "species": record[0],
         "record_hex": record.hex(), "source": source_ref(ctx, "data/events/odd_eggs.asm", line_no)}
        for index, (line_no, record) in enumerate(records)]}


def native_callers(ctx):
    targets = "GivePoke|GiveEgg|DayCare_GiveEgg|TryAddMonToParty|AddMobileMonToParty"
    pattern = re.compile(rf"^\s*(call|farcall|callfar|predef)\s+({targets})\s*(?:;.*)?$", re.M)
    rows = []
    for path in sorted((ctx.source_dir / "engine").rglob("*.asm")):
        if not pattern.search(path.read_text(encoding="utf-8")):
            continue
        relative = path.relative_to(ctx.source_dir).as_posix()
        for line_no, line in source_lines(ctx.read_source(relative), ctx.title):
            if match := pattern.fullmatch(line):
                rows.append({"operation": match[1], "target": match[2],
                             "source": source_ref(ctx, relative, line_no), "classification": "OPEN_native_caller"})
    if not any(row["target"] == "DayCare_GiveEgg" for row in rows):
        raise ValueError("daycare egg caller inventory missing")
    return rows


def shuckle_gift(ctx, names):
    """Read the dedicated borrowed-mon source, including its ROM immediates."""
    path = "engine/events/shuckle.asm"
    text = ctx.read_source(path)
    species = re.search(r"ld a, (\w+)\s*\n\s*ld \[wCurPartySpecies\], a", text)
    level = re.search(r"ld a, (\d+)\s*\n\s*ld \[wCurPartyLevel\], a", text)
    item = re.search(r"ld \[hl\], ([A-Z][A-Z_]+)\s*$", text, re.M)
    if species is None or level is None or item is None:
        raise ValueError("unresolved dedicated Shuckle grant source")
    species_id, given_level, item_id = byte(species[1], names), byte(level[1], names), byte(item[1], names)
    expected = b""
    for value, symbol in ((species_id, "wCurPartySpecies"), (given_level, "wCurPartyLevel")):
        expected += bytes([0x3e, value, 0xea]) + ctx.symbol(symbol).address.to_bytes(2, "little")
    row = {"label": "GiveShuckle", "next_labels": ["GiveShuckle.NotGiven"], "path": path,
           "line": text[:species.start()].count("\n") + 1}
    return {"kind": "borrowed_gift", "species": species_id, "level": given_level, "item": item_id,
            "source": source_ref(ctx, path, row["line"]), "rom": witness(ctx, row, expected),
            "success": "OPEN_runtime_observation", "finalization": "OPEN"}


def build(ctx):
    """Build source grant/trade catalogs without claiming runtime acquisition."""
    names, commands = values(ctx), command_ids(ctx)
    encoding = parse_charmap(ctx.read_source("constants/charmap.asm"))["encoding"]
    lengths = constants(ctx.read_source("constants/text_constants.asm").split("; GetName types")[0])
    maps = {row["map_name"]: row for row in build_area_map(ctx).values()}
    gifts, callers = [], []
    special_names = {"GiveShuckle", "GiveOddEgg", "GiveDratini", "DayCareMan", "DayCareLady", "DayCareManOutside"}
    for row in script_rows(ctx, {"givepoke", "giveegg", "trade", "special"}):
        op, args = row["operation"], row["arguments"]
        if op == "special" and (len(args) != 1 or args[0] not in special_names):
            continue
        entry = public_row(ctx, row, maps)
        entry.update(operation=op, arguments=args, finalization="OPEN", success="OPEN")
        if op in ("givepoke", "giveegg"):
            if len(args) not in ((2,) if op == "giveegg" else (2, 3, 5)):
                raise ValueError(f"unsupported {op} arguments")
            species, level = byte(args[0], names), byte(args[1], names)
            if not 1 <= species <= 251 or not 1 <= level <= 100:
                raise ValueError("invalid gift species/level")
            expected = bytes([commands[op], species, level])
            entry.update(kind="egg_reception" if op == "giveegg" else "scripted_grant",
                         species=species, species_const=args[0], level=level)
            if op == "givepoke":
                item = byte(args[2], names) if len(args) > 2 else names["NO_ITEM"]
                named = len(args) == 5
                expected += bytes([item, int(named)])
                if named:
                    expected += b"".join(ctx.symbol(name).address.to_bytes(2, "little") for name in args[3:])
                entry.update(item=item, named_trainer=bool(named), success_values=[0, 1], failure_values=[2],
                             completion_source="Script_givepoke return after GivePoke naming/box path")
            else:
                entry.update(capture_at_reception=False, hatch_area_id="gift_daycare", success_values=[2], failure_values=[0])
            entry["rom"] = witness(ctx, row, expected)
            gifts.append(entry)
        elif op == "trade":
            trade_id = byte(args[0], names)
            entry.update(kind="npc_exchange", trade_id=trade_id,
                         rom=witness(ctx, row, bytes([commands[op], trade_id])))
            callers.append(entry)
        else:
            base, target = ctx.symbol("SpecialsPointers"), ctx.symbol(args[0] + "Special")
            if base.bank != target.bank or (target.address - base.address) % 3:
                raise ValueError("invalid special pointer index")
            index = (target.address - base.address) // 3
            entry["rom"] = witness(ctx, row, bytes([commands[op]]) + index.to_bytes(2, "little"))
            entry.update(target=args[0], kind="post_grant_customization" if args[0] == "GiveDratini" else "dynamic_egg_reception" if args[0] == "GiveOddEgg" else "borrowed_gift" if args[0] == "GiveShuckle" else "daycare_interaction")
            if args[0] == "GiveShuckle":
                entry["grant"] = shuckle_gift(ctx, names)
            callers.append(entry)
    trades, trade_receipt = trade_data(ctx, names, encoding, lengths)
    if {row["trade_id"] for row in callers if row["kind"] == "npc_exchange"} != set(range(len(trades))):
        raise ValueError("NPC trade caller/table coverage mismatch")
    quest = ctx.read_source("maps/MrPokemonsHouse.asm").splitlines()
    excluded = [source_ref(ctx, "maps/MrPokemonsHouse.asm", i) for i, line in enumerate(quest, 1)
                if re.search(r"\bgiveitem MYSTERY_EGG\b", line)]
    if not excluded:
        raise ValueError("Mystery Egg key-item source exclusion missing")
    return {"schema": "gen2-gifts-v1", "generator": "gen_gen2_gifts.py", "source": ctx.source_record(),
            "version_dispatch": version_dispatch(ctx),
            "gifts": gifts, "npc_trades": trades, "npc_trades_rom": trade_receipt,
            "odd_eggs": odd_eggs(ctx, names, encoding, lengths), "caller_inventory": callers,
            "native_callers": native_callers(ctx),
            "native_caller_inventory_scope": "direct unconditional call/farcall/callfar/predef to the named grant/party append helpers",
            "exclusions": [{"kind": "key_item", "constant": "MYSTERY_EGG", "source": excluded}],
            "policies": {"egg_reception_is_capture": False, "hatch_area_id": "gift_daycare"},
            "open_obligations": ["dynamic_native_grant_callers", "conditional_native_calls_and_indirect_dispatch", "source_script_reachability",
                                 "success_identity_finalization_and_durability", "CPU_instruction_boundary_qualification"]}


def main(argv=None):
    return run_cli(argv, build, "gifts.json")


if __name__ == "__main__":
    raise SystemExit(main())
