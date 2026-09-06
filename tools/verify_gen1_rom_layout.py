#!/usr/bin/env python3
"""Verify every flat Gen 1 ROM offset this project depends on, against the real dumps.

WHY A SECOND VERIFIER. `tools/verify_profile_addresses.py` checks WRAM/SRAM symbols
against the pret symbol tables. It cannot check anything here: a flat file offset is not a
symbol, and the patch manifest's expected bytes are not addresses at all. Those two kinds
of claim fail in different ways and need different evidence, so they get different tools —
and every address this project introduces belongs in one of them, with no WARN and no SKIP
path that would let a missing check read as a passing one.

What is checked, all against the actual cartridge bytes:

  * every scanner offset resolves through `data/pret_rom_syms.json`, decoded as
    `bank << 16 | addr` (NOT a flat offset — decoding it wrongly is a trap this project
    has already fallen into once);
  * the scanners actually parse what is there: wild tables, all three rods, base stats
    for all 151 species, the evolution graph, the index-to-dex map;
  * every span in the companion-patch manifest holds exactly the bytes it expects to
    displace, and none of them touches the protected cartridge header;
  * the ROM0 free runs the patch reserves are still free.

Exit code is 0 only if every check passed on every ROM that is present. A ROM that is
absent is reported and is NOT counted as a pass.

    python tools/verify_gen1_rom_layout.py
    python tools/verify_gen1_rom_layout.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "patch", "gen1", "tools"))

ROMS = {
    "red": "patch/build/gen1_red.gb",
    "blue": "patch/build/gen1_blue.gb",
    "yellow": "patch/build/gen1_yellow.gbc",
}

# The companion patch exists for Red and Blue only; Yellow has no free WRAM for a mailbox.
PATCHABLE = ("red", "blue")

CLEAN_SHA1 = {
    "red": "ea9bcae617fdf159b045185467ae58b2e4a48b9a",
    "blue": "d7037c83e1ae5b39bde3c30787637ba1d4c48ce2",
    "yellow": "cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1",
}


def _rows_for(title: str, rom: bytes) -> list[tuple[str, bool, str]]:
    """(check, ok, detail) for one ROM."""
    from server.adapters.gen1_rom_scan import (
        RomScanError,
        _syms_for,
        evolution_graph,
        identify,
        scan_base_stats,
        scan_fishing,
        scan_pokedex_order,
        scan_wild,
        sym_to_offset,
    )
    rows: list[tuple[str, bool, str]] = []

    def check(name, fn):
        try:
            rows.append((name, True, fn()))
        except Exception as exc:                       # noqa: BLE001
            rows.append((name, False, f"{type(exc).__name__}: {exc}"))

    def _identity():
        value = identify(rom)
        if value["variant"] != title or value["sha1"] != CLEAN_SHA1[title]:
            raise RomScanError(f"expected canonical {title} {CLEAN_SHA1[title]}, got "
                               f"{value['variant']} {value['sha1']}")
        return f"{title} SHA-1={value['sha1']}"
    check("exact supported canonical ROM", _identity)

    def _symbols():
        _ident, syms = _syms_for(rom)
        wanted = ["WildDataPointers", "BaseStats", "EvosMovesPointerTable", "PokedexOrder"]
        out = []
        for name in wanted:
            if name not in syms:
                raise RomScanError(f"{name} missing from the symbol table")
            out.append(f"{name}={sym_to_offset(syms[name]):#07x}")
        return "  ".join(out)
    check("scanner symbols resolve (bank<<16|addr decoded)", _symbols)

    def _wild():
        w = scan_wild(rom)
        if len(w) < 50:
            raise RomScanError(f"only {len(w)} encounter maps")
        return f"{len(w)} maps"
    check("wild tables parse", _wild)

    def _fish():
        f = scan_fishing(rom)
        for rod in ("old_rod", "good_rod", "super_rod"):
            if rod not in f:
                raise RomScanError(f"{rod} missing")
        return "old/good/super all present"
    check("all three fishing rods parse", _fish)

    def _stats():
        st = scan_base_stats(rom)
        missing = sorted(set(range(1, 152)) - set(st))
        if missing:
            raise RomScanError(f"missing dex numbers {missing}")
        return "151 species incl. Mew"
    check("base stats cover every species", _stats)

    def _evos():
        g = evolution_graph(rom)
        edges = sum(len(v) for v in g.values())
        if edges != 72:
            raise RomScanError(f"{edges} evolution edges, expected 72")
        return "72 edges over 190 indexes"
    check("evolution graph parses", _evos)

    def _dex():
        order = scan_pokedex_order(rom)
        live = [x for x in order if x]
        if len(live) != 151:
            raise RomScanError(f"{len(live)} live dex entries")
        return "151 entries"
    check("index-to-dex map parses", _dex)

    from tools.gen1_patch_validation import verify_future_hook_anchors
    check("canonical service/trade prerequisites (not feature proof)",
          lambda: verify_future_hook_anchors(title, rom, _syms_for(rom)[1]))

    if title in PATCHABLE:
        import manifest

        from tools.gen1_patch_validation import verify_anchors, verify_assembly_references

        check("complete manifest geometry, source anchors and call banks",
              lambda: verify_anchors(rom, _syms_for(rom)[1], manifest))

        def _assembly():
            source = Path(_REPO, "patch/gen1/src/slink.asm").read_text(encoding="utf-8")
            ram = json.loads(Path(_REPO, "data/pret_syms.json").read_text(encoding="utf-8"))
            return verify_assembly_references(source, _syms_for(rom)[1], ram["pokered"])
        check("all external assembly addresses/banks resolve", _assembly)

        def _spans():
            lo, hi = manifest.PROTECTED_RANGE
            bad = []
            for off, original, new, why in manifest.MENU_PATCHES:
                if not (off + len(new) <= lo or off > hi):
                    bad.append(f"{off:#06x} overlaps the protected header ({why})")
                found = rom[off:off + len(original)]
                if found != original:
                    bad.append(f"{off:#06x} holds {found.hex()}, expected "
                               f"{original.hex()} ({why})")
            if bad:
                raise RomScanError("; ".join(bad))
            return f"{len(manifest.MENU_PATCHES)} spans, header untouched"
        check("companion-patch spans hold their expected bytes", _spans)

        def _hook():
            site = rom[manifest.HOOK_SITE:manifest.HOOK_SITE + len(manifest.HOOK_ORIGINAL)]
            if site != manifest.HOOK_ORIGINAL:
                raise RomScanError(f"{manifest.HOOK_SITE:#06x} holds {site.hex()}")
            return f"{manifest.HOOK_SITE:#06x} = farcall TrackPlayTime"
        check("the VBlank hook site is intact", _hook)

        def _bank():
            base = manifest.INJECT_OFFSET
            if any(rom[base:base + manifest.BANK_SIZE]):
                raise RomScanError(f"bank {manifest.HOOK_BANK:#x} is not empty")
            return f"bank {manifest.HOOK_BANK:#x} is {manifest.BANK_SIZE} bytes of zero"
        check("the target bank is free", _bank)

        def _free_runs():
            # The two ROM0 runs the patch reserves. 0x00BE..0x00FF is 66 usable bytes --
            # the zero run continues to 0x0100, but that byte is the cartridge entrypoint.
            for start, end, what in ((0x00BE, 0x0100, "ROM0 stub run"),
                                     (0x3FA6, 0x4000, "ROM0 trampoline run")):
                used = [i for i in range(start, end) if rom[i]]
                if used:
                    raise RomScanError(f"{what} {start:#06x}-{end:#06x} is not free "
                                       f"(first used byte {used[0]:#06x})")
            if rom[0x0100:0x0104] != bytes([0x00, 0xC3, 0x50, 0x01]):
                raise RomScanError("0x0100 is not the expected `nop; jp $0150` entrypoint")
            return "0x00BE-0x00FF and 0x3FA6-0x3FFF free; entrypoint intact"
        check("the reserved ROM0 runs are still free", _free_runs)

    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report: dict[str, list] = {}
    ok_total = fail_total = missing = 0

    for title, rel in ROMS.items():
        path = os.path.join(_REPO, rel)
        if not os.path.exists(path):
            report[title] = [("ROM present", False, f"{rel} not found")]
            missing += 1
            continue
        with open(path, "rb") as f:
            rows = _rows_for(title, f.read())
        report[title] = rows
        ok_total += sum(1 for _n, ok, _d in rows if ok)
        fail_total += sum(1 for _n, ok, _d in rows if not ok)

    import manifest

    from tools.gen1_patch_validation import verify_generated_payload
    try:
        detail = verify_generated_payload(manifest)
        report["generated_payload"] = [("fresh assembly matches published bytes", True, detail)]
        ok_total += 1
    except Exception as exc:
        report["generated_payload"] = [("fresh assembly matches published bytes", False,
                                        f"{type(exc).__name__}: {exc}")]
        fail_total += 1

    if args.json:
        print(json.dumps({t: [{"check": n, "ok": o, "detail": d} for n, o, d in rows]
                          for t, rows in report.items()}, indent=2))
    else:
        for title, rows in report.items():
            print(f"\n── {title} " + "─" * (60 - len(title)))
            for name, ok, detail in rows:
                print(f"  [{'ok' if ok else 'FAIL'}] {name}  — {detail}")
        print(f"\nSummary: {ok_total} ok / {fail_total} fail / {missing} ROM(s) missing")

    # A missing ROM is not a pass. It is the difference between "verified" and "not run",
    # and the release gate needs to be able to tell them apart.
    return 0 if (fail_total == 0 and missing == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
