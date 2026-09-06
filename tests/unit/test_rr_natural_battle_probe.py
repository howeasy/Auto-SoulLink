"""Battle-probe decision tests with a synthetic engine; no physical acceptance."""

import json
from pathlib import Path

import pytest

from tests.unit.test_rr_route1_traversal_probe import GRID, NEW_LAYOUT, SB1, TraversalHarness

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "lua/tests/rr/natural_battle_probe.lua"


class BattleHarness(TraversalHarness):
    def __init__(self, tmp_path, fault=None):
        super().__init__(tmp_path)
        self.battle_fault = fault
        self.stage = "field"
        self.phase_frames = 0
        self.write(SB1 + 5, 19)
        self.write(0x02036DFC, NEW_LAYOUT, 4)
        self.place(17, 7)
        route = json.loads((ROOT / "lua/tests/rr/route1_grass_route.json").read_text())
        self.config.identity = self.table({key: route[key] for key in ("rom_sha256", "fixture_sha256")})
        self.write(0x03005040, route["grid_width"], 4)
        for tile in route["tiles"]:
            self.write(GRID + (tile["y"] * route["grid_width"] + tile["x"]) * 2, tile["word"], 2)
        self.write(0x02024284 + 86, 22, 2)
        for address, data in [(0x0802E438, bytes.fromhex("00480047a19e0a09")),
                              (0x08016748, bytes.fromhex("004908473d050909")),
                              (0x08030610, bytes.fromhex("00b50020d2f726fc0004002801d1fdf7")),
                              (0x08005634, bytes.fromhex("00490847590e0c09")),
                              (0x08005680, bytes.fromhex("00490847a50e0c09"))]:
            for i, value in enumerate(data):
                self.write(address + i, value)
        self.write(0x08002E78, 0x02020034, 4)
        self.lua.execute("""
            local original_dofile = dofile
            dofile = function(path)
                if path:match('/route1_traversal_probe.lua$') then
                    return function(ctx) ctx.report.evidence.runtime = {classification='synthetic_arrival'} end
                end
                return original_dofile(path)
            end
        """)

    def advance(self):
        self.frame += 1
        self.inputs.append(self.buttons.copy())
        if self.stage == "field":
            x, y = self.read(0x02036E48, 2), self.read(0x02036E4A, 2)
            x += bool(self.buttons.get("Right")) - bool(self.buttons.get("Left"))
            y += bool(self.buttons.get("Down"))
            self.place(x, y)
            if y == 13:
                self.stage = "intro"
                self.write(0x030030F4, 0x08012345, 4)
                self.write(0x03000F9C, 1)
        elif self.stage == "intro":
            self.phase_frames += 1
            if self.phase_frames == (500 if self.battle_fault == "long_intro" else 2):
                self.stage = "text"
                self.write(0x030030F4, 0x08011101, 4)
                self.write(0x03004FE0, 0x0802E3B5 if self.battle_fault == "printer_controller" else 0x08030611, 4)
                self.write(0x02022B4C, 4, 4)
                self.write(0x02023BCC, 2)
                self.write(0x02020034 + 27, 1)
                self.write(0x02020034 + 28, 0 if self.battle_fault == "printer_state" else 2)
        elif self.stage == "text":
            if self.buttons.get("B"):
                self.stage = "menu"
                self.write(0x03004FE0, 0x0802E3B5 if self.battle_fault == "dispatcher" else 0x0802E439, 4)
                self.write(0x02023BCC, 2)
                self.write(0x0202402A, 0)  # Actual CFRU wild count is stale.
                self.write(0x0202402C + 86, 14, 2)
                self.write(0x0202402C + 88, 14, 2)
                self.write(0x02023BE4, 277, 2)
                self.write(0x02023BE4 + 40, 22, 2)
                self.write(0x02023BE4 + 44, 22, 2)
                self.write(0x02023BE4 + 88, 19, 2)
                if self.battle_fault == "trainer":
                    self.write(0x02022B4C, 8, 4)
                if self.battle_fault == "hp_loss":
                    self.write(0x02024284 + 86, 21, 2)
        elif self.stage == "menu":
            cursor = self.read(0x02023FF8)
            if self.buttons.get("Right") and self.battle_fault != "ignored_cursor":
                self.write(0x02023FF8, cursor | 1)
            if self.buttons.get("Down"):
                self.write(0x02023FF8, cursor | 2)
            if self.buttons.get("A"):
                assert cursor == 3
                self.stage = "escape"
                self.phase_frames = 0
                self.write(0x03004FE0, 0, 4)
        elif self.stage == "escape":
            self.phase_frames += 1
            self.write(0x02023E8A, 4)
            if self.phase_frames == 3:
                self.stage = "returned"
                self.write(0x030030F4, 0x080565B5, 4)
                self.write(0x03000F9C, 0)

    def run(self):
        self.lua.execute(SOURCE.read_text(encoding="utf-8"))(self.context)


