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
import json
import os
import shutil
import stat
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
        if parsed["sb1"][codec.SB1_PARTY_COUNT_OFFSET] > codec.PARTY_CAPACITY:
            raise ValueError("RR party count exceeds six")
        party = codec.rr_party_from_save(body)
        boxes = codec.rr_boxes_from_save(body)
        result["party"] = [{"species": m["species"], "level": m["level"]} for m in party]
        result["boxes"] = sum(bool(m["species"]) for box in boxes for m in box)
        result["boxes_note"] = ("RR layout pinned; extension sectors 30/31 have no checksum "
                                "or generation counter (rr_save_layout.md §5, §7)")
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


def derive_b(a_body: bytes, *, rr: bool = False) -> tuple[bytes, list[str]]:
    """Variant-specific distinct-OT derivation (flash_save.md §5). Returns
    (new_flash_body, manifest_lines); raises ValueError if the source does
    not qualify."""
    if rr:
        return _derive_b_rr(a_body)
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
        b_body, manifest = derive_b(a_body, rr=args.rr)
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    ok, msg = codec.qualify_flash(b_body, cfru=args.rr)
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
RUN_DIR = Path(REPO) / "patch" / "build" / "gen3_fixture_runs"
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
        # gen3_fr_newgame_inputs.lua's intro legs are frame-timed and were verified on FR US 1.0
        # only (its own header banner). LG's intro is the same engine, but nobody has calibrated
        # its naming screens, so the scripted NEW GAME lane refuses LG by name.
        "scripted_newgame": True,
    },
    "leafgreen": {
        "rom": "Pokemon - LeafGreen Version (USA).gba",
        "saveram": "Pokemon - LeafGreen Version (USA).SaveRAM",
        "scripted_newgame": False,
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
    try:
        from gen1_playthrough import write_run_config
        write_run_config(src, dst)
    except Exception:                       # unparseable config: a plain copy, same fallback
        shutil.copyfile(src, dst)
    os.makedirs(saveram_dir, exist_ok=True)
    with open(dst, encoding="utf-8-sig") as f:
        cfg = json.load(f)
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
    keys_before = [(m["species"], m["level"]) for m in (before.get("party") or [])]
    keys_after = [(m["species"], m["level"]) for m in (after.get("party") or [])]
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
    before = qualify_one(data, rr=args.rr)
    if not before["ok"]:
        print(f"BOOT-CHECK FAIL {fixture}: the fixture itself does not qualify: "
              f"{before['message']}", file=sys.stderr)
        return 1
    rom_rel, run_dir, battery = _prepare_run(
        f"bootcheck_{fixture.stem}", args.rom,
        seed=codec.split_rtc(data)[0], saveram_name_override=args.saveram_name)
    print(f"seeded {run_dir / battery} from {fixture} (counter={before['counter']})")

    passed, text = _launch(BOOT_CHECK_LUA, rom_rel, run_dir, rr=args.rr, timeout=args.timeout,
                           title=getattr(args, "title", None))
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
    after = qualify_one(codec.split_rtc(flushed.read_bytes())[0], rr=args.rr)
    ok, problems = boot_check_verdict(before, after)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print(f"BOOT-CHECK {'PASS' if ok else 'FAIL'} {fixture} counter={before['counter']}"
          f"->{after['counter']} party={after.get('party')}")
    return 0 if ok else 1


def cmd_make_fr(args: argparse.Namespace) -> int:
    """The scripted NEW GAME lane. FireRed only: gen3_fr_newgame_inputs.lua's intro legs are
    frame-timed and were verified on FR US 1.0 (its own header banner), and LG's naming screens
    have never been calibrated. Refused by name -- before anything is staged or launched -- so a
    caller who cannot supply a calibrated intro finds out here, not from a mistuned run."""
    try:
        title = _checked_title(args)
    except ValueError as exc:
        print(f"make-fr FAIL: {exc}", file=sys.stderr)
        return 1
    if not PARTY_TITLES[title]["scripted_newgame"]:
        print(f"make-fr FAIL: {title} has no calibrated scripted NEW GAME. "
              f"lua/tests/gen3_fr_newgame_inputs.lua's intro legs (copyright/Oak/gender/two "
              f"naming screens) are placed by elapsed frames and verified on FireRed US 1.0 "
              f"only; LG's screens are uncalibrated and the driver refuses to guess. For an LG "
              f"pre-starter save: play the intro by hand (normal inputs) to Pallet Town, save "
              f"in-game, then `import` it -- see tests/fixtures/gen3/README.md. For a party "
              f"fixture from such a save: `make-fr-party --title leafgreen --seed <it>`.",
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
    p_qualify.set_defaults(func=cmd_qualify)

    p_derive = sub.add_parser("derive-b", help="distinct-OT fixture derivation")
    p_derive.add_argument("a")
    p_derive.add_argument("b")
    p_derive.add_argument("--rr", action="store_true")
    p_derive.set_defaults(func=cmd_derive_b)

    p_boot = sub.add_parser("boot-check",
                            help="EMULATOR: cold boot -> CONTINUE -> re-save -> reload")
    p_boot.add_argument("--rom", required=True, help="the .gba to boot (staged space-free)")
    p_boot.add_argument("--fixture", required=True)
    p_boot.add_argument("--rr", action="store_true")
    p_boot.add_argument("--title", default=None,
                        help="profile title for the run (default: firered, or radical_red with --rr)")
    p_boot.add_argument("--saveram-name", default=None,
                        help="battery filename to seed, when BizHawk's gamedb names it")
    p_boot.add_argument("--timeout", type=int, default=600)
    p_boot.set_defaults(func=cmd_boot_check)

    p_fr = sub.add_parser("make-fr", help="EMULATOR: scripted NEW GAME on FireRed -> fixture "
                                          "(FireRed only; LeafGreen refuses by name)")
    p_fr.add_argument("--rom", required=True)
    p_fr.add_argument("--out", required=True)
    p_fr.add_argument("--title", default=None,
                      help="party-lane title (default firered); a title without a calibrated "
                           "scripted intro refuses by name")
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

    return ap


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
