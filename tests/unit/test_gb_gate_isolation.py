"""A gate must never use the user's live emulator SaveRAM directory."""
import json
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


def test_single_player_gate_redirects_saves_and_preserves_user_data(tmp_path, monkeypatch):
    repo = tmp_path / "worktree"
    build = repo / "patch/build"
    build.mkdir(parents=True)
    user_saves = tmp_path / "user-saves"
    user_saves.mkdir()
    sentinel = user_saves / "Pokemon - Red Version (USA, Europe).SaveRAM"
    sentinel.write_bytes(b"user progress")
    config = tmp_path / "user-config.ini"
    config.write_text(json.dumps({"PathEntries": {"Paths": [
        {"System": "GB_GBC_SGB", "Type": "Save RAM", "Path": str(user_saves)}]}}))
    original_config = config.read_bytes()
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
            assert cfg["PathEntries"]["Paths"][0]["Path"] == str(destinations[-1]).replace("\\", "/")
            result.write_text("RESULT: PASS proof\n")

        def poll(self):
            return 0

    monkeypatch.setattr(gate.subprocess, "Popen", Process)
    for _ in range(2):
        assert gate.run_gate("unused.lua", quiet=True)[0]
    assert destinations[0] != destinations[1]
    assert sentinel.read_bytes() == b"user progress"
    assert config.read_bytes() == original_config
