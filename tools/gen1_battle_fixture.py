"""Controlled two-mon battle fixtures for the Gen 1 live gates.

Copies tests/fixtures/gen1/<variant>_battle.SaveRAM (Route 1, one Squirtle L5) into
.cache/battle-fixtures/ and appends a level-5 DITTO (TRANSFORM) plus one POTION, so a
SWITCH turn and an ITEM turn can be exercised. The originals are never touched. Every
output ships with a manifest.json disclosing the source hash, the output hash and the
exact byte ranges that differ: these are fixtures, not new-game or campaign proof.

Layout (pret, pinned in data/pret_sources.lock.json; addresses from data/pret_syms.json):
  ram/sram.asm:12-24      sGameData = sPlayerName(11) sMainData(wMainDataStart..End)
                          sSpriteData sPartyData(wPartyDataStart..End) sCurBoxData
                          sTileAnimations; sMainDataCheckSum follows sGameDataEnd
  engine/menus/save.asm   SaveMainData 208-244 / SavePartyAndDexData 266-288 copy those
                          WRAM blocks verbatim; CalcCheckSum 298-310 = ~(byte sum) over
                          sGameData..sGameDataEnd (pokeyellow: 200-246 / 248-279 / 281-293)
  macros/ram.asm:7-37     box_struct/party_struct (44 bytes; PARTYMON_STRUCT_LENGTH $2c)
  ram/wram.asm:1720-1744  wPartyCount, wPartySpecies (6+$FF), wPartyMons, wPartyMonOT,
                          wPartyMonNicks; 1757-1759 wNumBagItems, wBagItems (20*2+1)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.gen1_grant_receipt import (  # noqa: E402
    FRESH,
    fresh_catch_rate,
    fresh_moves,
    fresh_stats,
)
from server.gen1_party_codec import PartyCodec  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/gen1"
OUT_DIR = ROOT / ".cache/battle-fixtures"
SYMS = json.loads((ROOT / "data/pret_syms.json").read_text(encoding="utf-8"))
SOURCE = {"red": "pokered", "blue": "pokered", "yellow": "pokeyellow"}
SRAM_SIZE = 32768
SCHEMA = "gen1-battle-fixture-v1"

DITTO = 0x4C        # constants/pokemon_constants.asm:85
TRANSFORM = 0x90    # constants/move_constants.asm:152 (decimal 144)
POTION = 0x14       # constants/item_constants.asm:29
BAG_ITEM_CAPACITY = 20  # constants/menu_constants.asm:1
LEVEL = 5
DITTO_DVS = 0xABCD
NICK = bytes((0x83, 0x88, 0x93, 0x93, 0x8E, 0x50)) + bytes(5)  # "DITTO@" constants/charmap.asm
PARTY_STRUCT, NAME_LENGTH = 44, 11


def offsets(variant: str) -> dict[str, int]:
    """Battery-file offsets: SRAM bank 1 is file 0x2000.., mirrors follow the WRAM deltas."""
    syms = SYMS[SOURCE[variant]]

    def sram(name):
        return 0x2000 + syms[name] - 0xA000

    def main(name):  # sMainData mirrors wMainDataStart.. (save.asm SaveMainData)
        return sram("sMainData") + syms[name] - syms["wMainDataStart"]

    def party(name):  # sPartyData mirrors wPartyDataStart.. (save.asm SavePartyAndDexData)
        return sram("sPartyData") + syms[name] - syms["wPartyDataStart"]

    return {
        "player_name": sram("sPlayerName"), "game_data": sram("sGameData"),
        "game_data_end": sram("sGameDataEnd"), "checksum": sram("sMainDataCheckSum"),
        "player_id": main("wPlayerID"), "num_bag_items": main("wNumBagItems"),
        "bag_items": main("wBagItems"), "status_flags4": main("wStatusFlags4"),
        "party_count": party("wPartyCount"), "party_species": party("wPartySpecies"),
        "party_mons": party("wPartyMons"), "party_ot": party("wPartyMonOT"),
        "party_nicks": party("wPartyMonNicks"),
    }


def checksum(data: bytes, o: dict[str, int]) -> int:
    """CalcCheckSum (engine/menus/save.asm:298-310): 8-bit sum, complemented."""
    return ~sum(data[o["game_data"]:o["game_data_end"]]) & 0xFF


def fresh_party_mon(codec, species, level, dvs, ot_id, ot_name, nick, box_level) -> bytes:
    """44-byte party_struct + OT + nickname as AddPartyMon leaves it (see test fresh())."""
    facts = codec.profile["species"][str(species)]
    table = FRESH["titles"][codec.variant]
    stats = fresh_stats(codec, species, dvs, level)
    moves = fresh_moves(table, species, level)
    raw = bytearray(PARTY_STRUCT)
    raw[0] = species
    raw[1:3] = stats[0].to_bytes(2, "big")
    raw[3] = box_level
    raw[5:7] = bytes(facts["types"])
    raw[7] = fresh_catch_rate(table, species)
    raw[8:12] = bytes(moves)
    raw[12:14] = ot_id.to_bytes(2, "big")
    raw[14:17] = codec.experience_for_level(facts["growth_rate"], level).to_bytes(3, "big")
    raw[27:29] = dvs.to_bytes(2, "big")
    raw[29:33] = bytes(codec.max_pp(move, 0) if move else 0 for move in moves)
    raw[33] = level
    for index, value in enumerate(stats):
        raw[34 + 2 * index:36 + 2 * index] = value.to_bytes(2, "big")
    return bytes(raw) + ot_name + nick


def slot_blob(data: bytes, o: dict[str, int], slot: int) -> bytes:
    mon = o["party_mons"] + PARTY_STRUCT * slot
    ot = o["party_ot"] + NAME_LENGTH * slot
    nick = o["party_nicks"] + NAME_LENGTH * slot
    return bytes(data[mon:mon + PARTY_STRUCT] + data[ot:ot + NAME_LENGTH] + data[nick:nick + NAME_LENGTH])


def build(variant: str) -> tuple[bytes, dict]:
    source = FIXTURES / f"{variant}_battle.SaveRAM"
    original = source.read_bytes()
    if len(original) != SRAM_SIZE:
        raise ValueError(f"{source} is not a 32 KiB battery save")
    o = offsets(variant)
    codec = PartyCodec(variant)
    out = bytearray(original)
    ranges = []

    def patch(start, value, label):
        end = start + len(value)
        ranges.append({"label": label, "start": start, "end": end,
                       "before_hex": original[start:end].hex().upper(), "after_hex": value.hex().upper()})
        out[start:end] = value

    if out[o["party_count"]] != 1:
        raise ValueError("source fixture must hold exactly one party mon")
    # The shipped Squirtle carries experience 0 at level 5, which the codec (and the
    # engine's AddPartyMon) never produce; pin it to the level's floor so both mons decode.
    squirtle = slot_blob(out, o, 0)
    growth = codec.profile["species"][str(squirtle[0])]["growth_rate"]
    exp = codec.experience_for_level(growth, squirtle[33]).to_bytes(3, "big")
    if squirtle[14:17] != exp:
        patch(o["party_mons"] + 14, exp, "slot0_experience_floor")

    ot_id = int.from_bytes(out[o["player_id"]:o["player_id"] + 2], "big")
    ot_name = bytes(out[o["player_name"]:o["player_name"] + NAME_LENGTH])
    ditto = fresh_party_mon(codec, DITTO, LEVEL, DITTO_DVS, ot_id, ot_name, NICK, LEVEL)
    patch(o["party_count"], bytes((2,)), "wPartyCount")
    patch(o["party_species"] + 1, bytes((DITTO, 0xFF)), "wPartySpecies[1..2]")
    patch(o["party_mons"] + PARTY_STRUCT, ditto[:44], "wPartyMon2")
    patch(o["party_ot"] + NAME_LENGTH, ditto[44:55], "wPartyMon2OT")
    patch(o["party_nicks"] + NAME_LENGTH, ditto[55:66], "wPartyMon2Nick")

    count = out[o["num_bag_items"]]
    bag = out[o["bag_items"]:o["bag_items"] + 2 * count]
    if count >= BAG_ITEM_CAPACITY or out[o["bag_items"] + 2 * count] != 0xFF:
        raise ValueError("bag is full or its $FF terminator is misplaced")
    if POTION in bag[0::2]:
        raise ValueError("bag already holds a POTION")
    patch(o["num_bag_items"], bytes((count + 1,)), "wNumBagItems")
    patch(o["bag_items"] + 2 * count, bytes((POTION, 1, 0xFF)), "wBagItems[+1] POTION x1, $FF")
    patch(o["checksum"], bytes((checksum(out, o),)), "sMainDataCheckSum")

    # Fail loudly: codec accepts both mons, checksum verifies, nothing else moved.
    mons = codec.validate_party([slot_blob(out, o, 0), slot_blob(out, o, 1)],
                                species_list=out[o["party_species"]:o["party_species"] + 7])
    if mons[1].key != f"{DITTO_DVS:04X}:{ot_id:04X}:{DITTO:02X}" or mons[1].moves[0] != TRANSFORM:
        raise ValueError("Ditto did not decode as built")
    if out[o["checksum"]] != checksum(out, o) or len(out) != SRAM_SIZE:
        raise ValueError("checksum or size drifted")
    covered = {i for r in ranges for i in range(r["start"], r["end"])}
    changed = {i for i in range(SRAM_SIZE) if out[i] != original[i]}
    if not changed <= covered:
        raise ValueError(f"undocumented bytes changed: {sorted(changed - covered)[:8]}")

    manifest = {
        "schema": SCHEMA, "variant": variant,
        "disclosure": "controlled fixture derived from the shipped battle save; not new-game or campaign proof",
        "source": {"path": source.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(original).hexdigest()},
        "output": {"path": f"{variant}_battle.SaveRAM", "sha256": hashlib.sha256(out).hexdigest(), "size": SRAM_SIZE},
        "changed_ranges": sorted(ranges, key=lambda r: r["start"]),
        "checksum": {"offset": o["checksum"], "covers": [o["game_data"], o["game_data_end"]],
                     "algorithm": "~sum(bytes) & 0xFF (engine/menus/save.asm CalcCheckSum)", "value": out[o["checksum"]]},
        "party": {"keys": [mon.key for mon in mons],
                  "added": [{"slot": 1, "species": DITTO, "level": LEVEL, "moves": list(mons[1].moves),
                             "party_struct_hex": ditto[:44].hex().upper(), "ot_hex": ditto[44:55].hex().upper(),
                             "nick_hex": ditto[55:66].hex().upper()}]},
        "bag": {"added": [{"item": POTION, "quantity": 1}], "count": count + 1},
        "status_flags4": {"offset": o["status_flags4"], "value": out[o["status_flags4"]],
                          "note": "BIT_NO_BATTLES (bit 4) left as shipped; the live gate clears it at boot"},
        "offsets": o,
    }
    return bytes(out), manifest


def manifest_text(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def write(variant: str, out_dir: Path, check: bool) -> Path:
    data, manifest = build(variant)
    save = out_dir / f"{variant}_battle.SaveRAM"
    meta = out_dir / f"{variant}_battle.manifest.json"
    if check:
        if not save.is_file() or save.read_bytes() != data:
            raise SystemExit(f"battle fixture drift: {save}")
        if not meta.is_file() or meta.read_text(encoding="utf-8") != manifest_text(manifest):
            raise SystemExit(f"battle fixture manifest drift: {meta}")
        return save
    out_dir.mkdir(parents=True, exist_ok=True)
    save.write_bytes(data)
    meta.write_text(manifest_text(manifest), encoding="utf-8", newline="\n")
    return save


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("build", help="write <variant>_battle.SaveRAM + manifest (or --check drift)")
    cmd.add_argument("--variant", choices=(*SOURCE, "all"), default="all")
    cmd.add_argument("--out", type=Path, default=OUT_DIR)
    cmd.add_argument("--check", action="store_true")
    options = parser.parse_args(argv)
    for variant in SOURCE if options.variant == "all" else (options.variant,):
        path = write(variant, options.out, options.check)
        print(f"{variant}: {'PASS' if options.check else 'wrote'} {path} "
              f"sha256={hashlib.sha256(path.read_bytes()).hexdigest()[:16]}")


if __name__ == "__main__":
    main()
