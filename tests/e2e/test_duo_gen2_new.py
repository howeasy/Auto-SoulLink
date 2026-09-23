"""Opt-in Gen 2 link pairings; enabled prerequisites and evidence fail closed."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import e2e_duo as duo  # noqa: E402

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_E2E") != "1",
                       reason="two-instance Gen 2 E2E requires SLINK_E2E=1"),
]

GAME = "gen2_new"
SCENARIOS = ("link", "gen2_faint", "gen2_admit_wrong_rom")
LANE = "gen2-cc-link"
PAIRINGS = {
    GAME: LANE,
    "gen2_gold_silver": "gen2-gs-link",
    "gen2_crystal_gold": "gen2-cg-link",
}


def run_gate(game=GAME, scenario="link"):
    # Qualification must bind both fixtures to the pinned ROM before any process starts.
    assert scenario in SCENARIOS, f"unknown Gen 2 duo scenario: {scenario}"
    lane = PAIRINGS[game].removesuffix("link") + scenario.removeprefix("gen2_")
    duo.gen2_preflight(repo=REPO, game=game, scenario=scenario)
    assert Path(duo.EMUHAWK).is_file(), f"EmuHawk missing: {duo.EMUHAWK}"
    receipts = [REPO / "patch" / "build" / f"e2e_{scenario}_{lane}_{side}_result.txt"
                for side in ("a", "b", "pydec")]
    for path in receipts:
        path.unlink(missing_ok=True)
    timeout = duo.SCENARIOS[scenario]["timeout"] + 300
    try:
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "e2e_duo.py"),
             "--keep-data", "--game", game, "--scenario", scenario, "--lane", lane],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"Gen 2 duo exceeded {timeout}s: {(exc.stdout or '')[-4000:]}")
    assert result.returncode == 0, (
        f"Gen 2 duo failed:\n{result.stdout[-4000:]}\n{result.stderr[-1000:]}")
    for side, path in zip(("a", "b", "pydec"), receipts, strict=True):
        assert path.is_file(), f"missing fresh {side} receipt: {path}"
        lines = path.read_text(encoding="utf-8").splitlines()
        prefix = "PYDEC:" if side == "pydec" else "RESULT:"
        verdicts = [line for line in lines if line.startswith(prefix)]
        assert verdicts and all(line == f"{prefix} PASS"
                                or line.startswith(f"{prefix} PASS ") for line in verdicts), (
            f"missing or failed {side} verdict: {verdicts}")


def run_link_gate(game=GAME):
    run_gate(game, "link")


@pytest.mark.parametrize("game", PAIRINGS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_gen2_new_duo(game, scenario):
    run_gate(game, scenario)
