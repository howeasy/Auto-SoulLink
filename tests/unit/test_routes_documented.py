"""Every route either app registers is written down in docs/REFERENCE.md.

106 routes were registered and 29 appeared in no document; the number drifts the moment
nobody is looking. The check is mechanical: a route's path (with its `{params}`) must be
in REFERENCE.md, except an overlay's `/fragment` twin, which one row covers for all.
"""
from __future__ import annotations

import os
import re
import types

import pytest

pytest.importorskip("aiohttp")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _doc() -> str:
    with open(os.path.join(_REPO, "docs", "REFERENCE.md"), encoding="utf-8") as f:
        return f.read()


def _run_server_routes():
    from server.server import SLinkServer, build_app
    stub = types.SimpleNamespace()
    for name in dir(SLinkServer):
        if name.startswith("handle_") or name in ("_build_sidebar_html", "STREAM_OVERLAYS"):
            setattr(stub, name, getattr(SLinkServer, name))
    app = build_app(stub)
    return sorted({getattr(r.resource, "canonical", str(r.resource)) for r in app.router.routes()
                   if r.method in ("GET", "POST")})


def _manager_routes():
    """The manager registers routes inside main(); read them off the source rather than
    binding a socket."""
    with open(os.path.join(_REPO, "server", "manager.py"), encoding="utf-8") as f:
        src = f.read()
    return sorted(set(re.findall(r'add_(?:get|post)\("([^"]+)"', src)))


def _documented(path: str, doc: str) -> bool:
    if path.endswith("/fragment"):
        return "`/stream/{slug}/fragment`" in doc
    if path in doc:
        return True
    # `/api/runs/{id}/start` · `/stop` style rows, and {run_id} vs {id}
    loose = path.replace("{run_id}", "{id}")
    if loose in doc:
        return True
    head, _, tail = loose.rpartition("/")
    return bool(tail) and f"`/{tail}`" in doc and head in doc


@pytest.mark.parametrize("path", _run_server_routes())
def test_run_server_route_is_documented(path):
    assert _documented(path, _doc()), f"{path} is registered on the run server but not in docs/REFERENCE.md"


@pytest.mark.parametrize("path", _manager_routes())
def test_manager_route_is_documented(path):
    assert _documented(path, _doc()), f"{path} is registered on the Manager but not in docs/REFERENCE.md"
