#!/usr/bin/env python3
"""Capture the RR4.1_Custom Battle Calc delta as a committed UPS the build re-applies.

The Battle Calc is the **in-battle damage / type-effectiveness calculator** bundled into
the SLink companion patch. `RR4.1_Custom.ups` patches *vanilla FireRed* -> a customized
Radical Red 4.1 ROM that is the **same RR build SLink targets** (base RR md5 8529f3a4...)
plus this one small, self-contained battle code-mod (~3.4 KB / 13 regions): it detours
`BattlePutTextOnWindow`, reads `gMoveSelectionCursor`, and renders a colored damage number
from new functions at ROM 0x09360000 (see ADDRESSES.md).

This tool re-expresses the Battle Calc as a **base-RR -> RR4.1_Custom** delta so `build.py`
can fold it into the emitted SLink patch (applied to a plain base RR, the result has the
Battle Calc *and* the companion patch). UPS is mandatory here: the Battle Calc code lives
at file offset ~0x1360000 (> 16 MB), which IPS's 24-bit offsets cannot reach.

Pipeline (all in memory, no scratch ROM written; round-trip self-checked like make_ups):
  1. apply RR4.1_Custom.ups onto vanilla FireRed     -> RR4.1_Custom image (CRC-gated)
  2. diff base RR vs that image                       -> Battle Calc UPS (ups_create)
  3. re-apply Battle Calc UPS onto base RR, assert md5 == RR4.1_Custom  (the trust gate)

Usage:
    python patch/tools/make_battle_calc_patch.py \
        [--fr <FireRed.gba>] [--custom-ups <RR4.1_Custom.ups>] \
        [--base-rr <Radical Red.gba>] [--out patch/src/rr41_battle_calc.ups]
"""
import argparse
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATCH = os.path.dirname(HERE)
SRC = os.path.join(PATCH, "src")

sys.path.insert(0, HERE)
import make_ups  # noqa: E402

# Machine-specific defaults (mirror build.py's DEFAULT_RR convention); override via flags.
DEFAULT_FR = r"D:/Downloads/Pokemon - FireRed Version (USA).gba"
DEFAULT_CUSTOM_UPS = r"D:/Downloads/RR4.1_Custom.ups"
DEFAULT_BASE_RR = r"E:/Google Drive/SLink/Pokemon - Radical Red.gba"
DEFAULT_OUT = os.path.join(SRC, "rr41_battle_calc.ups")

# Sanity expectations for the known RR4.1_Custom build (informational, not hard-gated so a
# different customizer build can be re-captured by re-running with new inputs).
EXPECT_BASE_RR_MD5 = "8529f3a45d32bce4da637976fcf269d4"
EXPECT_CUSTOM_MD5 = "b50b3a5136314b7f7e4fb9043a2811ba"


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def _md5(b):
    return hashlib.md5(b).hexdigest()


def _regions(a: bytes, b: bytes, gap: int = 64):
    """Cluster differing offsets into [start,end] runs (merging gaps <= `gap`)."""
    runs = []
    n = max(len(a), len(b))
    for o in range(n):
        ab = a[o] if o < len(a) else 0
        bb = b[o] if o < len(b) else 0
        if ab == bb:
            continue
        if runs and o - runs[-1][1] <= gap:
            runs[-1][1] = o
        else:
            runs.append([o, o])
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fr", default=DEFAULT_FR, help="vanilla FireRed USA .gba (UPS source)")
    ap.add_argument("--custom-ups", default=DEFAULT_CUSTOM_UPS, help="RR4.1_Custom.ups")
    ap.add_argument("--base-rr", default=DEFAULT_BASE_RR, help="clean Radical Red .gba (SLink base)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output Battle Calc UPS path")
    args = ap.parse_args()

    for label, p in (("FireRed", args.fr), ("RR4.1_Custom.ups", args.custom_ups),
                     ("base RR", args.base_rr)):
        if not os.path.exists(p):
            sys.exit(f"missing {label}: {p}")

    print("[1/3] reconstruct RR4.1_Custom from FireRed + RR4.1_Custom.ups")
    fr = _read(args.fr)
    custom = make_ups.ups_apply(fr, _read(args.custom_ups))  # CRC-gates FR source + custom target
    print(f"      RR4.1_Custom md5 {_md5(custom)}")
    if _md5(custom) != EXPECT_CUSTOM_MD5:
        print(f"      note: differs from the known build {EXPECT_CUSTOM_MD5} (re-capturing a new custom build)")

    print("[2/3] diff base RR -> RR4.1_Custom")
    base = _read(args.base_rr)
    base_md5 = _md5(base)
    print(f"      base RR md5 {base_md5}")
    if base_md5 != EXPECT_BASE_RR_MD5:
        sys.exit(f"base RR md5 mismatch (expected {EXPECT_BASE_RR_MD5}); wrong base ROM")
    if len(base) != len(custom):
        sys.exit(f"size mismatch base={len(base)} custom={len(custom)} — not the same RR build")
    regions = _regions(base, custom)
    diff_bytes = sum(1 for x, y in zip(base, custom, strict=True) if x != y)
    print(f"      delta: {diff_bytes} bytes in {len(regions)} regions")
    for a, b in regions:
        print(f"        ROM 0x{0x08000000 + a:08X}..0x{0x08000000 + b:08X}  ({b - a + 1} B)")

    print("[3/3] emit + round-trip verify Battle Calc UPS")
    ups = make_ups.ups_create(base, custom)
    rt = make_ups.ups_apply(base, ups)
    assert _md5(rt) == _md5(custom), "Battle Calc UPS round-trip mismatch!"
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(ups)
    print(f"      {os.path.relpath(args.out, PATCH)} ({len(ups)} B) round-trip OK "
          f"(base {base_md5} -> custom {_md5(custom)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