def test_verified_action_menu_and_each_cursor_transition_precede_run(tmp_path):
    h = BattleHarness(tmp_path)
    h.run()
    out = h.report.evidence.runtime
    assert [row.button for row in out.menu_inputs.values()] == ["Right", "Down", "A"]
    assert [row.cursor_before for row in out.menu_inputs.values()] == [0, 1, 3]
    assert out.action_menu.controller0 == 0x0802E439
    assert out.action_menu.battle_type == 4 and out.action_menu.enemy_count == 0
    assert len(out.text_inputs) == 1 and out.text_inputs[1].button == "B"
    assert out.escape_outcome.outcome == 4 and out.returned.map_num == 19
    assert out.ghost_tested is False and out.release_ready is False
    assert h.buttons == {} and h.posts == []
    assert len(h.assertions) == len(set(h.assertions))


def test_bounded_long_intro_can_finish_without_weakening_action_or_hp_oracles(tmp_path):
    h = BattleHarness(tmp_path, "long_intro")
    h.run()
    out = h.report.evidence.runtime
    assert out.action_menu.frame > 500
    assert out.action_menu.controller0 == 0x0802E439 and out.action_menu.party_hp == 22
    assert sum(bool(row.get("A")) for row in h.inputs) == 1


def test_read_only_pointer_evidence_keeps_canonical_and_irq_alias_separate(tmp_path):
    h = BattleHarness(tmp_path)
    h.write(0x03005008, 0x02028000, 4)
    h.write(0x02028004, 3)
    h.write(0x02028005, 19)
    h.write(0x0300500C, 0x02027000, 4)
    h.write(0x0202700A, 0x2BDDC8BF, 4)
    h.run()
    for row in (h.report.evidence.runtime.action_menu, h.report.evidence.runtime.returned):
        p = row.save_pointers
        assert p.sb1_canonical.value == 0x02028000 and p.sb1_irq_alias.value == SB1
        assert p.sb1_canonical.map_num == p.sb1_irq_alias.map_num == 19
        assert p.sb2_canonical.trainer_id == 0x2BDDC8BF
        assert p.sb2_irq_alias.valid is False


@pytest.mark.parametrize("fault,match", [
    ("dispatcher", "wild_action_menu_verified"), ("trainer", "wild_intro_no_trainer"),
    ("hp_loss", "wild_no_hp_loss"), ("ignored_cursor", "select_run_right_cursor"),
])
def test_unsafe_or_unverified_battle_never_receives_confirm_run(tmp_path, fault, match):
    h = BattleHarness(tmp_path, fault)
    with pytest.raises(Exception, match=match):
        h.run()
    assert not any(row.get("A") for row in h.inputs)
    assert h.buttons == {} and h.posts == []
    assert "wild_qualification_complete" not in h.assertions
    assert h.report.evidence.runtime.error


@pytest.mark.parametrize("fault", ["printer_controller", "printer_state"])
def test_intro_text_input_requires_both_exact_controller_and_waiting_printer(tmp_path, fault):
    h = BattleHarness(tmp_path, fault)
    with pytest.raises(Exception, match="wild_action_menu_verified"):
        h.run()
    assert not any(row.get("A") or row.get("B") for row in h.inputs)
    assert h.buttons == {} and len(h.report.evidence.runtime.text_inputs) == 0
