#!/usr/bin/env python3
"""Build and qualify tests/fixtures/gen3/*.sav from a real BizHawk battery save.

Worker card gen3-P2-C2-6. No emulator, no ROM: everything here is bytes in,
bytes out, checked with the independent codec (server/adapters/gen3_codec.py)
which is itself derived from pret/pokefirered + docs/gen3/research/flash_save.md.
``--boot-check`` (cold boot -> CONTINUE -> re-save -> reload) is NOT this
tool's job -- it needs EmuHawk and is the coordinator's lane (PLAN §5.5).

    python tools/gen3_fixtures.py import --src <SaveRAM> --out tests/fixtures/gen3/rr_town.sav --rr
    python tools/gen3_fixtures.py qualify tests/fixtures/gen3/*.sav
    python tools/gen3_fixtures.py qualify --rr tests/fixtures/gen3/rr_town.sav
    python tools/gen3_fixtures.py derive-b tests/fixtures/gen3/rr_town.sav tests/fixtures/gen3/rr_town_b.sav

``derive-b --rr`` always refuses (see RR_DERIVE_REFUSAL below): the codec's
own ``party_from_save``/``boxes_from_save`` refuse ``rr=True`` because RR's
chunk table, CFRU parasite payload and box disk mapping are UNVERIFIED
against the RR 4.1 binary (flash_save.md §3, §5.7, §7); rewriting sectors
without that mapping risks corrupting the parasite bytes CFRU appends after
the section checksum in ids 0/4/13. Vanilla FR/LG derive-b is fully
implemented per flash_save.md §5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from server.adapters import gen3_codec as codec  # noqa: E402

FIXTURES_DIR = Path(REPO) / "tests" / "fixtures" / "gen3"
RR_PROFILE = Path(REPO) / "data" / "games" / "gen3_rr" / "profile.json"

RR_PARTY_CITE = (
    "docs/gen3/research/flash_save.md §3, §7: upstream CFRU's chunk table "
    "and parasite mapping are not a qualified Radical Red 4.1 binary fact, "
    "so the SB1 party offset used here is UNVERIFIED at the disk-chunk level "
    "even though it is a real RAM/profile offset."
)
RR_DERIVE_REFUSAL = (
    "refused: Radical Red distinct-OT derivation is UNVERIFIED and not "
    "attempted. server/adapters/gen3_codec.py party_from_save/boxes_from_save "
    "refuse rr=True (RR's chunk table, CFRU parasite payload in sections "
    "0/4/13, and 25-box disk mapping are unpinned against the admitted RR "
    "4.1 binary). Rewriting sectors without that mapping risks destroying "
    "the parasite bytes CFRU appends after the section checksum. "
    "See docs/gen3/research/flash_save.md §3, §5.7, §7."
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rr_party_offset() -> int:
    """SB1_PARTY_BASE_OFFSET from the generated RR profile (a real RAM
    offset; disk-chunk validity is UNVERIFIED, see RR_PARTY_CITE)."""
    data = json.loads(RR_PROFILE.read_text(encoding="utf-8"))
    return data["titles"]["radical_red"]["derived"]["SB1_PARTY_BASE_OFFSET"]


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def import_savedata(src: bytes, *, rr: bool) -> bytes:
    """Strip the optional RTC suffix, refuse a blank or unqualified save,
    return the 128 KiB flash body to write as a fixture."""
    body, _rtc = codec.split_rtc(src)
    if all(b == 0xFF for b in body):
        raise ValueError("blank/erased save (flash body is all 0xFF)")
    ok, msg = codec.qualify_flash(body, cfru=rr)
    if not ok:
        raise ValueError(f"qualify_flash refused: {msg}")
    return body


def cmd_import(args: argparse.Namespace) -> int:
    src_path = Path(args.src)
    try:
        body = import_savedata(src_path.read_bytes(), rr=args.rr)
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    parsed = codec.parse_flash(body, cfru=args.rr)
    print(f"wrote {out} ({len(body)} bytes) sha256={sha256_hex(body)} "
          f"slot={parsed['slot']} counter={parsed['counter']} "
          f"source={src_path} source_sha256={sha256_hex(src_path.read_bytes())}")
    return 0


# ---------------------------------------------------------------------------
# qualify
# ---------------------------------------------------------------------------

def _trainer_identity(sb2: bytes) -> tuple[str, int]:
    """SaveBlock2 playerName +0 (7B), playerTrainerId +0xA (4B), per
    flash_save.md §5.1 / pret include/global.h#L327-L359."""
    name = codec.decode_name(sb2[0:7])
    trainer_id = int.from_bytes(sb2[0xA:0xE], "little")
    return name, trainer_id


