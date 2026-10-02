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
import struct

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
    ("taskman", {"task": 1}), ("no field map", {"live": 0}), ("launched app (unk4)", {"launched": 0x022A0500}),
    ("field app (unk0) null", {"app": 0})])
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
    w = armed_world(d7=None, no_pack_d7=True)
    assert w.hook_registrations == 0
    assert "pack_gap:battle.d7.seam" in w.session.battle_pending[1].why


def test_the_missed_seam_on_the_ending_frame_defers_loudly_and_the_checkpoint_executor_lands_it():
    w = armed_world()
    w.leave_battle()
    w.advance(6)
    assert w.hooks == {}
    assert any("no in-battle write landed" in s for s in w.logs)    # D12: the fallback carries a logged reason
    assert w.saved_hp(0) == 0 and w.saved_hp(1) == 11               # step 4: party HP zero at the checkpoint


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
    assert w.writes == []
    w.leave_battle()
    w.advance(6)
    assert any("no in-battle write landed" in s for s in w.logs)
    assert w.saved_hp(1) == 0 and w.saved_hp(0) == 20                # only the commanded mon


# ── step 4: deferred box / party writes at the checkpoint ────────────────────────────────
X = Mon(0x7777AAAA, 16, 3, 13, 13, otid=0x0000BEEF)
STATS = {"level": 7, "maxHP": 30, "attack": 11, "defense": 12, "speed": 13, "spAtk": 14, "spDef": 15}


def ready(title="heartgold", party=None, boxes=None, **kw):
    w = World(title, party=party or two_mon(), boxes=boxes, **kw)
    w.boot(80)
    return w


def test_the_overworld_faint_zeroes_the_party_hp_and_is_never_echoed_as_a_faint():
    w = ready()
    w.reply({"cmd": "force_faint", "key": w.party[0].key})
    w.advance(5)
    assert w.saved_hp(0) == 0 and w.saved_hp(1) == 11
    assert {n for _, _, n in w.writes} == {1} and len(w.writes) == 2     # the u16 HP, nothing else
    assert w.events("faint") == [] and w.state.fatal is None


@pytest.mark.parametrize("title", ["heartgold", "heartgold_hge"])
def test_battery_modified_word_at_1_with_an_idle_driver_still_arms(title):
    w = ready(title, boxes={(0, 5): Mon(0x44444444, 16, 3, 13, 13)})
    w.w(w.modified_word_addr(), 1)                                      # the battery keeps this at 1 permanently
    w.advance(40)
    assert w.session.driver.checkpoint_ok()[0] is True
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(5)
    assert w.party[0].key in w.box_keys() and w.saved_keys() == [w.party[1].key]
    assert w.events("box_mon_failed") == []


def test_a_busy_save_driver_refuses_and_nothing_is_written():
    w = ready()
    w.field(driver_state=0)                                             # the save driver is mid-write
    w.advance(3)
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(20)
    ok, why = w.session.driver.checkpoint_ok()
    assert ok is False and "save_busy" in why
    assert w.writes == [] and w.box_keys() == {} and w.events("box_mon_failed") == []
    assert w.session.deferred["items"][1].cmd == "box_mon"                # still queued, not dropped
    w.field(driver_state=1)
    w.advance(5)
    assert w.party[0].key in w.box_keys()


def test_a_deposit_keeps_the_box_checksum_the_party_order_and_sets_the_dirty_bit():
    w = ready(party=[Mon(0x10000001), Mon(0x10000002), Mon(0x10000003)])
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(5)
    assert w.saved_keys() == [key_of(0x10000002), key_of(0x10000003)]   # shifted, count shrank
    assert w.box_keys() == {key_of(0x10000001): (0, 0)}                 # decrypts: the checksum is intact
    assert w.r(w.modified_word_addr(), 4) == 1                          # PCStorage_SetBoxModified: flag |= 1 << box
    assert len(w.events("stats_cache")) == 1
    assert w.events("capture") == [] and w.events("party_to_box") == []  # our own move is not the player's


