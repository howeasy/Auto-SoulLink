"""Read-only extractor for Radical Red 4.1's in-game trade table + trader NPCs.

FireRed's sInGameTrades (pret pokefirered src/trade_scene.c, pokefirered.sym
`sInGameTrades` 0x0826CF8C size 0x21C = 9 * 0x3C) is NOT relocated by CFRU on
the RR ROM -- confirmed by reading the exact same ROM offset: it decodes as 9
well-formed struct InGameTrade entries (species/ivs/otId/personality all in
plausible ranges, nickname/otName text valid under the FRLG charmap). RR only
edited the entries' CONTENT (species, nickname, requestedSpecies, heldItem);
IVs/otId/personality/conditions/otName/otGender/sheen are carried over
unchanged from vanilla FireRed. See docs/gen3/research/rr_ingame_trades.md
for the full derivation, including why GetInGameTradeSpeciesInfo's own code
(unlike the table) IS detoured into CFRU expansion space.

Usage: python tools/rr_ingame_trades.py [--rom path/to/slink_RR.gba]
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROM_BASE = 0x08000000
RR_ROM_SHA1 = "da579690db7d6933a0952a1f490312842793f71a"  # patch/build/slink_RR.gba pin
DEFAULT_RR_ROM = ROOT / "patch" / "build" / "slink_RR.gba"
DEFAULT_VANILLA_ROM = ROOT / "patch" / "build" / "gen3_Pokemon_-_FireRed_Version_(USA).gba"

# pokefirered.sym: sInGameTrades 0826cf8c l 0000021c (data/gen3/pret/pokefirered.sym).
# Cross-checked to hold RR's own trade data (not vanilla's) at this SAME address --
# CFRU only detours the CODE that reads this table, not the table itself.
TRADE_TABLE_ADDR = 0x0826CF8C
TRADE_STRIDE = 0x3C  # struct InGameTrade, pokefirered src/trade_scene.c:57
TRADE_LABELS = ("MR_MIME", "JYNX", "NIDORAN", "FARFETCHD", "NIDORINOA",
                "LICKITUNG", "ELECTRODE", "TANGELA", "SEEL")  # pret INGAME_TRADE_* order

# gMapGroups (pokefirered.sym 083526a8), each trader's (group, num) from pret
# data/maps/map_groups.json. Object events are walked from the ROM, not assumed.
TRADE_MAPS = {
    "Route2_House": (15, 1),
    "CeruleanCity_House3": (7, 2),
    "UndergroundPath_NorthEntrance": (1, 30),
    "VermilionCity_House2": (9, 4),
    "Route11_EastEntrance_2F": (22, 1),
    "Route18_EastEntrance_2F": (26, 1),
    "CinnabarIsland_PokemonLab_Lounge": (12, 2),
    "CinnabarIsland_PokemonLab_ExperimentRoom": (12, 4),
}
GMAPGROUPS = 0x083526A8

# FRLG charmap (pret pokefirered/charmap.txt), letters + the few punctuation
# codes actually used by the trade nickname/OT-name fields.
_CHARMAP = {0x00: " ", 0xB4: "'"}
_CHARMAP.update({0xBB + i: c for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")})
_CHARMAP.update({0xD5 + i: c for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")})


def decode_text(b: bytes) -> str:
    out = []
    for byte in b:
        if byte == 0xFF:
            break
        out.append(_CHARMAP.get(byte, f"[{byte:02X}]"))
    return "".join(out)


def _u16(buf: bytes, addr: int) -> int:
    return struct.unpack_from("<H", buf, addr - ROM_BASE)[0]


def _u32(buf: bytes, addr: int) -> int:
    return struct.unpack_from("<I", buf, addr - ROM_BASE)[0]


def parse_trades(rom: bytes) -> list[dict]:
    """Decode the 9 InGameTrade entries at TRADE_TABLE_ADDR from ROM bytes."""
    off = TRADE_TABLE_ADDR - ROM_BASE
    trades = []
    for i, label in enumerate(TRADE_LABELS):
        e = rom[off + i * TRADE_STRIDE: off + (i + 1) * TRADE_STRIDE]
        trades.append({
            "label": label,
            "addr": TRADE_TABLE_ADDR + i * TRADE_STRIDE,
            "nickname": decode_text(e[0x00:0x0B]),
            "species": struct.unpack_from("<H", e, 0x0C)[0],
            "ivs": list(e[0x0E:0x14]),
            "ability_num": e[0x14],
            "ot_id": struct.unpack_from("<I", e, 0x18)[0],
            "conditions": list(e[0x1C:0x22]),
            "personality": struct.unpack_from("<I", e, 0x24)[0],
            "held_item": struct.unpack_from("<H", e, 0x28)[0],
            "mail_num": e[0x2A],
            "ot_name": decode_text(e[0x2B:0x36]),
            "ot_gender": e[0x36],
            "sheen": e[0x37],
            "requested_species": struct.unpack_from("<H", e, 0x38)[0],
        })
    return trades


def parse_map_object_events(rom: bytes, group: int, num: int) -> tuple[list[dict], list[dict]]:
    """Walk gMapGroups -> MapHeader -> MapEvents for one map (pret global.fieldmap.h)."""
    group_ptr = _u32(rom, GMAPGROUPS + group * 4)
    header_ptr = _u32(rom, group_ptr + num * 4)
    events_ptr = _u32(rom, header_ptr + 0x04)
    obj_count = rom[events_ptr - ROM_BASE]
    warp_count = rom[events_ptr - ROM_BASE + 1]
    obj_ev_ptr = _u32(rom, events_ptr + 4)
    warps_ptr = _u32(rom, events_ptr + 8)

    objects = []
    for i in range(obj_count):
        base = obj_ev_ptr + i * 0x18
        raw = rom[base - ROM_BASE: base - ROM_BASE + 0x18]
        x, y = struct.unpack_from("<hh", raw, 4)
        objects.append({
            "local_id": raw[0], "graphics_id": raw[1], "x": x, "y": y,
            "elevation": raw[8], "movement_type": raw[9],
            "script": struct.unpack_from("<I", raw, 0x10)[0],
            "flag_id": struct.unpack_from("<H", raw, 0x14)[0],
        })

    warps = []
    for i in range(warp_count):
        base = warps_ptr + i * 8
        raw = rom[base - ROM_BASE: base - ROM_BASE + 8]
        wx, wy = struct.unpack_from("<hh", raw, 0)
        warps.append({"x": wx, "y": wy, "elevation": raw[4], "warp_id": raw[5],
                       "map_num": raw[6], "map_group": raw[7]})
    return objects, warps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=DEFAULT_RR_ROM)
    args = ap.parse_args()
    rom = args.rom.read_bytes()
    for t in parse_trades(rom):
        print(f"[{t['label']}] species={t['species']} nickname={t['nickname']!r} "
              f"requested={t['requested_species']} heldItem={t['held_item']} "
              f"otName={t['ot_name']!r}")
    for name, (group, num) in TRADE_MAPS.items():
        objs, warps = parse_map_object_events(rom, group, num)
        print(f"{name} group={group} num={num} objects={objs} warps={warps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
