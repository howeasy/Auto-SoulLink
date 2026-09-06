"""Selected stock RR motion/camera routines on Unicorn, without routine stubs.

This is a synthetic CPU component, not a full CameraUpdate/game frame, PPU,
viewport-edge reachability, or physical gameplay result. Total camera scroll is
integrated by this harness; actual CameraObject and UpdateCameraPanning run below.
"""
import hashlib
import struct

import pytest

from tests.rr.native.test_ghost_placement_cpu import NativeCPU
from tests.rr.reference.test_withdrawal_oracle import ROM_SHA256
from tests.unit.test_rr_peer_position import SPRITE, SenderHarness

CAMERA = SPRITE + 8 * 68
STEPS = {0: [1] * 16, 1: [2] * 8, 2: [2, 3, 3, 2, 3, 3], 3: [4] * 4}
DIRECTIONS = {1: (0, 1), 2: (0, -1), 3: (-1, 0), 4: (1, 0)}


@pytest.fixture(scope="module")
def rom(rr_rom_path):
    data = rr_rom_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == ROM_SHA256
    return data


def signed(native, address):
    return struct.unpack("<h", native.read(address, 2))[0]


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize("speed", STEPS)
@pytest.mark.parametrize("camera", ["following", "fixed"])
def test_actual_rr_steps_and_camera_feed_production_sender(rom, direction, speed, camera):
    native = NativeCPU((rom, {"ghost_cb": 0x0837A970}))
    assert not native.stubs
    h = SenderHarness()
    initial = h.tick()
    dx, dy = DIRECTIONS[direction]
    native.w16(SPRITE + 32, 120)
    native.w16(SPRITE + 34, 80)
    native.w16(CAMERA + 46, 0)
    native.w16(CAMERA + 32, 120)
    native.w16(CAMERA + 34, 80)
    native.call(0x08068B40, [SPRITE, direction, speed])  # SetSpriteDataForNormalStep
    native.w32(0x03000EA0, 0)  # no panning callback in this synthetic fixture
    total_x, total_y, travelled = 0, 0, 0
    for index, distance in enumerate(STEPS[speed]):
        completed = native.call(0x08068B54, [SPRITE])  # NpcTakeStep, actual table+step helper
        travelled += distance
        assert signed(native, SPRITE + 32) == 120 + dx * travelled
        assert signed(native, SPRITE + 34) == 80 + dy * travelled
        assert completed == int(index == len(STEPS[speed]) - 1)
        native.call(0x0805F9F8 if camera == "following" else 0x0805FA30, [CAMERA])
        camera_dx, camera_dy = signed(native, CAMERA + 50), signed(native, CAMERA + 52)
        assert (camera_dx, camera_dy) == ((dx * distance, dy * distance) if camera == "following" else (0, 0))
        total_x -= camera_dx
        total_y -= camera_dy
        native.w16(0x0300506C, total_x)
        native.w16(0x03005068, total_y)
        native.w16(0x03000E98, index)  # independent pan, not player ground displacement
        native.w16(0x03000E9A, 32 + index)
        native.call(0x0805AE28)  # actual UpdateCameraPanning -> gSpriteCoordOffsetX/Y
        assert signed(native, 0x02021BC8) == total_x - index
        assert signed(native, 0x02021BCA) == total_y - 40 - index
        h.pose(x=33 + dx, y=34 + dy,
               previous_x=33 + dx if completed else 33,
               previous_y=34 + dy if completed else 34,
               px=signed(native, SPRITE + 32), py=signed(native, SPRITE + 34),
               coffx=signed(native, 0x02021BC8), coffy=signed(native, 0x02021BCA), idle=bool(completed))
        event = h.tick()
        assert (event["x"], event["y"]) == (initial["x"] + dx * travelled, initial["y"] + dy * travelled)
    assert travelled == 16 and not native.stubs


def test_actual_connection_tile_rebase_does_not_rebase_sprite_and_is_rejected(rom):
    native = NativeCPU((rom, {"ghost_cb": 0x0837A970}))
    h = SenderHarness()
    h.tick()
    native.w8(0x02036E38, 1)
    for offset, value in [(16, 32), (18, 34), (20, 33), (22, 34)]:
        native.w16(0x02036E38 + offset, value)
    native.w16(SPRITE + 32, 118)
    native.w16(SPRITE + 34, 80)
    native.w8(0x02036E18, 1)  # exact routine's connection-coordinate rebase flag
    native.w16(0x02036E18 + 4, 12)
    native.w16(0x02036E18 + 8, 0)
    native.call(0x0805F82C)
    assert signed(native, 0x02036E38 + 16) == 20
    assert signed(native, 0x02036E38 + 20) == 21
    assert signed(native, SPRITE + 32) == 118
    h.pose(x=20, previous_x=21, px=118, idle=False)
    h.tick()
    assert len(h.events) == 1 and not native.stubs
