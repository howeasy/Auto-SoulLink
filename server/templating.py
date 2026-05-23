"""server/templating.py — Jinja2 + static-asset wiring for SLink HTTP apps.

Both ``server.py`` (per-run dashboard) and ``manager.py`` (run manager + stream
overlays) call ``setup_templating(app)`` at startup. This:

* registers ``aiohttp-jinja2`` with the shared ``server/templates/`` loader
* mounts ``/static/*`` to serve ``server/static/`` with sensible cache headers
* exposes ``resolve_theme(request)`` for templates that need to derive the
  active theme from ``?theme=…`` or fall back to ``default``
"""

from __future__ import annotations

import mimetypes
import os
from typing import Optional

import aiohttp_jinja2
import jinja2
from aiohttp import web
from aiohttp import web_fileresponse

# Python's mimetypes db doesn't know font-related types out of the box on
# every platform. Register the ones we vendor on both the global registry
# and aiohttp's private CONTENT_TYPES table so aiohttp's StaticResource
# emits the correct Content-Type — browsers don't strictly enforce this
# for fonts, but lint tools and CDNs upstream of OBS often do.
for _mt, _ext in [
    ("font/woff2", ".woff2"),
    ("font/woff",  ".woff"),
    ("font/ttf",   ".ttf"),
]:
    mimetypes.add_type(_mt, _ext)
    web_fileresponse.CONTENT_TYPES.add_type(_mt, _ext)


# ── Paths ─────────────────────────────────────────────────────────────────────

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(_SERVER_DIR, "templates")
STATIC_DIR = os.path.join(_SERVER_DIR, "static")


# ── Themes ────────────────────────────────────────────────────────────────────
# Whitelist of accepted theme names. Unknown values fall through to "default"
# so a typo in ?theme= silently no-ops rather than 404ing or breaking layout.

VALID_THEMES = frozenset((
    "default",
    "light",
    "transparent",
    "funtastic-grape",
    "funtastic-jungle",
    "funtastic-fire",
    "funtastic-ice",
    "funtastic-watermelon",
    "funtastic-smoke",
))

# Legacy theme name aliases — every existing OBS browser source the user has
# saved uses one of these. Mapping them to the canonical theme names lets
# Funtastic land without breaking any pre-migration overlay URL.
_THEME_ALIASES = {
    "dark": "default",
}


def resolve_theme(request: web.Request) -> str:
    """Return the normalized theme name for this request.

    Resolution order: ``?theme=`` query param wins, then the ``slink-theme``
    cookie (set by ``dashboard.js`` ``applyTheme`` so cross-page navigation
    paints the right theme on first byte instead of flashing default and
    then snapping via JS). Legacy aliases (``dark`` → ``default``) apply at
    each stage; falls back to ``default`` for missing or unknown values.
    The return value is safe to embed in a ``<body class="theme-{theme}">``
    and as a filename ``/static/themes/{theme}.css``.
    """
    def _normalize(raw: str) -> Optional[str]:
        v = (raw or "").strip().lower()
        v = _THEME_ALIASES.get(v, v)
        return v if v in VALID_THEMES else None
    return (
        _normalize(request.query.get("theme", ""))
        or _normalize(request.cookies.get("slink-theme", ""))
        or "default"
    )


# ── Overlay layout variants ──────────────────────────────────────────────
# Stream overlays accept ?layout= to pick a body class that reshapes the
# `#root` container — horizontal, thin-bottom strip, thin sidebar. The
# class names (`lh` / `lth` / `ltv`) are referenced by the overlay CSS in
# slink.css.

_LAYOUT_MAP = {
    "":       "",       # default — no body class
    "h":      "lh",     # horizontal (party stretches across width)
    "thin-h": "lth",    # thin horizontal — narrow bottom strip
    "thin-v": "ltv",    # thin vertical — narrow sidebar
}


def resolve_layout(request: web.Request) -> str:
    """Return the body-class suffix for the ``?layout=`` query parameter.

    Empty for the default layout; ``lh`` / ``lth`` / ``ltv`` for the
    horizontal / thin-horizontal / thin-vertical variants. Unknown values
    fall through to the default (empty string).
    """
    requested = request.query.get("layout", "").strip().lower()
    return _LAYOUT_MAP.get(requested, "")


# ── App setup ─────────────────────────────────────────────────────────────────

def setup_templating(app: web.Application) -> None:
    """Wire Jinja2 templating and ``/static/*`` onto the given aiohttp app."""
    env = aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        # ``autoescape`` defaults to off in aiohttp-jinja2; opt in explicitly so
        # variable interpolation in HTML templates is XSS-safe by default.
        autoescape=jinja2.select_autoescape(["html", "xml", "j2"]),
    )

    # Bitwise filter — Jinja2 has no native bit operators, so the status
    # condition decoder in _macros.html uses ``cond | bitand(mask)`` instead.
    # Returns a Python int so chained tests against 0 work naturally.
    def _bitand(value, mask) -> int:
        try:
            return int(value) & int(mask)
        except (TypeError, ValueError):
            return 0
    env.filters["bitand"] = _bitand

    # Expose resolve_theme to templates as the ``current_theme`` global.
    app["templating"] = {"resolve_theme": resolve_theme}

    # Serve /static/{tail:.*} from disk. The aiohttp built-in handles MIME
    # detection (via the standard ``mimetypes`` module) and conditional GETs
    # (ETag / If-Modified-Since) for free, which OBS browser sources respect.
    if os.path.isdir(STATIC_DIR):
        app.router.add_static(
            "/static/",
            path=STATIC_DIR,
            name="static",
            show_index=False,
            follow_symlinks=False,
            append_version=False,
        )
        # Pair the static route with a no-cache policy. aiohttp's add_static
        # emits ETag + Last-Modified but NO Cache-Control header, which means
        # browsers fall back to heuristic caching (~10% of file age, often
        # capped at hours/days). That bit users repeatedly during the UI
        # migration: a tweak to dashboard.css would land on disk + on the
        # served response, but the browser would keep showing the stale
        # version until a hard refresh.
        #
        # With ``Cache-Control: no-cache``, the browser still caches the
        # asset but MUST revalidate every request. aiohttp answers with a
        # cheap 304 Not Modified when the ETag/Last-Modified matches, so
        # the wire payload is identical to a long-lived cache hit (just an
        # extra ~150 bytes of headers). For SLink's localhost-only
        # deployment this overhead is invisible.
        #
        # Implementation: an on-response middleware registered after the
        # route, scoped to paths under ``/static/``. We don't touch
        # ``no-store`` (would skip caching entirely and re-download every
        # asset) or set a max-age (would re-introduce the staleness).
        @web.middleware
        async def _static_no_cache(request: web.Request, handler):
            resp = await handler(request)
            if request.path.startswith("/static/"):
                resp.headers["Cache-Control"] = "no-cache"
            return resp
        # aiohttp middleware stacks must be set before app start; this
        # helper is called from manager.main() / server.main() during
        # setup, before the runner starts the server.
        app.middlewares.append(_static_no_cache)
