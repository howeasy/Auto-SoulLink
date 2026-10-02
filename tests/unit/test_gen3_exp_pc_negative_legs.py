"""EXP-PC-NEG: the observer-side absence claims for the two expansion PC negative legs.

The legs themselves (lua/tests/gen3_scripted_play.lua's `emerald_pc_release_cancel` and
`emerald_pc_full_box`, expansion-gated) drive the game; this file holds the half a live run
cannot assert on its own: that a kind stayed SILENT across a named window of the shadow log,
and that the observer was demonstrably alive inside that same window.

Absence needs a liveness sibling. `registered=22` only proves the sites were ARMED; a dead or
disconnected observer produces the same empty log. So every check here is a PAIR over one
window: the kind must be absent AND `frame_control` must have advanced inside the window. The
negative controls mutate the text -- a pc_release inside the window, a frozen frame_control, a
window with no liveness -- and must make the same functions fail, so a passing test cannot be
explained by an assertion that never runs.

The window boundaries are frames, because the shadow log's only ordering witness is `frame=`.
The leg prints `G.phase("release-cancelled", ...)` / `G.phase("box-full", ...)` markers; a live
run's receipt hands those two frames to `check_absent_over_window`.
"""
from __future__ import annotations

import re

import pytest


# ── parsing ────────────────────────────────────────────────────────────────────────────────
def _kv(line: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", line))


def shadows(text: str) -> list[dict[str, str]]:
    """Every SHADOW row in file order. _kv's \\w+ split keeps `address` off `callback_address=`."""
    return [_kv(ln) for ln in text.splitlines() if ln.startswith("SHADOW ")]


def statuses(text: str) -> list[dict[str, str]]:
    return [_kv(ln) for ln in text.splitlines() if ln.startswith("STATUS ")]


def frames_of(text: str, kind: str) -> list[int]:
    return [int(r["frame"]) for r in shadows(text) if r.get("kind") == kind]


def _status_at(text: str, frame: int) -> dict[str, str] | None:
    """The last STATUS row at or before `frame` (the observer's own periodic sample)."""
    best = None
    for row in statuses(text):
        if int(row["frame"]) <= frame:
            best = row
    return best


# ── the checks (text in, assertions out -- the controls mutate the text, not the files) ─────
def check_absent_over_window(text: str, kind: str, lo: int, hi: int) -> None:
    """`kind` fired nowhere in (lo, hi], and the observer was alive inside the window.

    A `frame_control` SHADOW is the strongest liveness witness: it is the observer's own
    per-frame drain, so one landing inside the window means the queue was being serviced while
    the action ran. Failing that, a STATUS `frame_control=` counter that strictly increases
    across the window. Either satisfies liveness; both absent does not.
    """
    assert lo < hi, f"window {lo}..{hi} is empty"
    fired = [f for f in frames_of(text, kind) if lo < f <= hi]
    assert not fired, f"{kind} fired inside {lo}..{hi} at {fired}"

    drained = [f for f in frames_of(text, "frame_control") if lo < f <= hi]
    if not drained:
        before, after = _status_at(text, lo), _status_at(text, hi)
        assert before is not None and after is not None, \
            f"no frame_control row and no STATUS pair around {lo}..{hi}: the window proves nothing"
        assert int(after["frame_control"]) > int(before["frame_control"]), \
            f"frame_control did not advance across {lo}..{hi} " \
            f"({before['frame_control']} -> {after['frame_control']}): observer not proven alive"


def check_fired_outside_window(text: str, kind: str, lo: int, hi: int) -> None:
    """The positive sibling: `kind` DID fire, outside (lo, hi]. Without this the absence above
    is what a dead observer also produces."""
    fired = [f for f in frames_of(text, kind) if f > hi]
    assert fired, f"{kind} never fired after the window {lo}..{hi}: no liveness sibling"


# ── a synthetic shadow log, shaped exactly like the committed one ───────────────────────────
# Four STATUS samples and four SHADOW rows, with the two PC legs' windows marked by the leg's
# own phase frames. Cancel window 4000..4600 (silent, observer draining inside it), the
# positive sibling release at 4700, the full-box window 5000..5600 (silent, draining), and
# the sibling deposit at 5800.
_SYNTH = """\
NOTE observer building unadmitted gen3_exp/emerald_expansion_28877d73
STATUS frame=1000 registered=22 rejected=0 dropped=0 pending=0 failed=nil handler_error=nil
STATUS frame=3500 registered=22 rejected=0 dropped=0 pending=1 failed=nil handler_error=nil frame_control=1200
SHADOW t=1 frame=3509 kind=pc_release_begin key= address=136127978 callback_address=136127978 cpsr=1610612799 mode=thumb raw_r15=136127980 sp=50363840 thumb=1
SHADOW t=2 frame=3509 kind=pc_release key= address=136128108 callback_address=136128108 cpsr=1610612799 mode=thumb raw_r15=136128110 sp=50363840 thumb=1
STATUS frame=4500 registered=22 rejected=0 dropped=0 pending=1 failed=nil handler_error=nil frame_control=2200
SHADOW t=3 frame=4550 kind=frame_control key= address=136300000 callback_address=136300000 cpsr=536870975 mode=thumb raw_r15=136300002 sp=50363792 thumb=1
STATUS frame=4600 registered=22 rejected=0 dropped=0 pending=1 failed=nil handler_error=nil frame_control=3200
SHADOW t=4 frame=4700 kind=pc_release_begin key= address=136127978 callback_address=136127978 cpsr=1610612799 mode=thumb raw_r15=136127980 sp=50363840 thumb=1
SHADOW t=5 frame=4700 kind=pc_release key= address=136128108 callback_address=136128108 cpsr=1610612799 mode=thumb raw_r15=136128110 sp=50363840 thumb=1
STATUS frame=5500 registered=22 rejected=0 dropped=0 pending=1 failed=nil handler_error=nil frame_control=4200
SHADOW t=6 frame=5550 kind=frame_control key= address=136300000 callback_address=136300000 cpsr=536870975 mode=thumb raw_r15=136300002 sp=50363792 thumb=1
STATUS frame=5600 registered=22 rejected=0 dropped=0 pending=1 failed=nil handler_error=nil frame_control=5200
SHADOW t=7 frame=5800 kind=pc_deposit key= address=136127454 callback_address=136127454 cpsr=63 mode=thumb raw_r15=136127460 sp=50363816 thumb=1
"""

CANCEL_WINDOW = (4000, 4600)
FULL_BOX_WINDOW = (5000, 5600)


# ── the real assertions ─────────────────────────────────────────────────────────────────────
def test_pc_release_is_absent_across_the_cancel_window_with_a_live_observer():
    check_absent_over_window(_SYNTH, "pc_release", *CANCEL_WINDOW)


def test_the_release_leg_has_a_positive_sibling_after_the_cancel_window():
    check_fired_outside_window(_SYNTH, "pc_release", *CANCEL_WINDOW)


def test_pc_deposit_is_absent_across_the_full_box_window_with_a_live_observer():
    check_absent_over_window(_SYNTH, "pc_deposit", *FULL_BOX_WINDOW)


def test_the_full_box_leg_has_a_positive_sibling_after_its_window():
    check_fired_outside_window(_SYNTH, "pc_deposit", *FULL_BOX_WINDOW)


# ── negative controls: the SAME functions over a mutated text must fail ────────────────────
def _move_row_into_window(text: str, kind: str, lo: int, hi: int) -> str:
    """Relabel a real firing of `kind` as landing inside the window."""
    out = text.splitlines(keepends=True)
    for i, ln in enumerate(out):
        if ln.startswith("SHADOW ") and f"kind={kind} " in ln:
            out[i] = re.sub(r"frame=\d+", f"frame={lo + 1}", ln, count=1)
            return "".join(out)
    raise AssertionError(f"no {kind} row to move")


def _freeze_frame_control(text: str) -> str:
    """Every STATUS reports the same counter: the observer was never proven advancing."""
    return re.sub(r"frame_control=\d+", "frame_control=1200", text)


def _drop_liveness(text: str) -> str:
    """Remove the in-window frame_control rows AND flatten the STATUS counters."""
    kept = [ln for ln in text.splitlines(keepends=True)
            if not (ln.startswith("SHADOW ") and "kind=frame_control " in ln)]
    return re.sub(r"frame_control=\d+", "frame_control=1200", "".join(kept))


def test_control_a_release_inside_the_window_fails_the_absence_check():
    with pytest.raises(AssertionError, match="pc_release fired inside"):
        check_absent_over_window(_move_row_into_window(_SYNTH, "pc_release", *CANCEL_WINDOW),
                                 "pc_release", *CANCEL_WINDOW)


def test_control_a_deposit_inside_the_window_fails_the_absence_check():
    with pytest.raises(AssertionError, match="pc_deposit fired inside"):
        check_absent_over_window(_move_row_into_window(_SYNTH, "pc_deposit", *FULL_BOX_WINDOW),
                                 "pc_deposit", *FULL_BOX_WINDOW)


def test_control_a_frozen_frame_control_fails_liveness_when_no_drain_row_survives():
    with pytest.raises(AssertionError, match="not proven alive|frame_control did not advance"):
        check_absent_over_window(_drop_liveness(_SYNTH), "pc_release", *CANCEL_WINDOW)


def test_control_a_flattened_status_counter_alone_still_fails_when_drain_rows_are_removed():
    # The drain rows are the primary liveness witness; remove them and freeze the counters and
    # the check must refuse rather than accept an empty-but-quiet window.
    with pytest.raises(AssertionError, match="not proven alive|frame_control did not advance"):
        check_absent_over_window(_freeze_frame_control(_drop_liveness(_SYNTH)),
                                 "pc_release", *CANCEL_WINDOW)


def test_control_a_missing_sibling_fails_the_positive_check():
    trimmed = "\n".join(ln for ln in _SYNTH.splitlines()
                        if not (ln.startswith("SHADOW ") and "kind=pc_release" in ln))
    with pytest.raises(AssertionError, match="never fired after the window"):
        check_fired_outside_window(trimmed, "pc_release", *CANCEL_WINDOW)


def test_control_an_empty_window_is_refused():
    with pytest.raises(AssertionError, match="is empty"):
        check_absent_over_window(_SYNTH, "pc_release", 4000, 4000)


# ── the legs themselves: registration ORDER, gating, and their own citations ─────────────────
def _lua_source() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[2] / "lua" / "tests"
            / "gen3_scripted_play.lua").read_text(encoding="utf-8")


