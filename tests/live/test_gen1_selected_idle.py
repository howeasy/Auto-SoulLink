"""Model checks for the tracked selected-run idle boundary; no live invocation."""

import asyncio
import hashlib
import inspect
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.live import gen1_selected_scenario as selected_scenario
from tests.live.gen1_scripted_host import prepare_scripted_plan, scripted_failure, scripted_progress
from tests.live.gen1_selected_scenario import (
    SelectedRun,
    drain_owned_handlers,
    verify_initial_save_file,
)


async def idle_enrollment(owned, *, emulator, base_config, limit=1800,
                          input_mode="human", launch_mode="product-cli", variants=("red", "blue")):
    """Explicit physical entry, invoked by a human outside pytest collection."""
    run = SelectedRun(owned, variants, emulator=emulator,
                      base_config=base_config, limit=limit, input_mode=input_mode,
                      launch_mode=launch_mode)
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


def test_scripted_host_prepares_checked_launcher_without_spawning(tmp_path):
    from server.bizhawk_launch import launch, manifest

    launcher = tmp_path / "launcher.lua"
    launcher.write_text("return true\n")
    rom = tmp_path / "slink_yellow.gb"
    rom.write_bytes(b"MODELED ROM")
    config = tmp_path / "base.ini"
    config.write_text('{"PathEntries":{"Paths":[{"Type":"Save RAM","System":"GB_GBC_SGB","Path":"old"}]}}')
    spec = manifest(run_id="a" * 32, player="a", profile="gambatte",
                    rom_sha1=hashlib.sha1(rom.read_bytes()).hexdigest(), launcher=launcher.read_text())
    result = prepare_scripted_plan(tmp_path / "owned", spec, rom=rom, launcher=launcher,
                                   base_config=config, bootstrap=Path(__file__).resolve().parents[2] /
                                   "lua/tests/gen1_scripted_new_game.lua")
    staged = Path(result["cwd"])
    assert (staged / "launcher.lua").read_bytes() == launcher.read_text().replace("\r\n", "\n").encode()
    assert (staged / "launch.json").is_file()
    assert result["arguments"][1] == "--lua=scripted_new_game.lua"
    assert result["environment"]["SLINK_SCRIPTED_INPUT"].startswith(str(tmp_path / "owned"))
    assert result["environment"]["SLINK_ROOT"] == str(Path(__file__).resolve().parents[2])
    assert result["environment"]["SLINK_CLIENT_STORAGE_ROOT"] == str((tmp_path / "owned").resolve())
    assert Path(result["environment"]["SLINK_SAVERAM_DIRECTORY"]).resolve() == (
        tmp_path / "owned" / spec["run_id"] / "a" / "SaveRAM").resolve()
    assert result["checked_launcher_sha256"] == spec["launcher_sha256"]
    fake_emulator = tmp_path / "EmuHawk.exe"
    fake_emulator.write_bytes(b"not qualified")
    with pytest.raises(ValueError, match="emulator executable differs"):
        launch(result, fake_emulator)


def test_rb_route_stages_only_test_module_beside_checked_launcher(tmp_path):
    from server.bizhawk_launch import manifest

    launcher = tmp_path / "launcher.lua"
    launcher.write_text("return true\n")
    rom = tmp_path / "slink_red.gb"
    rom.write_bytes(b"MODELED RED ROM")
    config = tmp_path / "base.ini"
    config.write_text('{"PathEntries":{"Paths":[{"Type":"Save RAM","System":"GB_GBC_SGB","Path":"old"}]}}')
    spec = manifest(run_id="a" * 32, player="a", profile="gambatte",
                    rom_sha1=hashlib.sha1(rom.read_bytes()).hexdigest(), launcher=launcher.read_text())
    plan = prepare_scripted_plan(tmp_path / "owned", spec, rom=rom, launcher=launcher,
                                 base_config=config, route_mode="rb-starter-rival")
    staged = Path(plan["cwd"])
    assert plan["arguments"][1] == "--lua=scripted_new_game.lua"
    assert hashlib.sha256((staged / "launcher.lua").read_bytes()).hexdigest() == spec["launcher_sha256"]
    assert (staged / "gen1_rb_ball_gate_inputs.lua").is_file()
    assert plan["rb_route_sha256"] == hashlib.sha256((staged / "gen1_rb_ball_gate_inputs.lua").read_bytes()).hexdigest()
    route = json.loads((staged / "scripted_input.json").read_text())["route"]
    assert route["mode"] == "rb-starter-rival"
    assert Path(route["handshake"]).parent == staged
    settings = {"emulator": tmp_path / "EmuHawk.exe", "base_config": config, "limit": 1800,
                "input_mode": "scripted-normal-buttons", "launch_mode": "scripted-selected-launcher",
                "route_mode": "rb-starter-rival"}
    run = SelectedRun(tmp_path / "selected", ("red", "blue"), **settings)
    assert run.outcome["route_mode"] == "rb-starter-rival"
    with pytest.raises(ValueError):
        SelectedRun(tmp_path / "wrong-pair", ("red", "yellow"), **settings)


