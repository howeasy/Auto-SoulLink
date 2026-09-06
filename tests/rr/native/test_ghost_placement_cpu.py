"""Execute the built Thumb code against synthetic RAM; no game/PPU/frame emulation.

These tests prove placement writes and guards, not live engine collision, resource
ownership across scenes, or physical gameplay. The explicit live lane remains required.
"""
import os
import struct
import subprocess
from pathlib import Path

import pytest
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_SP,
)

from tests.rr.native.test_native_build import native_output  # noqa: F401

EWRAM, IWRAM, ROM, RETURN = 0x02000000, 0x03000000, 0x08000000, 0x01000000
OBJECTS, SPRITES, GH, INTERACT = 0x02036E38, 0x0202063C, 0x0203F850, 0x0203F8D0
OE_ID, SID = 2, 5
OE, SPRITE = OBJECTS + OE_ID * 0x24, SPRITES + SID * 0x44


@pytest.fixture(scope="module")
def image(native_output):  # noqa: F811
    toolchain = os.environ.get("SLINK_ARMGCC")
    if not toolchain:
        pytest.fail("set SLINK_ARMGCC to the pinned native toolchain", pytrace=False)
    suffix = ".exe" if os.name == "nt" else ""
    result = subprocess.run([str(Path(toolchain) / ("arm-none-eabi-nm" + suffix)), "-n",
                             str(native_output / "handlers.elf")], capture_output=True, text=True, check=True)
    symbols = {parts[2]: int(parts[0], 16) for line in result.stdout.splitlines()
               if len(parts := line.split()) == 3}
    return (native_output / "slink_RR.gba").read_bytes(), symbols


class NativeCPU:
    def __init__(self, image):
        rom, self.symbols = image
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for address, size in [(ROM, 0x02000000), (EWRAM, 0x40000), (IWRAM, 0x8000), (RETURN, 0x1000)]:
            self.cpu.mem_map(address, size)
        self.cpu.mem_write(ROM, rom)
        self.w32(IWRAM + 0x30F4, 0x080565B5)
        self.w8(OE, 1)
        self.w8(OE + 4, SID)
        self.w8(OE + 8, 0xF0)
        self.w16(SPRITE + 0x2E, OE_ID)
        self.w32(SPRITE + 0x1C, self.symbols["ghost_cb"] | 1)
        self.w16(SPRITE + 0x3A, 512)
        self.w16(SPRITE + 0x3C, 0x534C)
        self.w8(SPRITE + 0x3E, 0x47)  # inUse, coordOffset, invisible, unrelated flag
        for offset, value in [(0x10, 40), (0x12, 41), (0x14, 99), (0x16, 98)]:
            self.w16(OE + offset, value)
        self.stubs = {}
        self.cpu.hook_add(UC_HOOK_CODE, self._stub)

    def _stub(self, cpu, address, size, user):
        if address in self.stubs:
            self.stubs[address](self)
            cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    def w8(self, address, value):
        self.cpu.mem_write(address, bytes([value]))

    def w16(self, address, value):
        self.cpu.mem_write(address, struct.pack("<H", value & 0xFFFF))

    def w32(self, address, value):
        self.cpu.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def read(self, address, size):
        return bytes(self.cpu.mem_read(address, size))

    def call(self, name, args=()):
        stack = IWRAM + 0x7E00
        self.cpu.reg_write(UC_ARM_REG_SP, stack)
        self.cpu.reg_write(UC_ARM_REG_LR, RETURN | 1)
        for index, value in enumerate(args):
            if index < 4:
                self.cpu.reg_write([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3][index], value & 0xFFFFFFFF)
            else:
                self.w32(stack + (index - 4) * 4, value)
        address = self.symbols[name] if isinstance(name, str) else name
        self.cpu.emu_start(address | 1, RETURN, timeout=2_000_000, count=100_000)
        assert self.cpu.reg_read(UC_ARM_REG_PC) == RETURN, "native call failed to return"
        return self.cpu.reg_read(UC_ARM_REG_R0)

    def place(self, x, y, elevation, visible):
        return self.call("rr_place_ghost", [OE_ID, 0xF0, self.symbols["ghost_cb"], x, y, elevation, visible])


@pytest.mark.parametrize("x,y,elevation,visible", [(12, 13, 0, 1), (-32768, 32767, 15, 0), (0, 0, 2, 1)])
def test_compiled_placement_changes_only_owned_coordinates_elevation_and_visibility(image, x, y, elevation, visible):
    native = NativeCPU(image)
    expected = bytearray(native.read(EWRAM, 0x40000))
    struct.pack_into("<hhhh", expected, OE + 0x10 - EWRAM, x, y, x, y)
    expected[OE + 0x0B - EWRAM] = elevation | elevation << 4
    expected[SPRITE + 0x3E - EWRAM] = 0x43 if visible else 0x47
    assert native.place(x, y, elevation, visible) == 1
    assert native.read(EWRAM, 0x40000) == expected


@pytest.mark.parametrize("fault", ["nonfield", "inactive_object", "wrong_local_id", "bad_sprite_id",
                                    "inactive_sprite", "wrong_object_binding", "wrong_callback", "wrong_marker",
                                    "zero_allocation", "misaligned_allocation", "oversized_allocation",
                                    "bad_elevation", "bad_visibility"])
