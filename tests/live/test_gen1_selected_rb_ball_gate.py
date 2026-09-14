"""Explicit R/B starter and lab-rival gameplay checkpoint; never auto-collected live."""

import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from tests.live.gen1_scripted_host import scripted_failure
from tests.live.gen1_selected_scenario import SelectedRun, checked_events, observe

ROOT = Path(__file__).resolve().parents[2]


def verify_starter_rival_checkpoint(document, rows, markers):
    """Audit first ordinary checkpoint without claiming the later ball route."""
    component = document["components"]["gen1-starter-settlement"]
    assert set(component["sources"]) == {"a", "b"}
    assert set(component["settled"]) == {"a", "b"}
    assert component["settled"]["a"]["member_id"] != component["settled"]["b"]["member_id"]
    assert component["link_id"] and component["rejection"] is None
    links = document["rules"]["core"]["links"]
    assert len(links) == 1 and links[0]["status"] == "alive" and links[0]["area_id"] == "oaks_lab"
    assert links[0]["a"]["species"] == 1 and links[0]["b"]["species"] == 4
    assert document["rules"]["core"]["pokeballs_obtained"] == {"a": False, "b": False}
    faint = document["components"].get("gen1-faint-settlement", {})
    assert not faint.get("activations") and not faint.get("deaths")
    receipt = {}
    for player in ("a", "b"):
        marker = markers[player]
        assert marker["stage"] == "lab-loss-complete" and marker["point"]["lab_rival_done"]
        assert marker["point"]["battle_result"] == 1 and marker["point"]["party_hp"] > 0
        signals = []
        for owner, revision, request, result, operation in rows:
            if owner != player or request.get("event") != "observation":
                continue
            assert result.get("ack") == "ACK"
            batch = request.get("signals")
            if batch is not None:
                assert result.get("engine_evidence_digest"), "engine signals lack committed result"
                for signal in batch["signals"]:
                    if signal["kind"] in {"starter_begin", "starter_end", "battle_faint"}:
                        signals.append({"kind": signal["kind"], "revision": revision,
                                        "operation_id": operation, "frame": signal["frame"],
                                        "point": signal["point"]})
        kinds = [signal["kind"] for signal in signals]
        assert kinds.count("starter_begin") == 1 and kinds.count("starter_end") == 1
        assert kinds.count("battle_faint") == 1
        assert signals[-1]["kind"] == "battle_faint" and signals[-1]["point"]["battle_hp"] == 0
        receipt[player] = {"marker": marker, "source_signals": signals}
    return {"starters": component, "link": links[0], "preball_faint": receipt,
            "activations": faint.get("activations", {}), "deaths": faint.get("deaths", {})}


def verify_parcel_checkpoint(document, markers):
    """Audit the first-ball-readback checkpoint reached via the chained parcel module.

    A purchased ball is a `pokeballs_obtained` engine signal, which settle()
    (server/gen1_faint_runtime.py:131-139) both records as a `gen1-faint-settlement`
    activation AND sets `pokeballs_obtained[player]=True` in the same step — so a
    correct run has one activation per player, never none.
    """
    links = document["rules"]["core"]["links"]
    assert len(links) == 1 and links[0]["status"] == "alive"
    faint = document["components"].get("gen1-faint-settlement", {})
    activations = faint.get("activations", {})
    assert set(activations) == {"a", "b"}
    for player in ("a", "b"):
        assert activations[player].get("engine_record") is not None
        assert isinstance(activations[player].get("index"), int)
    assert not faint.get("deaths")
    pokeballs = document["rules"]["core"]["pokeballs_obtained"]
    for player in ("a", "b"):
        marker = markers[player]
        assert marker["stage"] == "first-ball-readback"
        point = marker["point"]
        assert point["oak_got_parcel"] is True
        assert point["parcel_count"] == 0
        assert point["ball_count"] > 0
        assert pokeballs[player] is True
    return {"link": links[0], "markers": markers,
            "activations": activations, "deaths": faint.get("deaths", {})}


