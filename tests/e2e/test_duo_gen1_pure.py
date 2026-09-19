"""Two-instance E2E: the pureRGB pairings through the real server (PLAN §13 P3b/P4/P5).

The same eighteen `gen1_new` scenarios as test_duo_gen1_new.py, on the pure foundation:

* ``gen1_pure``          PureRed (A) vs PureBlue (B), clean builds -- every scenario the row does
                         not defer (`not_yet`): the rules, PC/save, reconnect, whiteout, poison,
                         rival swap and the randomized-admission gate on the UPR fork jar.
* ``gen1_pure_overlay``  the companion source overlay (patch/dist/SLink-Pure*.ups applied to the
                         clean builds): native trade YES / NO and Explode Mode.
* ``gen1_pure_green``    PureRed vs PureGreen, the third title on the B side.

Selection follows the runner's own GAMES rows: a scenario deferred by a row's `not_yet` is not
collected for it, so this file never skips one on purpose -- a skip here is a missing artifact,
and the release lane counts every skip as a failure.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen1_playthrough as play  # noqa: E402
from e2e_duo import (  # noqa: E402
    GAMES as RUNNER_GAMES,
    SCENARIOS as RUNNER_SCENARIOS,
    scenario_attempt_limit,
)
from test_duo_gen1_new import SCENARIOS  # noqa: E402  (the canonical eighteen)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_E2E") != "1",
                       reason="two-instance E2E only runs with SLINK_E2E=1 (spawns EmuHawk twice)"),
]

PURE_GAMES = ("gen1_pure", "gen1_pure_overlay", "gen1_pure_green")


def pure_cases():
    """(game, scenario) for every scenario a pure row runs; the overlay row runs only the three
    trade/explode scenarios the clean rows defer (the rest would just re-run the clean build)."""
    cases = []
    for game in PURE_GAMES:
        deferred = set(RUNNER_GAMES[game]["not_yet"])
        overlay = bool(RUNNER_GAMES[game].get("patched_saves_override"))
        for scenario in SCENARIOS:
            if scenario in deferred:
                continue
            if overlay and not RUNNER_SCENARIOS[scenario].get("patched_saves"):
                continue
            cases.append((game, scenario))
    return cases


def deadline_for(game, scenario):
    return (RUNNER_SCENARIOS[scenario]["timeout"]
            * scenario_attempt_limit(scenario, RUNNER_GAMES[game]["game"])) + 300


def required_fixtures(game, scenario):
    targets = RUNNER_SCENARIOS[scenario].get("target", "town")
    fixtures = RUNNER_GAMES[game]["fixture"]
    if isinstance(targets, dict):
        return [(fixtures[inst], targets[inst]) for inst in ("a", "b")]
    return [(fixtures[inst], targets) for inst in ("a", "b")]


@pytest.mark.parametrize("game,scenario", pure_cases())
def test_gen1_pure_duo(game, scenario):
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    for title, target in required_fixtures(game, scenario):
        fixture = os.path.join(play.FIXTURES, f"{title}_{target}.SaveRAM")
        if not os.path.exists(fixture):
            pytest.skip(f"missing fixture {fixture} — `python tools/gen1_fixtures.py {title} {target}`")
    cmd = [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
           "--game", game, "--scenario", scenario, "--lane", f"P_{game}"]
    if scenario == "reconnect_new":
        # C-1 on the pure pairing: the second-OT PureRed save (tests/fixtures/gen1).
        cmd.extend(("--wrong-save", os.environ.get("SLINK_PURE_WRONG_SAVE") or os.path.join(
            REPO, "tests", "fixtures", "gen1", "purered_town_ot2.SaveRAM")))
    try:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=deadline_for(game, scenario))
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"{game} duo {scenario} exceeded the wrapper deadline of "
                    f"{deadline_for(game, scenario)} s -- partial stdout:\n{(exc.stdout or '')[-4000:]}")
    assert proc.returncode == 0, (
        f"{game} duo {scenario} failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}")
