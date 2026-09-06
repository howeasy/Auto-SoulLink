"""Duo preparation uses private files; these tests do not launch an emulator."""
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import e2e_duo as duo
from emulator_sandbox import ProcessIdentity, SandboxError, terminate_owned


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root = tmp_path / "repo with spaces"
    build = root / "patch/build"
    build.mkdir(parents=True)
    emulator = tmp_path / "emulator"
    emulator.mkdir()
    config = emulator / "config.ini"
    base = {"PathEntries": {"Paths": [{"System": "GBA", "Type": kind, "Path": value}
            for kind, value in [("Base", "./GBA"), ("ROM", "./ROM"), ("Save RAM", "./SaveRAM"),
                                ("Savestates", "./State"), ("Screenshots", "./Screenshots"), ("Cheats", "./Cheats")]]},
            "CommonToolSettings": {"LuaConsole": {"AutoLoad": True}}, "LoadLastRom": True}
    config.write_text(json.dumps(base))
    (build / "slink_RR.gba").write_bytes(b"synthetic ROM fixture")
    state_dir = emulator / "GBA/State"
    state_dir.mkdir(parents=True)
    state_name = duo.SCENARIOS["faint"]["savestate"]
    assert isinstance(state_name, str)
    state = state_dir / state_name
    with zipfile.ZipFile(state, "w") as archive:
        archive.writestr("Core.bin", b"synthetic core state")
        archive.writestr("SyncSettings.json", json.dumps({"o": {"$type":
            "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk+SyncSettings, BizHawk.Emulation.Cores", "SkipBios": True}}))
    monkeypatch.setattr(duo, "REPO", str(root))
    monkeypatch.setattr(duo, "WT_FWD", root.as_posix())
    monkeypatch.setattr(duo, "BUILD", str(build))
    monkeypatch.setattr(duo, "BIZHAWK_CONFIG", str(config))
    monkeypatch.setattr(duo, "EMUHAWK", str(emulator / "EmuHawk.exe"))
    monkeypatch.setattr(duo, "SAVESTATE_DIR", str(state_dir))
    monkeypatch.setattr(duo, "free_port", lambda: 32123)
    monkeypatch.setattr(duo.DuoRun, "_remember_process", lambda self, process: None)
    calls = []
    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=1234, wait=lambda timeout=None: 0)
    monkeypatch.setattr(duo.subprocess, "Popen", spawn)
    def create():
        return duo.DuoRun("faint", SimpleNamespace(game="gen3_rr", keep_data=True, server_flags=[]))
    return root, config, state, calls, create


def test_two_invocations_cannot_share_config_saves_results_or_synchronization(isolated):
    root, original_config, state, calls, create = isolated
    before = original_config.read_bytes(), state.read_bytes()
    first, second = create(), create()
    first.start_instances()
    second.start_instances()
    from lupa import LuaRuntime
    for run in (first, second):
        for player, folder in run.instance_dirs.items():
            LuaRuntime().compile((folder / f"duo_{player}.lua").read_text())
    assert len(calls) == 4
    directories = [folder for run in (first, second) for folder in run.instance_dirs.values()]
    assert len(set(directories)) == 4
    for run in (first, second):
        for player, folder in run.instance_dirs.items():
            config = json.loads((folder / f"duo_cfg_{player}.ini").read_bytes())
            assert config["PreferredCores"]["GBA"] == "mGBA"
            assert not config["CommonToolSettings"] and not config["LoadLastRom"]
            assert all(Path(entry["Path"]).is_relative_to(folder) for entry in config["PathEntries"]["Paths"])
            assert Path(run.go_files[player]).parent == folder
            assert Path(run._result_path(player)).parent == folder
    Path(first._result_path("a")).write_text("RESULT: PASS")
    (root / "patch/build/e2e_faint_a_result.txt").write_text("RESULT: PASS")
    assert first._read_result("a") == "RESULT: PASS"
    assert second._read_result("a") is None
    assert before == (original_config.read_bytes(), state.read_bytes())
    assert all(" " not in argument for command, _ in calls for argument in command[1:])


