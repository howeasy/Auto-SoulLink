"""The bundled damage calculator's files, for both apps.

The run server serves the calc at ``/calc/…`` and the Manager at ``/runs/{id}/calc/…`` (the
page wears the Manager's chrome; the bridge inside it talks to that run through the
Manager's per-run API proxy). Both resolve files the same way: ``calc/src/`` wins over
``calc/dist/`` when both have the path, so ``calc/src/`` edits go live without the build
step, while the HTML entry points -- only in ``dist/`` -- resolve from there.
"""
from __future__ import annotations

import mimetypes
import ntpath
import os
import re
from pathlib import Path

from aiohttp import web

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(_ROOT, "calc", "dist")
SRC_DIR = os.path.join(_ROOT, "calc", "src")


def resolve(path: str) -> Path:
    """The file for a calc URL path, or HTTPForbidden / HTTPNotFound.

    URL paths must stay relative on Windows as well as POSIX. Normalizing first can hide
    traversal, and a drive-qualified join discards its base; ``resolve()`` follows symlinks
    and junctions before the containment check, since a textual prefix check is not enough.
    """
    if (ntpath.splitdrive(path)[0] or path.startswith("/") or "\\" in path
            or "\x00" in path or ".." in path.split("/")):
        raise web.HTTPForbidden()
    for directory in (SRC_DIR, DIST_DIR):
        try:
            root = Path(directory).resolve()
            candidate = (root / path).resolve()
            if not candidate.is_relative_to(root):
                raise web.HTTPForbidden()
            if candidate.is_file():
                return candidate
        except (OSError, RuntimeError, ValueError):
            raise web.HTTPForbidden() from None
    raise web.HTTPNotFound()


def page_body(abs_path: Path) -> str:
    """The inner ``<body>`` of a calc entry point, for wrapping in SLink's chrome.

    Regex-matched rather than ``text.find('<body')`` so HEAD comments that mention
    ``<body>`` textually do not trip it (the dist HTML's HEAD comment block does). Falls
    back to the whole file so a malformed dist degrades rather than 500s.
    """
    with open(abs_path, encoding="utf-8") as fh:
        full = fh.read()
    open_ = re.search(r"<body\b[^>]*>", full)
    close = list(re.finditer(r"</body\s*>", full))
    if open_ and close:
        return full[open_.end():close[-1].start()]
    return full


def mode_label(path: str) -> str:
    return "Hardcore Mode" if "hardcore" in path.lower() else "Normal Mode"


def file_response(abs_path: Path) -> web.FileResponse:
    mime, _ = mimetypes.guess_type(abs_path)
    return web.FileResponse(abs_path, headers={"Content-Type": mime or "application/octet-stream"})
