"""Evidence for the radical_red values in lua/tests/gen3_title_syms.lua (G5-RR-BATTERY-2).

Radical Red has no pret .sym. A harness symbol is carried over from FireRed only when the RR
ROM keeps FR's own uses of it: every FR literal-pool word holding the symbol's value (a code
site that loads the address) is still there, at the same ROM address, in the RR artifact.
Code symbols also report how much of the FR function body survives byte-for-byte (a CFRU
detour stub still leaves the task pointer the engine stores).

    python tools/research/rr_harness_syms.py            # the table in the research note
    python tools/research/rr_harness_syms.py --check    # exit 1 if any cited entry fails

Inputs are located in the repo root or any parent: the FR 1.0 dump (sha1 41cb23d8), the clean
RR 4.1 dump (964f951a) and patch/build/slink_RR.gba, the shipped companion (ea5352f8).
"""
from __future__ import annotations

import hashlib
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FR_SHA1 = "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"
RR_ARTIFACTS = {"964f951a0fdaf209e4ea1344883ef0d557bb3a80": "Pokemon - Radical Red.gba",
                "ea5352f8a3b9073f8ae20870ad12857925d442cd": "patch/build/slink_RR.gba"}
NOTE = "docs/gen3/research/rr_harness_syms_2026-09-24.md"


def find(rel):
    for base in (REPO, *REPO.parents):
        if (base / rel).is_file():
            return base / rel
    return None


def load(rel, sha):
    path = find(rel)
    if path is None:
        return None
    rom = path.read_bytes()
    if hashlib.sha1(rom).hexdigest() != sha:
        raise SystemExit(f"{path} is not {sha}")
    return rom


def refs(rom, value):
    lit, out, i = struct.pack("<I", value), [], rom.find(struct.pack("<I", value))
    while i >= 0:
        out.append(0x08000000 + i)
        i = rom.find(lit, i + 1)
    return out


def sym_sizes():
    out = {}
    for line in (REPO / "data/gen3/pret/pokefirered.sym").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([0-9a-f]+) \w ([0-9a-f]+) (\S+)", line)
        if m:
            out.setdefault(int(m.group(1), 16), int(m.group(2), 16))
    return out


def cited_entries():
    """(name, symbol, firered value, thumb) for every title_syms entry citing the note."""
    from lupa import LuaRuntime

    mod = LuaRuntime().execute(f'return dofile("{(REPO / "lua/tests/gen3_title_syms.lua").as_posix()}")')
    out = []
    for name, e in mod.entries.items():
        if e["radical_red"] is not None and NOTE in str(e["rr_source"] or ""):
            out.append((name, e["symbol"], e["firered"], bool(e["thumb"]), e["radical_red"]))
    return sorted(out)


def evidence(fr, rr, value, thumb, sizes):
    """{fr_refs, rr_refs, kept, body, size} for one symbol value against one RR artifact."""
    fr_refs, rr_refs = refs(fr, value), refs(rr, value)
    row = {"fr_refs": len(fr_refs), "rr_refs": len(rr_refs),
           "kept": all(struct.unpack_from("<I", rr, a - 0x08000000)[0] == value for a in fr_refs)}
    base = value - (1 if thumb else 0)
    if 0x08000000 <= base < 0x0A000000 and sizes.get(base):
        n, o, k = sizes[base], base - 0x08000000, 0
        while k < n and fr[o + k] == rr[o + k]:
            k += 1
        row["body"], row["size"] = k, n
    return row


def main(argv):
    fr = load("Pokemon - FireRed Version (USA).gba", FR_SHA1)
    if fr is None:
        raise SystemExit("the FR dump is not in the repo root or a parent")
    sizes, bad = sym_sizes(), []
    for sha, rel in RR_ARTIFACTS.items():
        rr = load(rel, sha)
        if rr is None:
            print(f"# {sha[:8]} ({rel}) not present")
            continue
        print(f"# RR artifact {sha} ({rel}); FR {FR_SHA1}")
        print("| entry | symbol | value | FR refs | RR refs | all FR sites kept | FR body kept |")
        print("|---|---|---|---|---|---|---|")
        for name, symbol, value, thumb, rr_value in cited_entries():
            ev = evidence(fr, rr, value, thumb, sizes)
            body = f"{ev['body']}/{ev['size']}" if "size" in ev else "-"
            print(f"| {name} | {symbol} | 0x{value:08X} | {ev['fr_refs']} | {ev['rr_refs']} | "
                  f"{'yes' if ev['kept'] else 'NO'} | {body} |")
            if not ev["kept"] or ev["fr_refs"] == 0 or rr_value != value:
                bad.append((sha[:8], name))
        print()
    if "--check" in argv and bad:
        print("FAIL", bad)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
