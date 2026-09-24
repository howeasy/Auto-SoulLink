"""Card gen2-u1e-poison, Gold errand fixture: the pure errand leg of lua/tests/gen2_scripted_play.lua on the real
gold_battle_errand route facts (tools/gen2_fixtures.spec_route_facts). No emulator: synthetic points in, buttons out.
Source facts: docs/gen2/reviews/OMP_GOLD_ERRAND_FACTS_2026-09-23.md (pokegold 656583c)."""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import gen2_fixtures as g  # noqa: E402

PLAY = ROOT / "lua/tests/gen2_scripted_play.lua"
SPEC = g.BY_NAME["gold_battle_errand"]
ALL = {"Up": True, "Down": True, "Left": True, "Right": True}


@functools.cache
def facts():
    return g.spec_route_facts(SPEC)


def test_errand_facts_add_only_the_errand_maps_events_prompt_and_naming_origin():
    plain, errand = g.route_facts("gold"), facts()
    assert set(errand["maps"]) - set(plain["maps"]) == {"CherrygroveCity", "Route30", "MrPokemonsHouse"}
    assert set(errand["ui_origins"]) - set(plain["ui_origins"]) == {"naming", "move_menu"}
    assert errand["ui_origins"]["naming"]["symbol"] == "NamingScreenJoypadLoop"
    assert set(errand["observer"]["errand_events"]) == set(g.ERRAND_EVENTS)
    assert errand["observer"]["prompts"]["tutorial"] == ["to show you how to"]
    assert "errand_events" not in plain["observer"] and "tutorial" not in plain["observer"]["prompts"]
    assert errand["fingerprint"] != plain["fingerprint"]
    # every other fixture keeps its recorded facts
    assert all(g.spec_route_facts(spec)["fingerprint"] == g.route_facts(spec.title)["fingerprint"]
               for spec in g.FIXTURES if spec.name not in g.ERRAND_FIXTURES and spec.title == "gold")


