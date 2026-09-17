"""The gate's own shape: lane names, order, slowness, and that every lane runs a real script.

`--list` indexes `REQUIREMENTS[lane.name]` directly, so a lane added without a mapping crashes
the listing instead of printing a blank line, and a lane whose script was renamed fails only
when someone runs the gate — possibly minutes in, after the lanes before it. Both are cheap to
catch here: the gate is importable (nothing but constants and classes at module level), so the
table it is built from can be asserted against instead of trusted.
"""
from __future__ import annotations

import os
import sys

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import verify_gen1_release as gate  # noqa: E402  (tools/ is not a package; the gate is a script)

LANE_ORDER = ["unit", "rom-layout", "lua-parse", "profile-addresses", "profile-generated",
              "statics-generated", "fixtures", "patch-build", "live-gates", "live-new-gates",
              "live-trade-gates", "duo-pairs"]


def test_lane_order_is_the_gate_order():
    assert [lane.name for lane in gate.LANES] == LANE_ORDER


def test_every_lane_has_requirements_and_no_requirements_lack_a_lane():
    names = {lane.name for lane in gate.LANES}
    missing = sorted(names - set(gate.REQUIREMENTS))
    orphaned = sorted(set(gate.REQUIREMENTS) - names)
    assert not missing, f"lanes with no REQUIREMENTS entry (--list would KeyError): {missing}"
    assert not orphaned, f"REQUIREMENTS entries with no lane: {orphaned}"
    for lane in gate.LANES:
        assert gate.REQUIREMENTS[lane.name], f"{lane.name} claims no requirements at all"


def test_the_generated_artifact_lanes_serve_what_they_claim():
    """The mapping is the release paperwork: which lane is the evidence for which rule."""
    expected = {"profile-generated": ["F-1"], "statics-generated": ["F-5", "S-8"],
                "fixtures": ["F-6"]}
    for name, ids in expected.items():
        assert gate.REQUIREMENTS[name] == ids, (
            f"{name} claims {gate.REQUIREMENTS[name]}, not {ids}")


def test_slow_lanes_are_exactly_the_emulator_lanes():
    """--quick's promise is that it stops before anything that needs an emulator."""
    assert {"live-gates", "live-new-gates", "live-trade-gates", "duo-pairs"} == gate._SLOW


def test_every_plain_lane_runs_a_script_that_exists():
    """argv[1] is the script for every non-pytest lane; a renamed tool must fail here."""
    for lane in gate.LANES:
        if lane.is_pytest:
            continue
        assert os.path.exists(os.path.join(_REPO, lane.argv[1])), (
            f"{lane.name} runs {lane.argv[1]}, which does not exist")


def _stubbed_lane(monkeypatch, text: str):
    """run_lane against a fake pytest process that printed `text` and exited 0."""
    class Proc:
        returncode, stdout, stderr = 0, text, ""

    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: Proc())
    lane = gate.Lane("stub", [sys.executable, "-m", "pytest", "tests/unit"])
    return gate.run_lane(lane, quiet=True)


def test_a_lane_only_run_is_not_a_release_verdict(monkeypatch, capsys):
    """`--lane unit` passing says nothing about the lanes it did not run."""
    monkeypatch.setattr(gate, "run_lane", lambda lane, quiet: (True, "1 passed, 0 failed"))
    monkeypatch.setattr(sys, "argv", ["verify_gen1_release.py", "--lane", "unit"])
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "LANE(S) PASSED — not a release verdict" in out
    assert "GATE PASSED" not in out


def test_a_skip_with_no_printed_reason_fails_the_lane(monkeypatch):
    """`1 skipped` with no SKIPPED line means the reason was never printed, so nothing on this
    list could have excused it."""
    ok, detail = _stubbed_lane(monkeypatch, "3 passed, 1 skipped in 0.4s\n")
    assert not ok
    assert "1 skipped but only 0 SKIPPED reason lines printed" in detail


def test_a_skip_with_an_allowed_reason_passes_the_lane(monkeypatch):
    reason = gate.ALLOWED_SKIPS[0][0]
    ok, detail = _stubbed_lane(
        monkeypatch, f"3 passed, 1 skipped in 0.4s\nSKIPPED [1] tests/x.py:12: {reason}\n")
    assert ok, detail
    assert "1 skipped" in detail
