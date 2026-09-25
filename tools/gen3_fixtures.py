#!/usr/bin/env python3
"""Build and qualify tests/fixtures/gen3/*.sav from a real BizHawk battery save.

Worker card gen3-P2-C2-6. No emulator, no ROM: everything here is bytes in,
bytes out, checked with the independent codec (server/adapters/gen3_codec.py)
which is itself derived from pret/pokefirered + docs/gen3/research/flash_save.md.
``boot-check`` and ``make-fr`` are the exception: they DO need EmuHawk (the
coordinator's lane, PLAN §5.5) and launch it through tools/run_gate.py with a
per-run SaveRAM directory and config copy, so no developer battery save is
ever touched.

    python tools/gen3_fixtures.py import --src <SaveRAM> --out tests/fixtures/gen3/rr_town.sav --rr
    python tools/gen3_fixtures.py qualify tests/fixtures/gen3/*.sav
    python tools/gen3_fixtures.py qualify --rr tests/fixtures/gen3/rr_town.sav
    python tools/gen3_fixtures.py derive-b --rr tests/fixtures/gen3/rr_town.sav <scratch>/rr_town_b.sav
    python tools/gen3_fixtures.py boot-check --rom patch/build/slink_RR.gba --fixture tests/fixtures/gen3/rr_town.sav --rr
    python tools/gen3_fixtures.py make-fr --rom "Pokemon - FireRed Version (USA).gba" --out tests/fixtures/gen3/firered_town.sav

``derive-b --rr`` uses the pinned RR layout in rr_save_layout.md. It patches
only player identity, owned party/box OT headers and affected chunk checksums;
it never rebuilds a sector with write_sector (which would erase parasite data).
The inactive rotating slot stays unchanged; extension sectors 30/31 are shared
by both slots. Daycare/mail/history are not re-identified. Bootability remains
the coordinator's separate cold-boot/re-save/reload check.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from server.adapters import gen3_codec as codec  # noqa: E402

FIXTURES_DIR = Path(REPO) / "tests" / "fixtures" / "gen3"



def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def import_savedata(src: bytes, *, rr: bool, title: str = codec.TITLE_FRLG) -> bytes:
    """Strip the optional RTC suffix, refuse a blank or unqualified save,
    return the 128 KiB flash body to write as a fixture."""
    body, _rtc = codec.split_rtc(src)
    if all(b == 0xFF for b in body):
        raise ValueError("blank/erased save (flash body is all 0xFF)")
    ok, msg = codec.qualify_flash(body, cfru=rr, title=title)
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


def _party_entry(mon: dict) -> dict:
    """One party record as qualify prints it: the client's identity key (lua/gen3/reads.lua
    r.key, PERSONALITY:OTID in eight upper-case hex digits) with species and level."""
    return {"key": f"{mon['personality']:08X}:{mon['ot_id']:08X}", "species": mon["species"],
            "level": mon["level"]}


def qualify_one(data: bytes, *, rr: bool, title: str = codec.TITLE_FRLG) -> dict:
    """Everything `qualify` prints, as a dict, so the test suite can assert
    on it directly instead of parsing stdout. ``title`` is the codec's save-layout
    title (frlg | emerald); RR ignores it."""
    body, rtc = codec.split_rtc(data)
    ok, msg = codec.qualify_flash(body, cfru=rr, title=title)
    parsed = codec.parse_flash(body, cfru=rr, title=title)
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
        if parsed["sb1"][codec.SB1_PARTY_COUNT_OFFSET] > codec.PARTY_CAPACITY:
            raise ValueError("RR party count exceeds six")
        party = codec.rr_party_from_save(body)
        boxes = codec.rr_boxes_from_save(body)
        result["party"] = [_party_entry(m) for m in party]
        result["boxes"] = sum(bool(m["species"]) for box in boxes for m in box)
        result["boxes_note"] = ("RR layout pinned; extension sectors 30/31 have no checksum "
                                "or generation counter (rr_save_layout.md §5, §7)")
    else:
        party = codec.party_from_save(body, rr=False, title=title)
        result["party"] = [_party_entry(m) for m in party]
        boxes = codec.boxes_from_save(body, rr=False, title=title)
        result["boxes"] = sum(1 for box in boxes for mon in box
                              if mon["personality"] or mon["ot_id"])
    return result


def cmd_qualify(args: argparse.Namespace) -> int:
    exit_code = 0
    for path in args.files:
        data = Path(path).read_bytes()
        try:
            r = qualify_one(data, rr=args.rr, title=args.title)
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
        print(f"  party: {r['party']}")
        print(f"  boxes: {r['boxes']} occupied slots")
        if args.rr:
            print(f"  note: {r['boxes_note']}")
    return exit_code


# ---------------------------------------------------------------------------
# derive-b (variant-specific layouts; RR preserves whole-sector spare bytes)
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


def derive_b(a_body: bytes, *, rr: bool = False,
             title: str = codec.TITLE_FRLG) -> tuple[bytes, list[str]]:
    """Variant-specific distinct-OT derivation (flash_save.md §5). Returns
    (new_flash_body, manifest_lines); raises ValueError if the source does
    not qualify. ``title`` (frlg | emerald) picks the vanilla save layout: Emerald's
    SaveBlocks are bigger and its party sits at SB1+0x234/+0x238 (gen3_codec)."""
    if rr:
        return _derive_b_rr(a_body)
    ok, msg = codec.qualify_flash(a_body, title=title)
    if not ok:
        raise ValueError(f"source fixture does not qualify: {msg}")
    parsed = codec.parse_flash(a_body, title=title)
    party_count_off, party_off = codec._TITLE_PARTY_OFFSETS[title]
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

    count = min(sb1[party_count_off], codec.PARTY_CAPACITY)
    for i in range(count):
        start = party_off + i * codec.PARTY_MON_SIZE
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

    layout = codec.slot_layout(title=title)
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


def _rr_write_spans(parsed: dict) -> list[tuple[int, int, int]]:
    """(RAM start, RAM end, flash start), excluding parasite and sector tails.

    gen3_codec.py:659-708 pins RR_CHUNK_TABLE, object bases and the two FF0
    extension payloads. rr_save_layout.md:91-100 maps all 25 box bases.
    """
    bases = {"sb2": codec.RR_SAVEBLOCK2_ADDR, "sb1": codec.RR_SAVEBLOCK1_ADDR,
             "storage": codec.RR_STORAGE_ADDR}
    half = parsed["slot"] * codec.NUM_SECTORS_PER_SLOT
    sectors = {s["id"]: s["index"]
               for s in parsed["sectors"][half:half + codec.NUM_SECTORS_PER_SLOT]}
    spans = []
    for entry in codec.rr_slot_layout():
        start = bases[entry["object"]] + entry["offset"]
        spans.append((start, start + entry["size"], sectors[entry["id"]] * codec.SECTOR_SIZE))
    for n, sector in enumerate(codec.RR_EXT_SECTORS):
        start = codec.RR_EXT_ADDR + n * codec.CHUNK_SIZE_CFRU
        spans.append((start, start + codec.CHUNK_SIZE_CFRU, sector * codec.SECTOR_SIZE))
    return spans


def _derive_b_rr(a_body: bytes) -> tuple[bytes, list[str]]:
    """Patch the selected slot and shared extension, retaining all other bytes.

    RR party is fixed-order/plaintext (codec:737-748); compressed box headers
    retain OTID +4 and OT name +14 (codec:47-49,345-362). Never encode a whole
    mon/sector: this preserves unknown fields, zero mon checksums, parasite
    bytes, extension tails, inactive slot, HOF and any supplied RTC suffix.
    """
    report = qualify_one(a_body, rr=True)
    if not report["ok"]:
        raise ValueError(f"source fixture does not qualify: {report['message']}")
    parsed = codec.parse_flash(a_body, cfru=True)
    party, boxes = codec.rr_party_from_save(a_body), codec.rr_boxes_from_save(a_body)
    old_name, old_tid = _trainer_identity(parsed["sb2"])
    new_tid = old_tid ^ 0xFFFFFFFF
    new_name = (old_name + "B") if len(old_name) < 7 else old_name[:6] + (
        "C" if old_name.endswith("B") else "B")
    encoded_name = codec.encode_name(new_name, codec.OT_NAME_LEN)
    spans = _rr_write_spans(parsed)
    patches: dict[int, int] = {}

    def field(address: int, data: bytes) -> None:
        for n, value in enumerate(data):
            addr = address + n
            hits = [start + addr - lo for lo, hi, start in spans if lo <= addr < hi]
            if len(hits) != 1:
                raise ValueError(f"RR identity byte 0x{addr:08X} has no unique flash mapping")
            offset = hits[0]
            if offset in patches and patches[offset] != value:
                raise ValueError("conflicting RR identity fields")
            patches[offset] = value

    field(codec.RR_SAVEBLOCK2_ADDR + 0xA, new_tid.to_bytes(4, "little"))
    field(codec.RR_SAVEBLOCK2_ADDR, encoded_name)
    manifest = [f"sb2 playerTrainerId {old_tid:#010x} -> {new_tid:#010x}",
                f"sb2 playerName {old_name!r} -> {new_name!r}",
                f"selected slot={parsed['slot']} counter={parsed['counter']} unchanged; "
                "inactive rotating slot preserved (retains original identity); extension is shared",
                "daycare/mail/history and SaveBlock2.encryptionKey preserved; boot-check still required"]

    def mon_fields(mon: dict, address: int, label: str) -> None:
        if not mon["species"] or mon["ot_id"] != old_tid:
            return  # empty or foreign/traded record: byte-for-byte provenance
        field(address + 4, new_tid.to_bytes(4, "little"))
        field(address + 0x14, encoded_name)
        manifest.append(f"{label} RAM={address:#010x} OTID+0x04/OT-name+0x14 re-keyed; plaintext preserved")

    for slot, mon in enumerate(party):
        mon_fields(mon, codec.RR_SAVEBLOCK1_ADDR + codec.SB1_PARTY_OFFSET
                   + slot * codec.PARTY_MON_SIZE, f"party[{slot}]")
    for box, mons in enumerate(boxes):
        for slot, mon in enumerate(mons):
            mon_fields(mon, codec.RR_BOX_BASES[box] + slot * codec.COMPRESSED_MON_SIZE,
                       f"box[{box}][{slot}]")

    new_body = bytearray(a_body)
    for offset, value in patches.items():
        new_body[offset] = value
    # Only affected rotating chunks have checksums; parasite and extension
    # bytes are outside those sums (rr_save_layout.md:132-154; codec:419-426).
    half = parsed["slot"] * codec.NUM_SECTORS_PER_SLOT
    for sector in parsed["sectors"][half:half + codec.NUM_SECTORS_PER_SLOT]:
        size = codec.RR_CHUNK_TABLE[sector["id"]][1]
        start = sector["index"] * codec.SECTOR_SIZE
        chunk = bytes(new_body[start:start + size])
        if chunk != a_body[start:start + size]:
            checksum = codec.sector_checksum(chunk, size)
            off = start + codec.OFF_SECTOR_CHECKSUM
            new_body[off:off + 2] = checksum.to_bytes(2, "little")
            manifest.append(f"sector[{sector['index']}] id={sector['id']} chunk checksum recomputed")
    result = bytes(new_body)
    qualified = qualify_one(result, rr=True)
    if not qualified["ok"]:
        raise ValueError(f"derived save does not re-qualify: {qualified['message']}")
    return result, manifest


def cmd_derive_b(args: argparse.Namespace) -> int:
    try:
        a_body = codec.split_rtc(Path(args.a).read_bytes())[0]
        b_body, manifest = derive_b(a_body, rr=args.rr, title=args.title)
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    ok, msg = codec.qualify_flash(b_body, cfru=args.rr, title=args.title)
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
# boot-check / make-fr: the EMULATOR lane (PLAN §5.5)
#
# Model qualification above is necessary but not sufficient: usability is signed only by a
# real cold boot -> CONTINUE -> re-save -> reload. These two subcommands drive that through
# tools/run_gate.py, with a PER-RUN SaveRAM directory so a live BizHawk save file is never
# touched and two runs cannot stamp on each other.
# ---------------------------------------------------------------------------

BOOT_CHECK_LUA = "lua/tests/gen3_boot_check.lua"
FR_NEWGAME_LUA = "lua/tests/gen3_fr_newgame_inputs.lua"
FR_PARTY_LUA = "lua/tests/gen3_fixture_from_state.lua"
# SLINK_GEN3_FIXTURE_RUNS moves the per-run SaveRAM dirs off Drive to a short lane path
# (reference_bizhawk_maxpath_saveram: SaveRAM writes fail silently near 260 chars).
RUN_DIR = Path(os.environ.get("SLINK_GEN3_FIXTURE_RUNS")
               or Path(REPO) / "patch" / "build" / "gen3_fixture_runs")
CHECKPOINTS = {False: Path(REPO) / "data/games/gen3_frlg/write_checkpoint.json",
               True: Path(REPO) / "data/games/gen3_rr/write_checkpoint.json"}


def saveram_name(rom_rel: str) -> str:
    """The battery filename for a ROM BizHawk's gamedb does not know: the ROM's basename with
    the extension dropped and underscores replaced by spaces. The coordinator's RR boot-check
    on 2026-09-21 observed gen3_slink_RR.gba -> "gen3 slink RR.SaveRAM"; see also
    tools/mkstates.py:117 for "slink RR.SaveRAM". BizHawk writes any optional 16-byte RTC
    suffix itself, and `import` normalizes it back out (codec.split_rtc).

    A cartridge that IS in the gamedb (a clean FR/LG dump) is filed under the gamedb name
    instead, which no rule here can derive; `--saveram-name` overrides for that case and the
    run fails loudly (erased battery / no flushed file) rather than silently booting NEW GAME.
    """
    return Path(rom_rel).stem.replace("_", " ") + ".SaveRAM"


# ---------------------------------------------------------------------------
# titles (card C4-LGF)
#
# The scripted party lane drives VANILLA FireRed and LeafGreen only. Radical Red is refused by
# name: its fixture is an imported real save and the shared scripted runtime says so itself
# (lua/tests/gen3_fr_newgame_inputs.lua's header: "Radical Red is NOT driven by this script").
# `rom` is only a DEFAULT for --rom: the owner keeps the dumps at the main checkout root, one to
# three parents above a worktree's own repo root (see _rom_candidates).
# ---------------------------------------------------------------------------

PARTY_TITLES: dict[str, dict[str, object]] = {
    "firered": {
        "rom": "Pokemon - FireRed Version (USA).gba",
        # BizHawk's gamedb knows a clean FR/LG dump: the battery is filed under the gamedb title
        # (tests/fixtures/gen3/README.md), not under the staged ROM's filename.
        "saveram": "Pokemon - FireRed Version (USA).SaveRAM",
        "scripted_newgame": True,
    },
    "leafgreen": {
        "rom": "Pokemon - LeafGreen Version (USA).gba",
        "saveram": "Pokemon - LeafGreen Version (USA).SaveRAM",
        # Owner ruling 2026-09-23 (card C4-LGF2): "the intro is the same as FireRed, why not
        # just copy it?" -- FR and LG are the same pret pokefirered engine built twice, so
        # gen3_fr_newgame_inputs.lua's intro legs (frame-timed, verified on FR US 1.0) are
        # reused on LG rather than refused. A mistuned run still fails loudly on the pinned
        # post-intro walk/save (map id, flash sector counter), same as FR.
        "scripted_newgame": True,
    },
}


def _rom_candidates(filename: str) -> list[Path]:
    """Everywhere a title's dump may live, nearest first: this repo root (the main checkout when
    the tool runs there, or a worktree's root), then the checkout the worktree belongs to
    (`<checkout>/.claude/worktrees/<name>` is three levels down)."""
    roots = [Path(REPO), *Path(REPO).parents[:3]]
    seen, out = set(), []
    for root in roots:
        cand = root / filename
        if str(cand) not in seen:
            seen.add(str(cand))
            out.append(cand)
    return out


def resolve_rom(title: str, rom: str | None) -> str:
    """--rom if given, else the title's default dump from PARTY_TITLES, searched via
    _rom_candidates. Raises FileNotFoundError naming every place searched."""
    if rom:
        return rom
    if title not in PARTY_TITLES:
        raise ValueError(f"title {title!r} is not drivable by the party lane; "
                         f"admitted: {', '.join(sorted(PARTY_TITLES))}")
    want = str(PARTY_TITLES[title]["rom"])
    for cand in _rom_candidates(want):
        if cand.exists():
            return str(cand)
    raise FileNotFoundError(
        f"{title} ROM {want!r} not found; looked in "
        + ", ".join(str(c.parent) for c in _rom_candidates(want)) + " -- pass --rom")


def _checked_title(args: argparse.Namespace) -> str:
    """The --title value, validated against PARTY_TITLES with a loud refusal (the party lane is
    vanilla FR/LG only). Absent --title keeps the historical FireRed behaviour byte-for-byte."""
    title = getattr(args, "title", None) or "firered"
    if title not in PARTY_TITLES:
        raise ValueError(f"title {title!r} is not drivable by the party lane; "
                         f"admitted: {', '.join(sorted(PARTY_TITLES))}")
    return title


def stage_rom(rom: str) -> str:
    """Copy a ROM to a space-free path under patch/build and return it RELATIVE to the repo.

    Launch rule shared with tools/run_gate.py and tools/e2e_duo.py: EmuHawk's CLI parser
    breaks on absolute paths containing the "Google Drive" space, so the ROM argument has to
    be a relative, space-free path from cwd = repo root.
    """
    src = Path(rom)
    if not src.exists():
        raise FileNotFoundError(f"ROM not found: {rom}")
    rel = f"patch/build/gen3_{src.stem.replace(' ', '_')}{src.suffix}"
    dst = Path(REPO) / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        shutil.copyfile(src, dst)
    return rel


def write_gba_run_config(src: str, dst: str, saveram_dir: str) -> None:
    """A per-run BizHawk config whose GBA Save RAM path points at `saveram_dir`.

    The window/mute/RTC handling is gen1_playthrough.write_run_config's (reused, not copied);
    only the GBA path entry is ours, because that function rewrites the GAME BOY Save RAM
    entry and refuses when it finds none.
    """
    sys.path.insert(0, os.path.join(REPO, "tools"))
    from gen1_playthrough import write_run_config
    # no plain-copy fallback: it would carry Rewind.Enabled=true (duo run 61569's crash); an
    # unparseable source now raises from write_run_config itself
    write_run_config(src, dst)
    os.makedirs(saveram_dir, exist_ok=True)
    with open(dst, encoding="utf-8-sig") as f:
        cfg = json.load(f)
    from gen1_playthrough import disable_rewind
    disable_rewind(cfg)                     # even on write_run_config's plain-copy fallback
    entries = (cfg.get("PathEntries") or {}).get("Paths") or []
    patched = [e for e in entries if e.get("Type") == "Save RAM" and e.get("System") == "GBA"]
    if not patched:
        raise RuntimeError(
            f"no GBA 'Save RAM' PathEntries in {src} — BizHawk's config schema changed, and "
            f"silently not redirecting would let this run read and overwrite the developer's "
            f"own battery saves")
    for entry in patched:
        entry["Path"] = saveram_dir.replace("\\", "/")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def _flushed_saveram(run_dir: Path, seeded_name: str) -> Path | None:
    """The battery file EmuHawk left behind. The seeded name first, then any other *.SaveRAM
    in the per-run directory -- a gamedb-known cartridge is filed under the gamedb name, not
    the one we seeded, and naming that file is more useful than claiming nothing was written.
    """
    exact = run_dir / seeded_name
    if exact.exists():
        return exact
    others = sorted(p for p in run_dir.glob("*.SaveRAM"))
    return others[0] if others else None


def boot_check_verdict(before: dict, after: dict) -> tuple[bool, list[str]]:
    """Compare the seeded fixture's `qualify_one` against the flushed save's.

    The three claims PLAN §5.5 asks a boot check to sign, and nothing more:
      * the reloaded save still qualifies (which is where "sector set complete" lives --
        codec.qualify_flash refuses a slot with a missing/duplicate/torn sector);
      * the save counter advanced by EXACTLY 1, i.e. the game performed one in-game save.
        Hash inequality alone would not prove that, and a counter that jumped proves the run
        saved more than once, which is not the scenario being signed;
      * the party is unchanged -- same keys, in the same order. The boot check walks no
        further than the START menu, so anything that moved means the run booted a different
        save (or a NEW GAME) rather than the fixture.
    """
    problems: list[str] = []
    if not after["ok"]:
        problems.append(f"the flushed save does not qualify: {after['message']}")
    if after["counter"] != before["counter"] + 1:
        problems.append(f"save counter {before['counter']} -> {after['counter']}, "
                        f"expected exactly one in-game save "
                        f"({before['counter']} -> {before['counter'] + 1})")
    # identity first (Codex receipt audit 2026-09-23): an ordered (species, level) match is
    # also what a DIFFERENT save with a lookalike party would give
    keys_before = [(m.get("key"), m["species"], m["level"]) for m in (before.get("party") or [])]
    keys_after = [(m.get("key"), m["species"], m["level"]) for m in (after.get("party") or [])]
    if any(k is None for k, _, _ in keys_before + keys_after):
        problems.append("a party record carries no PID:OTID identity key")
    if keys_before != keys_after:
        problems.append(f"party changed: {keys_before} -> {keys_after}")
    return not problems, problems


def _launch(script: str, rom_rel: str, run_dir: Path, *, rr: bool, timeout: int,
            extra_env: dict | None = None, title: str | None = None) -> tuple[bool, str]:
    """Run one Lua driver on the run_gate mechanism with a per-run config + SaveRAM dir."""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import run_gate

    # `run_gate.BIZHAWK_CONFIG` gets overwritten below to point at THIS call's per-run copy, so a
    # second `_launch` call in the same process (a retry) would otherwise read a config.ini that
    # a fresh `_prepare_run` had already deleted (FileNotFoundError) -- stash the pristine source
    # once per process rather than trusting the mutated module global on later calls.
    if not hasattr(run_gate, "_SLINK_ORIGINAL_CONFIG"):
        run_gate._SLINK_ORIGINAL_CONFIG = run_gate.BIZHAWK_CONFIG
    cfg = str(run_dir / "config.ini")
    write_gba_run_config(run_gate._SLINK_ORIGINAL_CONFIG, cfg, str(run_dir))
    checkpoint = CHECKPOINTS[rr]
    os.environ["SLINK_GEN3_CHECKPOINT"] = str(checkpoint)
    # title explicit, else the historical rr/firered mapping
    os.environ["SLINK_GEN3_TITLE"] = title or ("radical_red" if rr else "firered")
    os.environ.update(extra_env or {})
    # run_gate copies $SLINK_BIZHAWK_CONFIG into its own per-gate ini; pointing that module
    # global at OUR prepared config is how the SaveRAM redirect reaches the emulator.
    run_gate.BIZHAWK_CONFIG = cfg
    passed, _path, text = run_gate.run_gate(script, rom=rom_rel, timeout=timeout)
    return passed, text


def _prepare_run(name: str, rom: str, *, seed: bytes | None, saveram_name_override: str | None
                 ) -> tuple[str, Path, str]:
    """(rom_rel, run_dir, seeded battery filename). `seed=None` means COLD BOOT: the directory
    is emptied so the ROM cannot find a stale save and reach CONTINUE instead of NEW GAME."""
    rom_rel = stage_rom(rom)
    run_dir = RUN_DIR / name
    if run_dir.exists():
        # reference_worktree_readonly_attr: a prior run's directory can come back read-only
        # (Google Drive sync attribute), which plain rmtree refuses with WinError 5.
        def _clear_readonly(func, path, _exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(run_dir, onerror=_clear_readonly)
    run_dir.mkdir(parents=True)
    battery = saveram_name_override or saveram_name(rom_rel)
    if seed is not None:
        (run_dir / battery).write_bytes(seed)
    return rom_rel, run_dir, battery


def cmd_boot_check(args: argparse.Namespace) -> int:
    fixture = Path(args.fixture)
    data = fixture.read_bytes()
    emerald = getattr(args, "title", None) == "emerald"
    layout = codec.TITLE_EMERALD if emerald else codec.TITLE_FRLG
    before = qualify_one(data, rr=args.rr, title=layout)
    if not before["ok"]:
        print(f"BOOT-CHECK FAIL {fixture}: the fixture itself does not qualify: "
              f"{before['message']}", file=sys.stderr)
        return 1
    rom_rel, run_dir, battery = _prepare_run(
        f"bootcheck_{fixture.stem}", args.rom, seed=codec.split_rtc(data)[0],
        saveram_name_override=args.saveram_name or (EMERALD_SAVERAM if emerald else None))
    print(f"seeded {run_dir / battery} from {fixture} (counter={before['counter']})")

    passed, text = _launch(EMERALD_BOOT_LUA if emerald else BOOT_CHECK_LUA, rom_rel, run_dir,
                           rr=args.rr, timeout=args.timeout, title=getattr(args, "title", None))
    print(text.rstrip())
    if not passed:
        print(f"BOOT-CHECK FAIL {fixture}: the emulator driver did not report PASS",
              file=sys.stderr)
        return 1

    flushed = _flushed_saveram(run_dir, battery)
    if flushed is None:
        print(f"BOOT-CHECK FAIL {fixture}: EmuHawk left no *.SaveRAM in {run_dir}",
              file=sys.stderr)
        return 1
    if flushed.name != battery:
        print(f"note: BizHawk filed the battery as {flushed.name!r}, not the seeded "
              f"{battery!r} — pass --saveram-name {flushed.name!r} to seed it next time")
    after = qualify_one(codec.split_rtc(flushed.read_bytes())[0], rr=args.rr, title=layout)
    ok, problems = boot_check_verdict(before, after)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print(f"BOOT-CHECK {'PASS' if ok else 'FAIL'} {fixture} counter={before['counter']}"
          f"->{after['counter']} party={after.get('party')}")
    return 0 if ok else 1


def cmd_make_fr(args: argparse.Namespace) -> int:
    """The scripted NEW GAME lane: FireRed and LeafGreen, the same pret pokefirered engine built
    twice, share gen3_fr_newgame_inputs.lua's frame-timed intro legs (owner ruling 2026-09-23,
    card C4-LGF2). A title with no calibrated scripted intro (none currently) is refused by name
    -- before anything is staged or launched -- so a caller who cannot supply one finds out here,
    not from a mistuned run."""
    try:
        title = _checked_title(args)
    except ValueError as exc:
        print(f"make-fr FAIL: {exc}", file=sys.stderr)
        return 1
    if not PARTY_TITLES[title]["scripted_newgame"]:
        print(f"make-fr FAIL: {title} has no calibrated scripted NEW GAME. "
              f"lua/tests/gen3_fr_newgame_inputs.lua's intro legs (copyright/Oak/gender/two "
              f"naming screens) are placed by elapsed frames and verified on FireRed US 1.0 "
              f"only. For a pre-starter save on {title}: play the intro by hand (normal inputs) "
              f"to Pallet Town, save in-game, then `import` it -- see "
              f"tests/fixtures/gen3/README.md. For a party fixture from such a save: "
              f"`make-fr-party --title {title} --seed <it>`.",
              file=sys.stderr)
        return 1
    rom_rel, run_dir, battery = _prepare_run(
        f"make_fr_{title}", args.rom, seed=None, saveram_name_override=args.saveram_name)
    print(f"cold boot: {run_dir} is empty, battery will be {battery} (title={title})")

    passed, text = _launch(FR_NEWGAME_LUA, rom_rel, run_dir, rr=False, timeout=args.timeout,
                           title=title)
    print(text.rstrip())
    if not passed:
        print("make-fr FAIL: scripted play did not reach its terminals; no fixture written",
              file=sys.stderr)
        return 1

    flushed = _flushed_saveram(run_dir, battery)
    if flushed is None:
        print(f"make-fr FAIL: EmuHawk left no *.SaveRAM in {run_dir}", file=sys.stderr)
        return 1
    try:
        body = import_savedata(flushed.read_bytes(), rr=False)   # vanilla: strict qualify
    except (ValueError, OSError) as exc:
        print(f"make-fr FAIL: candidate refused: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    r = qualify_one(body, rr=False)
    print(f"wrote {out} ({len(body)} bytes) sha256={sha256_hex(body)} slot={r['slot']} "
          f"counter={r['counter']} trainer={r['trainer_name']!r}#{r['trainer_id']:08X} "
          f"party={r['party']}")
    return 0


def our_emuhawk_pids(processes: list[dict]) -> list[int]:
    """Pure filter: which EmuHawk.exe processes are OUR fixture-building runs, judged by whether
    their command line names a path under RUN_DIR (patch/build/gen3_fixture_runs/) or invokes
    THIS card's own Lua driver (FR_PARTY_LUA) -- NEVER a blanket match. `processes` is
    [{"ProcessId": int, "CommandLine": str|None}, ...], the shape `Get-CimInstance Win32_Process
    | Select ProcessId,CommandLine | ConvertTo-Json` produces -- NOTE "ProcessId", not "Id":
    Win32_Process has no "Id" property, so `Select-Object Id` silently returns null for every
    row (PHYSICAL 2026-09-23: this meant `kill_our_emuhawk` below had been taskkilling `/PID
    None` -- a silent no-op -- since it was written, so every crashed run's orphan piled up
    uncleaned before the next attempt launched. Found only by directly inspecting the JSON this
    query actually produces, not by trusting the property name).

    The run_dir itself is NOT a command-line argument (run_gate.py's cmd is only
    --config=<fixed-name>.ini --lua=<script> <rom>; the run_dir only appears INSIDE that config
    file, as the redirected SaveRAM path) -- FR_PARTY_LUA is what actually appears on the
    command line for every attempt this retry loop launches, so it is the check that fires in
    practice; the run_dir check stays as a second, harmless guard.

    2026-09-23 incident: a blanket `taskkill /IM EmuHawk.exe` here killed five in-flight Gen 2
    gate runs in a concurrent worktree (the owner allows the Gen 2 and Gen 3 emulator lanes to
    run at the same time) -- this filter is what makes the kill safe to scope to our own PIDs.
    """
    needles = (f"{RUN_DIR.as_posix()}/", str(RUN_DIR).replace("/", "\\") + "\\", FR_PARTY_LUA)
    return [p["ProcessId"] for p in processes
            if any(n in (p.get("CommandLine") or "") for n in needles)]


def _emuhawk_processes() -> list[dict]:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='EmuHawk.exe'\" | "
         "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=15)
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    data = json.loads(raw)
    return [data] if isinstance(data, dict) else data


def kill_our_emuhawk() -> None:
    """Best-effort: kill only EmuHawk.exe processes that are OUR fixture runs (see
    our_emuhawk_pids), never a machine-wide /IM kill. Failures here are swallowed -- this is
    orphan cleanup, not something worth failing the whole build over.

    Waits (bounded) for the kill to actually take effect: `taskkill` returning is not the same
    as the process's file handles being released (PHYSICAL 2026-09-23 -- a launch right after a
    reported-successful kill still hit `PermissionError` on the shared result.txt, from
    run_gate.py's own `os.remove`, which this file does not own and does not patch)."""
    try:
        for pid in our_emuhawk_pids(_emuhawk_processes()):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        for _ in range(20):
            if not our_emuhawk_pids(_emuhawk_processes()):
                return
            time.sleep(0.5)
    except Exception:
        pass


