"""Checked Manager-selected native free service, fresh New Game only.

This is a bounded bedroom smoke, not a trade or CONTINUE qualification. Its
early hold is before the first frame *after launcher load*, not emulator power-on:
the gate's observed/go handshake and intro frames precede that load. It uses
the Manager's actual POST and launcher/bundle HTTP handlers, the exact run-local
canonical companion files, two isolated BizHawk SaveRAM directories, and the
production LocalAppData client-journal location. The Lua gate only supplies
normal New Game inputs and read-only observations except for the existing
changed-inventory performance probe, which it restores within each window.
"""

import asyncio
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server import manager
from server.bizhawk_launch import prepare
from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_inventory_observation import COMPONENT as INVENTORY_COMPONENT, record_key
from server.gen1_run_config import open_runtime
from server.protocol import digest
from server.server import SLinkServer, build_app
from tests.live.test_gen1_bootstrap_launcher import publish
from tests.live.test_gen1_free_service import (
    ACTIVE_THREE_X_MIN_FPS,
    MIN_FRACTION,
    TARGET_FPS,
    classify_teardown_errors,
    journal_events,
)
from tools.run_gb_gate import BIZHAWK_CONFIG, run_gate
from tools.verify_canonical_sources import verify

ROOT = Path(__file__).resolve().parents[2]
GATE = "test_gen1_native_selected_fresh_gate"
PHASES = (
    {"name": "one_x_active", "speed": 100, "frames": 600, "active": True},
    {"name": "three_x_active", "speed": 300, "frames": 1800, "active": True},
    {"name": "one_x_quiet", "speed": 100, "frames": 600, "active": False},
    {"name": "three_x_quiet", "speed": 300, "frames": 600, "active": False},
)


def clean_rom(variant):
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    return ROOT / lock["clean_roms"][f"poke{variant}"]["filename"]


def assert_native_startup_order(result):
    """Early owner claim permits clean boot frames; only the later read pins a frame."""
    early = result["early_claim_frame"]
    first = result["first_client_frame"]
    held = result["held_frame"]
    read_frame = result["status"]["native_reattach"]["read"]["frame"]
    assert all(type(value) is int for value in (early, first, held, read_frame))
    assert result["frames_driven"] > 0 and early <= first < held <= read_frame


def test_native_startup_order_model_allows_clean_frames_but_pins_the_later_read():
    """No-emulator regression for early claim -> clean New Game -> held read ordering."""
    case = {"early_claim_frame": 120, "first_client_frame": 120, "held_frame": 800,
            "frames_driven": 680, "status": {"native_reattach": {"read": {"frame": 800}}}}
    assert_native_startup_order(case)
    with pytest.raises(AssertionError):
        assert_native_startup_order(case | {"held_frame": 120})
    with pytest.raises(AssertionError):
        assert_native_startup_order(case | {"status": {"native_reattach": {"read": {"frame": 799}}}})


async def selected_manager(directory, variants, monkeypatch):
    """Exercise the real Manager HTTP handlers without a background server process."""
    manager_dir = directory / "manager"
    manager_dir.mkdir()
    monkeypatch.setattr(manager, "MANAGER_DIR", str(manager_dir))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(manager_dir / "registry.json"))
    app = web.Application()
    owner = manager.RunManager("127.0.0.1")
    app.router.add_post("/api/runs/gen1", owner.handle_create_gen1)
    app.router.add_get("/api/runs/{run_id}/launcher/{player}", owner.handle_launcher)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.post("/api/runs/gen1", json={
            "name": "Checked fresh native pair", "rom_a": str(clean_rom(variants[0])),
            "rom_b": str(clean_rom(variants[1])), "rules": {}, "start": False, "native": True,
        })
        body = await response.json()
        assert response.status == 200 and body["ok"], body
        assert body["native_trade"] is True and body["runtime_mode"] == "free_service"
        run = body["run"]
        assert run["native_trade"] is True and run["status"] == "stopped"
        assert manager._load_registry() == [run]
        run_directory = manager_dir / run["run_id"]
        assert run_directory.resolve().parent == manager_dir.resolve()
        runtime = open_runtime(run_directory)
        try:
            assert runtime.native_trade is True and runtime.free_service is True
            assert runtime.prepared_cartridges.provenance == "canonical_companion"
            session_id = runtime.journal.run_id
            assert len(session_id) == 32 and session_id != run["run_id"]
            assert set(runtime.contract["players"]) == {"a", "b"}
        finally:
            runtime.close()
        return client, run, run_directory, session_id
    except BaseException:
        await client.close()
        raise


