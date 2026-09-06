"""Self-tests of the actual running probe/production MB with a toy native producer.

These validate refusal/recording oracles, not real mGBA movement or graphics.
"""
import json
from pathlib import Path

import pytest

from tests.unit.test_rr_ghost_resource_probe import (
    GH,
    OBJECTS,
    REFS,
    ROOT,
    SPRITE,
    SPRITES,
    ProbeHarness,
)

SOURCE = ROOT / "lua/tests/rr/ghost_running_probe.lua"
ROUTE = json.loads((ROOT / "lua/tests/rr/viridian_west_running_route.json").read_text())


class RunningHarness(ProbeHarness):
    def __init__(self, tmp_path, fault=None):
        super().__init__(tmp_path)
        self.probe_fault, self.buttons, self.world_x, self.target = fault, {}, 33 * 16, 33
        self.moving = False
        self.config.identity = self.table({"rom_sha256": ROUTE["rom_sha256"], "fixture_sha256": ROUTE["fixture_sha256"]})
        self.config.frames = 500
        self.write(OBJECTS + 5, 0)
        self.write(OBJECTS + 9, 1)
        self.write(OBJECTS + 10, 3)
        self.write(OBJECTS + 11, 0x33)
        self.write(OBJECTS + 16, 33, 2)
        self.write(OBJECTS + 18, 34, 2)
        self.write(OBJECTS + 20, 33, 2)
        self.write(OBJECTS + 22, 34, 2)
        self.write(0x08EB1000, 0x08124000, 4)
        self.write(0x02036DFC, ROUTE["layout"], 4)
        self.write(ROUTE["layout"] + 16, 0x08131000, 4)
        self.write(0x08131000 + 20, ROUTE["primary_attributes"], 4)
        self.write(0x02036E00, ROUTE["map_events"], 4)
        self.write(ROUTE["map_events"] + 1, ROUTE["warp_count"])
        self.write(ROUTE["map_events"] + 2, ROUTE["coord_count"])
        self.write(ROUTE["map_events"] + 8, ROUTE["warp_pointer"], 4)
        self.write(ROUTE["map_events"] + 12, ROUTE["coord_pointer"], 4)
        for name in ("warp", "coord"):
            for index, byte in enumerate(bytes.fromhex(ROUTE[name + "_hex"])):
                self.write(ROUTE[name + "_pointer"] + index, byte)
        self.write(0x03005040, 63, 4)
        self.write(0x03005044, 54, 4)
        self.write(0x03005048, 0x02018000, 4)
        for index, word in enumerate(ROUTE["corridor_words"]):
            self.write(0x02018000 + (34 * 63 + 26 + index) * 2, word, 2)
        self.write(0x083A6493 + 3, 22)
        # One observed-style NPC, off the route, using the original palette.
        npc = OBJECTS + 36
        self.write(npc, 1)
        self.write(npc + 4, 1)
        self.write(npc + 8, 1)
        self.write(npc + 11, 0x33)
        for offset, value in [(16, 40), (18, 33), (20, 40), (22, 33)]:
            self.write(npc + offset, value, 2)
        self.write(SPRITES + 68 + 62, 1)
        self.write(SPRITES + 68 + 46, 1, 2)
        self.write(REFS + 1, 2)
        self.lua.globals().joypad = self.table({"set": self.input})

    def input(self, buttons):
        self.buttons = dict(buttons.items())

    def advance(self):
        super().advance()
        if not self.moving and self.buttons.get("Left"):
            self.target = self.read(OBJECTS + 16, 2) - 1
            self.moving = True
        if self.moving:
            speed = 1 if self.probe_fault == "walking_only" else 2
            self.world_x -= speed
            self.write(OBJECTS + 16, self.target, 2)
            self.write(OBJECTS + 24, 3)
            self.write(SPRITES + 42, 6 if speed == 1 else 22)
            if self.world_x == self.target * 16:
                self.moving = False
                self.write(OBJECTS, 0xC1)
                self.write(OBJECTS + 20, self.target, 2)
                self.write(SPRITES + 44, 0x48)
            else:
                self.write(OBJECTS, 0x41)
                self.write(OBJECTS + 20, self.target + 1, 2)
                self.write(SPRITES + 44, 8)
            if self.probe_fault == "context_loss":
                self.write(0x030030F4, 0x08001111, 4)
            if self.probe_fault == "foreign_palette":
                self.write(REFS + 1, 0)
            if self.probe_fault == "friendship_change":
                self.write(0x02024284 + 0x29, 71)
            if self.probe_fault == "party_identity_change":
                self.write(0x02024284, 123, 4)
        offset = 33 * 16 - self.world_x
        self.write(0x02021BC8, offset, 2)
        self.write(SPRITES + 32, 120 - offset, 2)
        if self.read(GH + 1) < 16:
            self.write(SPRITE + 32, self.read(GH + 6, 2) - 408, 2)
            self.write(SPRITE + 34, 80, 2)
            anim = self.read(GH + 15) if self.read(GH + 11) else max(0, self.read(GH + 10) - 1)
            self.write(SPRITE + 42, 0 if self.probe_fault == "ghost_never_runs" else anim)
            self.write(SPRITE + 62, 3)
            if self.probe_fault == "wrong_ghost_callback" and self.buttons.get("Left"):
                self.write(SPRITE + 28, 0x08001111, 4)
            if self.probe_fault == "lost_ghost_tiles" and self.buttons.get("Left"):
                self.tile(32, 0)

    def run(self):
        self.lua.execute(SOURCE.read_text(encoding="utf-8"))(self.context)


