"""MODEL controls for the injected RR mailbox owner; no emulator or ROM required."""
import json
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]


class World:
    def __init__(self, present=True, initial_seq=0, kind="companion", scene_capability_model=False, abi=1):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.profile = json.loads((ROOT / "data/games/gen3_rr/profile.json").read_text())
        self.n = self.profile["native"]
        if abi == 2:
            from tools.gen_gen3_profile import native_abi
            self.n["ABI"], self.n["abi_v2"] = 2, native_abi()
            self.n["BASE"] = 0x0201B000  # private MODEL arena; no admitted v2 profile
        self.ram = self.profile["titles"]["radical_red"]["ram"]
        self.bus = {}
        self.frame = 10
        self.events = []
        self.output = []
        self.safe = True
        self.check_native_idle = False
        self.battle = True
        self.panel_result = 127
        if present:
            self.put(self.n["BASE"], self.n["SIG"], 4)
            self.put(self.n["BASE"] + 4, self.n["ABI"], 2)
            if abi == 2:
                self.put(self.n["BASE"] + 0x40, 0x04, 4)  # CAP_NATIVE_SOUND, not trade
        runtime = self.lua
        io = runtime.table(read_u8=lambda a: self.read(a, 1),
                           read_u16=lambda a: self.read(a, 2),
                           read_u32=lambda a: self.read(a, 4),
                           read_bytes=lambda a, n: runtime.table(*self.raw(a, n)),
                           framecount=lambda: self.frame)
        self.native_io = io
        writes_mod = runtime.execute((ROOT / "lua/gen3/writes.lua").read_text())
        self.writes = writes_mod.new(runtime.table(
            frame=lambda: self.frame,
            safety=runtime.table(snapshot=lambda *_: runtime.table(),
                                 check=lambda *_: (
                                     self.safe and (not self.check_native_idle
                                                    or self.native.idle(self.native)),
                                     "unsafe native checkpoint")),
            io=runtime.table(write_u8=self.write)))
        reads_mod = runtime.execute((ROOT / "lua/gen3/reads.lua").read_text(encoding="utf-8"))
        self.reads = reads_mod.new(runtime.table_from(
            self.profile["titles"]["radical_red"], recursive=True), io)
        module = runtime.execute((ROOT / "lua/gen3/native.lua").read_text(encoding="utf-8"))
        self.native = module.new(runtime.table_from(self.profile, recursive=True), runtime.table(
            io=io, writes=self.writes, reads=self.reads, initial_seq=initial_seq,
            artifact_kind=kind,
            timeout_frames=5, send=lambda event, fields: self.events.append((event, fields)),
            in_battle=lambda: self.battle,
            panel_closed=lambda: (True, self.panel_result)))
        if scene_capability_model:
            # Queue/receipt MODEL only; this does not qualify a shipped v2 binding.
            self.native.trade_capable = lambda *_: True

    def put(self, address, value, size=1):
        for i in range(size):
            self.bus[address + i] = (value >> (8 * i)) & 255

    def read(self, address, size):
        return sum(self.bus.get(address + i, 0) << (8 * i) for i in range(size))

    def raw(self, address, size):
        return bytes(self.bus.get(address + i, 0) for i in range(size))

    def write(self, address, value, *_):
        self.output.append((address, value))
        self.put(address, value)

    def service(self):
        self.native.service(self.native)

    def ack(self, status=2, result=0):
        base = self.n["BASE"]
        self.put(base + 12, self.read(base + 8, 2), 2)
        self.put(base + 10, status, 2)
        self.put(base + 6, 0, 2)
        self.put(base + 48, result)


def test_absent_native_does_not_stage_or_write():
    w = World(present=False)
    assert w.native.play_sound(w.native, 25) == (None, "native absent")
    w.service()
    assert w.output == []


def test_v2_mailbox_reads_capabilities_and_queues_only_epoch_handshake():
    w = World(abi=2)
    fields = w.native.mailbox(w.native)
    assert fields.capabilities == 4 and fields.session_epoch == 0
    assert w.native.trade_capable(w.native) is False
    w.native.set_session_epoch(w.native, 0x12345678)
    assert w.output == []
    w.safe = False
    w.service()
    assert w.output == []
    w.safe = True
    w.service()
    assert w.read(w.n["BASE"] + 0x44, 4) == 0x12345678
    assert [a for a, _ in w.output] == list(range(w.n["BASE"] + 0x44, w.n["BASE"] + 0x48))
    assert w.native.mailbox(w.native).capabilities == 4
    assert w.native.mailbox(w.native).session_epoch == 0x12345678


