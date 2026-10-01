"""Bounded, read-only RR 4.1 Nature Changer census. No runtime hook authorization.

Script command layouts: pret c75f3523 asm/macros/event.inc. Map records reuse
rr_ingame_trades (pret ObjectEventTemplate). Addresses below were derived from
the pinned cartridge's Nature Change text xrefs and its Viridian Center NPC.
Unknown scripts/opcodes fail closed; borrowed-party sites remain unresolved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from tools.rr_ingame_trades import ROM_BASE, decode_text, parse_map_object_events

CLEAN_SHA1 = "964f951a0fdaf209e4ea1344883ef0d557bb3a80"
COMPANION_SHA1 = "da579690db7d6933a0952a1f490312842793f71a"
from tools.pin_gen3_site import ROM_SPECS

DEFAULT_ROM = ROM_SPECS["rr"][3]
SERVICE = 0x0904C154
NATURE_END = 0x0904C64B
MUTATOR, MUTATOR_END = 0x090B17CC, 0x090B189A
# Only command widths used in the bounded service script, from event.inc.
WIDTHS = {2: 1, 3: 1, 4: 5, 5: 5, 6: 6, 7: 6, 9: 2, 15: 6,
          22: 5, 25: 5, 33: 5, 35: 5, 37: 3, 39: 1, 40: 3,
          41: 3, 43: 3, 47: 3, 48: 1, 90: 1, 102: 1, 103: 5,
          104: 1, 106: 1, 108: 1, 111: 5, 148: 3, 151: 2, 83: 6}


def take(rom: bytes, address: int, size: int) -> bytes:
    offset = address - ROM_BASE
    if size < 0 or offset < 0 or offset + size > len(rom):
        raise ValueError(f"ROM bounds: {address:#x}+{size}")
    return rom[offset:offset + size]


def u32(rom: bytes, address: int) -> int:
    return struct.unpack("<I", take(rom, address, 4))[0]


def instructions(rom: bytes, start: int, end: int) -> list[dict]:
    """Linear command-boundary census, not a reachability claim."""
    out = []
    while start < end:
        op = take(rom, start, 1)[0]
        if op not in WIDTHS:
            raise ValueError(f"unrecognized script opcode {op:#x} at {start:#x}")
        raw = take(rom, start, WIDTHS[op])
        if start + len(raw) > end:
            raise ValueError("script command crosses bound")
        out.append({"address": start, "opcode": op, "hex": raw.hex()})
        start += len(raw)
    return out


def census(rom: bytes) -> dict:
    sha1 = hashlib.sha1(rom).hexdigest()
    if sha1 not in (CLEAN_SHA1, COMPANION_SHA1):
        raise ValueError(f"unrecognized RR identity: {sha1}")
    commands = instructions(rom, SERVICE, NATURE_END)
    objects, warps = parse_map_object_events(rom, 5, 4)
    npc = next((o for o in objects if o["local_id"] == 5), None)
    if not npc or npc["script"] != SERVICE or (npc["x"], npc["y"]) != (8, 2):
        raise ValueError("Nature Changer NPC binding changed")
    nature_branches = [c for c in commands if c["opcode"] == 6
                       and bytes.fromhex(c["hex"]) == bytes.fromhex("0601d6c30409")]
    if len(nature_branches) != 2 or any(
        take(rom, c["address"] - 5, 5) != bytes.fromhex("210d800000")
        for c in nature_branches
    ):
        raise ValueError("service Nature option0 branch changed")
    calls = [c for c in commands if c["opcode"] == 35
             and 0x0904C514 <= c["address"] <= 0x0904C5DC]
    if len(calls) != 21:
        raise ValueError("nature wrapper census changed")
    wrappers = []
    for call in calls:
        target = int.from_bytes(bytes.fromhex(call["hex"])[1:], "little")
        raw = take(rom, target & ~1, 10)
        if raw[:2] != bytes.fromhex("10b5") or raw[3] != 0x20 or raw[8:] != bytes.fromhex("10bd"):
            raise ValueError("nature wrapper shape changed")
        first, second = struct.unpack("<HH", raw[4:8])
        if first & 0xF800 != 0xF000 or second & 0xF800 != 0xF800:
            raise ValueError("nature wrapper lacks Thumb BL")
        delta = ((first & 0x7FF) << 12) | ((second & 0x7FF) << 1)
        if delta & (1 << 22): delta -= 1 << 23
        if (target & ~1) + 8 + delta != MUTATOR:
            raise ValueError("nature wrapper mutator changed")
        wrappers.append({"script_call": call["address"], "target": target,
                         "nature": raw[2], "bytes": raw.hex()})
    expected_literals = {0x090B189C: 0x020370C0, 0x090B18A0: 0x02024284,
                         0x090B18B8: 0x0804037D, 0x090B18BC: 0x0803E47D}
    for address, expected in expected_literals.items():
        if u32(rom, address) != expected:
            raise ValueError(f"mutator literal changed: {address:#x}")
    if take(rom, 0x090B186C, 24).hex() != "07aa00212000114b01f04bfc2000104b01f047fc09b0f0bd":
        raise ValueError("PID mutation tail changed")
    texts = []
    for address in (0x09120A14, 0x09120A51, 0x09120A87):
        raw = take(rom, address, 120)
        texts.append({"address": address, "text": decode_text(raw)})
    body = take(rom, MUTATOR, MUTATOR_END - MUTATOR)
    return {"rom_sha1": sha1, "evidence": "ROM/SOURCE only; PHYSICAL unrun",
            "nature": {"status": "CANDIDATE", "npc": npc, "map": [5, 4],
                       "warps": warps, "texts": texts, "wrappers": wrappers,
                       "mutator": MUTATOR, "code_end_exclusive": MUTATOR_END,
                       "code_sha256": hashlib.sha256(body).hexdigest(),
                       "anchor_occurrences": rom.count(body),
                       "before_pid_store": 0x090B1874, "after_pid_store": 0x090B1878,
                       "mon_register": "R4", "party_base": 0x02024284,
                       "slot_address": 0x020370C0, "stride": 100,
                       "pid_value_pointer": "SP+0x1C", "field": 0,
                       "set_mon_data_thumb": 0x0804037D,
                       "source_field_binding": "pret c75f3523 include/constants/pokemon.h:5 MON_DATA_PERSONALITY=0",
                       "menu": {"service_option": 0, "accept_result": 1, "party_cancel_cutoff": 6,
                                "party_selector_special": 0x9F, "nature_list_special": 0x158,
                                "cost_evidence": "offer text says free of charge",
                                "progress_gate": "common menu expands under flag0x1040; nature stays option0"},
                       "service_script_bounds": [SERVICE, NATURE_END],
                       "service_script_sha256": hashlib.sha256(take(rom, SERVICE, NATURE_END-SERVICE)).hexdigest(),
                       "nature_option_branches": nature_branches},
            "borrowed_party": {"status": "UNRESOLVED", "sites": [],
                               "reason": "No proven RR swap/restore caller; backup literal is insufficient"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    args = parser.parse_args()
    print(json.dumps(census(args.rom.read_bytes()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
