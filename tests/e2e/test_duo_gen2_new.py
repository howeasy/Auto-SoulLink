"""Opt-in Crystal/Crystal link gate; enabled prerequisites and evidence fail closed."""
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
SCENARIOS = ("link",)
LANE = "gen2-cc-link"


def run_link_gate():
    # Qualification must bind both fixtures to the pinned ROM before any process starts.
    duo.gen2_preflight(repo=REPO)
    assert Path(duo.EMUHAWK).is_file(), f"EmuHawk missing: {duo.EMUHAWK}"
    receipts = [REPO / "patch" / "build" / f"e2e_link_{side}_result.txt"
                for side in ("a", "b", "pydec")]
    for path in receipts:
        path.unlink(missing_ok=True)
    timeout = duo.SCENARIOS["link"]["timeout"] + 300
    try:
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "e2e_duo.py"),
             "--keep-data", "--game", GAME, "--scenario", "link", "--lane", LANE],
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


def test_gen2_new_duo_link():
    run_link_gate()
