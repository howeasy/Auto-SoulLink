#!/usr/bin/env python3
"""Derive a SECOND trainer identity from the existing Polished Crystal duo SaveRAM fixture (SYNTH setup, O-33).

    python tools/polished_live/derive_save.py --src <fixture.SaveRAM> --out <B.SaveRAM> \
        [--name Bbbbbbb] [--id 53699] [--item SLOT:ITEMHEX] [--force]

PURE: `derive_identity` / `held_item_variant` map bytes to bytes (never mutate the input, touch no emulator, no
files). `verify_derived` is the offline verifier: it re-derives nothing, it reads both images through the repo codec
(server/adapters/polished_codec.py) and reports every way the derivative departs from its declaration.

Layout (flat CartRAM = bank * 0x2000 + addr - 0xA000; every fact re-read from data/polished/polished_slink.sym and
the pinned source ram/sram.asm + ram/wramx.asm):
    main   sGameData 01:a008 -> 0x2008 .. sGameDataEnd 01:ab83 -> 0x2B83, sChecksum 01:ad0d -> 0x2D0D
    backup sBackupGameData 00:b208 -> 0x1208 .. 00:bd83 -> 0x1D83,  sBackupChecksum 00:bf0d -> 0x1F0D
    inside a copy (wPlayerData starts at wPlayerID 01:d478): player ID +0 (2, big-endian), gender +2, name +3 (11),
    wPartyCount +0x856, wPartyMon1 +0x85E (48 B each), wPartyMonOTs +0x97E (11 B each: 8 name + 3 EXTRA),
    wPartyMonNicknames +0x9C0 (11 B each).  Checksum = 16-bit byte sum of the region, little-endian.
    sNewBox 0x30E4 / sBackupNewBox 0x3378: 20 records of 0x21 bytes, the first 20 bytes of a record are Entries.

This is a SYNTH identity derivative of an existing SYNTH fixture: it is NOT independently played, and whether the
native Continue / save / reload accepts it is evaluated separately (live).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from server.adapters import polished_codec as pc  # noqa: E402

REVISION = "derive_save/1 (pol-ident, 2026-10-06)"
STATEMENT = ("SYNTH identity derivative of an existing SYNTH setup fixture (O-33); not independently played; "
             "native Continue/save/reload evaluated separately")
ITEM_STATEMENT = ("SYNTH held-item variant of a SYNTH identity derivative (O-33); sets one party mon's held item "
                  "byte in both save copies and re-seals; not independently played; native Continue/save/reload "
                  "evaluated separately")

SAVE_SIZE = 32790
CART_SIZE = 32768
VERSION_AT, PHASE_AT = 0x0BE2, 0x0BE5
SAVE_VERSION = b"\x00\x0a"
NAME_FIELD = 8                       # 7 glyphs + terminator are carried in the first 8 bytes
NAME_ALLOC = pc.NAME_SIZE            # 11
MAX_NAME = NAME_FIELD - 1
PARTY_MAX = 6

# offsets inside a copy, relative to its game-data region start
ID_OFF, GENDER_OFF, NAME_OFF = 0x000, 0x002, 0x003
COUNT_OFF, MON_OFF, OT_OFF, NICK_OFF = 0x856, 0x85E, 0x97E, 0x9C0
ITEM_IN_MON, OT_ID_IN_MON = 1, 6


class Copy:
    """One of the two save copies (the geometry of one half of the SaveRAM)."""

    def __init__(self, name, start, end, checksum_at, low_marker_at, high_marker_at, newbox_at):
        self.name, self.start, self.end = name, start, end
        self.checksum_at, self.low_marker_at, self.high_marker_at = checksum_at, low_marker_at, high_marker_at
        self.newbox_at = newbox_at

    def at(self, off):
        return self.start + off

    def mon_at(self, slot):
        return self.at(MON_OFF + pc.PARTY_SIZE * slot)

    def ot_at(self, slot):
        return self.at(OT_OFF + NAME_ALLOC * slot)

    def nick_at(self, slot):
        return self.at(NICK_OFF + NAME_ALLOC * slot)


MAIN = Copy("main", 0x2008, 0x2B83, 0x2D0D, 0x2007, 0x2D0F, 0x30E4)
BACKUP = Copy("backup", 0x1208, 0x1D83, 0x1F0D, 0x1207, 0x1F0F, 0x3378)
ALL_COPIES = (MAIN, BACKUP)      # the verifier and the validators read this; never mutated
COPIES = ALL_COPIES              # the builders iterate this one
LOW_MARKER, HIGH_MARKER = 0x61, 0x7F
NEWBOX_COUNT, NEWBOX_SIZE, NEWBOX_ENTRIES = 20, 0x21, 20


class SaveIdentityError(ValueError):
    """Base of every named refusal (raised before any change is made)."""


class SaveLayoutError(SaveIdentityError):
    """Wrong size, markers, version, save phase or party count: not the save this builder understands."""


class SaveChecksumError(SaveIdentityError):
    """A copy's stored checksum disagrees with its region sum."""