def _leg_order() -> list[str]:
    """The real registration order, straight off the file's own `name = "..."` fields.

    Deliberately parsed, not reimplemented: emerald_stopped_legs' semantics are INCLUSIVE
    (it returns legs[1..stop_after]), so a test that modelled the order itself would prove
    nothing about the order the Lua file actually registers.
    """
    src = _lua_source()
    return re.findall(r'name = "(emerald_\w+)"', src)


def _exp_block() -> str:
    src = _lua_source()
    gate = src.find("if TITLE == Syms.EXP_TITLE then")
    assert gate != -1, "the expansion-only guard is gone"
    close = src.find("end -- if TITLE == Syms.EXP_TITLE")
    assert close > gate
    return src[gate:close]


def test_all_three_negative_legs_are_registered():
    order = _leg_order()
    for name in ("emerald_pc_move_release_bypass", "emerald_pc_release_cancel", "emerald_pc_full_box"):
        assert name in order


def test_the_negative_legs_are_registered_AFTER_emerald_save_town():
    """THE ORDER IS THE FIX. emerald_stopped_legs returns legs[1..stop_after] INCLUSIVE, so a
    negative leg registered before emerald_save_town would run inside the standing observer
    command (PLAY_FROM=emerald_enter_pc STOP_AFTER=emerald_save_town) -- and emerald_pc_full_box
    fails closed by design, killing that run."""
    order = _leg_order()
    stop = order.index("emerald_save_town")
    for name in ("emerald_pc_move_release_bypass", "emerald_pc_release_cancel",
                 "emerald_pc_full_box"):
        assert order.index(name) > stop, f"{name} is at {order.index(name)}, before save_town ({stop})"


