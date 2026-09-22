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


@pytest.mark.parametrize("stdout", ["3 passed in 0.4s\n", "================ 3 passed in 0.4s ================\n"])
def test_clean_pytest_lane_passes(monkeypatch, stdout):
    ok, detail = _stubbed_lane(monkeypatch, stdout)
    assert ok, detail
    assert "3 passed" in detail


@pytest.mark.parametrize("stdout", ["", "3989 tests collected in 4.80s\n", "0 passed in 0.01s\n"])
def test_zero_exit_without_executed_tests_fails(monkeypatch, stdout):
    ok, detail = _stubbed_lane(monkeypatch, stdout)
    assert not ok
    assert "no passing tests executed" in detail


def test_inherited_collect_only_cannot_pass_a_release_lane(monkeypatch, tmp_path):
    test_file = tmp_path / "test_required_lane.py"
    test_file.write_text(
        "import pytest\n"
        "@pytest.mark.parametrize('label', ['3 passed'])\n"
        "def test_required_behavior(label):\n    assert False\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    subprocess_run = gate.subprocess.run
    processes = []

    def record_process(*args, **kwargs):
        proc = subprocess_run(*args, **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(gate.subprocess, "run", record_process)
    lane = gate.Lane(
        "required", [sys.executable, "-m", "pytest", str(test_file), "-q", "-p", "no:cacheprovider"],
        env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    ok, detail = gate.run_lane(lane, quiet=True, allowed_skips=())
    assert len(processes) == 1
    assert processes[0].returncode == 0
    assert "1 test collected" in processes[0].stdout
    assert "[3 passed]" in processes[0].stdout
    assert not ok, detail
    assert "no passing tests executed" in detail


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


def test_allowlisted_skips_without_executed_tests_cannot_pass(monkeypatch):
    reason = "fixture belongs to another selected artifact"
    ok, detail = _stubbed_lane(
        monkeypatch, f"1 skipped in 0.1s\nSKIPPED [1] tests/x.py:12: {reason}\n",
        allowed_skips=[(reason, "binder-declared exclusion")],
    )
    assert not ok
    assert "no passing tests executed" in detail


def test_successful_nonpytest_command_does_not_need_a_test_summary(monkeypatch):
    ok, detail = _stubbed_lane(monkeypatch, "", pytest_lane=False)
    assert ok, detail


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


def test_list_prints_lanes_and_requirements_without_running_them(capsys):
    result, calls = _run_gate(["--list"])
    assert result == 0
    assert calls == []
    out = capsys.readouterr().out
    lines = [line.split() for line in out.splitlines()]
    assert ["fast", "[fast]"] in lines
    assert ["physical", "[slow]"] in lines
    assert lines.count(["requirements:", "example.requirement"]) == 2
    assert "GATE PASSED" not in out


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
