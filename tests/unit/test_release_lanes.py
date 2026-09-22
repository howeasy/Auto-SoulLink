"""Exercise the shared release gate without a generation-specific manifest."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import release_lanes as gate  # noqa: E402


def _stubbed_lane(
    monkeypatch, stdout, *, stderr="", returncode=0, allowed_skips=(), pytest_lane=True
):
    proc = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: proc)
    argv = [sys.executable, "-m", "pytest", "tests/unit", "-q", "-rs"]
    if not pytest_lane:
        argv = [sys.executable, "tools/example_check.py"]
    return gate.run_lane(gate.Lane("example", argv), quiet=True, allowed_skips=allowed_skips)


def test_clean_pytest_lane_passes(monkeypatch):
    ok, detail = _stubbed_lane(monkeypatch, "3 passed in 0.4s\n")
    assert ok, detail
    assert "3 passed" in detail


def test_skip_without_printed_reason_fails(monkeypatch):
    ok, detail = _stubbed_lane(monkeypatch, "3 passed, 1 skipped in 0.4s\n")
    assert not ok
    assert "1 skipped but only 0 SKIPPED reason lines printed" in detail


def test_only_the_callers_declared_skip_reason_is_allowed(monkeypatch):
    reason = "fixture belongs to another selected artifact"
    summary = f"3 passed, 1 skipped in 0.4s\nSKIPPED [1] tests/x.py:12: {reason}\n"
    ok, detail = _stubbed_lane(
        monkeypatch, summary, allowed_skips=[(reason, "binder-declared exclusion")]
    )
    assert ok, detail
    assert "1 skipped" in detail

    ok, _ = _stubbed_lane(monkeypatch, summary)
    assert not ok


def test_unexplained_skip_fails_despite_another_allowed_reason(monkeypatch):
    ok, detail = _stubbed_lane(
        monkeypatch,
        "3 passed, 1 skipped in 0.4s\nSKIPPED [1] tests/x.py:12: required input missing\n",
        allowed_skips=[("fixture belongs to another selected artifact", "binder exclusion")],
    )
    assert not ok
    assert "1 unexplained" in detail


@pytest.mark.parametrize("outcome", ["xfailed", "xpassed", "deselected", "error", "failed"])
def test_reported_nonpassing_outcome_fails_even_with_zero_exit(monkeypatch, outcome):
    ok, _ = _stubbed_lane(monkeypatch, f"3 passed, 1 {outcome} in 0.4s\n")
    assert not ok


def test_reported_error_on_stderr_fails_even_with_zero_exit(monkeypatch):
    ok, _ = _stubbed_lane(monkeypatch, "3 passed\n", stderr="2 errors in 0.4s\n")
    assert not ok


@pytest.mark.parametrize("pytest_lane", [True, False])
@pytest.mark.parametrize("returncode", [1, -9])
def test_nonzero_exit_fails_despite_passing_output(monkeypatch, pytest_lane, returncode):
    ok, _ = _stubbed_lane(
        monkeypatch, "3 passed in 0.4s\n", pytest_lane=pytest_lane, returncode=returncode
    )
    assert not ok


def _run_gate(argv, *, failing=()):
    lanes = [gate.Lane(name, []) for name in ("fast", "physical")]
    calls = []

    def run_lane(lane, quiet):
        calls.append(lane.name)
        return lane.name not in failing, "synthetic lane result"

    result = gate.run_gate(
        title="Example release gate",
        lanes=lanes,
        requirements={lane.name: ["example.requirement"] for lane in lanes},
        slow={"physical"},
        run_lane=run_lane,
        argv=argv,
    )
    return result, calls


def test_quick_run_omits_slow_lane_and_cannot_claim_release(capsys):
    result, calls = _run_gate(["--quick"])
    assert result == 0
    assert calls == ["fast"]
    out = capsys.readouterr().out
    assert "not a release verdict" in out
    assert "GATE PASSED" not in out


def test_selected_lane_run_cannot_claim_release(capsys):
    result, calls = _run_gate(["--lane", "fast"])
    assert result == 0
    assert calls == ["fast"]
    out = capsys.readouterr().out
    assert "LANE(S) PASSED — not a release verdict" in out
    assert "GATE PASSED" not in out


def test_full_run_visits_every_lane_in_order_and_can_pass(capsys):
    result, calls = _run_gate([])
    assert result == 0
    assert calls == ["fast", "physical"]
    assert "GATE PASSED — every lane ran and every lane passed." in capsys.readouterr().out


def test_failed_lane_fails_gate_without_suppressing_later_lanes(capsys):
    result, calls = _run_gate([], failing={"fast"})
    assert result == 1
    assert calls == ["fast", "physical"]
    out = capsys.readouterr().out
    assert "GATE FAILED — fast" in out
    assert "GATE PASSED" not in out
