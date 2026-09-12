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
import hashlib
import json
from pathlib import Path
from collections.abc import Callable

import aiohttp_jinja2
from aiohttp import web

from server.templating import resolve_theme

# ── Paths ───────────────────────────────────────────────────────────────────
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_DIST = os.path.normpath(os.path.join(_SERVER_DIR, "..", "patch", "dist"))

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
# Gen1 targets are generated from checked ABI-3 artifacts below. Yellow's patch
# supplies native trade only; it does not claim an R/B panel or event SFX.
TARGETS: dict[str, dict] = {
    "rr": {
        "slug":        "rr",
        "label":       "Radical Red",
        "patch":       "SLink-RR.ups",
        "base_md5":    "8529f3a45d32bce4da637976fcf269d4",
        "patched_md5": "8dcffce7659be02474dfa0f876639f8a",
        "accept":      ".gba,application/octet-stream",
        "out_name":    "Pokemon - Radical Red (SLink companion).gba",
        "base_hint":   "a clean Radical Red 4.1 ROM",
    },
}


def _gen1_targets():
    from server.gen1_admission import clean_profiles
    from server.gen1_cartridge_profiles import companion_profiles
    root=Path(_SERVER_DIR).parent
    data=json.loads((root/"data/games/gen1_rby/patcher_targets.json").read_text())
    if data.get("schema")!="gen1-browser-patcher-targets-v1" or set(data.get("targets",{}))!={"rb-red","rb-blue","yellow"}:
        raise ValueError("invalid Gen1 browser target catalog")
    clean,companions=clean_profiles(),companion_profiles()
    for slug,target in data["targets"].items():
        variant=target["variant"];profile=companions[variant]
        if (target["slug"]!=slug or target["base_sha256"]!=clean[variant]["rom_sha256"]
                or target["patched_sha256"]!=profile["rom_sha256"] or target["capabilities"]!=profile["capabilities"]
                or target["patch_sha256"]!=profile["manifest"]["companion"]["ups_sha256"]
                or target["patch_path"]!=profile["manifest"]["companion"]["ups"]
                or not (root/target["patch_path"]).resolve().is_relative_to(root.resolve())):
            raise ValueError("Gen1 browser target differs from installed companion")
    return data["targets"]


_GEN1_TARGETS=_gen1_targets()
TARGETS.update({slug:_GEN1_TARGETS[slug] for slug in ("rb-red","rb-blue","yellow")})

DEFAULT_TARGET = "rr"


def patch_path(slug: str) -> str:
    """Absolute path to a target's UPS file."""
    target=TARGETS[slug]
    if "patch_path"in target:return str(Path(_SERVER_DIR).parent/target["patch_path"])
    return os.path.join(_DIST, target["patch"])


# Kept for callers that predate the registry; the RR patch is still the default.
PATCH_FILE = os.path.join(_DIST, TARGETS[DEFAULT_TARGET]["patch"])
BASE_ROM_MD5 = TARGETS[DEFAULT_TARGET]["base_md5"]
PATCHED_ROM_MD5 = TARGETS[DEFAULT_TARGET]["patched_md5"]


def setup_patcher_routes(
    app: web.Application,
    sidebar_builder: Callable[[str], str],
    prepared_targets=None,
) -> None:
    """Register the patcher routes on ``app``.

    ``sidebar_builder`` is a callable ``(active_slug) -> html`` — each app
    passes its own so the rail renders with that app's port context (the
    manager passes ``build_sidebar_html`` with no ports; the per-run server
    passes its ``_build_sidebar_html`` so the brand subtitle + Manager link
    are populated).
    """

    def targets_for(request):
        extra=prepared_targets(request) if prepared_targets is not None else {}
        if not isinstance(extra,dict) or set(extra)&set(TARGETS):raise ValueError("invalid run patch targets")
        targets={**TARGETS,**extra}
        if len({target['patch'] for target in targets.values()})!=len(targets):raise ValueError("ambiguous patch filenames")
        return targets

    async def handle_patcher_page(request: web.Request) -> web.Response:
        targets=targets_for(request)
        slug = request.query.get("game", DEFAULT_TARGET)
        if slug not in targets:
            slug = DEFAULT_TARGET
        targets={key:{name:value for name,value in target.items() if name!='patch_bytes'} for key,target in targets.items()}
        target = targets[slug]
        ctx = {
            "page_title":      "SLink Companion ROM Patcher",
            "theme":           resolve_theme(request),
            "sidebar_html":    sidebar_builder("patcher"),
            "target":          target,
            "targets":         list(targets.values()),
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
        targets=targets_for(request)
        slug = next((s for s, t in targets.items() if t["patch"] == name), None)
        if slug is None:
            raise web.HTTPNotFound(text=f"{name} is not a companion patch this build ships")
        target=targets[slug]
        if "patch_bytes"in target:
            body=target["patch_bytes"]
            if not isinstance(body,bytes):raise web.HTTPConflict(text="Verified run patch is unavailable.")
        else:
            path = patch_path(slug)
            if not os.path.isfile(path):
                raise web.HTTPNotFound(
                    text=f"{name} not built — run patch/tools/make_ups.py (see patch/README.md)")
            with open(path, "rb") as fh:
                body = fh.read()
        expected=target.get("patch_sha256")
        if expected and hashlib.sha256(body).hexdigest()!=expected:
            raise web.HTTPConflict(text="Companion patch differs from its verified artifact. Rebuild before downloading.")
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
