#!/usr/bin/env python3
"""Stage the committed overlay and run harness.cmd_live's hello-only stage.

The fixture's SYNTH ancestry is unchanged. --dry-run validates inputs and prints
bindings without writing a lane or starting a server/emulator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True, help="private evidence directory")
    parser.add_argument("--fixture", type=Path, default=os.environ.get("POL_FIXTURE"),
                        help="SaveRAM input (or POL_FIXTURE); disclose its SYNTH ancestry")
    parser.add_argument("--base", type=Path,
                        default=Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) /
                        "cache/polished/release/polishedcrystal-3.2.3.gbc",
                        help="pinned clean release ROM")
    parser.add_argument("--dry-run", action="store_true", help="validate and print inputs; launch nothing")
    args = parser.parse_args(argv)
    if args.fixture is None:
        parser.error("--fixture or POL_FIXTURE is required")

    sys.path[:0] = [str(REPO / "patch/tools"), str(REPO / "tools/polished_live"),
                   str(REPO / "tools"), str(REPO)]
    from make_ups import ups_apply

    patch = REPO / "patch/dist/SLink-Polished.ups"
    data = ups_apply(args.base.read_bytes(), patch.read_bytes())
    rom_sha1 = hashlib.sha1(data).hexdigest()
    provenance = json.loads((REPO / "data/polished/overlay_provenance.json").read_text(encoding="utf-8"))
    if rom_sha1 != provenance["output"]["sha1"]:
        raise SystemExit(f"committed UPS produced {rom_sha1}, provenance pins {provenance['output']['sha1']}")
    fixture = args.fixture.resolve()
    fixture_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
    lane = args.lane.resolve()
    out = lane / "staged_overlay.gbc"
    print(json.dumps({"lane": str(lane), "base": str(args.base.resolve()), "patch": str(patch),
                      "fixture": str(fixture), "fixture_sha256": fixture_sha256,
                      "rom_sha1": rom_sha1, "stages": "1",
                      "evidence_file": str(lane / "live/wire/wire_a.jsonl"),
                      "dry_run": args.dry_run}, indent=2), flush=True)
    if args.dry_run:
        return 0

    os.environ.update(POL_LANE=str(lane), POL_FIXTURE=str(fixture), POL_KIND="overlay",
                      POL_STAGES="1", POL_RUNNAME="live")
    import harness

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    harness.ROM_SRC = out
    os.chdir(REPO)
    return harness.cmd_live()


if __name__ == "__main__":
    raise SystemExit(main())
