"""Deterministic receiving-cartridge trade projection (SOURCE/MODEL, not PHYSICAL).

The caller authenticates the offered 70 bytes and the actual UI decisions. This
module predicts native append/evolution effects; it does not authenticate a lease,
qualify an emulator run, or claim to validate auxiliary saved Unown form data.
The native call contract is LINK_TRADECENTER with forced evolution, not Time Capsule.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from server.adapters import gen2_codec as codec
from server.adapters.gen2_rom_scan import Rom
from tools.gen2_source_data import ROOT, load_context, rom_offset
from tools.gen_gen2_evos import build as build_evolutions
from tools.gen_gen2_items import build as build_items
from tools.gen_gen2_species import _name_bytes


def _need(condition, message):
    if not condition:
        raise ValueError("trade projection: " + message)


def _learnsets(ctx, evolutions, moves):
    """Independently parse ASM move rows and compare their complete native ROM stream."""
    source = ctx.read_source("data/pokemon/evos_attacks.asm")
    labels = re.findall(r"^\s*dw\s+(\w+EvosAttacks)\s*$", ctx.read_source("data/pokemon/evos_attacks_pointers.asm"), re.M)
    blocks = list(re.finditer(r"^(\w+EvosAttacks):\s*$", source, re.M))
    _need(len(labels) == len(blocks) == 251 and len(set(labels)) == 251, "learnset block inventory differs")
    move_ids = {row["constant"]: ident for ident, row in moves.items()}
    table = ctx.symbol("EvosAttacksPointers")
    start = rom_offset(*table)
    parsed = {}
    for index, match in enumerate(blocks):
        label = match[1]
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(source)
        lines = [line.split(";", 1)[0].strip() for line in source[match.end():end].splitlines()]
        lines = [line for line in lines if line]
        _need("db 0" in lines, "missing evolution terminator")
        rows = lines[lines.index("db 0") + 1:]
        _need(rows and rows[-1] == "db 0", "missing learnset terminator")
        levels, encoded = [], bytearray()
        for line in rows[:-1]:
            row = re.fullmatch(r"db\s+(\d+),\s*(\w+)", line)
            _need(row is not None and 1 <= int(row[1]) <= 100 and row[2] in move_ids, "unknown learnset row: " + line)
            level, move = int(row[1]), move_ids[row[2]]
            levels.append((level, move))
            encoded.extend((level, move))
        encoded.append(0)
        sid = labels.index(label) + 1
        native = ctx.symbol(label)
        pointer = int.from_bytes(ctx.rom[start + (sid - 1) * 2:start + sid * 2], "little")
        _need(native.bank == table.bank and pointer == native.address, "learnset ROM pointer differs")
        evos = evolutions["methods"].get(str(sid), [])
        evo_bytes = b"".join(bytes.fromhex(row["evidence"]["bytes_hex"]) for row in evos) + b"\0"
        at = rom_offset(*native)
        _need(ctx.rom[at:at + len(evo_bytes) + len(encoded)] == evo_bytes + encoded, "learnset ASM/ROM bytes differ: " + label)
        parsed[sid] = levels
    return parsed


def _load_projection_data(title, root):
    root = Path(root)
    ctx = load_context(title, root=root)
    layout = codec.for_foundation(title, root=root)
    packs = {}
    for name in ("species_index", "moves", "items", "evolutions"):
        pack = json.loads((root / f"data/games/gen2_{title}/{name}.json").read_text(encoding="utf-8"))
        _need(pack.get("title") == title and pack.get("source") == ctx.source_record(), f"{name} provenance differs")
        packs[name] = pack
    _need(packs["evolutions"] == build_evolutions(title, root), "evolution pack differs from source/ROM")
    _need(packs["items"] == build_items(ctx), "item pack differs from source/ROM")
    moves = {row["id"]: row for row in packs["moves"]["moves"]}
    _need(len(moves) == len(packs["moves"]["moves"]) == 251 and set(moves) == set(range(1, 252)), "move inventory differs")
    move_constants = dict(re.findall(r"^\s*const\s+(\w+)\s*;\s*([0-9a-fA-F]{2})\s*$",
                                    ctx.read_source("constants/move_constants.asm"), re.M))
    move_at = rom_offset(*ctx.symbol("Moves"))
    for ident, row in moves.items():
        _need(move_constants.get(row["constant"], "").lower() == f"{ident:02x}"
              and type(row["pp"]) is int and row["pp"] == ctx.rom[move_at + (ident - 1) * 7 + 5], "move ID/PP differs from source/ROM")
    species = packs["species_index"]["species"]
    rom = Rom(ctx.rom, layout.profile["titles"][title])
    for ident in range(1, 252):
        actual = rom.base_stats(ident)
        _need(all(species[str(ident)]["base_stats"][stat] == actual[stat] for stat in codec.STAT_NAMES), "species stats differ from ROM")
    _name_bytes(ctx)  # Existing independent source encoder also checks the ROM name table.
    names_at = rom_offset(*ctx.symbol("PokemonNames"))
    names = {sid: ctx.rom[names_at + (sid - 1) * 10:names_at + sid * 10] + bytes([0x50]) for sid in range(1, 252)}
    data_constants = ctx.read_source("constants/pokemon_data_constants.asm")
    match = re.search(r"^DEF BASE_HAPPINESS\s+EQU\s+(\d+)\s*$", data_constants, re.M)
    _need(match is not None and int(match[1]) == 70, "native base happiness changed")
    hm_source = ctx.read_source("home/hm_moves.asm").split(".HMMoves:", 1)[1]
    hm_names = re.findall(r"^\s*db\s+(\w+)\s*$", hm_source, re.M)
    hms = {next(ident for ident, row in moves.items() if row["constant"] == name) for name in hm_names}
    _need(len(hms) == 7, "HM list differs")
    hm_raw = bytes(int(move_constants[name], 16) for name in hm_names) + b"\xff"
    hm_at = rom_offset(*ctx.symbol("IsHMMove.HMMoves"))
    _need(ctx.rom[hm_at:hm_at + len(hm_raw)] == hm_raw, "HM source/ROM bytes differ")
    table = ctx.symbol("EvosAttacksPointers")
    egg_at = rom_offset(*table) + (layout.constants["EGG"] - 1) * 2
    # Native EGG marker indexes past the 251-row table; at these pins it reads
    # pointer $0002 into ROM0, whose first evolution byte is the zero terminator.
    _need(ctx.rom[egg_at:egg_at + 2] == b"\x02\0" and ctx.rom[2] == 0, "native egg evolution no-op changed")
    return {"layout": layout, "source": ctx.source_record(), "ctx": ctx, "species": species, "moves": moves,
            "items": packs["items"]["items"], "methods": packs["evolutions"]["methods"], "names": names,
            "learnsets": _learnsets(ctx, packs["evolutions"], moves), "hms": hms, "base_happiness": int(match[1])}


def project_received_mon(offered_blob: bytes, *, species_marker: int, title: str,
                         move_decisions=None, root=ROOT) -> dict:
    """Predict native append/evolution; ValueError refuses unknown or ambiguous input.

    For a full moveset, each decision is exactly {move_id, replace_slot} or
    {move_id, decline: True}, in native learnset order. Automatic learning and
    already-known moves consume no UI decision; extra decisions are refused.
    """
    _need(title in ("crystal", "gold", "silver"), "unsupported receiving title")
    _need(isinstance(offered_blob, bytes) and len(offered_blob) == 70, "offered blob must contain exactly 70 bytes")
    data = _load_projection_data(title, root)
    layout = data["layout"]
    mon = codec.decode_party_blob(offered_blob, layout, species_marker=species_marker)
    _need(mon["hp"] <= mon["max_hp"], "offered HP exceeds max HP")
    for name in ("ot_raw_hex", "nickname_raw_hex"):
        raw = bytes.fromhex(mon[name])
        _need(0x50 in raw and all(byte >= 0x60 for byte in raw[:raw.index(0x50)]), "name violates native trade renderer boundary")
    item = mon["held_item"]
    entry = data["items"].get(str(item))
    _need(item == 0 or entry is not None and not (entry["placeholder"] or entry["key_item"] or entry["mail"] or entry["permissions"] & 0x80),
          "mail, placeholder or unholdable item refused")
    _need(all(move == 0 or move in data["moves"] for move in mon["moves"]), "unknown offered move")
    choices = [] if move_decisions is None else move_decisions
    _need(isinstance(choices, (list, tuple)) and all(isinstance(row, dict) for row in choices), "move decisions must be a sequence of objects")
    before, evolved, consumed, learned = mon["species_id"], False, [], []
    expected_dex = [] if mon["is_egg"] else [before]
    if not mon["is_egg"]:
        mon["happiness"] = data["base_happiness"]
        everstone = next(int(ident) for ident, row in data["items"].items() if row["constant"] == "EVERSTONE")
        rows = [row for row in data["methods"].get(str(before), []) if row["method"] == "TRADE"
                and (row["held_item_id"] is None or row["held_item_id"] == item)] if item != everstone else []
        _need(len(rows) <= 1, "ambiguous native trade evolution")
        if rows:
            row = rows[0]
            target = row["target"]
            _need(row["consumes_held_item"] is (row["held_item_id"] is not None), "inconsistent trade item rule")
            if row["consumes_held_item"]:
                mon["held_item"] = 0
            old_name = bytes.fromhex(mon["nickname_raw_hex"])
            default = data["names"][before]
            if old_name.split(b"\x50", 1)[0] == default.split(b"\x50", 1)[0]:
                mon["nickname_raw_hex"] = data["names"][target].hex()
            stats = codec.calc_stats(data["species"][str(target)]["base_stats"], mon["dvs"], mon["stat_exp"], mon["level"])
            mon["hp"] = (mon["hp"] + stats["hp"] - mon["max_hp"]) & 0xFFFF
            mon["max_hp"] = stats["hp"]
            mon["stats"] = {stat: value for stat, value in stats.items() if stat != "hp"}
            mon["species_id"] = mon["species_marker"] = target
            evolved = True
            expected_dex.append(target)
            for level, move in data["learnsets"][target]:
                if level != mon["level"] or move in mon["moves"]:
                    continue
                if 0 in mon["moves"]:
                    slot = mon["moves"].index(0)
                else:
                    _need(len(consumed) < len(choices), f"explicit move decision required for {move}")
                    decision = choices[len(consumed)]
                    _need(type(decision.get("move_id")) is int and decision["move_id"] == move, "move decision names wrong move/order")
                    if set(decision) == {"move_id", "decline"} and decision["decline"] is True:
                        consumed.append({"move_id": move, "decline": True})
                        continue
                    _need(set(decision) == {"move_id", "replace_slot"} and type(decision["replace_slot"]) is int
                          and 0 <= decision["replace_slot"] < 4, "invalid move replacement decision")
                    slot = decision["replace_slot"]
                    _need(mon["moves"][slot] not in data["hms"], "native UI refuses forgetting HM move")
                    consumed.append({"move_id": move, "replace_slot": slot})
                mon["moves"][slot], mon["pp"][slot], mon["pp_ups"][slot] = move, data["moves"][move]["pp"], 0
                learned.append({"move_id": move, "slot": slot})
    _need(len(consumed) == len(choices), "unused move decisions refused")
    result = codec.encode_party_blob(mon, layout)
    auxiliary = ["unown_form_registration"] if not mon["is_egg"] and mon["species_id"] == 201 else []
    return {"blob": result, "blob_hex": result.hex(), "raw_hex": result[:48].hex(),
            "species_marker": mon["species_marker"], "key": codec.key(mon),
            "from_species": before, "to_species": mon["species_id"], "evolved": evolved,
            "expected_dex_species": sorted(set(expected_dex)), "move_decisions": consumed, "learned_moves": learned,
            "auxiliary_supported": not auxiliary, "unsupported_auxiliary_effects": auxiliary, "source": data["source"]}


def verify_received_mon(actual_blob: bytes, *, actual_species_marker: int, **projection_args) -> dict:
    expected = project_received_mon(**projection_args)
    _need(type(actual_species_marker) is int and isinstance(actual_blob, bytes)
          and actual_species_marker == expected["species_marker"] and actual_blob == expected["blob"],
          "received mon differs from deterministic native projection")
    return expected
