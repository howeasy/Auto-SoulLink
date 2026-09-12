"""A gate must never use the user's live emulator SaveRAM directory."""
import json
import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import gen1_playthrough as play
import run_gb_gate as gate


def test_unparseable_config_does_not_fall_back_when_isolation_is_required(tmp_path):
    source = tmp_path / "config.ini"
    source.write_text("not-json")
    destination = tmp_path / "isolated.ini"
    with pytest.raises(RuntimeError, match="refusing unisolated"):
        play.write_run_config(str(source), str(destination), str(tmp_path / "saves"))
    assert not destination.exists()


@pytest.mark.parametrize("override", [False, True])
def test_single_player_gate_redirects_saves_and_preserves_user_data(tmp_path, monkeypatch, override):
    repo = tmp_path / "worktree"
    build = repo / "patch/build"
    build.mkdir(parents=True)
    user_saves = tmp_path / "user-saves"
    user_saves.mkdir()
    sentinel = user_saves / "Pokemon - Red Version (USA, Europe).SaveRAM"
    sentinel.write_bytes(b"user progress")
    config = tmp_path / "user-config.ini"
    config.write_text(json.dumps({"Rewind": {"Enabled": True}, "PathEntries": {"Paths": [
        {"System": "GB_GBC_SGB", "Type": "Save RAM", "Path": str(user_saves)}]}}))
    original_config = config.read_bytes()
    private_config = tmp_path / "probe-config.ini"
    private = json.loads(original_config)
    private["Rewind"]["Enabled"] = False
    private_config.write_text(json.dumps(private))
    emulator = tmp_path / "EmuHawk.exe"
    emulator.touch()
    monkeypatch.setattr(gate, "REPO", str(repo))
    monkeypatch.setattr(gate, "BUILD", str(build))
    monkeypatch.setattr(gate, "EMUHAWK", str(emulator))
    monkeypatch.setattr(gate, "BIZHAWK_CONFIG", str(config))
    monkeypatch.setattr(gate, "SAVERAM_DIR", str(user_saves))
    monkeypatch.setattr(play, "staged_rom", lambda key: "patch/build/red.gb")
    destinations = []

    def seed(key, target, dest_dir=None):
        destination = Path(dest_dir)
        assert destination.is_relative_to(build)
        destinations.append(destination)
        (destination / sentinel.name).write_bytes(b"fixture")

    monkeypatch.setattr(gate, "seed_saveram", seed)
    result = build / "proof_result.txt"
    monkeypatch.setattr(gate, "_result_path_for", lambda script: str(result))

    class Process:
        def __init__(self, cmd, **kwargs):
            cfg_arg = next(arg for arg in cmd if arg.startswith("--config="))
            cfg = json.loads((repo / cfg_arg.split("=", 1)[1]).read_text())
            assert cfg["Rewind"]["Enabled"] is not override
            assert cfg["PathEntries"]["Paths"][0]["Path"] == str(destinations[-1]).replace("\\", "/")
            result.write_text("RESULT: PASS proof\n")

        def poll(self):
            return 0

    monkeypatch.setattr(gate.subprocess, "Popen", Process)
    for _ in range(2):
        options = {"config_base": str(private_config)} if override else {}
        assert gate.run_gate("unused.lua", quiet=True, **options)[0]
    assert destinations[0] != destinations[1]
    assert sentinel.read_bytes() == b"user progress"
    assert config.read_bytes() == original_config
    assert json.loads(private_config.read_text()) == private
    assert gate.BIZHAWK_CONFIG == str(config)