class SaveBoxesNotEmptyError(SaveIdentityError):
    """A newbox record holds a mon: the derivation would leave its OT behind, so it is refused."""


class SaveNameError(SaveIdentityError):
    """The requested trainer name or ID is empty, too long, unencodable or out of range."""


# ── pure helpers ─────────────────────────────────────────────────────────────

def region_sum(buf, copy) -> int:
    return sum(buf[copy.start:copy.end]) & 0xFFFF


def stored_sum(buf, copy) -> int:
    return int.from_bytes(buf[copy.checksum_at:copy.checksum_at + 2], "little")


def sha256(data) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def party_count(buf, copy) -> int:
    return buf[copy.at(COUNT_OFF)]


def _layout_problems(save) -> list[str]:
    """Everything that is wrong with the shape of the image (empty = the expected layout)."""
    if not isinstance(save, (bytes, bytearray)) or len(save) != SAVE_SIZE:
        return [f"size: expected exactly {SAVE_SIZE} bytes, got {len(save) if hasattr(save, '__len__') else '?'}"]
    out = []
    for c in ALL_COPIES:
        if save[c.low_marker_at] != LOW_MARKER:
            out.append(f"{c.name} marker 0x{c.low_marker_at:04X}: expected 61, got {save[c.low_marker_at]:02x}")
        if save[c.high_marker_at] != HIGH_MARKER:
            out.append(f"{c.name} marker 0x{c.high_marker_at:04X}: expected 7f, got {save[c.high_marker_at]:02x}")
        if not 1 <= party_count(save, c) <= PARTY_MAX:
            out.append(f"{c.name} party count {party_count(save, c)}: expected 1..{PARTY_MAX}")
    if bytes(save[VERSION_AT:VERSION_AT + 2]) != SAVE_VERSION:
        out.append(f"sSaveVersion: expected 000a, got {bytes(save[VERSION_AT:VERSION_AT + 2]).hex()}")
    if save[PHASE_AT] != 0:
        out.append(f"save phase 0x{PHASE_AT:04X}: expected 00, got {save[PHASE_AT]:02x}")
    return out


def _checksum_problems(save) -> list[str]:
    return [f"{c.name} checksum: stored {stored_sum(save, c):04x}, region sum {region_sum(save, c):04x}"
            for c in ALL_COPIES if stored_sum(save, c) != region_sum(save, c)]


def _box_problems(save) -> list[str]:
    out = []
    for c in ALL_COPIES:
        for box in range(NEWBOX_COUNT):
            at = c.newbox_at + NEWBOX_SIZE * box
            if any(save[at:at + NEWBOX_ENTRIES]):
                out.append(f"{c.name} newbox {box + 1}: Entries not all zero ({bytes(save[at:at + NEWBOX_ENTRIES]).hex()})")
    return out


def _validate(save) -> None:
    layout = _layout_problems(save)
    if layout:
        raise SaveLayoutError("; ".join(layout))
    checksum = _checksum_problems(save)
    if checksum:
        raise SaveChecksumError("; ".join(checksum))
    boxes = _box_problems(save)
    if boxes:
        raise SaveBoxesNotEmptyError("; ".join(boxes))


def _encode_name(name) -> bytes:
    if not isinstance(name, str) or not 1 <= len(name) <= MAX_NAME:
        raise SaveNameError(f"name: expected 1..{MAX_NAME} characters, got {name!r}")
    try:
        return pc.encode_text(name, NAME_FIELD)
    except ValueError as err:
        raise SaveNameError(str(err)) from err


def _check_id(player_id) -> int:
    if type(player_id) is not int or not 0 <= player_id <= 0xFFFF:
        raise SaveNameError(f"player_id: expected integer 0..65535, got {player_id!r}")
    return player_id


def _party_slots(count) -> range:
    return range(count)


def _write_ot_name(buf, at, name8) -> None:
    """The first 8 bytes of an OT field are the name; the final 3 are EXTRA metadata and are never touched."""
    buf[at:at + NAME_FIELD] = name8


