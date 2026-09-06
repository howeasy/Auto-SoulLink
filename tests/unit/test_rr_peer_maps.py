"""Production sender/receiver map tagging with controlled RAM, not duo gameplay."""
import json

import pytest

from tests.unit.test_rr_mailbox_v2 import packet, receiver  # noqa: F401
from tests.unit.test_rr_peer_position import OE, ROOT, SPRITE, SenderHarness

SB1 = 0x0202572C


def current_map(h, group, number, layout=0x082DE3E4):
    h.write(0x03005008, SB1, 4)
    h.write(SB1 + 4, group)
    h.write(SB1 + 5, number)
    h.write(0x02036DFC, layout, 4)


def test_sender_uses_current_map_when_object_spawn_map_stays_viridian():
    h = SenderHarness()
    current_map(h, 3, 1)
    assert h.tick()["mn"] == 1
    current_map(h, 3, 19, 0x082E55CC)
    h.pose(x=17, y=7, px=56, py=320)
    assert (h.read(OE + 10), h.read(OE + 9)) == (3, 1)
    event = h.tick()
    assert (event["mg"], event["mn"], event["x"], event["y"]) == (3, 19, 272, 112)


@pytest.mark.parametrize("peer_map,should_spawn", [(19, True), (1, False)])
def test_receiver_matches_current_map_not_retained_spawn_map(receiver, peer_map, should_spawn):  # noqa: F811
    h, pg = receiver
    current_map(h, 3, 19, 0x082E55CC)
    h.write(OE + 10, 3)
    h.write(OE + 9, 1)
    pg.on_ghost_pos(packet(h, mg=3, mn=peer_map))
    pg.on_frame()
    assert pg.debug().spawned is should_spawn


@pytest.mark.parametrize("pointer", [0, 0x01FFFFFC, 0x02000001, 0x0203FFFC, 0x03000000])
def test_invalid_current_map_pointer_suppresses_sender_without_zero_map_fallback(pointer):
    h = SenderHarness()
    h.write(0x03005008, pointer, 4)
    assert h.tick() is None


def test_same_layout_map_change_invalidates_midstep_anchor():
    h = SenderHarness()
    current_map(h, 3, 1)
    h.tick()
    current_map(h, 3, 19)  # a distinct map may reuse its layout
    h.pose(x=32, previous_x=33, px=118, idle=False)
    h.tick()
    assert len(h.events) == 1


def test_spawn_map_field_changes_do_not_retag_or_discard_current_map_motion():
    h = SenderHarness()
    current_map(h, 3, 19)
    h.tick()
    h.write(OE + 9, 7)
    h.pose(x=32, previous_x=33, px=118, idle=False)
    assert (h.tick()["mn"], h.events[-1]["x"]) == (19, 526)


def test_receiver_unknown_map_does_not_write_any_native_or_avatar_state(receiver):  # noqa: F811
    h, pg = receiver
    h.write(0x03005008, 0, 4)
    pg.on_ghost_pos(packet(h))
    before = dict(h.ram)
    pg.on_frame()
    assert h.ram == before and pg.debug().spawned is False


def test_local_map_transition_waits_for_clear_receipt_and_actual_removal(receiver):  # noqa: F811
    h, pg = receiver
    current_map(h, 3, 1)
    pg.on_ghost_pos(packet(h, mg=3, mn=1))
    pg.on_frame()
    h.complete()
    h.mb.pump()
    old_target = h.read(h.mb.GH_WX, 2)
    current_map(h, 3, 19, 0x082E55CC)
    pg.on_ghost_pos(packet(h, mg=3, mn=19, x=272))
    pg.on_frame()
    assert h.read(h.mb.OPCODE_ADDR, 2) == h.mb.OP_GHOST_CLEAR
    assert h.read(h.mb.GH_WX, 2) == old_target
    for _ in range(3):
        pg.on_frame()
    assert h.read(h.mb.GH_WX, 2) == old_target
    h.complete()  # accepted desired-state clear, ghost still exists until next field callback
    pg.on_frame()
    assert h.read(h.mb.GH_WX, 2) == old_target
    assert pg.debug().spawned is True
    h.write(h.mb.GH_OEID, 0xFF)  # synthetic producer's separately observed field cleanup
    pg.on_frame()
    assert pg.debug().spawned is False
    pg.on_frame()
    assert h.read(h.mb.OPCODE_ADDR, 2) == h.mb.OP_GHOST_SPAWN
    assert h.read(h.mb.GH_WX, 2) == 272


def test_failed_map_clear_never_stages_a_new_map_target(receiver):  # noqa: F811
    h, pg = receiver
    current_map(h, 3, 1)
    pg.on_ghost_pos(packet(h, mg=3, mn=1))
    pg.on_frame()
    h.complete()
    h.mb.pump()
    current_map(h, 3, 19, 0x082E55CC)
    pg.on_ghost_pos(packet(h, mg=3, mn=19, x=272))
    pg.on_frame()
    h.complete(status=h.mb.ST_FAIL)
    before = h.read(h.mb.GH_WX, 2)
    for _ in range(3):
        pg.on_frame()
    assert h.read(h.mb.GH_WX, 2) == before
    assert h.read(h.mb.OPCODE_ADDR, 2) == 0