def test_unknown_state_core_is_rejected_before_any_emulator_launch(isolated):
    _, _, state, calls, create = isolated
    with zipfile.ZipFile(state, "w") as archive:
        archive.writestr("Core.bin", b"state")
        archive.writestr("SyncSettings.json", '{"o":{"$type":"unqualified core"}}')
    with pytest.raises(RuntimeError, match="expected mGBA format"):
        create().start_instances()
    assert calls == []


def test_cleanup_detects_changed_immutable_inputs(isolated):
    _, config, _, _, create = isolated
    run = create()
    run.start_instances()
    config.write_text("changed outside the runner")
    with pytest.raises(SandboxError, match="Immutable input changed"):
        run.cleanup(False)
    assert Path(run.data_dir).exists()


def test_server_parent_log_handle_closes_after_spawn(isolated, monkeypatch):
    _, _, _, calls, create = isolated
    monkeypatch.setattr(duo, "wait_for", lambda *args: True)
    create().start_server()
    assert calls[0][1]["stdout"].closed


def test_pid_reuse_never_terminates_the_replacement_process():
    class Unexpected(Exception):
        pass
    process = SimpleNamespace(create_time=lambda: 2, terminate=lambda: pytest.fail("unrelated PID was terminated"))
    api = SimpleNamespace(Process=lambda pid: process, NoSuchProcess=Unexpected, TimeoutExpired=TimeoutError)
    assert terminate_owned([ProcessIdentity(1234, 1)], process_api=api) == []


def test_original_save_hashes_and_new_save_files_are_checked(isolated):
    _, config, _, _, create = isolated
    directory = config.parent / "GBA/SaveRAM"
    directory.mkdir()
    original = directory / "my-game.SaveRAM"
    original.write_bytes(b"user save")
    run = create()
    run.start_instances()
    assert any(item["path"] == str(original.resolve()) for item in run._inputs)
    (directory / "unexpected.SaveRAM").write_bytes(b"unexpected write")
    with pytest.raises(RuntimeError, match="Save RAM directory changed"):
        run.cleanup(False)
    assert original.read_bytes() == b"user save"


def test_partial_launch_failure_cleans_only_the_started_owned_process(isolated, monkeypatch):
    _, _, _, _, create = isolated
    attempts, stopped = [], []
    def spawn(command, **kwargs):
        attempts.append(command)
        if len(attempts) == 2:
            raise OSError("second launch failed")
        return SimpleNamespace(pid=1234, wait=lambda timeout=None: 0)
    monkeypatch.setattr(duo.subprocess, "Popen", spawn)
    monkeypatch.setattr(duo.DuoRun, "_remember_process", lambda self, process: self._owned_processes.append(ProcessIdentity(process.pid, 1)))
    monkeypatch.setattr(duo, "capture_owned_tree", lambda process: [process])
    monkeypatch.setattr(duo, "terminate_owned", lambda processes: stopped.extend(process.pid for process in processes))
    run = create()
    with pytest.raises(OSError, match="second launch"):
        run.start_instances()
    run.cleanup(False)
    assert stopped == [1234]
    assert Path(run.data_dir).exists()


def test_locked_temporary_directory_is_reported_with_results_preserved(isolated, monkeypatch):
    root, _, _, _, create = isolated
    run = create()
    run.args.keep_data = False
    run.start_instances()
    for player in ("a", "b"):
        Path(run._result_path(player)).write_text("RESULT: PASS")
    monkeypatch.setattr(duo.shutil, "rmtree", lambda path: (_ for _ in ()).throw(PermissionError("folder locked")))
    run.cleanup(True)
    summary = root / "patch/build/duo-results" / Path(run.data_dir).name
    assert (summary / "a-result.txt").read_text() == "RESULT: PASS"
    assert json.loads((summary / "input-verification.json").read_text())["unchanged"] is True
    assert json.loads((summary / "cleanup.json").read_text())["data_removed"] is False
