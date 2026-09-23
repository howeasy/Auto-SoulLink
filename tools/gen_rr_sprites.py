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
    python tools/gen_rr_sprites.py
"""

import base64
import json
import os
import re
import urllib.request

DATA_JS_URL = "https://raw.githubusercontent.com/JwowSquared/Radical-Red-Pokedex/master/data.js"
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


def main():
    with open(MAP_PATH, encoding="utf-8") as f:
        files = {int(k): v for k, v in json.load(f).items()}
    print(f"Fetching {DATA_JS_URL} ...")
    dex = _dex_sprites(urllib.request.urlopen(DATA_JS_URL).read().decode("utf-8"))
    print(f"  {len(dex)} sprites in data.js")

    by_file: dict[str, int] = {}
    for sid, fname in files.items():
        if sid in dex:
            by_file.setdefault(fname, sid)

    os.makedirs(OUT_DIR, exist_ok=True)
    wrote, skipped = 0, []
    for sid, fname in sorted(files.items()):
        src = sid if sid in dex else by_file.get(fname)
        if src is None:
            m = re.match(r"gFrontSprite(\d+)", fname)
            src = int(m.group(1)) if m and int(m.group(1)) in dex else None
        png = dex.get(src) if src is not None else None
        if png is None or not _is_single_64(png):
            skipped.append(sid)
            continue
        with open(os.path.join(OUT_DIR, f"{sid}.png"), "wb") as f:
            f.write(png)
        wrote += 1
    print(f"Wrote {wrote} sprites to {OUT_DIR}; no sprite for {skipped}")


if __name__ == "__main__":
    main()