def _run_fr_party_attempts(name: str, rom: str, saveram_name: str | None, timeout: int,
                            extra_env: dict, seed: bytes, title: str = "firered",
                            max_attempts: int = 25) -> tuple[bool, str, Path, str]:
    """Launch FR_PARTY_LUA up to `max_attempts` times under a fresh run_dir/`name`, seeded with
    `seed` (a flash body -- the source battery to cold-boot -> CONTINUE, same plumbing
    `boot-check` uses), retrying the WHOLE emulator process (not just an in-script step):
    observed 2026-09-23, EmuHawk itself intermittently exits with no RESULT line (no Lua error,
    no Windows crash record) somewhere in save_via_menu's post-save "wait for the dialog to
    close" loop -- ONLY ever reproduced after a savestate.load() mid-script, never after a real
    cold boot (which is what every kind uses now; kept here in case the flakiness turns out to
    be broader than that one instrument). A crashed run's `proc.poll()` reports the launched
    process gone, but `tasklist` still shows an EmuHawk.exe alive minutes later (run_gate.py's
    own taskkill only fires when its PID is still running, so this orphan is never cleaned up).
    Clean up before each attempt, but ONLY our own runs (kill_our_emuhawk/our_emuhawk_pids) -- a
    blanket /IM kill here previously took out a concurrent Gen 2 worktree's in-flight gate runs;
    the two emulator lanes are allowed to run at the same time. Returns
    (passed, text, run_dir, battery)."""
    passed, text, run_dir, battery = False, "", None, ""
    for attempt in range(1, max_attempts + 1):
        kill_our_emuhawk()
        rom_rel, run_dir, battery = _prepare_run(name, rom, seed=seed,
                                                  saveram_name_override=saveram_name)
        print(f"cold boot: {run_dir} seeded with {len(seed)} bytes, battery will be "
              f"{battery}" + (f" (process attempt {attempt}/{max_attempts})" if attempt > 1 else ""))
        passed, text = _launch(FR_PARTY_LUA, rom_rel, run_dir, rr=False, timeout=timeout,
                                extra_env=extra_env, title=title)
        print(text.rstrip())
        if passed or "RESULT: FAIL" in text:
            break   # a real FAIL verdict is not retried; only a crashed/no-verdict process is
        print(f"make-party: process attempt {attempt}/{max_attempts} left no RESULT line "
              f"(EmuHawk exited without one); retrying" if attempt < max_attempts else
              f"make-party: giving up after {max_attempts} process attempts", file=sys.stderr)
    return passed, text, run_dir, battery


