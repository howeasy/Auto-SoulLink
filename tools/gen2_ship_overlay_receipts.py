#!/usr/bin/env python3
"""Ship the digest-free overlay proofs production reads (OVERLAY_ADMISSION D6 step 3).

lua/gen2/entry.lua `Entry.RECEIPT_FILES[pack].overlay` names 22 files under
data/games/gen2_<t>/receipts/overlay/. Their captured sources live in tests/fixtures/gen2:

  * qualifications  receipts/overlay/<name>   copied byte for byte
  * O-33 disclosures (*.synth.json)  <name>   copied byte for byte (they sit beside their SaveRAM)
  * engine_sites / write_window      receipts/overlay/<name>  parsed, artifact_kind must be overlay
    (engine_sites schema v2), ONLY the top-level code_digest dropped, rewritten canonically.

    python tools/gen2_ship_overlay_receipts.py --check
    python tools/gen2_ship_overlay_receipts.py --write   # refuses unless every source is present and valid

A missing or invalid source is a hard error naming the path, never a skip, and --write ships all
22 or nothing. The clean (O-22) namespace is never read or written.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = "tests/fixtures/gen2"
DIGEST_STRIPPED = (".engine_sites.json", ".write_window.json")


def destinations() -> list[str]:
    """The overlay namespace of Entry.RECEIPT_FILES, as repo-relative posix paths."""
    from lupa.lua54 import LuaRuntime

    entry = LuaRuntime(unpack_returned_tuples=True).eval("dofile")(
        (REPO / "lua/gen2/entry.lua").as_posix())
    out: list[str] = []
    for pack in entry.RECEIPT_FILES.values():
        o = pack.overlay
        out += [o.engine_sites, o.write_window, *o.qualifications.values()]
    return sorted(out)


def source_of(root: Path, rel: str) -> Path:
    name = Path(rel).name
    return root / FIXTURES / ("" if name.endswith(".synth.json") else "receipts/overlay") / name


def shipped_bytes(root: Path, rel: str) -> bytes:
    """What the shipped copy must contain; raises ValueError naming the path on a bad source."""
    src = source_of(root, rel)
    if not src.is_file():
        raise ValueError(f"missing source {src.relative_to(root).as_posix()} (for {rel})")
    raw = src.read_bytes()
    if not rel.endswith(DIGEST_STRIPPED):
        return raw
    d = json.loads(raw)
    if d.get("artifact_kind") != "overlay":
        raise ValueError(f"{src.relative_to(root).as_posix()}: artifact_kind is not overlay")
    if rel.endswith(".engine_sites.json") and d.get("schema") != "gen2-engine-site-receipt-v2":
        raise ValueError(f"{src.relative_to(root).as_posix()}: engine_sites schema is not v2")
    d.pop("code_digest", None)
    return (json.dumps(d, indent=1, sort_keys=True) + "\n").encode()


def run(root: Path, write: bool, rels: list[str] | None = None) -> int:
    rels = destinations() if rels is None else rels
    want, errors = {}, []
    for rel in rels:
        try:
            want[rel] = shipped_bytes(root, rel)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(f"ERROR {rel}: {exc}")
    if write:
        if errors:
            print("\n".join(errors), file=sys.stderr)
            print(f"refusing --write: {len(errors)} of {len(rels)} sources missing/invalid; "
                  "nothing written", file=sys.stderr)
            return 1
        for rel, raw in want.items():
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(raw)
        print(f"wrote {len(want)} overlay receipts")
        return 0
    bad = len(errors)
    for rel, raw in want.items():
        dst = root / rel
        state = "MISSING" if not dst.is_file() else "OK" if dst.read_bytes() == raw else "DRIFT"
        bad += state != "OK"
        print(f"{state} {rel}")
    for line in errors:
        print(line)
    print(f"{len(rels) - bad}/{len(rels)} overlay receipts shipped and equal")
    return 1 if bad else 0


def main(argv: list[str] | None = None, root: Path = REPO) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    return run(root, ap.parse_args(argv).write)


if __name__ == "__main__":
    raise SystemExit(main())