@pytest.mark.parametrize("epoch", [0, -1, 1.5, 0x100000000])
def test_v2_rejects_invalid_epoch_without_writes(epoch):
    w = World(abi=2)
    assert w.native.set_session_epoch(w.native, epoch) == (None, "invalid session epoch")
    w.service()
    assert w.output == []


@pytest.mark.parametrize("abi,reason,expected", [
    (2, 11, "uncertain"), (2, 12, "identity"), (2, 13, "client_too_old"), (2, 99, None),
    (1, 11, None), (1, 12, None), (1, 13, None),
])
def test_failure_reason_names_are_bound_to_mailbox_abi(abi, reason, expected):
    w = World(abi=abi)
    if abi == 2:
        w.native.set_session_epoch(w.native, 1)
        w.service()
    results = []
    w.native.transfer(w.native, "enemy", w.lua.table(blobs_hex=w.lua.table("00" * 100)),
                      lambda *args: results.append(args))
    w.service()
    w.ack(status=3)
    w.put(w.n["BASE"] + 14, reason, 2)
    w.service()
    assert results == [("native refused", 0, expected)]


def test_v2_commands_require_handshake_and_refuse_changed_epoch():
    w = World(abi=2)
    assert w.native.play_sound(w.native, 25) == (None, "client_too_old")
    assert w.output == []
    w.native.set_session_epoch(w.native, 9)
    w.service()
    results = []
    w.native.transfer(w.native, "enemy", w.lua.table(blobs_hex=w.lua.table("00" * 100)),
                      lambda *args: results.append(args))
    before = len(w.output)
    w.put(w.n["BASE"] + 0x44, 10, 4)
    w.service()
    assert len(w.output) == before and results[0][0] == "native epoch changed"


def test_v2_panel_and_control_do_not_inherit_v1_memory_layout():
    w = World(abi=2)
    assert w.native.link_panel(w.native, w.lua.table(rows=w.lua.table("hello"))) == (
        None, "v2 panel binding unavailable")
    assert w.native.config(w.native, w.lua.table(pc_trade_npc=True, battle_calc=True)) == (
        None, "v2 control binding unavailable")
    w.service()
    assert w.output == []


def test_clean_artifact_does_not_trust_a_stale_companion_signature():
    w = World(kind="clean")
    assert w.native.play_sound(w.native, 25) == (None, "native absent")
    w.service()
    assert w.output == []


def test_sound_waits_until_previous_ack_is_consumed():
    w = World()
    w.native.show_menu(w.native, w.lua.table(token="menu", text="Ready?"))
    w.service()
    first = w.read(w.n["BASE"] + 8, 2)
    w.native.play_sound(w.native, 25)
    w.ack(result=1)
    w.service()
    assert [(e, f.token, f.choice) for e, f in w.events] == [("menu_result", "menu", 1)]
    assert w.read(w.n["BASE"] + 8, 2) != first
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_PLAY_SE"]
    assert all(w.writes.log[i].reason == "native" for i in range(1, len(w.writes.log) + 1))


def test_queue_owns_text_until_first_operation_finishes():
    w = World()
    first = w.lua.table(token="first", text="FIRST")
    second = w.lua.table(token="second", text="SECOND")
    w.native.show_menu(w.native, first)
    w.native.show_menu(w.native, second)
    second.text = "MUTATED"
    first.token = "MUTATED"
    assert w.output == []
    w.service()
    staged = w.raw(w.n["TEXT_BUF"], 6)
    w.service()
    assert w.raw(w.n["TEXT_BUF"], 6) == staged
    w.ack()
    w.service()
    assert w.events[0][1].token == "first"
    assert w.raw(w.n["TEXT_BUF"], 7) == bytes([0xCD, 0xBF, 0xBD, 0xC9, 0xC8, 0xBE, 0xFF])


@pytest.mark.parametrize("operation,cancel", [("show_menu", 0), ("show_choices", 127),
                                            ("choose_mon", 7)])
def test_refused_ui_has_the_exact_cancel_result(operation, cancel):
    w = World()
    cmd = w.lua.table(token="t", text="Pick", options=w.lua.table("A", "B"))
    getattr(w.native, operation)(w.native, cmd)
    w.service()
    w.ack(status=3)
    w.service()
    event, fields = w.events[0]
    assert fields.token == "t"
    assert (fields.slot if event == "mon_chosen" else fields.choice) == cancel
    assert w.native.idle(w.native) is True


# ── C5-7: per-job dispatch receipts ───────────────────────────────────────────────────────

def test_a_published_job_carries_its_own_dispatch_receipt():
    """The job table IS the handle: queued -> no flag, published -> the flag. Nothing infers it."""
    w = World(scene_capability_model=True)
    handle = w.native.transfer(w.native, "scene", w.lua.table(slot=0), lambda *_: None)
    assert handle["posted"] is None                              # queued, not posted
    w.service()
    assert handle["posted"] is True
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_TRADE_SCENE"]   # the publish the receipt names


