"""Actual sender fragment with synthetic RAM, not physical camera/gameplay proof."""
import json
from pathlib import Path

import pytest

from tests.unit.test_rr_mailbox_v2 import MailboxHarness

ROOT = Path(__file__).resolve().parents[2]
OE, SPRITE = 0x02036E38, 0x0202063C


class SenderHarness(MailboxHarness):
    def __init__(self):
        super().__init__()
        source = (ROOT / "lua/clients/gen3_frlge_client.lua").read_text(encoding="utf-8")
        start = source.index("    if IS_RR and is_overworld and patch_present() then", source.index("-- Peer ghost (RR"))
        end = source.index("        if PG then", start)
        self.sender = self.lua.execute("return function()\n" + source[start:end] + "\nend\nend")
        self.events = []
        env = self.lua.globals()
        env.IS_RR, env.is_overworld, env.pg_send_logged = True, True, True
        env.patch_present = lambda: True
        env.send = lambda event, *args: self.events.append(dict(event))
        env.frame_count = 6
        helper = ROOT / "lua/rr/peer_position.lua"
        if helper.exists():
            env.pg_position = self.lua.execute(helper.read_text()).new(env.memory)
        self.write(0x030030F4, 0x080565B5, 4)
        self.write(OE, 0x81)
        self.write(OE + 9, 1)
        self.write(OE + 10, 3)
        self.write(OE + 24, 3)
        self.write(SPRITE + 62, 3)  # inUse + coordOffsetEnabled
        self.write(SPRITE + 12, 0x08EB3810, 4)
        self.write(SPRITE + 8, 0x083A0188, 4)
        self.pose()

    def pose(self, *, x=33, previous_x=None, y=34, previous_y=None,
             px=120, py=80, coffx=0, coffy=-40, idle=True):
        self.write(OE, 0x81 if idle else 0x41)
        for address, value in [(OE + 16, x), (OE + 18, y),
                               (OE + 20, x if previous_x is None else previous_x),
                               (OE + 22, y if previous_y is None else previous_y),
                               (SPRITE + 32, px), (SPRITE + 34, py),
                               (0x02021BC8, coffx), (0x02021BCA, coffy)]:
            self.write(address, value, 2)
        self.write(SPRITE + 42, 6 if idle else 22)

    def tick(self):
        self.sender()
        self.lua.globals().frame_count += 6
        return self.events[-1] if self.events else None


@pytest.mark.parametrize("camera", ["following", "fixed", "pan"])
def test_actual_sender_tracks_sprite_displacement_independent_of_camera(camera):
    h = SenderHarness()
    assert h.tick()["x"] == 528
    for step in range(1, 9):
        h.pose(x=32, previous_x=33 if step < 8 else 32, px=120 - 2 * step,
               coffx=2 * step if camera == "following" else 0,
               coffy=-40 - step if camera == "pan" else -40, idle=step == 8)
        event = h.tick()
        assert (event["x"], event["y"]) == (528 - 2 * step, 544)


def test_fixed_camera_wall_bump_does_not_advance_peer():
    h = SenderHarness()
    h.tick()
    h.pose(idle=False)
    assert h.tick()["mv"] == 0


def test_midstep_start_waits_for_a_tile_aligned_calibration():
    h = SenderHarness()
    h.pose(x=32, previous_x=33, px=114, idle=False)
    assert h.tick() is None
    h.pose(x=32, px=104)
    assert h.tick()["x"] == 512


@pytest.mark.parametrize("change", ["map", "sprite", "graphics", "images", "scene", "tile_rebase"])
def test_changed_context_midstep_cannot_reuse_calibration(change):
    h = SenderHarness()
    h.tick()
    if change == "map":
        h.write(OE + 9, 2)
    elif change == "sprite":
        h.write(OE + 4, 1)
        for offset in range(68):
            h.write(SPRITE + 68 + offset, h.read(SPRITE + offset))
    elif change == "graphics":
        h.write(OE + 5, 1)
    elif change == "images":
        h.write(SPRITE + 12, 0x08EB3818, 4)
    elif change == "scene":
        h.write(0x030030F4, 0x08000001, 4)
        h.tick()
        h.write(0x030030F4, 0x080565B5, 4)
    h.pose(x=20 if change == "tile_rebase" else 32, previous_x=21 if change == "tile_rebase" else 33,
           px=118, idle=False)
    h.tick()
    assert len(h.events) == 1


@pytest.mark.parametrize("invalid", ["inactive", "sprite_range", "sprite_free", "binding", "coord_offset"])
def test_invalid_ownership_suppresses_position(invalid):
    h = SenderHarness()
    if invalid == "inactive":
        h.write(OE, 0x80)
    elif invalid == "sprite_range":
        h.write(OE + 4, 64)
    elif invalid == "sprite_free":
        h.write(SPRITE + 62, 2)
    elif invalid == "binding":
        h.write(SPRITE + 46, 1, 2)
    elif invalid == "coord_offset":
        h.write(SPRITE + 62, 1)
    assert h.tick() is None


def test_signed_sprite_wrap_uses_small_modular_displacement():
    h = SenderHarness()
    h.pose(px=-32768)
    h.tick()
    h.pose(x=32, previous_x=33, px=32766, idle=False)
    assert h.tick()["x"] == 526


def test_render_only_pos2_offsets_do_not_change_ground_position():
    h = SenderHarness()
    h.tick()
    h.write(SPRITE + 36, 8, 2)
    h.write(SPRITE + 38, -12, 2)
    h.pose(idle=False)
    assert (h.tick()["x"], h.events[-1]["y"]) == (528, 544)


def test_actual_running33_recorded_trace_preserves_normal_route_positions():
    data = json.loads((ROOT / "tests/rr/fixtures/running33_position_trace.json").read_text())
    assert data["result_sha256"] == "7070bf6a54867a4c6f4d6d5cacc1af90fe980d41b292299697904b880e72e862"
    assert data["release_ready"] is False and len(data["samples"]) == 65
    h = SenderHarness()
    for row in data["samples"]:
        p = dict(zip(data["columns"], row, strict=True))
        h.pose(x=p["x"], previous_x=p["previous_x"], y=p["y"], previous_y=p["previous_y"],
               px=p["player_px"], py=p["player_py"], coffx=p["coffx"], coffy=p["coffy"],
               idle=bool(p["flags"] & 0x80))
        h.write(SPRITE + 42, p["anim"])
        event = h.tick()
        assert (event["x"], event["y"]) == (p["wx"], p["wy"]), p["frame"]


@pytest.mark.parametrize("is_rr", [False, True])
def test_actual_initialization_loads_position_dependency_only_for_rr(is_rr):
    h = MailboxHarness()
    source = (ROOT / "lua/clients/gen3_frlge_client.lua").read_text(encoding="utf-8")
    declaration = next(line for line in source.splitlines() if line.startswith("local pg_position"))
    start = source.index("    if IS_RR then", source.index("-- Peer ghost (RR"))
    end = source.index("    if IS_RR and is_overworld and patch_present() then", start)
    calls = []
    module = h.lua.execute((ROOT / "lua/rr/peer_position.lua").read_text())

    def require(name):
        calls.append(name)
        assert name == "rr.peer_position"
        return module

    h.lua.globals().require = require
    h.lua.globals().is_overworld = True
    h.lua.globals().patch_present = lambda: True
    invoke = h.lua.execute(declaration + "\nreturn function(IS_RR)\n" + source[start:end] + "\nend")
    invoke(is_rr)
    invoke(is_rr)
    assert calls == (["rr.peer_position"] if is_rr else [])