def test_compiled_placement_refuses_stale_or_invalid_owner_without_any_ewram_write(image, fault):
    native = NativeCPU(image)
    changes = {
        "nonfield": (native.w32, IWRAM + 0x30F4, 0x08001235),
        "inactive_object": (native.w8, OE, 0), "wrong_local_id": (native.w8, OE + 8, 7),
        "bad_sprite_id": (native.w8, OE + 4, 64), "inactive_sprite": (native.w8, SPRITE + 0x3E, 6),
        "wrong_object_binding": (native.w16, SPRITE + 0x2E, 3),
        "wrong_callback": (native.w32, SPRITE + 0x1C, 0x08001111),
        "wrong_marker": (native.w16, SPRITE + 0x3C, 0), "zero_allocation": (native.w16, SPRITE + 0x3A, 0),
        "misaligned_allocation": (native.w16, SPRITE + 0x3A, 513),
        "oversized_allocation": (native.w16, SPRITE + 0x3A, 2080),
    }
    if fault in changes:
        write, address, value = changes[fault]
        write(address, value)
    before = native.read(EWRAM, 0x40000)
    assert native.place(12, 13, 16 if fault == "bad_elevation" else 0, 2 if fault == "bad_visibility" else 1) == 0
    assert native.read(EWRAM, 0x40000) == before


def driver(image):
    native = NativeCPU(image)
    native.w32(0x03005008, 0x0202552C)  # canonical save pointer; modeled map0:0
    native.w8(OBJECTS, 0x81)  # actual player OE0, idle, tile10,11
    native.w8(OBJECTS + 4, 0)
    native.w16(OBJECTS + 0x10, 10)
    native.w16(OBJECTS + 0x12, 11)
    native.w16(SPRITES + 0x20, 160)
    native.w16(SPRITES + 0x22, 176)
    for offset, value in [(0, 1), (1, OE_ID), (4, 0xF0), (10, 1), (14, 1), (41, 2), (42, SID), (43, 1)]:
        native.w8(GH + offset, value)
    native.w16(GH + 6, 32)
    native.w16(GH + 8, 48)
    native.w16(SPRITE + 4, 2 << 12)
    native.w8(0x0203B7D4 + 2 * 4, 6)
    native.w8(0x0203B7D4 + 2 * 4 + 1, 1)
    native.w8(INTERACT + 1, 1)
    native.w8(INTERACT + 2, OE_ID)
    return native


@pytest.mark.parametrize("state", ["visible", "offscreen", "no_camera_baseline", "invalid_avatar", "spawn"])
def test_compiled_driver_all_placement_paths_retire_previous_tile_and_hidden_interaction(image, state):
    native = driver(image)
    if state == "offscreen":
        native.w16(GH + 6, 1000)
    elif state == "no_camera_baseline":
        native.w8(OBJECTS, 1)  # calibration must wait while the actual player moves
    elif state == "invalid_avatar":
        # Isolate the driver's response to rejected avatar evidence; avatar validation
        # itself belongs to the resource/binary lane, not this placement assertion.
        native.stubs[native.symbols["apply_avatar"]] = lambda n: n.cpu.reg_write(UC_ARM_REG_R0, 0)
    elif state == "spawn":
        native.w8(GH + 1, 0xFF)
        native.w8(OE, 0)

        def spawn(n):
            assert n.cpu.reg_read(UC_ARM_REG_R3) == 10
            stack = n.cpu.reg_read(UC_ARM_REG_SP)
            assert struct.unpack("<I", n.read(stack, 4))[0] == 11  # no invisible adjacent tile
            n.w8(OE, 1)
            n.cpu.reg_write(UC_ARM_REG_R0, OE_ID)

        native.stubs[native.symbols["rr_spawn_presence"]] = spawn
    native.call("drive_ghost")
    expected = (2, 3, 2, 3) if state == "visible" else (10, 11, 10, 11)
    assert struct.unpack("<hhhh", native.read(OE + 0x10, 8)) == expected
    assert bool(native.read(SPRITE + 0x3E, 1)[0] & 4) is (state != "visible")
    assert native.read(INTERACT + 1, 1) == bytes([state == "visible"])


def test_pinned_rr_collision_really_reads_previous_coordinates_and_accepts_zero_elevation(rr_rom_path):
    rom = rr_rom_path.read_bytes()
    for address, expected in {
        0x0806393C: "1421505e984213d11621505e",  # unconditional previousX and previousY comparison
        0x0806835C: "00b50006000e0906090e002803d0002901d0884201d1012000e0002002bc",
    }.items():
        raw = bytes.fromhex(expected)
        assert rom[address - ROM:address - ROM + len(raw)] == raw


def test_actual_rr_object_collision_stops_reporting_old_tile_after_compiled_placement(image):
    native = NativeCPU(image)
    native.w8(OBJECTS, 1)
    native.w16(OBJECTS + 0x10, 10)
    native.w16(OBJECTS + 0x12, 11)
    native.w8(OE + 0x0B, 0xFF)
    # Only the RR follower exemption is stubbed: this case has no follower.
    # Run the actual pinned object loop and elevation comparator unchanged.
    native.stubs[0x090965BC] = lambda n: n.cpu.reg_write(UC_ARM_REG_R0, 0)
    def collision(x, y):
        return native.call(0x08063904, [OBJECTS, x, y])

    assert collision(99, 98) == 1  # stale previous tile, despite ghost elevation15/player0
    native.w8(OBJECTS + 0x0B, 0x22)
    assert collision(99, 98) == 0  # mismatch works only when neither elevation is zero
    native.w8(OBJECTS + 0x0B, 0)
    assert native.place(12, 13, 0, 1) == 1
    assert collision(99, 98) == 0
    assert collision(12, 13) == 1
    assert native.place(10, 11, 0, 0) == 1
    assert collision(12, 13) == 0
    assert collision(10, 12) == 0  # hidden ghost leaves the adjacent target clear