def test_partial_opcode_publication_is_distinct_from_no_dispatch():
    class InterruptedWorld(World):
        def write(self, address, value, *_):
            if address == self.n["BASE"] + 7:
                raise RuntimeError("high opcode byte failed")
            super().write(address, value)

    w = InterruptedWorld(scene_capability_model=True)
    results = []
    handle = w.native.transfer(w.native, "scene", w.lua.table(slot=0), lambda *args: results.append(args))
    w.service()
    assert handle["posted"] is None
    assert handle["publish_attempted"] is True
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_TRADE_SCENE"]
    assert results[0][0] == "native dispatch interrupted"


def test_shipped_native_declares_the_complete_trade_transport_interface():
    w = World()
    for method in ("trade_visit", "trade_eligible", "trade_authorized", "prepare_trade", "withdraw_trade", "cancel", "transfer"):
        assert w.native[method] is not None, method
    arity = w.lua.eval('function(f) return debug.getinfo(f, "u").nparams end')
    assert arity(w.native.transfer) == 6  # self, step, cmd, done, guard, milestone callback
    assert w.native.trade_capable(w.native) is False


def test_shipped_native_refuses_durable_scene_without_capability():
    w = World()
    results = []
    result = w.native.transfer(w.native, "scene", w.lua.table(slot=0),
                               lambda *args: results.append(args), None, lambda *_: None)
    assert result == (None, "durable_trade_unavailable")
    w.service()
    assert results == [("durable_trade_unavailable",)] and w.output == []


def test_shipped_v1_scene_probe_without_progress_returns_and_posts_a_job():
    """Proxy for lua/tests/test_live_tradescene.lua's direct transport call."""
    w = World()
    assert w.native.trade_capable(w.native) is False
    handle = w.native.transfer(w.native, "scene", w.lua.table(slot=0))
    assert not isinstance(handle, tuple) and handle is not None
    w.service()
    assert handle.posted is True
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_TRADE_SCENE"]


def test_progress_argument_does_not_block_unrelated_enemy_staging():
    w = World()
    handle = w.native.transfer(w.native, "enemy", w.lua.table(blobs_hex=w.lua.table("00" * 100)),
                               lambda *_: None, None, lambda *_: None)
    assert not isinstance(handle, tuple)
    w.service()
    assert handle.posted is True


def test_transfer_blob_length_uses_the_reads_facade_record_size():
    w = World()
    w.reads.PARTY_MON_SIZE = 80  # MODEL alternate record geometry, not a cartridge claim
    handle = w.native.transfer(w.native, "enemy", w.lua.table(blobs_hex=w.lua.table("00" * 80)), lambda *_: None)
    assert not isinstance(handle, tuple)
    w.service()
    assert handle.posted is True


def test_a_job_queued_behind_another_carries_no_receipt_yet():
    w = World(scene_capability_model=True)
    first = w.native.play_sound(w.native, 25)
    second = w.native.transfer(w.native, "scene", w.lua.table(slot=0), lambda *_: None)
    w.service()
    assert first["posted"] is True and second["posted"] is None
    w.ack()
    w.service()
    assert second["posted"] is True


def test_a_held_arm_sets_no_receipt_and_leaves_the_job_queued():
    """A refused arm asserts inside dispatch's pcall: the job stays queued (it is not consumed)
    and its receipt stays unset, so no caller can read it as posted."""
    w = World()
    w.safe = False
    handle = w.native.play_sound(w.native, 25)
    w.service()
    assert handle["posted"] is None and w.output == []
    w.safe = True
    w.service()
    assert handle["posted"] is True                              # held, then posted once eligible


def test_a_job_dropped_by_its_guard_carries_no_receipt():
    w = World(scene_capability_model=True)
    seen = []
    handle = w.native.transfer(w.native, "scene", w.lua.table(slot=0),
                               lambda why, _r, _reason=None: seen.append(why),
                               lambda: (False, "guard:moved"))
    w.service()
    assert seen == ["guard:moved"] and handle["posted"] is None and w.output == []


def test_a_stage_only_job_publishes_nothing_and_so_receipts_nothing():
    w = World()
    handle = w.native.config(w.native, w.lua.table(battle_calc=False))
    w.service()
    assert handle["posted"] is None and w.output != []           # staged, but no opcode to publish