def test_running_component_selftest_requires_native_motion_and_contiguous_captures(tmp_path):
    h = RunningHarness(tmp_path)
    h.run()
    out = h.report.evidence.runtime
    assert h.posts == [14, 15] * 4
    assert out.endpoint.x == out.endpoint.previous_x == 27
    assert out.running_frames >= 40 and out.max_consecutive_running >= 6
    assert out.ghost_running_frames >= 6
    frames = list(out.recording.frames.values())
    assert len(frames) > 48
    assert [f.frame for f in frames] == list(range(frames[0].frame, frames[0].frame + len(frames)))
    assert all(Path(frame.path).is_file() for frame in frames)
    assert out.release_ready is False and out.natural_battle_tested is False and out.visual_review == "pending"
    assert out.resource_review == "pending"
    assert out.normal_control.release_ready is False and len(out.normal_control.screenshots) == 7
    assert len(h.assertions) == len(set(h.assertions))


@pytest.mark.parametrize("fault,reason", [("walking_only", "running_native_motion_observed"),
                                         ("ghost_never_runs", "running_ghost_animation_observed"),
                                         ("context_loss", "_field"), ("foreign_palette", "_actor_owner_0"),
                                         ("wrong_ghost_callback", "_ghost_owner"), ("lost_ghost_tiles", "_tile_32"),
                                         ("party_identity_change", "_party_identity_1")])
def test_running_oracle_rejects_false_success_and_retains_failure_trace(tmp_path, fault, reason):
    h = RunningHarness(tmp_path, fault)
    with pytest.raises(Exception, match=reason):
        h.run()
    out = h.report.evidence.runtime
    assert "running_component_complete" not in h.assertions
    assert out.release_ready is False and out.trace and out.recording.frames
    if fault == "context_loss":
        assert h.posts == [14, 15] * 3 + [14]
        assert out.failure_cleanup.attempted is False


@pytest.mark.parametrize("fault", ["grid", "event_bytes", "start", "rom"])
def test_unreviewed_route_refuses_running_controls_and_new_peer(tmp_path, fault):
    h = RunningHarness(tmp_path)
    if fault == "grid":
        h.write(0x02018000 + (34 * 63 + 32) * 2, 0x3400, 2)
    elif fault == "event_bytes":
        h.write(ROUTE["coord_pointer"], 26, 2)
    elif fault == "start":
        h.write(OBJECTS + 16, 32, 2)
        h.write(OBJECTS + 20, 32, 2)
        h.world_x, h.target = 32 * 16, 32
        h.write(0x02021BC8, 16, 2)
        h.write(SPRITES + 32, 104, 2)
    else:
        h.config.identity.rom_sha256 = "0" * 64
    with pytest.raises(Exception, match="running_"):
        h.run()
    assert len(h.posts) <= 6
    assert h.world_x == (32 if fault == "start" else 33) * 16


def test_new_actor_obstruction_stops_before_running_and_cleans_the_peer(tmp_path):
    h = RunningHarness(tmp_path)
    npc = OBJECTS + 36
    for offset, value in [(16, 32), (18, 34), (20, 32), (22, 34)]:
        h.write(npc + offset, value, 2)
    with pytest.raises(Exception, match="running_step_1_clear_actor_1"):
        h.run()
    assert h.world_x == 33 * 16
    assert h.posts == [14, 15] * 4
    assert h.report.evidence.runtime.failure_cleanup.completed is True


def test_running_capture_failure_is_retained_without_preventing_safe_cleanup(tmp_path):
    h = RunningHarness(tmp_path)
    capture = h.screenshot
    h.lua.globals().client.screenshot = lambda path: None if "_running_frame_" in path else capture(path)
    with pytest.raises(Exception, match="running_capture_exists_0"):
        h.run()
    out = h.report.evidence.runtime
    assert out.recording.pending_capture.index == 0
    assert out.failure_cleanup.completed is True
    assert h.posts == [14, 15] * 4


def test_field_step_party_changes_are_retained_for_review_without_claiming_party_correctness(tmp_path):
    h = RunningHarness(tmp_path, "friendship_change")
    h.run()
    out = h.report.evidence.runtime
    assert out.party_changed is True and out.party_review == "pending"
    assert out.trace[1].party_hex and out.party_after != out.normal_control.reference.party
    assert out.release_ready is False
