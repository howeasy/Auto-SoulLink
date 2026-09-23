"""gen3_reads_pydec.py -- PYDEC oracle for lua/gen3/reads.lua (card gen3-P3-C3-14, PLAN §5.7).

Parses the dump lua/tests/probe_gen3_reads_dump.lua writes (patch/build/gen3_reads_dump.txt):
DUMP lines carry the raw hardware bytes reads.lua decoded from; LUA lines carry what it
decoded them into. This tool decodes the SAME raw bytes independently, through
server/adapters/gen3_codec.py, and diffs field by field. Any difference is a real
disagreement between the two decoders -- reads.lua and gen3_codec.py are written from pret
independently on purpose (PLAN §5.7), so agreement here is the falsifiable claim.

    python tools/gen3_reads_pydec.py patch/build/gen3_reads_dump.txt --title radical_red
    python tools/gen3_reads_pydec.py patch/build/gen3_reads_dump.txt --title firered
    python tools/gen3_reads_pydec.py patch/build/gen3_reads_dump.txt --title firered --mutate

Exit codes: 0 clean, 1 a field differs (diff table printed), 2 the dump names an unknown
title/profile (refused, never guessed).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
from server.adapters import gen3_codec as codec  # noqa: E402

PARTY_MON_SIZE = 100        # lua/gen3/reads.lua R.PARTY_MON_SIZE == pret sizeof(struct Pokemon)
BOX_MON_SIZE = 80           # R.BOX_MON_SIZE
COMPRESSED_MON_SIZE = 0x3A  # R.COMPRESSED_MON_SIZE (CFRU CompressedPokemon, RR boxes)

# title -> (profile json path, rr flag). The profile JSON is what picks the vanilla vs RR
# decode path (never a guess from the dump itself, which names no title).
TITLE_PROFILES = {
    "firered": (_REPO / "data/games/gen3_frlg/profile.json", False),
    "leafgreen": (_REPO / "data/games/gen3_frlg/profile.json", False),
    "radical_red": (_REPO / "data/games/gen3_rr/profile.json", True),
}

DUMP_RE = re.compile(
    r"^DUMP name=(?P<name>\S+) addr=0x(?P<addr>[0-9A-Fa-f]+) len=(?P<len>\d+) "
    r"frame=(?P<frame>\d+) hex=(?P<hex>[0-9a-fA-F]*)$"
)
LUA_RE = re.compile(
    r"^LUA name=(?P<name>\S+) slot=(?P<slot>\d+) key=(?P<key>\S+) "
    r"species=(?P<species>\S*) level=(?P<level>\S*) hp=(?P<hp>\S*) nickname=(?P<nickname>.*)$"
)

# Fields compared field-by-field; "checksum_ok" is deliberately excluded (rr mode reports
# it as None on the Python side and reads.lua never sets the key at all -- both mean "not
# applicable", not a value worth diffing).
COMPARE_FIELDS = ("key", "species", "level", "hp", "nickname")


def resolve_title(title: str) -> tuple[dict, bool]:
    entry = TITLE_PROFILES.get(title)
    if entry is None:
        raise SystemExit2(f"unknown gen3 title {title!r}; known: {sorted(TITLE_PROFILES)}")
    path, rr = entry
    if not path.exists():
        raise SystemExit2(f"profile for {title!r} not found: {path}")
    profile = json.loads(path.read_text(encoding="utf-8"))
    if title not in profile.get("titles", {}):
        raise SystemExit2(f"{title!r} is not a title in {path}")
    return profile["titles"][title], rr


class SystemExit2(SystemExit):
    def __init__(self, message: str):
        print(f"refused: {message}", file=sys.stderr)
        super().__init__(2)


def parse_dump(path: Path) -> tuple[dict, dict]:
    """-> (dumps, lua_lines): dumps[name] = bytes; lua_lines[(name, slot)] = dict of fields."""
    dumps: dict = {}
    lua_lines: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = DUMP_RE.match(line)
        if m:
            dumps[m["name"]] = bytes.fromhex(m["hex"])
            continue
        m = LUA_RE.match(line)
        if m:
            lua_lines[(m["name"], int(m["slot"]))] = {
                "key": m["key"], "species": m["species"], "level": m["level"],
                "hp": m["hp"], "nickname": m["nickname"],
            }
    return dumps, lua_lines


def _mon_to_fields(mon: dict) -> dict:
    return {
        "key": f"{mon['personality']:08X}:{mon['ot_id']:08X}",
        "species": str(mon["species"]),
        "level": str(mon["level"]) if "level" in mon else "",
        "hp": str(mon["hp"]) if "hp" in mon else "",
        "nickname": mon["nickname"],
    }


def decode_records(name: str, raw: bytes, rr: bool) -> list[dict]:
    if name == "party":
        stride = PARTY_MON_SIZE
        decode = lambda rec: codec.decode_party_mon(rec, rr=rr)  # noqa: E731
    elif name == "box0":
        stride = COMPRESSED_MON_SIZE if rr else BOX_MON_SIZE
        if rr:
            decode = lambda rec: codec.decode_box_mon(  # noqa: E731
                codec.expand_compressed_box_mon(rec), rr=True)
        else:
            decode = lambda rec: codec.decode_box_mon(rec, rr=False)  # noqa: E731
    else:
        return []
    if stride == 0 or len(raw) % stride != 0:
        raise ValueError(f"{name}: {len(raw)} bytes is not a multiple of the {stride}-byte record size")
    return [decode(raw[i:i + stride]) for i in range(0, len(raw), stride)]


def diff_dump(dumps: dict, lua_lines: dict, rr: bool) -> list[tuple]:
    """-> list of (name, slot, field, lua_value, py_value) mismatches."""
    diffs = []
    for name, raw in dumps.items():
        if name not in ("party", "box0"):
            continue
        records = decode_records(name, raw, rr)
        seen_slots = {slot for (n, slot) in lua_lines if n == name}
        for slot in range(max(len(records), (max(seen_slots) + 1) if seen_slots else 0)):
            lua_row = lua_lines.get((name, slot))
            py_row = _mon_to_fields(records[slot]) if slot < len(records) else None
            if lua_row is None and py_row is None:
                continue
            if lua_row is None:
                diffs.append((name, slot, "*row*", "<missing>", "<present>"))
                continue
            if py_row is None:
                diffs.append((name, slot, "*row*", "<present>", "<missing>"))
                continue
            for field in COMPARE_FIELDS:
                if lua_row[field] != py_row[field]:
                    diffs.append((name, slot, field, lua_row[field], py_row[field]))
    return diffs


def apply_mutation(dumps: dict) -> str | None:
    """Flip one byte of the first available record (party, else box0). Returns the mutated
    name, or None if there was nothing to mutate -- the planted-offender control (PLAN §5.7
    mutation test): decode_records on the mutated bytes MUST diverge from the LUA lines that
    were decoded from the ORIGINAL bytes."""
    for name in ("party", "box0"):
        raw = dumps.get(name)
        if raw:
            mutated = bytearray(raw)
            mutated[0] ^= 0xFF
            dumps[name] = bytes(mutated)
            return name
    return None


# ── P4 card C4-2a: trainer/location/badges/bag/battle-type decoders, independent of
# lua/gen3/reads.lua on purpose (PLAN §5.7) -- offsets default to the FR/LG values recorded in
# data/games/gen3_frlg/profile.json (derived.SB2_OT_ID_OFFSET etc). Callers on a different pack
# pass that pack's own offsets instead of assuming these defaults.
SB2_TRAINER_NAME_LEN = 7  # PLAYER_NAME_LENGTH, pret include/constants/global.h:64


def decode_trainer(sb2: bytes, ot_offset: int = 0x0A, name_offset: int = 0) -> dict:
    """SaveBlock2.playerTrainerId (u32 LE) + playerName (pret include/global.h:327-332)."""
    ot_id = int.from_bytes(sb2[ot_offset:ot_offset + 4], "little")
    name = codec.decode_name(sb2[name_offset:name_offset + SB2_TRAINER_NAME_LEN])
    return {"ot_id": ot_id, "name": name}


def decode_location(sb1: bytes, group_offset: int = 0x04, num_offset: int = 0x05) -> dict:
    """SaveBlock1.location, struct WarpData (pret include/global.h:392-398,759-762): two
    signed bytes."""
    def _s8(b: int) -> int:
        return b - 256 if b >= 128 else b
    return {"map_group": _s8(sb1[group_offset]), "map_num": _s8(sb1[num_offset])}


def decode_badges(flags_byte: int) -> int:
    """The 8 FLAG_BADGE0x_GET bits already share one byte (pret include/constants/flags.h);
    bit i (0-based) is badge i+1. `flags_byte` is SaveBlock1.flags[SB1_BADGE_BYTE_OFFSET]."""
    return flags_byte & 0xFF


def decode_ball_pocket(raw: bytes, count: int, key: int | None = None) -> dict:
    """ItemSlot{u16 itemId, u16 quantity} (pret include/global.h:400-404), `count` slots back
    to back. `key` is SaveBlock2.encryptionKey (src/item.c GetBagItemQuantity XORs the low 16
    bits); pass None for CFRU/RR's unencrypted pocket."""
    total = 0
    for i in range(count):
        item = int.from_bytes(raw[i * 4:i * 4 + 2], "little")
        qty = int.from_bytes(raw[i * 4 + 2:i * 4 + 4], "little")
        if key is not None:
            qty ^= key & 0xFFFF
        if item != 0:
            total += qty
    return {"ball_count": total, "has_pokeballs": total > 0}