def _reseal(buf) -> None:
    """Both checksums, recomputed from the (already modified) regions."""
    for c in ALL_COPIES:
        buf[c.checksum_at:c.checksum_at + 2] = region_sum(buf, c).to_bytes(2, "little")


def _field(field, copy, offset, old, new, **extra) -> dict:
    return {"field": field, "copy": copy.name, "offset": offset, "offset_hex": f"0x{offset:04X}",
            "length": len(old), "old_hex": bytes(old).hex(), "new_hex": bytes(new).hex(), **extra}


def _ranges(offsets) -> list[str]:
    out, run = [], []
    for o in sorted(offsets):
        if run and o == run[-1] + 1:
            run.append(o)
        else:
            if run:
                out.append(run)
            run = [o]
    if run:
        out.append(run)
    return [f"0x{r[0]:04X}" if len(r) == 1 else f"0x{r[0]:04X}-0x{r[-1]:04X}" for r in out]


def diff_offsets(a, b) -> list[int]:
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]


def _checksums_block(old, new) -> dict:
    return {c.name: {"offset": c.checksum_at, "offset_hex": f"0x{c.checksum_at:04X}",
                     "old": f"{stored_sum(old, c):04x}", "new": f"{stored_sum(new, c):04x}"} for c in ALL_COPIES}


# ── the builders ─────────────────────────────────────────────────────────────

def derive_identity(save: bytes, *, name: str = "Bbbbbbb", player_id: int = 53699) -> tuple[bytes, dict]:
    """Return (new_save, disclosure): the same save re-owned by trainer `name` / `player_id`.

    Changes in BOTH copies: player ID, the first 8 name bytes, and for every occupied party slot the OT ID and the
    first 8 bytes of the OT name field; then both checksums are recomputed. Everything else is byte-identical.
    """
    _validate(save)
    name8, new_id = _encode_name(name), _check_id(player_id)
    buf = bytearray(save)
    fields = []
    for c in COPIES:
        old_id, new_id_raw = bytes(buf[c.at(ID_OFF):c.at(ID_OFF) + 2]), new_id.to_bytes(2, "big")
        buf[c.at(ID_OFF):c.at(ID_OFF) + 2] = new_id_raw
        fields.append(_field("player_id", c, c.at(ID_OFF), old_id, new_id_raw,
                             old_value=int.from_bytes(old_id, "big"), new_value=new_id))
        old_name = bytes(buf[c.at(NAME_OFF):c.at(NAME_OFF) + NAME_FIELD])
        buf[c.at(NAME_OFF):c.at(NAME_OFF) + NAME_FIELD] = name8
        fields.append(_field("player_name", c, c.at(NAME_OFF), old_name, name8,
                             old_value=pc.decode_text(old_name), new_value=name))
        for slot in _party_slots(party_count(save, c)):
            at = c.mon_at(slot) + OT_ID_IN_MON
            old_ot_id = bytes(buf[at:at + 2])
            buf[at:at + 2] = new_id.to_bytes(2, "big")
            fields.append(_field("party_ot_id", c, at, old_ot_id, new_id.to_bytes(2, "big"), slot=slot,
                                 old_value=int.from_bytes(old_ot_id, "big"), new_value=new_id))
            at = c.ot_at(slot)
            old_ot = bytes(buf[at:at + NAME_FIELD])
            _write_ot_name(buf, at, name8)
            fields.append(_field("party_ot_name", c, at, old_ot, name8, slot=slot,
                                 old_value=pc.decode_text(old_ot), new_value=name,
                                 preserved_extra_hex=bytes(buf[at + NAME_FIELD:at + NAME_ALLOC]).hex()))
    _reseal(buf)
    out = bytes(buf)
    differing = diff_offsets(save, out)
    return out, {
        "revision": REVISION, "statement": STATEMENT, "input_sha256": sha256(save), "output_sha256": sha256(out),
        "arguments": {"name": name, "player_id": new_id},
        "changed_fields": fields, "checksums": _checksums_block(save, out),
        "differing_bytes": len(differing), "differing_ranges": _ranges(differing),
    }


