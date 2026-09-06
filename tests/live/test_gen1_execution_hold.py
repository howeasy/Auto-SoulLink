"""Actual pinned Gambatte actuator matrix; no general execution-safety verdict."""
import json
import os
from pathlib import Path

import pytest

from tools.run_gen1_execution_hold import MODES, run_probe

pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required")]


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("paused", [False, True])
def test_gambatte_hold_ownership_pause_emergency_and_stopped_owner(variant, mode, paused):
    result = run_probe(variant, mode, paused=paused)
    assert result["passed"], result
    assert not result["release_ready"] and not result["source_drift"]
    report = json.loads((Path(result["directory"]) / "result.json").read_text())
    runtime = report["evidence"]["runtime"]
    assert runtime["initial_paused"] is paused
    assert runtime["periods"]
    for period in runtime["periods"]:
        assert period["frame_before"] == period["frame_after"]
        assert period["yields"] > 0 and period["elapsed_ms"] >= 250
    for entry in runtime["statuses"]:
        capabilities = entry["status"]["capabilities"]
        assert not any(capabilities[key] for key in (
            "reset_control", "load_state_control", "rewind_control", "debugger_control",
            "native_recovery_execution", "full_execution_safety", "production_selected"))