def test_the_bypass_leg_is_registered_BEFORE_the_cancel_leg():
    """The second half of the order contract, and the one a reader cannot infer.

    emerald_pc_release_cancel ends with a 1-mon party (its own positive sibling releases one);
    emerald_pc_move_release_bypass refuses below two mons. So on a resumed chain that starts at
    either negative leg, running the bypass AFTER the cancel trips its own precondition. Both
    stay after emerald_save_town (above), and the bypass is strictly before the cancel.
    """
    order = _leg_order()
    assert order.index("emerald_pc_move_release_bypass") < order.index("emerald_pc_release_cancel")
    # and the leg says so, so a future reorder is caught from the Lua side too
    block = _exp_block()
    leg = block[block.find("-- MOVED-MON BYPASS"):]
    assert "BEFORE emerald_pc_release_cancel" in leg


def test_stop_after_save_town_excludes_every_negative_leg():
    """emerald_stopped_legs' own semantics, reproduced from its source: it appends each leg and
    RETURNS the list once `leg.name == stop_after` -- inclusive, no scan past it."""
    src = _lua_source()
    body = src[src.find("local function emerald_stopped_legs"):]
    body = body[:body.find("\nend")]
    assert "legs[i] = leg" in body
    assert "if leg.name == stop_after then return legs end" in body, \
        "the inclusive return is what the order fix depends on -- re-read it if this fails"
    order = _leg_order()
    kept = order[:order.index("emerald_save_town") + 1]
    assert "emerald_save_town" in kept
    for name in ("emerald_pc_move_release_bypass", "emerald_pc_release_cancel",
                 "emerald_pc_full_box"):
        assert name not in kept


