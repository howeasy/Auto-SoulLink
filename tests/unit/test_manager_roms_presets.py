"""server/manager.py — ROM scanning, cartridge downloads and randomizer presets.

Covers the handlers this worker owns: _scan_roms/handle_roms (zero-byte files, duplicate
content across ROM_DIRS), handle_rom_download (strict per-player resolution instead of a
run-level `randomizer` flag, the extension coming from the resolved path, a non-ASCII-safe
Content-Disposition), handle_settings_import (the family threaded through to
admit_settings), and handle_preset_save / handle_preset_delete (a validated name, the
overwrite gate instead of a silent replace, and a save/delete failure surfacing as JSON
instead of a 500 stack trace or a swallowed exception).
handle_rom_upload (~1363 on this branch) also gets two fixes: a per-request temp filename
instead of a per-process one (two concurrent uploads used to share `.upload-{pid}.part`),
and an oversized upload answering JSON instead of a bare 413 text body the page's fetch
cannot parse.
"""
from __future__ import annotations

import asyncio

import aiohttp
import pytest

from server import manager

pytest_plugins = ["tests.unit.manager_harness"]


def _run(run_root, run_id="run_1", name="Kanto Duo"):
    """A minimal stopped run: enough for the registry and download/settings/preset routes,
    without the SLinkServer state _stopped_run (test_manager_pages.py) builds for board
    rendering, which none of these tests touch."""
    run = {"run_id": run_id, "name": name, "created_at": "2026-09-14T12:00:00", "tcp_port": 54321,
           "http_port": 8081, "status": "stopped", "pid": None, "game": "gen1"}
    manager._save_registry([run])
    (run_root / run_id).mkdir(exist_ok=True)
    return run


# ── _scan_roms: zero-byte files and content-identity dedup (bugs 3 & 4) ───────────────────

def test_scan_roms_skips_zero_byte_files(tmp_path, monkeypatch):
    (tmp_path / "empty.gb").write_bytes(b"")
    (tmp_path / "real.gb").write_bytes(b"x" * 100)
    monkeypatch.setattr(manager, "ROM_DIRS", (str(tmp_path),))
    roms = manager.RunManager._scan_roms("")
    assert [r["name"] for r in roms] == ["real.gb"]


def test_scan_roms_dedupes_identical_content_first_folder_wins(tmp_path, monkeypatch):
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    (a_dir / "copy.gb").write_bytes(b"same bytes")
    (b_dir / "copy.gbc").write_bytes(b"same bytes")   # identical content, different folder/name
    (b_dir / "other.gb").write_bytes(b"different bytes")
    monkeypatch.setattr(manager, "ROM_DIRS", (str(a_dir), str(b_dir)))
    roms = manager.RunManager._scan_roms("")
    # a/copy.gb wins over b/copy.gbc (first folder), b/other.gb is distinct content and stays
    assert [r["path"] for r in roms] == [str(a_dir / "copy.gb"), str(b_dir / "other.gb")]


# ── handle_rom_download: strict per-player resolution (bugs 1 & 2) ───────────────────────

@pytest.mark.asyncio
async def test_rom_download_does_not_guess_from_a_truthy_run_level_randomizer(manager_client, manager_dir):
    """A run-level `randomizer` being present must not let an UNRECORDED player download a
    guessed roms/{player}_randomized.gbc -- only THIS player's own entry counts."""
    run = _run(manager_dir)
    only_a = manager_dir / run["run_id"] / "only_a.gb"
    only_a.write_bytes(b"only a")
    manager._update_run(run["run_id"], randomizer={
        "upr_version": "x", "settings_sha256": "", "categories": [], "spec": {}, "summary": "",
        "players": {"a": {"seed": "1", "rom_sha1": "aa", "output": str(only_a)}},
    })
    dl_a = await manager_client.get(f"/api/runs/{run['run_id']}/rom/a")
    assert dl_a.status == 200 and (await dl_a.read()) == b"only a"

    dl_b = await manager_client.get(f"/api/runs/{run['run_id']}/rom/b")
    assert dl_b.status == 404

    # Even a file sitting at the old guessed path must never be served for b.
    guessed = manager_dir / run["run_id"] / "roms" / "b_randomized.gbc"
    guessed.parent.mkdir(parents=True, exist_ok=True)
    guessed.write_bytes(b"wrong file entirely")
    dl_b2 = await manager_client.get(f"/api/runs/{run['run_id']}/rom/b")
    assert dl_b2.status == 404


