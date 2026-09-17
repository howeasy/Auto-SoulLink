"""The choke-point wait: a cartridge's terminal RESULT ends an orchestrate-time wait.

The whiteout_new hang (2026-09-17): both receipts carried a FAIL and the runner sat in the
BOTH_BOXED gate's 1800 s budget anyway, because no orchestrate-time wait looked at the receipts.
`DuoRun.wait_for` now does, `run()` records the finding and returns False, and the retry
classifier still sees the receipts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import e2e_duo as duo  # noqa: E402

FAIL_LINE = "RESULT: FAIL (the deposit did not send party_to_box for the linked key)"
PASS_LINE = "RESULT: PASS (whited out with an empty party and was rebuilt from the PC)"


def _run(receipts=None, timeout=0.2):
    """A bare DuoRun whose receipts are `receipts` (a dict, refreshed per call)."""
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "whiteout_new"
    run.emus = []
    run.cfg = dict(duo.SCENARIOS["whiteout_new"])
    run.cfg["timeout"] = timeout
    run._pydec_note = lambda fact: None
    texts = dict(receipts or {})
    run._receipts = texts
    return run


def _patch_results(monkeypatch, run):
    monkeypatch.setattr(duo, "read_result", lambda scenario, inst: run._receipts.get(inst, ""))


def test_a_failed_client_ends_the_wait_within_one_poll(tmp_path, monkeypatch):
    run = _run({"a": f"PRE_WHITEOUT\n{FAIL_LINE}\n"})
    _patch_results(monkeypatch, run)
    with pytest.raises(duo.ClientFinishedEarly) as excinfo:
        run.wait_for("a marker that never lands", lambda: None, 5)
    assert excinfo.value.awaited == "a marker that never lands"
    assert excinfo.value.finished["a"] == FAIL_LINE
    assert excinfo.value.finished["b"] == ""


def test_a_failed_client_ends_even_when_the_other_is_still_running(tmp_path, monkeypatch):
    """A FAIL means the run is already lost: burning the rest of a 1800 s budget on a marker
    that half can no longer produce helps nobody."""
    run = _run({"a": FAIL_LINE, "b": "IDLE_PARTNER hellos=1\n"})
    _patch_results(monkeypatch, run)
    with pytest.raises(duo.ClientFinishedEarly, match="a client RESULT landed"):
        run.wait_for("the pair", lambda: None, 5)


def test_two_finished_clients_end_the_wait(tmp_path, monkeypatch):
    run = _run({"a": PASS_LINE, "b": PASS_LINE})
    _patch_results(monkeypatch, run)
    with pytest.raises(duo.ClientFinishedEarly):
        run.wait_for("the pair", lambda: None, 5)


def test_one_pass_does_not_end_a_wait_the_other_half_can_satisfy(tmp_path, monkeypatch):
    """The deliberate deviation from "any RESULT ends the wait": one half finishing first is
    normal — deadzone_new, pc_ops_new and whiteout_new all wait on B's markers after A saved
    and exited — so a lone PASS is not an abort. Only a FAIL, or both halves done, is."""
    run = _run({"a": PASS_LINE, "b": "PC_BOX_AFTER party=1 box=1 count=1\n"})
    _patch_results(monkeypatch, run)
    with pytest.raises(TimeoutError, match="a marker that never lands"):
        run.wait_for("a marker that never lands", lambda: None, 0.2)


def test_a_satisfied_predicate_wins_over_a_result(tmp_path, monkeypatch):
    """`wait_results` and the reconnect B-done wait have the RESULT as their predicate; they
    must return it, not raise on it."""
    run = _run({"a": PASS_LINE, "b": PASS_LINE})
    _patch_results(monkeypatch, run)
    assert run.wait_for("both RESULT lines", lambda: "RESULT: PASS" in run._receipts["a"], 1)


def test_the_whiteout_gate_ends_on_the_lane_shape(tmp_path, monkeypatch):
    """The exact hang: the deposit never lands and both receipts carry the FAIL the lane
    produced at 14:43:45. The gate must stop within one poll, not at its 1800 s budget."""
    run = _run({"a": FAIL_LINE, "b": FAIL_LINE})
    _patch_results(monkeypatch, run)
    run._link_keys = {"a": "AAAA:1111:01", "b": "BBBB:2222:02"}
    run._raw_state = lambda: {"_live": {"party_keys": {"a": [], "b": []}}}
    with pytest.raises(duo.ClientFinishedEarly, match="both halves to deposit"):
        run.assert_whiteout_both_boxed()


def test_run_records_the_finding_and_returns_false(tmp_path, monkeypatch):
    """`run()` must not re-raise: the caller reads the receipts and classifies them, which is
    where the ball-RNG retry lives."""
    run = _run()
    run.attempt = 1
    run._pydec_path = str(tmp_path / "pydec.txt")
    notes = []
    run._pydec_note = notes.append
    run.start_server = lambda: None
    run.start_instances = lambda: None

    def orchestrate():
        raise duo.ClientFinishedEarly({"a": FAIL_LINE, "b": FAIL_LINE}, "the pair")

    run.orchestrate = orchestrate
    run.cleanup = lambda passed: None
    run.args = type("Args", (), {"keep_alive": False})()
    assert run.run() is False
    assert notes[-1] == "PYDEC: FAIL client RESULT before the pair", notes


def test_a_mid_wait_ball_miss_still_retries(tmp_path, monkeypatch):
    """The receipts a ClientFinishedEarly leaves behind are the ones the classifier reads: a
    ball miss that ended the wait is still CAUSE_RNG, and the partner's consequence phrase
    keeps the pair retryable."""
    assert duo.retryable_gen1_rng(
        "gen1_new",
        {"a": duo.RNG_OUT_OF_BALLS, "b": "RESULT: FAIL (runner never released B (A_PENDING))"},
        1)