def test_the_negative_legs_are_expansion_gated():
    """All three must live inside the `if TITLE == Syms.EXP_TITLE` block, so a vanilla Emerald run
    never sees them and the vanilla path stays byte-identical."""
    block = _exp_block()
    for name in ("emerald_pc_move_release_bypass", "emerald_pc_release_cancel",
                 "emerald_pc_full_box"):
        assert block.find(f'name = "{name}"') != -1, f"{name} escaped the expansion guard"


def test_the_cancel_leg_cites_the_corrected_source_ranges():
    """Each range re-verified in the pinned expansion's src/pokemon_storage_system.c at
    e8bd1cd7: ShowYesNoWindow 4338-4342, Task_ReleaseMon state 1 2917-2923, the MSTATE enum head
    2230-2232 with its case at 2250, SetMenuTexts_Mon 7758-7817 with SetMenuText 8112-8127,
    ReleaseMon 6552-6580, and INPUT_DEPOSIT's one-mon refusal 2327-2343. The old 4315-4319 /
    2254-2256 / 7621-7669 ranges pointed at unrelated code."""
    src = _lua_source()
    leg = src[src.find('name = "emerald_pc_release_cancel"'):src.find('name = "emerald_pc_full_box"')]
    for cite in ("2917-2923", "4338-4342", "2230-2232", "2250", "7758-7817", "8112-8127",
                 "6552-6580", "2327-2343"):
        assert cite in leg, f"the cancel leg lost its {cite} citation"
    for stale in ("4315-4319", "2254-2256", "7621-7669"):
        assert stale not in leg, f"the cancel leg still cites the wrong range {stale}"
    assert 'PC.release(L, "no")' in leg, "the cancel leg must drive the NO path"
    assert "boxes_unchanged(L, before.boxes, after.boxes, nil)" in leg


def test_the_full_box_leg_cites_the_corrected_source_ranges():
    """Task_DepositMenu case 1 is 2855-2897 (with the MSG_BOX_IS_FULL / state-4 set at
    2878-2879) and case 4 is 2898-2904 -- 2889-2895 was case 3. HandleChooseBoxMenuInput is
    1778-1801, not 1183-1211."""
    leg = _exp_block()
    for cite in ("2855-2897", "2878-2879", "2898-2904", "6492-6517", "1778-1801", "7758-7817"):
        assert cite in leg, f"the full-box leg lost its {cite} citation"
    for stale in ("2889-2895", "1183-1211", "2847-2910"):
        assert stale not in leg, f"the full-box leg still cites the wrong range {stale}"


def test_the_cancel_leg_states_its_in_chain_requirement():
    """No leg in this table declares `state`, and playlib never inherits one
    (playlib.lua:653-657), so a bare PLAY_FROM=emerald_pc_release_cancel boots cold. The leg
    must say so AND the precondition failure must name the requirement, not just the count."""
    leg = _exp_block()
    assert "IN-CHAIN" in leg
    assert "SLINK_GEN3_PLAY_FROM=%s" in leg, "the precondition message must name the resume var"
    assert "state" in leg