@pytest.mark.asyncio
async def test_rom_download_extension_comes_from_the_resolved_path(manager_client, manager_dir):
    """The old fallback hardcoded '.gb' while the guessed path it built was '.gbc'. The
    extension must always be the resolved file's own."""
    run = _run(manager_dir)
    rom = manager_dir / run["run_id"] / "b.gbc"
    rom.write_bytes(b"cart")
    manager._update_run(run["run_id"], randomizer={
        "upr_version": "x", "settings_sha256": "", "categories": [], "spec": {}, "summary": "",
        "players": {"b": {"seed": "1", "rom_sha1": "bb", "output": str(rom)}},
    })
    dl = await manager_client.get(f"/api/runs/{run['run_id']}/rom/b")
    assert dl.status == 200
    assert dl.headers["Content-Disposition"].endswith('_b.gbc"')


@pytest.mark.asyncio
async def test_rom_download_content_disposition_survives_a_non_ascii_run_name(manager_client, manager_dir):
    """safe_name's re.sub(r"[^\\w-]", ...) keeps Unicode letters (\\w is Unicode by default),
    so a run name like this reaches the header. Emit an ASCII-safe fallback plus the
    RFC 8187 UTF-8 form rather than crashing or mangling the header."""
    run = _run(manager_dir, name="Kantô Düo")
    rom = manager_dir / run["run_id"] / "a.gb"
    rom.write_bytes(b"cart")
    manager._update_run(run["run_id"], cartridges={"players": {"a": {"output": str(rom)}}})
    dl = await manager_client.get(f"/api/runs/{run['run_id']}/rom/a")
    assert dl.status == 200
    cd = dl.headers["Content-Disposition"]
    assert cd.startswith('attachment; filename="') and "; filename*=UTF-8''" in cd
    ascii_part = cd.split('filename="', 1)[1].split('"', 1)[0]
    ascii_part.encode("ascii")  # must not raise


@pytest.mark.asyncio
async def test_rom_download_content_disposition_is_untouched_for_ascii_names(manager_client, manager_dir):
    """No RFC 8187 noise for the common case: an already-ASCII name gets exactly the header
    it always got."""
    run = _run(manager_dir, name="Kanto Duo")
    rom = manager_dir / run["run_id"] / "a.gb"
    rom.write_bytes(b"cart")
    manager._update_run(run["run_id"], cartridges={"players": {"a": {"output": str(rom)}}})
    dl = await manager_client.get(f"/api/runs/{run['run_id']}/rom/a")
    assert dl.headers["Content-Disposition"] == 'attachment; filename="slink_Kanto_Duo_a.gb"'


# ── handle_settings_import: the family reaches admit_settings (bug 5) ────────────────────

@pytest.mark.asyncio
async def test_settings_import_admits_by_the_given_family(manager_client):
    """type_themed_gyms is a normal vanilla setting but forbidden for pureRGB (pure entries
    carry no gym/Elite tags) -- proof the family actually reaches admit_settings rather than
    always defaulting to vanilla."""
    from server.upr_settings import build_spec
    blob = build_spec({"trainers": "type_themed_gyms"})

    async def imp(family):
        form = aiohttp.FormData()
        form.add_field("file", blob, filename="x.rnqs", content_type="application/octet-stream")
        if family is not None:
            form.add_field("family", family)
        return await (await manager_client.post("/api/randomizer/settings/import", data=form)).json()

    vanilla_default = await imp(None)
    assert vanilla_default["ok"] and vanilla_default["spec"]["trainers"] == "type_themed_gyms"

    pure = await imp("gen1_purergb")
    assert pure["ok"] is False and "trainers" in pure["error"]

    unknown = await imp("not_a_real_family")
    assert unknown["ok"] is False and "unknown family" in unknown["error"]


