"""lua/gen4/client.lua, steps 0-3 (G3 card), against the lupa world model (tests/unit/gen4_world.py).

Nothing here is PHYSICAL evidence. Each step's falsifier is an assertion that fails without the
behaviour (revert-checked, see the card report):

  step 0  admission + skeleton: one hello, a tick every 30 frames, no hook, no write
  step 1  snapshot + reducer in pre_pump only; boxes.gen bumps only on a COMPLETE scan; two-valued
          box_generation
  step 2  the D7 faint: the one-frame lease (stale r1 / wrong command / wrong overlay / lease not
          renewed by the previous frame -> ZERO bytes; renew then fire -> exactly one write)
  step 3  the 900-frame effect window (+900 satisfied, +901 not)
"""
import pytest

from tests.unit.gen4_world import BS, CTX, Mon, World, key_of

A = Mon(0x5A3C91E7, 155, 5, 20, 20)
B = Mon(0x0BADF00D, 155, 5, 11, 11)
SPY = """
function(tbl, name, log)
  local orig = tbl[name]
  tbl[name] = function(...)
    local r = table.pack(orig(...))
    log[#log + 1] = tostring(r[1]) .. "|" .. tostring(r[2])
    return table.unpack(r, 1, r.n)
  end
end
"""


def spy(w, tbl, name):
    log = w.lua.table()
    w.lua.eval(SPY)(tbl, name, log)
    return log


def lines(log):
    return [log[i] for i in range(1, len(log) + 1)]


def two_mon():
    return [Mon(A.pid, 155, 5, 20, 20), Mon(B.pid, 155, 5, 11, 11)]


def armed_world(title="heartgold", party=None, **kw):
    """A 2-mon party in a singles battle at the command-select screen, with a force_faint for the active
    battler HELD (the seam hook armed, lease renewed by the last frame's flush)."""
    w = World(title, party=party or two_mon(), **kw)
    w.boot(80)
    w.enter_battle(cmd=5)
    w.advance(3)
    w.reply({"cmd": "force_faint", "key": w.party[0].key})
    w.advance(1)
    return w


def seam_cmd(w):
    return w.d7["seam"]["cmd"]


def snapshot_bytes(w):
    return (w.battler_hp(0), w.battle_party_hp(0), w.faint_bit(0))


# ── step 0: admission + the driver skeleton ──────────────────────────────────────────────
def test_admission_refuses_an_unpinned_hash_and_builds_nothing():
    w = World(rom_hash="00" * 16, start=False)
    assert w.session is None and "unpinned build" in w.admit_why
    assert w.hook_registrations == 0 and w.writes == []


def test_vanilla_admission_runs_the_arm9_anchors():
    w = World(pre=lambda x: x.m.__setitem__(slice(0x02000CD0 - 0x02000000, 0x02000CD0 - 0x02000000 + 4), b"\0\0\0\0"),
              start=False)
    assert w.session is None and "anchor check failed" in w.admit_why


def test_hge_is_admitted_by_hash_only():
    w = World("heartgold_hge")
    assert w.session is not None and w.session.admitted.pack == "gen4_hge"


@pytest.mark.parametrize("title", ["heartgold", "heartgold_hge"])
def test_step0_exactly_one_hello_then_a_tick_every_30_frames_and_no_hook_or_write(title):
    w = World(title, party=two_mon())
    bw = spy(w, w.session.driver, "battle_write")
    w.advance(100)
    w.enter_battle()                                  # a battle with NO force command: still nothing to write
    w.advance(100)
    assert len(w.events("hello")) == 1 and w.sent[0]["event"] == "hello"
    ticks = [f for m, f in zip(w.sent, w.sent_frames, strict=True) if m["event"] == "tick"]
    assert ticks and all(f % 30 == 0 for f in ticks)
    first = next(f for m, f in zip(w.sent, w.sent_frames, strict=True) if m["event"] == "tick")
    assert ticks == list(range(first, 201, 30))      # every 30 frames, none skipped
    assert w.hook_registrations == 0 and w.writes == [] and lines(bw) == []
    assert w.state.pre_err is None


# ── step 1: snapshot + reducer, pre_pump only ────────────────────────────────────────────
def test_box_generation_returns_two_values():
    w = World(boxes={(0, 0): Mon(0x11111111, 16, 3, 13, 13)})
    w.boot(80)
    got = w.session.driver.box_generation()
    assert isinstance(got, tuple) and len(got) == 2 and got[1] is True


