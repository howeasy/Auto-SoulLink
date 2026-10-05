"""tests/unit/test_polished_trade_fp.py — the Polished trade dispatch-entry gate, against the
real measurement.

The evidence is `tests/fixtures/polished/explore_B_stacks.json`, copied verbatim from
`F:/slink-work/lanes/pol-trade2/explore_B/stacks.json` (overlay
34942315bb3e62189a56dabbcb9cef6dd3e9a9f5, Pokemon Center 2F, 937 samples over 181 distinct stacks).
Its sha256 is pinned below; no stack byte is pasted into this file. If the fixture is absent the
module skips with a named absence rather than passing vacuously.

WHAT THE MEASUREMENT SETTLED, and what it did not
    The nine pinned bytes are constant across the two overworld phases (300 + 61 samples) and every
    expected value re-derives from data/polished/polished_slink.sym.

    Four measured samples carry a stack BYTE-IDENTICAL to the accept case and must still be
    refused: `talk` x3 and `after_wait` x1, all SP $C0DE, hROMBank $25, bytes
    ab0dc25100fe86d6444622d16b51e2501400018a611400120f00584314000177. No choice of pinned positions
    can separate them, because there is nothing left to separate — which is why the WRAM half of the
    gate is load-bearing and not defence in depth.

    DISCLOSED GAP: the lane recorded stack bytes, hROMBank and SVBK only. Its stacks.json has
    exactly six keys and none is engine state, and result.txt logs none of the eight WRAM symbols.
    So the engine blocks below are INFERRED, per vector, and are labelled as such. The one that
    carries the talk case is `wPlayerStepFlags` bit PLAYERSTEP_CONTINUE_F: the talk frame is the A
    press that STARTS the receptionist script, so wScriptMode and wMapStatus are still idle there
    and vanilla's own reason for that bit (patch/gen2/src/trade_dispatch.asm:55-60) is the only
    one that applies. A probe that logs those eight bytes per frame would replace every INFERRED
    below with a measurement; until then the engine half is a hypothesis that has tests.

Run:  python -m pytest tests/unit/test_polished_trade_fp.py -q
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from server.adapters import polished_trade_fingerprint as fp  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "polished" / "explore_B_stacks.json"
# The verbatim copy of F:/slink-work/lanes/pol-trade2/explore_B/stacks.json.
FIXTURE_SHA256 = "4d55371779278605b8ccaaa26419ffec625345d36f2c656358c3f5c50c48ac66"
LANE_SOURCE = "F:/slink-work/lanes/pol-trade2/explore_B/stacks.json"
OVERLAY_SHA1 = "34942315bb3e62189a56dabbcb9cef6dd3e9a9f5"

# INFERRED, not measured — see the module docstring. The accept case: a player walking in the
# Pokemon Center 2F overworld with a partner PROMPT sitting in the lease. The only non-zero value
# is wMapStatus, and its expected value (MAPSTATUS_HANDLE = 2) comes from the pinned source.
ACCEPT_ENGINE = {
    "wScriptMode": 0,
    "wBattleMode": 0,
    "wLinkMode": 0,
    "wGameLogicPaused": 0,
    "hInMenu": 0,
    "wMapStatus": fp.MAPSTATUS_HANDLE,
    "wMapEventStatus": fp.MAPEVENTS_ON,
    "wPlayerStepFlags": 0,          # player is walking, so PLAYERSTEP_CONTINUE_F is clear
}
# INFERRED: the talk frame is the A press that STARTS the receptionist script. The script has not
# begun, so every "is the script running" byte is still idle; what makes it unsafe is that the
# player is standing still, which is what PLAYERSTEP_CONTINUE_F means.
TALK_ENGINE = {**ACCEPT_ENGINE, "wPlayerStepFlags": 1 << fp.PLAYERSTEP_CONTINUE_F}
# INFERRED: the link wait runs with wLinkMode set; that is what the measured $0A bank came through.
LINK_ENGINE = {**ACCEPT_ENGINE, "wLinkMode": 1}


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    if not FIXTURE.is_file():
        pytest.skip(f"measured stacks absent: {FIXTURE} (lane source {LANE_SOURCE})")
    raw = FIXTURE.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != FIXTURE_SHA256:
        pytest.fail(f"{FIXTURE} hashes {got}, pinned {FIXTURE_SHA256}")
    return json.loads(raw.decode("utf-8"))


def _phase(rows: list[dict], phase: str) -> list[dict]:
    out = [r for r in rows if r["phase"] == phase]
    assert out, f"no {phase} samples in the fixture"
    return out


def _dominant(rows: list[dict], phase: str) -> dict:
    return max(_phase(rows, phase), key=lambda r: r["count"])


def _snapshot(sample: dict, engine: dict) -> dict:
    return fp.snapshot_from_probe(sample, engine)


# ───────────────────────────────────────────────── the evidence itself


def test_the_fixture_is_the_pinned_measurement(rows):
    assert len(rows) == 181, f"expected 181 distinct stacks, got {len(rows)}"
    assert {r["phase"] for r in rows} == {
        "overworld", "overworld_after", "script", "wait_friend", "yesno", "after_wait", "talk"}
    assert sum(r["count"] for r in rows) == 937


def test_the_pinned_positions_resolve_from_the_committed_sym():
    """The expected values are DERIVED, not pasted. This is the test that fails if a label moves."""
    expected = fp.expected_positions()
    assert set(expected) == set(fp.PINNED_POSITIONS)
    # Hand-derived from data/polished/polished_slink.sym, quoted so a silent change is visible.
    syms = fp.load_symbols()
    assert syms["DelayFrame"][1] + 3 == 0x0DAB
    assert syms["NextOverworldFrame.gfx_done"][1] + 6 == 0x51C2
    assert syms["HandleMap"][1] + 0x15 == 0x516B
    assert syms["OverworldLoop.loop"][1] + 9 == 0x50E2
    assert syms["NextOverworldFrame"][0] == 0x25
    assert [expected[p] for p in (12, 13, 14, 15, 24, 25, 26, 27)] == [0xAB, 0x0D, 0xC2, 0x51,
                                                                     0x6B, 0x51, 0xE2, 0x50]
    assert expected[5] == 0x25


def test_the_derived_positions_are_exactly_what_the_overworld_measured(rows):
    """The symbolic derivation and the live measurement agree byte for byte."""
    view = fp.dispatch_view(_dominant(rows, "overworld")["bytes"], _dominant(rows, "overworld")["rombank"])
    expected = fp.expected_positions()
    for position in fp.PINNED_POSITIONS:
        assert view[position] == expected[position], f"sp+{position}"


# ───────────────────────────────────────────────── the accept population


@pytest.mark.parametrize("phase", ["overworld", "overworld_after"])
def test_the_measured_overworld_stacks_accept(rows, phase):
    verdict = fp.accepts(_snapshot(_dominant(rows, phase), ACCEPT_ENGINE))
    assert verdict.accepted, verdict.reason


def test_the_overworld_phases_never_vary_at_a_pinned_position(rows):
    """300 + 61 samples, two distinct stacks between them, all pinned bytes constant."""
    for phase in ("overworld", "overworld_after"):
        views = [fp.dispatch_view(r["bytes"], r["rombank"]) for r in _phase(rows, phase)]
        for position in fp.PINNED_POSITIONS:
            assert {v[position] for v in views} == {fp.expected_positions()[position]}, phase


# ───────────────────────────────────────────────── the refuse populations


@pytest.mark.parametrize("phase", ["script", "wait_friend", "after_wait"])
def test_the_measured_refuse_phases_refuse_on_the_stack_half(rows, phase):
    """script/after_wait run in bank $24 and the link wait in $0A: sp+5 rejects all three alone."""
    verdict = fp.stack_fingerprint_ok(
        fp.dispatch_view(_dominant(rows, phase)["bytes"], _dominant(rows, phase)["rombank"]))
    assert not verdict.accepted
    assert verdict.stage == "stack" and verdict.position == 5, verdict.reason


def test_the_yesno_phase_refuses_on_sp14(rows):
    """The YES/NO prompt runs in bank $25, so sp+5 passes and sp+14-15 is what refuses it."""
    verdict = fp.stack_fingerprint_ok(
        fp.dispatch_view(_dominant(rows, "yesno")["bytes"], _dominant(rows, "yesno")["rombank"]))
    assert not verdict.accepted
    assert verdict.stage == "stack" and verdict.position == 14, verdict.reason


def test_no_measured_stack_outside_the_overworld_phases_ever_passes_the_fingerprint(rows):
    """Every one of the 937 samples: only overworld/overworld_after/talk/after_wait may pass, and
    the last two are the false-accepts the engine half exists to reject."""
    expected = fp.expected_positions()
    passing = {r["phase"] for r in rows
               if fp.stack_fingerprint_ok(fp.dispatch_view(r["bytes"], r["rombank"]),
                                          expected).accepted}
    assert passing == {"overworld", "overworld_after", "talk", "after_wait"}


# ───────────────────────────────────────────────── the false accepts, which are byte-identical


def _accepting(rows: list[dict], phase: str) -> list[dict]:
    expected = fp.expected_positions()
    return [r for r in _phase(rows, phase)
            if fp.stack_fingerprint_ok(fp.dispatch_view(r["bytes"], r["rombank"]),
                                       expected).accepted]


def test_the_false_accepts_are_byte_identical_to_the_accept_vector(rows):
    """Why the engine half is the gate: there is nothing left in the stack to tell them apart."""
    overworld = _dominant(rows, "overworld")
    talk = _accepting(rows, "talk")
    after = _accepting(rows, "after_wait")
    assert [r["count"] for r in talk] == [3]
    assert [r["count"] for r in after] == [1]
    for sample in talk + after:
        assert sample["bytes"] == overworld["bytes"], sample["phase"]
        assert sample["sp"] == overworld["sp"] and sample["rombank"] == overworld["rombank"]


def test_the_talk_frame_accepts_with_a_safe_engine_and_refuses_with_continue_set(rows):
    """Same stack in both cases: the difference is engine state, and nothing else."""
    talk = _accepting(rows, "talk")[0]
    assert fp.accepts(_snapshot(talk, ACCEPT_ENGINE)).accepted, "a walking frame is a safe frame"
    verdict = fp.accepts(_snapshot(talk, TALK_ENGINE))
    assert not verdict.accepted
    assert verdict.stage == "engine" and "PLAYERSTEP_CONTINUE_F" in verdict.reason


def test_a_link_wait_engine_state_refuses_even_on_the_accept_stack(rows):
    verdict = fp.accepts(_snapshot(_dominant(rows, "overworld"), LINK_ENGINE))
    assert not verdict.accepted
    assert verdict.stage == "engine" and "wLinkMode" in verdict.reason


def test_a_snapshot_without_engine_state_refuses(rows):
    verdict = fp.accepts({"stack_view": fp.dispatch_view(_dominant(rows, "overworld")["bytes"],
                                                         _dominant(rows, "overworld")["rombank"])})
    assert not verdict.accepted and verdict.stage == "engine"


def test_every_missing_engine_key_refuses(rows):
    for key in fp.ENGINE_KEYS:
        engine = {k: v for k, v in ACCEPT_ENGINE.items() if k != key}
        verdict = fp.accepts(_snapshot(_dominant(rows, "overworld"), engine))
        assert not verdict.accepted, f"{key} missing but the gate said yes"
        assert "not in the snapshot" in verdict.reason


# ───────────────────────────────────────────────── RED CONTROL 1: flip each pinned byte
# The mutation a future dispatcher could ship: a moved label, a wrong bank byte, an off-by-one in
# a `call` width. Each must refuse, and each must name the position it refused on.


@pytest.mark.parametrize("position", fp.PINNED_POSITIONS)
def test_red_control_flipping_a_pinned_byte_refuses(rows, position):
    sample = _dominant(rows, "overworld")
    view = fp.dispatch_view(sample["bytes"], sample["rombank"])
    view[position] ^= 0xFF
    verdict = fp.accepts({"stack_view": view, "engine": dict(ACCEPT_ENGINE)})
    assert not verdict.accepted
    assert verdict.stage == "stack" and verdict.position == position


# ───────────────────────────────────────────────── RED CONTROL 2: drop an engine-state refusal
# The mutation is a "cleanup" that quietly removes a check. The gate must then answer WRONGLY on
# the very frames that check exists for, and the test goes red.


def test_red_control_dropping_the_continue_bit_makes_the_talk_frame_accept(rows, monkeypatch):
    talk = _accepting(rows, "talk")[0]
    assert not fp.accepts(_snapshot(talk, TALK_ENGINE)).accepted     # green today
    monkeypatch.setattr(fp, "ENGINE_CLEAR_BITS", ())                # the "cleanup"
    verdict = fp.accepts(_snapshot(talk, TALK_ENGINE))
    assert verdict.accepted, "dropping PLAYERSTEP_CONTINUE_F silently opened the talk frame"


def test_red_control_dropping_the_link_mode_refusal_accepts_a_link_frame(rows, monkeypatch):
    assert not fp.accepts(_snapshot(_dominant(rows, "overworld"), LINK_ENGINE)).accepted
    monkeypatch.setattr(fp, "ENGINE_REFUSALS",
                        tuple(row for row in fp.ENGINE_REFUSALS if row[0] != "wLinkMode"))
    verdict = fp.accepts(_snapshot(_dominant(rows, "overworld"), LINK_ENGINE))
    assert verdict.accepted, "dropping wLinkMode let a linked frame through the gate"


# ───────────────────────────────────────────────── RED CONTROL 3: noise positions are unpinned


@pytest.mark.parametrize("position", fp.NOISE_POSITIONS)
def test_red_control_flipping_a_noise_position_changes_nothing(rows, position):
    """The other mutation: pinning the game's registers. Stage B records sp+4 and sp+8..9 varying
    between runs, so a gate that checked them would fail on a different overworld frame."""
    sample = _dominant(rows, "overworld")
    view = fp.dispatch_view(sample["bytes"], sample["rombank"])
    view[position] ^= 0xFF
    verdict = fp.accepts({"stack_view": view, "engine": dict(ACCEPT_ENGINE)})
    assert verdict.accepted, f"noise position sp+{position} was pinned"


def test_the_noise_positions_really_do_vary_in_the_measurement(rows):
    """Not a claim about the game's registers — a fact read out of the fixture."""
    views = [fp.dispatch_view(r["bytes"], r["rombank"]) for r in _phase(rows, "overworld")]
    varying = {p for p in fp.NOISE_POSITIONS if len({v[p] for v in views}) > 1}
    assert varying, "no registered byte varies across the overworld samples: nothing to unpin"


# ───────────────────────────────────────────────── the frame depth


def test_dispatch_view_shifts_the_bridge_window_by_twelve():
    raw = bytes(range(32))
    view = fp.dispatch_view(raw, 0x25)
    assert view[12] == raw[0] and view[13] == raw[1]
    assert view[43] == raw[31]
    assert view[5] == 0x25
    with pytest.raises(ValueError, match="expected 32"):
        fp.dispatch_view(bytes(31), 0x25)


def test_a_bridge_sample_is_not_a_dispatch_sample(rows):
    """Feeding the raw lane record straight in must refuse — the +12 shift is not optional."""
    raw = _dominant(rows, "overworld")
    verdict = fp.stack_fingerprint_ok(fp.dispatch_view(raw["bytes"], raw["rombank"]))
    assert verdict.accepted
    # the same 32 bytes read at BRIDGE-entry offsets: words 0 and 2 are the accept values there,
    # and it is the +12 shift that turns them into dispatch sp+12-13 and sp+14-15.
    bridge_words = {i: raw["bytes"][i * 4:(i + 1) * 4] for i in range(8)}
    assert bridge_words[0] == "ab0d" and bridge_words[1] == "c251"
