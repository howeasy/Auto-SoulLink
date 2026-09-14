"""Two-instance Gen 1 E2E for the NEW client (lua/gen1/*): Red as player A, Blue as player B.

    SLINK_E2E=1 pytest tests/e2e/test_duo_gen1_new.py -q

docs/gen1_requirements.md D-1 (encounter link) and D-3 (dead zone) from real play: a
throwaway server plus two EmuHawk instances running the production client built through
lua/gen1/entry.lua, walking Route 1's grass and throwing the fixture's single Poke Ball. The
runner (tools/e2e_duo.py, game gen1_new) reads the verdict off the SERVER, never off the client.

Skipped, never hung, when a prerequisite is missing: no EmuHawk, no cartridge dumps (they
are gitignored), or the battle fixtures not built.
"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen1_playthrough as play  # noqa: E402
from e2e_duo import SCENARIOS as RUNNER_SCENARIOS  # noqa: E402

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_E2E") != "1",
                       reason="two-instance E2E only runs with SLINK_E2E=1 (spawns EmuHawk twice)"),
]

GAME = "gen1_new"
ROMS = ("red", "blue")
SCENARIOS = ("link_new", "deadzone_new")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_gen1_new_duo(scenario):
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    target = RUNNER_SCENARIOS[scenario].get("target", "town")
    for rom in ROMS:
        if not os.path.exists(os.path.join(REPO, play.ROMS[rom])):
            pytest.skip(f"{play.ROMS[rom]} not present (ROMs are gitignored)")
        fixture = os.path.join(play.FIXTURES, f"{rom}_{target}.SaveRAM")
        if not os.path.exists(fixture):
            pytest.skip(f"missing fixture — build with `python tools/gen1_fixtures.py {rom} {target}`")

    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
         "--game", GAME, "--scenario", scenario],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
        # Always outlive the runner's own per-scenario timeout (plus boot and teardown).
        timeout=RUNNER_SCENARIOS[scenario]["timeout"] + 300)
    assert proc.returncode == 0, (
        f"{GAME} duo {scenario} failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}")