def test_a_nil_boxes_frame_does_not_bump_the_generation_and_a_complete_scan_does():
    w = World(boxes={(0, 0): Mon(0x11111111, 16, 3, 13, 13)})
    w.boot(80)
    gen, ok = w.session.driver.box_generation()
    assert ok is True and gen >= 1
    addr = w.box_addr(0, 0)
    good = w.get(addr, 0x88)
    w.put(addr + 0x20, bytes([good[0x20] ^ 0xFF]))    # a torn record: the checksum no longer matches
    assert w.session.driver.rescan_boxes()[0] is False                # (False, why)
    assert w.session.driver.box_generation() == (gen, False)       # no bump, and the flag says why
    w.advance(30)
    assert "pc_boxes" not in w.events("tick")[-1]                   # nothing is published for an incomplete census
    w.put(addr, good)
    assert w.session.driver.rescan_boxes() is True
    assert w.session.driver.box_generation() == (gen + 1, True)


def test_an_unchanged_idle_edge_does_not_bump_the_generation_but_a_moved_mon_does():
    w = World(boxes={(0, 0): Mon(0x11111111, 16, 3, 13, 13)})
    w.boot(80)
    gen = w.session.driver.box_generation()[0]
    w.field(task=1)
    w.advance(3)
    w.field(task=0)
    w.advance(5)
    assert w.session.driver.box_generation() == (gen, True)        # the signature is unchanged: no heavy scan
    w.boxes[(0, 1)] = Mon(0x22222222, 16, 3, 13, 13)
    w.write_boxes()
    w.field(task=1)
    w.advance(3)
    w.field(task=0)
    w.advance(5)
    assert w.session.driver.box_generation() == (gen + 1, True)


def test_the_reducer_runs_on_the_snapshot_a_new_party_mon_is_a_gift_capture():
    w = World()
    w.boot(80)
    assert w.events("capture") == []
    w.party.append(Mon(0x33333333, 16, 3, 13, 13))
    w.write_party()
    w.advance(10)
    caps = w.events("capture")
    assert [c["key"] for c in caps] == [key_of(0x33333333)] and caps[0]["gift"] is True
    assert w.state.pre_err is None


def test_a_local_battler_at_zero_hp_is_one_faint_event():
    w = World(party=two_mon())
    w.boot(80)
    w.enter_battle()
    w.advance(5)
    w.set_battle_hp(0, 0)
    w.advance(6)
    faints = w.events("faint")
    assert [f["key"] for f in faints] == [A and w.party[0].key]


def test_poll_runs_only_in_pre_pump_and_there_are_no_frame_hooks():
    w = World()
    drv = w.session.driver
    assert drv.frame_hooks is None                    # a frame hook reads one frame late: none exists
    flag = w.lua.table_from({"in_pp": False, "polls": 0, "outside": 0})
    w.lua.eval("""function(drv, sig, flag)
        local pp, poll = drv.pre_pump, sig.poll
        drv.pre_pump = function() flag.in_pp = true; pp(); flag.in_pp = false end
        sig.poll = function(...) flag.polls = flag.polls + 1; if not flag.in_pp then flag.outside = flag.outside + 1 end
                                  return poll(...) end
    end""")(drv, w.signals, flag)
    w.advance(40)
    assert flag["polls"] == 40 and flag["outside"] == 0


@pytest.mark.parametrize(("what", "kw"), [
    ("taskman", {"task": 1}), ("no field map", {"live": 0}), ("launched app (child)", {"launched": 0x022A0500}),
    ("field app (parent) null", {"app": 0})])
def test_idle_is_the_safety_checkpoint_one_clause_each(what, kw):
    w = World()
    w.boot(80)
    assert w.session.driver.checkpoint_ok()[0] is True
    w.field(**kw)
    w.advance(2)
    ok, why = w.session.driver.checkpoint_ok()
    assert ok is False and why, what
    w.field()
    w.advance(2)
    assert w.session.driver.checkpoint_ok()[0] is True


# ── step 2: the D7 faint, the one-frame lease ────────────────────────────────────────────
def test_renew_then_fire_writes_exactly_once_both_hp_copies_and_the_faint_bit():
    w = armed_world()
    assert len(w.hooks) == 1 and w.writes == []
    before = snapshot_bytes(w)
    assert before == (20, 20, 0)
    w.dispatch_seam(cmd=seam_cmd(w))
    w.advance(1)
    assert len(w.writes) == 3 and {n for _, _, n in w.writes} == {4, 2}
    assert snapshot_bytes(w) == (0, 0, 1)
    assert w.hooks == {}                              # single shot: the drain removed the hook
    assert len(w.session.battle_pending) == 0         # the completion latch: the next battle_write said "done"
    assert any("D7 faint written" in s for s in w.logs)
    w.dispatch_seam(cmd=seam_cmd(w))                  # a later dispatch finds no hook: no second write
    w.advance(5)
    assert len(w.writes) == 3 and w.hook_registrations == 1
    assert w.events("faint") == []                    # our own zero is commanded: never echoed as a faint


