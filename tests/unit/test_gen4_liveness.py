"""W-1 MODEL half: the checkpoint LIVENESS bound, on tests/unit/gen4_world.py.

Nothing here is PHYSICAL evidence. PHYSICAL reacquire times -- how long a real cartridge stays in a
forbidden state, and how many frames after it clears the real client writes -- are a separate
measurement (W-1 PHYSICAL, tests/live/test_gen4_w_gates.py). This file proves only the MODEL half the
ledger names for W-1 (docs/gen4_requirements.md:61, "valid idle eventually reachable"): after a
forbidden state clears, a queued storage command's write actually lands, and it lands within a bound
derived from the client's own scheduling.

THE BOUND -- IDLE_REACQUIRE_FRAMES = 1
The gate is re-evaluated once per emulator frame and nowhere else:

  * lua/gen4/client.lua:60-61 -- "polled ONCE per frame in pre_pump and cached for the frame (it is
    stateful)"; the poll is lua/gen4/client.lua:680 `st.ck, st.ck_why = safety:checkpoint()` with
    :681 `st.ck_frame = frame`.
  * lua/core/session.lua:409 runs game.pre_pump() and :473 runs the deferred queue, both inside the
    SAME frame_end and in that order. The client states the ordering itself at lua/gen4/client.lua:
    762-763 ("The PERMIT is the safety checkpoint of THIS frame (st.ck, polled in pre_pump; the
    deferred queue runs in the same frame_end)").
  * the queue evaluates the gate on entry (lua/core/deferred.lua:117-118, holding the command without
    executing it) and runs ONE command per call (:130), so a single queued command is not waiting
    behind anything.

The state is cleared between two frameadvances, so nothing has re-evaluated the gate on the frame the
state cleared: the write cannot land there. It lands on the very next one. Measured in framesadvanced
after the clearing frame until the first byte moves, IDLE_REACQUIRE_FRAMES = 1, and N - 1 = 0 frames
is the failing control. Every test below asserts the landing frame EXACTLY (all of the plan's bytes on
one named frame), never "within N frames" -- a number that always passes is not a bound.

The oracle shape is Gen 2's write-window liveness (tests/live/test_gen2_write_windows.py:111-117,
verify_liveness: accepted holds, and a fresh one after every window), here counted in MODEL frames.
The clause-by-clause SAFETY half of W-1 already lives in tests/unit/test_gen4_safety_lua.py and
tests/unit/test_gen4_client.py:576-588; this file is the LIVENESS half and repeats neither.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

import pytest

from tests.unit.gen4_world import Mon, World

# The bound, and the client lines it is derived from (see the module docstring).
IDLE_REACQUIRE_FRAMES = 1

# Frames the forbidden state is held after the command is delivered: enough for the reply to be read
# (session.lua:456) and refused on several frames, so a "one frame" result is not a lucky first frame.
HOLD_FRAMES = 3
# Past Session.PENDING_HUD_FRAMES (lua/core/session.lua:59) so a permanently stuck command has had to
# publish its reason (session.lua:382-397, called on every 30-frame tick).
STUCK_FRAMES = 660


def party() -> list[Mon]:
    """Two mons, one of them bench-alive: a deposit refuses "last party mon" (client.lua:947)."""
    return [Mon(0x5A3C91E7, 155, 5, 20, 20), Mon(0x0BADF00D, 155, 5, 11, 11)]


class Case(NamedTuple):
    name: str
    clause: str                                   # the checkpoint reason this state must produce
    titles: tuple[str, ...]
    forbid: Callable[[World], None]
    clear: Callable[[World], None]


BOTH = ("heartgold", "heartgold_hge")
CASES = (
    # a field task (script / gift / warp) running            -> safety.lua:97 task_running
    Case("script", "task_running", BOTH, lambda w: w.field(task=1), lambda w: w.field(task=0)),
    # the pause menu up                                    -> safety.lua:95 paused
    Case("pause", "paused", BOTH, lambda w: w.field(paused=1), lambda w: w.field(paused=0)),
    # the save driver mid-write                            -> safety.lua:117 save_busy
    Case("save", "save_busy", BOTH, lambda w: w.field(driver_state=2), lambda w: w.field(driver_state=1)),
    # an encounter: the battle app is launched, so the app clause (safety.lua:104) fires ahead of
    # encounter_active; it clears only when the encounter task has ended and the app is gone
    # (reads.lua:423 man == 0 -> "no_app" -> st.battle nil -> encounter_active false).
    # HeartGold only: that is the title whose battle chain the world model is exercised with
    # (tests/unit/test_gen4_client.py:973); the hge chain has no MODEL evidence here.
    Case("battle", "app_launched", ("heartgold",), lambda w: w.enter_battle(), lambda w: w.leave_battle()),
)


def held(case: Case, title: str) -> World:
    """A booted world in `case`'s forbidden state with one box_mon queued and refused on every frame.

    Asserts the precondition the bound is measured against: the command is IN the queue (held, not
    dropped and not failed), and not one byte has moved.
    """
    w = World(title, party=party())
    w.boot(80)                                          # past VALIDATE_EVERY (session.lua:59): writes armed
    case.forbid(w)
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(HOLD_FRAMES)
    assert w.writes == [], case.name
    assert w.session.deferred["items"][1].cmd == "box_mon", case.name
    assert w.events("box_mon_failed") == [], case.name
    return w


def parametrized():
    return [pytest.param(c, t, id=f"{c.name}-{t}") for c in CASES for t in c.titles]


@pytest.mark.parametrize(("case", "title"), parametrized())
def test_a_queued_storage_command_lands_on_the_frame_after_the_state_clears(case: Case, title: str):
    """The W-1 liveness claim: forbidden -> released -> the write lands, within IDLE_REACQUIRE_FRAMES."""
    w = held(case, title)
    ok, why = w.session.driver.checkpoint_ok()
    assert ok is False and why == case.clause, (case.name, why)

    case.clear(w)
    released = w.frame                                  # the last frame that ran with the state forbidden

    w.advance(IDLE_REACQUIRE_FRAMES - 1)                 # N - 1 frames: no poll since the clear, no write
    assert w.writes == [], case.name
    assert w.session.deferred["items"][1].cmd == "box_mon", case.name

    w.advance(1)
    # exact, not "within": the whole plan, on one named frame, and on no other
    assert {f for f, _, _ in w.writes} == {released + IDLE_REACQUIRE_FRAMES}, case.name
    assert w.state.ck is True and w.state.ck_frame == w.frame, case.name   # the gate was polled THIS frame

    key, kept = w.party[0].key, w.party[1].key
    assert key in w.box_keys() and w.saved_keys() == [kept], case.name
    assert w.events("box_mon_failed") == [] and len(w.events("stats_cache")) == 1, case.name

    moved = len(w.writes)
    w.advance(30)                                        # a slack window of the same size again
    assert len(w.writes) == moved, case.name            # one effect: never re-run frame after frame
    assert w.session.deferred["items"][2] is None, case.name


@pytest.mark.parametrize(("case", "title"), parametrized())
def test_a_forbidden_state_that_never_clears_fails_the_bound_and_names_its_clause(case: Case, title: str):
    """The other half of "eventually reachable": a clause that stays closed must NOT be written through,
    and the command must survive queued and diagnosable rather than be failed away."""
    w = held(case, title)
    w.advance(STUCK_FRAMES)                              # >> the bound
    assert w.writes == [], case.name                    # nothing was written through the closed gate
    assert w.box_keys() == {} and w.saved_keys() == [m.key for m in w.party], case.name
    assert w.events("box_mon_failed") == [], case.name   # held, never refused
    assert w.session.deferred["items"][1].cmd == "box_mon", case.name
    ok, why = w.session.driver.checkpoint_ok()
    assert ok is False and why == case.clause, (case.name, why)
    assert any("held: box_mon x1" in line and case.clause in line for line in w.logs), w.logs[-3:]


@pytest.mark.parametrize("title", BOTH)
def test_with_the_gate_already_open_the_command_lands_on_the_frame_it_arrives(title: str):
    """Why the bound is one frame and not two: the reply is read (session.lua:456) after pre_pump
    (:409) and before the deferred run (:473), so an open gate needs no extra poll to be noticed."""
    w = World(title, party=party())
    w.boot(80)
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(1)
    assert {f for f, _, _ in w.writes} == {w.frame}, title
    assert w.party[0].key in w.box_keys(), title

