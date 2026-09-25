"""Only a jar whose SHA-256 is in data/upr_jars.json is ever handed to `java -jar`.

The jar path reaches the Manager from a browser (the cartridges body, the status query), so
anything else would run arbitrary code. Trust is by hash, never by name, location or the
fork's (forgeable) INI marker, and an unknown jar is refused before subprocess.Popen."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import aiohttp
import pytest

from server import cartridges, upr_pipeline

pytest_plugins = ["tests.unit.manager_harness"]


def _popen_forbidden(*_a, **_k):
    raise AssertionError("Java was launched for an untrusted jar")


@pytest.fixture
def allowlist(tmp_path, monkeypatch):
    """An empty allowlist in tmp; `pin(path)` admits a jar by its hash."""
    path = tmp_path / "upr_jars.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(upr_pipeline, "UPR_JAR_ALLOWLIST", str(path))

    def pin(jar):
        pins = json.loads(path.read_text(encoding="utf-8"))
        pins[f"test {os.path.basename(jar)}"] = hashlib.sha256(Path(jar).read_bytes()).hexdigest()
        path.write_text(json.dumps(pins), encoding="utf-8")
    return pin


def _files(tmp_path, jar_bytes=b"PK\x03\x04 not really a jar"):
    jar = tmp_path / "elsewhere" / "PokeRandoZX.jar"
    jar.parent.mkdir()
    jar.write_bytes(jar_bytes)
    settings, rom = tmp_path / "s.rnqs", tmp_path / "red.gb"
    settings.write_bytes(b"x")
    rom.write_bytes(b"\0" * 16)
    return str(jar), str(settings), str(rom)


def test_the_shipped_allowlist_is_well_formed():
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "data", "upr_jars.json"), encoding="utf-8") as f:
        pins = json.load(f)
    assert pins and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in pins.values())
    assert len(set(pins.values())) == len(pins)


def test_unknown_jar_is_refused_before_popen(tmp_path, allowlist, monkeypatch):
    jar, settings, rom = _files(tmp_path)
    monkeypatch.setattr(upr_pipeline, "identify", lambda _b: {})
    monkeypatch.setattr(subprocess, "Popen", _popen_forbidden)
    with pytest.raises(upr_pipeline.UprPipelineError, match="unknown randomizer build"):
        upr_pipeline.randomize(jar, settings, rom, str(tmp_path / "out.gbc"), java=sys.executable)


def test_a_forged_fork_marker_does_not_make_a_jar_trusted(tmp_path, allowlist, monkeypatch):
    """jar_is_fork is a capability check on a forgeable INI; it never admits a jar."""
    import zipfile
    jar = tmp_path / "forged.jar"
    with zipfile.ZipFile(jar, "w") as zf:
        zf.writestr("com/dabomstew/pkrandom/config/gen1_offsets.ini",
                    "[PureRed (U)]\nSlinkForkRevision=3\n")
    assert upr_pipeline.jar_is_fork(str(jar)) and not upr_pipeline.jar_is_trusted(str(jar))


def test_unc_path_is_refused_without_touching_the_share(allowlist, monkeypatch):
    monkeypatch.setattr(os.path, "realpath", lambda *_a: pytest.fail("resolved a UNC path"))
    monkeypatch.setattr(os.path, "isfile", lambda *_a: pytest.fail("stat'ed a UNC path"))
    for unc in (r"\\attacker\share\PokeRandoZX.jar", "//attacker/share/PokeRandoZX.jar"):
        assert upr_pipeline.jar_sha256(unc) is None
        assert not upr_pipeline.jar_is_trusted(unc)
        assert "not a readable local file" in upr_pipeline.untrusted_jar_message(unc)


def test_trust_is_the_hash_not_the_location(tmp_path, allowlist):
    jar, _, _ = _files(tmp_path)
    assert not upr_pipeline.jar_is_trusted(jar), "out-of-tree, unknown hash"
    allowlist(jar)
    assert upr_pipeline.jar_is_trusted(jar), "same place, pinned hash"
    with open(jar, "ab") as f:
        f.write(b"!")
    assert not upr_pipeline.jar_is_trusted(jar), "one byte changed"
    assert not upr_pipeline.jar_is_trusted(str(tmp_path / "missing.jar"))
    assert not upr_pipeline.jar_is_trusted("")


def test_allowlisted_jar_reaches_java(tmp_path, allowlist, monkeypatch):
    jar, settings, rom = _files(tmp_path)
    allowlist(jar)
    monkeypatch.setattr(upr_pipeline, "identify", lambda _b: {})

    class Launched(Exception):
        pass

    def launched(argv, timeout):
        assert argv[1:3] == ["-jar", os.path.realpath(jar)]
        raise Launched
    monkeypatch.setattr(upr_pipeline, "_run_bounded", launched)
    with pytest.raises(Launched):
        upr_pipeline.randomize(jar, settings, rom, str(tmp_path / "out.gbc"), java=sys.executable)


def test_preflight_reports_trust(tmp_path, allowlist):
    jar, _, _ = _files(tmp_path)
    pre = upr_pipeline.preflight(jar, {})
    assert pre["jar_found"] and pre["jar_trusted"] is False and pre["ok"] is False
    assert "unknown randomizer build" in pre["jar_error"]
    allowlist(jar)
    pre = upr_pipeline.preflight(jar, {})
    assert pre["jar_trusted"] is True and "jar_error" not in pre


def test_cartridges_refuse_an_unknown_jar_before_any_work(tmp_path, allowlist, monkeypatch):
    jar, settings, rom = _files(tmp_path)
    monkeypatch.setattr(upr_pipeline, "describe_rom", lambda *_a, **_k: {"clean": True, "title": ""})
    monkeypatch.setattr(upr_pipeline, "family_of", lambda _s: "gen1_rby")
    monkeypatch.setattr(upr_pipeline, "prepare_pair", lambda *_a: pytest.fail("randomized with an unknown jar"))
    with pytest.raises(cartridges.CartridgeError, match="unknown randomizer build"):
        cartridges.provision(str(tmp_path / "run"), {"a": rom, "b": rom}, companion=False,
                             randomize={"settings_path": settings}, jar=jar)


@pytest.mark.asyncio
async def test_status_route_exposes_trust(manager_client, tmp_path, allowlist):
    jar, _, _ = _files(tmp_path)
    j = await (await manager_client.get("/api/randomizer/status", params={"jar": jar})).json()
    assert j["jar_found"] and j["jar_trusted"] is False and j["ok"] is False


@pytest.mark.asyncio
async def test_upload_refuses_an_unknown_jar_and_keeps_a_pinned_one(manager_client, tmp_path, allowlist, monkeypatch):
    """Refused at upload, not stored: the jar would land at <repo>/PokeRandoZX.jar, the first
    place find_upr_jar looks, and shadow the pinned fork."""
    from server import manager
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(manager, "PROJECT_ROOT", str(root))

    async def upload(data):
        form = aiohttp.FormData()
        form.add_field("file", data, filename="evil.jar", content_type="application/java-archive")
        resp = await manager_client.post("/api/roms", data=form)
        return resp.status, await resp.json()

    status, j = await upload(b"PK evil")
    assert status == 400 and not j["ok"] and "unknown randomizer build" in j["error"]
    assert os.listdir(root) == [], "nothing stored, no .part left"

    good = tmp_path / "good.jar"
    good.write_bytes(b"PK good")
    allowlist(str(good))
    status, j = await upload(b"PK good")
    assert status == 200 and j["ok"] and j["jar_trusted"] is True
    assert j["path"] == str(root / "PokeRandoZX.jar")


def test_build_pin_is_idempotent(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
    import build_upr_fork
    monkeypatch.setattr(build_upr_fork, "ALLOWLIST", tmp_path / "upr_jars.json")
    jar = tmp_path / "PokeRandoZX.jar"
    jar.write_bytes(b"PK")
    digest = hashlib.sha256(b"PK").hexdigest()
    label = build_upr_fork.pin(jar, digest)
    assert build_upr_fork.pin(jar, digest) == label
    assert json.loads((tmp_path / "upr_jars.json").read_text(encoding="utf-8")) == {label: digest}
