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

# Two duo configurations, see GAMES in tools/e2e_duo.py:
#   gen1         A=Red,    B=Blue
#   gen1_yellow  A=Yellow, B=Red
#
# Yellow is not a formality. It shifts nearly every WRAM address by -1, and until this
# parametrisation existed it only ever ran SINGLE-instance gates — so no Yellow address had
# been exercised through the server and none of its write paths had run against a partner.
# Pairing it with Red rather than a second Yellow means a shift bug shows up as an asymmetry
# between the two halves instead of cancelling out. Adding it immediately found a harness bug:
# the orchestrator branched on `self.game == "gen1"`, so every non-default Gen 1 configuration
# silently took the Gen 3 path.
DUO_GAMES = {
    "gen1": ("red", "blue"),
    "gen1_yellow": ("yellow", "red"),
}
DUO_ROMS = DUO_GAMES["gen1"]

# Every Soul Link rule Gen 1 supports, end to end through the real server:
#   faint        one player's death kills the partner's linked mon on the other machine
#   boxsync      depositing half a pair auto-boxes the other half
#   memorialize  a dead pair is buried in Gen 1's Box 12 graveyard, and acked
#   rivalswap    the rival fights you with the partner's live team (no ROM patch)
#   explode_g1   the survivor is coerced into Explosion instead of a plain faint
# "playthrough" is last because it is the slowest and the only one that PLAYS: it walks
# Route 1's grass on both cartridges, meets real wild Pokemon, throws real Poke Balls, and
# requires the SERVER to pair the two captures by area. Nothing is injected and the Nuzlocke
# gate comes from the real bag, so it is the only coverage of encounter linking, area
# resolution and the ball gate — every other scenario injects the state it verifies.
SCENARIOS = ("faint", "boxsync", "memorialize", "rivalswap", "explode_g1", "playthrough")


def _subprocess_timeout(scenario: str) -> int:
    """Always outlive the scenario's OWN timeout, with margin for startup and teardown.

    A fixed 1200s here silently under-cut the playthrough's 1500s budget: pytest killed the
    subprocess mid-hunt and reported TimeoutExpired, which looks exactly like a hang. Deriving
    it from the same table the runner uses means the two can never drift apart again.
    """
    sys.path.insert(0, os.path.join(REPO, "tools"))
    from e2e_duo import SCENARIOS
    return SCENARIOS[scenario]["timeout"] + 300


@pytest.mark.parametrize("game", sorted(DUO_GAMES))
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_gen1_duo(scenario, game):
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    for rom in DUO_GAMES[game]:
        if not os.path.exists(os.path.join(REPO, play.ROMS[rom])):
            pytest.skip(f"{play.ROMS[rom]} not present (ROMs are gitignored)")
        fixture = os.path.join(play.FIXTURES, f"{rom}_town.SaveRAM")
        if not os.path.exists(fixture):
            pytest.skip(f"missing fixture — build with "
                        f"`python tools/gen1_playthrough.py --rom {rom} --target town`")

    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
         "--game", game, "--scenario", scenario],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=_subprocess_timeout(scenario))
    assert proc.returncode == 0, (
        f"{game} duo {scenario} failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}")
