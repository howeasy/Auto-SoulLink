"""MODEL controls for the injected RR mailbox owner; no emulator or ROM required."""
import json
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]


class World:
    def __init__(self, present=True, initial_seq=0, kind="companion"):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.profile = json.loads((ROOT / "data/games/gen3_rr/profile.json").read_text())
        self.n = self.profile["native"]
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
            in_battle=lambda: self.battle, refresh_enemy=lambda *_: True,
            panel_closed=lambda: (True, self.panel_result)))

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


def test_rival_success_reports_readback_species_after_refresh():
    w = World()
    raw = bytearray(100)
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
    assert w.events[0][0] == "rival_team_replaced"
    assert w.events[0][1].error is None
    assert w.events[0][1].species_ids[1] == 25


def test_trade_transport_owns_blob_staging_until_ack_and_does_not_expose_apply_trade():
    w = World()
    completions = []
    w.native.transfer(w.native, "enemy", w.lua.table(blobs_hex=w.lua.table("11" * 100)),
                      lambda why, result: completions.append((why, result)))
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
        refresh_enemy=lambda *_: True, panel_closed=lambda: (True, 127)))
    if op == "OP_PLAY_SE":
        native.play_sound(native, 25)
    elif op == "OP_SHOW_MENU":
        native.show_menu(native, L.table(token="t", text="?"))
    elif op == "OP_CHOOSE_PARTY_MON":
        native.choose_mon(native, L.table(token="t"))
    else:
        assert native.transfer(native, "scene", L.table(slot=0), lambda *_: None)
    native.service(native)
    assert w.read(w.n["BASE"] + 6, 2) == w.n[op]
    w.frame += frames - 1
    native.service(native)
    assert native.idle(native) is False and native.service(native) is True
    w.frame += 1
    assert native.service(native) == (None, "native timeout")
