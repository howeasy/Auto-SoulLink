"""Generate data/games/polished_crystal/overlay/beacon.json: a digest over EVERY byte the Polished companion overlay changes.

lua/gen2/polished.lua's rand_overlay gate (P.admit, anchors mode) re-hashes these spans from the executing ROM. A
randomized companion cartridge keeps them all: server/upr_polished_write_domain.check_output refuses any UPR output
that wrote an overlay-owned byte, bank $7E or the header, so a cartridge whose spans differ is not an intact overlay.
The Polished counterpart of tools/gen_gen2_beacon.py (claude/gen2-randomizer).

The spans are the UPS hunks (server.upr_polished_write_domain.ups_spans) of the provenance's UPS, cross-checked against
a byte diff of the pinned release and the overlay it yields. Every input is pinned: the release to
data/polished_sources.lock.json and the provenance base_sha1, the UPS to the provenance's ups sha256, the overlay to
the provenance output sha1 (data/polished/overlay_provenance.json, read only).

    python tools/gen_polished_beacon.py [--rom <polishedcrystal-3.2.3.gbc>]          # write the beacon
    python tools/gen_polished_beacon.py [--rom <polishedcrystal-3.2.3.gbc>] --check  # exit 1 if it is stale

Default --rom: $SLINK_WORK_ROOT/cache/polished/release/polishedcrystal-3.2.3.gbc (SLINK_WORK_ROOT defaults to F:/slink-work).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from patch.tools.make_ups import ups_apply  # noqa: E402
from server.upr_polished_write_domain import ups_spans  # noqa: E402

SCHEMA = "polished-overlay-beacon-v1"
BEACON = "data/games/polished_crystal/overlay/beacon.json"
DEFAULT_ROM = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"


def _json(rel: str) -> dict:
    return json.loads((REPO / rel).read_text(encoding="utf-8"))


def build(clean: bytes) -> dict:
    """The beacon from the pinned release; raises SystemExit on any pin mismatch."""
    prov = _json("data/polished/overlay_provenance.json")
    lock_sha1 = _json("data/polished_sources.lock.json")["outputs"]["polishedcrystal"]["sha1"]
    clean_sha1 = hashlib.sha1(clean).hexdigest()
    if clean_sha1 != lock_sha1 or clean_sha1 != prov["base_sha1"]:
        raise SystemExit(f"release {clean_sha1} is not the pinned {lock_sha1} / provenance base_sha1")
    out = prov["output"]
    ups = (REPO / out["ups"]["file"]).read_bytes()
    ups_sha256 = hashlib.sha256(ups).hexdigest()
    if ups_sha256 != out["ups"]["sha256"]:
        raise SystemExit(f"{out['ups']['file']} sha256 {ups_sha256} is not the provenance's {out['ups']['sha256']}")
    overlay = ups_apply(clean, ups)
    overlay_sha1 = hashlib.sha1(overlay).hexdigest()
    if overlay_sha1 != out["sha1"] or len(overlay) != out["size"]:
        raise SystemExit(f"overlay {overlay_sha1} is not the provenance output {out['sha1']}")
    spans = ups_spans(ups)
    changed = [i for i, (x, y) in enumerate(zip(clean, overlay, strict=True)) if x != y]
    if [i for a, b in spans for i in range(a, b)] != changed:
        raise SystemExit("UPS hunks disagree with the release/overlay byte diff")
    # T8 ruling (2026-10-04): the beacon pins the overlay's identity, so the 20-byte version field
    # and the GB global checksum it perturbs must be EXCLUDED -- re-stamping --version then moves
    # neither beacon.json nor the canonical sha1. Both come from rom_identity (slot_from_sym /
    # GB_CHECKSUM), so "canonical" has exactly one definition.
    slot = out.get("version_slot")
    if not slot:
        raise SystemExit("provenance has no version_slot; rebuild with the T8 canonical identity")
    excluded = set(range(slot["offset"], slot["offset"] + slot["length"])) | set(range(0x14E, 0x150))
    beacon: list[tuple[int, int]] = []
    for lo, hi in spans:
        cur = lo
        for i in range(lo, hi):
            if i in excluded:
                if cur < i:
                    beacon.append((cur, i))
                cur = i + 1
        if cur < hi:
            beacon.append((cur, hi))
    keep = {i for a, b in beacon for i in range(a, b)}
    union = {i for a, b in spans for i in range(a, b)}
    if union - (keep | excluded):
        raise SystemExit("beacon spans + excluded do not cover the UPS hunks")
    if keep & excluded:
        raise SystemExit("a beacon span overlaps an excluded byte")
    spans = beacon
    body = b"".join(overlay[a:b] for a, b in spans)
    return {
        "schema": SCHEMA,
        "title": "polished",
        "source": {"overlay_sha1": overlay_sha1, "clean_sha1": clean_sha1, "ups_sha256": ups_sha256,
                   "ups_file": out["ups"]["file"], "rom_size": len(overlay),
                   "canonical_sha1": out.get("canonical_sha1"),
                   "version_slot": slot, "canonical_spans": out.get("canonical_spans"),
                   "excluded": sorted(excluded), "generator": "tools/gen_polished_beacon.py"},
        "count": len(spans),
        "total": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "spans": [{"offset": a, "length": b - a} for a, b in spans],
    }


def render(doc: dict) -> str:
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def main(argv: list[str] | None = None, out_root: Path = REPO) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rom", default=str(DEFAULT_ROM), help="the pinned Polished Crystal v3.2.3 release")
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed beacon differs")
    args = ap.parse_args(argv)
    rom = Path(args.rom)
    if not rom.is_file():
        raise SystemExit(f"pinned Polished Crystal release absent: {rom}")
    text, path = render(build(rom.read_bytes())), out_root / BEACON
    if args.check:
        have = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else None
        if have != text:
            print(f"STALE {path}")
            return 1
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
