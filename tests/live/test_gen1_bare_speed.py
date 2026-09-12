"""Two bare pinned Gambatte processes establish the host ceiling at 1x and 3x.

No SLink runtime, journal, socket, observer or memory helper is loaded by the Lua
gate.  The only work inside a measured window is ``emu.frameadvance()``; this is
the negative control for attributing later free-service overhead.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from tools.gen1_playthrough import BIZHAWK_CONFIG, EMUHAWK, ROMS, write_run_config

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "lua/tests/test_gen1_bare_speed_gate.lua"
TARGET = 59.727500569606
MIN_FRACTION = 0.99
WINDOW_MIN_FRACTION = 0.95
WINDOW_SPREAD_FRACTION = 0.10

pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required"),
]


def _private_config(directory: Path, player: str) -> Path:
    saveram = directory / f"SaveRAM-{player}"
    config = directory / f"config-{player}.ini"
    write_run_config(BIZHAWK_CONFIG, str(config), saveram_dir=str(saveram))
    document = json.loads(config.read_text(encoding="utf-8-sig"))
    document["ClockThrottle"] = True
    document["VSyncThrottle"] = False
    document["SoundThrottle"] = False
    document["AutoMinimizeSkipping"] = False
    document["FrameSkip"] = 0  # the Lua gate selects 0, then the minimal 3x value 2
    document.setdefault("Rewind", {})["Enabled"] = False
    sync = document["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]
    sync["FrameLength"] = 0  # pinned VBlank-driven Gambatte mode
    config.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return config


def _stage_rom(directory: Path, player: str, variant: str) -> str:
    source_root = Path(os.environ.get("SLINK_ROM_ROOT", ROOT.parents[2]))
    source = source_root / ROMS[variant]
    if not source.is_file():
        raise FileNotFoundError(f"canonical {variant} ROM not found under {source_root}")
    data = source.read_bytes()
    profiles = json.loads((ROOT / "data/games/gen1_rby/admission_profiles.json").read_text())["profiles"]
    expected = profiles[variant]
    assert hashlib.sha1(data).hexdigest() == expected["final_rom_sha1"]
    assert hashlib.sha256(data).hexdigest() == expected["rom_sha256"]
    target = directory / f"rom-{player}{source.suffix.lower()}"
    target.write_bytes(data)
    assert target.read_bytes() == data
    return target.relative_to(ROOT).as_posix()


def _launch_pair(directory: Path, variants: tuple[str, str]):
    jobs = []
    for player, variant in zip(("a", "b"), variants, strict=True):
        output = directory / f"result-{player}.json"
        config = _private_config(directory, player)
        before = json.loads(config.read_text(encoding="utf-8"))
        assert before["FrameSkip"] == 0 and before["ClockThrottle"] is True
        assert before["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]["FrameLength"] == 0
        env = dict(os.environ, SLINK_ROOT=ROOT.as_posix(), SLINK_BARE_SPEED_OUTPUT=str(output),
                   SLINK_BARE_SPEED_PLAYER=player)
        command = [EMUHAWK, f"--lua={SCRIPT}",
                   f"--config={config.relative_to(ROOT).as_posix()}", _stage_rom(directory, player, variant)]
        jobs.append((player, variant, output, config, subprocess.Popen(command, cwd=ROOT, env=env)))
    return jobs


def _wait(jobs, timeout: float = 120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(output.is_file() for _player, _variant, output, _config, _job in jobs):
            break
        exited = [(player, job.returncode) for player, _variant, _output, _config, job in jobs
                  if job.poll() is not None]
        if exited:
            raise AssertionError(f"bare Gambatte process exited before publishing evidence: {exited}")
        time.sleep(0.05)
    else:
        raise AssertionError("bare paired Gambatte speed gate timed out")
    for _player, _variant, _output, _config, job in jobs:
        try:
            job.wait(timeout=10)
        except subprocess.TimeoutExpired:
            job.kill()
            job.wait()


def _qualifies(phase: dict) -> bool:
    windows = [row["fps"] for row in phase["windows"]]
    target = phase["target_fps"]
    return (phase["fps"] >= target * MIN_FRACTION
            and min(windows) >= target * WINDOW_MIN_FRACTION
            and max(windows) - min(windows) <= target * WINDOW_SPREAD_FRACTION)


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue")])
def test_bare_paired_gambatte_sustains_one_and_three_x(variants):
    (ROOT / ".cache").mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=f"bare-speed-{variants[0][0]}{variants[1][0]}-", dir=ROOT / ".cache"))
    jobs = _launch_pair(directory, variants)
    try:
        _wait(jobs)
    finally:
        for _player, _variant, _output, _config, job in jobs:
            if job.poll() is None:
                job.kill()
                job.wait()

    summary = {"schema": "rby-bare-gambatte-pair-v1", "variants": list(variants), "players": {}}
    for player, variant, output, config, _job in jobs:
        result = json.loads(output.read_text(encoding="utf-8"))
        assert "error" not in result, result.get("error")
        assert result["schema"] == "rby-bare-gambatte-speed-v1" and result["player"] == player
        phases = {phase["name"]: phase for phase in result["phases"]}
        one = phases["one_x"]
        no_skip = phases["three_x_no_skip"]
        skip_two = phases["three_x_skip_two"]
        assert one["frameskip"] == 0 and one["target_fps"] == pytest.approx(TARGET)
        assert _qualifies(one), one
        selected = no_skip if _qualifies(no_skip) else skip_two
        assert selected["frameskip"] in (0, 2)
        assert selected["target_fps"] == pytest.approx(3 * TARGET)
        assert _qualifies(selected), {"no_skip": no_skip, "skip_two": skip_two}
        assert all(row["frames"] == 120 and row["last_frame"] - row["first_frame"] == 120
                   for phase in phases.values() for row in phase["windows"])
        summary["players"][player] = {"variant": variant, "rom_hash": result["rom_hash"],
                                       "one_x": one, "three_x_no_skip": no_skip,
                                       "three_x_skip_two": skip_two,
                                       "required_frameskip": selected["frameskip"]}
        private = json.loads(config.read_text(encoding="utf-8"))
        assert private["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]["FrameLength"] == 0
    (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
