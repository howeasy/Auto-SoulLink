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
