"""server/patcher.py — in-browser companion-ROM patcher routes.

Shared by both aiohttp apps (``server.py`` per-run dashboard + ``manager.py``)
so the patcher page is reachable from either port. Registers two routes:

* ``GET /patcher`` — the patcher page, wrapped in the standard SLink chrome
  (sidebar / theme / font) via the ``patcher.html`` Jinja template.
* ``GET /companion/SLink-RR.ups`` — serves the built UPS patch bytes from
  ``patch/dist/SLink-RR.ups`` as a download. Used both by the in-browser fetch
  (the page applies it client-side) and by the "download .ups" link for users
  who prefer Flips / NUPS / RomPatcher.js.

The actual UPS apply + hashing happens entirely client-side in
``static/patcher.js`` (a 1:1 port of ``patch/tools/make_ups.py``); nothing is
uploaded. This module only serves the page and the patch file.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import aiohttp_jinja2
from aiohttp import web

from server.templating import resolve_theme

# ── Paths ───────────────────────────────────────────────────────────────────
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_DIST = os.path.normpath(os.path.join(_SERVER_DIR, "..", "patch", "dist"))
_PURE_ADMISSION = os.path.normpath(os.path.join(
    _SERVER_DIR, "..", "data", "games", "gen1_purergb", "admission_overlay.json"))


def _pure_md5s(title: str) -> tuple[str, str]:
    """(base md5, overlay md5) for one pure title, from the overlay admission table — the same
    file that admits the cartridge at runtime, so the page can never advertise a hash the
    client would refuse (the literals drifted once after an overlay rebuild)."""
    import json

    with open(_PURE_ADMISSION, encoding="utf-8") as fh:
        rows = json.load(fh)
    clean_path = _PURE_ADMISSION.replace("admission_overlay.json", "admission.json")
    with open(clean_path, encoding="utf-8") as fh:
        clean = json.load(fh)
    for row in rows.values():
        if row.get("title") == title and row.get("kind") == "overlay":
            return clean[row["base_sha1"]]["md5"], row["md5"]
    raise KeyError(f"no overlay admission row for {title}")

# ── Targets ─────────────────────────────────────────────────────────────────
# A REGISTRY, not a single file. There are three companion patches now and they are not
# interchangeable: a UPS carries the CRC32 of the exact source it was diffed against, so
# offering one file for several games means every user but one gets a refusal they cannot
# act on.
#
# Each entry is one clean base dump -> one patched result. md5s are the friendly
# fingerprints the page echoes; correctness is gated by the UPS-embedded CRC32 in
# patcher.js, which is a property of the patch file rather than of this table.
#
# NO YELLOW ENTRY, deliberately. Yellow has arithmetically zero free WRAM
# (pokeyellow/ram/wram.asm: the CGB palette section took Red's gap and the stack was
# shortened $100 -> $EB), so there is no companion build to ship and shipping one would
# imply a capability that cannot exist. tests/unit/test_patcher_routes.py asserts its
# absence rather than leaving it to be noticed.
TARGETS: dict[str, dict] = {
    "rr": {
        "slug":        "rr",
        "label":       "Radical Red",
        "patch":       "SLink-RR.ups",
        "base_md5":    "8529f3a45d32bce4da637976fcf269d4",
        "patched_md5": "bf8e94a01c0aee0aa7eb37c7333329af",
        "accept":      ".gba,application/octet-stream",
        "out_name":    "Pokemon - Radical Red (SLink companion).gba",
        "base_hint":   "a clean Radical Red 4.1 ROM",
    },
    "rb-red": {
        "slug":        "rb-red",
        "label":       "Pokemon Red",
        "patch":       "SLink-RB-Red.ups",
        "base_md5":    "3d45c1ee9abd5738df46d2bdda8b57dc",
        "patched_md5": "eb8c79d45007b9e22f72ada3560a001d",
        "accept":      ".gb,.gbc,application/octet-stream",
        "out_name":    "Pokemon Red (SLink companion).gb",
        "base_hint":   "a clean US/English Pokemon Red dump",
    },
    "rb-blue": {
        "slug":        "rb-blue",
        "label":       "Pokemon Blue",
        "patch":       "SLink-RB-Blue.ups",
        "base_md5":    "50927e843568814f7ed45ec4f944bd8b",
        "patched_md5": "068b59eebc5d8fc573a23e9dfe1376bf",
        "accept":      ".gb,.gbc,application/octet-stream",
        "out_name":    "Pokemon Blue (SLink companion).gb",
        "base_hint":   "a clean US/English Pokemon Blue dump",
    },
    # pureRGB (Vortyne, v2.7.6 @ 7e7a4653): the SLink companion overlay is a source build
    # linked into pureRGB (patch/gen1/purergb/, tools/build_purergb_overlay.py). The base is
    # the locked pure build (data/purergb_sources.lock.json), the result is recorded in
    # data/purergb/overlay_provenance.json and admitted by data/games/gen1_purergb/
    # admission_overlay.json, which is also where these md5s come from.
    "pure-red": {
        "slug":        "pure-red",
        "label":       "pureRGB Red",
        "patch":       "SLink-PureRed.ups",
        "base_md5":    _pure_md5s("purered")[0],
        "patched_md5": _pure_md5s("purered")[1],
        "accept":      ".gbc,.gb,application/octet-stream",
        "out_name":    "Pokemon Red (pureRGB, SLink companion).gbc",
        "base_hint":   "the pureRGB v2.7.6 Red build (pokered.gbc)",
    },
    "pure-blue": {
        "slug":        "pure-blue",
        "label":       "pureRGB Blue",
        "patch":       "SLink-PureBlue.ups",
        "base_md5":    _pure_md5s("pureblue")[0],
        "patched_md5": _pure_md5s("pureblue")[1],
        "accept":      ".gbc,.gb,application/octet-stream",
        "out_name":    "Pokemon Blue (pureRGB, SLink companion).gbc",
        "base_hint":   "the pureRGB v2.7.6 Blue build (pokeblue.gbc)",
    },
    "pure-green": {
        "slug":        "pure-green",
        "label":       "pureRGB Green",
        "patch":       "SLink-PureGreen.ups",
        "base_md5":    _pure_md5s("puregreen")[0],
        "patched_md5": _pure_md5s("puregreen")[1],
        "accept":      ".gbc,.gb,application/octet-stream",
        "out_name":    "Pokemon Green (pureRGB, SLink companion).gbc",
        "base_hint":   "the pureRGB v2.7.6 Green build (pokegreen.gbc)",
    },
}

DEFAULT_TARGET = "rr"


def patch_path(slug: str) -> str:
    """Absolute path to a target's UPS file."""
    return os.path.join(_DIST, TARGETS[slug]["patch"])