class Run:
    def __init__(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        P = self.lua.execute(PLAY.read_text(encoding="utf-8"))
        f = facts()
        case = {"name": SPEC.name, "title": "gold", "target": "battle", "identity": "default",
                "title_idle_frames": 0, "attempt_id": "unit-1"}
        self.facts = f
        self.driver = P.new(self.lua.table_from(f, recursive=True), self.lua.table_from(case))
        self.frame = 0
        # NEW GAME entry: the bedroom with an empty party marks the route entered
        self.step(map_name="PlayersHouse2F", x=3, y=3, party_count=0, got_starter=False)

    def point(self, map_name, **fields):
        m = self.facts["maps"][map_name]
        base = {"title": "gold", "rom_sha1": self.facts["rom_sha1"], "core_mode": "CGB", "attempt_id": "unit-1",
                "facts_fingerprint": self.facts["fingerprint"], "overworld_ready": True, "battle_mode": 0,
                "party_count": 1, "starter_species": self.facts["starter"]["species"], "starter_level": 5,
                "got_starter": True, "pokegear_obtained": True, "save_success_counter": 0,
                "new_bark_scene": self.facts["maps"]["NewBarkTown"]["scenes"]["SCENE_NEWBARKTOWN_NOOP"],
                "ball_pocket": {"count": 1, "items": {1: {"id": self.facts["balls"]["item"], "quantity": 10}},
                                "terminator": 255},
                "map_group": m["map_group"], "map_number": m["map_number"], "can_step": ALL, "facing": "Down",
                "got_egg": False, "gave_egg": False}
        base.update(fields)
        return self.lua.table_from(base, recursive=True)

    def step(self, map_name, **fields):
        self.frame += 1
        buttons, phase = self.driver.step(self.point(map_name, **fields), self.frame)[:2]
        assert buttons is not None, phase
        return sorted(k for k, v in buttons.items() if v), phase

    def press(self, map_name, **fields):
        pressed = self.step(map_name, **fields)
        for _ in range(12):
            self.step(map_name, **fields)
        return pressed


def test_outbound_route29_and_cherrygrove_cross_their_source_edges():
    r = Run()
    assert r.step("Route29", x=10, y=6)[1] == "errand-west"
    assert r.press("Route29", x=0, y=6) == (["Left"], "errand-west")
    assert r.step("CherrygroveCity", x=39, y=6)[1] == "errand-west"
    assert r.press("CherrygroveCity", x=16, y=0) == (["Up"], "errand-west")


def test_route30_heads_for_mr_pokemons_door_and_the_house_scene_waits():
    r = Run()
    buttons, phase = r.step("Route30", x=17, y=6)
    assert (buttons, phase) == (["Up"], "errand-mr-pokemon")      # (17,5) is the door warp
    assert r.step("MrPokemonsHouse", x=3, y=7) == ([], "errand-mr-pokemon")


def test_with_the_egg_the_house_is_left_and_cherrygrove_crosses_the_unavoidable_rival_tiles():
    r = Run()
    egg = {"got_egg": True}
    assert r.step("MrPokemonsHouse", x=3, y=5, **egg)[1] == "errand-egg"
    assert r.press("Route30", x=7, y=53, **egg) == (["Down"], "errand-egg")
    rival = {(e["x"], e["y"]) for e in r.facts["maps"]["CherrygroveCity"]["coord_events"]}
    assert rival == {(33, 6), (33, 7)}
    # rows 4-5 end at x=31 and rows 8-9 at x=33: the east exit is reached only across the rival's tiles
    grid, width = r.facts["maps"]["CherrygroveCity"]["grid"], r.facts["maps"]["CherrygroveCity"]["width"]
    assert all(grid[y * width + 34] == 0 for y in (4, 5, 8, 9)) and grid[4 * width + 32] == 0
    assert r.step("CherrygroveCity", x=32, y=7, **egg)[1] == "errand-east"      # a path exists (no avoid list)
    assert r.press("CherrygroveCity", x=39, y=6, **egg) == (["Right"], "errand-east")
    assert r.press("Route29", x=59, y=8, **egg) == (["Right"], "errand-east")
    assert r.step("NewBarkTown", x=6, y=5, **egg) == (["Up"], "errand-elm")     # the lab door (6,3)


def test_the_lab_waits_out_the_officer_then_talks_to_elm_from_below():
    r = Run()
    egg = {"got_egg": True}
    cop = {"blocked": {1: {"x": 5, "y": 3}}}
    assert r.step("ElmsLab", x=5, y=4, **egg, **cop) == ([], "errand-elm")
    assert r.step("ElmsLab", x=5, y=4, **egg)[0] == ["Up"]                   # the officer left: to (5,3)
    assert r.press("ElmsLab", x=5, y=3, facing="Up", **egg) == (["A"], "errand-elm")


def test_the_naming_screen_takes_start_then_a_and_the_tutorial_gets_no():
    r = Run()
    naming = {"overworld_ready": False, "input_ready": True,
              "ui": {"kind": "naming", "origin": "NamingScreenJoypadLoop"}}
    assert r.press("ElmsLab", x=5, y=4, got_egg=True, **naming)[0] == ["Start"]
    assert r.press("ElmsLab", x=5, y=4, got_egg=True, **naming)[0] == ["A"]
    tutorial = {"overworld_ready": False, "input_ready": True,
                "ui": {"kind": "yes_no", "origin": "_YesNoBox", "prompt": "tutorial", "items": {1: "YES", 2: "NO"},
                       "cursor": 1, "columns": 1}}
    assert r.press("Route29", x=53, y=8, got_egg=True, gave_egg=True, **tutorial)[0] == ["Down"]   # toward NO


def test_the_rival_battle_is_fought_with_leer_only():
    r = Run()
    battle = {"got_egg": True, "overworld_ready": False, "input_ready": True, "battle_mode": 2}
    menu = {"kind": "battle_menu", "origin": "BattleMenu", "items": {1: "FIGHT", 2: "<PK><MN>", 3: "PACK", 4: "RUN"},
            "cursor": 1, "columns": 2}
    assert r.press("CherrygroveCity", x=33, y=6, ui=menu, **battle)[0] == ["A"]
    moves = {"kind": "move_menu", "origin": "MoveSelectionScreen.interpret_joypad", "items": {1: "SCRATCH", 2: "LEER"},
             "cursor": 1, "columns": 1}
    assert r.press("CherrygroveCity", x=33, y=6, ui=moves, **battle)[0] == ["Down"]
    assert r.press("CherrygroveCity", x=33, y=6, ui=dict(moves, cursor=2), **battle)[0] == ["A"]


def test_the_handoff_is_marked_once_then_the_battle_route_takes_over():
    r = Run()
    done = {"got_egg": True, "gave_egg": True}
    assert r.step("ElmsLab", x=5, y=3, **done) == ([], "errand-handoff")
    assert r.step("ElmsLab", x=5, y=3, **done)[1] == "leave-elm"
    assert r.step("NewBarkTown", x=5, y=8, **done)[1] == "to-route29"


@pytest.mark.parametrize("name", ["gold_battle", "gold_town"])
def test_plain_facts_never_run_the_errand(name):
    spec = g.BY_NAME[name]
    lua = LuaRuntime(unpack_returned_tuples=True)
    P = lua.execute(PLAY.read_text(encoding="utf-8"))
    plain = g.route_facts("gold")
    case = {"name": name, "title": "gold", "target": spec.target, "identity": "default", "title_idle_frames": 0,
            "attempt_id": "unit-1"}
    driver = P.new(lua.table_from(plain, recursive=True), lua.table_from(case))
    assert driver.errand is not None   # the method exists, but nothing routes into it without errand events
    assert "errand_events" not in plain["observer"]


def test_a_phantom_object_on_the_only_aisle_does_not_strand_the_route():
    """Errand live attempt a1 (and Crystal U1e run 1): an object struct read at Route 29 (11,7), the one-tile
    aisle west, closed every path. The planner retries without objects; a real NPC only bumps the step."""
    r = Run()
    assert r.step("Route29", x=11, y=6, blocked={1: {"x": 11, "y": 7}}) == (["Down"], "errand-west")