def test_the_codex_counterexample_a_completion_write_does_not_receipt_a_refused_trade_arm():
    """REV7's counterexample, with the writer real: one service() call runs a completion callback
    that writes through the sink (G5-RR-RIVAL: the rival swap no longer refreshes gBattleMons, so
    the vehicle is a transfer's own `done`), and then refuses our guarded trade arm -- so a
    sink byte moved and a guard ran, the two inputs the byte-count inference read, while our own
    op was never published."""
    holder = {}

    def writing_done(*_args):
        w.writes.arm(w.writes, "native", holder["allow"])
        holder["write"](w.writes)
        w.writes.disarm(w.writes)

    w = World(scene_capability_model=True)
    # writes.lua type-checks the allow predicate, and lupa hands a Python callable over as
    # userdata (not "function"), so the writer's predicate -- and the write itself, which needs
    # an explicit self when called from Python -- go through Lua.
    holder["allow"] = w.lua.eval("function(addr, n) return true end")
    holder["write"] = w.lua.eval("function(w) w:write_bytes(0x0203F900, {0x5A}) end")
    swap = w.native.transfer(w.native, "enemy",
                             w.lua.table(blobs_hex=w.lua.table("AB" * 100)), writing_done)
    w.service()
    assert swap["posted"] is True
    seen = []
    trade = w.native.transfer(w.native, "scene", w.lua.table(slot=0),
                              lambda why, _r, _reason=None: seen.append(why),
                              lambda: (False, "guard:moved"))
    before = w.writes["attempted"]
    w.ack()                                                      # the swap completes in this call
    w.service()
    assert w.writes["attempted"] > before, "the counterexample needs a real foreign write"
    assert (0x0203F900, 0x5A) in w.output
    assert seen == ["guard:moved"], "and a guard that ran and refused, in the same call"
    assert trade["posted"] is None, "our op was never published, so it cannot read as posted"


# ── C5-11a: the rival swap's own opcode, and the two uses kept apart ─────────────────────────

def test_c511a_the_rival_swap_posts_opcode_28_with_the_trainer_as_u16_le():
    w = World()
    handle = w.native.replace_rival_team(
        w.native, w.lua.table(trainer_id=0x1234, blobs_hex=w.lua.table("AB" * 100)))
    w.service()
    assert handle["posted"] is True
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_RIVAL_SWAP"] == 28
    assert w.read(w.n["BASE"] + 16, 1) == 1                  # count
    assert w.read(w.n["BASE"] + 17, 1) == 0x34               # trainer low byte
    assert w.read(w.n["BASE"] + 18, 1) == 0x12               # trainer high byte


def test_c511a_transfer_enemy_still_posts_the_trade_opcode_16():
    """The field trade's staging is untouched by the rival opcode (handlers.c:1993-1998 documents
    that OP_TRADE_SCENE depends on it)."""
    w = World()
    handle = w.native.transfer(w.native, "enemy", w.lua.table(blobs_hex=w.lua.table("AB" * 100)),
                               lambda *_: None)
    w.service()
    assert handle["posted"] is True
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_SET_ENEMY_PARTY"] == 16


def test_omp_f8_there_is_no_second_ungated_rival_opcode_path():
    """OP_RIVAL_SWAP is posted ONLY by replace_rival_team (hold/ready/guard); transfer() refuses."""
    w = World()
    assert w.native.transfer(w.native, "rival",
                             w.lua.table(trainer_id=5, blobs_hex=w.lua.table("AB" * 100)),
                             lambda *_: None) == (None, "unsupported transfer step")


def test_c511a_a_fail_ack_carries_the_patchs_reason_word_into_the_reply():
    """The patch's reason word (handlers.c owns the numbering) is the reply's error AND reason:
    8 -> window_closed (review F3; was the misleading refresh_failed)."""
    w = World()
    w.native.replace_rival_team(w.native, w.lua.table(trainer_id=5, blobs_hex=w.lua.table("AB" * 100)))
    w.service()
    w.put(w.n["BASE"] + 14, 8, 2)                            # reason = REASON_WINDOW_CLOSED
    w.ack(status=3)                                          # ST_FAIL
    w.service()
    (event, fields), = w.events
    assert fields.error == "window_closed" and fields.reason == "window_closed"


def test_c511a_the_patch_handler_keeps_the_two_uses_apart():
    """No C test harness exists in this repo (and no compiler on this host), so this is a static
    contract over patch/src/handlers.c: opcode 28 exists with the five-part consumption check and
    the window_closed reason, and opcode 16's own case carries NO window check -- the field trade
    stages with 16, so a check there would reject every trade."""
    src = (ROOT / "patch" / "src" / "handlers.c").read_text(encoding="utf-8")
    assert "OP_RIVAL_SWAP = 28" in src
    assert "#define REASON_WINDOW_CLOSED  8u" in src
    rival = src[src.index("case OP_RIVAL_SWAP:"):]
    rival = rival[:rival.index("case OP_SET_ENEMY_PARTY:")]
    for part in ("RV_BATTLE_COMM", "RV_BATTLE_MAIN_FUNC", "RV_GMAIN_CB2", "RV_BATTLE_TYPE_LINK",
                 "RV_TRAINER_OPPONENT", "REASON_WINDOW_CLOSED", "stage_enemy_party(count)"):
        assert part in rival, part
    trade = src[src.index("case OP_SET_ENEMY_PARTY:"):]
    trade = trade[:trade.index("case OP_SET_PARTY_MON:")]
    assert "RV_" not in trade, "opcode 16 must stay free of the window check"
    assert "stage_enemy_party(count)" in trade


