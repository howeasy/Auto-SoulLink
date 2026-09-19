"""tools/upr_lossless_check.py — the C1 lossless baseline (docs/purergb/PLAN.md §6 M5).

For each pure ROM: detect the RomEntry the fork picks, then run the fork's CLI exactly as
server/upr_pipeline.randomize() does with EVERY setting off (no tweaks either) and require
sha1(output) == sha1(input). Exit 1 on any difference, printing the first differing bytes.

    python tools/upr_lossless_check.py [--jar .cache/slink-upr/PokeRandoZX.jar] [--roms .cache/purergb]
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from server.upr_settings import build_categories  # noqa: E402
from tools._upr_probe import REPO, cli, probe, sha1  # noqa: E402

TITLES = ("red", "blue", "green")


def first_diffs(a: bytes, b: bytes, limit: int = 8) -> list[str]:
    out = []
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            out.append(f"0x{i:06X}: {x:02X} -> {y:02X}")
            if len(out) >= limit:
                break
    if len(a) != len(b):
        out.append(f"length {len(a)} -> {len(b)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jar", default=str(REPO / ".cache" / "slink-upr" / "PokeRandoZX.jar"))
    ap.add_argument("--roms", default=str(REPO / ".cache" / "purergb"))
    args = ap.parse_args()
    jar, roms = pathlib.Path(args.jar), pathlib.Path(args.roms)
    print(f"jar {jar} sha1={sha1(jar)}")
    print("version:", probe(jar, "version").stdout.strip())
    ok = True
    with tempfile.TemporaryDirectory(prefix="upr-lossless-") as tmp:
        tmp = pathlib.Path(tmp)
        settings = tmp / "off.rnqs"
        settings.write_bytes(build_categories(set(), fastest_text=False))
        for t in TITLES:
            src = roms / f"poke{t}.gbc"
            entry = probe(jar, "entry", str(src)).stdout.strip()
            out = tmp / f"{t}_out.gbc"
            proc = cli(jar, settings, src, out)
            if proc.returncode != 0 or not out.exists():
                print(f"[{t}] entry={entry} CLI FAILED rc={proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}")
                ok = False
                continue
            a, b = src.read_bytes(), out.read_bytes()
            same = a == b
            ok &= same
            print(f"[{t}] entry={entry} in={sha1(src)} out={sha1(out)} {'IDENTICAL' if same else 'DIFFERS'}")
            if not same:
                for line in first_diffs(a, b):
                    print("    " + line)
                print(f"    {sum(1 for x, y in zip(a, b, strict=False) if x != y)} bytes differ")
    print("LOSSLESS OK" if ok else "LOSSLESS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
