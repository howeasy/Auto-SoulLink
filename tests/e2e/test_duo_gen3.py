"""Two-instance Gen 3 E2E for the NEW client (lua/gen3/*) on vanilla FRLG, game gen3_frlg.

    SLINK_E2E=1 pytest tests/e2e/test_duo_gen3.py -q

docs/gen3/PLAN.md §5.5 / §6 P4: the seven FRLG scenarios through a throwaway server and two
EmuHawk instances running lua/gen3/run.lua's production build (lua/tests/duo/duo_gen3_main.lua),
booted from the flash fixtures tests/fixtures/gen3/firered_party_{town,battle}{,_b}.sav. Every
scenario's verdict is the runner's: both RESULT lines, then check_save_witness_gen3 on the dumped
flash, then the scenario's saved-state oracle (tools/e2e_duo.py).

This is the `duo-pairs-gen3` lane of tools/verify_gen3_release.py, which excuses no input-missing
skip: with SLINK_E2E=1 a missing EmuHawk, ROM dump or fixture FAILS here rather than skipping.
"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

from e2e_duo import (  # noqa: E402
    EMUHAWK,
    GAMES as RUNNER_GAMES,
    GEN3_FIXTURES,
    SCENARIOS as RUNNER_SCENARIOS,
    scenario_attempt_limit,
    scenario_target,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_E2E") != "1",
                       reason="two-instance E2E only runs with SLINK_E2E=1 (spawns EmuHawk twice)"),
]

GAME = "gen3_frlg"
SCENARIOS = ("faint_cmd_gen3", "linked_faint_active_gen3", "boxsync_gen3", "whiteout_gen3",
             "link_gen3", "deadzone_gen3", "reconnect_gen3", "explode_gen3", "center_controls_gen3",
             "save_then_write_gen3", "trainer_bench_gen3", "active_end_gen3",
             "linked_faint_active_whiteout_gen3", "linked_faint_active_trainer_gen3",
             "species_clause_gen3", "gender_clause_gen3", "type_clause_gen3", "release_gen3", "ball_gate_gen3")
# G4 item 2a on LeafGreen: the same family with LG as A (C4-6m), for the A-side Center receipts
GAME_LGFR = "gen3_lgfr"
SCENARIOS_LGFR = ("whiteout_gen3", "center_controls_gen3", "save_then_write_gen3",
                  "trainer_bench_gen3", "active_end_gen3", "explode_gen3",
                  # G4-PH: the P+H subject is B, so LG-as-A puts FireRed under the commit
                  "linked_faint_active_gen3", "linked_faint_active_whiteout_gen3",
                  "linked_faint_active_trainer_gen3", "species_clause_gen3", "gender_clause_gen3",
                  "type_clause_gen3", "release_gen3", "ball_gate_gen3")


def deadline_for(scenario):
    """Every attempt the runner may take (one, for gen3_frlg), plus boot and teardown."""
    return RUNNER_SCENARIOS[scenario]["timeout"] * scenario_attempt_limit(scenario, GAME) + 300


def required_fixtures(scenario, game=GAME):
    """The fixture stems this scenario boots, one per instance (the row's sides x the target)."""
    targets = scenario_target(RUNNER_SCENARIOS[scenario], game)
    sides = RUNNER_GAMES[game]["sides"]
    return [sides[inst][1].format(target=targets[inst] if isinstance(targets, dict) else targets)
            for inst in ("a", "b")]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_gen3_frlg_duo(scenario):
    _run_duo(GAME, scenario)


@pytest.mark.parametrize("scenario", SCENARIOS_LGFR)
def test_gen3_lgfr_duo(scenario):
    _run_duo(GAME_LGFR, scenario)


def test_gen3_emerald_explode_duo():
    _run_duo("gen3_emerald", "explode_gen3")


def _run_duo(game, scenario):
    if not os.path.exists(EMUHAWK):
        pytest.fail(f"EmuHawk missing: {EMUHAWK}")
    for stem in required_fixtures(scenario, game):
        if not os.path.exists(os.path.join(GEN3_FIXTURES, stem + ".sav")):
            pytest.fail(f"fixture missing: tests/fixtures/gen3/{stem}.sav (tools/gen3_fixtures.py)")
    cmd = [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
           "--game", game, "--scenario", scenario]
    if scenario == "reconnect_gen3" and os.environ.get("SLINK_WRONG_SAVE"):
        cmd.extend(("--wrong-save", os.environ["SLINK_WRONG_SAVE"]))  # default: B's own fixture
    try:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=deadline_for(scenario))
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"{game} duo {scenario} exceeded {deadline_for(scenario)} s -- partial "
                    f"stdout:\n{(exc.stdout or '')[-4000:]}")
    assert proc.returncode == 0, (
        f"{game} duo {scenario} failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}")