def qualify_one(data: bytes, *, rr: bool) -> dict:
    """Everything `qualify` prints, as a dict, so the test suite can assert
    on it directly instead of parsing stdout."""
    body, rtc = codec.split_rtc(data)
    ok, msg = codec.qualify_flash(body, cfru=rr)
    parsed = codec.parse_flash(body, cfru=rr)
    name, trainer_id = _trainer_identity(parsed["sb2"])
    result: dict = {
        "ok": ok, "message": msg, "slot": parsed["slot"],
        "counter": parsed["counter"], "rotation": parsed["rotation"],
        "status": parsed["status_name"], "trainer_name": name,
        "trainer_id": trainer_id, "rtc_suffix": bool(rtc),
        "size": len(data),
    }
    if not ok:
        return result
    if rr:
        offset = rr_party_offset()
        sb1 = parsed["sb1"]
        count = min(sb1[codec.SB1_PARTY_COUNT_OFFSET], codec.PARTY_CAPACITY)
        party = []
        for i in range(count):
            start = offset + i * codec.PARTY_MON_SIZE
            raw = sb1[start:start + codec.PARTY_MON_SIZE]
            if len(raw) != codec.PARTY_MON_SIZE:
                break
            mon = codec.decode_party_mon(raw, rr=True)
            party.append({"species": mon["species"], "level": mon["level"]})
        result["party"] = party
        result["party_unverified"] = RR_PARTY_CITE
        result["boxes"] = None
        result["boxes_note"] = ("not supported for RR: CFRU 25-box disk "
                                 "layout UNVERIFIED, flash_save.md §3")
    else:
        party = codec.party_from_save(body, rr=False)
        result["party"] = [{"species": m["species"], "level": m["level"]}
                            for m in party]
        boxes = codec.boxes_from_save(body, rr=False)
        result["boxes"] = sum(1 for box in boxes for mon in box
                              if mon["personality"] or mon["ot_id"])
    return result


def cmd_qualify(args: argparse.Namespace) -> int:
    exit_code = 0
    for path in args.files:
        data = Path(path).read_bytes()
        try:
            r = qualify_one(data, rr=args.rr)
        except ValueError as exc:
            print(f"{path}: REFUSED {exc}")
            exit_code = 1
            continue
        status = "OK" if r["ok"] else f"REFUSED ({r['message']})"
        print(f"{path}: {status} size={r['size']} slot={r['slot']} "
              f"counter={r['counter']} rotation={r['rotation']} "
              f"trainer={r['trainer_name']!r}#{r['trainer_id']:08X} "
              f"rtc_suffix={r['rtc_suffix']}")
        if not r["ok"]:
            exit_code = 1
            continue
        if args.rr:
            print(f"  party (UNVERIFIED, {r['party_unverified']}): {r['party']}")
            print(f"  boxes: {r['boxes_note']}")
        else:
            print(f"  party: {r['party']}")
            print(f"  boxes: {r['boxes']} occupied slots")
    return exit_code


# ---------------------------------------------------------------------------
# derive-b (vanilla only; RR always refuses, see RR_DERIVE_REFUSAL)
# ---------------------------------------------------------------------------

def _rekey_mon(raw: bytes, *, party: bool, old_tid: int, new_tid: int,
               new_name: str) -> tuple[bytes, bool]:
    """Re-key one owned record's OTID/OT-name and re-encrypt+checksum it
    (flash_save.md §5.4: decrypt with OLD pid^otid, keep PID/permutation,
    change OTID/name, re-encrypt with NEW pid^otid, recompute checksum).
    A record not owned by ``old_tid`` (traded-mon provenance) is returned
    unchanged. An empty slot (personality==0 and ot_id==0) is left alone."""
    decode = codec.decode_party_mon if party else codec.decode_box_mon
    encode = codec.encode_party_mon if party else codec.encode_box_mon
    mon = decode(raw)
    if mon["personality"] == 0 and mon["ot_id"] == 0:
        return raw, False
    if mon["ot_id"] != old_tid:
        return raw, False  # foreign/traded provenance: preserve, flash_save.md §5.3
    mon["ot_id"] = new_tid
    mon["ot_name"] = new_name
    mon.pop("ot_name_raw", None)
    new_raw = encode(mon)
    return new_raw, new_raw != raw