def cmd_make_fr_party(args: argparse.Namespace) -> int:
    """Cold-boot a source battery (--seed) -> CONTINUE and drive lua/tests/gen3_fixture_from_
    state.lua with scripted normal inputs (walk, heal, flee every incidental wild encounter --
    never fight) to a party fixture, saved in-game. BUILD ORDER MATTERS: --kind town first
    (--seed the accepted-but-unhealed battle fixture; heals the party at the Viridian Center and
    saves standing at Viridian's own south tile), then --kind battle (--seed town's own output;
    walks the short leg back to Route 1's grass origin and saves there) -- a single cold-boot
    session covering the WHOLE heal-and-return round trip reproducibly crashed EmuHawk (see the
    Lua driver's own header comment for the physical evidence); two short sessions split at
    Viridian never did. No savestate is used anywhere either way."""
    if not args.out:
        print("make-fr-party FAIL: --out is required", file=sys.stderr)
        return 1
    try:
        title = _checked_title(args)
        rom = resolve_rom(title, args.rom)
    except (ValueError, FileNotFoundError) as exc:
        print(f"make-fr-party FAIL: {exc}", file=sys.stderr)
        return 1
    saveram = args.saveram_name or str(PARTY_TITLES[title]["saveram"])
    seed_path = Path(args.seed)
    if not seed_path.exists():
        print(f"make-fr-party FAIL: --seed {seed_path} does not exist", file=sys.stderr)
        return 1
    try:
        seed = codec.split_rtc(seed_path.read_bytes())[0]
        ok, msg = codec.qualify_flash(seed)
        if not ok:
            raise ValueError(f"--seed does not qualify: {msg}")
    except (ValueError, OSError) as exc:
        print(f"make-fr-party FAIL: {exc}", file=sys.stderr)
        return 1
    extra_env = {"SLINK_GEN3_FIXTURE_KIND": args.kind}

    passed, _text, run_dir, battery = _run_fr_party_attempts(
        f"make_fr_party_{title}_{args.kind}", rom, saveram, args.timeout, extra_env, seed,
        title=title)
    if not passed:
        print("make-fr-party FAIL: the driver did not report PASS", file=sys.stderr)
        return 1

    flushed = _flushed_saveram(run_dir, battery)
    if flushed is None:
        print(f"make-fr-party FAIL: EmuHawk left no *.SaveRAM in {run_dir}", file=sys.stderr)
        return 1
    try:
        body = import_savedata(flushed.read_bytes(), rr=False)
    except (ValueError, OSError) as exc:
        print(f"make-fr-party FAIL: candidate refused: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    r = qualify_one(body, rr=False)
    print(f"wrote {out} ({len(body)} bytes) title={title} sha256={sha256_hex(body)} "
          f"slot={r['slot']} counter={r['counter']} trainer={r['trainer_name']!r}"
          f"#{r['trainer_id']:08X} party={r['party']}")
    return 0


# ---------------------------------------------------------------------------
# Emerald (card E1-FIX, EF-10): a DISCLOSED O-33 SYNTH seed, re-saved natively by the game
#
# `make-emerald` writes a bootable Emerald flash save from pret facts (the SYNTH setup), cold-boots
# it on the real ROM -> CONTINUE -> in-game SAVE, and keeps the GAME's own re-save as the fixture.
# The seed sets SaveBlock2.specialSaveWarpFlags = CONTINUE_GAME_WARP, so CONTINUE runs pret's own
# warp-in (CB2_ContinueSavedGame -> WarpIntoMap -> CB2_LoadMap, pret src/overworld.c:1739-1746)
# instead of restoring a saved map view / object-event table the seed does not carry. The game
# clears that flag (ClearContinueGameWarpStatus) and then writes a complete SaveBlock1 of its own;
# `emerald_fixture_problems` refuses a result where it is still set. Only the boot, the warp-in
# and the save run natively; everything in the seed is listed in tests/fixtures/gen3/README.md.
# Struct offsets are pret's own annotations (pokeemerald c65e93f2 include/global.h).
# ---------------------------------------------------------------------------

EMERALD_ROM = "Pokemon - Emerald Version (USA, Europe).gba"
# BizHawk gamedb_gba.txt:1979 knows the clean dump (sha1 F3AE0881...), so EmuHawk files the battery
# under the gamedb title, not under the staged ROM's filename.
EMERALD_SAVERAM = "Pokemon - Emerald Version (USA, Europe).SaveRAM"
EMERALD_BOOT_LUA = "lua/tests/gen3_emerald_boot_check.lua"

# kind -> (pret map dir, mapGroup, mapNum, LAYOUT_* id, x, y). Group/num are the map's position in
# data/maps/map_groups.json; the layout id is its 1-based index in data/layouts/layouts.json
# (gMapLayouts[mapLayoutId - 1], src/overworld.c:532-538). Tiles come from data/layouts/*/map.bin +
# metatile attributes; tests/unit/test_gen3_fixture_qualify_emerald.py re-derives every claim.
EMERALD_KINDS = {
    # HEAL_LOCATION_OLDALE_TOWN (src/data/heal_locations.json), one step S of the Pokemon Center
    # door warp (6,16) (data/maps/OldaleTown/map.json); towns carry no wild encounters
    "town": ("OldaleTown", 0, 10, 11, 6, 17),
    # MB_TALL_GRASS inside the (19..25, 16..17) patch; no trainer faces it
    "battle": ("Route102", 0, 17, 18, 21, 16),
    # one step W of Youngster Calvin's sight line: he stands at (33,14) facing down with sight 3
    # (data/maps/Route102/map.json), so one Right step onto (33,16) starts his battle
    "trainer": ("Route102", 0, 17, 18, 32, 16),
}
EMERALD_HEAL = (0, 10, 6, 17)          # HEAL_LOCATION_OLDALE_TOWN: MAP_OLDALE_TOWN (6,17)
EMERALD_OT = ("EMER", 0x20250925)      # SYNTH identity; `derive-b --title emerald` makes the _b side
EMERALD_SEED_COUNTER = 1               # the seed's slot is 1; the game's save writes counter 2, slot 0

# The party: one starter as ScriptGiveMon would build it at Lv5 on Route 101 (pret src/pokemon.c
# CreateBoxMon/CalculateMonStats). Species facts, pokeemerald c65e93f2:
#   SPECIES_MUDKIP 283 (include/constants/species.h:289); base 50/70/50/40/50/50, genderRatio
#   PERCENT_FEMALE(12.5) = 31, STANDARD_FRIENDSHIP 70, GROWTH_MEDIUM_SLOW
#   (src/data/pokemon/species_info.h:7799-7821); Lv1 moves TACKLE 33 (pp 35) and GROWL 45 (pp 40)
#   (level_up_learnsets.h:3676-3678, battle_moves.h:432-438/588-594).
MUDKIP = {"species": 283, "name": "MUDKIP", "gender_ratio": 31, "friendship": 70,
          "base": {"hp": 50, "attack": 70, "defense": 50, "speed": 40,
                   "sp_attack": 50, "sp_defense": 50},
          "moves": [33, 45, 0, 0], "pp": [35, 40, 0, 0]}
STARTER_LEVEL, STARTER_IV = 5, 15
MAPSEC_ROUTE_101 = 16      # src/data/region_map/region_map_sections.json, index of MAPSEC_ROUTE_101
VERSION_EMERALD, LANGUAGE_ENGLISH, ITEM_POKE_BALL = 3, 2, 4   # constants/global.h:10,21; items.h:10
# Flags a player holds once Birch has handed over the Pokedex (FLAG_ADVENTURE_STARTED: its comment
# in constants/flags.h:136 is "RECEIVED Pokedex") -- it is what unblocks Oldale's west exit to
# Route 102 (data/maps/OldaleTown/scripts.inc OnTransition). Everything else a new game sets comes
# from EventScript_ResetAllMapFlags (data/scripts/new_game.inc:115), read from pret at build time.
EMERALD_STORY_FLAGS = ("FLAG_SYS_POKEMON_GET", "FLAG_ADVENTURE_STARTED",
                       "FLAG_RECEIVED_POTION_OLDALE", "FLAG_VISITED_OLDALE_TOWN",
                       "FLAG_HIDE_OLDALE_TOWN_RIVAL", "FLAG_HIDE_ROUTE_103_RIVAL")


def pret_emerald() -> Path:
    """The pokeemerald checkout: $SLINK_PRET_EMERALD, else <root>/.cache/pret/pokeemerald for this
    repo root and the checkout a worktree belongs to (the _rom_candidates search)."""
    env = os.environ.get("SLINK_PRET_EMERALD")
    roots = [Path(env)] if env else [c.parent for c in _rom_candidates(".cache/pret/pokeemerald/x")]
    for root in roots:
        if (root / "include" / "global.h").exists():
            return root
    raise FileNotFoundError("pret pokeemerald not found in " + ", ".join(map(str, roots))
                            + " -- set SLINK_PRET_EMERALD")


def pret_flag_ids(pret: Path, names) -> list[int]:
    """Evaluate FLAG_* names from include/constants/flags.h (+ opponents.h for MAX_TRAINERS_COUNT,
    which TRAINER_FLAGS_END and so every SYSTEM_FLAGS flag hangs off)."""
    defs = {}
    for rel in ("include/constants/flags.h", "include/constants/opponents.h"):
        text = (pret / rel).read_text(encoding="utf-8")
        for m in re.finditer(r"^#define\s+(\w+)\s+(.+)$", text, re.M):
            defs[m.group(1)] = m.group(2).split("//")[0].strip()

    def value(name: str) -> int:
        expr = re.sub(r"(?<!\w)[A-Za-z_]\w*", lambda m: str(value(m.group(0))), defs[name])
        if not re.fullmatch(r"[\s0-9a-fA-FxX+\-()]+", expr):
            raise ValueError(f"{name}: unsupported expression {defs[name]!r}")
        return int(eval(expr, {"__builtins__": {}}))   # digits/+/-/() only, checked above
    return [value(n) for n in names]


def emerald_new_game_flags(pret: Path) -> list[int]:
    """EventScript_ResetAllMapFlags's setflag list (new_game.inc:115-...) plus EMERALD_STORY_FLAGS."""
    text = (pret / "data/scripts/new_game.inc").read_text(encoding="utf-8")
    block = re.split(r"^\s*end\s*$", text.split("EventScript_ResetAllMapFlags::", 1)[1],
                     maxsplit=1, flags=re.M)[0]
    names = re.findall(r"^\s*setflag (\w+)", block, re.M)
    return pret_flag_ids(pret, [*names, *EMERALD_STORY_FLAGS])


def emerald_starter(ot_name: str, tid: int) -> dict:
    """The codec dict for a Lv5 Mudkip. Personality: the first value from 'MUDK' that is Hardy
    (neutral nature, pid % 25 == 0), male (pid & 0xFF >= genderRatio) and not shiny for `tid`."""
    pid = next(p for p in itertools.count(0x4D55444B)
               if p % 25 == 0 and (p & 0xFF) >= MUDKIP["gender_ratio"]
               and ((tid & 0xFFFF) ^ (tid >> 16) ^ (p & 0xFFFF) ^ (p >> 16)) >= 8)
    lv = STARTER_LEVEL
    stats = {k: (2 * b + STARTER_IV) * lv // 100 + 5 for k, b in MUDKIP["base"].items()}
    stats["hp"] = (2 * MUDKIP["base"]["hp"] + STARTER_IV) * lv // 100 + lv + 10
    return {
        "personality": pid, "ot_id": tid, "nickname": MUDKIP["name"], "language": LANGUAGE_ENGLISH,
        "is_bad_egg": 0, "has_species": 1, "is_egg_flag": 0, "block_box_rs": 0, "flags_unused": 0,
        "ot_name": ot_name, "markings": 0, "unknown": 0,
        "species": MUDKIP["species"], "held_item": 0,
        "experience": 6 * lv ** 3 // 5 - 15 * lv ** 2 + 100 * lv - 140,   # EXP_MEDIUM_SLOW
        "pp_bonuses": 0, "friendship": MUDKIP["friendship"], "growth_filler": 0,
        "moves": list(MUDKIP["moves"]), "pp": list(MUDKIP["pp"]),
        "evs": dict.fromkeys(MUDKIP["base"], 0), "contest": [0] * 6,
        "pokerus": 0, "met_location": MAPSEC_ROUTE_101, "met_level": lv,
        "met_game": VERSION_EMERALD, "pokeball": ITEM_POKE_BALL, "ot_gender": 0,
        "ivs": dict.fromkeys(MUDKIP["base"], STARTER_IV),
        "is_egg": 0, "ability_num": pid & 1, "ribbons": 0,
        "status": 0, "level": lv, "mail": 0xFF, "max_hp": stats["hp"], **stats,
    }


def _warp(group: int, num: int, x: int, y: int) -> bytes:
    """struct WarpData (global.h:581-588): s8 mapGroup, mapNum, warpId, pad, s16 x, y. warpId is
    WARP_ID_NONE (-1) so SetPlayerCoordsFromWarp uses x/y (overworld.c:603-615)."""
    return struct.pack("<bbbxhh", group, num, -1, x, y)


def build_emerald_seed(kind: str, flags: list[int]) -> bytes:
    """The SYNTH flash image for `kind` (see the section header). `flags` = emerald_new_game_flags."""
    _map, group, num, layout_id, x, y = EMERALD_KINDS[kind]
    name, tid = EMERALD_OT
    sb2 = bytearray(codec.SAVEBLOCK2_SIZE_EMERALD)
    sb2[0x00:0x08] = codec.encode_name(name, 8)   # playerName[PLAYER_NAME_LENGTH + 1], global.h:510
    sb2[0x08] = 0                                 # playerGender MALE, :511
    sb2[0x09] = 1                                 # specialSaveWarpFlags CONTINUE_GAME_WARP (save_location.h:5), :512
    sb2[0x0A:0x0E] = tid.to_bytes(4, "little")    # playerTrainerId, :513
    sb2[0x14] = 1                                 # optionsTextSpeed MID, :519; SetDefaultOptions new_game.c:91-99
    # encryptionKey (+0xAC, :532) stays 0 as NewGameInitData leaves it (new_game.c:155): money is plain

    sb1 = bytearray(codec.SAVEBLOCK1_SIZE_EMERALD)
    sb1[0x00:0x04] = struct.pack("<hh", x, y)     # pos, global.h:986
    sb1[0x04:0x0C] = _warp(group, num, x, y)      # location, :987
    sb1[0x0C:0x14] = _warp(group, num, x, y)      # continueGameWarp, :988
    sb1[0x1C:0x24] = _warp(*EMERALD_HEAL)         # lastHealLocation, :990 (SetLastHealLocationWarp)
    sb1[0x32:0x34] = layout_id.to_bytes(2, "little")   # mapLayoutId, :997 (0 = a NULL layout)
    sb1[codec.SB1_PARTY_COUNT_OFFSET_EMERALD] = 1
    start = codec.SB1_PARTY_OFFSET_EMERALD
    sb1[start:start + codec.PARTY_MON_SIZE] = codec.encode_party_mon(emerald_starter(name, tid))
    sb1[0x490:0x494] = (3000).to_bytes(4, "little")    # money, :1002; SetMoney(3000), new_game.c:172
    for flag in flags:                                 # flags[NUM_FLAG_BYTES], :1020
        sb1[0x1270 + flag // 8] |= 1 << (flag % 8)

    storage = bytearray(codec.STORAGE_SIZE)            # ResetPokemonStorageSystem, pokemon_storage_system.c:1729-1749
    for box in range(codec.BOXES_PER_STORE):
        at = codec.BOX_NAMES_OFFSET + box * 9          # boxNames[14][BOX_NAME_LENGTH + 1], pokemon_storage_system.h:23
        storage[at:at + 9] = codec.encode_name(f"BOX{box + 1}", 9)
        storage[0x83C2 + box] = box % 4                # boxWallpapers, :24; % (MAX_DEFAULT_WALLPAPER + 1), wallpapers.h:21

    layout = codec.slot_layout(title=codec.TITLE_EMERALD)
    blocks = {"sb2": bytes(sb2), "sb1": bytes(sb1), "storage": bytes(storage)}
    image = bytearray(b"\xFF" * codec.FLASH_SIZE)      # erased flash: the other slot reads EMPTY
    half = codec.NUM_SECTORS_PER_SLOT * (EMERALD_SEED_COUNTER % codec.NUM_SAVE_SLOTS)
    for entry in layout:
        chunk = blocks[entry["object"]][entry["offset"]:entry["offset"] + entry["size"]]
        at = (half + entry["id"]) * codec.SECTOR_SIZE
        image[at:at + codec.SECTOR_SIZE] = codec.write_sector(chunk, entry["id"],
                                                              EMERALD_SEED_COUNTER, layout)
    return bytes(image)


def emerald_fixture_problems(body: bytes, kind: str) -> list[str]:
    """What a NATIVE re-save of a `kind` seed must show: it qualifies, the game cleared the
    continue-game warp (so it ran the warp-in and wrote SaveBlock1 itself), the player stands on
    the kind's tile of the kind's map, and the party is the one Mudkip."""
    ok, msg = codec.qualify_flash(body, title=codec.TITLE_EMERALD)
    if not ok:
        return [f"does not qualify as Emerald: {msg}"]
    parsed = codec.parse_flash(body, title=codec.TITLE_EMERALD)
    sb1, sb2 = parsed["sb1"], parsed["sb2"]
    _map, group, num, layout_id, x, y = EMERALD_KINDS[kind]
    problems = []
    if sb2[0x09] & 1:
        problems.append("specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save")
    where = struct.unpack_from("<hhbb", sb1, 0)
    if where != (x, y, group, num):
        problems.append(f"player at (x,y,group,num)={where}, expected {(x, y, group, num)}")
    if int.from_bytes(sb1[0x32:0x34], "little") != layout_id:
        problems.append(f"mapLayoutId {int.from_bytes(sb1[0x32:0x34], 'little')} != {layout_id}")
    party = codec.party_from_save(body, title=codec.TITLE_EMERALD)
    if [(m["species"], m["level"], m["checksum_ok"]) for m in party] != [(MUDKIP["species"],
                                                                          STARTER_LEVEL, True)]:
        problems.append(f"party is not one Lv{STARTER_LEVEL} Mudkip: {party}")
    return problems


def cmd_make_emerald(args: argparse.Namespace) -> int:
    rom = args.rom or next((str(c) for c in _rom_candidates(EMERALD_ROM) if c.exists()), None)
    if not rom:
        print(f"make-emerald FAIL: {EMERALD_ROM!r} not found -- pass --rom", file=sys.stderr)
        return 1
    try:
        seed = build_emerald_seed(args.kind, emerald_new_game_flags(pret_emerald()))
    except (OSError, ValueError, KeyError) as exc:
        print(f"make-emerald FAIL: cannot build the SYNTH seed: {exc}", file=sys.stderr)
        return 1
    before = qualify_one(seed, rr=False, title=codec.TITLE_EMERALD)
    rom_rel, run_dir, battery = _prepare_run(
        f"make_emerald_{args.kind}", rom, seed=seed,
        saveram_name_override=args.saveram_name or EMERALD_SAVERAM)
    print(f"SYNTH seed {args.kind}: {run_dir / battery} sha256={sha256_hex(seed)} "
          f"counter={before['counter']} party={before['party']}")
    passed, text = _launch(EMERALD_BOOT_LUA, rom_rel, run_dir, rr=False, timeout=args.timeout,
                           title="emerald")
    print(text.rstrip())
    flushed = _flushed_saveram(run_dir, battery)
    if not passed or flushed is None:
        print("make-emerald FAIL: the driver did not report PASS or left no *.SaveRAM",
              file=sys.stderr)
        return 1
    try:
        body = import_savedata(flushed.read_bytes(), rr=False, title=codec.TITLE_EMERALD)
    except (ValueError, OSError) as exc:
        print(f"make-emerald FAIL: candidate refused: {exc}", file=sys.stderr)
        return 1
    after = qualify_one(body, rr=False, title=codec.TITLE_EMERALD)
    problems = boot_check_verdict(before, after)[1] + emerald_fixture_problems(body, args.kind)
    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("make-emerald FAIL: the re-save is not the fixture asked for", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    print(f"wrote {out} ({len(body)} bytes) sha256={sha256_hex(body)} slot={after['slot']} "
          f"counter={after['counter']} trainer={after['trainer_name']!r}"
          f"#{after['trainer_id']:08X} party={after['party']}")
    return 0


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
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
    p_qualify.add_argument("--title", choices=[codec.TITLE_FRLG, codec.TITLE_EMERALD],
                           default=codec.TITLE_FRLG, help="vanilla save layout (default frlg)")
    p_qualify.set_defaults(func=cmd_qualify)

    p_derive = sub.add_parser("derive-b", help="distinct-OT fixture derivation")
    p_derive.add_argument("a")
    p_derive.add_argument("b")
    p_derive.add_argument("--rr", action="store_true")
    p_derive.add_argument("--title", choices=[codec.TITLE_FRLG, codec.TITLE_EMERALD],
                          default=codec.TITLE_FRLG, help="vanilla save layout (default frlg)")
    p_derive.set_defaults(func=cmd_derive_b)

    p_boot = sub.add_parser("boot-check",
                            help="EMULATOR: cold boot -> CONTINUE -> re-save -> reload")
    p_boot.add_argument("--rom", required=True, help="the .gba to boot (staged space-free)")
    p_boot.add_argument("--fixture", required=True)
    p_boot.add_argument("--rr", action="store_true")
    p_boot.add_argument("--title", default=None,
                        help="profile title for the run (default: firered, or radical_red with "
                             "--rr); emerald boots lua/tests/gen3_emerald_boot_check.lua")
    p_boot.add_argument("--saveram-name", default=None,
                        help="battery filename to seed, when BizHawk's gamedb names it")
    p_boot.add_argument("--timeout", type=int, default=600)
    p_boot.set_defaults(func=cmd_boot_check)

    p_fr = sub.add_parser("make-fr", help="EMULATOR: scripted NEW GAME -> fixture "
                                          "(FireRed and LeafGreen; the same intro drives both)")
    p_fr.add_argument("--rom", required=True)
    p_fr.add_argument("--out", required=True)
    p_fr.add_argument("--title", default=None,
                      help="party-lane title (default firered): firered or leafgreen; a title "
                           "without a calibrated scripted intro refuses by name")
    p_fr.add_argument("--saveram-name", default=None)
    p_fr.add_argument("--timeout", type=int, default=1800)
    p_fr.set_defaults(func=cmd_make_fr)

    # `make-party` is the title-aware name; `make-fr-party` stays as the alias every existing
    # invocation and the README use (same handler, same flags).
    p_frp = sub.add_parser("make-party", aliases=["make-fr-party"],
                           help="EMULATOR: cold-boot --seed, walk/heal/flee, save in-game "
                                "(aliases: make-fr-party)")
    p_frp.add_argument("--rom", default=None,
                       help="the ROM to boot (default: the --title's dump at the checkout root)")
    p_frp.add_argument("--out", required=True)
    p_frp.add_argument("--title", default=None,
                       help="firered | leafgreen (default firered). LeafGreen is the same "
                            "engine and the same shared maps; the party driver is title-aware.")
    p_frp.add_argument("--kind", choices=["battle", "town"], required=True)
    p_frp.add_argument("--seed", required=True,
                       help="battery .sav to cold-boot -> CONTINUE (town: the accepted-but-"
                            "unhealed battle fixture; battle: town's own healed output -- "
                            "build town FIRST)")
    p_frp.add_argument("--saveram-name", default=None)
    p_frp.add_argument("--timeout", type=int, default=1800)
    p_frp.set_defaults(func=cmd_make_fr_party)

    p_em = sub.add_parser("make-emerald", help="EMULATOR: SYNTH Emerald seed -> CONTINUE -> "
                                              "in-game SAVE; the re-save is the fixture")
    p_em.add_argument("--kind", choices=sorted(EMERALD_KINDS), required=True)
    p_em.add_argument("--out", required=True)
    p_em.add_argument("--rom", default=None, help=f"default: {EMERALD_ROM} at the checkout root")
    p_em.add_argument("--saveram-name", default=None)
    p_em.add_argument("--timeout", type=int, default=600)
    p_em.set_defaults(func=cmd_make_emerald)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