async def rb_starter_rival(owned, *, emulator, base_config, limit=1800):
    """Explicit controlled-scripted Red/Blue run, awaiting a separate live grant."""
    run = SelectedRun(owned, ("red", "blue"), emulator=emulator, base_config=base_config,
                      limit=limit, input_mode="scripted-normal-buttons",
                      launch_mode="scripted-selected-launcher", route_mode="rb-starter-rival")
    async with run:
        rows = await run.wait(run.enrollment_ready)
        run.audit_enrollment(rows)
        run.outcome["source_files"]["tests/live/test_gen1_selected_rb_ball_gate.py"] = hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest()
        handshakes = {}
        for player in ("a", "b"):
            initial = run.outcome["enrollment"]["evidence"]["players"][player]["initial_observation"]
            spec = json.loads(run.downloads[player]["manifest"].read_text())
            handshake = {"ready": True, "run_id": spec["run_id"], "player": player,
                         "rom_sha1": spec["rom_sha1"],
                         "context_generation": initial["binding"]["context_generation"],
                         "physical_instance": initial["metadata"]["gen1_metadata"]["physical_instance"]}
            directory = run.owned / "clients" / spec["run_id"] / player / "emulator"
            target = directory / "rb_route_go.json"
            temporary = directory / "rb_route_go.json.tmp"
            assert not target.exists() and not temporary.exists(), "route handshake must be one-time"
            temporary.write_text(json.dumps(handshake, indent=2) + "\n")
            temporary.replace(target)
            handshakes[player] = handshake
        run.outcome["route_handshakes"] = handshakes
        deadline = time.monotonic() + limit
        markers = {}
        while time.monotonic() < deadline:
            for job in run.jobs:
                player = job["player"]
                if observe(job) is not None:
                    raise RuntimeError(f"{player} scripted host exited before lab checkpoint")
                spec = json.loads(run.downloads[player]["manifest"].read_text())
                directory = run.owned / "clients" / spec["run_id"] / player / "emulator"
                failure = scripted_failure(directory)
                if failure is not None:
                    run.outcome.setdefault("route_failures", {})[player] = failure
                    raise RuntimeError(f"{player} R/B route failed: {failure['error']}")
                try:
                    marker = json.loads((directory / "rb_route_progress.json").read_text())
                except FileNotFoundError:
                    continue
                run.outcome.setdefault("route_progress", {})[player] = marker
                if marker["stage"] == "lab-loss-complete":
                    markers[player] = marker
            if set(markers) == {"a", "b"}:
                snapshot = run.runtime.journal.snapshot().state
                components = snapshot.get("components", {})
                starters = components.get("gen1-starter-settlement", {})
                engines = components.get("gen1-engine-signals", {})
                settled = set(starters.get("settled", {})) == {"a", "b"} and starters.get("link_id")
                fainted = all(any(row.get("kind") == "faint" for row in
                                  engines.get(player, {}).get("transactions", ())) for player in ("a", "b"))
                queues_empty = not any(run.runtime.journal.pending_ids(player) for player in ("a", "b"))
                if settled and fainted and queues_empty and run.runtime.service_current():
                    break
            await asyncio.sleep(0.25)
        else:
            raise TimeoutError("R/B starter/lab loss checkpoint timed out")
        document = run.runtime.state().document()
        rows = checked_events(run.runtime)
        evidence = verify_starter_rival_checkpoint(document, rows, markers)
        database = sqlite3.connect((Path(run.runtime.data_dir) / "runtime.sqlite3").resolve().as_uri() +
                                   "?mode=ro", uri=True)
        try:
            command_ids = database.execute("SELECT player, command_id FROM commands").fetchall()
        finally:
            database.close()
        for recipient, command_id in command_ids:
            body = run.runtime.journal.command(recipient, command_id)["body"]
            assert body.get("cmd") not in {"force_faint", "force_explode", "memorialize"}, (
                "pre-ball lab loss queued a physical death command", command_id)
        assert run.runtime.service_current(), "final paired service is not current"
        assert not any(run.runtime.journal.pending_ids(player) for player in ("a", "b"))
        run.audit_scenario("rb-starter-rival", evidence)
        run.outcome["status"] = "rb-starter-rival-checkpoint-observed"
    return run.outcome