# ── gen3_rr: the same NEW client on Radical Red (P5, card C5-5) ─────────────────────────────
# Several of these are currently BLOCKED: linked_faint_active/boxsync/whiteout/link/deadzone/
# explode/rival_swap all need a "battle" target, and tests/fixtures/gen3/rr_battle{,_b}.sav do
# not exist yet (only rr_town.sav/rr_town_b.sav are built) -- required_fixtures_rr below fails
# them loudly with the missing fixture's name, the same policy the module docstring states for
# gen3_frlg, rather than silently skipping. Only faint_cmd_gen3, reconnect_gen3 and
# native_absent_gen3 (all "town") can actually run today.
GAME_RR = "gen3_rr"
SCENARIOS_RR = ("faint_cmd_gen3", "linked_faint_active_gen3", "boxsync_gen3", "whiteout_gen3",
                "link_gen3", "deadzone_gen3", "reconnect_gen3",
                "explode_gen3", "rival_swap_gen3", "rival_swap_real_gen3", "native_absent_gen3",
                "linked_faint_active_whiteout_gen3",
                "linked_faint_active_lhammer_gen3", "linked_faint_active_mega_gen3",
                "trade_gen3", "trade_decline_gen3", "infopanel_gen3", "infopanel_dex_gen3",
                "species_clause_gen3", "gender_clause_gen3", "type_clause_gen3", "release_gen3", "ball_gate_gen3")


def deadline_for_rr(scenario):
    return RUNNER_SCENARIOS[scenario]["timeout"] * scenario_attempt_limit(scenario, GAME_RR) + 300


def required_fixtures_rr(scenario):
    targets = scenario_target(RUNNER_SCENARIOS[scenario], GAME_RR)
    sides = RUNNER_GAMES[GAME_RR]["sides"]
    return [sides[inst][1].format(target=targets[inst] if isinstance(targets, dict) else targets)
            for inst in ("a", "b")]


@pytest.mark.parametrize("scenario", SCENARIOS_RR)
def test_gen3_rr_duo(scenario):
    if not os.path.exists(EMUHAWK):
        pytest.fail(f"EmuHawk missing: {EMUHAWK}")
    for stem in required_fixtures_rr(scenario):
        if not os.path.exists(os.path.join(GEN3_FIXTURES, stem + ".sav")):
            pytest.fail(f"fixture missing: tests/fixtures/gen3/{stem}.sav (tools/gen3_fixtures.py)")
    cmd = [sys.executable, os.path.join(REPO, "tools", "e2e_duo.py"),
           "--game", GAME_RR, "--scenario", scenario]
    if scenario == "reconnect_gen3" and os.environ.get("SLINK_WRONG_SAVE"):
        cmd.extend(("--wrong-save", os.environ["SLINK_WRONG_SAVE"]))
    try:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=deadline_for_rr(scenario))
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"{GAME_RR} duo {scenario} exceeded {deadline_for_rr(scenario)} s -- partial "
                    f"stdout:\n{(exc.stdout or '')[-4000:]}")
    assert proc.returncode == 0, (
        f"{GAME_RR} duo {scenario} failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}")