async def checked_downloads(client, run, run_directory, session_id, variants, base_config):
    """Verify the Manager bundle and its private-host launch inputs without launching it."""
    output = {}
    for player, variant in zip(("a", "b"), variants, strict=True):
        endpoint = f"/api/runs/{run['run_id']}/launcher/{player}"
        plain = await client.get(endpoint)
        assert plain.status == 200
        launcher = await plain.text()
        package = await client.get(endpoint + "?bundle=1")
        assert package.status == 200
        with zipfile.ZipFile(io.BytesIO(await package.read())) as archive:
            assert set(archive.namelist()) == {"launch.json", "launcher.lua", "README.txt"}
            manifest = json.loads(archive.read("launch.json"))
            assert archive.read("launcher.lua") == launcher.encode()
        expected = companion_profiles()[variant]
        rom = run_directory / "prepared" / "final" / player / f"slink_{variant}.gb"
        assert rom.is_file() and rom.resolve().is_relative_to(run_directory.resolve())
        data = rom.read_bytes()
        assert hashlib.sha1(data).hexdigest() == expected["final_rom_sha1"]
        assert hashlib.sha256(data).hexdigest() == expected["rom_sha256"]
        assert manifest["run_id"] == session_id and manifest["player"] == player
        assert manifest["rom_sha1"] == expected["final_rom_sha1"]
        assert manifest["launcher_sha256"] == hashlib.sha256(launcher.encode()).hexdigest()
        script = run_directory / f"download-{player}.lua"
        script.write_text(launcher)
        plan = prepare(run_directory / "host-preflight", manifest, rom=rom, launcher=script,
                       base_config=base_config)
        private_saves = Path(plan["save_directory"])
        assert private_saves.resolve().is_relative_to((run_directory / "host-preflight").resolve())
        assert plan["environment"]["SLINK_SAVERAM_DIRECTORY"] == str(private_saves)
        assert Path(plan["cwd"], "game.gb").read_bytes() == data
        output[player] = {"rom": rom, "sha256": hashlib.sha256(data).hexdigest(),
                          "launcher": script, "bundle": manifest, "host_preflight": plan}
    return output


