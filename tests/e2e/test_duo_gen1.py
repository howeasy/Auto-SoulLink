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
#   whiteout     A poisons its last mon to death, takes pokered's real HandleBlackOut, and
#                the partner loses its linked mon AND gets the auto-rebuild pulled back
# "playthrough" is last because it is the slowest and the only one that PLAYS: it walks
# Route 1's grass on both cartridges, meets real wild Pokemon, throws real Poke Balls, and
# requires the SERVER to pair the two captures by area. Nothing is injected and the Nuzlocke
# gate comes from the real bag, so it is the only coverage of encounter linking, area
# resolution and the ball gate — every other scenario injects the state it verifies.
#   deadzone     a real failed encounter locks the area for BOTH, and the partner's later
#                catch in that area is taken straight back off them
#   dupes        the species clause rejects the second half of a same-family pair
SCENARIOS = ("faint", "boxsync", "memorialize", "rivalswap", "explode_g1", "whiteout",
             "playthrough", "deadzone", "dupes")

# THE YELLOW FIXTURE IS NOT ON ROUTE 3. A SAME_MAP_ONLY tuple used to skip playthrough,
# deadzone and dupes on the Yellow pairing, on the stated grounds that the Yellow battery
# save "came out on Route 3" and so shared no encounter map with Red's. Decoding the
# fixtures says otherwise: wCurMap sits at file offset 0x260A (0x2000 + 0x598 + 11, and
# wCurMap - wPokedexOwned = 0x67 in both decomps), and ALL THREE battle fixtures read
# map 0x0C -- Route 1 -- at (10, 35), byte for byte the same placement. All three town
# fixtures read map 0x00, Pallet.
#
# The claim entered with the commit that FIXED Yellow's WRAM-shift bugs, which is the
# giveaway: it was read off the wrong byte. Three real runs per pairing were being skipped,
# and a skip reads exactly like a pass.
# tests/unit/test_gen1_fixtures.py now pins the decoded maps so this cannot come back.

# Scenarios registered but NOT passing, mapped to the reason. EMPTY, and keeping it empty is
# the point: every Gen 1 duo scenario now passes. Entries here are xfail rather than deletion
# so that a scenario starting to work reports XPASS instead of rotting silently -- and a
# scenario that stops working belongs in a fix, not in here.
KNOWN_FAILING = {}
# `dupes` USED to live here. It now passes, and what unblocked it was not the catch loop and
# not species forcing -- both of those already worked. Three things were wrong, each found by
# measuring rather than reasoning, and each is worth not re-deriving:
#
#   1. The `battle` fixture stands in Route 1 grass, so the walk that proves the game is live
#      started a wild encounter and committed a species before one could be forced -- and no
#      way of ending that battle leaves the area usable. Fixed by closing the engine's own
#      NewBattle gate (BIT_NO_BATTLES in wStatusFlags4, home/overworld.asm:362-373) across
#      the boot and reopening it in gen1_hunt.force_wild once the species is chosen.
#   2. That write has to be RE-ASSERTED EVERY FRAME. duo_gb_main runs before the ROM boots,
#      and the ~1000 frames spent reaching the overworld are the game initialising its own
#      WRAM, which wipes it. A single write read back set and the encounter still happened.
#   3. prove_booted could never complete its full proof on this fixture: its two round trips
#      set off in OPPOSITE directions, and Route 1 (10,35) has a wall to the Left -- measured
#      0 moves in 185 attempts Left against 183 in 186 Right
#      (lua/tests/probe_gen1_bootwalk.lua). It only ever "booted" there by way of the
#      wild-battle exception, which is the very encounter (1) removes. Both round trips now
#      go the same way, and the boot got FASTER: frame 1092 against the old 1053, and 1053
#      was the frame a battle started rather than a walk completing.
#
# A fourth bug was in the scenario's verdict, not the rule: H.wait_retired watched the
# memorial box's SIZE, which cannot see a burial that already happened, so the rejected side
# reported KEPT while the server log showed the clause firing correctly. It now asks whether
# that specific key is in the memorial.


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
    if scenario in KNOWN_FAILING:
        pytest.xfail(KNOWN_FAILING[scenario])
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    for rom in DUO_GAMES[game]:
        if not os.path.exists(os.path.join(REPO, play.ROMS[rom])):
            pytest.skip(f"{play.ROMS[rom]} not present (ROMs are gitignored)")
        # THE FIXTURE THE SCENARIO ACTUALLY LOADS, not always the town one. playthrough,
        # deadzone and dupes declare `target: battle`; this pre-check looked for
        # `_town.SaveRAM` regardless, so it could skip on a missing file the run would not
        # have opened, and pass through a missing one it needed.
        sys.path.insert(0, os.path.join(REPO, "tools"))
        from e2e_duo import SCENARIOS as _RUNNER_SCENARIOS
        target = _RUNNER_SCENARIOS[scenario].get("target", "town")
        fixture = os.path.join(play.FIXTURES, f"{rom}_{target}.SaveRAM")
        if not os.path.exists(fixture):
            pytest.skip(f"missing fixture — build with "
                        f"`python tools/gen1_playthrough.py --rom {rom} --target {target}`")

    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
         "--game", game, "--scenario", scenario],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=_subprocess_timeout(scenario))
    assert proc.returncode == 0, (
        f"{game} duo {scenario} failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}")
