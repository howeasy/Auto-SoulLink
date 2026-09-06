"""Presence component assertions with modeled scenes, not a real battle oracle."""

from pathlib import Path

import pytest

from tests.unit.test_rr_ghost_resource_probe import (
    ANIMS,
    GH,
    IMAGES,
    OBJECTS,
    SPRITES,
    ProbeHarness,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "lua/tests/rr/ghost_natural_battle_probe.lua"


def setup(tmp_path, fault=None):
    h = ProbeHarness(tmp_path, fault=fault)
    h.write(OBJECTS + 5, 0)
    h.write(OBJECTS + 8, 255)
    for offset, value in ((16, 23), (20, 23), (18, 12), (22, 12)):
        h.write(OBJECTS + offset, value, 2)
    h.write(SPRITES + 62, 3)
    h.write(0x08EB1000, 0x08EB140C, 4)
    h.write(0x08EB140C + 6, 512, 2)
    h.write(0x08EB140C + 28, IMAGES, 4)
    h.write(0x08EB140C + 24, ANIMS, 4)
    h.write(0x03003840, 0x02025000, 4)
    h.write(0x03005008, 0x02025000, 4)
    h.write(0x02025004, 3)
    h.write(0x02025005, 19)
    h.write(0x02036DFC, 0x082E55CC, 4)
    h.write(0x03005040, 39, 4)
    h.write(0x03005048, 0x02010000, 4)
    h.write(0x02010000 + (12 * 39 + 25) * 2, 0x3000, 2)
    h.write(0x02010000 + (13 * 39 + 25) * 2, 0x3000, 2)
    h.lua.globals().model_route = h.table({"peer_tiles": h.table([
        h.table({"x": 25, "y": 12, "word": 0x3000, "attribute": 0}),
        h.table({"x": 25, "y": 13, "word": 0x3000, "attribute": 0}),
    ])})
    # The reusable resource fixture's callback differs from frozen03's symbol.
    h.config.probe_options.native_contract.ghost_callback = 0x0837A970
    original_allocate = h.allocate

    def allocate():
        original_allocate()
        if fault != "wrong_callback":
            h.write(SPRITES + 5 * 68 + 28, 0x0837A971, 4)

    h.allocate = allocate
    original_advance = h.advance
    return_frames = 0

    def advance():
        nonlocal return_frames
        original_advance()
        if fault != "missing_coord_offset" and h.read(SPRITES + 5 * 68 + 62) & 1:
            h.write(SPRITES + 5 * 68 + 62, h.read(SPRITES + 5 * 68 + 62) | 2)
        gid = h.read(GH + 1)
        if gid < 16 and h.read(0x030030F4, 4) == 0x080565B5:
            if h.lua.globals().model_assertions.battle:
                return_frames += 1
                if fault == "return_owner_lost" and return_frames == 4:
                    h.write(SPRITES + 5 * 68 + 28, 0x08000101, 4)
            for offset in (16, 20):
                h.write(OBJECTS + gid * 36 + offset, h.read(OBJECTS + 16, 2) + 2, 2)
            for offset in (18, 22):
                h.write(OBJECTS + gid * 36 + offset, h.read(OBJECTS + 18, 2), 2)

    h.lua.globals().emu.frameadvance = advance
    h.lua.globals().model_write = h.write
    h.lua.globals().model_assertions = h.table({})
    h.lua.execute("""
        local original_dofile=dofile
        dofile=function(path)
            if path:match('/natural_battle_probe.lua$') then
                return function(ctx,component)
                    local out={route=model_route};ctx.report.evidence.runtime=out
                    local api={out=out,capture=function() end,resources=function() end}
                    api.advance=function(buttons,label)
                        component.before_frame();emu.frameadvance()
                        local p={frame=emu.framecount(),label=label}
                        component.after_frame(p)
                        return p
                    end
                    component.begin(api)
                    model_assertions.ready=true
                    model_write(0x030030F4,0x08011101,4)
                    model_write(0x02023BE4+44,22,2)
                    model_write(0x0203F850+43,2,1)
                    for i=1,3 do api.advance({},'battle') end
                    model_assertions.battle=true
                    model_write(0x030030F4,0x080565B5,4)
                    model_write(0x02023E8A,4,1)
                    model_write(0x02036E38+18,13,2)
                    model_write(0x02036E38+22,13,2)
                    component.finish(api)
                end
            end
            return original_dofile(path)
        end
    """)
    return h


def test_component_uses_owned_presence_then_skips_publications_in_battle_and_cleans(tmp_path):
    h = setup(tmp_path)
    h.lua.execute(SOURCE.read_text())(h.context)
    out = h.report.evidence.runtime.ghost_component
    assert h.posts == [14, 15] and out.nonfield_frames == out.suspended_frames == 3
    assert len(out.requests) == 2 and out.field_owned_frames > 0
    assert len(out.allocations) == 1 and out.allocations[1].fully_owned is False
    assert out.allocations[1].sprite_flags & 4  # Hidden allocation is still attributed.
    assert out.after.refs == out.reference.refs and out.after.tiles == out.reference.tiles
    assert all(p.callback2 == 0x080565B5 and p.script_lock == 0 for p in out.publications.values())
    assert len(h.assertions) == len(set(h.assertions))
    assert "ghost_wild_component_complete" in h.assertions
    assert out.return_presentation.frames == 12
    assert out.return_presentation.last_frame - out.return_presentation.first_frame == 12


@pytest.mark.parametrize("fault,match", [
    ("wrong_callback", "ghost_wild_initial_owned"), ("wrong_allocation", "ghost_wild_initial_owned"),
    ("missing_coord_offset", "ghost_wild_initial_owned"),
    ("return_owner_lost", "ghost_wild_return_present_3_owned"),
    ("palette_leak", "ghost_wild_no_private_after"), ("tile_leak", "ghost_wild_allocated_tile_accounted"),
])
def test_component_rejects_false_ownership_or_leaked_resources(tmp_path, fault, match):
    h = setup(tmp_path, fault)
    with pytest.raises(Exception, match=match):
        h.lua.execute(SOURCE.read_text())(h.context)
    assert "ghost_wild_component_complete" not in h.assertions


def test_component_refuses_wrong_pinned_callback_before_presence_requests(tmp_path):
    h = setup(tmp_path)
    h.config.probe_options.native_contract.ghost_callback = 0x08370000
    with pytest.raises(Exception, match="ghost_wild_callback"):
        h.lua.execute(SOURCE.read_text())(h.context)
    assert h.posts == [] and h.read(GH) == 0


def add_stock_grass_after_clear(h, fault=None):
    original_complete = h.complete

    def complete(*args, **kwargs):
        opcode = h.read(h.mb.BASE + 6, 2)
        original_complete(*args, **kwargs)
        if opcode != 15:
            return
        sprite = SPRITES + 60 * 68
        h.write(sprite + 2, 0x4000, 2)
        h.write(sprite + 4, 0x1000 | 32, 2)
        h.write(sprite + 8, 0x083A541C, 4)
        h.write(sprite + 12, 0x083A53DC, 4)
        h.write(sprite + 20, 0x083A5420, 4)
        h.write(sprite + 28, 0x080DB3ED, 4)
        h.write(sprite + 48, 23, 2)
        h.write(sprite + 50, 13, 2)
        h.write(sprite + 52, 0xF001 if fault == "wrong_owner" else 0xFF01, 2)
        h.write(sprite + 62, 3)
        for offset, value, width in [(0, 65535, 2), (2, 0x1005, 2), (8, 0x083A541C, 4),
                                      (12, 0x083A53DC, 4), (20, 0x080DB3ED, 4)]:
            h.write(0x083A5420 + offset, value, width)
        for frame in range(5):
            h.write(0x083A53DC + frame * 8 + 4, 128, 2)
        h.write(0x0203B7D4 + 4, 2)
        h.write(0x0203B7D4 + 5, 1)
        h.write(0x0203B7D4 + 6, 0x1005, 2)
        for bit in range(32, 37 if fault == "extra_tile" else 36):
            h.tile(bit, 1)

    h.complete = complete


def test_old_ghost_tiles_can_be_reassigned_only_to_proven_player_grass(tmp_path):
    h = setup(tmp_path)
    add_stock_grass_after_clear(h)
    h.lua.execute(SOURCE.read_text())(h.context)
    out = h.report.evidence.runtime.ghost_component
    assert len(out.stock_reassignments) == 1 and out.stock_reassignments[1].tile == 32
    assert out.stock_reassignments[1].owner_id == 0
    assert "ghost_wild_component_complete" in h.assertions


@pytest.mark.parametrize("fault,match", [
    ("wrong_owner", "ghost_wild_grass_owner"), ("extra_tile", "ghost_wild_allocated_tile_accounted"),
])
def test_grass_tag_does_not_excuse_wrong_owner_or_additional_leaked_tiles(tmp_path, fault, match):
    h = setup(tmp_path)
    add_stock_grass_after_clear(h, fault)
    with pytest.raises(Exception, match=match):
        h.lua.execute(SOURCE.read_text())(h.context)
    assert "ghost_wild_component_complete" not in h.assertions