def test_a_withdraw_restores_the_party_tail_from_the_cached_stats():
    mon = Mon(0x55555555, 155, 7, 3, 30)
    w = ready(party=[Mon(A.pid)], boxes={(2, 4): mon})
    w.reply({"cmd": "party_mon", "key": mon.key, "stats": STATS})
    w.advance(5)
    assert w.saved_keys() == [key_of(A.pid), mon.key] and w.box_keys() == {}
    tail = w.saved_party()[1]
    assert tail[0x8C] == 7 and struct.unpack_from("<HH", tail, 0x8E) == (30, 30)
    assert struct.unpack_from("<5H", tail, 0x92) == (11, 12, 13, 14, 15)
    assert [m["key"] for m in w.events("sync_retrieve_done")] == [mon.key]
    assert w.r(w.modified_word_addr(), 4) == 1 << 2
    assert w.events("box_to_party") == []


def test_a_withdraw_without_the_stats_is_refused_before_any_byte():
    mon = Mon(0x55555555)
    w = ready(party=[Mon(A.pid)], boxes={(0, 0): mon})
    w.reply({"cmd": "party_mon", "key": mon.key})
    w.advance(5)
    assert w.writes == [] and w.events("sync_retrieve_failed")[0]["reason"] == "missing stats"


def test_memorialize_moves_a_party_mon_to_the_memorial_box_and_never_the_last_party_mon():
    w = ready()
    w.reply({"cmd": "memorialize", "key": w.party[1].key})
    w.advance(5)
    assert w.box_keys() == {w.party[1].key: (17, 0)} and w.saved_keys() == [w.party[0].key]
    assert [m["key"] for m in w.events("memorialize_done")] == [w.party[1].key]
    assert w.r(w.modified_word_addr(), 4) == 1 << 17
    n = len(w.writes)
    w.reply({"cmd": "memorialize", "key": w.party[0].key})              # the last mon: blocked, never written
    w.advance(10)
    assert len(w.writes) == n and w.saved_keys() == [w.party[0].key]


def test_two_boxed_records_on_one_key_are_refused_not_guessed():
    twin = Mon(0x66666666)
    w = ready(boxes={(0, 0): twin, (1, 0): twin})
    w.reply({"cmd": "box_mon", "key": twin.key})
    w.advance(5)
    assert w.writes == [] and "ambiguous" in w.events("box_mon_failed")[0]["reason"]


def test_a_locked_record_is_refused_with_nothing_written():
    w = ready()
    w.w(w.party_base + 8 + 4, 1, 2)                                     # partyDecrypted: plaintext representation
    w.advance(2)
    w.reply({"cmd": "force_faint", "key": w.party[0].key})
    w.advance(6)
    assert w.writes == []


def test_a_write_that_fails_readback_is_fatal_visible_and_closes_the_gate():
    w = ready()
    w.drop_writes.add(w.box_addr(0, 0))                                 # the box record first byte is silently lost
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(5)
    assert w.state.fatal and "readback differs" in w.state.fatal
    assert any("STORAGE FATAL" in s for s in w.logs)
    assert w.events("box_mon_failed")[0]["reason"].startswith("fatal")  # never reported as success
    ok, why = w.session.driver.checkpoint_ok()
    assert ok is False and "write fault" in why
    n = len(w.writes)
    w.reply({"cmd": "force_faint", "key": w.party[1].key})
    w.advance(10)
    assert len(w.writes) == n                                           # revoked: nothing further lands


# ── step 5: D11 key_change for an NPC trade ──────────────────────────────────────────────
def trade_world():
    w = ready()
    w.party[0] = Mon(X.pid, 16, 3, 13, 13, otid=X.otid)
    w.write_party()
    w.advance(8)
    return w


def test_an_npc_trade_is_one_key_change_with_the_alias_and_the_exact_message_on_it():
    w = trade_world()
    kc = w.events("key_change")
    assert len(kc) == 1
    assert kc[0]["old_key"] == key_of(A.pid) and kc[0]["new_key"] == X.key
    assert kc[0]["reason"] == "npc_trade" and kc[0]["new_species"] == 16
    pend = w.session.identity.pending
    assert pend.old_key == key_of(A.pid) and pend.msg.new_key == X.key