async def rb_parcel_first_ball(owned, *, emulator, base_config, limit=1800):
    """Explicit controlled-scripted Red/Blue run through the chained parcel first-ball checkpoint."""
    run = SelectedRun(owned, ("red", "blue"), emulator=emulator, base_config=base_config,
                      limit=limit, input_mode="scripted-normal-buttons",
                      launch_mode="scripted-selected-launcher", route_mode="rb-parcel")
    async with run:
        rows = await run.wait(run.enrollment_ready)
        run.audit_enrollment(rows)
        run.outcome["source_files"]["tests/live/test_gen1_selected_rb_ball_gate.py"] = hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest()
        handshakes = {}
        for player in ("a", "b"):
            initial = run.outcome["enrollment"]["evidence"]["players"][player]["initial_observation"]
            spec = json.loads(run.downloads[player]["manifest"].read_text())
            handshake = {"ready": True, "run_id": spec["run_id"], "player": player,
                         "rom_sha1": spec["rom_sha1"],
                         "context_generation": initial["binding"]["context_generation"],
                         "physical_instance": initial["metadata"]["gen1_metadata"]["physical_instance"]}
            directory = run.owned / "clients" / spec["run_id"] / player / "emulator"
            target = directory / "rb_route_go.json"
            temporary = directory / "rb_route_go.json.tmp"
            assert not target.exists() and not temporary.exists(), "route handshake must be one-time"
            temporary.write_text(json.dumps(handshake, indent=2) + "\n")
            temporary.replace(target)
            handshakes[player] = handshake
        run.outcome["route_handshakes"] = handshakes
        deadline = time.monotonic() + limit
        markers = {}
        while time.monotonic() < deadline:
            for job in run.jobs:
                player = job["player"]
                if observe(job) is not None:
                    raise RuntimeError(f"{player} scripted host exited before parcel checkpoint")
                spec = json.loads(run.downloads[player]["manifest"].read_text())
                directory = run.owned / "clients" / spec["run_id"] / player / "emulator"
                failure = scripted_failure(directory)
                if failure is not None:
                    run.outcome.setdefault("route_failures", {})[player] = failure
                    raise RuntimeError(f"{player} R/B route failed: {failure['error']}")
                try:
                    marker = json.loads((directory / "rb_route_progress.json").read_text())
                except FileNotFoundError:
                    continue
                run.outcome.setdefault("route_progress", {})[player] = marker
                if marker["stage"] == "first-ball-readback":
                    markers[player] = marker
            if set(markers) == {"a", "b"}:
                snapshot = run.runtime.journal.snapshot().state
                components = snapshot.get("components", {})
                faint = components.get("gen1-faint-settlement", {})
                settled = set(faint.get("activations", {})) == {"a", "b"}
                queues_empty = not any(run.runtime.journal.pending_ids(player) for player in ("a", "b"))
                if settled and queues_empty and run.runtime.service_current():
                    break
            await asyncio.sleep(0.25)
        else:
            raise TimeoutError("R/B parcel first-ball checkpoint timed out")
        document = run.runtime.state().document()
        evidence = verify_parcel_checkpoint(document, markers)
        database = sqlite3.connect((Path(run.runtime.data_dir) / "runtime.sqlite3").resolve().as_uri() +
                                   "?mode=ro", uri=True)
        try:
            command_ids = database.execute("SELECT player, command_id FROM commands").fetchall()
        finally:
            database.close()
        for recipient, command_id in command_ids:
            body = run.runtime.journal.command(recipient, command_id)["body"]
            assert body.get("cmd") not in {"force_faint", "force_explode", "memorialize"}, (
                "pre-ball parcel run queued a physical death command", command_id)
        assert run.runtime.service_current(), "final paired service is not current"
        assert not any(run.runtime.journal.pending_ids(player) for player in ("a", "b"))
        run.audit_scenario("rb-parcel", evidence)
        run.outcome["status"] = "rb-parcel-checkpoint-observed"
    return run.outcome
