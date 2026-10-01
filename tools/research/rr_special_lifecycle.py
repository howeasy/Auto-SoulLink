"""Bounded, read-only RR 4.1 Nature Changer census. No runtime hook authorization.

Script command layouts: pret c75f3523 asm/macros/event.inc. Map records reuse
rr_ingame_trades (pret ObjectEventTemplate). Addresses below were derived from
the pinned cartridge's Nature Change text xrefs and its Viridian Center NPC.
Unknown scripts/opcodes fail closed; postbattle restore attribution remains unresolved.
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


def borrowed_contract(rom: bytes) -> dict:
    """Bounded script/body checks; caller verifies cartridge identity first."""
    objects, _ = parse_map_object_events(rom, 5, 2)
    npc = next((o for o in objects if o["local_id"] == 1), None)
    if not npc or npc["script"] != 0x09051ABF or (npc["x"], npc["y"]) != (6, 2):
        raise ValueError("borrowed school NPC binding changed")
    bindings = {0x09051AC1: "2b47100601251c05092b96100601b91b0509",
                0x09051B01: "252700252800", 0x09051B87: "2301930709",
                0x09051BF2: "2301930709", 0x09051C45: "252800"}
    for address, expected in bindings.items():
        if take(rom, address, len(expected)//2).hex() != expected:
            raise ValueError(f"borrowed school script binding changed: {address:#x}")
    for special, target in ((0x27, 0x0804C1F1), (0x28, 0x0804C231)):
        if u32(rom, 0x0815FD60 + special*4) != target:
            raise ValueError("borrowed backup/restore special target changed")
    reviewed = {
        "builder": (0x09079300, 120, "5656bcf55dbba578bae20780b9ab33faa07dc871d2d4cd28159bb57f3f9f73f2"),
        "backup": (0x0804C1F0, 64, "3137ada334afde84cbc5a809b487a5bdd2336d4c4445287cb2ce736979c043ca"),
        "restore": (0x0804C230, 64, "f58f43e511818d73bd3337e2db971358f22685cc17bfcaf2a5debadff55b3e1e")}
    bodies = {}
    for name, (address, size, sha256) in reviewed.items():
        body = take(rom, address, size)
        if name == "backup" and hashlib.sha1(rom).hexdigest() == COMPANION_SHA1:
            # Reviewed patch/tools/build.py BACKUP_BL_SITES redirects only the memcpy BL
            # at0804C212 to slink_backup_wrap08379B44. No guessed backup RAM is adopted.
            sha256 = "76d1b088005e475ea87255e4a338a4bdf292cb0540fb59abdaef33a0305f7372"
        if hashlib.sha256(body).hexdigest() != sha256 or rom.count(body) != 1:
            raise ValueError(f"borrowed {name} body changed or ambiguous")
        bodies[name] = {"address": address, "size": size, "sha256": sha256,
                        "anchor_occurrences": 1, "expected_hex": body.hex().upper()}
    return {"status": "SOURCE_PIN", "npc": npc, "map": [5, 2], "bodies": bodies,
            "begin": 0x09079300, "end": 0x0804C262,
            "script_flags_checked": [0x1047, 0x1096],
            "builder_script_calls": [0x09051B87, 0x09051BF2],
            "cancel_restore_script": 0x09051C45,
            "backup_storage": "*[03005008]+0x34 count; +0x38 six 100-byte records",
            "party_base": 0x02024284, "stride": 100,
            "postbattle_restore_caller": "UNRESOLVED for this school route; generic EndPokedudeBattle direct BL0807FAFA is not attribution",
            "contract": "begin before school builder overwrites party, including prebattle ViewYourTeam; end only active borrow with restored own keys/count; clear on reset"}


def school_fixture_flags(rom: bytes, image: bytes) -> dict:
    """Read existing save evidence, never alter flags or provision a fixture."""
    from server.adapters import gen3_codec as codec
    if hashlib.sha1(rom).hexdigest() not in (CLEAN_SHA1, COMPANION_SHA1):
        raise ValueError("unrecognized RR identity")
    # FlagGet0806E6D8 -> flag-pointer detour09042DEC -> extended helper090B8FB0.
    # That helper computes (flag-0x900)/8 + parasite base for flags0900..18FF.
    if (u32(rom, 0x090B8FE4), u32(rom, 0x090B8FE8), u32(rom, 0x090B8FEC)) != (
            0xFFFFF700, 0xFFF, codec.RR_PARASITE_ADDR):
        raise ValueError("extended flag addressing changed")
    parsed = codec.parse_flash(image, cfru=True)
    sections = [s for s in parsed["sectors"] if s["id"] == 4
                and s["counter"] == parsed["counter"]
                and s["checksum_ok"] and s["signature_ok"]]
    if len(sections) != 1:
        raise ValueError("no unique current valid section4 for progress flags")
    values = {}
    for flag in (0x1047, 0x1096):
        parasite_offset = (flag - 0x900)//8
        # RR save dispatcher: section4 tail stores parasite offsetsCC..323.
        offset = codec.RR_CHUNK_TABLE[4][1] + parasite_offset - codec.RR_PARASITE_PIECES[0]
        values[f"{flag:04X}"] = (sections[0]["data"][offset] >> (flag % 8)) & 1
    return {"sha256": hashlib.sha256(image).hexdigest(), "counter": parsed["counter"],
            "flags": values, "storage": "section4 unauthenticated parasite tail; section checksum does not cover these bytes"}


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
            "borrowed_party": borrowed_contract(rom)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--fixture", type=Path, action="append", default=[])
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    result = census(rom)
    result["existing_fixture_flags"] = [{"path": str(p), **school_fixture_flags(rom, p.read_bytes())}
                                        for p in args.fixture]
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
