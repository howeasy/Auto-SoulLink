"""Explicit R/B save -> close -> resume round trip; never auto-collected live.

Run 1 (route "rb-save"): the rb-starter-rival route to `lab-loss-complete`, then the chained
START-menu save driver to `save-witnessed` (both players' `gen1-save-witness` acked, SaveRAM
flushed). Run 2: a NEW Manager run created with `resume_from=<run 1 registry id>` through run 1's
Manager registry, each player launched with `--resume-save <run 1 private .SaveRAM>` and booted
through CONTINUE; both enroll under the resume contract with the lab link intact.
"""

import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from server.bizhawk_launch import projection_digest
from tests.live.gen1_scripted_host import scripted_failure
from tests.live.gen1_selected_scenario import SelectedRun, checked_events, observe, private_receipt

ROOT = Path(__file__).resolve().parents[2]
PROJECTION = "cartram-0498-8000-v1"


def player_directory(run, player):
    spec = json.loads(run.downloads[player]["manifest"].read_text())
    return run.owned / "clients" / spec["run_id"] / player / "emulator"


def start_route(run):
    """One-time paired handshake that lets the staged route module take the buttons."""
    handshakes = {}
    for player in ("a", "b"):
        initial = run.outcome["enrollment"]["evidence"]["players"][player]["initial_observation"]
        spec = json.loads(run.downloads[player]["manifest"].read_text())
        handshake = {"ready": True, "run_id": spec["run_id"], "player": player, "rom_sha1": spec["rom_sha1"],
                     "context_generation": initial["binding"]["context_generation"],
                     "physical_instance": initial["metadata"]["gen1_metadata"]["physical_instance"]}
        target = player_directory(run, player) / "rb_route_go.json"
        temporary = target.with_suffix(".json.tmp")
        assert not target.exists() and not temporary.exists(), "route handshake must be one-time"
        temporary.write_text(json.dumps(handshake, indent=2) + "\n")
        temporary.replace(target)
        handshakes[player] = handshake
    run.outcome["route_handshakes"] = handshakes


async def await_stage(run, stage, ready, limit, *, flushed=False):
    """Poll both route progress markers to `stage`, then the checked snapshot until `ready`."""
    deadline = time.monotonic() + limit
    markers = {}
    while time.monotonic() < deadline:
        for job in run.jobs:
            player = job["player"]
            if observe(job) is not None:
                raise RuntimeError(f"{player} scripted host exited before {stage}")
            directory = player_directory(run, player)
            failure = scripted_failure(directory)
            if failure is not None:
                run.outcome.setdefault("route_failures", {})[player] = failure
                raise RuntimeError(f"{player} R/B route failed: {failure['error']}")
            try:
                marker = json.loads((directory / "rb_route_progress.json").read_text())
            except (FileNotFoundError, PermissionError, json.JSONDecodeError):  # publisher remove+rename race
                continue
            run.outcome.setdefault("route_progress", {})[player] = marker
            if marker["stage"] == stage and (not flushed or marker.get("saveram_flushed") is True):
                markers[player] = marker
        if set(markers) == {"a", "b"}:
            components = run.runtime.journal.snapshot().state.get("components", {})
            queues_empty = not any(run.runtime.journal.pending_ids(player) for player in ("a", "b"))
            if ready(components) and queues_empty and run.runtime.service_current():
                return markers
        await asyncio.sleep(0.25)
    raise TimeoutError(f"R/B {stage} checkpoint timed out")


def no_death_commands(run):
    database = sqlite3.connect((Path(run.runtime.data_dir) / "runtime.sqlite3").resolve().as_uri() +
                               "?mode=ro", uri=True)
    try:
        command_ids = database.execute("SELECT player, command_id FROM commands").fetchall()
    finally:
        database.close()
    for recipient, command_id in command_ids:
        body = run.runtime.journal.command(recipient, command_id)["body"]
        assert body.get("cmd") not in {"force_faint", "force_explode", "memorialize"}, (
            "pre-ball run queued a physical death command", command_id)
    assert run.runtime.service_current(), "final paired service is not current"
    assert not any(run.runtime.journal.pending_ids(player) for player in ("a", "b"))


def lab_link(document):
    links = document["rules"]["core"]["links"]
    assert len(links) == 1 and links[0]["status"] == "alive" and links[0]["area_id"] == "oaks_lab"
    assert links[0]["a"]["species"] == 1 and links[0]["b"]["species"] == 4
    assert document["rules"]["core"]["pokeballs_obtained"] == {"a": False, "b": False}
    faint = document["components"].get("gen1-faint-settlement", {})
    assert not faint.get("deaths")
    return links[0]