@pytest.mark.parametrize("lost_ack", [False, True])
def test_timeout_and_lost_ack_never_reuse_uncertain_mailbox(lost_ack):
    w = World()
    w.native.show_menu(w.native, w.lua.table(token="t", text="Wait"))
    w.service()
    if lost_ack:
        w.put(w.n["BASE"] + 6, 0, 2)  # engine consumed it; receipt was lost
    w.native.play_sound(w.native, 25)
    before = len(w.output)
    w.frame += 5
    assert w.native.service(w.native) == (None, "native timeout")
    assert w.native.idle(w.native) is False
    assert len(w.output) == before
    assert w.events[0][1].choice == 0
    assert w.native.play_sound(w.native, 26) == (None, "native timeout")


def test_overwritten_staging_is_refused_before_ack_success():
    w = World()
    w.native.show_menu(w.native, w.lua.table(token="t", text="Wait"))
    w.service()
    w.put(w.n["TEXT_BUF"], 1)
    w.ack(result=1)
    assert w.native.service(w.native) == (None, "native staging overwritten")
    assert w.events[0][1].choice == 0


@pytest.mark.parametrize("offset,value", [(8, 999), (6, 99), (16, 77)])
def test_foreign_mailbox_mutations_do_not_complete_our_operation(offset, value):
    w = World()
    w.native.play_sound(w.native, 25)
    w.service()
    w.put(w.n["BASE"] + offset, value, 2)
    w.service()
    assert w.native.idle(w.native) is False


def test_rival_queued_in_battle_is_refused_if_battle_ends_before_dispatch():
    w = World()
    w.native.replace_rival_team(w.native, w.lua.table(
        trainer_id=5, blobs_hex=w.lua.table(bytes(100).hex())))
    w.battle = False
    w.service()
    assert w.output == []
    assert w.events[0][1].error == "not_in_battle"


@pytest.mark.parametrize("reset", ["beacon", "frame"])
def test_reset_mid_operation_cancels_stale_queue_without_writes(reset):
    w = World()
    w.native.show_menu(w.native, w.lua.table(token="t", text="Wait"))
    w.service()
    w.native.play_sound(w.native, 25)
    before = len(w.output)
    if reset == "beacon":
        w.put(w.n["BASE"], 0, 4)
    else:
        w.frame = 0
    w.service()
    assert len(w.output) == before
    assert len(w.events) == 1 and w.events[0][1].choice == 0


def test_sequence_wrap_uses_a_nonmatching_ack_sentinel():
    w = World(initial_seq=65535)
    w.native.play_sound(w.native, 25)
    w.service()
    assert w.read(w.n["BASE"] + 8, 2) == 0
    assert w.read(w.n["BASE"] + 12, 2) == 65535
    w.ack()
    w.service()
    assert w.native.idle(w.native) is True


def test_unsafe_native_checkpoint_holds_queue_without_staging():
    w = World()
    w.safe = False
    w.native.show_menu(w.native, w.lua.table(token="t", text="Wait"))
    w.service()
    assert w.output == []
    w.safe = True
    w.service()
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_SHOW_MENU"]


def test_hardware_busy_async_operation_blocks_sound_even_with_zero_opcode():
    w = World()
    w.put(w.n["BASE"] + 10, 1, 2)
    w.native.play_sound(w.native, 25)
    w.service()
    assert w.output == []


def test_native_idle_policy_does_not_deadlock_its_own_atomic_post():
    w = World()
    w.check_native_idle = True
    w.native.show_menu(w.native, w.lua.table(token="t", text="Wait"))
    w.service()
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_SHOW_MENU"]
    assert w.native.idle(w.native) is False
    w.ack(result=1)
    w.service()
    assert w.native.idle(w.native) is True


def test_terminal_status_with_wrong_ack_does_not_count_as_completion():
    w = World()
    w.native.show_menu(w.native, w.lua.table(token="t", text="Wait"))
    w.service()
    w.put(w.n["BASE"] + 6, 0, 2)
    w.put(w.n["BASE"] + 10, 2, 2)
    w.service()
    assert w.events == []
    w.frame += 5
    w.service()
    assert w.events[0][1].choice == 0