def test_a_rejected_change_then_a_reorder_still_finds_the_changed_record_and_no_bystander():
    w = trade_world()
    w.reply({"cmd": "key_change_rejected", "old_key": key_of(A.pid), "new_key": X.key, "reason": "collision"})
    w.advance(2)
    w.party = [w.party[1], w.party[0]]                                  # the player reorders: X is now slot 1
    w.write_party()
    w.advance(3)
    w.reply({"cmd": "force_faint", "key": key_of(A.pid)})               # the server still names the OLD key
    w.advance(6)
    assert w.saved_hp(1) == 0 and w.saved_hp(0) == 11                   # the changed record, not the bystander


def test_a_rejected_change_whose_record_left_the_party_retires_nothing():
    w = trade_world()
    w.reply({"cmd": "key_change_rejected", "old_key": key_of(A.pid), "new_key": X.key, "reason": "collision"})
    w.advance(2)
    w.boxes[(0, 0)] = w.party[0]                                        # X goes to the PC
    w.party = [w.party[1]]
    w.write_party()
    w.write_boxes()
    w.advance(3)
    w.reply({"cmd": "force_faint", "key": key_of(A.pid)})
    w.advance(6)
    assert w.writes == [] and w.saved_hp(0) == 11


def test_two_party_records_on_one_key_are_refused():
    w = ready(party=[Mon(A.pid), Mon(A.pid)])
    w.reply({"cmd": "force_faint", "key": key_of(A.pid)})
    w.advance(6)
    assert w.writes == [] and any("ambiguous" in s for s in w.logs)


def test_a_retryable_refusal_resends_the_exact_key_change_after_a_newer_complete_census():
    w = trade_world()
    first = w.events("key_change")[0]
    w.reply({"cmd": "key_change_rejected", "old_key": first["old_key"], "new_key": first["new_key"],
             "reason": "ambiguous key (trade clash)"})
    w.advance(40)
    assert len(w.events("key_change")) == 1                             # armed, nothing resent without a newer census
    w.boxes[(0, 1)] = Mon(0x88888888)                                   # a box changes: the next complete census is newer
    w.write_boxes()
    w.field(task=1)
    w.advance(3)
    w.field(task=0)
    w.advance(70)
    kc = w.events("key_change")
    assert len(kc) == 2
    assert {k: v for k, v in kc[1].items() if k != "seq"} == {k: v for k, v in kc[0].items() if k != "seq"}


# ── step 6: the full hello / tick (every line is strict-validated by the world) ────────────
def test_hello_and_tick_carry_what_gen4_can_supply():
    w = World(party=two_mon(), boxes={(0, 3): Mon(0x99999999, 16, 3, 13, 13)},
              charmap={0x12: "A", 0x13: "B", 0x14: "C"},
              area_of="function(map, loc) return 'route_' .. map, 'Route ' .. map end")
    w.set_badges(0xA5, 0x3C)
    w.boot(80)
    h = w.events("hello")[0]
    assert h["rom_type"] == "heartgold" and h["rom_sha1"] == w.title["rom"]["sha1"]
    assert h["ot_id"] == 0x30391A5C and h["badges"] == 0xA5 and h["trainer_name"] == "ABC" and h["player_gender"] == 0
    assert h["area_id"] == "route_60" and h["loc_name"] == "Route 60"
    assert [e["key"] for e in h["pc_boxes"]] == [key_of(0x99999999)] and h["pc_boxes_generation"] >= 1
    assert h["party"][0]["species_id"] == 155 and h["party"][0]["status_cond"] == 0 and h["party"][0]["active"] is False
    t = w.events("tick")[-1]
    assert t["kanto_badges"] == 0x3C and t["badges"] == 0xA5 and t["in_battle"] is False and t["enemy_party"] == []
    assert t["is_trainer_battle"] is False and t["area_id"] == "route_60"


@pytest.mark.parametrize(("btype", "trainer", "doubles"), [(0, False, False), (1, True, False), (2, False, True)])
def test_the_tick_in_battle_names_the_foe_the_battle_kind_and_the_active_mon(btype, trainer, doubles):
    w = ready(area_of="function(map) return 'route_' .. map, 'Route' end")
    w.enter_battle(btype=btype)
    w.advance(40)
    t = w.events("tick")[-1]
    assert t["in_battle"] is True and t["is_trainer_battle"] is trainer and t["is_doubles"] is doubles
    assert [e["species_id"] for e in t["enemy_party"]] == [16] and t["area_id"] == "route_60"
    assert [p["active"] for p in t["party"]] == [True, False]
