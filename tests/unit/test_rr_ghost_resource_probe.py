"""Exercise the probe's assertions with production MB and a toy native producer.

The positive simulation is a probe self-test, never physical release evidence.
"""
import struct
import zlib
from pathlib import Path

import pytest

from tests.unit.test_rr_mailbox_v2 import MailboxHarness

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "lua/tests/rr/ghost_resource_probe.lua"
OBJECTS, SPRITES, GH, REFS, TILES = 0x02036E38, 0x0202063C, 0x0203F850, 0x0203B7D4, 0x02021B48
OE, SPRITE = OBJECTS + 2 * 36, SPRITES + 5 * 68
CALLBACK, IMAGES, ANIMS = 0x0837A970, 0x08123400, 0x08123500


def png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 240, 160, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes((240 * 3 + 1) * 160))) + chunk(b"IEND", b""))


class ProbeHarness(MailboxHarness):
    def __init__(self, tmp_path, fault=None):
        super().__init__()
        self.frame, self.posts, self.avatar_accepts, self.fault = 0, [], 0, fault
        self.assertions = []
        self.write(0x030030F4, 0x080565B5, 4)
        self.write(GH + 1, 255)
        self.write(OBJECTS, 0x81)
        self.write(OBJECTS + 5, 1)
        self.write(OBJECTS + 0x10, 20, 2)
        self.write(OBJECTS + 0x12, 21, 2)
        self.write(OBJECTS + 0x14, 20, 2)
        self.write(OBJECTS + 0x16, 21, 2)
        self.write(OBJECTS + 0x18, 1)
        self.write(0x02037078, 1)
        self.write(0x02024029, 1)
        self.write(SPRITES + 0x3E, 1)
        self.write(SPRITES + 32, 120, 2)
        self.write(SPRITES + 34, 80, 2)
        self.write(SPRITES + 12, IMAGES, 4)
        self.write(SPRITES + 8, ANIMS, 4)
        self.write(IMAGES + 4, 512, 2)
        self.write(0x08EB1000 + 4, 0x08124000, 4)  # direct gfx1 ROM record
        self.write(0x08124000 + 6, 512, 2)
        self.write(0x08124000 + 28, IMAGES, 4)
        self.write(0x08124000 + 24, ANIMS, 4)
        self.write(REFS, 1)
        self.write(REFS + 1, 1)
        self.write(REFS + 2, 0x1234, 2)
        for index in range(32):
            self.write(0x020373F8 + index, index)
        for bit in range(16):
            self.tile(bit, 1)
        descriptor = b"SLD2" + bytes(85) + self.mb.LAYOUT.sha256.encode() + bytes(3)
        for index, value in enumerate(descriptor):
            self.write(0x0837BF04 + index, value)
        self.lua.globals().emu = self.table({"framecount": lambda: self.frame, "frameadvance": self.advance})
        self.lua.globals().joypad = self.table({"set": lambda value: None})
        self.lua.globals().client = self.table({"screenshot": self.screenshot})
        self.report = self.table({"evidence": self.table({})})
        self.config = self.table({
            "source_root": ROOT.as_posix(), "result_path": (tmp_path / "result.json").as_posix(),
            "purpose": "validation", "fixture_kind": "state", "frames": 240,
            "descriptor": self.table({"address": 0x0837BF04, "size": 156, "hex": descriptor.hex(), "build_id": "a" * 64}),
            "probe_options": self.table({"cycles": 3, "phase_frames": 4, "quiet_frames": 2, "visible_frames": 2,
                                          "native_contract": self.table({"build_id": "a" * 64, "ghost_callback": CALLBACK})}),
        })
        self.context = self.table({"config": self.config, "report": self.report, "check": self.check})

    def check(self, name, actual, expected):
        self.assertions.append(name)
        assert actual == expected, name

    def tile(self, bit, value):
        address = TILES + bit // 8
        self.write(address, (self.read(address) & ~(1 << (bit % 8))) | value << (bit % 8))

    def allocate(self):
        self.write(GH, 1)
        self.write(GH + 1, 2)
        self.write(OE, 1)
        self.write(OE + 4, 5)
        self.write(OE + 8, 0xF0)
        self.write(SPRITE + 4, (1 << 12) | 32, 2)
        self.write(SPRITE + 46, 2, 2)
        self.write(SPRITE + 58, 512, 2)
        self.write(SPRITE + 60, 0x534C, 2)
        self.write(SPRITE + 62, 5)
        self.write(SPRITE + 28, CALLBACK | 1, 4)
        self.write(SPRITE + 12, IMAGES, 4)
        self.write(SPRITE + 8, ANIMS, 4)
        self.write(REFS + 4, 6)
        self.write(REFS + 5, 1)
        self.write(REFS + 6, 0x1234, 2)
        for bit in range(32, 48):
            self.tile(bit, 1)
        if self.fault == "wrong_callback":
            self.write(SPRITE + 28, 0x08001111, 4)
        if self.fault == "wrong_allocation":
            self.write(SPRITE + 58, 1024, 2)

    def advance(self):
        self.frame += 1
        opcode = self.read(self.mb.BASE + 6, 2)
        if opcode:
            self.posts.append(opcode)
            assert opcode in (14, 15), "probe must use only production ghost opcodes"
            if opcode == 14 and self.fault != "spawn_timeout":
                self.allocate()
            elif opcode == 15:
                self.write(GH, 0)
                self.write(GH + 1, 255)
                self.write(OE, 0)
                self.write(SPRITE + 62, 0)
                if self.fault != "palette_leak":
                    self.write(REFS + 4, 0, 4)
                if self.fault != "tile_leak":
                    for bit in range(32, 48):
                        self.tile(bit, 0)
            self.complete(status=3 if self.fault == "native_fail" else 2)
        if self.read(GH + 17) and self.read(GH + 1) < 16:
            self.avatar_accepts += 1
            if self.fault != "avatar_timeout":
                self.write(GH + 17, 0)
                self.write(SPRITE + 62, 1)
                self.write(SPRITE + 32, 152, 2)
                self.write(SPRITE + 34, 80, 2)
            for index in range(32):
                self.write(0x020373F8 + 32 + index, self.read(self.mb.GHOST_PAL_BUF + index))
            if self.fault == "foreign_ref":
                self.write(REFS + 1, 2)
            if self.fault == "foreign_tile":
                self.tile(123, 1)
            if self.fault == "wrong_private_tag":
                self.write(REFS + 6, 0x7777, 2)
            if self.fault == "foreign_sprite":
                self.write(SPRITES + 12, 0x08123444, 4)
            if self.fault == "context_loss":
                self.write(0x030030F4, 0x08001111, 4)
        elif self.fault == "lost_visibility" and self.read(GH + 1) < 16:
            self.write(SPRITE + 62, 5)

    def screenshot(self, path):
        if self.fault == "missing_screenshot":
            return
        if self.fault == "visible_screenshot_failure" and "visible" in path:
            raise RuntimeError("capture failed")
        Path(path).write_bytes(b"not a PNG" if self.fault == "bad_screenshot" else png())

    def run(self):
        self.lua.execute(SOURCE.read_text(encoding="utf-8"))(self.context)


