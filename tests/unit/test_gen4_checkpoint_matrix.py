"""Card G3-B -- the forbidden-state x write-log matrix for lua/gen4/safety.lua (the MODEL half).

A queued storage command and the save it would rewrite are separated by exactly one thing: the
checkpoint polled in pre_pump (lua/gen4/client.lua:680) and re-read by the deferred gate
(lua/core/session.lua:477-483). For every forbidden state that clause list has one obligation --
refuse, write ZERO bytes, keep the entry queued -- and one promise: when the world goes idle
again the deposit lands exactly once.

    row              the world cell safety.lua reads      refusal reason (lua/gen4/safety.lua)
    taskman active   fs + probe_field.task                task_running    (safety.lua:96-98)
    paused           sub + probe_field.paused              paused          (safety.lua:93-95)
    an app launched  sub + probe_field.launched_app        app_launched    (safety.lua:102-104)
    save in flight   save-driver data + save_state         save_busy       (safety.lua:115-117)
    encounter up     (the same cell as "app launched")    app_launched    <- the encounter_active
                                                                  clause is unreachable here; see
                                                                  the named-OPEN test below.

Every row asserts the four obligations, and every row has a RED CONTROL: the same world with its
one detector cell blinded by `_BlindRAM` -- the cartridge still holds the forbidden value (no
write path is touched), only the checkpoint is lied to. A clause that was doing no work would
leave the red control passing, so the red control is what makes the row falsifiable.

The two named-OPEN tests record what this model CANNOT reach, rather than asserting around it.

NOTHING here is PHYSICAL evidence: it is the offline model of the contract
(tests/unit/gen4_world.py). The live proof is the probe's job.
"""
import pytest

from tests.unit.gen4_world import BASE, DRV_DATA, FS, SUB, Mon, World

A = Mon(0x5A3C91E7, 155, 5, 20, 20)
B = Mon(0x0BADF00D, 155, 5, 11, 11)

ANY_TASK = 0x022A9000            # the save driver's own struct: a plausible non-NULL taskman
NOT_THE_BATTLE_APP = 0x022A0500  # a launched OverlayManager slot that is not the battle template


def two_mon():
    return [Mon(A.pid, 155, 5, 20, 20), Mon(B.pid, 155, 5, 11, 11)]


def ready():
    """A booted, validated, idle overworld (past the 60-frame validation, so writes are ENABLED)."""
    w = World(party=two_mon())
    w.boot(80)
    return w


def ck(w):
    """checkpoint_ok() -> (ok, why). lupa hands back a bare bool when why is nil, so normalise."""
    got = w.session.driver.checkpoint_ok()
    if isinstance(got, tuple):
        return got[0], (got[1] if len(got) > 1 else None)
    return got, None


def queued(w):
    """The deferred FIFO's command names, head first (lua/core/deferred.lua:74-99)."""
    items = w.session.deferred["items"]
    return [items[i].cmd for i in range(1, len(items) + 1)]


class _BlindRAM(bytearray):
    """A RAM whose READS of one cell return a value the cartridge no longer holds.

    `World.w`/`put` go through __setitem__ and are untouched, so the world really is in the
    forbidden state and the write path is intact; only the detector is blind. That is exactly
    the mutant the red control needs: a checkpoint that ignored its clause would let the
    deposit through. blind_reads proves the detector actually consulted the cell.
    """

    def __init__(self, src, blind_at, blind_to, base):
        super().__init__(src)
        self.blind_at = blind_at - base
        self.blind_to = blind_to
        self.blind_reads = 0

    def __getitem__(self, key):
        if isinstance(key, slice) and key.start == self.blind_at and key.stop is not None:
            n = key.stop - key.start
            if n in (1, 2, 4):
                self.blind_reads += 1
                return int(self.blind_to).to_bytes(n, "little")
        return super().__getitem__(key)


def cell(w, name, base):
    """The absolute address of one probe_field cell -- the same arithmetic safety.lua does."""
    return base + w.prof["probe_field"][name]


def rows():
    """(id, enter the forbidden state, leave it, expected reason, detector cell, value it must read)."""
    return [
        ("taskman",
         lambda w: w.field(task=ANY_TASK), lambda w: w.field(task=0), "task_running",
         lambda w: cell(w, "task", FS), 0),
        ("paused",
         lambda w: w.field(paused=1), lambda w: w.field(paused=0), "paused",
         lambda w: cell(w, "paused", SUB), 0),
        ("app_launched",
         lambda w: w.field(launched=NOT_THE_BATTLE_APP), lambda w: w.field(launched=0), "app_launched",
         lambda w: cell(w, "launched_app", SUB), 0),
        ("save_in_flight",
         lambda w: w.field(driver_state=0), lambda w: w.field(driver_state=1), "save_busy",
         lambda w: cell(w, "save_state", DRV_DATA), 1),
        # the encounter row: a battle is the launched battle app (reads.lua:421-427), so the
        # app_launched clause refuses it before the encounter clause is ever consulted.
        ("encounter",
         World.enter_battle, World.leave_battle, "app_launched",
         lambda w: cell(w, "launched_app", SUB), 0),
    ]


