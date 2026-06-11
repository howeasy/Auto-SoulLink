"""
Unit tests for server/patcher.py — the in-browser companion-ROM patcher routes.

Covers the patch-file endpoint contract the browser patcher (static/patcher.js)
and the "download .ups" link rely on:
  * 200 with octet-stream + attachment headers + exact file bytes when the UPS exists
  * 404 with the "run build.py" hint when it doesn't
  * the md5 fingerprint constants stay in sync with patch/README.md

Run:
    pytest tests/unit/test_patcher_routes.py -v
"""

import os
import re

import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import server.patcher as patcher

pytest_plugins = ("pytest_asyncio",)


def _make_app() -> web.Application:
    app = web.Application()
    # The page route needs jinja2 setup; these tests only exercise the file
    # endpoint, but setup_patcher_routes registers both, so satisfy the import.
    import aiohttp_jinja2
    import jinja2
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(
        os.path.join(os.path.dirname(patcher.__file__), "templates")))
    patcher.setup_patcher_routes(app, sidebar_builder=lambda active: "")
    return app


@pytest.mark.asyncio
async def test_patch_file_served_with_download_headers(tmp_path, monkeypatch):
    """When the UPS exists, the endpoint returns its exact bytes as a download."""
    ups = tmp_path / "SLink-RR.ups"
    payload = b"UPS1\x00fake-patch-bytes"
    ups.write_bytes(payload)
    monkeypatch.setattr(patcher, "PATCH_FILE", str(ups))

    client = TestClient(TestServer(_make_app()))
    await client.start_server()
    try:
        resp = await client.get("/companion/SLink-RR.ups")
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "application/octet-stream"
        assert resp.headers["Content-Disposition"] == 'attachment; filename="SLink-RR.ups"'
        assert resp.headers["Cache-Control"] == "no-cache"
        assert await resp.read() == payload
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_patch_file_missing_is_404_with_hint(tmp_path, monkeypatch):
    """When the UPS hasn't been built, the endpoint 404s and says how to fix it."""
    monkeypatch.setattr(patcher, "PATCH_FILE", str(tmp_path / "nope.ups"))

    client = TestClient(TestServer(_make_app()))
    await client.start_server()
    try:
        resp = await client.get("/companion/SLink-RR.ups")
        assert resp.status == 404
        assert "build.py" in await resp.text()
    finally:
        await client.close()


def test_md5_constants_match_readme():
    """BASE_ROM_MD5 / PATCHED_ROM_MD5 must stay in sync with patch/README.md."""
    readme = os.path.normpath(os.path.join(
        os.path.dirname(patcher.__file__), "..", "patch", "README.md"))
    text = open(readme, encoding="utf-8").read()
    assert patcher.BASE_ROM_MD5 in text, "base ROM md5 drifted from patch/README.md"
    assert patcher.PATCHED_ROM_MD5 in text, "patched ROM md5 drifted from patch/README.md"
    # And both look like md5 hex.
    assert re.fullmatch(r"[0-9a-f]{32}", patcher.BASE_ROM_MD5)
    assert re.fullmatch(r"[0-9a-f]{32}", patcher.PATCHED_ROM_MD5)
