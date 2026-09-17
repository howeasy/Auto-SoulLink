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
SCENARIOS = ("link_new", "deadzone_new", "linked_faint_bench_new",
             "linked_faint_active_new", "trade_new", "reconnect_new", "ball_gate_new",
             "admit_randomized_new", "soft_reset_new", "trade_decline_new", "explode_new",
             "pc_ops_new", "changebox_new", "whiteout_new")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_gen1_new_duo(scenario):
    admission = scenario == "admit_randomized_new"
    if not os.path.exists(play.EMUHAWK):
        if admission:
            pytest.fail(f"EmuHawk missing for admission gate: {play.EMUHAWK}")
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    for rom_path in RUNNER_SCENARIOS[scenario].get("rom", {}).values():
        if not os.path.exists(os.path.join(REPO, rom_path)):
            pytest.skip(f"trade-carrying ROM {rom_path} not built")
    target = RUNNER_SCENARIOS[scenario].get("target", "town")
    for rom in ROMS:
        if not os.path.exists(os.path.join(REPO, play.ROMS[rom])):
            if admission:
                pytest.fail(f"clean {rom} ROM missing for admission gate: {play.ROMS[rom]}")
            pytest.skip(f"{play.ROMS[rom]} not present (ROMs are gitignored)")
        if not RUNNER_SCENARIOS[scenario].get("cold_boot"):
            fixture = os.path.join(play.FIXTURES, f"{rom}_{target}.SaveRAM")
            if not os.path.exists(fixture):
                if admission:
                    pytest.fail(f"town fixture missing for admission gate: {fixture}")
                pytest.skip(f"missing fixture — build with `python tools/gen1_fixtures.py {rom} {target}`")

    cmd = [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
           "--game", GAME, "--scenario", scenario]
    if scenario == "reconnect_new":
        # C-1 needs a second-OT Red save. The lane sets no environment, so the committed fixture
        # is the default and SLINK_WRONG_SAVE only overrides it; if the fixture is missing the
        # runner refuses it and the scenario fails, which is what a missing leg must do.
        cmd.extend(("--wrong-save", os.environ.get("SLINK_WRONG_SAVE") or os.path.join(
            REPO, "tests", "fixtures", "gen1", "red_town_ot2.SaveRAM")))
    proc = subprocess.run(
        cmd,
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
        # Always outlive the runner's own per-scenario timeout (plus boot and teardown).
        timeout=RUNNER_SCENARIOS[scenario]["timeout"] + 300)
    assert proc.returncode == 0, (
        f"{GAME} duo {scenario} failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}")
