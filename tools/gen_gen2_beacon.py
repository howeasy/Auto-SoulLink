"""Generate data/games/gen2_<title>/overlay/beacon.json: a digest over EVERY byte the SLink companion overlay changes.

lua/gen2/entry.lua's rand_overlay gate (docs/gen2/RANDOMIZER.md, "Overlay beacon") re-hashes these spans from the
executing ROM. A randomized companion cartridge keeps them all: R0 proved the pinned UPR fork never writes an
overlay-changed byte (server/upr_gen2_write_domain.py re-proves it on every output), so a cartridge whose spans
differ is not an intact overlay, whatever its two hook pins say.

The spans are the UPS hunks (server.upr_gen2_write_domain.ups_spans) of patch/dist/SLink-<Title>.ups, cross-checked
against a byte diff of the pinned clean build and the overlay it produces. Every input is pinned: the clean build to
data/gen2_sources.lock.json and the binding's base_sha1, the UPS to the binding's ups_sha256, the overlay it yields
to the binding's rom_sha1 (data/games/gen2_<title>/overlay/binding.json, read only).

    python tools/gen_gen2_beacon.py --rom <clean.gbc> [--rom ...]          # write the three beacons
    python tools/gen_gen2_beacon.py --rom <clean.gbc> [--rom ...] --check  # exit 1 if any is stale

--rom names candidate clean builds (any order, any name; each title takes the one at its pin). Default pool:
.cache/gen2-build/{pokecrystal/pokecrystal,pokegold/pokegold,pokegold/pokesilver}.gbc.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from patch.tools.make_ups import ups_apply  # noqa: E402
from server.upr_gen2_write_domain import TITLES, ups_spans  # noqa: E402

SCHEMA = "gen2-overlay-beacon-v1"
BEACON = "data/games/gen2_{title}/overlay/beacon.json"
DEFAULT_POOL = [".cache/gen2-build/pokecrystal/pokecrystal.gbc", ".cache/gen2-build/pokegold/pokegold.gbc",
                ".cache/gen2-build/pokegold/pokesilver.gbc"]


def _json(rel: str) -> dict:
    return json.loads((REPO / rel).read_text(encoding="utf-8"))


def build(title: str, clean: bytes) -> dict:
    """The beacon of one title from its pinned clean build; raises on any pin mismatch."""
    binding = _json(f"data/games/gen2_{title}/overlay/binding.json")
    lock_sha1 = _json("data/gen2_sources.lock.json")["outputs"][TITLES[title][0]]["sha1"]
    clean_sha1 = hashlib.sha1(clean).hexdigest()
    if clean_sha1 != lock_sha1 or clean_sha1 != binding["base_sha1"]:
        raise SystemExit(f"{title}: clean build {clean_sha1} is not the pinned {lock_sha1} / binding base")
    prov = _json("data/gen2/overlay_provenance.json")["outputs"][TITLES[title][0]]
    ups = (REPO / prov["ups"]["file"]).read_bytes()
    ups_sha256 = hashlib.sha256(ups).hexdigest()
    if ups_sha256 != binding["ups_sha256"]:
        raise SystemExit(f"{title}: {prov['ups']['file']} sha256 {ups_sha256} is not the binding's ups_sha256")
    overlay = ups_apply(clean, ups)
    overlay_sha1 = hashlib.sha1(overlay).hexdigest()
    if overlay_sha1 != binding["rom_sha1"]:
        raise SystemExit(f"{title}: overlay {overlay_sha1} is not binding.rom_sha1 {binding['rom_sha1']}")
    spans = ups_spans(ups)
    changed = [i for i, (x, y) in enumerate(zip(clean, overlay, strict=True)) if x != y]
    if [i for a, b in spans for i in range(a, b)] != changed:
        raise SystemExit(f"{title}: UPS hunks disagree with the clean/overlay byte diff")
    body = b"".join(overlay[a:b] for a, b in spans)
    return {
        "schema": SCHEMA,
        "title": title,
        "source": {"overlay_sha1": overlay_sha1, "clean_sha1": clean_sha1, "ups_sha256": ups_sha256,
                   "ups_file": prov["ups"]["file"], "generator": "tools/gen_gen2_beacon.py"},
        "count": len(spans),
        "total": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "spans": [{"offset": a, "length": b - a} for a, b in spans],
    }


def render(doc: dict) -> str:
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def _pool(paths: list[str]) -> dict[str, bytes]:
    out = {}
    for p in paths:
        path = Path(p) if Path(p).is_absolute() else REPO / p
        if path.is_file():
            data = path.read_bytes()
            out[hashlib.sha1(data).hexdigest()] = data
    return out


def main(argv: list[str] | None = None, out_root: Path = REPO) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rom", action="append", help="candidate clean build (repeatable)")
    ap.add_argument("--check", action="store_true", help="exit 1 if a committed beacon differs")
    args = ap.parse_args(argv)
    pool = _pool(args.rom or DEFAULT_POOL)
    stale = 0
    for title, (key, _) in TITLES.items():
        pin = _json("data/gen2_sources.lock.json")["outputs"][key]["sha1"]
        if pin not in pool:
            raise SystemExit(f"{title}: pinned clean build {pin} not among --rom")
        text, path = render(build(title, pool[pin])), out_root / BEACON.format(title=title)
        if args.check:
            have = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else None
            if have != text:
                stale += 1
                print(f"STALE {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
            print(f"wrote {path}")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