def test_scripted_driver_failure_marker_is_read_from_owned_path(tmp_path):
    assert scripted_failure(tmp_path) is None
    marker = tmp_path / "scripted_failure.json"
    marker.write_text(json.dumps({"stage": "failure", "player": "a", "error": "no bounded progress"}))
    assert scripted_failure(tmp_path)["error"] == "no bounded progress"
    marker.write_text(json.dumps({"stage": "success", "error": "forged"}))
    with pytest.raises(ValueError):
        scripted_failure(tmp_path)
    assert scripted_progress(tmp_path) is None
    state = tmp_path / "scripted_progress.json"
    state.write_text(json.dumps({"stage": "normal-buttons", "boot_frames": 120}))
    assert scripted_progress(tmp_path)["boot_frames"] == 120
    state.write_text(json.dumps({"stage": "not-a-driver-state"}))
    with pytest.raises(ValueError):
        scripted_progress(tmp_path)


def test_scripted_marker_reader_treats_only_transient_absence_as_wait(tmp_path, monkeypatch):
    progress_file = tmp_path / "scripted_progress.json"
    failure_file = tmp_path / "scripted_failure.json"
    progress_file.write_text(json.dumps({"stage": "normal-buttons"}))
    failure_file.write_text(json.dumps({"stage": "failure", "error": "stopped"}))
    original = Path.read_text

    def transient(self, *args, **kwargs):
        if self in {progress_file, failure_file}:
            raise FileNotFoundError("publisher replaced marker between lookup and read")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transient)
    assert scripted_progress(tmp_path) is None
    assert scripted_failure(tmp_path) is None
    monkeypatch.setattr(Path, "read_text", original)
    progress_file.write_text("{malformed")
    with pytest.raises(json.JSONDecodeError):
        scripted_progress(tmp_path)
    failure_file.write_text("{malformed")
    with pytest.raises(json.JSONDecodeError):
        scripted_failure(tmp_path)


def test_scripted_launch_and_input_modes_are_explicit(tmp_path):
    settings = {"emulator": tmp_path / "EmuHawk.exe", "base_config": tmp_path / "config.ini", "limit": 1800}
    run = SelectedRun(tmp_path / "scripted", ("yellow", "yellow"),
                      input_mode="scripted-normal-buttons", launch_mode="scripted-selected-launcher", **settings)
    assert run.outcome["launch_mode"] == "scripted-selected-launcher"
    assert run.outcome["input_mode"] == "scripted-normal-buttons"
    assert run.outcome["human_inputs_only"] is False
    with pytest.raises(ValueError):
        SelectedRun(tmp_path / "mismatch", ("yellow", "yellow"),
                    input_mode="scripted-normal-buttons", launch_mode="product-cli", **settings)