def test_a_held_hook_is_busy_not_an_error_and_is_never_reregistered():
    w = armed_world()
    req = spy(w, w.signals, "request")
    bw = spy(w, w.session.driver, "battle_write")
    w.advance(6)
    assert w.hook_registrations == 1 and len(w.hooks) == 1
    assert set(lines(bw)) == {"hold|D7 seam armed"}
    assert set(lines(req)) == {"nil|busy: d7 already armed"}      # busy = held, every frame, and it renews the lease
    assert w.state.d7.renewed_frame == w.frame


GUARDS = [   # (name, the one fault, the refusal it must be refused FOR; None = the overlay guard drops the hit silently)
    ("stale r1", lambda w: w.dispatch_seam(cmd=seam_cmd(w), r1=CTX + 4), "r1 is not the battle context"),
    ("stale r0", lambda w: w.dispatch_seam(cmd=seam_cmd(w), r0=BS + 4), "r0 is not the battle system"),
    ("wrong command", lambda w: w.dispatch_seam(cmd=5), "is not the seam command"),
    ("another overlay resident", lambda w: (w.set_overlay(99), w.dispatch_seam(cmd=seam_cmd(w))), None),
    ("key not a local battler", lambda w: (w.battler(0, w.party[1], 0), w.dispatch_seam(cmd=seam_cmd(w))),
     "key is not a local battler"),
    ("party slot pin differs", lambda w: (w.battler(0, w.party[0], 1), w.dispatch_seam(cmd=seam_cmd(w))),
     "party slot pin differs"),
    ("exempt battle type", lambda w: (w.w(BS + w.prof["battle"]["type_off"], 8), w.dispatch_seam(cmd=seam_cmd(w))),
     "battle type is exempt"),
    ("record locked", lambda w: (w.w(w.battle_party_rec(0) + 4, 1, 2), w.dispatch_seam(cmd=seam_cmd(w))), "locked"),
    ("hp copies incoherent", lambda w: (w.set_battle_hp(0, 0), w.dispatch_seam(cmd=seam_cmd(w))),
     "hp copies incoherent"),
    ("record identity differs", lambda w: (w.put(w.battle_party_rec(0), w.party[1].party_raw()),
                                           w.dispatch_seam(cmd=seam_cmd(w))), "record identity differs"),
]


@pytest.mark.parametrize(("name", "fault", "why"), GUARDS, ids=[g[0] for g in GUARDS])
def test_every_guard_writes_zero_bytes(name, fault, why):
    w = armed_world()
    fault(w)
    w.advance(1)
    assert w.writes == [], name                       # every client write goes through io: none happened
    if why is None:
        assert len(w.hooks) == 1 and not any("D7 write refused" in s for s in w.logs)   # dropped before the callback
    else:
        assert any("D7 write refused" in s and why in s for s in w.logs), w.logs


def test_a_lease_not_renewed_by_the_previous_frame_writes_zero_bytes():
    w = armed_world()
    w.session.writes_enabled = False                  # the core now skips battle_write (writes paused)
    w.advance(1)                                      # this frame's flush does NOT renew
    assert len(w.hooks) == 1                          # pre_pump of THIS frame cannot see it yet: still armed
    w.dispatch_seam(cmd=seam_cmd(w))
    w.advance(1)                                      # the hook fires inside this advance, lease one frame stale
    assert w.writes == [] and snapshot_bytes(w) == (20, 20, 0)
    assert any("lease not renewed" in s for s in w.logs)


def test_pre_pump_disarms_an_unrenewed_lease_as_cleanup():
    w = armed_world()
    w.session.writes_enabled = False
    w.advance(3)
    assert w.hooks == {} and w.state.d7 is None and w.writes == []
    w.session.writes_enabled = True
    w.advance(2)                                      # the held entry re-arms on its own next call
    assert len(w.hooks) == 1 and w.hook_registrations == 2


def test_the_d7_phase_declares_no_active_predicate_so_poll_never_rearms_it():
    w = armed_world()
    w.dispatch_seam(cmd=seam_cmd(w))
    w.advance(1)
    assert w.hooks == {}
    w.advance(20)
    assert w.hook_registrations == 1 and w.hooks == {}              # an `active` predicate would re-arm it here