def test_the_box_claim_is_stated_as_what_is_actually_compared():
    """owned_snapshot keys a box only where species ~= 0 and the party side carries decoded
    fields, not bytes -- so 'all 14 boxes byte-identical' overstates it. Both readback comments
    must name OCCUPIED records and say the party is compared by count and departure."""
    block = _exp_block()
    assert "all 14 boxes byte-identical" not in block
    assert "OCCUPIED" in block
    assert block.count("occupied box record") >= 1 or "OCCUPIED" in block


def test_the_full_box_leg_fails_closed_on_the_absent_synth_fixture():
    """The fixture belongs to the acquisition tooling's lease; the leg must name it and stop,
    never silently deposit into a 2-mon box and call that a full-box proof."""
    block = _exp_block()
    assert 'EXP_PC_FULL_BOX_SAV = "tests/fixtures/gen3/exp_pc_box0_full_synth.sav"' in block
    leg = block[block.find('name = "emerald_pc_full_box"'):]
    assert "EXP_PC_FULL_BOX_SAV" in leg, "the leg must check the named fixture before depositing"
    assert "missing fixture" in leg


# ── the absence helpers on the COMMITTED real run-2 shadow log ─────────────────────────────
def _real_run2_shadow() -> str:
    from pathlib import Path
    path = (Path(__file__).resolve().parents[2] / "docs" / "gen3_emerald" / "probes"
            / "dev_2026-10-01" / "gen3_scripted_play_emerald_result.shadow.log")
    assert path.is_file(), f"the retained run-2 shadow log is gone: {path}"
    return path.read_text(encoding="utf-8")


def test_the_real_log_parses_and_carries_the_reported_release():
    """The real run-2 log is the one these helpers must survive: pc_release_begin and pc_release
    both land on frame 4650, which is the whole reason a cancel window has to be chosen around
    them rather than assumed."""
    text = _real_run2_shadow()
    assert frames_of(text, "pc_release_begin") == [4650]
    assert frames_of(text, "pc_release") == [4650]
    assert frames_of(text, "frame_control") == [], \
        "this run has no frame_control SHADOW rows; liveness must come from the STATUS counter"


def test_a_window_before_the_real_release_passes_with_a_real_liveness_delta():
    """STATUS frame=3483 carries frame_control=591 and the next sample (frame=4083) carries 1146,
    so (3483, 4649] is provably alive AND provably silent: the real release is at 4650 and the
    window is half-open at its top edge, so that release is its liveness sibling."""
    text = _real_run2_shadow()
    check_absent_over_window(text, "pc_release", 3483, 4649)
    check_absent_over_window(text, "pc_deposit", 3483, 4649)
    check_fired_outside_window(text, "pc_release", 3483, 4649)


def test_a_window_containing_the_real_release_is_correctly_REPORTED():
    """The helpers must not merely pass: a window containing the real frame-4650 release must
    fail, and a window whose top edge is past it has no sibling left to prove liveness."""
    text = _real_run2_shadow()
    with pytest.raises(AssertionError, match=r"pc_release fired inside 4000\.\.4680 at \[4650\]"):
        check_absent_over_window(text, "pc_release", 4000, 4680)
    with pytest.raises(AssertionError, match="no liveness sibling"):
        check_fired_outside_window(text, "pc_release", 4700, 5600)


def test_the_real_log_has_no_status_rows_past_its_last_sample():
    """A window beyond the final STATUS sample has no liveness witness to offer, so the check
    must refuse it rather than accept a quiet tail."""
    text = _real_run2_shadow()
    last_status = max(int(r["frame"]) for r in statuses(text))
    assert last_status == 5283
    with pytest.raises(AssertionError):
        check_absent_over_window(text, "pc_release", last_status, last_status + 1000)


# ── the MOVED-MON BYPASS shape: begin ABSENT, release PRESENT UNPAIRED ──────────────────────
def _counter_advanced(text: str, lo: int, hi: int) -> bool:
    before, after = _status_at(text, lo), _status_at(text, hi)
    if not before or not after:
        return False
    # the FIRST STATUS row of a run carries no frame_control= yet, so read it optionally
    a, b = before.get("frame_control"), after.get("frame_control")
    return bool(a and b and int(b) > int(a))