def verify_save_checkpoint(document, rows, markers, saves):
    """Run 1 ended in an acked in-game save per player whose flushed SaveRAM matches the witness."""
    starters = document["components"]["gen1-starter-settlement"]
    assert set(starters["settled"]) == {"a", "b"} and starters["link_id"] and starters["rejection"] is None
    link = lab_link(document)
    witnesses = document["components"]["gen1-save-witness"]
    assert set(witnesses) == {"a", "b"}
    receipt = {}
    for player in ("a", "b"):
        marker = markers[player]
        assert marker["stage"] == "save-witnessed" and marker["saveram_flushed"] is True
        assert marker["point"]["save_file_status"] == 2
        assert marker["point"]["lab_rival_done"] and marker["point"]["party_hp"] > 0
        assert [entry["stage"] for entry in marker["chain_handoffs"]] == ["lab-loss-complete"]
        witness = witnesses[player]
        assert witness["projection"] == PROJECTION
        batches = [(revision, operation, request["signals"]["signals"]) for owner, revision, request, result, operation
                   in rows if owner == player and request.get("event") == "observation"
                   and request.get("signals") is not None and result.get("ack") == "ACK"]
        saved = [(operation, index, signal) for revision, operation, batch in batches
                 for index, signal in enumerate(batch) if signal["kind"] == "save_witness"]
        assert len(saved) == 1, "exactly one acked save_witness signal expected"
        operation, index, signal = saved[0]
        assert (operation, index) == (witness["operation_id"], witness["index"])
        assert signal["point"]["digest"] == witness["digest"] and signal["point"]["save_file_status"] == 2
        assert index == len(next(b for _, op, b in batches if op == operation)) - 1, "played after the save in its batch"
        file_digest = projection_digest(Path(saves[player]).read_bytes(), PROJECTION)
        assert file_digest == witness["digest"], f"{player} flushed SaveRAM differs from the acked save witness"
        receipt[player] = {"marker": marker, "witness": witness, "save_file": str(saves[player]),
                           "save_sha256": hashlib.sha256(Path(saves[player]).read_bytes()).hexdigest()}
    return {"starters": starters, "link": link, "saves": receipt}


def verify_resume_checkpoint(run, predecessor, rows):
    """Run 2 enrolled both players under the resume contract with the predecessor's link intact."""
    document = run.runtime.state().document()
    receipts = {job["player"]: private_receipt(job, json.loads(run.downloads[job["player"]]["manifest"].read_text()),
                                               run.downloads[job["player"]]["rom"], run.emulator,
                                               run.requested_speed_percent) for job in run.jobs}
    run.outcome["enrollment"] = {"document": document, "players": receipts}  # no initial-save audit on CONTINUE
    component = document["components"]["gen1-resume"]
    assert component["from_run"] == predecessor["manager"]["run_id"]
    assert component["pending"] == {"a": False, "b": False} and set(component["enrolled"]) == {"a", "b"}
    witnesses = predecessor["scenario_results"]["rb-save"]["saves"]
    link = lab_link(document)
    assert link["a"]["species"] == predecessor["scenario_results"]["rb-save"]["link"]["a"]["species"]
    assert link["b"]["species"] == predecessor["scenario_results"]["rb-save"]["link"]["b"]["species"]
    players = {}
    for player in ("a", "b"):
        required = component["required"][player]
        enrolled = component["enrolled"][player]
        assert required["digest"] == witnesses[player]["witness"]["digest"] == enrolled["digest"]
        assert enrolled["continue_witness"]["loaded"]["status"] == 2
        initial = document["components"]["gen1-initial-observations"][player]
        assert enrolled["binding"] == initial["binding"]
        plan = json.loads((player_directory(run, player) / "scripted_plan.json").read_text())
        assert plan["resume_save"]["projection_digest"] == required["digest"]
        assert Path(plan["resume_save"]["source_path"]).resolve() == Path(witnesses[player]["save_file"]).resolve()
        state = json.loads((player_directory(run, player) / "scripted_progress.json").read_text())
        assert state["stage"] == "input-stopped"
        players[player] = {"enrolled": enrolled, "plan": plan, "scripted_progress": state,
                           "observation_count": len(run.observation_sequence(rows, player))}
    no_death_commands(run)
    return {"resume": component, "link": link, "players": players}


async def rb_resume_roundtrip(owned, *, emulator, base_config, limit=1800):
    """Explicit controlled-scripted Red/Blue save, close and CONTINUE-resume round trip."""
    owned = Path(owned)
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    first = SelectedRun(owned, ("red", "blue"), emulator=emulator, base_config=base_config, limit=limit,
                        input_mode="scripted-normal-buttons", launch_mode="scripted-selected-launcher",
                        route_mode="rb-save")
    async with first:
        rows = await first.wait(first.enrollment_ready)
        first.audit_enrollment(rows)
        first.outcome["source_files"]["tests/live/test_gen1_selected_rb_resume.py"] = source_hash
        start_route(first)
        markers = await await_stage(first, "save-witnessed", lambda components: set(
            components.get("gen1-save-witness", {})) == {"a", "b"}, limit, flushed=True)
        saves = {}
        for player in ("a", "b"):
            files = sorted(Path(first.outcome["enrollment"]["players"][player]["save_directory"]).glob("*.SaveRAM"))
            assert len(files) == 1, f"{player} private SaveRAM directory holds {files}"
            saves[player] = files[0]
        evidence = verify_save_checkpoint(first.runtime.state().document(), checked_events(first.runtime),
                                          markers, saves)
        no_death_commands(first)
        first.audit_scenario("rb-save", evidence)
        first.outcome["status"] = "rb-save-checkpoint-observed"
    predecessor = first.outcome
    second = SelectedRun(owned.with_name(owned.name + "-resumed"), ("red", "blue"), emulator=emulator,
                         base_config=base_config, limit=limit, input_mode="scripted-normal-buttons",
                         launch_mode="scripted-selected-launcher",
                         resume_from={"run_id": predecessor["manager"]["run_id"],
                                      "manager_dir": str(first.owned / "manager"), "saves": saves})
    async with second:
        rows = await second.wait(second.resume_ready)
        second.outcome["source_files"]["tests/live/test_gen1_selected_rb_resume.py"] = source_hash
        second.outcome["predecessor"] = {"owned": predecessor["owned"], "manager": predecessor["manager"]}
        second.audit_scenario("rb-resume", verify_resume_checkpoint(second, predecessor, rows))
        second.outcome["status"] = "rb-resume-checkpoint-observed"
    return {"status": "rb-resume-checkpoint-observed", "predecessor": predecessor, "resumed": second.outcome}