def decode_battle_type(flags: int, trainer_mask: int, double_mask: int) -> dict:
    """gBattleTypeFlags (u32) against the pack's BATTLE_TYPE_TRAINER_MASK/DOUBLE_MASK."""
    return {"is_trainer": bool(flags & trainer_mask), "is_doubles": bool(flags & double_mask)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dump", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--mutate", action="store_true",
                        help="flip one byte of the first record before decoding "
                             "(planted-offender control: must produce a diff)")
    args = parser.parse_args(argv)

    _profile, rr = resolve_title(args.title)
    if not args.dump.exists():
        raise SystemExit2(f"dump not found: {args.dump}")
    dumps, lua_lines = parse_dump(args.dump)
    if not dumps and not lua_lines:
        raise SystemExit2(f"no DUMP/LUA lines in {args.dump}")

    mutated_name = apply_mutation(dumps) if args.mutate else None
    if args.mutate and mutated_name is None:
        raise SystemExit2("--mutate requested but the dump has no party or box0 record to mutate")

    diffs = diff_dump(dumps, lua_lines, rr)

    if args.mutate:
        print(f"mutated: flipped byte 0 of the first {mutated_name} record")
    if not diffs:
        print(f"OK: reads.lua and gen3_codec.py agree on every field ({args.title}, rr={rr})")
        return 0
    print(f"{len(diffs)} difference(s) ({args.title}, rr={rr}):")
    print(f"{'name':<8} {'slot':>4} {'field':<10} {'lua':<20} {'py':<20}")
    for name, slot, field, lua_val, py_val in diffs:
        print(f"{name:<8} {slot:>4} {field:<10} {str(lua_val):<20} {str(py_val):<20}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
