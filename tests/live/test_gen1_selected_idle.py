"""Model checks for the tracked selected-run idle boundary; no live invocation."""

import asyncio
import hashlib
import inspect
import tempfile
from pathlib import Path

import pytest

from tests.live.gen1_selected_scenario import (
    SelectedRun,
    drain_owned_handlers,
    verify_initial_save_file,
)


async def idle_enrollment(owned, *, emulator, base_config, limit=1800, input_mode="human"):
    """Explicit physical entry, invoked by a human outside pytest collection."""
    run = SelectedRun(owned, ("yellow", "yellow"), emulator=emulator,
                      base_config=base_config, limit=limit, input_mode=input_mode)
    async with run:
        rows = await run.wait(run.enrollment_ready)
        enrollment = run.audit_enrollment(rows)
        run.audit_scenario("idle", {"observation_counts": {
            player: enrollment["players"][player]["observation_count"] for player in ("a", "b")}})
        run.outcome["source_files"]["tests/live/test_gen1_selected_idle.py"] = hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest()
        run.outcome["status"] = "bounded-idle-enrollment-observed"
    return run.outcome


def test_quiet_selected_run_can_be_configured_without_launching(tmp_path):
    run = SelectedRun(tmp_path / "owned", ("yellow", "yellow"), emulator=tmp_path / "EmuHawk.exe",
                      base_config=tmp_path / "config.ini", limit=1800)
    assert not (tmp_path / "owned").exists()
    assert run.variants == ("yellow", "yellow")
    components = {name: {player: {} for player in ("a", "b")} for name in (
        "gen1-native-reattach", "gen1-initial-observations",
        "gen1-new-game-bootstrap", "gen1-initial-save")}
    for player in ("a", "b"):
        components["gen1-initial-save"][player]["receipt_operation"] = "a" * 32
    assert run.enrollment_ready(components, {"a": [], "b": []})
    assert run.observation_sequence([], "a") == []


def test_idle_readiness_refuses_pending_or_unacknowledged_save(tmp_path):
    run = SelectedRun(tmp_path / "owned", ("yellow", "yellow"), emulator=tmp_path / "EmuHawk.exe",
                      base_config=tmp_path / "config.ini", limit=1800)
    components = {name: {player: {} for player in ("a", "b")} for name in (
        "gen1-native-reattach", "gen1-initial-observations",
        "gen1-new-game-bootstrap", "gen1-initial-save")}
    for player in ("a", "b"):
        components["gen1-initial-save"][player]["receipt_operation"] = "a" * 32
    assert not run.enrollment_ready(components, {"a": ["pending"], "b": []})
    components["gen1-initial-save"]["b"]["receipt_operation"] = None
    assert not run.enrollment_ready(components, {"a": [], "b": []})


def test_existing_observation_must_be_contiguous_and_acked(tmp_path):
    run = SelectedRun(tmp_path / "owned", ("yellow", "yellow"), emulator=tmp_path / "EmuHawk.exe",
                      base_config=tmp_path / "config.ini", limit=1800)
    valid = [("a", number, {"event": "observation", "sequence": number}, {"ack": "ACK"}, str(number) * 32)
             for number in (1, 2)]
    assert run.observation_sequence(valid, "a") == [1, 2]
    with pytest.raises(AssertionError):
        run.observation_sequence(valid[1:], "a")
    with pytest.raises(AssertionError):
        run.observation_sequence([("a", 1, valid[0][2], {"ack": "NACK"}, "a" * 32)], "a")


def test_initial_file_audit_reads_exact_owned_image(tmp_path):
    owned = tmp_path / "a" / "SaveRAM"
    owned.mkdir(parents=True)
    path = owned / "game.sav"
    expected = bytes(range(256)) * 128
    path.write_bytes(expected)
    proof = {"path": str(path), "sha256": hashlib.sha256(expected).hexdigest(),
             "byte_length": 32768, "flushed": True, "readback": True}
    assert verify_initial_save_file(proof, expected, owned)["byte_length"] == 32768
    with pytest.raises(AssertionError):
        verify_initial_save_file(proof, b"\x00" * 32768, owned)
    outside = tmp_path / "other" / "SaveRAM"
    outside.mkdir(parents=True)
    with pytest.raises(AssertionError):
        verify_initial_save_file(proof, expected, outside)