def test_excluded_production_opcode_entry_points_are_absent():
    w = World()
    for method in ("show_message", "show_battle_message", "ghost_pos", "force_faint",
                   "force_move", "force_move_slot", "apply_trade"):
        assert w.native[method] is None


def test_config_is_queued_and_npc_counter_is_latched_on_reset():
    w = World()
    w.native.config(w.native, w.lua.table(overworld_presence=False, pc_trade_npc=True,
                                         battle_calc=False))
    assert w.output == []
    w.service()
    assert w.read(w.n["TN_ENABLE"], 1) == 1
    assert w.read(w.n["CALC_OFF"], 1) == 1
    w.put(w.n["PI_COUNT"], 1)
    w.service()
    assert [e for e, _ in w.events] == ["trade_request"]
    w.put(w.n["PI_COUNT"], 0)
    w.service()
    assert len(w.events) == 1


def test_link_panel_publishes_rows_before_line_count_and_does_not_dispatch_text():
    w = World()
    w.native.link_panel(w.native, w.lua.table(rows=w.lua.table("A|B", "NEXT")))
    assert w.output == []
    w.service()
    assert w.read(w.n["INFO"] + 3, 1) == 2
    assert w.raw(w.n["INFO"] + 8, 4) == bytes([0xBB, 0xFE, 0xBC, 0xFF])
    row_write = next(i for i, pair in enumerate(w.output) if pair[0] == w.n["INFO"] + 8)
    publish = next(i for i, pair in enumerate(w.output) if pair[0] == w.n["INFO"] + 3)
    assert row_write < publish
    assert w.read(w.n["BASE"] + 6, 2) == 0


def test_two_queued_panel_snapshots_each_advance_generation_at_dispatch():
    w = World()
    for text in ("FIRST", "SECOND"):
        w.native.link_panel(w.native, w.lua.table(rows=w.lua.table(text)))
    w.service()
    assert w.read(w.n["INFO"] + 6, 1) == 1
    w.service()
    assert w.read(w.n["INFO"] + 6, 1) == 2


def test_panel_advance_uses_info_opcode_and_close_resets_first_page_once():
    w = World()
    w.native.link_panel(w.native, w.lua.table(rows=w.lua.table(*["ROW"] * 7)))
    w.service()
    w.put(w.n["INFO"] + 1, 1)
    w.put(w.n["INFO"] + 2, 1)
    w.panel_result = 0
    w.service()
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_SHOW_INFO"]
    assert w.read(w.n["INFO"] + 4, 1) == 1
    w.put(w.n["INFO"] + 1, 2)
    w.put(w.n["INFO"] + 2, 2)
    w.ack(result=127)
    w.service()
    assert w.read(w.n["INFO"] + 4, 1) == 0
    before = len(w.output)
    w.service()
    assert len(w.output) == before


def test_rival_ack_requires_actual_enemy_party_readback():
    w = World()
    raw = bytearray(100)
    raw[0x20] = 1
    raw[0x58] = 20
    w.native.replace_rival_team(w.native, w.lua.table(
        trainer_id=5, blobs_hex=w.lua.table(raw.hex())))
    w.service()
    assert w.raw(w.n["BLOB_BUF"], 100) == raw
    w.ack()
    w.service()
    assert w.events[0][1].error == "enemy_readback_failed"


def test_rival_success_reports_readback_species_with_no_refresh_step():
    w = World()
    raw = bytearray(100)
    raw[0:4] = (0x0BADCAFE).to_bytes(4, "little")          # a PID gBattleMons[1] does not hold yet
    raw[0x20] = 25
    raw[0x58] = 20
    w.native.replace_rival_team(w.native, w.lua.table(
        trainer_id=5, blobs_hex=w.lua.table(raw.hex())))
    w.service()
    for i, byte in enumerate(raw):
        w.put(w.ram["ENEMY_BASE"] + i, byte)
    w.put(w.ram["ENEMY_COUNT_ADDR"], 1)
    w.ack()
    w.service()
    assert w.events == [], "no reply before the engine snapshot shows a staged mon"
    _snapshot(w, raw)
    w.service()
    assert w.events[0][0] == "rival_team_replaced"
    assert w.events[0][1].error is None
    assert w.events[0][1].species_ids[1] == 25


