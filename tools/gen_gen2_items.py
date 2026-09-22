"""Generate Gen 2 item names/attributes from pinned ASM and verify every ROM row."""
from __future__ import annotations

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


def item_ids(text: str) -> tuple[dict[int, str], dict[int, str]]:
    ids, machines, value, tm, hm = {}, {}, 0, 0, 0
    for line in source_lines(text.split("DEF USE_SCRIPT_VAR")[0]):
        if line == "const_def":
            value = 0
        elif match := re.fullmatch(r"const\s+(\w+)", line):
            ids[value] = match[1]
            value += 1
        elif match := re.fullmatch(r"add_(tm|hm)\s+(\w+)", line):
            if match[1] == "tm":
                tm += 1
                label = f"TM{tm:02d}"
            else:
                hm += 1
                label = f"HM{hm:02d}"
            ids[value] = match[1].upper() + "_" + match[2]
            machines[value] = label
            value += 1
        elif line.startswith("DEF ") or re.fullmatch(r"add_mt\s+\w+", line):
            continue
        else:
            raise ValueError(f"unsupported item constants: {line}")
    if value != 251 or tm != 50 or hm != 7 or ids.get(0) != "NO_ITEM":
        raise ValueError("item ID/TM/HM coverage changed")
    return ids, machines


def attribute_rows(text: str) -> list[list[str]]:
    rows = []
    for line in source_lines(text):
        if line == "ItemAttributes:" or line == "table_width ITEMATTR_STRUCT_LENGTH" or line.startswith("assert_table_length "):
            continue
        if not line.startswith("item_attribute "):
            raise ValueError(f"unsupported item attributes: {line}")
        row = [part.strip() for part in line.removeprefix("item_attribute ").split(",")]
        if len(row) != 7:
            raise ValueError("item_attribute requires seven fields")
        rows.append(row)
    if len(rows) != 256:
        raise ValueError(f"ItemAttributes: {len(rows)} rows != 256")
    return rows


def build(ctx) -> dict:
    """Generate all native item-table slots, with byte0/255 sentinels separate."""
    names, table = name_list(ctx, "data/items/names.asm", "ItemNames", "ITEM_NAME_LENGTH", 256)
    id_source = ctx.read_source("constants/item_constants.asm")
    ids, machines = item_ids(id_source)
    marker = re.search(r"DEF ITEM_FROM_MEM\s+EQU\s+(\$[0-9a-f]+|\d+)", id_source)
    if not marker or integer(marker[1]) != 255:
        raise ValueError("item-from-memory sentinel changed")
    values = constants(ctx.read_source("constants/item_data_constants.asm"))
    if values["ITEMATTR_STRUCT_LENGTH"] != 7 or values["ITEMATTR_POCKET"] != 5:
        raise ValueError("unsupported item attribute layout")
    chars = parse_charmap(ctx.read_source("constants/charmap.asm"))
    # This shortcut is executed by the native text engine, not guessed title casing.
    verify_table(ctx, "PlacePOKeText", encode("POKé@", chars["encoding"]))
    rows = attribute_rows(ctx.read_source("data/items/attributes.asm"))
    raw, items, sentinels = bytearray(), {}, {}
    pockets = {values[key]: key for key in ("ITEM", "KEY_ITEM", "BALL", "TM_HM")}
    for index, (name, row) in enumerate(zip(names, rows, strict=True)):
        item_id = (index + 1) & 0xff
        price, effect, parameter, permissions, pocket, field, battle = [integer(token, values) for token in row]
        if not 0 <= price <= 65535 or pocket not in pockets or not 0 <= field <= 15 or not 0 <= battle <= 15:
            raise ValueError(f"item {item_id}: invalid price/pocket/menu bounds")
        if not -128 <= parameter <= 255 or not 0 <= effect <= 255 or not 0 <= permissions <= 255:
            raise ValueError(f"item {item_id}: invalid attribute byte")
        raw.extend([price & 255, price >> 8, effect, parameter & 255, permissions, pocket, (field << 4) | battle])
        machine = machines.get(item_id)
        if machine and machine != name:
            raise ValueError(f"item {item_id}: source TM/HM number disagrees with name")
        entry = {"constant": ids.get(item_id), "native_name": name, "name": name.replace("#", "POKé"),
                 "placeholder": name == "TERU-SAMA", "price": price,
                 "held_effect": effect, "parameter_byte": parameter & 255,
                 "permissions": permissions, "pocket": pockets[pocket],
                 "key_item": pocket == values["KEY_ITEM"], "ball": pocket == values["BALL"],
                 "tm_hm": machine, "field_menu": field, "battle_menu": battle}
        if item_id in (0, 255):
            entry["constant"] = "NO_ITEM" if item_id == 0 else "ITEM_FROM_MEM"
            sentinels[str(item_id)] = entry
        else:
            items[str(item_id)] = entry
    offset = verify_table(ctx, "ItemAttributes", bytes(raw))
    return {"schema": "gen2-items-v1", "generator": "tools/gen_gen2_items.py", "source": ctx.source_record(),
            "title": ctx.title, "tables": {"names": table, "attributes": {"symbol": "ItemAttributes", "offset": offset, "rows": 256, "record_size": 7}},
            "items": items, "sentinels": sentinels,
            "ball_ids": [int(key) for key, entry in items.items() if entry["ball"]]}


def main(argv=None) -> int:
    return run_cli(argv, build, "items.json")


if __name__ == "__main__":
    raise SystemExit(main())