def assert_forbidden(w, why):
    """The four obligations, in the order they can fail."""
    ok, got = ck(w)
    assert ok is False, f"the checkpoint opened: {got!r}"
    assert got == why, got
    assert w.writes == [], w.writes                                     # zero bytes: every client
    assert queued(w) == ["box_mon"], queued(w)                          # write goes through io
    assert w.box_keys() == {} and w.events("box_mon_failed") == []     # the entry is retained


def assert_lands_once(w, recovered):
    assert {f for f, _, _ in w.writes} == {recovered}, w.writes          # ONE frame, ONE command
    assert queued(w) == [], queued(w)
    assert w.box_keys() == {w.party[0].key: (0, 0)}
    assert w.saved_keys() == [w.party[1].key]
    settled = len(w.writes)
    w.advance(30)
    assert len(w.writes) == settled, w.writes                            # no retry, no second move


@pytest.mark.parametrize(("name", "enter", "leave", "why", "blind", "blind_to"),
                         rows(), ids=[r[0] for r in rows()])
def test_every_forbidden_state_refuses_holds_and_lands_once_on_idle(name, enter, leave, why, blind, blind_to):
    w = ready()
    enter(w)
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(12)                                                        # crosses a 30-frame tick
    assert_forbidden(w, why)
    recovered = w.frame + 1
    leave(w)
    w.advance(1)                                                         # the first idle frame
    assert_lands_once(w, recovered)


@pytest.mark.parametrize(("name", "enter", "leave", "why", "blind", "blind_to"),
                         rows(), ids=[r[0] for r in rows()])
def test_red_control_blinding_the_detector_makes_the_row_fail(name, enter, leave, why, blind, blind_to):
    """The mutant that IGNORES this forbidden state: the cell still holds it, the read does not."""
    w = ready()
    enter(w)
    w.m = _BlindRAM(w.m, blind(w), blind_to, BASE)
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(12)
    assert w.m.blind_reads > 0, f"{name}: the detector never read the blinded cell -- the mutant " \
                              f"did not engage, so this row proves nothing"
    with pytest.raises(AssertionError):                                  # the row MUST go red
        assert_forbidden(w, why)
    # ...and it went red for the right reason: the checkpoint opened and the deposit landed.
    assert ck(w)[0] is True
    assert w.writes != [] and w.box_keys() == {w.party[0].key: (0, 0)}


# ── named OPEN rows: what this model cannot reach ───────────────────────────────────────
def test_open_a_menu_is_refused_only_through_the_taskman_cell_and_the_model_cannot_produce_one():
    """OPEN -- the card's "paused/menu" row has no cell of its own in this model.

    lua/gen4/safety.lua's clause list (safety.lua:70-123) has no menu, textbox or overlay clause,
    and it does not need one IF the repo's own reading holds: safety.lua:19 and
    docs/gen4/research/checkpoint.md:35 both state the start menu is a FIELD TASK
    (src/start_menu.c:233), so fs+0x10 (taskman) non-NULL is the refusal. What the model can
    prove is the consequence -- a non-NULL taskman refuses (the taskman row above). What it
    CANNOT prove is that pressing START produces that cell, and a menu that instead kept
    isPaused == 0, ran no task and launched no app is byte-identical to the overworld here,
    so the checkpoint would open for it. That half is UNPROVEN, not proven unsafe.
    """
    everything_allowed = ready()
    everything_allowed.field(live=1, task=0, launched=0, paused=0, driver_state=1)
    everything_allowed.reply({"cmd": "box_mon", "key": everything_allowed.party[0].key})
    everything_allowed.advance(12)
    assert ck(everything_allowed) == (True, None)                       # no clause can see a menu
    assert everything_allowed.writes != []
    assert everything_allowed.party[0].key in everything_allowed.box_keys()

    menu_claims_a_task = ready()
    menu_claims_a_task.field(task=ANY_TASK)                              # what checkpoint.md:35 asserts
    menu_claims_a_task.reply({"cmd": "box_mon", "key": menu_claims_a_task.party[0].key})
    menu_claims_a_task.advance(12)
    assert ck(menu_claims_a_task) == (False, "task_running")
    assert menu_claims_a_task.writes == []


def test_open_the_encounter_clause_is_shadowed_by_the_launched_app_clause():
    """OPEN -- `encounter_active` (safety.lua:119-121) can never be the reason a state is refused.

    lua/gen4/reads.lua:421-427 builds the battle chain OUT of [sub + probe_field.launched_app] and
    returns nil ("no_app") when that word is 0, so `st.battle ~= nil` -- the whole of
    `encounter_active` (client.lua:140) -- implies launched_app != 0, and app_launched
    (safety.lua:102-104) is evaluated first. The clause is a backstop for a pack whose battle
    chain needs no launched app; with today's adapters it is dead code, not a hole. Left OPEN
    rather than asserted away: a future adapter that drops the launched_app read from the battle
    chain would make it load-bearing again with no test change.
    """
    w = ready()
    w.enter_battle()
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(12)
    assert w.state.battle is not None                                    # the encounter IS active
    ok, why = ck(w)
    assert (ok, why) == (False, "app_launched"), why                      # ...and app_launched said so
    assert why != "encounter_active"                                    # not the clause that said it
    assert w.writes == [] and queued(w) == ["box_mon"]
    recovered = w.frame + 1
    w.leave_battle()
    w.advance(1)
    assert w.state.battle is None                                        # and with it gone, idle
    assert_lands_once(w, recovered)
