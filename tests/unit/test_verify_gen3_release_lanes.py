"""The Gen 3 gate's own shape, mirroring test_verify_gen1_release_lanes.py: lane names are
unique, every lane has a REQUIREMENTS entry, `--list` covers every lane, and a synthetic pytest
summary with an unexplained skip fails the lane -- the same fail-closed core (release_lanes.py)
Gen 1 uses, applied to the Gen 3 manifest.
"""
from __future__ import annotations

import os
import sys

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import verify_gen3_release as gate  # noqa: E402  (tools/ is not a package; the gate is a script)

LANE_ORDER = ["unit", "lua-parse", "pins", "profile-generated", "probe-gates",
              "duo-pairs-gen3"]


def test_lane_order_is_the_gate_order():
    assert [lane.name for lane in gate.LANES] == LANE_ORDER


def test_lane_names_are_unique():
    names = [lane.name for lane in gate.LANES]
    assert len(names) == len(set(names))


def test_every_lane_has_requirements_and_no_requirements_lack_a_lane():
    names = {lane.name for lane in gate.LANES}
    missing = sorted(names - set(gate.REQUIREMENTS))
    orphaned = sorted(set(gate.REQUIREMENTS) - names)
    assert not missing, f"lanes with no REQUIREMENTS entry (--list would KeyError): {missing}"
    assert not orphaned, f"REQUIREMENTS entries with no lane: {orphaned}"
    for lane in gate.LANES:
        assert gate.REQUIREMENTS[lane.name], f"{lane.name} claims no requirements at all"


def test_slow_lanes_are_exactly_the_emulator_lanes():
    """--quick's promise is that it stops before anything that needs an emulator."""
    assert {"probe-gates", "duo-pairs-gen3"} == gate._SLOW


def test_the_lane_selection_skip_is_the_only_gen3_skip_that_is_excused():
    """A test for a cartridge/pack a lane did not select is not part of that lane; every skip
    about a MISSING input stays unexcused, which is what keeps a machine without the builds
    red -- same rule as Gen 1's ALLOWED_SKIPS."""
    fragments = [frag for frag, _why in gate.ALLOWED_SKIPS]
    assert fragments == ["is not one of this lane's cartridges"]
    for reason in ("cartridge dump not present", "SaveRAM not present", "EmuHawk not found",
                   "ROM dump missing", "fixture missing"):
        assert not any(frag in reason for frag in fragments), reason


def test_every_plain_lane_runs_a_script_that_exists_or_is_a_declared_placeholder():
    """argv[1] is the script for every non-pytest lane; a renamed *shipped* tool must fail here.

    `profile-generated` runs `tools/gen_gen3_profile.py`, which the P2 card that lands after
    this one still has to write -- the manifest names it now on purpose (a missing script is a
    FAIL at gate run time, not a skip, per the worker card), so it is excused from this
    exists-on-disk check by name rather than by "any non-pytest lane".
    """
    placeholders = {"profile-generated"}
    for lane in gate.LANES:
        if lane.is_pytest or lane.name in placeholders:
            continue
        assert os.path.exists(os.path.join(_REPO, lane.argv[1])), (
            f"{lane.name} runs {lane.argv[1]}, which does not exist")


def test_list_output_includes_every_lane(capsys):
    monkeypatch_argv = sys.argv
    sys.argv = ["verify_gen3_release.py", "--list"]
    try:
        assert gate.main() == 0
    finally:
        sys.argv = monkeypatch_argv
    out = capsys.readouterr().out
    for lane in gate.LANES:
        assert lane.name in out


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
    monkeypatch.setattr(sys, "argv", ["verify_gen3_release.py", "--lane", "unit"])
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


def test_an_unexplained_skip_fails_the_lane(monkeypatch):
    ok, detail = _stubbed_lane(
        monkeypatch, "3 passed, 1 skipped in 0.4s\nSKIPPED [1] tests/x.py:12: no jar\n")
    assert not ok
    assert "1 skipped" in detail