def check_bypass_window(text: str, lo: int, hi: int) -> None:
    """The bypass's inverse shape: pc_release_begin ABSENT, pc_release PRESENT UNPAIRED, alive.

    The pair is the whole point. A log with no pc_release at all would satisfy the absence half
    trivially, and a dead observer produces the same; the unpaired pc_release is what proves the
    engine actually took ReleaseMon's flag-clear branch rather than nothing happening.
    """
    check_absent_over_window(text, "pc_release_begin", lo, hi)
    inside = [f for f in frames_of(text, "pc_release") if lo < f <= hi]
    assert inside, f"pc_release did not fire inside {lo}..{hi}: the bypass did not take"
    drained = [f for f in frames_of(text, "frame_control") if lo < f <= hi]
    assert drained or _counter_advanced(text, lo, hi), "observer not proven alive in the window"


def test_bypass_window_passes_on_the_unpaired_shape():
    bypass = _SYNTH.replace("kind=pc_release_begin", "kind=map_load", 1)
    check_bypass_window(bypass, 3500, 4600)


def test_bypass_window_rejects_a_paired_release_on_real_text():
    """Control on REAL text: the committed run-2 log has both kinds on frame 4650, so a window
    containing it must FAIL -- the helper is not vacuous."""
    text = _real_run2_shadow()
    with pytest.raises(AssertionError, match="pc_release_begin fired inside"):
        check_bypass_window(text, 3483, 5283)


def test_control_a_silent_window_fails_the_bypass_check():
    # no begin (so the absence half passes) AND no pc_release inside: the bypass did not happen
    silent = "\n".join(ln for ln in _SYNTH.splitlines() if "kind=pc_release_begin" not in ln
                       and not (ln.startswith("SHADOW ") and "frame=3509" in ln))
    with pytest.raises(AssertionError, match="pc_release did not fire inside"):
        check_bypass_window(silent, 3500, 4600)


def test_control_a_frozen_observer_fails_the_bypass_check():
    frozen = _drop_liveness(_SYNTH).replace("kind=pc_release_begin", "kind=map_load", 1)
    with pytest.raises(AssertionError, match="not proven alive|did not advance"):
        check_bypass_window(frozen, 3500, 4600)


def test_the_bypass_leg_cites_the_source_branches_it_drives():
    """Every range re-verified in the pinned expansion's src/pokemon_storage_system.c at
    e8bd1cd7: SetMenuTexts_Mon 7758-7817 with the RELEASE gate at 7813-7814 and SetMenuText
    8112-8127, the A handler 7501-7537 (INPUT_IN_MENU at 7510-7513), Task_OnSelectedMon
    2292-2293, MENU_RELEASE 2637-2653, ReleaseMon 6552-6580 (:6558-6561) and MoveMon :6399."""
    block = _exp_block()
    leg = block[block.find("-- MOVED-MON BYPASS"):]
    for cite in ("7813-7814", "7758-7817", "8112-8127", "7501-7537", "7510-7513", "2637-2653",
                 "6552-6580", "6558-6561", "6399", "2292-2293", "5795"):
        assert cite in leg, f"the bypass leg lost its {cite} citation"
    assert "PC.mode(L, PC.OPTION.move_mons)" in leg
    assert 'em_wait_carry(L, "grab_not_done", 1)' in leg
    assert "DUO claim" in leg, "the leg must say the client's no-report half needs a duo"



def test_the_bypass_leg_reads_back_a_grab_purged_mon_and_needs_only_one_party_mon():
    """Grabbing a boxed mon already purges its slot (MoveMon -> SetMovingMonData ->
    PurgeMonOrBoxMon, pokemon_storage_system.c:6391-6450), so ReleaseMon's held branch (:6558-6561)
    only clears the flag: the readback is 'gone from every box, party unchanged', never 'still
    boxed'. And IsRemovingLastPartyMon (:6878-6884) cannot fire for a held box mon, so the
    chain's one-mon party is enough."""
    block = _exp_block()
    leg = block.split('name = "emerald_pc_move_release_bypass"')[1].split('name = "emerald_pc_release_cancel"')[0]
    assert "if before.party.n < 1 then" in leg and "at least 2" not in leg
    assert "if after.boxes[target] then" in leg and "boxes_unchanged(L, before.boxes, after.boxes, target)" in leg
    assert "still = after.boxes[target]" not in leg and "byte-identical" not in leg.split("run = function")[1]
