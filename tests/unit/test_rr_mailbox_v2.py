"""Exercise the production Lua mailbox; no emulator, server or source mutations."""
import struct
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class MailboxHarness:
    def __init__(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.ram = {}
        memory = self.lua.table()
        for width in (1, 2, 4):
            suffix = "u8" if width == 1 else f"u{width * 8}_le"
            memory["read_" + suffix] = lambda address, *args, width=width: self.read(address, width)
            memory["write_" + suffix] = lambda address, value, *args, width=width: self.write(address, value, width)
        memory.read_s16_le = lambda address, *args: self.read(address, 2) - (65536 if self.read(address, 2) >= 32768 else 0)
        memory.read_s8 = lambda address, *args: self.read(address) - (256 if self.read(address) >= 128 else 0)
        memory.write_s16_le = lambda address, value, *args: self.write(address, value, 2)
        self.lua.globals().memory = memory
        self.lua.execute('package.loaded.memory_gba={CHARSET_REV={A=1,B=2,C=3}}')
        self.mb = self.lua.execute((ROOT / "lua/mailbox.lua").read_text(encoding="utf-8"))
        self.lua.globals().MB = self.mb
        self.write(self.mb.BASE, self.mb.SIG, 4)
        self.write(self.mb.BASE + 4, 2, 2)

    def read(self, address, width=1):
        return sum(self.ram.get(address + i, 0) << (i * 8) for i in range(width))

    def write(self, address, value, width=1):
        for i in range(width):
            self.ram[address + i] = (int(value) >> (i * 8)) & 255

    def table(self, value):
        return self.lua.table_from(value)

    def complete(self, result=0, status=2, reason=0):
        base = self.mb.BASE
        self.write(base + 48, result)
        self.write(base + 14, reason, 2)
        self.write(base + 12, self.read(base + 8, 2), 2)
        self.write(base + 6, 0, 2)
        for i in range(8):
            self.write(base + 48 + 8 + i, self.read(base + 16 + 24 + i))
        self.write(base + 10, status, 2)


@pytest.fixture
def h():
    return MailboxHarness()


def test_receipt_survives_pump_and_later_ack(h):
    first = h.mb.send(1)
    second = h.mb.send(19, h.table([25, 0]))
    h.complete(result=7)
    h.mb.pump()
    assert h.read(h.mb.BASE + 6, 2) == 19
    h.complete(result=9)
    assert h.mb.poll(first) == (2, 0)
    assert h.mb.read_result_u8(0) == 7
    assert h.mb.poll(second) == (2, 0)
    assert h.mb.read_result_u8(0) == 9


def test_async_opcode_zero_does_not_free_owner(h):
    h.mb.send(17)
    h.write(h.mb.BASE + 6, 0, 2)  # engine accepted async operation, still BUSY
    h.mb.send(19, h.table([25, 0]))
    h.mb.pump()
    assert h.read(h.mb.BASE + 6, 2) == 0
    assert h.read(h.mb.BASE + 8, 2) == 1


def test_arguments_are_immutable_while_queued(h):
    h.mb.send(1)
    args = h.table([25, 0])
    h.mb.send(19, args)
    args[1] = 99
    h.complete()
    h.mb.pump()
    assert h.read(h.mb.BASE + 16) == 25


def test_blob_staging_does_not_touch_live_memory_and_is_per_command(h):
    h.mb.send(1)
    first = h.table([11] * 100)
    h.mb.set_party_mon(0, first, False)
    h.mb.set_party_mon(1, h.table([22] * 100), False)
    first[1] = 33
    assert h.read(h.mb.BLOB_BUF) == 0
    h.complete()
    h.mb.pump()
    assert bytes(h.read(h.mb.BLOB_BUF + i) for i in range(100)) == bytes([11] * 100)
    h.complete()
    h.mb.pump()
    assert bytes(h.read(h.mb.BLOB_BUF + i) for i in range(100)) == bytes([22] * 100)


@pytest.mark.parametrize("lease_address", [0x0203FC80, 0x03000F9C, 0x0203FD00])
def test_text_lease_outlives_receipt(h, lease_address):
    h.mb.write_message("A")
    first = h.mb.send(8)
    h.write(lease_address, 1)
    h.mb.write_message("B")
    h.mb.send(8)
    assert h.read(h.mb.TEXT_BUF) == 1
    h.complete(result=1)
    h.mb.pump()
    assert h.mb.poll(first) == (2, 0)
    assert h.read(h.mb.BASE + 6, 2) == 0
    assert h.read(h.mb.TEXT_BUF) == 1
    h.write(lease_address, 0)
    h.mb.pump()
    assert h.read(h.mb.TEXT_BUF) == 2


def test_menu_payloads_snapshot_and_wait_for_ui_lease(h):
    h.mb.send(1)
    h.mb.show_choices(h.table(["A", "B"]))
    h.mb.show_choices(h.table(["C"]))
    assert h.read(h.mb.MENU_BUF) == 0
    h.complete()
    h.write(0x0203FC80, 1)
    h.mb.pump()
    assert h.read(h.mb.BASE + 6, 2) == 0
    h.write(0x0203FC80, 0)
    h.mb.pump()
    assert [h.read(h.mb.MENU_BUF + i) for i in range(5)] == [2, 1, 255, 2, 255]


def test_native_session_loss_never_reposts_pending_mutation(h):
    h.mb.send(24, h.table([0, 1, 0]))
    h.mb.send(19, h.table([25, 0]))
    h.write(h.mb.BASE + 8, 0, 2)
    h.write(h.mb.BASE + 6, 0, 2)
    h.write(h.mb.BASE + 10, 0, 2)
    h.mb.pump()
    assert h.mb.session_error() == "native_session_changed"
    assert h.read(h.mb.BASE + 6, 2) == 0


def test_lua_reload_cannot_overwrite_unowned_native_operation(h):
    h.write(h.mb.BASE + 10, 1, 2)
    result = h.mb.send(1)
    assert result == (None, "unowned_native_operation")
    assert h.read(h.mb.BASE + 10, 2) == 1


def test_reconcile_reset_refuses_active_ui_or_operation(h):
    h.mb.send(17)
    assert h.mb.reset_after_reconcile()[0] is False
    h.complete()
    h.mb.pump()
    h.write(0x0203FC80, 1)
    assert h.mb.reset_after_reconcile()[0] is False
    h.write(0x0203FC80, 0)
    assert h.mb.reset_after_reconcile() is True


def test_fire_and_forget_sounds_do_not_exhaust_receipt_storage(h):
    for _ in range(300):
        assert isinstance(h.mb.play_se(25), int)
        h.complete()
        h.mb.pump()
    assert h.mb.session_error() is None


def test_native_wire_wrap_does_not_reuse_lua_token(h):
    h.lua.execute('''for i=1,30 do local name,fn=debug.getupvalue(MB.send,i)
      if name == "prepare" then for j=1,30 do local n=debug.getupvalue(fn,j)
        if n == "next_token" then debug.setupvalue(fn,j,65535); break end end; break end end''')
    first = h.mb.send(1)
    assert first == 65536
    assert h.read(h.mb.BASE + 8, 2) == 0
    h.complete()
    assert h.mb.poll(first) == (2, 0)
    assert h.mb.send(1) == 65537


def test_storage_requires_guard_and_packs_identity_without_truncation(h):
    assert h.mb.deposit_mon(0, 1, 2)[0] is None
    guard = h.table({"pid": 0xFEDCBA98, "otid": 0x76543210, "count": 3})
    assert h.mb.deposit_mon(0, 1, 2, guard) == 1
    args = bytes(h.read(h.mb.BASE + 16 + i) for i in range(13))
    assert args == bytes([0, 1, 2, 0xA2]) + struct.pack("<II", 0xFEDCBA98, 0x76543210) + b"\x03"


def test_box_transfer_argument_contract(h):
    guard = h.table({"pid": 7, "otid": 9, "count": 2})
    assert h.mb.move_box_mon(24, 29, 23, 28, guard) == 1
    assert h.read(h.mb.BASE + 6, 2) == 28
    assert [h.read(h.mb.BASE + 16 + i) for i in (0, 1, 2, 3, 12, 13)] == [24, 29, 23, 0xA2, 2, 28]


@pytest.mark.parametrize("count", [-1, 7, 1.5])
def test_invalid_storage_count_is_not_sent(h, count):
    result = h.mb.withdraw_mon(0, 0, 0, h.table({"pid": 1, "otid": 2, "count": count}))
    assert result[0] is None
    assert h.read(h.mb.BASE + 6, 2) == 0


def test_invalid_locations_and_payloads_never_publish(h):
    guard = h.table({"pid": 1, "otid": 2, "count": 2})
    assert h.mb.move_box_mon(25, 0, 1, 0, guard)[0] is None
    assert h.mb.deposit_mon(None, 0, 0, guard)[0] is None
    assert h.mb.set_party_mon(0, h.table([0] * 101), False) is None
    assert h.read(h.mb.BASE + 6, 2) == 0


def test_descriptor_is_read_from_rom_and_validated(h):
    token = h.mb.send(1)
    address = 0x08378000
    descriptor = struct.pack("<IHHIIIHH", 0x32444C53, 1, 2, 156, 15, h.mb.BASE, 64, 0xA2)
    descriptor += b"a" * 64 + b"\0" + b"b" * 64 + b"\0\0\0"
    assert len(descriptor) == 156
    for i, value in enumerate(descriptor):
        h.write(address + i, value)
    h.complete()
    h.write(h.mb.BASE + 48, address, 4)
    decoded = h.mb.read_descriptor(token)
    assert decoded.abi == 2
    assert decoded.build_id == "a" * 64
    assert decoded.layout_sha256 == "b" * 64
    assert decoded.capabilities.storage_guard_v2 is True


def test_descriptor_pointer_outside_rom_fails(h):
    token = h.mb.send(1)
    h.complete()
    h.write(h.mb.BASE + 48, 0x02000000, 4)
    assert h.mb.read_descriptor(token) == (None, "invalid descriptor pointer")


def test_durable_preparation_does_not_write_even_to_retire_existing_ack(h):
    h.mb.send(1)
    h.complete()
    before = dict(h.ram)
    h.mb.set_context_generation("save-epoch-7")
    prepared = h.mb.prepare(19, h.table([25, 0]), "0123456789abcdef")
    assert prepared.native_id == "0123456789abcdef"
    assert dict(h.ram) == before
    assert h.mb.submit(prepared) == prepared.token
    assert [h.read(h.mb.BASE + 16 + 24 + i) for i in range(8)] == list(bytes.fromhex(prepared.native_id))


def test_submit_rejects_modified_persisted_preparation(h):
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(19, h.table([25, 0]), "1111111111111111")
    prepared.args[1] = 99
    assert h.mb.submit(prepared) == (None, "unknown_or_changed_preparation")
    assert h.read(h.mb.BASE + 6, 2) == 0


def test_same_native_id_cannot_be_rebound_to_another_preparation(h):
    h.mb.set_context_generation("epoch-1")
    h.mb.prepare(19, h.table([25, 0]), "1111111111111111")
    assert h.mb.prepare(19, h.table([26, 0]), "1111111111111111") == (None, "native_reservation_conflict")


def test_context_generation_change_blocks_submit(h):
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(19, h.table([25, 0]), "1111111111111111")
    h.mb.set_context_generation("epoch-2")
    assert h.mb.submit(prepared) == (None, "native_context_changed")
    assert h.read(h.mb.BASE + 6, 2) == 0


def test_structural_rr_context_change_blocks_submit(h):
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(19, h.table([25, 0]), "1111111111111111")
    h.write(0x030030F4, 0x080565B5, 4)
    assert h.mb.submit(prepared) == (None, "native_context_changed")


def test_queued_preparation_rechecks_context_before_posting(h):
    h.mb.send(1)
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(19, h.table([25, 0]), "1111111111111111")
    assert h.mb.submit(prepared) == prepared.token
    h.mb.set_context_generation("epoch-2")
    h.complete()
    h.mb.pump()
    assert h.mb.session_error() == "native_context_changed"
    assert h.read(h.mb.BASE + 6, 2) == 0


def test_old_same_wire_receipt_with_other_reservation_is_not_accepted(h):
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(19, h.table([25, 0]), "1111111111111111")
    h.mb.submit(prepared)
    h.complete()
    h.write(h.mb.BASE + 48 + 8, 0x22)
    assert h.mb.poll(prepared.token) == (None, "native_reservation_receipt_mismatch")
    assert h.read(h.mb.BASE + 10, 2) == 2  # mismatched receipt was not retired


def test_restored_async_arguments_with_same_wire_are_not_replayed(h):
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(17, h.table([]), "1111111111111111")
    h.mb.submit(prepared)
    h.write(h.mb.BASE + 6, 0, 2)  # native UI running
    h.mb.send(19, h.table([25, 0]))  # queued work must not survive by silently reposting
    h.write(h.mb.BASE + 16 + 24, 0x22)  # a different saved preparation restored
    h.mb.pump()
    assert h.mb.session_error() == "native_reservation_changed"
    assert h.read(h.mb.BASE + 6, 2) == 0


def test_guarded_storage_can_be_prepared_without_posting(h):
    h.mb.set_context_generation("epoch-1")
    guard = h.table({"pid": 7, "otid": 9, "count": 2, "native_id": "1111111111111111"})
    before = dict(h.ram)
    prepared = h.mb.prepare_move_box_mon(24, 29, 23, 28, guard)
    assert dict(h.ram) == before
    assert prepared.args[14] == 28
    assert h.mb.submit(prepared) == prepared.token
    assert h.read(h.mb.BASE + 16 + 23) == 0xC2


@pytest.mark.parametrize("completed", [False, True])
def test_changed_generation_refuses_matching_inflight_receipt_retirement(h, completed):
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(19, h.table([25, 0]), "1111111111111111")
    h.mb.submit(prepared)
    if completed:
        h.complete()
    h.mb.set_context_generation("epoch-2")
    before = dict(h.ram)
    assert h.mb.poll(prepared.token) == (None, "native_context_generation_changed")
    assert h.ram == before
    assert h.read(h.mb.BASE + 10, 2) == (2 if completed else 1)


def test_saved_receipt_is_generation_qualified_and_detached(h):
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(19, h.table([25, 0]), "1111111111111111")
    h.mb.submit(prepared)
    h.complete(result=7)
    h.mb.pump()
    saved = h.mb.get_saved_receipt(prepared.token)
    assert saved.context_generation == "epoch-1"
    saved.context_generation = "epoch-2"
    assert h.mb.get_saved_receipt(prepared.token).context_generation == "epoch-1"
    h.mb.set_context_generation("epoch-2")
    assert h.mb.poll(prepared.token) == (None, "native_context_generation_changed")
    assert h.mb.get_saved_receipt(prepared.token).result[1] == 7


def test_expected_scene_callback_change_does_not_invalidate_generation(h):
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(21, h.table([0]), "1111111111111111")
    h.mb.submit(prepared)
    h.write(0x030030F4, 0x08000001, 4)
    h.complete()
    assert h.mb.poll(prepared.token) == (2, 0)


def test_ghost_spawn_preserves_full_graphics_id(h):
    assert isinstance(h.mb.ghost_spawn(0x0203), int)
    assert [h.read(h.mb.BASE + 16 + i) for i in range(3)] == [3, 0xF0, 2]
    assert h.mb.ghost_spawn(65536) == (None, "invalid gfx16")


@pytest.mark.parametrize("abi", [None, 1])
@pytest.mark.parametrize("method,args", [
    ("events_init", []), ("set_pc_npc", [True]), ("set_battle_calc", [False]),
    ("set_info_enable", [True]), ("write_info", [["A"], 0, 1]),
    ("ghost_set_pos", [160, 160, 4, True, 6, False]), ("ghost_snap", []),
    ("ghost_set_avatar", [0x08123400, 0x08234500, "1234" * 16]),
])
def test_public_ewram_writers_refuse_absent_or_stale_abi_without_shadow_reads(h, abi, method, args):
    h.write(h.mb.BASE, h.mb.SIG if abi else 0, 4)
    h.write(h.mb.BASE + 4, abi or 0, 2)
    reads = []
    memory = h.lua.globals().memory
    for width, name in ((1, "read_u8"), (2, "read_u16_le"), (4, "read_u32_le")):
        def read(address, *unused, width=width):
            reads.append((address, width))
            return h.read(address, width)
        memory[name] = read
    before = dict(h.ram)
    supplied = [h.table(value) if isinstance(value, list) else value for value in args]
    assert h.mb[method](*supplied) is False
    assert h.ram == before
    assert reads and all(pair in ((h.mb.BASE, 4), (h.mb.BASE + 4, 2)) for pair in reads)


@pytest.mark.parametrize("abi", [None, 1])
def test_event_drain_and_pump_do_not_touch_absent_or_stale_native_shadow(h, abi):
    h.write(h.mb.BASE, h.mb.SIG if abi else 0, 4)
    h.write(h.mb.BASE + 4, abi or 0, 2)
    reads = []
    memory = h.lua.globals().memory
    for width, name in ((1, "read_u8"), (2, "read_u16_le"), (4, "read_u32_le")):
        def read(address, *unused, width=width):
            reads.append((address, width))
            return h.read(address, width)
        memory[name] = read
    before = dict(h.ram)
    events, overflow = h.mb.events_drain()
    assert len(events) == 0 and overflow is False
    assert h.mb.pump() is False
    assert h.ram == before
    assert all(pair in ((h.mb.BASE, 4), (h.mb.BASE + 4, 2)) for pair in reads)


def test_prepared_command_cannot_submit_after_beacon_disappears(h):
    h.mb.set_context_generation("epoch-1")
    prepared = h.mb.prepare(19, h.table([25, 0]), "1111111111111111")
    h.write(h.mb.BASE, 0, 4)
    before = dict(h.ram)
    assert h.mb.submit(prepared) == (None, "native_session_changed")
    assert h.ram == before


def test_present_event_init_retains_legacy_drop_semantics(h):
    h.write(h.mb.EVR, 7)
    h.write(h.mb.EVR + 1, 2)
    h.write(h.mb.EVR + 2, 1)
    assert h.mb.events_init() is True
    assert h.read(h.mb.EVR + 1) == 7
    assert h.read(h.mb.EVR + 2) == 0


def test_unreadable_beacon_refuses_writer_without_probing_shadow(h):
    def unreadable(*args):
        raise RuntimeError("no supported memory domain")
    h.lua.globals().memory.read_u32_le = unreadable
    before = dict(h.ram)
    assert h.mb.set_pc_npc(True) is False
    assert h.ram == before


@pytest.fixture
def receiver():
    h = MailboxHarness()
    h.lua.globals().console = h.table({"log": lambda *args: None})
    h.lua.execute("package.loaded.mailbox = MB")
    h.write(0x030030F4, 0x080565B5, 4)
    h.write(0x02036E38, 0x81)
    h.write(h.mb.GH_OEID, 1)
    h.write(0x02036E38 + 0x24, 1)
    h.write(0x02036E38 + 0x24 + 8, 0xF0)
    h.write(0x02036E38 + 0x24 + 4, 2)
    pg = h.lua.execute((ROOT / "lua/peer_ghost_npc.lua").read_text())
    pg.init()
    return h, pg


def packet(h, **changes):
    data = {"mg": 0, "mn": 0, "x": 160, "y": 160, "f": 4, "mv": 0, "an": 3,
            "run": 0, "gfx": 0x0203, "imgs": 0x08123400, "anim": 0x08234500, "pcol": "1234" * 16}
    data.update(changes)
    return h.table(data)


def test_receiver_only_stages_and_never_rewrites_sprite_or_live_palette(receiver):
    h, pg = receiver
    watched = list(range(0x0202063C, 0x02021780)) + list(range(0x020373F8, 0x020377F8 + 512)) + list(range(0x05000200, 0x05000400))
    before = [h.read(address) for address in watched]
    pg.on_ghost_pos(packet(h))
    pg.on_frame()
    assert [h.read(address) for address in watched] == before
    assert h.read(h.mb.GH_IMGS, 4) == 0x08123400
    assert [h.read(h.mb.BASE + 16 + i) for i in range(3)] == [3, 0xF0, 2]


def test_palette_and_animation_only_changes_are_forwarded(receiver):
    h, pg = receiver
    pg.on_ghost_pos(packet(h))
    pg.on_frame()
    pg.on_ghost_pos(packet(h, anim=0x08234600, pcol="5678" * 16))
    pg.on_frame()
    assert h.read(h.mb.GH_ANIMS, 4) == 0x08234600
    assert h.read(h.mb.GHOST_PAL_BUF, 2) == 0x5678


def test_failed_spawn_request_is_not_latched_as_spawned(receiver):
    h, pg = receiver
    h.write(h.mb.BASE + 10, 1, 2)  # unknown native owner, requiring reconciliation
    pg.on_ghost_pos(packet(h))
    pg.on_frame()
    assert pg.debug().spawned is False


def test_receiver_does_not_stage_avatar_in_nonfield_context(receiver):
    h, pg = receiver
    h.write(0x030030F4, 0x08000001, 4)
    before = dict(h.ram)
    pg.on_ghost_pos(packet(h))
    pg.on_frame()
    assert h.ram == before


def test_presence_disable_clears_cached_ghost_and_rejects_stale_positions(receiver):
    h, pg = receiver
    pg.on_ghost_pos(packet(h))
    pg.on_frame()
    pg.set_enabled(False)
    assert pg.debug().spawned is False
    assert pg.on_ghost_pos(packet(h)) is False
    pg.set_enabled(True)
    assert pg.on_ghost_pos(packet(h)) is True


def test_invalid_ghost_graphics_or_palette_is_not_coerced_to_player_default(receiver):
    h, pg = receiver
    assert pg.on_ghost_pos(packet(h, gfx=65536)) is False
    assert pg.on_ghost_pos(packet(h, pcol="not-a-palette")) is False
    assert pg.on_ghost_pos(packet(h, imgs=0x02000000)) is False
    assert pg.debug().spawned is False


@pytest.mark.parametrize("field", [True, False])
def test_actual_sender_fragment_carries_gfx16_and_is_field_gated(field):
    h = MailboxHarness()
    h.write(0x030030F4, 0x080565B5 if field else 0x08000001, 4)
    h.write(0x02036E38, 0x81)
    h.write(0x02036E38 + 5, 3)
    h.write(0x02036E38 + 0x23, 2)
    h.write(0x0202063C + 62, 3)  # owned, coordinate-offset sprite
    captured = []
    h.lua.globals().IS_RR = True
    h.lua.globals().is_overworld = True
    h.lua.globals().frame_count = 3
    h.lua.globals().pg_send_logged = True
    h.lua.globals().pg_position = h.lua.execute((ROOT / "lua/rr/peer_position.lua").read_text()).new(h.lua.globals().memory)
    h.lua.globals().patch_present = lambda: True
    h.lua.globals().send = lambda event, *args: captured.append(event)
    source = (ROOT / "lua/clients/gen3_frlge_client.lua").read_text(encoding="utf-8")
    start = source.index("    if IS_RR and is_overworld and patch_present() then", source.index("-- Peer ghost (RR"))
    end = source.index("        if PG then", start)
    h.lua.execute(source[start:end] + "\nend")
    assert len(captured) == int(field)
    if field:
        assert captured[0].gfx == 0x0203