# ── handle_preset_save / handle_preset_delete (bugs 6 & 7) ───────────────────────────────

@pytest.mark.asyncio
async def test_preset_save_rejects_bad_names_instead_of_coercing_or_truncating(manager_client):
    assert (await manager_client.post("/api/presets", json={"name": 5, "spec": {}})).status == 400
    assert (await manager_client.post("/api/presets", json={"name": None, "spec": {}})).status == 400
    assert (await manager_client.post("/api/presets", json={"name": "", "spec": {}})).status == 400
    assert (await manager_client.post("/api/presets", json={"name": "x" * 61, "spec": {}})).status == 400
    ok = await (await manager_client.post("/api/presets", json={"name": "x" * 60, "spec": {}})).json()
    assert ok["ok"] and ok["preset"]["name"] == "x" * 60


@pytest.mark.asyncio
async def test_preset_save_replace_requires_explicit_overwrite(manager_client):
    first = await (await manager_client.post(
        "/api/presets", json={"name": "Chaos", "spec": {"wild": "random"}})).json()
    assert first["ok"]

    conflict = await manager_client.post("/api/presets", json={"name": "chaos", "spec": {"wild": "area"}})
    assert conflict.status == 409
    body = await conflict.json()
    assert body["ok"] is False and body.get("conflict") is True

    # refused, so the original preset is untouched
    listed = await (await manager_client.get("/api/presets")).json()
    assert len(listed["presets"]) == 1 and listed["presets"][0]["spec"]["wild"] == "random"

    replaced = await (await manager_client.post(
        "/api/presets", json={"name": "chaos", "spec": {"wild": "area"}, "overwrite": True})).json()
    assert replaced["ok"] and replaced["preset"]["spec"]["wild"] == "area"
    listed = await (await manager_client.get("/api/presets")).json()
    assert len(listed["presets"]) == 1 and listed["presets"][0]["spec"]["wild"] == "area"


@pytest.mark.asyncio
async def test_preset_save_failure_is_reported_as_json_not_a_crash(manager_client, monkeypatch):
    def boom(_presets):
        raise OSError("disk full")
    monkeypatch.setattr(manager, "_save_presets", boom)
    resp = await manager_client.post("/api/presets", json={"name": "Chaos", "spec": {}})
    assert resp.status == 500
    body = await resp.json()
    assert body["ok"] is False and "disk full" in body["error"]


@pytest.mark.asyncio
async def test_preset_delete_failure_is_reported_as_json_not_a_crash(manager_client, monkeypatch):
    ok = await (await manager_client.post("/api/presets", json={"name": "Chaos", "spec": {}})).json()
    assert ok["ok"]

    def boom(_presets):
        raise OSError("disk full")
    monkeypatch.setattr(manager, "_save_presets", boom)
    resp = await manager_client.post("/api/presets/delete", json={"name": "Chaos"})
    assert resp.status == 500
    body = await resp.json()
    assert body["ok"] is False and "disk full" in body["error"]


# ── handle_rom_upload: a unique temp name and a JSON 413 ─────────────────────────────────

@pytest.mark.asyncio
async def test_rom_upload_oversized_file_is_a_json_413_not_a_bare_text_body(manager_client, tmp_path, monkeypatch):
    """The old HTTPRequestEntityTooLarge answered 413 with a text/plain body; the page's
    fetch always parses JSON, so the user saw a parse error instead of the actual limit."""
    dest = tmp_path / "roms"
    monkeypatch.setattr(manager, "ROM_UPLOAD_DIR", str(dest))
    monkeypatch.setattr(manager, "UPLOAD_MAX", 4)
    form = aiohttp.FormData()
    form.add_field("file", b"x" * 100, filename="big.gb", content_type="application/octet-stream")
    resp = await manager_client.post("/api/roms", data=form)
    assert resp.status == 413
    body = await resp.json()   # raises aiohttp.ContentTypeError against a text/plain body
    assert body["ok"] is False and "too large" in body["error"] and "MB" in body["error"]
    assert not dest.is_dir() or list(dest.iterdir()) == []   # no partial file kept


