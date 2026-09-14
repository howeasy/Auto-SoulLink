#!/usr/bin/env python3
"""Pin an engine execution site into data/games/gen1_rby/engine_signals.json.

A site is a pret symbol (locals allowed: `AddItemToInventory_.done`) plus an optional
instruction offset; the tool resolves it per title from the committed .sym files, reads the
expected bytes out of the clean ROM dumps in patch/build/, and writes the entry under every
title's `sites`. tests/unit/test_gen1_engine_sites.py (F-2) then guards it forever.

    python tools/pin_gen1_site.py add_party_mon AddPartyMon
    python tools/pin_gen1_site.py capture_box   SendNewMonToBox --len 8
    python tools/pin_gen1_site.py map_load      LoadMapHeader --capture-offset 3

--dry-run prints the entries without touching the JSON.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from tools.gen_gen1_profile import TITLES, flat, parse_sym  # noqa: E402

SITES = REPO / "data" / "games" / "gen1_rby" / "engine_signals.json"
DUMPS = {"red": "gen1_red.gb", "blue": "gen1_blue.gb", "yellow": "gen1_yellow.gbc"}


def pin(kind: str, symbol: str, *, length: int, capture_offset: int, yellow_symbol: str | None) -> dict:
    out = {}
    for title, (_repo, sym_name, _rom_key) in TITLES.items():
        syms = parse_sym(REPO / "data" / "pret" / sym_name)
        name = yellow_symbol if (title == "yellow" and yellow_symbol) else symbol
        if name not in syms:
            sys.exit(f"{title}: symbol {name!r} not in {sym_name}")
        bank, addr = syms[name]
        rom_offset = flat(bank, addr)
        rom = (REPO / "patch" / "build" / DUMPS[title]).read_bytes()
        out[title] = {
            "symbol": name,  # the offset lives in capture_offset, as the RC entries do (SaveMenu.save + 3)
            "bank": bank, "address": addr, "rom_offset": rom_offset,
            "capture_offset": capture_offset,
            "expected_hex": rom[rom_offset:rom_offset + length].hex().upper(),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind")
    ap.add_argument("symbol")
    ap.add_argument("--len", type=int, default=6, dest="length", help="expected bytes to pin (default 6)")
    ap.add_argument("--capture-offset", type=int, default=0, help="hook PC = address + this")
    ap.add_argument("--yellow-symbol", help="symbol name in pokeyellow.sym when it differs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    entries = pin(args.kind, args.symbol, length=args.length, capture_offset=args.capture_offset,
                  yellow_symbol=args.yellow_symbol)
    for title, e in entries.items():
        print(f"{title:6} {e['symbol']:34} {e['bank']:02X}:{e['address']:04X} flat {e['rom_offset']:6} {e['expected_hex']}")
    if args.dry_run:
        return 0
    data = json.loads(SITES.read_text(encoding="utf-8"))
    for title, e in entries.items():
        data["titles"][title]["sites"][args.kind] = e
    SITES.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"pinned {args.kind!r} into {SITES.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