# Kept for callers that predate the registry; the RR patch is still the default.
PATCH_FILE = os.path.join(_DIST, TARGETS[DEFAULT_TARGET]["patch"])
BASE_ROM_MD5 = TARGETS[DEFAULT_TARGET]["base_md5"]
PATCHED_ROM_MD5 = TARGETS[DEFAULT_TARGET]["patched_md5"]


def setup_patcher_routes(
    app: web.Application,
    chrome: Callable[[web.Request], dict],
) -> None:
    """Register the patcher routes on ``app``.

    ``chrome`` is a callable ``(request) -> dict`` giving the page its shell: at least
    ``sidebar_html``; both apps also pass ``mgr=True`` and
    ``body_class`` so the page wears the board chrome, the per-run server passes its own
    rail so the brand subtitle + Manager link are populated.
    """

    async def handle_patcher_page(request: web.Request) -> web.Response:
        slug = request.query.get("game", DEFAULT_TARGET)
        if slug not in TARGETS:
            slug = DEFAULT_TARGET
        target = TARGETS[slug]
        ctx = {
            "page_title":      "SLink Companion ROM Patcher",
            "theme":           resolve_theme(request),
            **chrome(request),
            "target":          target,
            "targets":         list(TARGETS.values()),
            "base_rom_md5":    target["base_md5"],
            "patched_rom_md5": target["patched_md5"],
        }
        resp = aiohttp_jinja2.render_template("patcher.html", request, ctx)
        # The rendered theme depends on the slink-theme cookie; revalidate so a
        # theme change on another page isn't masked by a heuristic-cached copy
        # (same reasoning as the calc handler + the /static middleware).
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    async def handle_patch_file(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        slug = next((s for s, t in TARGETS.items() if t["patch"] == name), None)
        if slug is None:
            raise web.HTTPNotFound(text=f"{name} is not a companion patch this build ships")
        path = patch_path(slug)
        if not os.path.isfile(path):
            raise web.HTTPNotFound(
                text=f"{name} not built — run patch/tools/make_ups.py (see patch/README.md)")
        with open(path, "rb") as fh:
            body = fh.read()
        return web.Response(
            body=body,
            content_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/patcher", handle_patcher_page)
    # One route for every target. The old fixed path still resolves, because it is just
    # the RR entry's filename.
    app.router.add_get("/companion/{name}", handle_patch_file)