def test_trade_transport_owns_blob_staging_until_ack_and_does_not_expose_apply_trade():
    w = World()
    completions = []
    w.native.transfer(w.native, "enemy", w.lua.table(blobs_hex=w.lua.table("11" * 100)),
                      lambda why, result, _reason=None: completions.append((why, result)))
    w.native.transfer(w.native, "party", w.lua.table(slot=2, blob_hex="22" * 100), None)
    assert w.output == []
    w.service()
    assert w.raw(w.n["BLOB_BUF"], 100) == bytes([17]) * 100
    w.service()
    assert w.raw(w.n["BLOB_BUF"], 100) == bytes([17]) * 100
    w.ack()
    w.service()
    assert completions == [(None, 0)]
    assert w.raw(w.n["BLOB_BUF"], 100) == bytes([34]) * 100
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_SET_PARTY_MON"]
    assert w.native.apply_trade is None


def test_unsupported_and_malformed_transfers_cannot_write():
    w = World()
    for step, cmd in [("force_faint", w.lua.table(slot=0)),
                      ("party", w.lua.table(slot=7, blob_hex="00" * 100)),
                      ("enemy", w.lua.table(blobs_hex=w.lua.table("00" * 99)))]:
        result, _ = w.native.transfer(w.native, step, cmd, None)
        assert result is None
    w.service()
    assert w.output == []


def test_a_stale_ok_from_the_previous_op_never_completes_the_new_job():
    """C5-6a: dispatch no longer writes status=BUSY. The previous op's ST_OK stays in the status
    word with ack_seq one behind the new seq; completion needs ack == seq, so the new job stays
    pending until the patch acks it -- and no status byte is ever written by Lua."""
    w = World()
    w.native.play_sound(w.native, 25)
    w.service()
    w.ack(status=2)
    w.service()
    assert w.native.idle(w.native) is True                   # the first op completed
    first_seq = w.read(w.n["BASE"] + 8, 2)
    w.native.show_menu(w.native, w.lua.table(token="t", text="Yes?"))
    w.service()
    assert w.read(w.n["BASE"] + 10, 2) == 2                   # the stale ST_OK is still there
    assert w.read(w.n["BASE"] + 12, 2) == first_seq           # ack_seq = new seq - 1
    assert w.read(w.n["BASE"] + 8, 2) == first_seq + 1
    for _ in range(3):
        w.frame += 1
        w.service()
    assert w.events == [] and w.native.idle(w.native) is False
    assert all(addr not in (w.n["BASE"] + 10, w.n["BASE"] + 11) for addr, _ in w.output)
    w.ack(status=2, result=1)
    w.service()
    assert [(e, f.choice) for e, f in w.events] == [("menu_result", 1)]


@pytest.mark.parametrize("op,frames", [("OP_PLAY_SE", 1800), ("OP_SHOW_MENU", 2400),
                                       ("OP_CHOOSE_PARTY_MON", 2400), ("OP_TRADE_SCENE", 6000)])
def test_per_op_timeouts_outlast_the_patch_own_deadline(op, frames):
    """Each op's ACK deadline exceeds the patch's own (handlers.c drive_ui): a normal trade scene
    (~5580 frames) or a slow YES/NO answer (~1860) never poisons the mailbox."""
    w = World()
    # the harness native has timeout_frames=5: build a production-shaped one without the knob
    L = w.lua
    module = L.execute((ROOT / "lua/gen3/native.lua").read_text(encoding="utf-8"))
    native = module.new(L.table_from(w.profile, recursive=True), L.table(
        io=w.native_io, writes=w.writes, reads=w.reads, artifact_kind="companion",
        send=lambda e, f: w.events.append((e, f)), in_battle=lambda: True,
        panel_closed=lambda: (True, 127)))
    if op == "OP_PLAY_SE":
        native.play_sound(native, 25)
    elif op == "OP_SHOW_MENU":
        native.show_menu(native, L.table(token="t", text="?"))
    elif op == "OP_CHOOSE_PARTY_MON":
        native.choose_mon(native, L.table(token="t"))
    else:
        native.trade_capable = lambda *_: True  # scene timeout MODEL, not binding admission
        assert native.transfer(native, "scene", L.table(slot=0), lambda *_: None)
    native.service(native)
    assert w.read(w.n["BASE"] + 6, 2) == w.n[op]
    w.frame += frames - 1
    native.service(native)
    assert native.idle(native) is False and native.service(native) is True
    w.frame += 1
    assert native.service(native) == (None, "native timeout")


# ── G5-RR-RIVAL: a pre-announced swap is STAGED and posted in the W1 window ─────────────────

def _snapshot(w, raw):
    """BattleIntroDrawTrainersOrMonsSprites: gBattleMons[1] now holds the lead's personality."""
    w.put(w.ram["BATTLE_MONS_ADDR"] + 0x58 + 0x48, int.from_bytes(bytes(raw[:4]), "little"), 4)


def _window(w, open_=True):
    rr = w.profile["titles"]["radical_red"]
    w.put(rr["ram"]["BATTLE_MAIN_FUNC_ADDR"], rr["rom"]["BEGIN_BATTLE_INTRO_DUMMY_ADDR"] if open_ else 0, 4)
    w.put(rr["ram"]["BATTLE_COMM_ADDR"], 0)


