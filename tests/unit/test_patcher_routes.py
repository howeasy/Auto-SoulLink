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
from aiohttp import web  # noqa: E402  (must follow importorskip)
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402  (must follow importorskip)

import server.patcher as patcher  # noqa: E402  (must follow importorskip)


def _make_app() -> web.Application:
    app = web.Application()
    # The page route needs jinja2 setup; these tests only exercise the file
    # endpoint, but setup_patcher_routes registers both, so satisfy the import.
    import aiohttp_jinja2
    import jinja2
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(
        os.path.join(os.path.dirname(patcher.__file__), "templates")))
    patcher.setup_patcher_routes(app, chrome=lambda _req: {"sidebar_html": ""})
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", list(patcher.TARGETS))
async def test_every_target_is_served_with_download_headers(slug, tmp_path, monkeypatch):
    """Each companion patch has its own route, because each is pinned to one dump.

    A UPS carries the CRC32 of the exact source it was diffed against, so a single shared
    file would refuse every user but one -- and that refusal would look like a corrupt
    download rather than the wrong game.
    """
    name = patcher.TARGETS[slug]["patch"]
    payload = b"UPS1" + slug.encode()
    (tmp_path / name).write_bytes(payload)
    monkeypatch.setattr(patcher, "_DIST", str(tmp_path))

    client = TestClient(TestServer(_make_app()))
    await client.start_server()
    try:
        resp = await client.get(f"/companion/{name}")
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "application/octet-stream"
        assert resp.headers["Content-Disposition"] == f'attachment; filename="{name}"'
        assert resp.headers["Cache-Control"] == "no-cache"
        assert await resp.read() == payload
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_patch_file_missing_is_404_with_hint(tmp_path, monkeypatch):
    """When the UPS hasn't been built, the endpoint 404s and says how to fix it."""
    monkeypatch.setattr(patcher, "_DIST", str(tmp_path))

    client = TestClient(TestServer(_make_app()))
    await client.start_server()
    try:
        resp = await client.get("/companion/SLink-RR.ups")
        assert resp.status == 404
        assert "make_ups" in await resp.text()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_an_unknown_patch_name_is_refused(tmp_path, monkeypatch):
    """The route takes a filename, so it must not hand out arbitrary files from dist/."""
    (tmp_path / "secrets.ups").write_bytes(b"UPS1")
    monkeypatch.setattr(patcher, "_DIST", str(tmp_path))

    client = TestClient(TestServer(_make_app()))
    await client.start_server()
    try:
        resp = await client.get("/companion/secrets.ups")
        assert resp.status == 404
    finally:
        await client.close()


def test_no_yellow_companion_artifact_is_shipped():
    """Yellow has arithmetically zero free WRAM for the mailbox, so there is no build to
    ship -- and shipping one would advertise a capability that cannot exist."""
    assert not any("yellow" in t["patch"].lower() for t in patcher.TARGETS.values())
    dist = os.path.normpath(os.path.join(os.path.dirname(patcher.__file__), "..",
                                         "patch", "dist"))
    if os.path.isdir(dist):
        assert not [f for f in os.listdir(dist) if "yellow" in f.lower()]



def test_md5_constants_match_readme():
    """BASE_ROM_MD5 / PATCHED_ROM_MD5 must stay in sync with patch/README.md."""
    readme = os.path.normpath(os.path.join(
        os.path.dirname(patcher.__file__), "..", "patch", "README.md"))
    with open(readme, encoding="utf-8") as fh:
        text = fh.read()
    assert patcher.BASE_ROM_MD5 in text, "base ROM md5 drifted from patch/README.md"
    assert patcher.PATCHED_ROM_MD5 in text, "patched ROM md5 drifted from patch/README.md"
    # And both look like md5 hex.
    assert re.fullmatch(r"[0-9a-f]{32}", patcher.BASE_ROM_MD5)
    assert re.fullmatch(r"[0-9a-f]{32}", patcher.PATCHED_ROM_MD5)


def test_md5_constants_match_build_tools():
    """The base-ROM md5 is also hardcoded in patch/tools/build.py (RR_MD5) and
    make_battle_calc_patch.py (EXPECT_BASE_RR_MD5) — the historically-stale copies
    the README<->patcher.py test doesn't cover. Pin all four to one value."""
    tools = os.path.normpath(os.path.join(
        os.path.dirname(patcher.__file__), "..", "patch", "tools"))
    with open(os.path.join(tools, "build.py"), encoding="utf-8") as fh:
        build_src = fh.read()
    with open(os.path.join(tools, "make_battle_calc_patch.py"), encoding="utf-8") as fh:
        calc_src = fh.read()
    m = re.search(r'RR_MD5\s*=\s*"([0-9a-f]{32})"', build_src)
    assert m and m.group(1) == patcher.BASE_ROM_MD5, \
        "build.py RR_MD5 drifted from server/patcher.py BASE_ROM_MD5"
    m = re.search(r'EXPECT_BASE_RR_MD5\s*=\s*"([0-9a-f]{32})"', calc_src)
    assert m and m.group(1) == patcher.BASE_ROM_MD5, \
        "make_battle_calc_patch.py EXPECT_BASE_RR_MD5 drifted from server/patcher.py BASE_ROM_MD5"


