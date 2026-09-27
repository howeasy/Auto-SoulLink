"""Vendor the Radical Red front sprites into server/static/sprites/rr/<id>.png.

The sprites used to be hot-linked from funnotbun/funnotbun.github.io, which no longer
exists. The Radical Red dex (https://dex.radicalred.net) loads its data from
JwowSquared/Radical-Red-Pokedex's data.js, which embeds every front sprite as a base64
PNG keyed by the CFRU species id -- the same non-standard ids SLink's RR species use
(440 = Turtwig, 900 = Camerupt-Mega, 1200 = Nymble-Sevii), not national dex numbers.
The art is pixel-identical to the old funnotbun files, minus their chroma-key background.

data/games/gen3_frlge/rr_sprites.json (id -> funnotbun filename) stays the list of ids
to write. A few ids have no sprite of their own in the dex (1214 reuses Koffing's
graphic, 1224 Mime Jr.'s); those take the sprite of another id sharing their filename,
or of the id in the filename itself. Ids left with nothing fall back to PokeAPI in the
adapter.

Usage:
    python tools/gen_rr_sprites.py            # regenerate the vendored sprites
    python tools/gen_rr_sprites.py --check     # regenerate in memory and diff
                                                 # every sprite's bytes against
                                                 # the committed PNGs

data.js used to be read from the live 'master' branch. This now reads a
byte-for-byte pinned commit declared in data/gen3_rr_sources.lock.json
(jwowsquared_data_js). See docs/gen3_requirements.md row F-7 and
tools/fetch_rr_sources.py.
"""

import argparse
import base64
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_rr_sources import cached_source  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_PATH = os.path.join(ROOT, "data", "games", "gen3_frlge", "rr_sprites.json")
OUT_DIR = os.path.join(ROOT, "server", "static", "sprites", "rr")
PNG_64 = (b"\x89PNG\r\n\x1a\n", 64, 64)


def _dex_sprites(js: str) -> dict[int, bytes]:
    body = js[js.index("sprites"):]
    return {int(k): base64.b64decode(v)
            for k, v in re.findall(r"(\d+):'data:image/png;base64,([A-Za-z0-9+/=]+)'", body)}


def _is_single_64(png: bytes) -> bool:
    # IHDR width/height; a multi-form sheet (Castform) is taller than 64.
    return png.startswith(PNG_64[0]) and int.from_bytes(png[16:20]) == 64 \
        and int.from_bytes(png[20:24]) == 64


def _resolve_sprites(files: dict[int, str], dex: dict[int, bytes]) -> tuple[dict[int, bytes], list[int]]:
    """Return ({sid: png_bytes}, [skipped_sid, ...])."""
    by_file: dict[str, int] = {}
    for sid, fname in files.items():
        if sid in dex:
            by_file.setdefault(fname, sid)

    resolved: dict[int, bytes] = {}
    skipped: list[int] = []
    for sid, fname in sorted(files.items()):
        src = sid if sid in dex else by_file.get(fname)
        if src is None:
            m = re.match(r"gFrontSprite(\d+)", fname)
            src = int(m.group(1)) if m and int(m.group(1)) in dex else None
        png = dex.get(src) if src is not None else None
        if png is None or not _is_single_64(png):
            skipped.append(sid)
            continue
        resolved[sid] = png
    return resolved, skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help=f"Regenerate in memory and diff every sprite's bytes "
                             f"against the committed PNGs under {OUT_DIR}; exit 1 on drift.")
    args = parser.parse_args()

    with open(MAP_PATH, encoding="utf-8") as f:
        files = {int(k): v for k, v in json.load(f).items()}
    dex = _dex_sprites(cached_source("jwowsquared_data_js").decode("utf-8"))
    print(f"  {len(dex)} sprites in data.js")

    resolved, skipped = _resolve_sprites(files, dex)

    if args.check:
        committed_ids = {int(f[:-4]) for f in os.listdir(OUT_DIR) if f.endswith(".png")}
        mismatched = []
        for sid, png in resolved.items():
            path = os.path.join(OUT_DIR, f"{sid}.png")
            if not os.path.exists(path):
                mismatched.append((sid, "missing"))
                continue
            with open(path, "rb") as f:
                if f.read() != png:
                    mismatched.append((sid, "bytes differ"))
        extra_committed = sorted(committed_ids - set(resolved))
        if not mismatched and not extra_committed:
            print(f"OK: {len(resolved)} regenerated sprites match the committed "
                  f"PNGs under {OUT_DIR} byte-for-byte.")
            return 0
        print(f"DRIFT: {len(mismatched)} sprite(s) differ, "
              f"{len(extra_committed)} committed sprite(s) not reproduced.", file=sys.stderr)
        print(f"  mismatched sample: {mismatched[:10]}", file=sys.stderr)
        print(f"  extra committed sample: {extra_committed[:10]}", file=sys.stderr)
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    for sid, png in resolved.items():
        with open(os.path.join(OUT_DIR, f"{sid}.png"), "wb") as f:
            f.write(png)
    print(f"Wrote {len(resolved)} sprites to {OUT_DIR}; no sprite for {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
