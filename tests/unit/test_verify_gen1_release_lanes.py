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

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import verify_gen1_release as gate  # noqa: E402  (tools/ is not a package; the gate is a script)

LANE_ORDER = ["unit", "rom-layout", "lua-parse", "profile-addresses", "profile-generated",
              "profile-generated-purergb", "statics-generated", "fixtures", "patch-build",
              "live-gates", "live-new-gates", "inspect-purergb", "apex-purergb",
              "live-trade-gates", "inspect-purergb-overlay", "live-trade-gates-purergb",
              "apex-refusal-purergb", "duo-pairs", "duo-pairs-purergb"]


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
    expected = {"profile-generated": ["F-1"], "profile-generated-purergb": ["F-1"],
                "apex-purergb": ["T1", "T3"], "statics-generated": ["F-5", "S-8"],
                "fixtures": ["F-6"]}
    for name, ids in expected.items():
        assert gate.REQUIREMENTS[name] == ids, (
            f"{name} claims {gate.REQUIREMENTS[name]}, not {ids}")


def test_the_fixtures_lane_reason_matches_the_legacy_set():
    """The lane's reason used to promise a Yellow legacy exception. LEGACY is empty now, so a
    reason that still claimed one would be the metadata lying about its own tool — and if an
    entry ever comes back, the reason has to say so again."""
    import gen1_fixtures

    why = next(lane.why for lane in gate.LANES if lane.name == "fixtures")
    assert ("legacy" in why.lower()) == bool(gen1_fixtures.LEGACY), why


def test_slow_lanes_are_exactly_the_emulator_lanes():
    """--quick's promise is that it stops before anything that needs an emulator."""
    assert {"live-gates", "live-new-gates", "inspect-purergb", "apex-purergb",
            "live-trade-gates", "duo-pairs", "inspect-purergb-overlay",
            "live-trade-gates-purergb", "apex-refusal-purergb", "duo-pairs-purergb"} == gate._SLOW


def test_the_pure_lanes_are_fail_closed():
    """A pure lane's inputs are the staged .gbc files and the per-title fixtures, and a skip is a
    lane failure: no ALLOWED_SKIPS fragment may excuse one, or a machine without the builds would
    read as green (the whole reason this gate exists)."""
    for reason in ("cartridge dump not present", "SaveRAM not present"):
        assert not any(frag in reason for frag, _why in gate.ALLOWED_SKIPS), (
            f"an ALLOWED_SKIPS fragment would excuse the pure lane's own skip: {reason}")
    pure = [lane for lane in gate.LANES if lane.name.endswith("purergb") or "purergb" in lane.name]
    assert {lane.name for lane in pure} == {"profile-generated-purergb", "inspect-purergb",
                                            "apex-purergb", "inspect-purergb-overlay",
                                            "live-trade-gates-purergb", "apex-refusal-purergb",
                                            "duo-pairs-purergb"}
    for lane in pure:
        assert lane.why, f"{lane.name} claims no reason"
    inspect = next(lane for lane in pure if lane.name == "inspect-purergb")
    # The subset is selected by env, not by -k: the lane scorer counts a deselection as a failure.
    assert "-k" not in inspect.argv
    assert inspect.env.get("SLINK_GEN1_ROMS", "").split() == ["purered", "pureblue", "puregreen"]
    profile = next(lane for lane in pure if lane.name == "profile-generated-purergb")
    assert profile.argv[-2:] == ["--foundation", "purergb"]
    apex = next(lane for lane in pure if lane.name == "apex-purergb")
    # One test, named by node id: a lane that collects a subset with -k would be scored as
    # failing (deselection counts), and the node id also pins WHICH test is the evidence.
    assert apex.argv[3] == ("tests/live/test_gen1_new_gates.py"
                            "::test_apex_chip_contract_on_a_pure_cartridge")
    assert "-k" not in apex.argv
    assert apex.env.get("SLINK_GEN1_ROMS") == "purered"
    assert apex.env.get("SLINK_LIVE") == "1"

    # The M3 overlay lanes (PLAN §6): all three select by node id, same reasoning as apex-purergb.
    inspect_overlay = next(lane for lane in pure if lane.name == "inspect-purergb-overlay")
    assert "-k" not in inspect_overlay.argv
    assert inspect_overlay.argv[3] == ("tests/live/test_gen1_new_gates.py"
                                       "::test_inspect_gate_overlay_round_trip")
    assert inspect_overlay.env.get("SLINK_LIVE") == "1"

    trade_overlay = next(lane for lane in pure if lane.name == "live-trade-gates-purergb")
    assert "-k" not in trade_overlay.argv
    assert trade_overlay.argv[3] == (
        "tests/live/test_gen1_trade_gates.py::test_receptionist_query_offer_and_native_notices"
        "[purered_overlay-purered-None]")
    assert trade_overlay.env.get("SLINK_LIVE") == "1"

    apex_refusal = next(lane for lane in pure if lane.name == "apex-refusal-purergb")
    assert not apex_refusal.is_pytest  # run_gb_gate.py fails closed on its own; no -rs needed
    assert apex_refusal.argv[1:4] == ["tools/run_gb_gate.py",
                                      "lua/tests/test_gen1_apex_refusal_gate.lua", "--rom"]
    assert "purered_overlay" in apex_refusal.argv


def test_the_lane_selection_skip_is_the_only_gen1_skip_that_is_excused():
    """A test for a cartridge a lane did not select is not part of that lane; every skip about a
    MISSING input stays unexcused, which is what keeps a machine without the builds red."""
    fragments = [frag for frag, _why in gate.ALLOWED_SKIPS]
    assert "is not one of this lane's cartridges" in fragments
    for reason in ("cartridge dump not present", "SaveRAM not present", "EmuHawk not found"):
        assert not any(frag in reason for frag in fragments), reason


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


@pytest.mark.parametrize("stdout", ["", "3989 tests collected in 4.80s\n"])
def test_zero_execution_cannot_pass_the_gen1_binding(monkeypatch, stdout):
    ok, detail = _stubbed_lane(monkeypatch, stdout)
    assert not ok
    assert "no passing tests executed" in detail


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