class TestTheShippedPatchesActuallyApply:
    """The apply path had NO coverage on either generation.

    This file used `UPS1` followed by filler as its patch bytes, and patcher.js exports
    `upsApply` "for tests" with nothing consuming it. A patch that downloads correctly and
    produces the wrong ROM is the failure that matters, and nothing could see it. These run
    the real codec over the real shipped files.
    """

    def _tools(self):
        import importlib.util
        path = os.path.normpath(os.path.join(os.path.dirname(patcher.__file__), "..",
                                             "patch", "tools", "make_ups.py"))
        spec = importlib.util.spec_from_file_location("make_ups", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _bytes(self, *paths):
        out = []
        for path in paths:
            if not os.path.exists(path):
                pytest.skip(f"{os.path.basename(path)} not present (ROMs are gitignored)")
            with open(path, "rb") as f:
                out.append(f.read())
        return out

    def _clean(self, name):
        return os.path.normpath(os.path.join(os.path.dirname(patcher.__file__), "..",
                                             "patch", "build", name))

    @pytest.mark.parametrize("slug,base", [("rb-red", "gen1_red.gb"),
                                           ("rb-blue", "gen1_blue.gb")])
    def test_applying_the_shipped_ups_reproduces_the_recorded_md5(self, slug, base):
        import hashlib
        src, patch_bytes = self._bytes(self._clean(base), patcher.patch_path(slug))
        out = self._tools().ups_apply(src, patch_bytes)
        assert hashlib.md5(out).hexdigest() == patcher.TARGETS[slug]["patched_md5"], (
            "the shipped patch does not produce the ROM whose md5 the page advertises")

    @pytest.mark.parametrize("slug,base", [("rb-red", "gen1_red.gb"),
                                           ("rb-blue", "gen1_blue.gb")])
    def test_the_patched_result_carries_the_companion_beacon(self, slug, base):
        """Beyond the hash: the thing the patch exists to add is actually there.

        A hash check proves the bytes match what was built; it cannot tell you the build
        was right. The client detects the patch by reading 'SLNK' at the mailbox, so that
        is what to assert.
        """
        src, patch_bytes = self._bytes(self._clean(base), patcher.patch_path(slug))
        out = self._tools().ups_apply(src, patch_bytes)
        bank = out[0x3F * 0x4000:0x40 * 0x4000]
        assert b"\x3e\x53" in bank[:64], "the beacon writer is missing from bank $3F"
        assert len(out) == len(src), "the patch changed the ROM size"

    @pytest.mark.parametrize("slug,wrong", [("rb-red", "gen1_blue.gb"),
                                            ("rb-blue", "gen1_red.gb")])
    def test_applying_a_patch_to_the_wrong_dump_is_refused(self, slug, wrong):
        """The CRC32 embedded in the UPS is the entire safety mechanism. A patcher that
        ignored it would quietly hand the player a corrupt cartridge."""
        src, patch_bytes = self._bytes(self._clean(wrong), patcher.patch_path(slug))
        with pytest.raises(ValueError, match="source ROM CRC mismatch"):
            self._tools().ups_apply(src, patch_bytes)


def test_pure_targets_advertise_the_admitted_overlay_hashes():
    """The /patcher page's pure rows must name the md5 of the ROM the client admits (the overlay
    admission table) and of the pinned clean build it is applied to -- a literal drifted once."""
    import json
    root = os.path.normpath(os.path.join(os.path.dirname(patcher.__file__), ".."))
    pack = os.path.join(root, "data", "games", "gen1_purergb")
    with open(os.path.join(pack, "admission.json"), encoding="utf-8") as fh:
        clean = json.load(fh)
    with open(os.path.join(pack, "admission_overlay.json"), encoding="utf-8") as fh:
        overlay = json.load(fh)
    by_title = {row["title"]: row for row in overlay.values() if row.get("kind") == "overlay"}
    for slug, title in (("pure-red", "purered"), ("pure-blue", "pureblue"), ("pure-green", "puregreen")):
        row = by_title[title]
        assert patcher.TARGETS[slug]["patched_md5"] == row["md5"]
        assert patcher.TARGETS[slug]["base_md5"] == clean[row["base_sha1"]]["md5"]
