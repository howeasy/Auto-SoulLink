"""Two-instance headless E2E (tools/e2e_duo.py) as pytest, gated behind SLINK_E2E=1.

Each test boots a throwaway server + two EmuHawk instances and runs one scenario —
minutes each, Windows-only, needs E:/Howard/Bizhawk + the patched ROM — so the whole
module is skipped unless explicitly requested:

    SLINK_E2E=1 pytest tests/e2e/ -q
"""
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SLINK_E2E") != "1",
    reason="two-instance E2E only runs with SLINK_E2E=1 (spawns EmuHawk twice)")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.parametrize("scenario", ["faint", "boxsync", "trade", "ghost", "explode"])
def test_duo_scenario(scenario):
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
         "--scenario", scenario],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=1200)
    assert proc.returncode == 0, (
        f"duo {scenario} failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-1000:]}")