def held_item_variant(save: bytes, slot: int, item: int) -> tuple[bytes, dict]:
    """Set party mon `slot` (0-based, within the party count) to held item byte `item` in BOTH copies and re-seal.

    Used only when item coverage is needed; `derive_identity` never applies it. Returns (new_save, disclosure).
    """
    _validate(save)
    if type(item) is not int or not 0 <= item <= 255:
        raise SaveLayoutError(f"item: expected integer 0..255, got {item!r}")
    if type(slot) is not int or not all(0 <= slot < party_count(save, c) for c in COPIES):
        raise SaveLayoutError(f"slot: {slot!r} is not an occupied party slot in both copies")
    buf = bytearray(save)
    fields = []
    for c in COPIES:
        at = c.mon_at(slot) + ITEM_IN_MON
        fields.append(_field("party_held_item", c, at, bytes([buf[at]]), bytes([item]), slot=slot,
                             old_value=buf[at], new_value=item))
        buf[at] = item
    _reseal(buf)
    out = bytes(buf)
    differing = diff_offsets(save, out)
    return out, {
        "revision": REVISION, "statement": ITEM_STATEMENT, "input_sha256": sha256(save), "output_sha256": sha256(out),
        "arguments": {"slot": slot, "item": item}, "changed_fields": fields,
        "checksums": _checksums_block(save, out),
        "differing_bytes": len(differing), "differing_ranges": _ranges(differing),
    }


# ── the offline verifier ─────────────────────────────────────────────────────

def declared_offsets(original, *, item_slots=()) -> set[int]:
    """The only offsets a derivation may change, computed from the ORIGINAL (never from the builder)."""
    out = set()
    for c in ALL_COPIES:
        out.update(range(c.at(ID_OFF), c.at(ID_OFF) + 2))
        out.update(range(c.at(NAME_OFF), c.at(NAME_OFF) + NAME_FIELD))
        out.update(range(c.checksum_at, c.checksum_at + 2))
        for slot in range(party_count(original, c)):
            out.update(range(c.mon_at(slot) + OT_ID_IN_MON, c.mon_at(slot) + OT_ID_IN_MON + 2))
            out.update(range(c.ot_at(slot), c.ot_at(slot) + NAME_FIELD))
        for slot in item_slots:
            out.add(c.mon_at(slot) + ITEM_IN_MON)
    return out


def _mon(save, copy, slot) -> dict:
    at = copy.mon_at(slot)
    return pc.decode_party_mon(bytes(save[at:at + pc.PARTY_SIZE]))


def _identity(save, copy) -> dict:
    return {"id": int.from_bytes(save[copy.at(ID_OFF):copy.at(ID_OFF) + 2], "big"),
            "name": pc.decode_text(bytes(save[copy.at(NAME_OFF):copy.at(NAME_OFF) + NAME_FIELD]))}


