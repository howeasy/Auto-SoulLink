#!/usr/bin/env python3
"""Derive the Cherrygrove-scene SaveRAM for the rival-gate measurement from the pinned Polished warp fixture (SYNTH, O-33).

    python tools/polished_live/derive_rival_save.py --out <rival_scene.SaveRAM> [--src <fixture.SaveRAM>] [--force]

Plan: docs/polished/RIVAL_STAGING.md section 2. The ONLY game change is wCherrygroveCitySceneID 00 -> 01 in BOTH save
copies; both checksums are then recomputed. On the pinned input that is exactly four bytes: 0x1782, 0x1F0D, 0x2582, 0x2D0D.

PURE: `derive_rival_scene` maps bytes to bytes (never mutates the input, no emulator, no files). `verify_rival_scene` is the
independent verifier: it shares NO offset or helper with the builder (every number is written out again below) and it
reports every way the derivative departs from the declaration. The builder runs the verifier on its own output and refuses
to return anything the verifier rejects.

Facts (each re-read from data/polished/polished_slink.sym and the pinned source at
F:/slink-work/cache/polished/src, commit 3fa43192379df5c3e7b09a08e4d5d79af4f02f42, = data/polished/overlay_provenance.json):
  flat SaveRAM = bank * 0x2000 + addr - 0xA000
  sGameData 01:a008 -> 0x2008, sBackupGameData 00:b208 -> 0x1208      (sym; src/ram/sram.asm:19-23,48-52)
  sGameDataEnd 01:ab83 -> 0x2B83, sBackupGameDataEnd 00:bd83 -> 0x1D83
  sChecksum 01:ad0d -> 0x2D0D, sBackupChecksum 00:bf0d -> 0x1F0D
  wPlayerData 01:d478 is the first byte of the saved game data (sPlayerData is the first member of sGameData)
  wCherrygroveCitySceneID 01:d9f2 -> offset 0x57A inside the game data (inside wPlayerData..wPlayerDataEnd 01:dc9e;
      src/ram/wramx.asm:875,1073,1323) -> main 0x2582, backup 0x1782. Backup displacement is 0xE00, not 0x1000.
  scene 1 at (33,7) is the rival trigger and scene 0 the guide (src/maps/CherrygroveCity.asm:15-17), and
      src/data/maps/scenes.asm:25 maps CHERRYGROVE_CITY to wCherrygroveCitySceneID.
  preconditions (all preserved, none edited): map group 24 / map 3 / Y 12 / X 48 at wMapGroup (+0x834 -> 0x283C / 0x1A3C);
      starter flags EVENT_GOT_{CYNDAQUIL,TOTODILE,CHIKORITA}_FROM_ELM = event 28/29/30 = byte 3 mask 0x70 of wEventFlags
      (01:da5a, +0x5E2 -> 0x25EA / 0x17EA; src/constants/event_flags.asm:42-44; bits are LSB-first, src/home/flag.asm:1-40);
      EVENT_RIVAL_CHERRYGROVE_CITY = event 0x687 = byte 0xD0 mask 0x80 (-> 0x26BA / 0x18BA) must stay SET, the script
      appears the rival natively (src/maps/CherrygroveCity.asm:88-108).

SYNTH: the output skips the starter / Mr. Pokemon story by setting the scene directly. It is NOT independently played, and
whether the native CONTINUE accepts it and whether the walk reaches the rival are evaluated separately (live).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

REVISION = "derive_rival_save/1 (pol-rivalb, 2026-10-07)"
STATEMENT = ("SYNTH Cherrygrove-scene derivative of an existing SYNTH setup fixture (O-33): sets wCherrygroveCitySceneID "
             "00 -> 01 in both save copies and re-seals both checksums; not independently played; the rival fight "
             "itself must run natively; native CONTINUE/walk/trigger evaluated separately (live)")

PINNED_SRC_SHA256 = "75c7a5dc30126f746567202cfb39fe583dfa04eb226063560541f6cbd29f36b8"
EXPECTED_OUT_SHA256 = "030c62ff898050d81d80dea19677e8520e2f707dae0c35f873d87e79cf7ac1ae"
SOURCE_COMMIT = "3fa43192379df5c3e7b09a08e4d5d79af4f02f42"
SOURCE_CANDIDATES = (Path("F:/slink-work/lanes/pol-live/fixture/polished_overlay_warp.SaveRAM"),
                     Path("F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM"))
# The committed fixtures are never an output target.
PROTECTED_DIRS = (REPO / "tests" / "fixtures",)

SAVE_SIZE = 32790          # 32768 cartridge SRAM + 22-byte RTC footer; the plan preserves all of it
CART_SIZE = 32768
FOOTER_LEN = SAVE_SIZE - CART_SIZE


class Copy:
    """One half of the SaveRAM (the geometry of main or backup)."""

    def __init__(self, name, start, end, checksum_at, low_marker_at, high_marker_at):
        self.name, self.start, self.end = name, start, end
        self.checksum_at, self.low_marker_at, self.high_marker_at = checksum_at, low_marker_at, high_marker_at


MAIN = Copy("main", 0x2008, 0x2B83, 0x2D0D, 0x2007, 0x2D0F)
BACKUP = Copy("backup", 0x1208, 0x1D83, 0x1F0D, 0x1207, 0x1F0F)
COPIES = (MAIN, BACKUP)

SCENE_IN_GAME_DATA = 0x57A             # wCherrygroveCitySceneID (01:d9f2) - wPlayerData (01:d478)
SCENE_OFFSETS = tuple(c.start + SCENE_IN_GAME_DATA for c in COPIES)   # (0x2582, 0x1782)
SCENE_OLD, SCENE_NEW = 0x00, 0x01

MAP_IN_GAME_DATA = 0x834               # wMapGroup (01:dcac) - wPlayerData
ROUTE29_POSITION = bytes((24, 3, 12, 48))
EVENT_FLAGS_IN_GAME_DATA = 0x5E2       # wEventFlags (01:da5a) - wPlayerData
STARTER_BYTE_IN_FLAGS, STARTER_MASK = 3, 0x70
RIVAL_BYTE_IN_FLAGS, RIVAL_MASK = 0xD0, 0x80
COUNT_IN_GAME_DATA = 0x856             # wPartyCount (01:dcce) - wPlayerData
VERSION_AT, PHASE_AT = 0x0BE2, 0x0BE5
SAVE_VERSION = b"\x00\x0a"
LOW_MARKER, HIGH_MARKER = 0x61, 0x7F


class RivalError(ValueError):
    """Base of every named refusal (raised before any output is returned)."""


class RivalSourceError(RivalError):
    """The input is not the pinned file or not a structurally valid save (hash, size, markers, version, checksums)."""


class RivalPreconditionError(RivalError):
    """The input is a valid save but not in the state this derivation is defined for."""


class RivalVerifyError(RivalError):
    """The independent verifier rejected what the builder produced (the builder is wrong, not the input)."""


# ── pure helpers ─────────────────────────────────────────────────────────────

def sha256(data) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def _region_sum(buf, copy) -> int:
    return sum(buf[copy.start:copy.end]) & 0xFFFF


def _stored_sum(buf, copy) -> int:
    return int.from_bytes(buf[copy.checksum_at:copy.checksum_at + 2], "little")


def _at(copy, offset) -> int:
    return copy.start + offset


def _layout_problems(save) -> list[str]:
    if not isinstance(save, (bytes, bytearray)):
        return [f"input: expected bytes, got {type(save).__name__}"]
    if len(save) != SAVE_SIZE:
        extra = " (the plan forbids the truncated 32768-byte lane copy)" if len(save) == CART_SIZE else ""
        return [f"size: expected exactly {SAVE_SIZE} bytes, got {len(save)}{extra}"]
    out = []
    for c in COPIES:
        if save[c.low_marker_at] != LOW_MARKER:
            out.append(f"{c.name} marker 0x{c.low_marker_at:04X}: expected 61, got {save[c.low_marker_at]:02x}")
        if save[c.high_marker_at] != HIGH_MARKER:
            out.append(f"{c.name} marker 0x{c.high_marker_at:04X}: expected 7f, got {save[c.high_marker_at]:02x}")
        count = save[_at(c, COUNT_IN_GAME_DATA)]
        if not 1 <= count <= 6:
            out.append(f"{c.name} party count {count}: expected 1..6")
    if bytes(save[VERSION_AT:VERSION_AT + 2]) != SAVE_VERSION:
        out.append(f"sSaveVersion: expected 000a, got {bytes(save[VERSION_AT:VERSION_AT + 2]).hex()}")
    if save[PHASE_AT] != 0:
        out.append(f"save phase 0x{PHASE_AT:04X}: expected 00, got {save[PHASE_AT]:02x}")
    return out


def _checksum_problems(save) -> list[str]:
    return [f"{c.name} checksum: stored {_stored_sum(save, c):04x}, region sum {_region_sum(save, c):04x}"
            for c in COPIES if _stored_sum(save, c) != _region_sum(save, c)]


def _precondition_problems(save) -> list[str]:
    out = []
    main, backup = (bytes(save[c.start:c.end]) for c in COPIES)
    if main != backup:
        diff = [i for i in range(len(main)) if main[i] != backup[i]]
        out.append(f"main and backup game data disagree at {len(diff)} bytes (first at region offset 0x{diff[0]:04X})")
    for c in COPIES:
        scene = save[_at(c, SCENE_IN_GAME_DATA)]
        if scene != SCENE_OLD:
            out.append(f"{c.name} wCherrygroveCitySceneID: expected 00, got {scene:02x} (scene already advanced)")
        pos = bytes(save[_at(c, MAP_IN_GAME_DATA):_at(c, MAP_IN_GAME_DATA) + 4])
        if pos != ROUTE29_POSITION:
            out.append(f"{c.name} map/position: expected {ROUTE29_POSITION.hex()} (Route 29 48,12), got {pos.hex()}")
        starter = save[_at(c, EVENT_FLAGS_IN_GAME_DATA + STARTER_BYTE_IN_FLAGS)] & STARTER_MASK
        if starter:
            out.append(f"{c.name} starter flag set (mask {starter:02x}): the trainer id would not be RIVAL0 3")
        if not save[_at(c, EVENT_FLAGS_IN_GAME_DATA + RIVAL_BYTE_IN_FLAGS)] & RIVAL_MASK:
            out.append(f"{c.name} EVENT_RIVAL_CHERRYGROVE_CITY clear: the rival object would already be visible")
    return out


def _check_source(save) -> None:
    problems = _layout_problems(save)
    if problems:
        raise RivalSourceError("; ".join(problems))
    problems = _checksum_problems(save)
    if problems:
        raise RivalSourceError("; ".join(problems))
    problems = _precondition_problems(save)
    if problems:
        raise RivalPreconditionError("; ".join(problems))


def _apply_edit(buf) -> None:
    """The one game change: the Cherrygrove scene byte in both copies."""
    for at in SCENE_OFFSETS:
        buf[at] = SCENE_NEW


def _reseal(buf) -> None:
    for c in COPIES:
        buf[c.checksum_at:c.checksum_at + 2] = _region_sum(buf, c).to_bytes(2, "little")


def _diff(a, b) -> list[int]:
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]


# ── the independent verifier (shares no offset or helper with the builder) ───

def verify_rival_scene(original, derived) -> list[str]:
    """Problems with `derived` as the Cherrygrove-scene derivative of `original` (empty list = ok).

    Allowlist, hand-written: the two scene bytes and the four checksum bytes. Both scene bytes must go 00 -> 01, both
    checksums must equal their region sums, the 22-byte footer and every other byte must be identical.
    """
    problems = []
    for label, image in (("original", original), ("derived", derived)):
        if len(image) != 32790:
            problems.append(f"{label}: size {len(image)} != 32790")
    if problems:
        return problems
    for label, image in (("original", original), ("derived", derived)):
        for name, (lo, hi, at) in (("main", (0x2008, 0x2B83, 0x2D0D)), ("backup", (0x1208, 0x1D83, 0x1F0D))):
            if int.from_bytes(image[at:at + 2], "little") != sum(image[lo:hi]) & 0xFFFF:
                problems.append(f"{label}: {name} checksum does not equal its region sum")
        for at, value in ((0x2007, 0x61), (0x1207, 0x61), (0x2D0F, 0x7F), (0x1F0F, 0x7F)):
            if image[at] != value:
                problems.append(f"{label}: marker 0x{at:04X} is {image[at]:02x}, expected {value:02x}")
    if problems:
        return problems
    allowed = {0x2582, 0x1782, 0x2D0D, 0x2D0E, 0x1F0D, 0x1F0E}
    differing = [i for i in range(32790) if original[i] != derived[i]]
    outside = [i for i in differing if i not in allowed]
    if outside:
        shown = ", ".join(f"0x{i:04X}" for i in outside[:12])
        problems.append(f"undeclared offsets differ ({len(outside)}): {shown}")
    for name, at in (("main", 0x2582), ("backup", 0x1782)):
        if original[at] != 0x00:
            problems.append(f"original {name} scene 0x{at:04X} is {original[at]:02x}, expected 00")
        if derived[at] != 0x01:
            problems.append(f"derived {name} scene 0x{at:04X} is {derived[at]:02x}, expected 01 (00 -> 01 is the only change)")
    if bytes(original[32768:]) != bytes(derived[32768:]):
        problems.append("RTC footer [0x8000,32790) changed")
    if bytes(derived[0x2008:0x2582]) != bytes(original[0x2008:0x2582]) or bytes(derived[0x1208:0x1782]) != bytes(original[0x1208:0x1782]):
        problems.append("game data before the scene byte changed")
    return problems


# ── the builder ──────────────────────────────────────────────────────────────

def derive_rival_scene(save, *, pinned: bool = True) -> tuple[bytes, dict]:
    """Return (new_save, disclosure): `save` with the Cherrygrove scene advanced 00 -> 01 and both checksums re-sealed.

    `pinned=True` (the default; the CLI never uses anything else) refuses any input whose SHA-256 is not the pinned fixture's.
    `pinned=False` exists for the unit tests' synthetic images and marks the disclosure so.
    """
    if not isinstance(save, (bytes, bytearray)):
        raise RivalSourceError(f"input: expected bytes, got {type(save).__name__}")
    original = bytes(save)
    if pinned and sha256(original) != PINNED_SRC_SHA256:
        raise RivalSourceError(f"input sha256 {sha256(original)} is not the pinned source {PINNED_SRC_SHA256}")
    _check_source(original)
    buf = bytearray(original)
    _apply_edit(buf)
    _reseal(buf)
    out = bytes(buf)
    problems = verify_rival_scene(original, out)
    differing = _diff(original, out)
    if pinned:
        if differing != [0x1782, 0x1F0D, 0x2582, 0x2D0D]:
            problems.append(f"pinned input must differ at exactly 0x1782,0x1F0D,0x2582,0x2D0D, got {[hex(i) for i in differing]}")
        if sha256(out) != EXPECTED_OUT_SHA256:
            problems.append(f"output sha256 {sha256(out)} != expected {EXPECTED_OUT_SHA256}")
    if problems:
        raise RivalVerifyError("; ".join(problems))
    fields = [{"field": "cherrygrove_scene", "copy": c.name, "offset": at, "offset_hex": f"0x{at:04X}",
               "old_hex": f"{original[at]:02x}", "new_hex": f"{out[at]:02x}",
               "symbol": "wCherrygroveCitySceneID", "symbol_addr": "01:d9f2"}
              for c, at in zip(COPIES, SCENE_OFFSETS, strict=True)]
    fields += [{"field": "checksum", "copy": c.name, "offset": c.checksum_at, "offset_hex": f"0x{c.checksum_at:04X}",
                "old_hex": original[c.checksum_at:c.checksum_at + 2].hex(),
                "new_hex": out[c.checksum_at:c.checksum_at + 2].hex(),
                "region": [f"0x{c.start:04X}", f"0x{c.end:04X}"]} for c in COPIES]
    disclosure = {
        "revision": REVISION, "synth": True, "statement": STATEMENT,
        "pinned_input": pinned, "input_sha256": sha256(original), "output_sha256": sha256(out),
        "source_commit": SOURCE_COMMIT, "source_plan": "docs/polished/RIVAL_STAGING.md section 2",
        "changed_fields": fields,
        "differing_bytes": len(differing), "differing_offsets": differing,
        "footer": {"offset": CART_SIZE, "length": FOOTER_LEN, "preserved": True, "sha256": sha256(original[CART_SIZE:])},
        "preserved_preconditions": {
            "map_group_map_y_x": ROUTE29_POSITION.hex(), "starter_flags_clear": True,
            "rival_object_bit_set": True, "party_count": original[_at(MAIN, COUNT_IN_GAME_DATA)],
            "copies_identical": True},
        "expected_native_encounter": "RIVAL0 trainer 3 (RATTATA 4, TOTODILE 5) at Cherrygrove (33,7) scene 1",
        "native_acceptance": "UNVERIFIED",
    }
    return out, disclosure


# ── source location + CLI ────────────────────────────────────────────────────

def locate_source(explicit=None):
    """The explicit path, else the first existing candidate that matches the pin, else the first existing one, else None."""
    if explicit is not None:
        return Path(explicit)
    existing = [p for p in SOURCE_CANDIDATES if p.exists()]
    for path in existing:
        if sha256(path.read_bytes()) == PINNED_SRC_SHA256:
            return path
    return existing[0] if existing else None


def _protected(out: Path) -> bool:
    for root in PROTECTED_DIRS:
        try:
            out.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", type=Path, help="the pinned polished_overlay_warp.SaveRAM (default: the lane copies)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out (never the source)")
    args = ap.parse_args(argv)
    src = locate_source(args.src)
    if src is None or not src.is_file():
        print(f"refused: no source fixture found (tried {[str(p) for p in SOURCE_CANDIDATES]})", file=sys.stderr)
        return 2
    src, out = src.resolve(), args.out.resolve()
    if src == out or (out.exists() and out.samefile(src)):
        print(f"refused: --out is the source file {src}", file=sys.stderr)
        return 2
    if _protected(out):
        print(f"refused: {out} is inside the committed fixtures", file=sys.stderr)
        return 2
    if out.exists() and not args.force:
        print(f"refused: {out} exists (pass --force to overwrite)", file=sys.stderr)
        return 2
    try:
        derived, disclosure = derive_rival_scene(src.read_bytes())
    except RivalVerifyError as err:
        print(f"refused: {type(err).__name__}: {err}", file=sys.stderr)
        return 4
    except RivalError as err:
        print(f"refused: {type(err).__name__}: {err}", file=sys.stderr)
        return 3
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(derived)
    print(json.dumps(disclosure, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
