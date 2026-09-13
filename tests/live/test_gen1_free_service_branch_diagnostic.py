"""Temporary Y/Y diagnostic: active gate branch cost with no changed RAM bytes.

This is not a release or speed acceptance gate. It generates a modified *copy*
of the checked strict Lua gate in one evidence directory; production and strict
gate source files are never edited. Remove this test by a later revert commit.
"""

import asyncio
import json
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.gen1_run_config import configure_runtime, create_runtime
from server.server import SLinkServer, build_app
from tests.live.test_gen1_bootstrap_launcher import publish
from tests.live.test_gen1_free_service import GATE, ROOT, classify_teardown_errors
from tests.unit.test_gen1_sessions import contract
from tools.run_gb_gate import BIZHAWK_CONFIG, run_gate
from tools.verify_canonical_sources import verify

PHASES = [
    {"name": "quiet_early", "speed": 300, "frames": 600, "active": False},
    {"name": "branch_early", "speed": 300, "frames": 600, "active": True},
    {"name": "branch_late", "speed": 300, "frames": 600, "active": True},
    {"name": "quiet_late", "speed": 300, "frames": 600, "active": False},
]


def diagnostic_lua(source):
    """Preserve the per-frame active branch but remove every test RAM write."""
    guarded = source
    for original in (
        'memory.write_u8(probe.address,probe.replacement,"System Bus")',
        'memory.write_u8(probe.address,probe.original,"System Bus")',
    ):
        assert guarded.count(original) == 1, "strict gate probe site moved"
        guarded = guarded.replace(original, f"if not input.branch_no_write then {original} end")
    old_finish = '''                if not begin_phase(status) then
                    local address=assert(symbols.wPartyDataStart)+403
                    local original=memory.read_u8(address,"System Bus")
                    dirty_probe={schema="rby-inventory-dirty-negative-control-v1",phase="changed",address=address,
                        original=original,replacement=(original+1)%256,before=status.observation_diagnostics.inventory_publications,
                        began_frame=emu.framecount(),deadline=emu.framecount()+300}
                    memory.write_u8(address,dirty_probe.replacement,"System Bus")
                end'''
    new_finish = '''                if not begin_phase(status) then
                    publish("ready",{status=status,held_frame=held_frame,loop_started=loop_started,
                        frame_after=emu.framecount(),clock_after=clock(),frames_driven=frames_driven,
                        screenshots=screenshots,phases=phases,final_source=independent_inventory(),
                        actual_generated_launcher=true})
                    reported=true
                end'''
    assert guarded.count(old_finish) == 1, "strict gate finish site moved"
    guarded = guarded.replace(old_finish, new_finish)
    assert guarded.count('memory.write_u8(address,dirty_probe.replacement,"System Bus")') == 0
    restore = 'memory.write_u8(dirty_probe.address,dirty_probe.original,"System Bus")'
    assert guarded.count(restore) == 1
    guarded = guarded.replace(restore, 'error("diagnostic dirty probe unexpectedly active")')
    return guarded


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="exclusive emulator lane required")
def test_checked_yy_active_branch_without_ram_change():
    assert not verify()["failures"]
    assert "SLINK_CLIENT_STORAGE_ROOT" not in os.environ

    async def scenario():
        directory = Path(tempfile.mkdtemp(prefix="free-service-branch-yy-", dir=ROOT / ".cache"))
        run_id = secrets.token_hex(16)
        client_base = Path(os.environ["LOCALAPPDATA"]) / "SLink" / "clients"
        client_run_root = client_base / run_id
        client_run_root.mkdir(parents=True, exist_ok=False)
        marker = client_run_root / ".slink-live-test-owner"
        marker.write_text(run_id)
        config = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
        config["Rewind"]["Enabled"] = False
        config["FrameSkip"] = 0
        config["AutoMinimizeSkipping"] = False
        config["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]["FrameLength"] = 0
        config_path = directory / "base-config.ini"
        config_path.write_text(json.dumps(config))
        strict_source = (ROOT / f"lua/tests/{GATE}.lua").read_text()
        source = diagnostic_lua(strict_source)
        assert source.count(f'G.start("{GATE}"') == 1
        jobs, listener, web, runtime = [], None, None, None
        turns = []

        async def wait(name, player, seconds):
            path = directory / f"{name}-{player}.json"
            deadline = asyncio.get_running_loop().time() + seconds
            while asyncio.get_running_loop().time() < deadline:
                if path.exists():
                    return json.loads(path.read_text())
                for job in jobs:
                    if job.done():
                        passed, gate_path, log = await job
                        raise AssertionError(f"emulator exited before {name}: {passed} {gate_path}\n{log}")
                await asyncio.sleep(0.02)
            raise AssertionError(f"launcher timed out waiting for {name}-{player}")

        try:
            for player in ("a", "b"):
                fixture = directory / f"blank-{player}.SaveRAM"
                fixture.write_bytes(b"\xff" * 0x8000)
                script = directory / f"gate-{player}.lua"
                script.write_text(source.replace(
                    f'G.start("{GATE}"', f'G.start("{directory.name.replace("-", "_")}_{player}"'
                ))
                spec = directory / f"input-{player}.json"
                publish(spec, {"directory": directory.as_posix(), "run_id": run_id, "player": player,
                               "launcher": (directory / f"download-{player}.lua").as_posix(),
                               "cold_boot": True, "branch_no_write": True, "phases": PHASES})
                jobs.append(asyncio.create_task(asyncio.to_thread(
                    run_gate, script.relative_to(ROOT).as_posix(), rom_key="yellow", timeout=420, quiet=True,
                    config_base=str(config_path), fixture_override=str(fixture),
                    extra_env={"SLINK_LAUNCHER_TEST_INPUT": str(spec)})))
            observed = {player: await wait("observed", player, 55) for player in ("a", "b")}
            assert all(row["cold_boot"] is True for row in observed.values())
            runtime = create_runtime(directory, contract("yellow", "yellow"), run_id=run_id, free_service=True)
            original_process = runtime.process

            def measured_process(message, owner):
                began = time.perf_counter()
                failure = None
                try:
                    return original_process(message, owner)
                except Exception as error:
                    failure = f"{type(error).__name__}: {error}"
                    raise
                finally:
                    turns.append({"event": message.get("event"), "player": message.get("player"),
                                  "began": began, "finished": time.perf_counter(), "error": failure})

            runtime.process = measured_process
            configure_runtime(runtime)
            server = SLinkServer(data_dir=str(directory), gen1_runtime=runtime)
            listener = await asyncio.start_server(server.handle_client, "127.0.0.1", 0, limit=4 * 1024 * 1024)
            server._tcp_port = listener.sockets[0].getsockname()[1]
            web = TestClient(TestServer(build_app(server)))
            await web.start_server()
            for player in ("a", "b"):
                response = await web.get("/launcher/" + player)
                assert response.status == 200
                (directory / f"download-{player}.lua").write_text(await response.text())
            publish(directory / "go.json", {"ready": True})
            ready = {player: await wait("ready", player, 400) for player in ("a", "b")}
            saves = runtime.journal.snapshot().state["components"].get("gen1-initial-save", {})
            assert set(saves) == {"a", "b"} and all(row["receipt_operation"] for row in saves.values())
            finish_requested_at = time.perf_counter()
            publish(directory / "finish.json", {"done": True})
            for job in jobs:
                passed, gate_path, log = await job
                assert passed, f"{gate_path}\n{log[-4000:]}"
            await asyncio.sleep(0.1)
            teardown_errors = classify_teardown_errors(turns, finish_requested_at)
            assert not [row for row in turns if row["error"] and row["began"] < finish_requested_at]
            assert not [row for row in turns if row["event"] == "observation"]
            results = {"schema": "rby-active-branch-no-write-diagnostic-v1", "directory": directory.name,
                       "teardown_control_errors": len(teardown_errors), "players": {}}
            for player, row in ready.items():
                status = row["status"]
                assert row["actual_generated_launcher"] and status["free_service"]
                assert status["phase"] == "free_service" and status["runtime"]["connected"]
                assert not status["runtime"]["failed"] and not status["host"]["held"]
                assert status["runtime"]["pending_events"] == status["runtime"]["pending_commands"] == 0
                assert [phase["name"] for phase in row["phases"]] == [phase["name"] for phase in PHASES]
                windows = []
                for phase in row["phases"]:
                    assert len(phase["windows"]) == 1 and len(phase["probes"]) == int(phase["active"])
                    assert phase["frames"] == phase["windows"][0]["frames"] == 600
                    assert phase["diagnostics"]["after"]["inventory_publications"] == phase["diagnostics"]["before"]["inventory_publications"]
                    assert phase["windows"][0]["pending_events"] == 0
                    if phase["active"]:
                        probe = phase["probes"][0]
                        assert probe["injected"] and probe["restored"]
                        assert probe["original"] != probe["replacement"]
                        assert int(row["final_source"]["fields"]["party"][806:808], 16) == probe["original"]
                    windows.append({"name": phase["name"], "fps": phase["windows"][0]["fps"],
                                    "seconds": phase["windows"][0]["seconds"]})
                journal_path = Path(status["journal_path"])
                assert journal_path.resolve() == (client_run_root / player / "journal.json").resolve()
                local = json.loads(journal_path.read_text())["document"]["payload"]
                assert local["outbox"] == local["inbox"] == []
                results["players"][player] = windows
            publish(directory / "server-turns.json", {"turns": turns,
                                                      "finish_requested_at": finish_requested_at})
            publish(directory / "branch-diagnostic.json", results)
        finally:
            if any(not job.done() for job in jobs):
                publish(directory / "abort.json", {"reason": "branch diagnostic ended"})
            pending = set()
            if jobs:
                _, pending = await asyncio.wait(jobs, timeout=15)
            if web is not None:
                await web.close()
            if listener is not None:
                listener.close()
                await listener.wait_closed()
            if runtime is not None:
                runtime.close()
            assert not pending, "diagnostic emulator remains active"
            assert (not client_run_root.is_symlink() and not client_run_root.is_junction()
                    and client_run_root.resolve().parent == client_base.resolve()
                    and marker.read_text() == run_id), "diagnostic client journal ownership changed"
            shutil.rmtree(client_run_root)

    asyncio.run(scenario())