def derive_b(a_body: bytes) -> tuple[bytes, list[str]]:
    """Vanilla distinct-OT derivation (flash_save.md §5). Returns
    (new_flash_body, manifest_lines); raises ValueError if the source does
    not qualify."""
    ok, msg = codec.qualify_flash(a_body)
    if not ok:
        raise ValueError(f"source fixture does not qualify: {msg}")
    parsed = codec.parse_flash(a_body)
    sb2 = bytearray(parsed["sb2"])
    sb1 = bytearray(parsed["sb1"])
    storage = bytearray(parsed["storage"])
    manifest: list[str] = []

    old_name, old_tid = _trainer_identity(bytes(sb2))
    new_tid = (~old_tid) & 0xFFFFFFFF          # deterministic, distinct OT id
    suffix = "B"
    new_name = (old_name[:len(old_name) - len(suffix)] + suffix
                if len(old_name) + len(suffix) > 7 else old_name + suffix) or "B"
    sb2[0xA:0xE] = new_tid.to_bytes(4, "little")
    manifest.append(f"sb2+0x0A..0x0E playerTrainerId {old_tid:#010x} -> {new_tid:#010x}")
    sb2[0:7] = codec.encode_name(new_name, 7)
    manifest.append(f"sb2+0x00..0x07 playerName {old_name!r} -> {new_name!r}")
    # SaveBlock2.encryptionKey (+0xF20) is deliberately untouched: an OT-only
    # transformation does not need a bag/stats rekey (flash_save.md §5.5).

    count = min(sb1[codec.SB1_PARTY_COUNT_OFFSET], codec.PARTY_CAPACITY)
    for i in range(count):
        start = codec.SB1_PARTY_OFFSET + i * codec.PARTY_MON_SIZE
        raw = bytes(sb1[start:start + codec.PARTY_MON_SIZE])
        new_raw, changed = _rekey_mon(raw, party=True, old_tid=old_tid,
                                       new_tid=new_tid, new_name=new_name)
        if changed:
            sb1[start:start + codec.PARTY_MON_SIZE] = new_raw
            manifest.append(f"sb1+{start:#06x}..{start + codec.PARTY_MON_SIZE:#06x} "
                            f"party[{i}] OTID/OT-name re-keyed, secure re-encrypted+checksummed")

    for box in range(codec.BOXES_PER_STORE):
        for slot in range(codec.MONS_PER_BOX):
            idx = box * codec.MONS_PER_BOX + slot
            start = codec.BOX_DATA_OFFSET + idx * codec.BOX_MON_SIZE
            raw = bytes(storage[start:start + codec.BOX_MON_SIZE])
            new_raw, changed = _rekey_mon(raw, party=False, old_tid=old_tid,
                                          new_tid=new_tid, new_name=new_name)
            if changed:
                storage[start:start + codec.BOX_MON_SIZE] = new_raw
                manifest.append(f"storage+{start:#06x}..{start + codec.BOX_MON_SIZE:#06x} "
                                f"box[{box}][{slot}] OTID/OT-name re-keyed, secure "
                                f"re-encrypted+checksummed")

    # Daycare (+0x2F80), mail (+0x2CD0) and Battle Tower records may carry
    # foreign trainer identities (history, not the current player) and are
    # UNVERIFIED to enumerate exhaustively -- flash_save.md §5.3 restricts
    # simple fixtures to leaving them untouched rather than guessing.

    layout = codec.slot_layout()
    objects = {"sb2": bytes(sb2), "sb1": bytes(sb1), "storage": bytes(storage)}
    base = codec.NUM_SECTORS_PER_SLOT * parsed["slot"]
    new_body = bytearray(a_body)
    for entry in layout:
        sid = entry["id"]
        phys = next(s["index"] for s in parsed["sectors"][base:base + codec.NUM_SECTORS_PER_SLOT]
                    if s["id"] == sid)
        chunk = objects[entry["object"]][entry["offset"]:entry["offset"] + entry["size"]]
        new_sector = codec.write_sector(chunk, sid, parsed["counter"], layout)
        start = phys * codec.SECTOR_SIZE
        new_body[start:start + codec.SECTOR_SIZE] = new_sector
    return bytes(new_body), manifest


def cmd_derive_b(args: argparse.Namespace) -> int:
    if args.rr:
        print(RR_DERIVE_REFUSAL, file=sys.stderr)
        return 1
    a_body = codec.split_rtc(Path(args.a).read_bytes())[0]
    try:
        b_body, manifest = derive_b(a_body)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    ok, msg = codec.qualify_flash(b_body)
    if not ok:
        print(f"refused: derived save does not re-qualify: {msg}", file=sys.stderr)
        return 1
    out = Path(args.b)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b_body)
    print(f"wrote {out} ({len(b_body)} bytes) sha256={sha256_hex(b_body)}")
    print("manifest:")
    for line in manifest:
        print(f"  {line}")
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import", help="turn a BizHawk battery save into a fixture")
    p_import.add_argument("--src", required=True)
    p_import.add_argument("--out", required=True)
    p_import.add_argument("--rr", action="store_true")
    p_import.set_defaults(func=cmd_import)

    p_qualify = sub.add_parser("qualify", help="check fixtures with no emulator")
    p_qualify.add_argument("files", nargs="+")
    p_qualify.add_argument("--rr", action="store_true")
    p_qualify.set_defaults(func=cmd_qualify)

    p_derive = sub.add_parser("derive-b", help="distinct-OT fixture derivation")
    p_derive.add_argument("a")
    p_derive.add_argument("b")
    p_derive.add_argument("--rr", action="store_true")
    p_derive.set_defaults(func=cmd_derive_b)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