def test_complete_probe_selftest_requires_resources_and_screenshots_without_release_claim(tmp_path):
    harness = ProbeHarness(tmp_path)
    harness.run()
    evidence = harness.report.evidence.runtime
    assert harness.posts == [14, 15] * 3 and harness.avatar_accepts == 3
    assert len(evidence.cycles) == 3 and len(evidence.screenshots) == 7
    assert len(set(harness.assertions)) == len(harness.assertions)
    assert evidence.release_ready is False and evidence.visual_review == "pending"
    assert evidence.classification == "synthetic_single_cartridge_component"
    assert evidence.arena_ownership == "unresolved"
    assert "resource_normal_lifetime_complete" in harness.assertions
    for item in evidence.screenshots.values():
        assert Path(item.path).read_bytes().startswith(b"\x89PNG")


def test_current_probe_refuses_a_legacy_or_different_selected_layout_before_native_requests(tmp_path):
    harness = ProbeHarness(tmp_path)
    descriptor = bytes.fromhex(harness.config.descriptor.hex)
    descriptor = descriptor[:89] + b"0" * 64 + descriptor[153:]
    harness.config.descriptor.hex = descriptor.hex()
    before = dict(harness.ram)
    with pytest.raises(AssertionError, match="resource_layout_matches_selected_descriptor"):
        harness.run()
    assert harness.posts == [] and harness.ram == before


@pytest.mark.parametrize("fault,assertion", [
    ("wrong_callback", "callback_owner"), ("wrong_allocation", "native_allocation"),
    ("foreign_ref", "preserved_ref_0"), ("foreign_tile", "foreign_tile_123"),
    ("wrong_private_tag", "private_reference"), ("foreign_sprite", "_avatar"),
    ("palette_leak", "restored_ref_1"), ("tile_leak", "all_tiles_restored"),
    ("missing_screenshot", "screenshot_exists_before"), ("bad_screenshot", "screenshot_png_before"),
    ("visible_screenshot_failure", "screenshot_call_cycle_1_visible"),
    ("spawn_timeout", "owned_spawn_completed"), ("avatar_timeout", "avatar_acceptance_completed"),
    ("context_loss", "_field"), ("native_fail", "native failure"), ("lost_visibility", "still_owned"),
])
def test_probe_refuses_false_component_pass_and_preserves_failure(tmp_path, fault, assertion):
    harness = ProbeHarness(tmp_path, fault)
    with pytest.raises(Exception, match=assertion):
        harness.run()
    assert "resource_normal_lifetime_complete" not in harness.assertions
    assert harness.report.evidence.runtime.release_ready is False
    if fault in ("missing_screenshot", "bad_screenshot"):
        assert harness.posts == []
    if fault == "visible_screenshot_failure":
        assert harness.posts == [14, 15]
        assert harness.report.evidence.runtime.failure_cleanup.completed is True
    if fault == "context_loss":
        assert harness.posts == [14]  # no cleanup opcode posted into unknown scene ownership
        assert harness.report.evidence.runtime.failure_cleanup.attempted is False