def verify_derived(original: bytes, derived: bytes, *, item_slots=()) -> list[str]:
    """Problems with `derived` as an identity derivative of `original` (empty list = ok).

    `item_slots` names party slots whose held item is allowed to differ (a `held_item_variant` was applied).
    """
    problems = []
    for label, image in (("original", original), ("derived", derived)):
        if len(image) != SAVE_SIZE:
            problems.append(f"{label}: size {len(image)} != {SAVE_SIZE}")
    if problems:
        return problems
    for label, image in (("original", original), ("derived", derived)):
        problems += [f"{label}: {p}" for p in _layout_problems(image) + _checksum_problems(image)]
    if problems:
        return problems
    for c in ALL_COPIES:
        if party_count(original, c) != party_count(derived, c):
            problems.append(f"{c.name}: party count changed {party_count(original, c)} -> {party_count(derived, c)}")
    if problems:
        return problems
    if bytes(original[CART_SIZE:]) != bytes(derived[CART_SIZE:]):
        problems.append("RTC trailer changed")
    for label, at, size in (("sSaveVersion", VERSION_AT, 2), ("save phase", PHASE_AT, 1)):
        if bytes(original[at:at + size]) != bytes(derived[at:at + size]):
            problems.append(f"{label} changed")
    for c in ALL_COPIES:
        for at in (c.low_marker_at, c.high_marker_at):
            if original[at] != derived[at]:
                problems.append(f"{c.name} marker 0x{at:04X} changed")
    declared = declared_offsets(original, item_slots=item_slots)
    undeclared = sorted(set(diff_offsets(original, derived)) - declared)
    if undeclared:
        problems.append(f"undeclared offsets differ ({len(undeclared)}): {_ranges(undeclared)}")
    for c in ALL_COPIES:
        old_id, new_id = _identity(original, c), _identity(derived, c)
        if new_id["id"] == old_id["id"]:
            problems.append(f"{c.name}: player ID unchanged ({new_id['id']})")
        if new_id["name"] == old_id["name"] or not new_id["name"]:
            problems.append(f"{c.name}: player name not changed to a different non-empty name ({new_id['name']!r})")
        for slot in range(party_count(original, c)):
            tag = f"{c.name} slot {slot}"
            o_rec, d_rec = _mon(original, c, slot), _mon(derived, c, slot)
            if d_rec["ot_id"] != new_id["id"]:
                problems.append(f"{tag}: OT id {d_rec['ot_id']} != derived player id {new_id['id']}")
            if d_rec["ot_id"] == o_rec["ot_id"]:
                problems.append(f"{tag}: OT id not changed ({d_rec['ot_id']})")
            o_ot = bytes(original[c.ot_at(slot):c.ot_at(slot) + NAME_ALLOC])
            d_ot = bytes(derived[c.ot_at(slot):c.ot_at(slot) + NAME_ALLOC])
            if pc.decode_text(d_ot[:NAME_FIELD]) != new_id["name"]:
                problems.append(f"{tag}: OT name {pc.decode_text(d_ot[:NAME_FIELD])!r} != player name {new_id['name']!r}")
            if d_ot[:NAME_FIELD] == o_ot[:NAME_FIELD]:
                problems.append(f"{tag}: OT name not changed")
            if d_ot[NAME_FIELD:] != o_ot[NAME_FIELD:]:
                problems.append(f"{tag}: OT EXTRA bytes changed {o_ot[NAME_FIELD:].hex()} -> {d_ot[NAME_FIELD:].hex()}")
            if bytes(derived[c.nick_at(slot):c.nick_at(slot) + NAME_ALLOC]) != bytes(original[c.nick_at(slot):c.nick_at(slot) + NAME_ALLOC]):
                problems.append(f"{tag}: nickname changed")
            same = {k for k in o_rec if k not in ("ot_id", "raw_hex")}
            if slot in item_slots:
                same.discard("held_item")
            for k in sorted(same):
                if o_rec[k] != d_rec[k]:
                    problems.append(f"{tag}: composition field {k} changed {o_rec[k]!r} -> {d_rec[k]!r}")
    if _identity(derived, MAIN) != _identity(derived, BACKUP):
        problems.append(f"copies disagree on identity: main {_identity(derived, MAIN)} backup {_identity(derived, BACKUP)}")
    for c in ALL_COPIES:
        o_keys = {pc.key(_mon(original, c, s)) for s in range(party_count(original, c))}
        d_keys = {pc.key(_mon(derived, c, s)) for s in range(party_count(derived, c))}
        shared = sorted(o_keys & d_keys)
        if shared:
            problems.append(f"{c.name}: SLink mon keys not disjoint: {shared}")
        if len(d_keys) != party_count(derived, c):
            problems.append(f"{c.name}: derived party mon keys collide ({len(d_keys)} unique of {party_count(derived, c)})")
    return problems


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_item(text):
    slot, _, item = text.partition(":")
    if not slot or not item:
        raise argparse.ArgumentTypeError("--item expects SLOT:ITEMHEX, e.g. 0:2B")
    try:
        return int(slot, 10), int(item, 16)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"--item {text!r}: {err}") from err


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--name", default="Bbbbbbb")
    ap.add_argument("--id", dest="player_id", type=int, default=53699)
    ap.add_argument("--item", action="append", default=[], type=_parse_item, metavar="SLOT:ITEMHEX",
                    help="also set party slot SLOT's (0-based) held item (hex) in both copies; repeatable")
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out (never the source)")
    args = ap.parse_args(argv)
    src, out = args.src.resolve(), args.out.resolve()
    if src == out or (out.exists() and src.exists() and out.samefile(src)):
        print(f"refused: --out is the source file {src}", file=sys.stderr)
        return 2
    if out.exists() and not args.force:
        print(f"refused: {out} exists (pass --force to overwrite)", file=sys.stderr)
        return 2
    original = src.read_bytes()
    try:
        derived, disclosure = derive_identity(original, name=args.name, player_id=args.player_id)
        variants = []
        for slot, item in args.item:
            derived, extra = held_item_variant(derived, slot, item)
            variants.append(extra)
    except SaveIdentityError as err:
        print(f"refused: {type(err).__name__}: {err}", file=sys.stderr)
        return 3
    problems = verify_derived(original, derived, item_slots=[s for s, _ in args.item])
    if problems:
        print("refused: verify_derived reported problems:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 4
    if variants:
        disclosure["held_item_variants"] = variants
        disclosure["final_output_sha256"] = sha256(derived)
        disclosure["final_differing_bytes"] = len(diff_offsets(original, derived))
    disclosure["verify_derived"] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(derived)
    print(json.dumps(disclosure, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
