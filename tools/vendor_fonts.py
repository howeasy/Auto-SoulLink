"""Vendor a webfont's latin woff2 files into server/static/fonts/.

Fonts are bundled, never fetched at runtime: an OBS browser source caches CDN assets
aggressively and unpredictably, and a stream overlay that loses its font mid-broadcast
reflows on air. Same rule as server/static/vendor/VERSIONS.md.

Google's CSS API serves woff2 only to a browser-shaped User-Agent; with the default one it
hands back TTF, which is roughly four times the bytes for the same glyphs. The UA below is
therefore load-bearing, not decoration.

    python tools/vendor_fonts.py "IBM Plex Sans" "IBM Plex Mono"
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request

FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "server", "static", "fonts",
)

# Any modern Chrome UA works; what matters is that it is not urllib's default, which
# Google reads as "no woff2 support".
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Only the latin subsets. Cyrillic, Greek and Vietnamese are dead weight for a Pokémon
# tracker and every extra file is another thing an overlay waits on.
WANTED_SUBSETS = ("latin", "latin-ext")


def slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def vendor(family: str, weights: str = "400;500;600;700") -> list[str]:
    css_url = (
        "https://fonts.googleapis.com/css2?family="
        + urllib.parse.quote(family).replace("%20", "+")
        + f":wght@{weights}&display=swap"
    )
    css = fetch(css_url).decode("utf-8")

    # The CSS is emitted as a run of /* subset */ comments each followed by its @font-face.
    # Pair each url() back to the subset comment above it so the files can be named for
    # what they contain rather than for the order they happened to arrive in.
    written = []
    subset = "latin"
    for line in css.splitlines():
        m = re.match(r"\s*/\*\s*([a-z0-9-]+)\s*\*/", line)
        if m:
            subset = m.group(1)
            continue
        u = re.search(r"url\((https://[^)]+\.woff2)\)", line)
        if not u or subset not in WANTED_SUBSETS:
            continue
        path = os.path.join(FONT_DIR, f"{slug(family)}-{subset}.woff2")
        # One file per subset: Google ships the same woff2 for every weight of a variable
        # font, so writing per weight would store identical bytes several times over.
        if os.path.exists(path):
            continue
        data = fetch(u.group(1))
        with open(path, "wb") as f:
            f.write(data)
        written.append(f"{os.path.basename(path)}  {len(data) / 1024:.1f} KiB")
    return written


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    os.makedirs(FONT_DIR, exist_ok=True)
    for family in argv:
        out = vendor(family)
        print(f"{family}: " + (", ".join(out) if out else "nothing new"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