@pytest.mark.parametrize("address,value,width", [(0x030030F4, 0x08001111, 4), (0x03000F9C, 1, 1),
                                                (0x0203F840, 1, 1), (0x0203F800 + 4, 1, 2),
                                                (0x0203F800 + 10, 2, 2), (GH, 1, 1), (REFS + 4, 6, 1),
                                                (OBJECTS + 8, 0xF0, 1)])
def test_probe_admission_failure_posts_no_native_operation(tmp_path, address, value, width):
    harness = ProbeHarness(tmp_path)
    harness.write(address, value, width)
    before = dict(harness.ram)
    with pytest.raises(AssertionError, match="resource_"):
        harness.run()
    assert harness.posts == [] and harness.ram == before


def test_probe_refuses_stale_screenshot_instead_of_reusing_it(tmp_path):
    harness = ProbeHarness(tmp_path)
    image = tmp_path / "result_ghost_before.png"
    image.write_bytes(png())
    before = image.read_bytes()
    with pytest.raises(Exception, match="screenshot_fresh_before"):
        harness.run()
    assert harness.posts == [] and image.read_bytes() == before


def test_rejected_idle_reference_retains_raw_diagnostics_and_unqualified_capture(tmp_path):
    harness = ProbeHarness(tmp_path)
    harness.write(SPRITES + 42, 4)
    harness.write(SPRITES + 44, 0x08)
    with pytest.raises(AssertionError, match="reference_on_foot_idle"):
        harness.run()
    evidence = harness.report.evidence.runtime
    assert evidence.reference.raw_avatar_flags == 1 and evidence.reference.anim_num == 4
    assert evidence.reference.anim_delay_pause == 0x08
    assert evidence.reference.player_address == OBJECTS and evidence.reference.sprite_address == SPRITES
    assert evidence.reference_precondition_screenshot.qualified is False
    assert evidence.reference_precondition_screenshot.capture_ok is True
    assert evidence.reference_precondition_screenshot.png_signature is True
    assert harness.posts == [] and len(evidence.screenshots) == 0


def test_actual_rr_stopped_walk_animation_qualifies_without_forcing_a_face_animation(tmp_path):
    harness = ProbeHarness(tmp_path)
    harness.write(0x02037078, 0x21)
    harness.write(SPRITES + 42, 4)
    harness.write(SPRITES + 44, 0x48)
    harness.write(SPRITES + 63, 8)
    harness.run()
    assert harness.report.evidence.runtime.reference.stopped_animation == "paused_locomotion"
    assert harness.posts == [14, 15] * 3


@pytest.mark.parametrize("anim,delay,previous_x", [(4, 8, 20), (5, 0x48, 20), (20, 0x48, 20), (4, 0x48, 19)])
def test_unpaused_wrong_facing_special_or_moving_reference_does_not_qualify(tmp_path, anim, delay, previous_x):
    harness = ProbeHarness(tmp_path)
    harness.write(SPRITES + 42, anim)
    harness.write(SPRITES + 44, delay)
    harness.write(OBJECTS + 20, previous_x, 2)
    with pytest.raises(AssertionError, match="resource_field_prerequisite|reference_on_foot_idle"):
        harness.run()
    assert harness.posts == []


def test_rr_allocation_uses_graphics_reservation_not_smaller_first_frame_transfer(tmp_path):
    harness = ProbeHarness(tmp_path)
    harness.write(IMAGES + 4, 256, 2)
    harness.run()
    reference = harness.report.evidence.runtime.reference
    assert reference.first_frame_bytes == 256 and reference.allocation == 512
    for cycle in harness.report.evidence.runtime.cycles.values():
        assert cycle.spawn_state.allocation == 512
        assert cycle.spawn_state.images == IMAGES
        assert cycle.owner.tile_count == 16


@pytest.mark.parametrize("fault", ["wrong_table_association", "oversized_frame", "dynamic_alias"])
def test_unproved_graphics_allocation_refuses_probe_before_native_requests(tmp_path, fault):
    harness = ProbeHarness(tmp_path)
    if fault == "wrong_table_association":
        harness.write(0x08124000 + 28, IMAGES + 4, 4)
    elif fault == "oversized_frame":
        harness.write(IMAGES + 4, 1024, 2)
    else:
        harness.write(OBJECTS + 35, 255)
    with pytest.raises(AssertionError, match="reference_graphics_association|reference_frame_fits_allocation|reference_direct_graphics"):
        harness.run()
    assert harness.posts == []