def test_later_scenario_result_does_not_repeat_initial_file_audit(tmp_path):
    run = SelectedRun(tmp_path / "owned", ("yellow", "yellow"), emulator=tmp_path / "EmuHawk.exe",
                      base_config=tmp_path / "config.ini", limit=1800)
    run.outcome["enrollment"] = {"initial_image_verified": True}
    run.audit_scenario("later", {"later_save_relation": "scenario-owned"})
    assert run.outcome["enrollment"] == {"initial_image_verified": True}
    assert run.outcome["scenario_results"]["later"] == {"later_save_relation": "scenario-owned"}


@pytest.mark.asyncio
async def test_owned_handler_cleanup_bounds_listener_and_runtime_order():
    order, errors = [], []

    class Listener:
        def close(self):
            order.append("listener-close")

        async def wait_closed(self):
            order.append("listener-wait")

    async def handler():
        await asyncio.sleep(0)
        order.append("handler-done")

    await drain_owned_handlers(Listener(), {asyncio.create_task(handler())}, errors, timeout=0.1)
    order.append("runtime-close")
    assert order == ["listener-close", "handler-done", "listener-wait", "runtime-close"]
    assert errors == []


@pytest.mark.asyncio
async def test_owned_handler_and_listener_timeouts_remain_errors():
    errors = []

    class NeverListener:
        def close(self):
            pass

        async def wait_closed(self):
            await asyncio.Event().wait()

    async def stuck():
        await asyncio.sleep(10)

    task = asyncio.create_task(stuck())
    await drain_owned_handlers(NeverListener(), {task}, errors, timeout=0.01, listener_timeout=0.01)
    assert task.cancelled()
    assert {next(iter(item)) for item in errors} == {"owned_handlers_timeout", "listener_wait"}


@pytest.mark.asyncio
async def test_existing_in_cache_output_is_preserved_on_context_refusal(tmp_path):
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / ".cache") as temporary:
        owned = Path(temporary) / "existing"
        owned.mkdir()
        progress_file = owned / "progress.json"
        summary = owned.parent / "existing-summary.json"
        progress_file.write_bytes(b"prior progress sentinel\n")
        summary.write_bytes(b"prior summary sentinel\n")
        run = SelectedRun(owned, ("yellow", "yellow"), emulator=tmp_path / "EmuHawk.exe",
                          base_config=tmp_path / "config.ini", limit=1800)
        with pytest.raises(AssertionError):
            async with run:
                pytest.fail("existing output should be refused before entry")
        assert progress_file.read_bytes() == b"prior progress sentinel\n"
        assert summary.read_bytes() == b"prior summary sentinel\n"


@pytest.mark.asyncio
async def test_outside_cache_output_is_preserved_on_context_refusal(tmp_path):
    owned = tmp_path / "outside"
    owned.mkdir()
    progress_file = owned / "progress.json"
    summary = owned.parent / "outside-summary.json"
    progress_file.write_bytes(b"outside progress sentinel\n")
    summary.write_bytes(b"outside summary sentinel\n")
    run = SelectedRun(owned, ("yellow", "yellow"), emulator=tmp_path / "EmuHawk.exe",
                      base_config=tmp_path / "config.ini", limit=1800)
    with pytest.raises(AssertionError):
        async with run:
            pytest.fail("outside output should be refused before entry")
    assert progress_file.read_bytes() == b"outside progress sentinel\n"
    assert summary.read_bytes() == b"outside summary sentinel\n"


def test_selected_idle_input_attribution_is_explicit_and_validated(tmp_path):
    assert inspect.signature(idle_enrollment).parameters["input_mode"].default == "human"
    settings = {"emulator": tmp_path / "EmuHawk.exe", "base_config": tmp_path / "config.ini", "limit": 1800}
    human = SelectedRun(tmp_path / "human", ("yellow", "yellow"), **settings)
    assert human.outcome["input_mode"] == "human"
    assert human.outcome["human_inputs_only"] is True
    computer = SelectedRun(tmp_path / "computer", ("yellow", "yellow"),
                           input_mode="computer-use-normal-buttons", **settings)
    assert computer.outcome["input_mode"] == "computer-use-normal-buttons"
    assert computer.outcome["human_inputs_only"] is False
    with pytest.raises(ValueError):
        SelectedRun(tmp_path / "invalid", ("yellow", "yellow"), input_mode="automation", **settings)
    assert not any((tmp_path / name).exists() for name in ("human", "computer", "invalid"))
