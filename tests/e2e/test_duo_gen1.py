"""Two-instance Gen 1 E2E: Red as player A, Blue as player B.

    SLINK_E2E=1 pytest tests/e2e/test_duo_gen1.py -q

The end-to-end proof that the Soul Link rules work on Gen 1 — a throwaway server plus two
concurrent EmuHawk instances running the REAL production client, with one player's faint
travelling over TCP and killing the other player's mon on the other machine.

TWO THINGS THIS DOES THAT THE GEN 3 DUO CANNOT:

  * DIFFERENT CARTRIDGES. Gen 3 runs the same ROM twice; here A is Red and B is Blue, which
    is how the feature is actually played. It also means BizHawk cannot mix the two saves up
    — it names SaveRAM from its own gamedb entry, so Red and Blue get different filenames.
  * NO SAVESTATE, SO NO STALENESS SKIP. The Gen 3 scenarios each load a version-locked
    `.State` and skip themselves whenever BizHawk has been upgraded (tools/mkstates.py
    exists to rebuild them). Gen 1 boots the committed battery fixtures, which are plain
    SRAM and never expire.

Skipped, never hung, when a prerequisite is missing: no EmuHawk, no cartridge dumps (they
are gitignored), or fixtures not yet built.
"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen1_playthrough as play  # noqa: E402

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_E2E") != "1",
                       reason="two-instance E2E only runs with SLINK_E2E=1 (spawns EmuHawk twice)"),
]

# A is Red, B is Blue — see GAMES["gen1"] in tools/e2e_duo.py.
DUO_ROMS = ("red", "blue")

# Every Soul Link rule Gen 1 supports, end to end through the real server:
#   faint        one player's death kills the partner's linked mon on the other machine
#   boxsync      depositing half a pair auto-boxes the other half
#   memorialize  a dead pair is buried in Gen 1's Box 12 graveyard, and acked
#   rivalswap    the rival fights you with the partner's live team (no ROM patch)
#   explode_g1   the survivor is coerced into Explosion instead of a plain faint
SCENARIOS = ("faint", "boxsync", "memorialize", "rivalswap", "explode_g1")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_gen1_duo(scenario):
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    for rom in DUO_ROMS:
        if not os.path.exists(os.path.join(REPO, play.ROMS[rom])):
            pytest.skip(f"{play.ROMS[rom]} not present (ROMs are gitignored)")
        fixture = os.path.join(play.FIXTURES, f"{rom}_town.SaveRAM")
        if not os.path.exists(fixture):
            pytest.skip(f"missing fixture — build with "
                        f"`python tools/gen1_playthrough.py --rom {rom} --target town`")

    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
         "--game", "gen1", "--scenario", scenario],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=1200)
    assert proc.returncode == 0, (
        f"gen1 duo {scenario} failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}")
