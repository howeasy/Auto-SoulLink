"""Prepared-run selection, read-only journals and generation-neutral launch bytes."""

import asyncio
import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.gen1_launcher import FILES, configuration, launcher
from server.gen1_run_config import FILENAME, configure_runtime, open_runtime, read_configuration
from server.journal_reader import read_journal
from server.protocol import ProtocolError
from server.protocol_journal import JournalError
from server.runtime_boundary import read_saved_run
from server.runtime_launcher import file_bundle
from server.server import SLinkServer, build_app
from tests.unit.test_gen1_runtime_server import RUN_ID, RuntimeCase


@pytest.fixture
def prepared(tmp_path):
    value = RuntimeCase(tmp_path)
    yield value
    value.close()


def test_launcher_binds_run_player_cartridge_mode_and_every_client_file(prepared):
    config = configuration(prepared.runtime, "b")
    assert config["run_id"] == RUN_ID and config["player"] == "b"
    assert config["mode"] == "held_service" and config["cartridge"]["variant"] == "yellow"
    assert {row["path"] for row in config["files"]} == set(FILES)
    source = launcher(
        prepared.runtime,
        "b",
        "::1",
        54321,
        name='Run\n"end" @FILES@ @ROOT@',
        root_hint='C:/A "quoted" root/',
    )
    assert "SLINK_RUNTIME_LAUNCH_JSON=" in source
    assert "File.ReadAllBytes" in source and source.index("hash:ComputeHash") < source.index(
        "dofile(root"
    )
    from lupa import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().source = source
    assert lua.eval("load(source)") is not None


def test_bundle_hashes_are_cross_checkout_stable_but_do_not_hide_content_drift(tmp_path):
    script = tmp_path / "sample.lua"
    script.write_bytes(b"return 1\r\n")
    first = file_bundle(tmp_path, ["sample.lua"])
    script.write_bytes(b"return 1\n")
    assert file_bundle(tmp_path, ["sample.lua"]) == first
    script.write_bytes(b"return 2\n")
    assert file_bundle(tmp_path, ["sample.lua"]) != first
    with pytest.raises(ValueError):
        file_bundle(tmp_path, ["../elsewhere.lua"])


def test_wrong_run_launcher_cannot_admit_even_with_identical_cartridge_and_save(prepared):
    before = prepared.runtime.journal.snapshot()
    with pytest.raises(ProtocolError, match="different run"):
        prepared.runtime.process(prepared.hello("a", run_id="f" * 32), object())
    assert not prepared.runtime.gate.sessions and prepared.runtime.journal.snapshot() == before


def test_prepared_configuration_reopens_only_its_existing_journal(prepared):
    cfg = configure_runtime(prepared.runtime)
    assert read_configuration(prepared.path) == cfg
    before = prepared.runtime.journal.snapshot()
    assert read_journal(prepared.runtime.journal.path, run_id=RUN_ID).snapshot == before
    assert prepared.runtime.journal.snapshot() == before
    prepared.close()
    reopened = open_runtime(prepared.path)
    assert reopened.rule_state().to_document() == prepared.rules["core"]
    assert reopened.state().barrier.ticket() is None
    reopened.close()
    prepared.open()


def test_stopped_reader_returns_committed_rules_without_opening_a_runtime(prepared):
    configure_runtime(prepared.runtime)
    path = prepared.runtime.journal.path
    expected = prepared.runtime.journal.snapshot()
    prepared.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = read_saved_run(prepared.path)
    assert result["available"] and result["source"] == "protocol_journal"
    assert (
        result["committed_revision"] == expected.revision
        and result["document"] == expected.state["rules"]["core"]
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    prepared.open()


@pytest.mark.parametrize("kind", ["missing", "empty", "foreign", "corrupt"])
def test_reader_never_initializes_or_repairs_invalid_input(tmp_path, kind):
    path = tmp_path / "invalid.sqlite3"
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "foreign":
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE other(value)")
        db.close()
    elif kind == "corrupt":
        path.write_bytes(b"not a sqlite database")
    before = path.read_bytes() if path.exists() else None
    with pytest.raises((JournalError, sqlite3.Error)):
        read_journal(path)
    assert (path.read_bytes() if path.exists() else None) == before


def test_prepared_config_cannot_escape_or_silently_fall_back_to_links_json(prepared):
    config = configure_runtime(prepared.runtime)
    config["journal"] = "../other.sqlite3"
    (prepared.path / FILENAME).write_text(json.dumps(config))
    (prepared.path / "links.json").write_text(json.dumps(prepared.rules["core"]))
    assert read_saved_run(prepared.path)["reason_code"] == "durable_saved_state_invalid"
    with pytest.raises(JournalError):
        open_runtime(prepared.path)


def test_http_download_selects_held_entry_and_keeps_mutations_closed(prepared):
    async def scenario():
        srv = SLinkServer(
            data_dir=str(prepared.path), gen1_runtime=prepared.runtime, tcp_port=54321
        )
        client = TestClient(TestServer(build_app(srv)))
        await client.start_server()
        try:
            before = prepared.runtime.journal.snapshot()
            response = await client.get("/launcher/a")
            assert response.status == 200 and "_held.lua" in response.headers["Content-Disposition"]
            source = await response.text()
            assert RUN_ID in source and "held_service" in source
            assert (await client.post("/api/reset", json={})).status == 409
            assert prepared.runtime.journal.snapshot() == before
        finally:
            await client.close()

    asyncio.run(scenario())


def test_manager_selects_only_prepared_run_launcher_and_refuses_corrupt_binding(
    prepared, monkeypatch
):
    from server import manager

    prepared.runtime.initial_observations = True
    prepared.runtime.free_service = True
    configure_runtime(prepared.runtime)
    run_name = prepared.path.name
    monkeypatch.setattr(manager, "MANAGER_DIR", str(prepared.path.parent))
    monkeypatch.setattr(
        manager,
        "_load_registry",
        lambda: [{"run_id": run_name, "name": "Prepared", "tcp_port": 54321}],
    )
    request = SimpleNamespace(match_info={"run_id": run_name, "player": "b"}, host="[::1]:8090")
    instance = manager.RunManager("127.0.0.1")
    response = asyncio.run(instance.handle_launcher(request))
    assert response.status == 200 and "_free.lua" in response.headers["Content-Disposition"]
    assert RUN_ID in response.text and "free_service" in response.text
    config = json.loads((prepared.path / FILENAME).read_text())
    config["run_id"] = "f" * 32
    (prepared.path / FILENAME).write_text(json.dumps(config))
    assert asyncio.run(instance.handle_launcher(request)).status == 409


def test_actual_server_cli_selects_prepared_journal_without_creating_legacy_links(prepared):
    configure_runtime(prepared.runtime)
    prepared.close()
    root = Path(__file__).resolve().parents[2]
    ports = []
    for _ in range(2):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            ports.append(probe.getsockname()[1])
    output = prepared.path / "child-server.log"
    with output.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "server.server",
                "--host",
                "127.0.0.1",
                "--port",
                str(ports[0]),
                "--http-port",
                str(ports[1]),
                "--data-dir",
                str(prepared.path),
            ],
            cwd=root,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail(output.read_text(errors="replace"))
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{ports[1]}/launcher/a", timeout=0.5
                    ) as response:
                        content = response.read().decode()
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                pytest.fail("prepared CLI server did not become available")
            assert RUN_ID in content and "held_service" in content
            assert not (prepared.path / "links.json").exists()
        finally:
            process.terminate()
            process.wait(timeout=10)
    prepared.open()
