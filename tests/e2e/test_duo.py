"""Two-instance headless E2E (tools/e2e_duo.py) as pytest, gated behind SLINK_E2E=1.

Each test boots a throwaway server + two EmuHawk instances and runs one scenario —
minutes each, Windows-only, needs E:/Howard/Bizhawk + the patched ROM — so the whole
module is skipped unless explicitly requested:

    SLINK_E2E=1 pytest tests/e2e/ -q

Every scenario loads a savestate, and BizHawk stops on a modal version dialog when handed
a state from another release (the emulator then hangs rather than erroring), so each
scenario also skips while its state is stale.  tools/mkstates.py rebuilds them.
"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import mkstates  # noqa: E402
from e2e_duo import SCENARIOS  # noqa: E402

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_E2E") != "1",
                       reason="two-instance E2E only runs with SLINK_E2E=1 (spawns EmuHawk twice)"),
]


def _states_for(scenario):
    ss = SCENARIOS[scenario]["savestate"]
    return sorted(set(ss.values())) if isinstance(ss, dict) else [ss]


# Gen 1-only scenarios (memorialize / rivalswap / explode_g1) boot battery fixtures and
# declare no savestate — running them here would KeyError in _states_for. They have their
# own module: tests/e2e/test_duo_gen1.py.
GEN3_SCENARIOS = sorted(k for k, v in SCENARIOS.items()
                        if "gen3_rr" in v.get("games", ("gen3_rr",)))


@pytest.mark.parametrize("scenario", GEN3_SCENARIOS)
def test_duo_scenario(scenario):
    if not os.path.exists(mkstates.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {mkstates.EMUHAWK}")
    emu = mkstates.emuhawk_version()
    for name in _states_for(scenario):
        stale, why = mkstates.is_stale(os.path.join(mkstates.STATE_DIR, name), emu)
        if stale:
            pytest.skip(f"{name} {why} — rebuild with `python tools/mkstates.py`")
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
         "--scenario", scenario],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=1200)
    assert proc.returncode == 0, (
        f"duo {scenario} failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-1000:]}")