@pytest.mark.parametrize("rom_key", ["red", "yellow_receptionist_trade", "crystal"])
def test_override_fixture_and_lua_input_are_isolated_for_both_generations(tmp_path, monkeypatch, rom_key):
    repo = tmp_path / "worktree"
    build = repo / "patch/build"
    build.mkdir(parents=True)
    emulator = repo / "EmuHawk.exe"
    emulator.touch()
    config = repo / "config.ini"
    config.write_text(json.dumps({"PathEntries": {"Paths": [
        {"System": "GB_GBC_SGB", "Type": "Save RAM", "Path": str(tmp_path / "user-saves")}]
    }}))
    fixture = repo / "source.SaveRAM"
    fixture.write_bytes(b"immutable prepared fixture")
    source_config = config.read_bytes()
    monkeypatch.setattr(gate, "REPO", str(repo))
    monkeypatch.setattr(gate, "BUILD", str(build))
    monkeypatch.setattr(gate, "EMUHAWK", str(emulator))
    monkeypatch.setattr(gate, "BIZHAWK_CONFIG", str(config))
    spec = gate.GENS[gate.gen_for(rom_key)]
    monkeypatch.setattr(spec["play"], "staged_rom", lambda key: "patch/build/rom.gb")
    if rom_key in spec["patched"]:
        _, path, save_name = spec["patched"][rom_key]
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    else:
        save_name = spec["saveram_names"][rom_key]
    result = build / "proof_result.txt"
    monkeypatch.setattr(gate, "_result_path_for", lambda script: str(result))
    lua_input = str(repo / "run-input.json")
    previous = os.environ.get("SLINK_TEST_INPUT")
    destinations = []

    class Process:
        def __init__(self, cmd, **kwargs):
            cfg_arg = next(arg for arg in cmd if arg.startswith("--config="))
            cfg = json.loads((repo / cfg_arg.split("=", 1)[1]).read_text())
            saves = [row for row in cfg["PathEntries"]["Paths"] if row["Type"] == "Save RAM"]
            destination = Path(saves[0]["Path"])
            assert destination.is_relative_to(build)
            assert (destination / save_name).read_bytes() == fixture.read_bytes()
            (destination / save_name).write_bytes(b"emulator progress")
            destinations.append(destination)
            assert kwargs["env"]["SLINK_TEST_INPUT"] == lua_input
            assert kwargs["env"]["SLINK_ROOT"] == str(repo).replace("\\", "/")
            result.write_text("RESULT: PASS proof\n")

        def poll(self):
            return 0

    monkeypatch.setattr(gate.subprocess, "Popen", Process)
    for _ in range(2):
        assert gate.run_gate("unused.lua", rom_key=rom_key, quiet=True, fixture_override=str(fixture),
                             extra_env={"SLINK_TEST_INPUT": lua_input})[0]
    assert destinations[0] != destinations[1]
    assert fixture.read_bytes() == b"immutable prepared fixture" and config.read_bytes() == source_config
    assert os.environ.get("SLINK_TEST_INPUT") == previous


def test_extra_environment_cannot_change_worktree():
    with pytest.raises(ValueError, match="cannot override the gate worktree"):
        gate.run_gate("unused.lua", extra_env={"SLINK_ROOT": "somewhere else"})


def test_explicit_cartridge_is_hashed_copied_and_bound_to_private_saves(tmp_path,monkeypatch):
    repo=tmp_path/"worktree";build=repo/"patch/build";build.mkdir(parents=True)
    emulator=repo/"EmuHawk.exe";emulator.touch()
    config=repo/"config.ini";config.write_text(json.dumps({"PathEntries":{"Paths":[
        {"System":"GB_GBC_SGB","Type":"Save RAM","Path":"user-save-directory"}]}}))
    source=repo/"input.gbc";source.write_bytes(b"candidate fixture")
    fixture=repo/"fixture.SaveRAM";fixture.write_bytes(b"private save fixture")
    for name,value in (("REPO",repo),("BUILD",build),("EMUHAWK",emulator),("BIZHAWK_CONFIG",config)):
        monkeypatch.setattr(gate,name,str(value))
    output=build/"result.txt";monkeypatch.setattr(gate,"_result_path_for",lambda script:str(output))
    launched=[]
    class Process:
        def __init__(self,cmd,**kwargs):
            candidate=repo/cmd[-1]
            assert candidate.name=="candidate.gbc" and candidate.read_bytes()==source.read_bytes()
            assert candidate!=source and candidate.is_relative_to(build)
            save=Path(kwargs["env"]["SLINK_GATE_SAVERAM"])
            assert save.is_relative_to(build) and save.name=="candidate.SaveRAM"
            assert save.read_bytes()==fixture.read_bytes()
            launched.append(candidate);output.write_text("RESULT: PASS isolated\n")
        def poll(self):return 0
    monkeypatch.setattr(gate.subprocess,"Popen",Process)
    override={"path":str(source),"sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"saveram_name":"candidate.SaveRAM"}
    for change in ({"sha256":"0"*64},{"saveram_name":"../escape.SaveRAM"},{"unknown":True}):
        with pytest.raises(ValueError):
            gate.run_gate("unused.lua",quiet=True,fixture_override=str(fixture),cartridge_override=override|change)
    assert not launched
    for _ in range(2):
        assert gate.run_gate("unused.lua",quiet=True,fixture_override=str(fixture),cartridge_override=override)[0]
    assert launched[0]!=launched[1] and source.read_bytes()==b"candidate fixture"
    assert fixture.read_bytes()==b"private save fixture"
