"""Preparation, attribution and mocked execution tests. No emulator is launched."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from lupa import LuaError, LuaRuntime

from tools import emulator_sandbox as sandbox
from tools.rr import native_gate as gate


@pytest.fixture
def spec(tmp_path):
    source = tmp_path / "source"
    emulator = tmp_path / "emulator" / "EmuHawk.exe"
    emulator.parent.mkdir()
    emulator.write_bytes(b"fake executable; tests never launch this")
    source.mkdir()
    script = source / "probe.lua"
    script.write_text('return function(ctx) ctx.check("probe_readback", memory.read_u8(0x02000001), 7) '
                      'ctx.report.evidence.runtime.note="quote\\\" and newline\\n" end', encoding="utf-8")
    config = emulator.parent / "config.ini"
    config.write_text(json.dumps({
        "PathEntries": {"Paths": [
            {"System": "GBA", "Type": name, "Path": "E:/live/" + name}
            for name in ("Base", "ROM", "Save RAM", "Savestates", "Screenshots", "Cheats")
        ] + [{"System": "Global", "Type": "Lua", "Path": "E:/live/Lua"}],
            "LastRomPath": "E:/live/rom"},
        "RecentLua": {"recentlist": ["E:/live/slink.lua"], "AutoLoad": True},
        "RecentLuaSession": {"recentlist": ["E:/live/session.luases"], "AutoLoad": True},
        "CommonToolSettings": {"LuaConsole": {"AutoLoad": True}},
        "CustomToolSettings": {"LuaConsole": {"LastPath": "E:/live/slink.lua"}},
        "TrustedExtTools": {"E:/live/tool.dll": True},
        "SingleInstanceMode": True, "AcceptBackgroundInputControllerOnly": True,
        "Nested": {"AutoLoadAnything": True, "LastToolFile": "E:/live/slink.lua"},
        "Cheats": {"LoadFileByGame": True, "AutoSaveOnClose": True},
    }), encoding="utf-8")
    rom = tmp_path / "input.gba"
    rom.write_bytes(bytes(64) + b"SLD2test" + bytes(64))
    sync = sandbox.json_bytes({"o": {"$type": "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk+SyncSettings, X",
                                    "RTCUseRealTime": False, "SkipBios": True}})
    fixture = tmp_path / "fixture.State"
    with zipfile.ZipFile(fixture, "w") as z:
        z.writestr("BizVersion.txt", "Version 2.11.1\r\n")
        z.writestr("SyncSettings.json", sync)
        z.writestr("Core.bin", b"fake core state, not an emulator fixture")
    sidecar = tmp_path / "fixture.json"
    sidecar.write_bytes(sandbox.json_bytes({
        "schema": "slink-rr-fixture-v1", "kind": "state", "system": "GBA", "core": "mGBA",
        "scene": "controlled test fixture", "rom_sha256": sandbox.identity(rom)["sha256"],
        "fixture_sha256": sandbox.identity(fixture)["sha256"],
        "emulator_sha256": sandbox.identity(emulator)["sha256"], "emulator_version": "2.11.1",
        "sync_settings_sha256": sandbox.digest(sync),
    }))
    return gate.GateSpec(emulator=emulator, emulator_version="2.11.1", base_config=config,
                         rom=rom, fixture=fixture, fixture_manifest=sidecar, source_root=source,
                         script="probe.lua", output_root=tmp_path / "private", run_id="case01",
                         player="a", required_assertions=("probe_readback",), frames=10)


@pytest.mark.parametrize("relative", ["../escape", "a/../../escape", "a\\..\\escape", "/absolute",
                                     "C:/escape", "C:escape", "a//b", ".", ""])
def test_containment_rejects_both_path_syntaxes(tmp_path, relative):
    with pytest.raises(sandbox.SandboxError):
        sandbox.child_path(tmp_path, relative)


@pytest.mark.parametrize("run_id", ["../live", "with space", "x/y", "x\\y", "", "a" * 65])
def test_invalid_run_id_does_not_create_files(spec, run_id):
    with pytest.raises(sandbox.SandboxError, match="run_id"):
        gate.prepare_gate(replace(spec, run_id=run_id))
    assert not spec.output_root.exists()


def test_preparation_is_private_and_originals_immutable(spec):
    originals = [sandbox.identity(path) for path in (spec.rom, spec.fixture, spec.base_config,
                                                    spec.source_root / spec.script)]
    path = gate.prepare_gate(spec)
    prepared = gate.verify_preparation(path)
    root = path.parent
    assert prepared["phase"] == "prepared_not_executed"
    assert prepared["command"][1:] == ["--config=config.json", "--lua=launcher.lua", "rom/rrgate.gba"]
    assert all(" " not in arg for arg in prepared["command"][1:])
    for pair in prepared["copies"].values():
        assert root in Path(pair["copy"]["path"]).parents
        assert pair["original"]["sha256"] == pair["copy"]["sha256"]
        assert pair["original"]["path"] != pair["copy"]["path"]
    config = json.loads((root / "config.json").read_text())
    assert config["RecentLua"]["recentlist"] == [] and config["RecentLua"]["AutoLoad"] is False
    assert config["RecentLuaSession"]["AutoLoad"] is False
    assert config["CommonToolSettings"] == config["CustomToolSettings"] == config["TrustedExtTools"] == {}
    assert config["Nested"] == {"AutoLoadAnything": False, "LastToolFile": ""}
    assert config["Cheats"]["LoadFileByGame"] is False
    assert config["SpeedPercent"] == config["SpeedPercentAlternate"] == 100
    assert config["FrameSkip"] == 0 and config["Unthrottled"] is False
    assert config["Rewind"]["Enabled"] is False
    assert config["SingleInstanceMode"] is False and config["AcceptBackgroundInputControllerOnly"] is False
    for entry in config["PathEntries"]["Paths"]:
        assert root in Path(entry["Path"]).parents
    for original in originals:
        sandbox.verify_identity(original)


def test_two_players_have_distinct_paths_and_run_cannot_be_reused(spec):
    a = gate.prepare_gate(spec)
    b = gate.prepare_gate(replace(spec, player="b"))
    assert a.parent != b.parent
    assert json.loads(a.read_text())["config"]["sha256"] != json.loads(b.read_text())["config"]["sha256"]
    with pytest.raises(FileExistsError):
        gate.prepare_gate(spec)


def test_preparation_rejects_output_inside_source_or_emulator(spec):
    for root in (spec.source_root / "output", spec.emulator.parent / "output"):
        with pytest.raises(sandbox.SandboxError, match="protected"):
            gate.prepare_gate(replace(spec, output_root=root))


def test_config_without_gba_paths_is_rejected(spec):
    spec.base_config.write_text('{"PathEntries":{"Paths":[{"Type":"Base","System":"GB"}]}}')
    with pytest.raises(sandbox.SandboxError, match="Missing GBA"):
        gate.prepare_gate(spec)


@pytest.mark.parametrize("field,value,match", [
    ("rom_sha256", "0" * 64, "another ROM"),
    ("fixture_sha256", "0" * 64, "Fixture hash"),
    ("emulator_sha256", "0" * 64, "emulator identity"),
    ("sync_settings_sha256", "0" * 64, "sync-settings"),
])
def test_incompatible_fixture_is_rejected_before_copy(spec, field, value, match):
    metadata = json.loads(spec.fixture_manifest.read_text())
    metadata[field] = value
    spec.fixture_manifest.write_bytes(sandbox.json_bytes(metadata))
    with pytest.raises(sandbox.SandboxError, match=match):
        gate.prepare_gate(spec)
    assert not spec.output_root.exists()


def test_stale_version_inside_state_is_rejected(spec):
    with zipfile.ZipFile(spec.fixture) as z:
        sync = z.read("SyncSettings.json")
    with zipfile.ZipFile(spec.fixture, "w") as z:
        z.writestr("BizVersion.txt", "Version 2.9.1")
        z.writestr("SyncSettings.json", sync)
        z.writestr("Core.bin", b"fake")
    metadata = json.loads(spec.fixture_manifest.read_text())
    metadata["fixture_sha256"] = sandbox.identity(spec.fixture)["sha256"]
    spec.fixture_manifest.write_bytes(sandbox.json_bytes(metadata))
    with pytest.raises(sandbox.SandboxError, match="Stale savestate"):
        gate.prepare_gate(spec)


def test_battery_naming_uses_database_hash_or_ascii_fallback(spec, tmp_path):
    db = tmp_path / "gamedb"
    db.mkdir()
    data = spec.rom.read_bytes()
    sha1 = hashlib.sha1(data).hexdigest().upper()
    table = db / "gamedb_gba.txt"
    table.write_text(f"{sha1}\t!\tKnown RR Name\tGBA\t\n")
    resolved = sandbox.database_saveram_name(data, db)
    assert resolved["filename"] == "Known RR Name.SaveRAM"
    assert resolved["in_database"] is True
    table.write_text("0" * 40 + "\t!\tDifferent game\tGBA\t\n")
    assert sandbox.database_saveram_name(data, db)["filename"] == "rrgate.SaveRAM"


def test_battery_seed_and_original_fixture_are_separate(spec, tmp_path):
    fixture = tmp_path / "battery.SaveRAM"
    fixture.write_bytes(b"\x01" + bytes(131087))
    metadata = {"schema": "slink-rr-fixture-v1", "kind": "battery", "system": "GBA", "core": "mGBA",
                "scene": "known party", "fixture_sha256": sandbox.identity(fixture)["sha256"],
                "rom_sha256": sandbox.identity(spec.rom)["sha256"],
                "ram_assertions": [{"address": 0x02024029, "width": 1, "expected": 2}]}
    spec.fixture_manifest.write_bytes(sandbox.json_bytes(metadata))
    db = tmp_path / "db"
    db.mkdir()
    (db / "gba.txt").write_text("0" * 40 + "\t!\tOther game\tGBA\t\n")
    path = gate.prepare_gate(replace(spec, fixture=fixture, game_db_dir=db))
    prepared = gate.verify_preparation(path)
    seed = Path(prepared["copies"]["seeded_battery"]["copy"]["path"])
    assert seed.read_bytes() == fixture.read_bytes()
    seed.write_bytes(b"runtime changed this private copy")
    gate.verify_preparation(path, after_execution=True)
    sandbox.verify_identity(prepared["copies"]["seeded_battery"]["original"])
    with pytest.raises(sandbox.SandboxError, match="changed"):
        gate.verify_preparation(path)


def test_prepared_source_drift_and_command_tampering_are_rejected(spec):
    path = gate.prepare_gate(spec)
    prepared = json.loads(path.read_text())
    prepared["command"][1] = "--config=E:/live/config.ini"
    path.write_bytes(sandbox.json_bytes(prepared))
    with pytest.raises(sandbox.SandboxError, match="private launcher"):
        gate.verify_preparation(path)
    prepared["command"][1] = "--config=config.json"
    path.write_bytes(sandbox.json_bytes(prepared))
    (spec.source_root / spec.script).write_text("changed source")
    with pytest.raises(sandbox.SandboxError, match="changed"):
        gate.verify_preparation(path)


def _valid_result(prepared):
    return {"schema": gate.RESULT_SCHEMA, "purpose": prepared["purpose"], "identity": copy.deepcopy(prepared["identity"]),
            "complete": True, "release_ready": False,
            "observed": {"rom_sha1": prepared["identity"]["rom_sha1"],
                         "emulator_version": prepared["identity"]["emulator_version"], "system": "GBA"},
            "assertions": [{"id": name, "kind": "structural", "actual": True,
                            "expected": True, "passed": True} for name in prepared["required_assertions"]]}


@pytest.mark.parametrize("problem", ["missing", "naked_pass", "wrong_identity", "missing_assertion",
                                     "failed_assertion", "lying_assertion", "duplicate_assertion", "incomplete",
                                     "wrong_observed_rom", "boolean_is_not_one", "duplicate_json_key"])
def test_missing_or_malformed_results_never_pass(spec, problem):
    prepared = gate.verify_preparation(gate.prepare_gate(spec))
    result = _valid_result(prepared)
    path = Path(prepared["result_path"])
    if problem == "missing":
        pass
    elif problem == "naked_pass":
        path.write_text('"RESULT: PASS"')
    elif problem == "duplicate_json_key":
        path.write_text('{"schema":"wrong","schema":"' + gate.RESULT_SCHEMA + '"}')
    else:
        if problem == "wrong_identity":
            result["identity"]["run_id"] = "another_run"
        elif problem == "missing_assertion":
            result["assertions"].pop()
        elif problem == "failed_assertion":
            result["assertions"][0]["passed"] = False
        elif problem == "lying_assertion":
            result["assertions"][0]["actual"] = False
        elif problem == "duplicate_assertion":
            result["assertions"].append(result["assertions"][0])
        elif problem == "incomplete":
            result["complete"] = False
        elif problem == "wrong_observed_rom":
            result["observed"]["rom_sha1"] = "0" * 40
        elif problem == "boolean_is_not_one":
            result["assertions"][0]["actual"] = 1
        path.write_bytes(sandbox.json_bytes(result))
    with pytest.raises((sandbox.SandboxError, ValueError)):
        gate.validate_result(prepared)


def test_generated_lua_wrapper_executes_under_stubs_and_emits_real_json(spec):
    script = spec.source_root / spec.script
    script.write_text(script.read_text().replace("ctx.report.evidence.runtime.note=",
                      'ctx.checkpoint("observed_not_complete"); ctx.report.evidence.runtime.note='))
    prepared_path = gate.prepare_gate(spec)
    prepared = gate.verify_preparation(prepared_path)
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().client = {"getversion": lambda: "2.11.1", "exit": lambda: None}
    runtime.globals().emu = {"getsystemid": lambda: "GBA"}
    runtime.globals().gameinfo = {"getromhash": lambda: "SHA1:" + prepared["identity"]["rom_sha1"]}
    runtime.globals().savestate = {"load": lambda _: True}
    runtime.globals().memory = {"usememorydomain": lambda _: None, "read_u8": lambda _: 7}
    runtime.execute(Path(prepared["launcher"]["path"]).read_text(encoding="utf-8"))
    result = gate.validate_result(prepared)
    assert result["evidence"]["runtime"]["note"] == 'quote" and newline\n'
    assert result["release_ready"] is False
    partial = Path(prepared["result_path"]).with_name("result_progress.json")
    progress = json.loads(partial.read_text())
    assert progress["complete"] is False and progress["phase"] == "observed_not_complete"
    assert progress["identity"] == prepared["identity"]
    with pytest.raises(sandbox.SandboxError, match="does not belong"):
        gate.validate_result(prepared, partial)
    Path(prepared["result_path"]).write_bytes(partial.read_bytes())
    with pytest.raises(sandbox.SandboxError, match="did not complete"):
        gate.validate_result(prepared)


@pytest.mark.parametrize("mismatch", [None, "core_type", "native_module", "unavailable"])
def test_running_core_evidence_is_compared_with_reviewed_fixture(spec, mismatch):
    expected = {"available": True, "core_type": "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk",
                "matches_requested_core": True, "module_query_available": True,
                "core_assembly_file": {"sha256": "1" * 64}, "native_modules": [{"sha256": "2" * 64}]}
    meta = json.loads(spec.fixture_manifest.read_text())
    meta["host"] = expected
    spec.fixture_manifest.write_bytes(sandbox.json_bytes(meta))
    with pytest.raises(sandbox.SandboxError, match="explicit host_identity"):
        gate.prepare_gate(spec)
    actual = copy.deepcopy(expected)
    if mismatch == "core_type":
        actual["core_type"] = "WrongCore"
    elif mismatch == "native_module":
        actual["native_modules"][0]["sha256"] = "3" * 64
    elif mismatch == "unavailable":
        actual["available"] = False
    helper = spec.source_root / gate.HOST_IDENTITY_HELPER
    helper.parent.mkdir(parents=True)
    helper.write_text("return {capture=function(core) return " + gate._lua_literal(actual) + ",nil end}")
    prepared = gate.verify_preparation(gate.prepare_gate(replace(spec, source_files=(gate.HOST_IDENTITY_HELPER,))))
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().client = {"getversion": lambda: "2.11.1", "exit": lambda: None}
    runtime.globals().emu = {"getsystemid": lambda: "GBA"}
    runtime.globals().gameinfo = {"getromhash": lambda: prepared["identity"]["rom_sha1"]}
    runtime.globals().savestate = {"load": lambda _: True}
    runtime.globals().memory = {"usememorydomain": lambda _: None, "read_u8": lambda _: 7}
    runtime.execute(Path(prepared["launcher"]["path"]).read_text(encoding="utf-8"))
    if mismatch:
        with pytest.raises(sandbox.SandboxError, match="did not complete"):
            gate.validate_result(prepared)
    else:
        assert gate.validate_result(prepared)["observed"]["host"] == expected


def test_host_identity_unavailable_is_explicit_partial_evidence():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    source = Path(__file__).parents[2] / gate.HOST_IDENTITY_HELPER
    module = runtime.execute(source.read_text(encoding="utf-8"))
    host, main_form = module.capture("mGBA")
    assert host.available is False and host.error and main_form is None


@pytest.mark.parametrize("missing_control", [None, "read_callback2", "write_beacon", "exec_frame_control"])
def test_exact_callback_capability_requires_real_controls_and_cleans_up(missing_control):
    runtime = LuaRuntime(unpack_returned_tuples=True)
    hooks, frame = {}, [0]

    def register(callback, address, name, scope):
        assert address is not None and scope == "System Bus"
        hooks[name] = callback
        return "control:" + name

    def advance():
        frame[0] += 1
        for name, address in (("read_callback2", 0x030030F4), ("write_beacon", 0x0203F800),
                              ("exec_frame_control", 0x0800051A)):
            if name != missing_control:
                hooks[name](address, 0, 1)
        # Interior watchpoint can dispatch another base-address callback; its
        # own callback may have zero hits despite successful registration.
        if missing_control != "write_beacon":
            hooks["write_beacon"](0x0203F800, 0x4B4E4C53, 2)

    def check(name, actual, expected):
        if actual != expected:
            raise RuntimeError(name)

    runtime.globals().event = {"on_bus_read": register, "on_bus_write": register, "on_bus_exec": register,
                               "unregisterbyid": lambda key: hooks.pop(key.removeprefix("control:"), None) is not None}
    runtime.globals().emu = {"framecount": lambda: frame[0], "frameadvance": advance,
                             "getregisters": lambda: runtime.table_from({"R15": 0x0800051E, "CPSR": 0x3F}),
                             "getregister": lambda name: 0x3F if name == "CPSR" else 0x0800051E,
                             "totalexecutedcycles": lambda: frame[0] * 280896}
    runtime.globals().memory = {"read_u8": lambda address: 0}
    config = runtime.table_from({"purpose": "validation", "fixture_kind": "state", "frames": 2,
                                  "descriptor": runtime.table_from({"address": 0x08000000, "size": 4,
                                                                    "hex": "00000000"})})
    context = runtime.table_from({"config": config, "check": check, "checkpoint": lambda phase: None,
                                   "report": runtime.table_from({"evidence": runtime.table()})})
    source = Path(__file__).parents[2] / "lua/tests/rr/callback_capability_probe.lua"
    probe = runtime.execute(source.read_text(encoding="utf-8"))
    if missing_control:
        with pytest.raises((RuntimeError, LuaError), match="exact_.*_observed"):
            probe(context)
    else:
        probe(context)
        out = context.report.evidence.runtime
        assert out.classification == "exact_callback_capability_only"
        assert out.hits.write_plus_one_diagnostic == 0 and out.hits.write_beacon == 4
        assert out.trace[1].raw_pc == 0x0800051E and out.trace[1].raw_cpsr == 0x3F
        assert out.arena_ownership == "unresolved" and out.release_ready is False
    assert not hooks


def test_windows_startup_is_hidden(monkeypatch):
    monkeypatch.setattr(subprocess, "STARTUPINFO", lambda: SimpleNamespace(dwFlags=0, wShowWindow=1), raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    result = sandbox.hidden_process_kwargs("nt")
    assert result["startupinfo"].wShowWindow == 0
    assert result["startupinfo"].dwFlags & 1
    assert result["creationflags"] == 0x08000000


def test_launch_api_uses_only_private_arguments_and_cleans_slink_environment(spec, monkeypatch):
    path = gate.prepare_gate(spec)
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=100)

    api = SimpleNamespace(Process=lambda _: SimpleNamespace(create_time=lambda: 123))
    monkeypatch.setenv("SLINK_ROOT", "E:/live")
    monkeypatch.setenv("SLINK_HOST", "live.example.invalid")
    monkeypatch.setenv("LUA_PATH", "E:/live/?.lua")
    process, owned = gate.launch_prepared(path, popen=fake_popen, process_api=api)
    assert process.pid == owned.pid == 100
    assert owned.created == 123
    command, kwargs = calls[0]
    assert command[1:] == ["--config=config.json", "--lua=launcher.lua", "rom/rrgate.gba"]
    assert kwargs["cwd"] == path.parent
    assert kwargs["env"]["SLINK_ROOT"] == str(path.parent / "source")
    assert "SLINK_HOST" not in kwargs["env"] and "LUA_PATH" not in kwargs["env"]


def test_native_descriptor_is_bound_to_selected_image(spec, tmp_path):
    manifest = tmp_path / "native.json"
    data = {"rom_sha256": sandbox.identity(spec.rom)["sha256"],
            "descriptor_address": 0x08000040, "descriptor_size": 8, "build_id": "candidate"}
    manifest.write_bytes(sandbox.json_bytes(data))
    path = gate.prepare_gate(replace(spec, native_manifest=manifest))
    assert "534c443274657374" in Path(json.loads(path.read_text())["launcher"]["path"]).read_text()
    data["rom_sha256"] = "0" * 64
    manifest.write_bytes(sandbox.json_bytes(data))
    with pytest.raises(sandbox.SandboxError, match="does not match"):
        gate.prepare_gate(replace(spec, native_manifest=manifest, run_id="other"))


def test_native_source_manifest_is_checked_and_snapshotted(spec, tmp_path):
    native_source = spec.source_root / "patch/src/handlers.c"
    native_source.parent.mkdir(parents=True)
    native_source.write_text("/* controlled source */")
    manifest = tmp_path / "native.json"
    manifest.write_bytes(sandbox.json_bytes({
        "rom_sha256": sandbox.identity(spec.rom)["sha256"],
        "descriptor_address": 0x08000040, "descriptor_size": 8,
        "native_inputs": {"src/handlers.c": sandbox.identity(native_source)["sha256"]},
    }))
    path = gate.prepare_gate(replace(spec, native_manifest=manifest))
    prepared = gate.verify_preparation(path)
    assert "source:patch/src/handlers.c" in prepared["copies"]
    native_source.write_text("/* changed after build */")
    with pytest.raises(sandbox.SandboxError, match="differs from build"):
        gate.prepare_gate(replace(spec, native_manifest=manifest, run_id="changed"))


def test_cleanup_is_pid_and_creation_time_scoped():
    events = []

    class FakeProcess:
        def __init__(self, pid, created):
            self.pid, self.created = pid, created

        def create_time(self):
            return self.created

        def children(self, recursive):
            assert recursive is True
            return [processes[101]]

        def terminate(self):
            events.append((self.pid, "terminate"))

        def wait(self, timeout):
            assert timeout == 5

    processes = {100: FakeProcess(100, 1), 101: FakeProcess(101, 2), 999: FakeProcess(999, 9)}
    api = SimpleNamespace(Process=lambda pid: processes[pid], NoSuchProcess=ProcessLookupError,
                          TimeoutExpired=TimeoutError)
    owned = sandbox.capture_owned_tree(sandbox.ProcessIdentity(100, 1), api)
    assert [p.pid for p in owned] == [101, 100]
    processes[101].created = 3  # PID reuse must never kill the replacement.
    assert sandbox.terminate_owned(owned, api) == [100]
    assert events == [(100, "terminate")]


def test_arena_probe_parses_without_running_it():
    source = Path(__file__).parents[2] / "lua/tests/rr/arena_probe.lua"
    runtime = LuaRuntime(unpack_returned_tuples=True)
    parse = runtime.eval("function(code) local f,e=load(code); return f~=nil,e end")
    ok, error = parse(source.read_text(encoding="utf-8"))
    assert ok, error


@pytest.mark.parametrize("battery", [False, True])
def test_arena_legacy_wildcard_preparation_is_rejected_before_boot_or_registration(battery):
    """Old runner configurations must not silently acquire successor coverage."""
    source = Path(__file__).parents[2] / "lua/tests/rr/arena_probe.lua"
    runtime = LuaRuntime(unpack_returned_tuples=True)

    def check(name, actual, expected):
        if actual != expected:
            raise RuntimeError(name)

    # No core/registration APIs are installed: reaching either is a test failure.
    report = runtime.table_from({"evidence": runtime.table()})
    config = runtime.table_from({"fixture_kind": "battery" if battery else "state", "frames": 3})
    context = runtime.table_from({"config": config,
                                  "report": report, "check": check})
    probe = runtime.execute(source.read_text(encoding="utf-8"))
    with pytest.raises(RuntimeError, match="arena_explicit_lane"):
        probe(context)
    evidence = report.evidence.runtime
    assert evidence.frames == 0 and len(evidence.registration_attempts) == 0
    assert evidence.ownership == "unresolved" and evidence.release_ready is False


def test_unverified_candidate_discovery_cannot_qualify_as_native_validation(spec, tmp_path):
    fixture = tmp_path / "candidate.SaveRAM"
    fixture.write_bytes(b"\x01" + bytes(131087))
    spec.fixture_manifest.write_bytes(sandbox.json_bytes({
        "schema": "slink-rr-fixture-candidate-v1", "kind": "battery", "system": "GBA", "core": "mGBA",
        "scene": "unknown historical battery", "fixture_sha256": sandbox.identity(fixture)["sha256"],
        "compatibility": "unverified", "provenance": {"origin": "controlled test bytes"},
    }))
    probe = spec.source_root / "lua/tests/rr/fixture_probe.lua"
    probe.parent.mkdir(parents=True)
    probe.write_text("return function(ctx) end")
    db = tmp_path / "db"
    db.mkdir()
    (db / "gba.txt").write_text("0" * 40 + "\t!\tOther game\tGBA\n")
    candidate = replace(spec, fixture=fixture, script="lua/tests/rr/fixture_probe.lua", game_db_dir=db,
                        purpose="fixture_discovery", required_assertions=("fixture_observation_complete",))
    prepared = gate.verify_preparation(gate.prepare_gate(candidate))
    result = _valid_result(prepared)
    result["fixture_compatibility"] = "unverified"
    Path(prepared["result_path"]).write_bytes(sandbox.json_bytes(result))
    assert gate.validate_observation(prepared)["fixture_compatibility"] == "unverified"
    assert "fixture_loaded" not in prepared["required_assertions"]
    with pytest.raises(sandbox.SandboxError, match="Candidate discovery"):
        gate.validate_result(prepared)
    with pytest.raises(sandbox.SandboxError, match="identity sidecar"):
        gate.prepare_gate(replace(candidate, purpose="validation", run_id="invalid"))
    result["fixture_compatibility"] = "verified"
    Path(prepared["result_path"]).write_bytes(sandbox.json_bytes(result))
    with pytest.raises(sandbox.SandboxError, match="must not claim"):
        gate.validate_observation(prepared)


def test_fixture_probe_parses_without_emulator_execution():
    source = Path(__file__).parents[2] / "lua/tests/rr/fixture_probe.lua"
    runtime = LuaRuntime(unpack_returned_tuples=True)
    parse = runtime.eval("function(code) local f,e=load(code); return f~=nil,e end")
    ok, error = parse(source.read_text(encoding="utf-8"))
    assert ok, error


@pytest.mark.parametrize("options", [{"steps": [{"frames": 720}]},
                                     {"steps": [{"frames": True}]},
                                     {"steps": [{"frames": 5, "buttons": {"Start": 1}}]},
                                     {"steps": [{"frames": 5, "buttons": {"Unreviewed": True}}]}])
def test_discovery_invalid_steps_fail_before_any_file_copy(spec, options):
    candidate = replace(spec, purpose="fixture_discovery", script="lua/tests/rr/fixture_probe.lua", probe_options=options)
    with pytest.raises(sandbox.SandboxError, match="Discovery step|Unsupported discovery"):
        gate.prepare_gate(candidate)
    assert not spec.output_root.exists()


@pytest.mark.parametrize("options", [{"host_hold_ms": True}, {"host_hold_ms": 2001},
                                     {"host_hold_ms": -1}, {"stop_at_field": 1},
                                     {"host_pause_before_hold": 1}, {"host_pause_before_hold": True}])
def test_discovery_host_options_rejected_before_file_copy(spec, options):
    candidate = replace(spec, purpose="fixture_discovery", script="lua/tests/rr/fixture_probe.lua", probe_options=options)
    with pytest.raises(sandbox.SandboxError, match="Discovery"):
        gate.prepare_gate(candidate)
    assert not spec.output_root.exists()


@pytest.mark.parametrize("steps", [None, [{"frames": True}], [{"frames": 601}],
                                   [{"frames": 1, "buttons": {"A": 1}}],
                                   [{"frames": 1, "buttons": {"Fake": True}}],
                                   [{"frames": 600}] * 7])
def test_battery_boot_input_contract_rejects_unbounded_or_ambiguous_inputs(steps):
    with pytest.raises(sandbox.SandboxError, match="Battery boot|battery boot"):
        gate._validate_boot_inputs(steps)


@pytest.mark.parametrize("unsupported_lane", ["wildcard_reads_writes", "exact_controls"])
def test_arena_does_not_infer_the_successor_lane_from_other_probe_names(unsupported_lane):
    source = Path(__file__).parents[2] / "lua/tests/rr/arena_probe.lua"
    runtime = LuaRuntime(unpack_returned_tuples=True)
    def check(name, actual, expected):
        if actual != expected:
            raise RuntimeError("rejected " + name)

    config = runtime.table_from({"probe_options": runtime.table_from({"arena_lane": unsupported_lane})})
    context = runtime.table_from({"config": config,
                                  "report": runtime.table_from({"evidence": runtime.table()}), "check": check})
    probe = runtime.execute(source.read_text(encoding="utf-8"))
    with pytest.raises(RuntimeError, match="arena_explicit_lane"):
        probe(context)
    assert len(context.report.evidence.runtime.registration_attempts) == 0