@pytest.mark.parametrize("fault", ["none", "replacement", "no-progress", "held-advance"])
def test_scripted_lua_uses_only_owned_normal_boot_frames(tmp_path, fault):
    from lupa.lua54 import LuaError, LuaRuntime

    root = Path(__file__).resolve().parents[2]
    source = (root / "lua/tests/gen1_scripted_new_game.lua").read_text()
    lua = LuaRuntime(unpack_returned_tuples=True)
    assert callable(lua.eval('function(s) return load(s, "scripted-model") end')(source))
    symbols = {}
    for line in (root / ".cache/pret/pokeyellow/pokeyellow.sym").read_text().splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] in {
                "wMaxMenuItem", "wTopMenuItemY", "wTopMenuItemX", "wCurrentMenuItem"}:
            symbols[fields[1]] = int(fields[0].split(":")[1], 16)
    assert len(symbols) == 4
    inputs = {"schema": "gen1-scripted-normal-buttons-v1", "player": "a", "variant": "yellow",
              "rom_sha1": "a" * 40, "launcher": str(tmp_path / "launcher.lua"),
              "progress": str(tmp_path / "progress.json"), "failure": str(tmp_path / "failure.json"),
              "max_boot_frames": 2 if fault == "no-progress" else 20000,
              "deadline_seconds": 1800}
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps(inputs))
    frame = [0]
    held = [False]
    pressed = []
    status_checks = [0]
    after_stop = [None]
    def replacement_advance():
        frame[0] += 1

    def replacement_yield():
        return None
    globals_ = lua.globals()
    globals_.SLINK_ROOT = root.as_posix()
    globals_.gameinfo = lua.table_from({"getromhash": lambda: "a" * 40})
    globals_.joypad = lua.table_from({"set": lambda buttons: pressed.append(
        {key: bool(buttons[key]) for key in ("A", "Down", "Start")})})
    globals_.memory = lua.table_from({"read_u8": lambda address, _domain: (
        3 if address == symbols["wMaxMenuItem"] else
        2 if address == symbols["wTopMenuItemY"] else
        1 if address == symbols["wTopMenuItemX"] else
        (0 if frame[0] < 2 else 1))})
    globals_.emu = lua.table_from({"framecount": lambda: frame[0],
                                   "frameadvance": lambda: frame.__setitem__(0, frame[0] + 1),
                                   "yield": lambda: None})
    def status_now():
        status_checks[0] += 1
        return lua.table_from({
            "observation_loop": frame[0] >= 20, "phase": "waiting_for_overworld",
            "host": lua.table_from({"lease_owned": True, "owner_id": "owner", "held": held[0]}),
            "context": lua.table_from({"physical_instance": "owner"})})

    globals_.SLINK_RUNTIME_STATUS = status_now
    original_getenv = globals_.os.getenv
    globals_.os.getenv = lambda key: str(input_file) if key == "SLINK_SCRIPTED_INPUT" else original_getenv(key)
    original_dofile = globals_.dofile

    def dofile(path):
        if path == inputs["launcher"]:
            for index in range(22):
                if fault == "held-advance" and index == 2:
                    held[0] = True
                if fault in {"none", "replacement"} and index == 18:
                    before = frame[0]
                    held[0] = True
                    globals_.emu["yield"]()
                    assert frame[0] == before
                    held[0] = False
                if fault == "replacement" and index == 21:
                    globals_.emu.frameadvance = replacement_advance
                    globals_.emu["yield"] = replacement_yield
                globals_.emu.frameadvance()
                if fault in {"none", "replacement"} and index == 20:
                    after_stop[0] = (len(pressed), status_checks[0])
            return None
        return original_dofile(path)

    globals_.dofile = dofile
    if fault in {"no-progress", "held-advance"}:
        with pytest.raises(LuaError):
            lua.execute(source)
        failure = json.loads((tmp_path / "failure.json").read_text())
        assert failure["stage"] == "failure"
        assert ("bounded progress" if fault == "no-progress" else "clean native owner") in failure["error"]
        assert frame[0] == 2
        return
    lua.execute(source)
    assert frame == [22], "wrapper advanced a frame beyond the launcher calls"
    assert after_stop[0] == (len(pressed), status_checks[0]), (
        "wrapper continued injecting idle or polling status after input stopped")
    if fault == "replacement":
        assert globals_.emu.frameadvance == replacement_advance
        assert globals_.emu["yield"] == replacement_yield
    assert any(buttons["Down"] for buttons in pressed)
    assert any(buttons["A"] for buttons in pressed)
    assert pressed[-1] == {"A": False, "Down": False, "Start": False}
    assert json.loads((tmp_path / "progress.json").read_text())["stage"] == "input-stopped"
    assert not (tmp_path / "failure.json").exists()


@pytest.mark.asyncio
async def test_scripted_waits_for_both_delayed_input_stopped_markers(tmp_path, monkeypatch):
    owned = tmp_path / "owned"
    owned.mkdir()
    run = SelectedRun(owned, ("yellow", "yellow"), emulator=tmp_path / "EmuHawk.exe",
                      base_config=tmp_path / "config.ini", limit=1,
                      input_mode="scripted-normal-buttons", launch_mode="scripted-selected-launcher")
    run.outcome["manager"] = {"run_id": "manager", "session_id": "session"}
    run.jobs = [{"player": player} for player in ("a", "b")]
    for player in ("a", "b"):
        manifest = owned / f"{player}.json"
        manifest.write_text(json.dumps({"run_id": "a" * 32}))
        run.downloads[player] = {"manifest": manifest}
    journal = SimpleNamespace(snapshot=lambda: SimpleNamespace(state={"components": {}}),
                              pending_ids=lambda _player: [])
    run.runtime = SimpleNamespace(journal=journal, service_current=lambda: True)
    monkeypatch.setattr(selected_scenario, "observe", lambda _job: None)
    monkeypatch.setattr(selected_scenario, "emulator_child", lambda job, _emu: {"pid": job["player"]})
    monkeypatch.setattr(selected_scenario, "checked_events", lambda _runtime: [])

    async def publish_later():
        for player in ("a", "b"):
            await asyncio.sleep(0.04)
            directory = owned / "clients" / ("a" * 32) / player / "emulator"
            directory.mkdir(parents=True)
            (directory / "scripted_progress.json").write_text(json.dumps({
                "stage": "input-stopped", "player": player, "boot_frames": 20}))

    publisher = asyncio.create_task(publish_later())
    await run.wait(lambda _components, _pending: True, poll=0.01)
    assert publisher.done(), "wait returned before both drivers stopped input"
    assert set(run.outcome["scripted_driver_progress"]) == {"a", "b"}