@pytest.mark.asyncio
async def test_manager_native_bundle_preflight_uses_the_exact_run_local_pair(tmp_path, monkeypatch):
    """Offline, old-code-failing selected-path assertion: no emulator is started."""
    if not clean_rom("yellow").is_file():
        pytest.skip("legal clean Yellow cartridge is unavailable")
    client, run, run_directory, session_id = await selected_manager(tmp_path, ("yellow", "yellow"), monkeypatch)
    try:
        await checked_downloads(client, run, run_directory, session_id, ("yellow", "yellow"), BIZHAWK_CONFIG)
    finally:
        await client.close()


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="exclusive live emulator lane required")
@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue")])
def test_manager_selected_native_pair_free_runs_fresh_bedroom(variants, monkeypatch):
    assert not verify()["failures"]
    assert "SLINK_CLIENT_STORAGE_ROOT" not in os.environ, "use the production LocalAppData journal path"

    async def scenario():
        directory = Path(tempfile.mkdtemp(prefix="native-selected-fresh-", dir=ROOT / ".cache")).resolve()
        private = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
        private["Rewind"]["Enabled"] = False
        private["FrameSkip"] = 0
        private["AutoMinimizeSkipping"] = False
        private["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]["FrameLength"] = 0
        base_config = directory / "base-config.ini"
        base_config.write_text(json.dumps(private))
        client = None
        runtime = None
        listener = None
        web_client = None
        jobs = []
        client_run_root = None
        marker = None
        turns = []

        async def wait(name, player, seconds):
            file = directory / f"{name}-{player}.json"
            deadline = asyncio.get_running_loop().time() + seconds
            while asyncio.get_running_loop().time() < deadline:
                if file.exists():
                    return json.loads(file.read_text())
                for job in jobs:
                    if job.done():
                        passed, path, log = await job
                        raise AssertionError(f"emulator exited before {name}: {passed} {path}\n{log}")
                await asyncio.sleep(0.02)
            raise AssertionError(f"native-selected fresh gate timed out waiting for {name}-{player}")

        try:
            client, run, run_directory, session_id = await selected_manager(directory, variants, monkeypatch)
            runtime = open_runtime(run_directory)
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
                                  "began": began, "error": failure})

            runtime.process = measured_process
            srv = SLinkServer(data_dir=str(run_directory), gen1_runtime=runtime)
            listener = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0, limit=4 * 1024 * 1024)
            srv._tcp_port = listener.sockets[0].getsockname()[1]
            records = manager._load_registry()
            assert len(records) == 1 and records[0]["run_id"] == run["run_id"]
            records[0]["tcp_port"] = srv._tcp_port
            manager._save_registry(records)
            web_client = TestClient(TestServer(build_app(srv)))
            await web_client.start_server()
            # The Manager download is regenerated with the listener's actual port.
            downloaded = await checked_downloads(client, records[0], run_directory, session_id, variants, base_config)

            client_base = Path(os.environ["LOCALAPPDATA"]) / "SLink" / "clients"
            client_run_root = client_base / session_id
            client_run_root.mkdir(parents=True, exist_ok=False)
            marker = client_run_root / ".slink-native-selected-test-owner"
            marker.write_text(session_id)
            source = (ROOT / f"lua/tests/{GATE}.lua").read_text()
            for player, variant in zip(("a", "b"), variants, strict=True):
                fixture = directory / f"blank-{player}.SaveRAM"
                fixture.write_bytes(b"\xff" * 0x8000)
                script = directory / f"gate-{player}.lua"
                script.write_text(source.replace(f'G.start("{GATE}"',
                    f'G.start("{directory.name.replace("-", "_")}_{player}"'))
                spec = directory / f"input-{player}.json"
                publish(spec, {"directory": directory.as_posix(), "player": player,
                               "launcher": str(downloaded[player]["launcher"]),
                               "phases": PHASES, "rom_sha1": downloaded[player]["bundle"]["rom_sha1"]})
                jobs.append(asyncio.create_task(asyncio.to_thread(
                    run_gate, script.relative_to(ROOT).as_posix(), rom_key=variant + "_companion",
                    timeout=480, quiet=True, config_base=str(base_config), fixture_override=str(fixture),
                    cartridge_override={"path": str(downloaded[player]["rom"]),
                                        "sha256": downloaded[player]["sha256"],
                                        "saveram_name": "candidate.SaveRAM"},
                    extra_env={"SLINK_LAUNCHER_TEST_INPUT": str(spec)},
                )))
            observed = {player: await wait("observed", player, 55) for player in ("a", "b")}
            for player in ("a", "b"):
                row = observed[player]
                assert row["rom_sha1"] == downloaded[player]["bundle"]["rom_sha1"]
                save = Path(row["saveram_path"])
                assert Path(row["saveram_directory"]).resolve() == save.resolve().parent
                assert save.name == "candidate.SaveRAM"
                assert save.resolve().parent.name == "SaveRAM"
                assert save.resolve().parent.parent.name.startswith("gb-gate-")
                assert save.read_bytes() == b"\xff" * 0x8000
            publish(directory / "go.json", {"ready": True})
            ready = {player: await wait("ready", player, 400) for player in ("a", "b")}
            document = runtime.state().document()
            assert document["active_trade"] is None
            assert not document["components"].get("gen1-trade", {}).get("transactions", {})
            assert set(document["components"]["gen1-native-reattach"]) == {"a", "b"}
            assert set(document["components"]["gen1-initial-observations"]) == {"a", "b"}
            assert set(document["components"]["gen1-new-game-bootstrap"]) == {"a", "b"}
            saves = document["components"]["gen1-initial-save"]
            assert set(saves) == {"a", "b"}
            assert all(saves[player]["receipt_operation"] for player in ("a", "b"))
            assert runtime.service_current()
            for player, result in ready.items():
                status = result["status"]
                assert status["free_service"] and status["observation_loop"]
                assert status["phase"] == "free_service" and not status["runtime"]["failed"]
                assert status["runtime"]["connected"] and status["runtime"]["session_state"] == "admitted"
                assert status["host"]["held"] is False and status["host"]["owner_id"] == status["context"]["physical_instance"]
                assert status["native"] is not None
                assert status["native_host"].get("failed") is None and status["native_host"]["armed"] is False
                reattach = status["native_reattach"]
                assert reattach["read"]["host"]["held"] is True
                assert_native_startup_order(result)
                assert reattach["server"]["verdict"] == "released"
                assert reattach["server"]["read_digest"] == reattach["read_digest"]
                entry = document["components"]["gen1-native-reattach"][player]
                assert entry["verdict"] == "released" and entry["class"] == "clean"
                assert entry["read_digest"] == reattach["read_digest"] and entry["frame"] == reattach["read"]["frame"]
                assert result["loop_started"]["frame"] >= result["held_frame"]
                assert result["frames_driven"] > 0
                assert result["frame_after"] - result["loop_started"]["frame"] >= sum(p["frames"] for p in PHASES)
                assert [phase["name"] for phase in result["phases"]] == [phase["name"] for phase in PHASES]
                for phase, planned in zip(result["phases"], PHASES, strict=True):
                    floor = (ACTIVE_THREE_X_MIN_FPS if planned["speed"] == 300 and planned["active"]
                             else TARGET_FPS * planned["speed"] / 100 * MIN_FRACTION)
                    assert phase["active"] is planned["active"] and phase["frames"] >= planned["frames"]
                    assert phase["fps"] >= floor, phase
                    assert len(phase["windows"]) == planned["frames"] // 600
                    assert all(window["fps"] >= floor and window["pending_events"] == 0
                               for window in phase["windows"]), phase
                    assert all(probe["injected"] and probe["restored"] for probe in phase["probes"])
                assert status["runtime"]["pending_events"] == 0
            assert all(turn["error"] is None for turn in turns), "server error before client finish"
            finish_requested_at = time.perf_counter()
            publish(directory / "finish.json", {"done": True})
            for job in jobs:
                passed, path, log = await job
                assert passed, f"{path}\n{log[-4000:]}"
            classify_teardown_errors(turns, finish_requested_at)
            rows, snapshot = journal_events(run_directory / "runtime.sqlite3")
            for player in ("a", "b"):
                events = [row for row in rows if row[0] == player]
                reattach_events = [row for row in events if row[2].get("event") == "native_reattach"]
                assert len(reattach_events) == 1 and reattach_events[0][3]["ack"] == "ACK"
                assert reattach_events[0][3]["native_reattach"]["verdict"] == "released"
                observed_rows = [row for row in events if row[2].get("event") == "observation"]
                observations = [row[2] for row in observed_rows]
                assert all(row[3]["ack"] == "ACK" and row[3]["ordinary_execution"] is False
                           for row in observed_rows)
                assert all("inventory_transition_digest" not in row[3] and not row[3].get("inventory_deferred")
                           for row in observed_rows if row[2]["inventory"] is None)
                assert [row["sequence"] for row in observations] == list(range(1, len(observations) + 1))
                points_and_results = [row for row in observed_rows if row[2]["inventory"] is not None]
                history = runtime.journal.record_history(INVENTORY_COMPONENT, record_key(player), limit=128)
                assert len(history) == len(points_and_results)
                for committed, row in zip(history, points_and_results, strict=True):
                    assert committed.revision == row[1]
                    assert committed.value["observation"] == row[2]["inventory"]
                    assert row[3]["inventory_transition_digest"] == digest(committed.value)
                    assert not row[3].get("inventory_deferred")
                for phase in ready[player]["phases"]:
                    for index, window in enumerate(phase["windows"]):
                        points = [row for row in observations if window["first_frame"] < row["frame"] <= window["last_frame"]
                                  and row["inventory"] is not None]
                        if phase["active"]:
                            assert len(points) == 2, (player, phase["name"], index, points)
                            probe = phase["probes"][index]
                            assert (window["first_frame"] <= probe["injected_frame"]
                                    < probe["restored_frame"] <= window["last_frame"])
                            assert (probe["injected_frame"] < points[0]["frame"] <= probe["restored_frame"]
                                    < points[1]["frame"] <= window["last_frame"])
                            assert [int(point["inventory"]["source"]["fields"]["party"][806:808], 16)
                                    for point in points] == [probe["replacement"], probe["original"]]
                        else:
                            assert not points
                # The bedroom is pre-starter: source-verified heartbeat inventory
                # points carry a nullable native checkpoint, never a fabricated
                # party that could authorize a trade.
                assert all("native_checkpoint" in point and point["native_checkpoint"] is None
                           for point in observations if point["inventory"] is not None)
                assert int(ready[player]["final_source"]["fields"]["party"][806:808], 16) == ready[player]["phases"][1]["probes"][-1]["original"]
                journal_path = Path(ready[player]["status"]["journal_path"])
                assert journal_path.resolve() == (client_run_root / player / "journal.json").resolve()
                local = json.loads(journal_path.read_text())["document"]["payload"]
                assert local["outbox"] == [] and local["inbox"] == []
                assert not runtime.journal.pending_ids(player)
                assert (directory / f"blank-{player}.SaveRAM").read_bytes() == b"\xff" * 0x8000
            assert snapshot["components"]["gen1-native-reattach"] == document["components"]["gen1-native-reattach"]
            assert not document["identities"]["members"] and not document["rules"]["core"]["links"]
            publish(directory / "summary.json", {"schema": "rby-native-selected-fresh-smoke-v1",
                "launch_boundary": "hold before first post-launcher frame; observed/go and intro preceded launcher load",
                "manager_id": run["run_id"], "session_id": session_id, "variants": variants,
                "players": {player: {"phases": ready[player]["phases"], "held_frame": ready[player]["held_frame"],
                                      "loop_started": ready[player]["loop_started"]} for player in ("a", "b")}})
        except BaseException as error:
            publish(directory / "harness-error.json", {"type": type(error).__name__, "reason": str(error)[:1000]})
            raise
        finally:
            if any(not job.done() for job in jobs):
                publish(directory / "abort.json", {"reason": "paired selected-native fresh gate finished or failed"})
            pending = set()
            if jobs:
                _, pending = await asyncio.wait(jobs, timeout=15)
            if web_client is not None:
                await web_client.close()
            if listener is not None:
                listener.close()
                await listener.wait_closed()
            if runtime is not None:
                runtime.close()
            if client is not None:
                await client.close()
            assert not pending, "test clients still running; preserve their journal directory for diagnosis"
            if client_run_root is not None and marker is not None:
                client_base = Path(os.environ["LOCALAPPDATA"]) / "SLink" / "clients"
                assert (not client_run_root.is_symlink() and not client_run_root.is_junction()
                        and client_run_root.resolve().parent == client_base.resolve()
                        and marker.read_text() == client_run_root.name == session_id), "client journal ownership changed"
                shutil.rmtree(client_run_root)

    asyncio.run(scenario())
