"""Actual HTTP launcher + server: the free-running observation loop runs the bedroom at cartridge rate.

Proposals P4 (lua/gen1_observation_loop.lua) and P10 (server/gen1_observation_runtime.py plus
the free_service wiring). Cold boot with a blank SaveRAM and normal menu inputs exactly as the
bootstrap launcher test; the client then releases its hold and the loop publishes one
``observation`` batch per engine signal, source receipt or 30-frame heartbeat while the core
free-runs. Frames and seconds come from two clocks: the emulator (per phase, from the gate)
and the server journal commits (first to last observation). The heartbeat inventory is
compared with the credit-path run behind ORDINARY_FRAME_TURNOVER_PROFILE.md.
"""

import asyncio
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.gen1_initial_observation import inventory as decode_inventory
from server.gen1_inventory_observation import COMPONENT as INVENTORY
from server.gen1_observation_runtime import COMPONENT as PROGRESS
from server.gen1_run_config import configure_runtime, create_runtime, open_runtime
from server.server import SLinkServer, build_app
from tests.live.test_gen1_bootstrap_launcher import publish
from tests.unit.test_gen1_sessions import contract
from tools.run_gb_gate import BIZHAWK_CONFIG, run_gate
from tools.verify_canonical_sources import verify

ROOT = Path(__file__).resolve().parents[2]
GATE = "test_gen1_free_service_gate"
# Production cadence: a ten-second 1x window and the same wall duration at 3x.
PHASES = [{"name": "one_x", "speed": 100, "frames": 600},
          {"name": "three_x", "speed": 300, "frames": 1800}]
TARGET_FPS = 59.727500569606
MIN_FRACTION = 0.99
# The credit-loop run behind ORDINARY_FRAME_TURNOVER_PROFILE.md (refresh 2026-09-10).
CREDIT_RUN = Path(os.environ.get("SLINK_CREDIT_RUN", ROOT / ".cache/gen1-bootstrap-launcher-ehtld3qv"))
CREDIT_LOOP = {"source": "docs/gen1_reference/ORDINARY_FRAME_TURNOVER_PROFILE.md, refresh 2026-09-10",
               "a": {"frames": 321, "seconds": 10.339, "end_to_end_fps": 31.05, "grants": 8, "persist_ms_per_step": 5.9},
               "b": {"frames": 328, "seconds": 10.497, "end_to_end_fps": 31.25, "grants": 8, "persist_ms_per_step": 5.9}}
pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required"
    ),
]


def journal_events(journal):
    """Committed events of a journal, in commit order: (player, revision, request, result), plus the snapshot."""
    staging = Path(tempfile.mkdtemp(prefix="journal-read-"))
    for name in ("runtime.sqlite3", "runtime.sqlite3-wal", "runtime.sqlite3-shm"):
        if (journal.parent / name).exists():
            shutil.copy(journal.parent / name, staging / name)
    db = sqlite3.connect(staging / "runtime.sqlite3")
    try:
        rows = [(player, revision, json.loads(request), json.loads(result)) for player, revision, request, result
                in db.execute("SELECT player, revision, request, result FROM events ORDER BY revision")]
        snapshot = json.loads(db.execute("SELECT body FROM snapshot WHERE singleton=1").fetchone()[0])
    finally:
        db.close()
    return rows, snapshot


def strip_digests(transition):
    return {key: value for key, value in transition.items() if not key.endswith("_digest")}


def credit_reference(player):
    """What the credit path recorded on the same route: last checkpoint bytes, receipt kinds, transition."""
    journal = CREDIT_RUN / "runtime.sqlite3"
    if not journal.exists():
        return None
    rows, snapshot = journal_events(journal)
    bundles = [row[2]["bundle"] for row in rows if row[0] == player and row[2].get("event") == "frame_complete"]
    checkpoints = [bundle["inventory"] for bundle in bundles if bundle["inventory"] is not None]
    last = checkpoints[-1]
    return {"directory": CREDIT_RUN.name, "checkpoints": len(checkpoints), "frame": last["frame"],
            "party": last["source"]["fields"]["party"], "box": last["source"]["fields"]["box"],
            "name": last["source"]["fields"]["name"], "save_status": last["source"]["save_status"],
            "acquisition_kinds": [item["kind"] for bundle in bundles for item in bundle["acquisitions"]],
            "transition": strip_digests(snapshot["components"][INVENTORY][player]["transition"])}


