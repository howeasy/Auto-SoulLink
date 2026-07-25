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
from typing import Callable

import aiohttp_jinja2
from aiohttp import web

from server.templating import resolve_theme

# ── Paths ───────────────────────────────────────────────────────────────────
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
# Repo-root-relative: server/ -> ../patch/dist/SLink-RR.ups
PATCH_FILE = os.path.normpath(
    os.path.join(_SERVER_DIR, "..", "patch", "dist", "SLink-RR.ups")
)

# ── Fingerprints (single source of truth: patch/README.md) ──────────────────
# Base clean Radical Red build the patch is pinned to, and the expected md5 of
# the patched result. Surfaced to the page so it can echo the README's friendly
# fingerprints; correctness is gated by the UPS-embedded CRC32 in patcher.js.
BASE_ROM_MD5 = "8529f3a45d32bce4da637976fcf269d4"
PATCHED_ROM_MD5 = "8dcffce7659be02474dfa0f876639f8a"


def setup_patcher_routes(
    app: web.Application,
    sidebar_builder: Callable[[str], str],
) -> None:
    """Register the patcher routes on ``app``.

    ``sidebar_builder`` is a callable ``(active_slug) -> html`` — each app
    passes its own so the rail renders with that app's port context (the
    manager passes ``build_sidebar_html`` with no ports; the per-run server
    passes its ``_build_sidebar_html`` so the brand subtitle + Manager link
    are populated).
    """

    async def handle_patcher_page(request: web.Request) -> web.Response:
        ctx = {
            "page_title":      "SLink Companion ROM Patcher",
            "theme":           resolve_theme(request),
            "sidebar_html":    sidebar_builder("patcher"),
            "base_rom_md5":    BASE_ROM_MD5,
            "patched_rom_md5": PATCHED_ROM_MD5,
        }
        resp = aiohttp_jinja2.render_template("patcher.html", request, ctx)
        # The rendered theme depends on the slink-theme cookie; revalidate so a
        # theme change on another page isn't masked by a heuristic-cached copy
        # (same reasoning as the calc handler + the /static middleware).
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    async def handle_patch_file(request: web.Request) -> web.Response:
        if not os.path.isfile(PATCH_FILE):
            raise web.HTTPNotFound(text="SLink-RR.ups not built — run patch/tools/build.py")
        with open(PATCH_FILE, "rb") as fh:
            body = fh.read()
        return web.Response(
            body=body,
            content_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="SLink-RR.ups"',
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/patcher", handle_patcher_page)
    app.router.add_get("/companion/SLink-RR.ups", handle_patch_file)
