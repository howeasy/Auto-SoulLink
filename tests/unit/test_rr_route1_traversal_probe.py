"""Traversal-oracle fault injection; synthetic movement is not route evidence."""

from pathlib import Path

import pytest

from tests.unit.test_rr_ghost_resource_probe import OBJECTS, SPRITES, ProbeHarness

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "lua/tests/rr/route1_traversal_probe.lua"
SB1, GRID, OLD_LAYOUT, NEW_LAYOUT = 0x02025000, 0x02010000, 0x082DE3E4, 0x082E55CC


class TraversalHarness(ProbeHarness):
    def __init__(self, tmp_path, fault=None):
        super().__init__(tmp_path)
        self.route_fault = fault
        self.inputs = []
        self.buttons = {}
        self.write(0x03003840, SB1, 4)
        self.write(0x03005008, SB1, 4)
        self.write(SB1 + 4, 3)
        self.write(SB1 + 5, 1)
        self.write(OBJECTS + 9, 1)  # Spawn map deliberately stays Viridian.
        self.write(OBJECTS + 10, 3)
        self.write(OBJECTS + 11, 3)
        self.write(SPRITES + 62, 3)
        self.write(0x02036DFC, OLD_LAYOUT, 4)
        self.write(0x03005040, 63, 4)
        self.write(0x03005044, 54, 4)
        self.write(0x03005048, GRID, 4)
        self.write(0x0203B470, 1, 2)
        for i in range(63 * 54):
            self.write(GRID + i * 2, 0x3000, 2)
        self.place(33, 34)
        initial = self.table({
            "prerequisites": self.table({"var_507e": 1}),
            "map": self.table({"layout": OLD_LAYOUT, "grid_width": 63,
                               "grid_words": self.table([0x3000] * (63 * 54)),
                               "metatile_attributes": self.table([0] * 1024)}),
        })
        self.report.evidence.runtime = initial
        self.lua.globals().initial_observation = initial
        self.lua.execute("""
            local original_dofile = dofile
            dofile = function(path)
                if path:match('/encounter_route_observation.lua$') then
                    return function(ctx) ctx.report.evidence.runtime = initial_observation end
                end
                return original_dofile(path)
            end
        """)
        self.lua.globals().joypad.set = self.set_buttons
        self.context.checkpoint = lambda _phase: None

    def place(self, x, y):
        for offset, value in ((16, x), (18, y), (20, x), (22, y)):
            self.write(OBJECTS + offset, value, 2)

    def set_buttons(self, buttons):
        self.buttons = dict(buttons.items())

    def advance(self):
        self.frame += 1
        self.inputs.append(self.buttons.copy())
        x = self.read(OBJECTS + 16, 2)
        y = self.read(OBJECTS + 18, 2)
        x -= bool(self.buttons.get("Left"))
        y += bool(self.buttons.get("Down"))
        if y == 47:
            x, y = 17, 7
            self.write(SB1 + 5, 20 if self.route_fault == "wrong_map" else 19)
            self.write(0x02036DFC, NEW_LAYOUT, 4)
            self.write(NEW_LAYOUT, 24, 4)
            self.write(NEW_LAYOUT + 4, 40, 4)
            self.write(NEW_LAYOUT + 16, 0x08131000, 4)
            self.write(NEW_LAYOUT + 20, 0x08131100, 4)
            self.write(0x08131014, 0x08132000, 4)
            self.write(0x08131114, 0x08133000, 4)
        if self.route_fault == "script" and self.frame == 1:
            self.write(0x03000F9C, 1)
        if self.route_fault == "battle" and self.frame == 1:
            self.write(0x03004FE0, 0x0802E439, 4)
        self.place(x, y)

    def run(self):
        self.lua.execute(SOURCE.read_text(encoding="utf-8"))(self.context)


def test_current_save_map_qualifies_connection_while_object_spawn_map_stays_old(tmp_path):
    h = TraversalHarness(tmp_path)
    h.run()
    out = h.report.evidence.runtime
    assert (out.arrival.map_group, out.arrival.map_num) == (3, 19)
    assert (out.arrival.object_spawn_map_group, out.arrival.object_spawn_map_num) == (3, 1)
    assert (out.arrival.x, out.arrival.y, out.arrival.layout) == (17, 7, NEW_LAYOUT)
    assert len(h.inputs) == 17 and h.buttons == {} and h.posts == []
    assert len(h.assertions) == len(set(h.assertions))
    assert out.release_ready is False and out.natural_battle_tested is False


@pytest.mark.parametrize("fault,error", [
    ("wrong_map", "Unexpected map"), ("script", "context|no_script"),
    ("battle", "no_action_controller"),
])
def test_unexpected_scene_fails_before_more_input_and_preserves_capture(tmp_path, fault, error):
    h = TraversalHarness(tmp_path, fault)
    with pytest.raises(Exception, match=error):
        h.run()
    assert h.buttons == {} and h.posts == []
    assert "route1_traversal_complete" not in h.assertions
    assert (tmp_path / "result_route1_failure.png").exists()
    if fault != "wrong_map":
        assert len(h.inputs) == 1


def test_bad_save_pointer_fails_before_any_route_input(tmp_path):
    h = TraversalHarness(tmp_path)
    h.write(0x03003840, 0x08000000, 4)
    with pytest.raises(Exception, match="route1_save_pointer"):
        h.run()
    assert h.inputs == [] and h.buttons == {}
