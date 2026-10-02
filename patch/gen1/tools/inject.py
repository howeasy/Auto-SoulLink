#!/usr/bin/env python3
"""Apply the Gen 1 companion patch to a ROM whose hash cannot be known in advance.

WHY THIS EXISTS ALONGSIDE build.py. A UPS patch is a delta against ONE exact source and
carries that source's CRC32, so it cannot patch a randomized cartridge: every seed is a
different file. `build.py` has the opposite problem -- it is the deterministic build tool
and is gated on the two pinned clean SHA-1s, which is correct and must stay that way.

So this is a third thing: the same manifest, applied structurally. Instead of asking "is
this the dump I expect?", it asks "does every byte I am about to overwrite hold exactly
what the manifest says it should?" -- twelve spans, the eight-byte hook site, an empty
target bank and an untouched cartridge header. On a randomized ROM all of those are still
true, because UPR does not touch the menu code, the VBlank hook or bank $3F.

Both paths read `manifest.py`. Neither owns it, so they cannot drift.

NOTHING IS WRITTEN UNTIL EVERYTHING IS CHECKED. A manifest that is half-applicable leaves
the input untouched and says why, because a half-patched cartridge is worse than an
unpatched one: it boots, and then misbehaves in a way nobody can attribute.

CLI:
    python inject.py <in.gb> <out.gb>
    python inject.py --check <in.gb>        # report only, write nothing
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from manifest import (  # noqa: E402
    BANK_SIZE,
    HOOK_BANK,
    HOOK_ORIGINAL,
    HOOK_SITE,
    HOOK_TARGET,
    INJECT_OFFSET,
    MENU_PATCHES,
    PROTECTED_RANGE,
)
from title_screen import DEFAULT_VERSION, FREE_FROM, title_spans  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
PAYLOAD_FILE = os.path.normpath(os.path.join(_HERE, "..", "dist", "slink_bank3f.bin"))

ROM_SIZE = 1024 * 1024

# `ld a, "S" / ld [SLINK_MAILBOX], a` -- the first of the four beacon writers. Searched for
# in the payload rather than hardcoded as an offset, so it survives the module being
# re-laid-out by a future build.
_BEACON_WRITER = bytes([0x3E, 0x53, 0xEA, 0xE2, 0xDE])
# `ld [SLINK_MAILBOX + 4], a` -- the ABI byte write, which follows the beacon writers.
_ABI_STORE = bytes([0xEA, 0xE6, 0xDE])


class InjectError(Exception):
    """The ROM cannot be patched. Raised BEFORE anything is written, always."""


def load_payload() -> bytes:
    """The assembled bank-$3F module, published by build.py."""
    if not os.path.exists(PAYLOAD_FILE):
        raise InjectError(
            f"{PAYLOAD_FILE} is missing — run patch/gen1/tools/build.py once to "
            f"assemble and publish it")
    with open(PAYLOAD_FILE, "rb") as f:
        return f.read()


def _abi_in_bank(bank: bytes) -> int | None:
    """The ABI version an already-injected module advertises, if we can find it."""
    start = bank.find(_BEACON_WRITER)
    if start < 0:
        return None
    for i in range(start, min(start + 64, len(bank) - 5)):
        if bank[i] == 0x3E and bank[i + 2:i + 5] == _ABI_STORE:
            return bank[i + 1]
    return None


def describe(rom: bytes) -> dict:
    """What state is this ROM in? Never raises; the caller decides what to do."""
    out = {
        "size_ok": len(rom) == ROM_SIZE,
        "bank_empty": False,
        "hook_clean": False,
        "hook_ours": False,
        "spans_ok": 0,
        "spans_written": 0,
        "spans_total": len(MENU_PATCHES),
        "already": None,
    }
    if not out["size_ok"]:
        return out

    bank = rom[INJECT_OFFSET:INJECT_OFFSET + BANK_SIZE]
    out["bank_empty"] = not any(bank)
    site = rom[HOOK_SITE:HOOK_SITE + len(HOOK_ORIGINAL)]
    out["hook_clean"] = site == HOOK_ORIGINAL
    out["hook_ours"] = (site[1] == HOOK_BANK
                        and (site[3] | (site[4] << 8)) == HOOK_TARGET)
    out["spans_ok"] = sum(1 for off, orig, _new, _why in MENU_PATCHES
                          if rom[off:off + len(orig)] == orig)
    out["spans_written"] = sum(1 for off, _orig, new, _why in MENU_PATCHES
                               if rom[off:off + len(new)] == new)

    if out["hook_ours"] and not out["bank_empty"]:
        try:
            payload = load_payload()
        except InjectError:
            payload = b""
        out["already"] = {
            "abi": _abi_in_bank(bank),
            "identical": bool(payload) and bank[:len(payload)] == payload,
        }
    return out


def inject(rom: bytes, payload: bytes | None = None, version: str = DEFAULT_VERSION) -> bytes:
    """Return the patched ROM, or raise InjectError having written nothing."""
    payload = payload if payload is not None else load_payload()
    state = describe(rom)

    if not state["size_ok"]:
        raise InjectError(f"expected a {ROM_SIZE}-byte Game Boy ROM, got {len(rom)} bytes")
    if len(payload) > FREE_FROM - INJECT_OFFSET:
        raise InjectError("the payload runs into the title band at the end of bank $3F")

    # ── Already patched? Say which, and refuse the ones we cannot safely redo. ─────────
    # The reapply matrix, stated rather than discovered at runtime: an exact match is a
    # no-op, any other SLink patch is a refusal. Re-patching over ABI 2 cannot work,
    # because the spans it displaced no longer hold the bytes the manifest expects -- the
    # structural check would fail anyway, and this says why instead of listing twelve
    # mismatches.
    if state["already"] is not None:
        info = state["already"]
        if info["identical"]:
            raise InjectError(
                "this ROM already carries exactly this companion patch — nothing to do")
        raise InjectError(
            f"this ROM already carries a DIFFERENT SLink patch (ABI {info['abi']}). "
            f"Start again from the unpatched randomized ROM: the spans that patch "
            f"displaced are no longer the bytes this one expects to find.")

    # ── Structural preconditions. ALL of them, before ANY write. ──────────────────────
    problems: list[str] = []
    if not state["bank_empty"]:
        problems.append(
            f"bank {HOOK_BANK:#x} is not empty — this ROM uses the space the module needs")
    if not state["hook_clean"]:
        site = rom[HOOK_SITE:HOOK_SITE + len(HOOK_ORIGINAL)].hex()
        problems.append(
            f"the VBlank hook site {HOOK_SITE:#06x} holds {site}, expected "
            f"{HOOK_ORIGINAL.hex()}")
    lo, hi = PROTECTED_RANGE
    try:
        spans = MENU_PATCHES + title_spans(rom, version)
    except ValueError as exc:
        raise InjectError(f"refusing to patch; nothing was written: {exc}") from None
    for off, original, new, why in spans:
        if not (off + len(new) <= lo or off > hi):
            problems.append(f"{off:#06x} ({why}) overlaps the protected cartridge header")
        found = rom[off:off + len(original)]
        if found != original:
            problems.append(
                f"{off:#06x} holds {found.hex()}, expected {original.hex()} ({why})")
    if problems:
        raise InjectError("refusing to patch; nothing was written:\n  - "
                          + "\n  - ".join(problems))

    # ── Write ─────────────────────────────────────────────────────────────────────────
    data = bytearray(rom)
    data[INJECT_OFFSET:INJECT_OFFSET + len(payload)] = payload
    for off, _original, new, _why in spans:
        data[off:off + len(new)] = new
    data[HOOK_SITE + 1] = HOOK_BANK
    data[HOOK_SITE + 3] = HOOK_TARGET & 0xFF
    data[HOOK_SITE + 4] = HOOK_TARGET >> 8
    out = bytes(data)

    # ── Read back. The header and the size are the two things a bad patch destroys ────
    # invisibly: a cartridge with a broken header does not boot, and one that changed
    # size is not a Game Boy ROM at all.
    if out[lo:hi + 1] != rom[lo:hi + 1]:
        raise InjectError("internal error: the cartridge header changed")
    if len(out) != len(rom):
        raise InjectError("internal error: the ROM changed size")
    for off, _original, new, why in spans:
        if out[off:off + len(new)] != new:
            raise InjectError(f"internal error: {why} did not land at {off:#06x}")
    if out[INJECT_OFFSET:INJECT_OFFSET + len(payload)] != payload:
        raise InjectError("internal error: the module did not land in bank $3F")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    with open(args.rom, "rb") as f:
        rom = f.read()

    if args.check:
        st = describe(rom)
        print(f"size ok        : {st['size_ok']}")
        print(f"bank $3F empty : {st['bank_empty']}")
        print(f"hook unpatched : {st['hook_clean']}")
        print(f"menu spans ok  : {st['spans_ok']}/{st['spans_total']}")
        print(f"already patched: {st['already']}")
        return 0

    if not args.out:
        ap.error("an output path is required unless --check is given")
    try:
        out = inject(rom)
    except InjectError as exc:
        print(f"[gen1-inject] {exc}", file=sys.stderr)
        return 1
    with open(args.out, "wb") as f:
        f.write(out)
    print(f"[gen1-inject] {args.out}  sha1={hashlib.sha1(out).hexdigest()}  "
          f"md5={hashlib.md5(out).hexdigest()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