@pytest.mark.asyncio
async def test_rom_upload_concurrent_uploads_do_not_share_a_temp_file(manager_client, tmp_path, monkeypatch):
    """Two uploads in flight at once used to share `.upload-{pid}.part` (one pid for the
    whole process): one clobbered or corrupted the other's bytes. Payloads bigger than one
    read_chunk (1 MiB) so both requests actually interleave across awaits."""
    monkeypatch.setattr(manager, "ROM_UPLOAD_DIR", str(tmp_path / "roms"))

    async def upload(name, fill, size):
        form = aiohttp.FormData()
        form.add_field("file", bytes([fill]) * size, filename=name, content_type="application/octet-stream")
        return await (await manager_client.post("/api/roms", data=form)).json()

    size = (1 << 20) + 4096
    j_a, j_b = await asyncio.gather(upload("a.gb", 0xAA, size), upload("b.gb", 0xBB, size))
    assert j_a["ok"] and j_b["ok"]
    assert (tmp_path / "roms" / "a.gb").read_bytes() == bytes([0xAA]) * size
    assert (tmp_path / "roms" / "b.gb").read_bytes() == bytes([0xBB]) * size


# ── _scan_roms reads each ROM once and caches by (size, mtime) ───────────────────────────

def test_scan_roms_reads_each_file_once_then_hits_the_cache(tmp_path, monkeypatch):
    import builtins
    import os
    rom = tmp_path / "red.gb"
    rom.write_bytes(b"x" * 100)
    monkeypatch.setattr(manager, "ROM_DIRS", (str(tmp_path),))
    reads, real_open = [], builtins.open

    def counting_open(file, mode="r", *a, **k):
        if str(file) == str(rom) and "r" in mode:
            reads.append(file)
        return real_open(file, mode, *a, **k)
    monkeypatch.setattr(builtins, "open", counting_open)

    first = manager.RunManager._scan_roms("")
    assert len(reads) == 1, "hash for dedup and describe_rom share one read"
    assert manager.RunManager._scan_roms("") == first and len(reads) == 1, "unchanged file: cache hit"
    rom.write_bytes(b"y" * 101)
    os.utime(rom, ns=(1, 1))
    assert manager.RunManager._scan_roms("")[0]["sha1"] != first[0]["sha1"] and len(reads) == 2


# ── handle_rom_upload: a duplicate answers with the file already there ──────────────────

@pytest.mark.asyncio
async def test_rom_upload_of_an_existing_rom_returns_that_file(manager_client, tmp_path, monkeypatch):
    """A copy of a ROM already in the repo root used to land in roms/ and be selected; the
    next scan deduped the roms/ copy away and the picker went blank."""
    root, up = tmp_path / "root", tmp_path / "roms"
    root.mkdir()
    (root / "Red.gb").write_bytes(b"red bytes")
    monkeypatch.setattr(manager, "ROM_DIRS", (str(root), str(up)))
    monkeypatch.setattr(manager, "ROM_UPLOAD_DIR", str(up))
    form = aiohttp.FormData()
    form.add_field("file", b"red bytes", filename="copy of red.gb", content_type="application/octet-stream")
    j = await (await manager_client.post("/api/roms", data=form)).json()
    assert j["ok"] and j["existing"] and j["path"] == str(root / "Red.gb")
    assert [r["path"] for r in manager.RunManager._scan_roms("")] == [j["path"]]
    assert not up.is_dir() or list(up.iterdir()) == []   # no duplicate (and no .part) kept