def test_a_pack_gap_holds_the_entry_and_arms_nothing():
    w = armed_world(d7=None)
    assert w.hook_registrations == 0
    assert "pack_gap:battle.d7.seam" in w.session.battle_pending[1].why


def test_the_missed_seam_on_the_ending_frame_defers_loudly_not_silently():
    w = armed_world()
    w.leave_battle()
    w.advance(3)
    assert w.hooks == {} and w.writes == []
    assert any("no in-battle write landed" in s for s in w.logs)
    assert any("not implemented" in s for s in w.logs)             # the step-4 executor refuses with a reason


def test_a_failed_readback_is_fatal_revokes_d7_and_hands_later_entries_to_the_checkpoint():
    w = armed_world()
    w.drop_writes.add(w.battle_party_rec(0) + 0x8E)               # the party-copy write is silently lost
    w.dispatch_seam(cmd=seam_cmd(w))
    w.advance(1)
    assert "party hp nonzero" in w.state.revoked and any("D7 FATAL" in s for s in w.logs)
    w.reply({"cmd": "force_faint", "key": w.party[1].key})
    w.advance(4)
    assert w.hook_registrations == 1                              # revoked: never armed again


def test_hge_derives_the_seam_from_the_rom_dispatch_table_command_9():
    w = armed_world("heartgold_hge")
    assert [a for _, a, _ in w.hooks.values()] == [0x022494DC]
    w.dispatch(0x0224A70C, BS, CTX)                               # the HG seam address: never hooked on hge
    w.advance(1)
    assert w.writes == []
    w.dispatch_seam(cmd=9)
    w.advance(1)
    assert len(w.writes) == 3 and snapshot_bytes(w) == (0, 0, 1)


# ── step 3: the 900-frame effect window ──────────────────────────────────────────────────
def written_world(party=None):
    w = armed_world(party=party)
    w.dispatch_seam(cmd=seam_cmd(w))
    w.advance(1)
    assert len(w.writes) == 3
    return w, w.frame


def effect_at(w, written, k, how):
    w.run_to(written + k - 1)
    assert w.state.effect is None
    if how == "repl":
        w.set_repl(0, 1)
    else:
        w.set_outcome(w.prof["battle_enums"]["outcomes"]["lose"])
    w.advance(1)
    return w.state.effect


@pytest.mark.parametrize("k", [1, 155, 900])
def test_an_effect_inside_the_window_is_satisfied(k):
    w, written = written_world()
    e = effect_at(w, written, k, "repl")
    assert e.result == "satisfied" and e.via == "replacement" and e.frames == k


def test_an_effect_first_seen_at_plus_901_is_late_and_not_satisfied():
    w, written = written_world()
    e = effect_at(w, written, 901, "repl")
    assert e.result == "late" and e.result != "satisfied" and e.frames == 901
    assert any("D7 effect late" in s for s in w.logs)


def test_no_effect_at_all_expires_exactly_at_plus_901_and_a_later_effect_is_not_credited():
    w, written = written_world()
    w.run_to(written + 900)
    assert w.state.effect is None and w.state.watch is not None     # still inside the window at +900
    w.advance(1)
    assert w.state.effect.result == "expired" and w.state.effect.frames == 901
    w.set_repl(0, 1)
    w.run_to(written + 5000)                                         # +5000: an unrelated replacement is not this write's effect
    assert w.state.effect.result == "expired"


def test_the_one_mon_party_is_satisfied_by_the_lose_result_byte():
    w, written = written_world(party=[Mon(A.pid, 155, 5, 20, 20)])
    e = effect_at(w, written, 12, "lose")
    assert e.result == "satisfied" and e.via == "lose"


def test_the_lose_byte_first_seen_after_the_window_is_not_satisfied():
    w, written = written_world(party=[Mon(A.pid, 155, 5, 20, 20)])
    e = effect_at(w, written, 901, "lose")
    assert e.result == "late" and e.via == "lose"


def test_a_bench_mon_is_held_to_the_battle_end_and_never_arms_the_seam():
    w = World(party=two_mon())
    w.boot(80)
    w.enter_battle()
    w.advance(3)
    w.reply({"cmd": "force_faint", "key": w.party[1].key})
    w.advance(4)
    assert w.hook_registrations == 0 and "not an active battler" in w.session.battle_pending[1].why
    w.leave_battle()
    w.advance(2)
    assert any("no in-battle write landed" in s for s in w.logs) and w.writes == []