def fps_between(commits):
    if len(commits) < 2:
        return None
    seconds = commits[-1]["finished"] - commits[0]["finished"]
    return {"frames": commits[-1]["frame"] - commits[0]["frame"], "seconds": seconds,
            "fps": (commits[-1]["frame"] - commits[0]["frame"]) / seconds if seconds > 0 else None,
            "first_frame": commits[0]["frame"], "last_frame": commits[-1]["frame"], "events": len(commits)}


def run_free_pair(variants):
    assert not verify()["failures"]

    async def scenario():
        directory = Path(tempfile.mkdtemp(prefix=f"free-service-{variants[0][0]}{variants[1][0]}-", dir=ROOT / ".cache"))
        run_id = secrets.token_hex(16)
        players = dict(zip(("a", "b"), variants, strict=True))
        private = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
        private["Rewind"]["Enabled"] = False
        private["FrameSkip"] = 0
        private["AutoMinimizeSkipping"] = False
        private["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]["FrameLength"] = 0
        config = directory / "base-config.ini"
        config.write_text(json.dumps(private))
        source = (ROOT / f"lua/tests/{GATE}.lua").read_text()
        jobs, listener, web = [], None, None
        runtime = None
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
            raise AssertionError(f"launcher test timed out waiting for {name}-{player}")

        try:
            for p, variant in players.items():
                fixture = directory / f"blank-{p}.SaveRAM"
                fixture.write_bytes(b"\xff" * 0x8000)
                script = directory / f"gate-{p}.lua"
                script.write_text(
                    source.replace(f'G.start("{GATE}"', f'G.start("{directory.name.replace("-", "_")}_{p}"')
                )
                spec = directory / f"input-{p}.json"
                publish(spec, {"directory": directory.as_posix(), "run_id": run_id, "player": p,
                               "launcher": (directory / f"download-{p}.lua").as_posix(),
                               "cold_boot": True, "phases": PHASES})
                jobs.append(asyncio.create_task(asyncio.to_thread(
                    run_gate, script.relative_to(ROOT).as_posix(), rom_key=variant, timeout=420, quiet=True,
                    config_base=str(config), fixture_override=str(fixture),
                    extra_env={"SLINK_LAUNCHER_TEST_INPUT": str(spec),
                               "SLINK_CLIENT_STORAGE_ROOT": str(directory / "client-data")})))
            observed = {p: await wait("observed", p, 55) for p in players}
            assert all(row["cold_boot"] is True for row in observed.values())
            runtime = create_runtime(directory, contract(*variants), run_id=run_id, free_service=True)
            original_process = runtime.process

            def measured_process(message, owner):
                # Wall clock around every server turn; observation rows also keep their frame
                # and sequence so the commit timeline reads in frames.
                began = time.perf_counter()
                failure = None
                try:
                    return original_process(message, owner)
                except Exception as error:
                    failure = f"{type(error).__name__}: {error}"
                    raise
                finally:
                    row = {"event": message.get("event"), "player": message.get("player"), "began": began,
                           "finished": time.perf_counter(), "error": failure}
                    if message.get("event") == "observation":
                        signals = message.get("signals") or {}
                        row.update(frame=message.get("frame"), sequence=message.get("sequence"),
                                   operation_id=message.get("operation_id"),
                                   heartbeat=message.get("inventory") is not None,
                                   signals=len(signals.get("signals") or []),
                                   acquisitions=len(message.get("acquisitions") or []))
                    turns.append(row)

            runtime.process = measured_process
            assert not runtime.journal.snapshot().state["rules"]["core"]["player_identity"]
            configure_runtime(runtime)
            srv = SLinkServer(data_dir=str(directory), gen1_runtime=runtime)
            listener = await asyncio.start_server(
                srv.handle_client, "127.0.0.1", 0, limit=4 * 1024 * 1024
            )
            srv._tcp_port = listener.sockets[0].getsockname()[1]
            web = TestClient(TestServer(build_app(srv)))
            await web.start_server()
            for p in players:
                response = await web.get("/launcher/" + p)
                assert response.status == 200
                (directory / f"download-{p}.lua").write_text(await response.text())
            publish(directory / "go.json", {"ready": True})
            ready = {p: await wait("ready", p, 400) for p in players}
            deadline = asyncio.get_running_loop().time() + 45
            while True:
                saves = runtime.journal.snapshot().state["components"].get("gen1-initial-save", {})
                if set(saves) == set(players) and all(row["receipt_operation"] for row in saves.values()):
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("normal launcher initial save did not obtain its file receipt")
                for job in jobs:
                    if job.done():
                        passed, path, log = await job
                        raise AssertionError(f"emulator exited before initial save: {passed} {path}\n{log}")
                await asyncio.sleep(0.05)
            # Both owners are still admitted after every phase; then stop the proven clients
            # before the synchronous evidence review, as the ordinary launcher test does.
            assert set(runtime.gate.sessions) == set(players)
            publish(directory / "finish.json", {"done": True})
            for job in jobs:
                passed, path, log = await job
                assert passed, f"{path}\n{log[-4000:]}"
            client_final = {}
            for p, result in ready.items():
                local_state = json.loads(Path(result["status"]["journal_path"]).read_text())["document"]["payload"]
                assert local_state["outbox"] == [] and local_state["inbox"] == []
                initial_cursor = local_state["observation"]["initial_inventory"]
                assert initial_cursor["schema"] == "rby-initial-observation-cursor-v1"
                assert "payload" not in initial_cursor and len(json.dumps(local_state)) < 16 * 1024
                client_final[p] = {"pending_events": 0, "pending_commands": 0,
                                   "journal_bytes": Path(result["status"]["journal_path"]).stat().st_size}
            publish(directory / "server-turns.json", {"turns": turns})
            document = runtime.state().document()
            state = runtime.state()
            summary = {"schema": "rby-free-service-live-v1", "directory": directory.name, "run_id": run_id,
                       "variants": list(variants), "phases_planned": PHASES, "credit_loop": CREDIT_LOOP,
                       "server_turns": {event: len([row for row in turns if row["event"] == event])
                                        for event in sorted({row["event"] for row in turns})},
                       "players": {}}
            for p, result in ready.items():
                status = result["status"]
                assert result["actual_generated_launcher"]
                assert status["free_service"] is True and status["observation_loop"] is True
                assert status["phase"] == "free_service" and status["ordinary_execution"] is False
                assert status.get("frame_progress") is None  # no frame ledger client is shipped
                assert status["run_id"] == run_id and status["player"] == p
                assert status["initial_observation"] == "acknowledged"
                assert status["bootstrap"]["complete"] and status["bootstrap"].get("failed") is None
                assert status.get("bootstrap_observation") == "acknowledged"
                assert status["engine_signals"].get("failed") is None
                assert status["runtime"]["connected"] and status["runtime"]["session_state"] == "admitted"
                assert not status["runtime"]["failed"]
                # Free-running: the one host is owned but released; the hold is momentary.
                assert status["host"]["held"] is False and status["host"].get("failed") is not True
                assert status["host"]["owner_id"] == status["context"]["physical_instance"]
                assert result["frames_driven"] > 0
                assert result["loop_started"]["frame"] >= result["held_frame"]
                assert result["frame_after"] - result["loop_started"]["frame"] >= sum(ph["frames"] for ph in PHASES)
                phases = result["phases"]
                assert [ph["name"] for ph in phases] == [ph["name"] for ph in PHASES]
                for ph, planned in zip(phases, PHASES, strict=True):
                    assert ph["frames"] >= planned["frames"] and ph["seconds"] > 0
                    target = TARGET_FPS * planned["speed"] / 100
                    assert ph["fps"] >= target * MIN_FRACTION, ph
                    assert ph["windows"] and all(window["fps"] >= target * MIN_FRACTION for window in ph["windows"]), ph
                    assert ph["windows"][-1]["fps"] >= ph["windows"][0]["fps"] * MIN_FRACTION, ph
                labels = {Path(shot).name.split("-", 1)[1] for shot in result["screenshots"]}
                assert labels == {"intro.png", "held-checkpoint.png", "free-start.png"}
                start_shot, end_shot = directory / f"{p}-free-start.png", directory / f"{p}-free-end.png"
                for shot in (start_shot, end_shot):
                    assert shot.is_file() and shot.stat().st_size > 0
                assert start_shot.read_bytes() != end_shot.read_bytes()
                # Unchanged 30-frame fingerprints intentionally create no semantic event.
                # Any actual source change still publishes the complete existing point.
                final_inventory = result["final_inventory"]
                initial_entry = document["components"]["gen1-initial-observations"][p]
                decoded = decode_inventory(final_inventory["source"], initial_entry["metadata"]["save_identity"])
                assert {key: value for key, value in decoded.items() if key != "source_digest"} == {
                    key: value for key, value in initial_entry["inventory"].items() if key != "source_digest"}
                commits = [row for row in turns if row["event"] == "observation" and row["player"] == p]
                assert all(row["error"] is None for row in commits)
                assert [row["sequence"] for row in commits] == list(range(1, len(commits) + 1))
                assert all(b["frame"] > a["frame"] for a, b in zip(commits, commits[1:], strict=False))
                progress = document["components"].get(PROGRESS, {}).get(p)
                if commits:
                    assert progress["sequence"] == len(commits) and progress["frame"] == commits[-1]["frame"]
                else:
                    assert progress is None
                heartbeats = [row for row in commits if row["heartbeat"]]
                diagnostics = status["observation_diagnostics"]
                measured_checks = sum(ph["diagnostics"]["after"]["inventory_checks"]
                                      - ph["diagnostics"]["before"]["inventory_checks"] for ph in phases)
                measured_publications = sum(ph["diagnostics"]["after"]["inventory_publications"]
                                            - ph["diagnostics"]["before"]["inventory_publications"] for ph in phases)
                assert measured_checks == sum(ph["frames"] for ph in PHASES) // 30
                assert measured_publications == 0
                dirty = result["dirty_probe"]
                assert dirty["schema"] == "rby-inventory-dirty-negative-control-v1"
                assert dirty["phase"] == "restored" and dirty["after"] - dirty["before"] == 2
                assert diagnostics["inventory_publications"] == len(heartbeats) == 2
                per_phase = {}
                for ph in phases:
                    inside = [row for row in commits if ph["began"]["frame"] <= row["frame"] <= ph["ended"]["frame"]]
                    per_phase[ph["name"]] = {"emulator": {"frames": ph["frames"], "seconds": ph["seconds"], "fps": ph["fps"],
                                                          "speed": ph["speed"], "pending_events_at_start": ph["began"]["pending_events"],
                                                          "pending_events_at_end": ph["ended"]["pending_events"],
                                                          "windows": ph.get("windows"), "diagnostics": ph.get("diagnostics")},
                                             "server_commits": fps_between(inside),
                                             "heartbeats": sum(1 for row in inside if row["heartbeat"])}
                summary["players"][p] = {
                    "variant": players[p], "held_frame": result["held_frame"], "loop_started_frame": result["loop_started"]["frame"],
                    "frame_after": result["frame_after"], "menu_frames_driven": result["frames_driven"],
                    "observation_events": len(commits), "heartbeats": len(heartbeats),
                    "batches_without_inventory": len(commits) - len(heartbeats),
                    "signals": sum(row["signals"] for row in commits), "acquisitions": sum(row["acquisitions"] for row in commits),
                    "sequence_gaps": 0, "first_frame": commits[0]["frame"] if commits else None,
                    "last_frame": commits[-1]["frame"] if commits else None,
                    "server_commits": fps_between(commits),
                    "server_ms_per_observation": (1000 * sum(row["finished"] - row["began"] for row in commits) / len(commits)
                                                  if commits else None),
                    "phases": per_phase, "pending_events_at_end": status["runtime"]["pending_events"],
                    "final_backlog": client_final[p],
                    "screenshots": [start_shot.name, end_shot.name]}
            assert not document["identities"]["members"] and not document["rules"]["core"]["links"]
            assert state.barrier.ticket() is None
            assert not runtime.journal.pending_ids("a") and not runtime.journal.pending_ids("b")
            for p in players:
                fixture = directory / f"blank-{p}.SaveRAM"
                assert fixture.read_bytes() == b"\xff" * 0x8000
            runtime.close()
            runtime = None
            # The run reopens after the servers stop: same selection, every verifier green, and
            # every evidence component intact (only gen1-runtime moves: close and reopen commit
            # runtime_suspended / runtime_opened).
            reopened = open_runtime(directory)
            try:
                assert reopened.free_service is True
                restored = reopened.state().document()

                def evidence(doc):
                    return {name: value for name, value in doc["components"].items() if name != "gen1-runtime"}

                assert evidence(restored) == evidence(document)
                assert restored["identities"] == document["identities"] and restored["rules"] == document["rules"]
            finally:
                reopened.close()
            rows, snapshot = journal_events(directory / "runtime.sqlite3")
            assert snapshot["components"].get(PROGRESS) == document["components"].get(PROGRESS)
            for p in players:
                observations = [row for row in rows if row[0] == p and row[2].get("event") == "observation"]
                assert [row[2]["sequence"] for row in observations] == list(range(1, len(observations) + 1))
                assert len(observations) == summary["players"][p]["observation_events"]
                assert all(row[3]["ack"] == "ACK" and row[3]["ordinary_execution"] is False for row in observations)
                assert not any(row[2].get("event") in ("frame_grant", "frame_complete", "frame_enrollment") for row in rows if row[0] == p)
                checkpoints = [row[2]["inventory"] for row in observations if row[2]["inventory"] is not None]
                kinds = [item["kind"] for row in observations for item in row[2]["acquisitions"]]
                deferred = sum(1 for row in observations if row[3].get("inventory_deferred"))
                last = ready[p]["final_inventory"]
                transition = (snapshot["components"].get(INVENTORY, {}).get(p) or {}).get("transition", {
                    "added": [], "removed": [], "movements": [], "party_hp_zero": [], "changed": []})
                comparison = {"route": "bedroom only: the scripted inputs (one step Right) never reach the starter",
                              "free_run": {"checkpoints": len(checkpoints), "deferred_checkpoints": deferred, "frame": last["frame"],
                                           "acquisition_kinds": kinds, "save_status": last["source"]["save_status"],
                                           "transition": strip_digests(transition)},
                              "credit_run": credit_reference(p)}
                reference = comparison["credit_run"]
                if reference is not None:
                    assert last["source"]["fields"]["party"] == reference["party"]
                    assert last["source"]["fields"]["box"] == reference["box"]
                    assert last["source"]["fields"]["name"] == reference["name"]
                    assert last["source"]["save_status"] == reference["save_status"]
                    assert kinds == reference["acquisition_kinds"] == []
                    assert comparison["free_run"]["transition"] == reference["transition"]
                    comparison["result"] = "party, box and name bytes, save status, receipt kinds and transition identical"
                else:
                    comparison["result"] = "credit run unavailable; set SLINK_CREDIT_RUN to compare"
                summary["players"][p]["receipt_comparison"] = comparison
            publish(directory / "summary.json", summary)
        finally:
            if any(not job.done() for job in jobs):
                publish(directory / "abort.json", {"reason": "paired free-service launcher test finished or failed"})
            if web is not None:
                await web.close()
            if listener is not None:
                listener.close()
                await listener.wait_closed()
            if runtime is not None:
                runtime.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue")])
def test_generated_free_service_launcher_free_runs_the_bedroom_and_publishes_observation_batches(variants):
    run_free_pair(variants)
