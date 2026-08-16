"""Two-instance Gen 2 Soul Link E2E: two Crystals, one real server.

    SLINK_E2E=1 pytest tests/e2e/test_duo_gen2.py -q

THE SAME CARTRIDGE ON BOTH SIDES, which Gen 1 could not do. BizHawk names a SaveRAM file
from its own gamedb entry, keyed on ROM hash rather than the path launched, so two instances
of one dump resolve to a single file and stamp on each other. Gen 1 sidestepped that by
pairing Red with Blue — a constraint on which cartridges can be tested together, not a fix.
`write_run_config(saveram_dir=…)` gives each instance its own directory, and there is exactly
one Crystal dump, so this pairing is only possible because of it.

THREE SCENARIOS, and the choice is deliberate rather than "what happened to work":

  faint        the core Soul Link rule. One linked mon dies, the partner's must die on the
               other machine, through the real server.
  boxsync      party sync. A deposits its half and the server must mirror box_mon to B —
               nothing is injected, so a broken rule cannot be masked by the harness doing
               the work itself. This is the scenario that exercises the Gen 2 box paths the
               write gate covers single-instance: a 32-byte box struct with no HP field, and
               a withdraw that needs the server's cached stats block.
  memorialize  both halves die and the pair is buried in Box 14 (sBox14, flat CartRAM
               0x79E0), which lives outside Gen 2's save checksum.

NOT RUN HERE, and stated rather than silently absent: playthrough, deadzone and dupes. Those
need tall grass, and Gen 2's fixture parks indoors because New Bark Town's west exit is
script-locked until Elm hands over a starter (see lua/tests/gen2_playthrough.lua). The rules
they cover — encounter linking, the dead zone, the species clause — are enforced server-side
and are generation-independent, and Gen 1 runs all three. Paying for a Gen 2 grass fixture
would buy a second copy of coverage that already exists.
"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen1_playthrough as g1  # noqa: E402  (EMUHAWK lives here)
import gen2_playthrough as play  # noqa: E402

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_E2E") != "1",
                       reason="two-instance Gen 2 E2E only runs with SLINK_E2E=1"),
]

SCENARIOS = ("faint", "boxsync", "memorialize")
ROM = "crystal"


def _subprocess_timeout(scenario):
    """Derived from the runner's own table, never a second hardcoded number.

    A pytest timeout shorter than the scenario's budget kills the subprocess mid-run and
    reports TimeoutExpired, which looks exactly like a hang.
    """
    from e2e_duo import SCENARIOS as RUNNER_SCENARIOS
    return RUNNER_SCENARIOS[scenario]["timeout"] + 300


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_gen2_duo(scenario):
    if not os.path.exists(g1.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {g1.EMUHAWK}")
    if not os.path.exists(os.path.join(REPO, play.ROMS[ROM])):
        pytest.skip(f"{play.ROMS[ROM]} not present (ROMs are gitignored)")
    if not os.path.exists(play.fixture_path(ROM, "town")):
        pytest.skip("missing fixture — build with `python tools/gen2_playthrough.py`")

    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
         "--game", "gen2", "--scenario", scenario],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=_subprocess_timeout(scenario))
    assert proc.returncode == 0, (
        f"gen2 duo {scenario} failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}")