def test_recorded_route40_current_map_differs_from_object_spawn_map():
    data = json.loads((ROOT / "tests/rr/fixtures/route40_map_connection.json").read_text())
    assert data["result_sha256"] == "4addaa88d7e3a72d0302ef23b8f3342cd6f19d773acd68887173331c281f5f4c"
    h = SenderHarness()
    reader = h.lua.execute((ROOT / "lua/rr/peer_position.lua").read_text()).current_map
    for sample in data["snapshots"]:
        h.write(0x03005008, sample["saveblock1"], 4)
        h.write(sample["saveblock1"] + 4, sample["map_group"])
        h.write(sample["saveblock1"] + 5, sample["map_num"])
        h.write(OE + 10, sample["object_spawn_map_group"])
        h.write(OE + 9, sample["object_spawn_map_num"])
        h.write(0x02036DFC, sample["layout"], 4)
        observed = reader(h.lua.globals().memory)
        assert (observed.mg, observed.mn, observed.layout, observed.saveblock1) == (
            sample["map_group"], sample["map_num"], sample["layout"], sample["saveblock1"])
        position = sample["position"]
        if position is None:
            # This trace did not record raw pos1 while its old sampler rejected
            # the midstep. Replay the recorded map facts only, not invented pixels.
            continue
        h.pose(x=sample["x"], y=sample["y"], previous_x=sample["previous_x"], previous_y=sample["previous_y"],
               px=position["px"], py=position["py"], idle=position["idle"])
        h.write(SPRITE + 12, position["imgs"], 4)
        h.write(SPRITE + 8, position["anims"], 4)
        event = h.tick()
        assert (event["mg"], event["mn"]) == (sample["map_group"], sample["map_num"])
        assert (event["x"], event["y"]) == (position["wx"], position["wy"])
    assert (h.events[-1]["mn"], h.read(OE + 9)) == (19, 1)


def test_clear_receipt_survives_unrelated_native_completion(receiver):  # noqa: F811
    h, pg = receiver
    current_map(h, 3, 1)
    pg.on_ghost_pos(packet(h, mg=3, mn=1))
    pg.on_frame()
    h.complete()
    h.mb.pump()
    current_map(h, 3, 19)
    pg.on_ghost_pos(packet(h, mg=3, mn=19))
    pg.on_frame()
    h.complete()
    h.mb.pump()
    h.mb.send(h.mb.OP_PING)
    h.complete()
    h.mb.pump()
    h.write(h.mb.GH_OEID, 0xFF)
    pg.on_frame()
    assert pg.debug().spawned is False
    pg.on_frame()
    assert h.read(h.mb.OPCODE_ADDR, 2) == h.mb.OP_GHOST_SPAWN


def test_map_transition_drops_pending_old_map_interaction(receiver):  # noqa: F811
    h, pg = receiver
    current_map(h, 3, 1)
    pg.on_ghost_pos(packet(h, mg=3, mn=1))
    pg.on_frame()
    h.complete()
    h.mb.pump()
    h.write(h.mb.PI_COUNT, 1)
    pg.on_frame()
    current_map(h, 3, 19)
    pg.on_frame()
    assert pg.consume_interact() is False


@pytest.mark.parametrize("phase", ["posted", "acknowledged"])
@pytest.mark.parametrize("cancel", ["nil_packet", "other_map", "explicit_clear", "disable"])
def test_pending_map_cleanup_survives_cancel_init_and_disable(receiver, phase, cancel):  # noqa: F811
    h, pg = receiver
    current_map(h, 3, 1)
    pg.on_ghost_pos(packet(h, mg=3, mn=1))
    pg.on_frame()
    h.complete()
    h.mb.pump()
    current_map(h, 3, 19)
    pg.on_ghost_pos(packet(h, mg=3, mn=19, x=272))
    pg.on_frame()
    if phase == "acknowledged":
        h.complete()
        h.mb.pump()
    if cancel == "nil_packet":
        assert pg.on_ghost_pos(None) is False  # invalid input is not an explicit clear
    elif cancel == "other_map":
        pg.on_ghost_pos(packet(h, mg=3, mn=1))
    elif cancel == "explicit_clear":
        pg.on_ghost_clear()
    else:
        pg.set_enabled(False)
    pg.init()  # repeated initialization must not abandon a live mailbox obligation
    assert pg.debug().map_clearing is True
    if cancel == "disable":
        assert pg.on_ghost_pos(packet(h, mg=3, mn=19)) is False
    pg.on_frame()
    assert h.read(h.mb.GH_WX, 2) == 160
    if phase == "posted":
        h.complete()
        h.mb.pump()
    assert h.read(h.mb.OPCODE_ADDR, 2) == 0  # cancellation did not enqueue an extra untracked clear
    h.write(h.mb.GH_OEID, 0xFF)
    h.write(h.mb.PI_COUNT, 7)
    pg.on_frame()  # receipt retirement is serviced even while presence is disabled
    assert pg.debug().map_clearing is False
    assert pg.consume_interact() is False
    h.mb.send(h.mb.OP_PING)
    h.complete()
    h.mb.pump()
    assert h.mb.get_saved_receipt(2) is None  # retained clear receipt was consumed, not lost in init
    if cancel == "disable":
        pg.set_enabled(True)
        pg.on_ghost_pos(packet(h, mg=3, mn=19))
    pg.on_frame()
    expected_spawn = cancel in ("nil_packet", "disable")
    assert pg.debug().spawned is expected_spawn
    assert pg.consume_interact() is False


@pytest.mark.parametrize("cancel", ["explicit_clear", "disable", "other_map"])
def test_cancel_cannot_leave_a_pending_old_peer_interaction(receiver, cancel):  # noqa: F811
    h, pg = receiver
    current_map(h, 3, 1)
    pg.on_ghost_pos(packet(h, mg=3, mn=1))
    pg.on_frame()
    h.complete()
    h.mb.pump()
    h.write(h.mb.PI_COUNT, 1)
    pg.on_frame()
    if cancel == "explicit_clear":
        pg.on_ghost_clear()
    elif cancel == "disable":
        pg.set_enabled(False)
    else:
        pg.on_ghost_pos(packet(h, mg=3, mn=19))
        pg.on_frame()
    assert pg.consume_interact() is False