def _staged_swap(w, holding):
    raw = bytearray(100)
    raw[0x20] = 25
    raw[0x58] = 20
    guard = lambda _epoch: (True, None)                             # noqa: E731
    hold = lambda _epoch: holding[0]                                # noqa: E731
    handle = w.native.replace_rival_team(w.native, w.lua.table(
        trainer_id=331, session="S", battle_id=1, blobs_hex=w.lua.table(raw.hex())), guard, hold)
    return handle, raw


def test_a_held_swap_is_staged_off_battle_and_posts_only_when_the_window_opens():
    w = World()
    w.battle = False                                              # still on the field
    holding = [True]
    handle, raw = _staged_swap(w, holding)
    assert w.events == [], "held: no not_in_battle refusal"
    for _ in range(5):
        w.frame += 1
        w.service()
    assert handle["posted"] is None and w.read(w.n["BASE"] + 6, 2) == 0, "nothing posted before W1"
    w.native.play_sound(w.native, 25)                             # a held swap blocks nobody
    w.service()
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_PLAY_SE"]
    w.ack()
    w.service()
    _window(w)                                                    # BeginBattleIntroDummy, comm0 0
    w.service()
    assert handle["posted"] is True and w.read(w.n["BASE"] + 6, 2) == w.n["OP_RIVAL_SWAP"]
    for i, byte in enumerate(raw):
        w.put(w.ram["ENEMY_BASE"] + i, byte)
    w.put(w.ram["ENEMY_COUNT_ADDR"], 1)
    w.ack()
    w.service()
    _snapshot(w, raw)
    w.service()
    (event, fields), = [e for e in w.events if e[0] == "rival_team_replaced"]
    assert fields.error is None and fields.species_ids[1] == 25


def test_the_window_is_the_dummy_phase_with_comm0_below_15():
    w = World()
    assert w.native.rival_window_open(w.native) is False
    _window(w)
    assert w.native.rival_window_open(w.native) is True
    w.put(w.ram["BATTLE_COMM_ADDR"], 15)                          # InitBattleControllers' case
    assert w.native.rival_window_open(w.native) is False


def test_a_hold_that_ends_without_the_window_dispatches_to_a_clean_refusal():
    """The late case: the hold ends (window missed / battle never began) off battle -> the
    dispatch guard refuses not_in_battle and nothing is posted."""
    w = World()
    w.battle = False
    holding = [True]
    handle, _raw = _staged_swap(w, holding)
    w.service()
    holding[0] = False
    w.service()
    assert handle["posted"] is None and w.output == []
    assert [e[1].error for e in w.events] == ["not_in_battle"]


def test_omp_f2_a_readback_whose_engine_snapshot_never_shows_a_staged_mon_is_stale():
    w = World()
    raw = bytearray(100)
    raw[0:4] = (0x1234ABCD).to_bytes(4, "little")
    raw[0x20] = 25
    raw[0x58] = 20
    w.native.replace_rival_team(w.native, w.lua.table(trainer_id=5, blobs_hex=w.lua.table(raw.hex())))
    w.service()
    for i, byte in enumerate(raw):
        w.put(w.ram["ENEMY_BASE"] + i, byte)
    w.put(w.ram["ENEMY_COUNT_ADDR"], 1)
    w.ack()
    w.service()
    w.frame += 600
    w.service()
    (event, fields), = w.events
    assert fields.error == "enemy_snapshot_stale"


def test_omp_f3_a_failed_read_while_the_hold_lasts_keeps_the_job_queued():
    w = World()
    w.battle = False
    holding, guard_ok = [True], [False]
    raw = bytearray(100)
    raw[0x20] = 25
    raw[0x58] = 20
    handle = w.native.replace_rival_team(w.native, w.lua.table(
        trainer_id=331, session="S", battle_id=1, blobs_hex=w.lua.table(raw.hex())),
        lambda _e: (True, None) if guard_ok[0] else (False, "stale_battle_id"),
        lambda _e: holding[0])
    _window(w)
    w.service()                                              # window open, first read not ready
    assert handle["posted"] is None and w.events == [], "not refused while the hold lasts"
    guard_ok[0] = True
    w.service()
    assert handle["posted"] is True


def test_omp_f4_a_link_battle_is_never_the_window():
    w = World()
    _window(w)
    rr = w.profile["titles"]["radical_red"]
    w.put(w.ram["BATTLE_TYPE_ADDR"], rr["derived"]["BATTLE_TYPE_LINK_MASK"], 4)
    assert w.native.rival_window_open(w.native) is False
