"""Card gen2-u1e-poison: the pure poison leg (lua/tests/gen2_poison_inputs.lua) and the frame-align gate's poison
record rules (lua/tests/gen2_frame_align.lua F.poison_problem / F.poison_emission_problem / F.expect).
No emulator: synthetic points in, buttons out."""
from __future__ import annotations

from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
POISON = ROOT / "lua/tests/gen2_poison_inputs.lua"
ALIGN = ROOT / "lua/tests/gen2_frame_align.lua"
PSN = 8

# 5x3 map: row 0 floor, row 1 grass except x=4, row 2 floor. group 1.
GRID = [1, 1, 1, 1, 1,
        2, 2, 2, 2, 1,
        1, 1, 1, 1, 1]


def lua():
    return LuaRuntime(unpack_returned_tuples=True)


def load(rt):
    return rt.execute(POISON.read_text(encoding="utf-8"))


def frame_align(rt):
    rt.globals().SLINK_GEN2_GATE_LIBRARY = True
    return rt.execute(ALIGN.read_text(encoding="utf-8"))


def table(rt, value):
    return rt.table_from(value, recursive=True)


def lua_list(values):
    return {i + 1: v for i, v in enumerate(values)}


def a_map(number, grid=GRID, width=5, height=3):
    return {"map_group": 1, "map_number": number, "map_const": f"M{number}", "width": width, "height": height,
            "grid": lua_list(grid), "warps": {}}


ALL = {"Up": True, "Down": True, "Left": True, "Right": True}


def test_path_prefers_floor_to_grass_and_arrives():
    rt = lua()
    PI = load(rt)
    m = table(rt, a_map(1))
    # (3,0) -> (3,2): straight down costs grass 4 + floor 1 = 5; around the floor column x=4 costs 4
    step = PI.step_toward(m, table(rt, {"x": 3, "y": 0, "can_step": ALL}), table(rt, lua_list([{"x": 3, "y": 2}])))
    assert step == "Right"
    # (0,0) -> (0,2): the detour costs 10, so the grass is crossed
    assert PI.step_toward(m, table(rt, {"x": 0, "y": 0, "can_step": ALL}), table(rt, lua_list([{"x": 0, "y": 2}]))) == "Down"
    assert PI.step_toward(m, table(rt, {"x": 0, "y": 2, "can_step": ALL}),
                          table(rt, lua_list([{"x": 0, "y": 2}]))) == "arrived"


def test_path_first_step_obeys_live_collision_and_objects():
    rt = lua()
    PI = load(rt)
    m = table(rt, a_map(1))
    no_right = dict(ALL, Right=False)
    step = PI.step_toward(m, table(rt, {"x": 0, "y": 0, "can_step": no_right}), table(rt, lua_list([{"x": 0, "y": 2}])))
    assert step == "Down"
    blocked = PI.step_toward(m, table(rt, {"x": 0, "y": 0, "can_step": no_right, "blocked": lua_list([{"x": 0, "y": 1}])}),
                             table(rt, lua_list([{"x": 0, "y": 2}])))
    assert blocked[0] is None and "no source path" in blocked[1]


FACTS = {"maps": {"A": a_map(1), "H": a_map(2)}, "hunt_map": "H",
         "legs": lua_list([{"map": "A", "side": "Left", "exits": lua_list([{"x": 0, "y": 0}])}]),
         "hunt_grass": lua_list([{"x": 1, "y": 1}]), "park": lua_list([{"x": 0, "y": 2}, {"x": 1, "y": 2}]),
         "moves": {"POISON_STING": 40}, "psn_mask": PSN}
MENU = ["FIGHT", "<PK><MN>", "PACK", "RUN"]


def driver(rt, PI):
    F = rt.eval("{walk_direction=function() return 'Left' end}")
    return PI.driver(F, table(rt, FACTS), table(rt, {"moves": lua_list(["GROWL", "LEER"])}))


def pt(rt, **fields):
    base = {"map_group": 1, "map_number": 2, "x": 1, "y": 1, "can_step": ALL, "battle_mode": 0,
            "overworld_ready": True, "input_ready": True, "party": {0: {"hp": 20, "status": 0}, 1: {"hp": 12, "status": 0}}}
    base.update(fields)
    return table(rt, base)


def ui(kind, items=None, cursor=1, columns=1, **extra):
    out = {"kind": kind, **extra}
    if items:
        out.update(items=lua_list(items), cursor=cursor, columns=columns)
    return out


def step(rt, d, **fields):
    buttons, phase = d.step(pt(rt, **fields))
    assert buttons is not None, phase
    pressed = sorted(k for k, v in buttons.items() if v)
    if pressed and pressed[0] in ("A", "B", "Up", "Down", "Left", "Right") and fields.get("ui"):
        for _ in range(12):
            d.step(pt(rt, **fields))
    return pressed, phase


def test_travel_crosses_the_source_edge_then_enters_the_hunt_grass():
    rt = lua()
    d = driver(rt, load(rt))
    assert step(rt, d, map_number=1, x=1, y=0) == (["Left"], "travel")      # toward the exit tile
    assert step(rt, d, map_number=1, x=0, y=0) == (["Left"], "travel")      # on it: hold the side
    assert step(rt, d, map_number=2, x=1, y=0)[0] == ["Down"]               # hunt map: onto the grass
    assert step(rt, d, map_number=2, x=1, y=1) == (["Left"], "hunt")        # grass reached: oscillate


def test_battle_runs_from_a_foe_without_poison_sting():
    rt = lua()
    d = driver(rt, load(rt))
    step(rt, d, map_number=2, x=1, y=1)
    battle = {"battle_mode": 1, "active_slot": 0, "active_hp": 20, "foe_sting": False, "overworld_ready": False}
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **battle)[0] == ["Right"]
    assert step(rt, d, ui=ui("battle_menu", MENU, 2, 2), **battle)[0] == ["Down"]
    assert step(rt, d, ui=ui("battle_menu", MENU, 4, 2), **battle)[0] == ["A"]


def test_a_poison_sting_foe_gets_leer_until_a_party_mon_is_poisoned_then_run():
    rt = lua()
    d = driver(rt, load(rt))
    step(rt, d, map_number=2, x=1, y=1)
    battle = {"battle_mode": 1, "active_slot": 0, "active_hp": 20, "foe_sting": True, "overworld_ready": False}
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **battle)[0] == ["A"]                       # FIGHT
    assert step(rt, d, ui=ui("move_menu", ["SCRATCH", "LEER"]), **battle)[0] == ["Down"]
    assert step(rt, d, ui=ui("move_menu", ["SCRATCH", "LEER"], 2), **battle)[0] == ["A"]             # never SCRATCH
    battle["active_psn"] = True
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **battle)[0] == ["Right"]                   # toward RUN
    assert step(rt, d, ui=ui("move_menu", ["SCRATCH", "LEER"]), **battle)[0] == ["B"]


def test_a_worn_down_or_passive_less_mon_switches_out_and_nobody_fit_runs():
    """Silver live run 1: the lead was worn down until a sting fainted it in battle."""
    rt = lua()
    d = driver(rt, load(rt))
    step(rt, d, map_number=2, x=1, y=1)
    low = {"battle_mode": 1, "active_slot": 0, "active_hp": 7, "foe_sting": True, "overworld_ready": False}
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **low)[0] == ["Right"]                      # PKMN cell
    assert step(rt, d, ui=ui("battle_party"), party_cursor=0, **low)[0] == ["Down"]
    assert step(rt, d, ui=ui("battle_party"), party_cursor=1, **low)[0] == ["A"]
    assert step(rt, d, ui=ui("battle_mon_menu", ["SWITCH", "STATS", "CANCEL"]), **low)[0] == ["A"]
    mate = {"battle_mode": 1, "active_slot": 1, "active_hp": 12, "foe_sting": True, "overworld_ready": False}
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **mate)[0] == ["A"]                         # FIGHT first
    assert step(rt, d, ui=ui("move_menu", ["TACKLE"]), **mate)[0] == ["B"]                            # no passive
    party = {0: {"hp": 20, "status": 0}, 1: {"hp": 12, "status": 0}}
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), party=party, **mate)[0] == ["Right"]         # PKMN now
    worn = {0: {"hp": 5, "status": 0}, 1: {"hp": 12, "status": 0}}
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), party=worn, **mate)[0] == ["Right"]          # toward RUN
    assert step(rt, d, ui=ui("battle_menu", MENU, 2, 2), party=worn, **mate)[0] == ["Down"]
    assert step(rt, d, ui=ui("battle_menu", MENU, 4, 2), party=worn, **mate)[0] == ["A"]


def test_any_poisoned_party_mon_ends_the_hunt():
    rt = lua()
    d = driver(rt, load(rt))
    step(rt, d, map_number=2, x=1, y=1)
    battle = {"battle_mode": 1, "active_slot": 0, "active_hp": 20, "foe_sting": True, "overworld_ready": False,
              "party": {0: {"hp": 20, "status": 0}, 1: {"hp": 9, "status": PSN}}}
    assert step(rt, d, ui=ui("battle_menu", MENU, 4, 2), **battle)[0] == ["A"]                       # RUN
    buttons, phase = d.step(pt(rt, x=1, y=1, party={0: {"hp": 20, "status": 0}, 1: {"hp": 9, "status": PSN}}))
    assert phase == "tick"


def test_poisoned_lead_ticks_on_the_park_tiles_then_parks_after_the_faint():
    rt = lua()
    d = driver(rt, load(rt))
    step(rt, d, map_number=2, x=1, y=1)
    poisoned = {"party": {0: {"hp": 9, "status": PSN}, 1: {"hp": 12, "status": 0}}}
    buttons, phase = d.step(pt(rt, x=1, y=1, **poisoned))
    assert phase == "tick" and buttons["Down"]                     # off the grass toward park[1] (0,2)
    buttons, phase = d.step(pt(rt, x=0, y=2, **poisoned))
    assert phase == "tick" and buttons["Right"]                    # on park[1]: go to park[2]
    buttons, phase = d.step(pt(rt, x=1, y=2, **poisoned))
    assert phase == "tick" and buttons["Left"]
    assert step(rt, d, x=1, y=2, overworld_ready=False, ui=ui("text"))[0] == ["A"]   # "fainted!"
    fainted = {"party": {0: {"hp": 0, "status": 0}, 1: {"hp": 12, "status": 0}}, "poison_fainted": True}
    buttons, phase = d.step(pt(rt, x=1, y=2, **fainted))
    assert phase == "park" and buttons["Up"]                     # onto the hunt grass (1,1)
    buttons, phase = d.step(pt(rt, x=1, y=1, **fainted))
    assert phase == "poisoned" and not any(buttons.values())


def test_the_lead_fainting_in_battle_is_a_failure_not_a_poison_proof():
    rt = lua()
    d = driver(rt, load(rt))
    step(rt, d, map_number=2, x=1, y=1)
    buttons, why = d.step(pt(rt, battle_mode=1, active_slot=0, overworld_ready=False,
                             ui=ui("yes_no", ["YES", "NO"], prompt="next_mon")))
    assert buttons is None and "fainted in battle" in why


def test_a_battle_on_the_park_tiles_is_refused():
    rt = lua()
    d = driver(rt, load(rt))
    step(rt, d, map_number=2, x=1, y=1)
    d.step(pt(rt, x=1, y=1, party={0: {"hp": 9, "status": PSN}}))
    buttons, why = d.step(pt(rt, battle_mode=1, overworld_ready=False))
    assert buttons is None and "park" in why


GOOD = {"armed": 900, "callback": 900, "slot": 0, "party_count": 2, "battle_mode": 0, "species": 158, "dvs": 0xF794,
        "callback_hp": 0, "callback_status": PSN, "pre_hp": 1, "status_zero_frame": 900}


def test_poison_rule_accepts_the_same_frame_record():
    rt = lua()
    F = frame_align(rt)
    assert F.poison_problem(table(rt, GOOD), PSN) is None
    assert F.poison_problem(table(rt, dict(GOOD, pre_hp=0, status_zero_frame=901)), PSN) is None


@pytest.mark.parametrize("change,match", [
    ({"callback": 901}, "callback frame"),
    ({"slot": 2}, "party slot"),
    ({"battle_mode": 1}, "inside a battle"),
    ({"callback_hp": 1}, "0 HP"),
    ({"callback_status": 0}, "PSN"),
    ({"pre_hp": 2}, "1 HP"),
    ({"status_zero_frame": 902}, "status did not read 0"),
    ({"status_zero_frame": None}, "status did not read 0"),
])
def test_poison_rule_refuses_each_broken_measurement(change, match):
    rt = lua()
    F = frame_align(rt)
    record = {k: v for k, v in dict(GOOD, **change).items() if v is not None}
    assert match in F.poison_problem(table(rt, record), PSN)
    assert "no same-frame" in F.poison_problem(None, PSN)


EVENT = {"kind": "faint", "cause": "poison", "site_id": "poison_faint", "slot": 0, "species": 158, "dvs": 0xF794}


@pytest.mark.parametrize("events,match", [
    ([EVENT], None),
    ([], "emitted 0"),
    ([EVENT, EVENT], "emitted 2"),
    ([dict(EVENT, cause="battle")], "not a poison faint"),
    ([dict(EVENT, slot=1)], "another record"),
    ([dict(EVENT, dvs=1)], "another record"),
])
def test_emission_rule_needs_one_poison_faint_naming_the_snapshot(events, match):
    rt = lua()
    F = frame_align(rt)
    why = F.poison_emission_problem(table(rt, {"events": lua_list(events)}), table(rt, GOOD))
    assert (why is None) if match is None else (match in why)


def test_poison_joins_the_expected_order_just_before_battle_faint():
    rt = lua()
    F = frame_align(rt)
    assert list(F.expect(False).values()) == list(F.EXPECT.values())
    names = list(F.expect(True).values())
    assert names[-2:] == ["poison_faint", "battle_faint"] and len(names) == len(F.EXPECT) + 1


def test_a_path_blocked_only_by_a_live_object_waits_then_fails_with_the_live_facts():
    rt = lua()
    PI = load(rt)
    PI.WAIT_FRAMES = 3
    d = driver(rt, PI)
    closed = {"Up": False, "Down": False, "Left": False, "Right": False}
    wall = {"map_number": 1, "x": 0, "y": 2, "can_step": closed, "blocked": lua_list([{"x": 0, "y": 1}, {"x": 1, "y": 2}])}
    for _ in range(3):
        buttons, phase = d.step(pt(rt, **wall))
        assert phase == "travel" and not any(buttons.values())
    buttons, why = d.step(pt(rt, **wall))
    assert buttons is None and "objects 0,1 1,2" in why and "can_step" in why


def test_park_hands_over_on_a_grass_tile_or_in_a_battle():
    """Crystal live runs 2-3: the U1 grass walk refused the floor park tile's single grass neighbour; the
    faint leg now starts in the grass."""
    rt = lua()
    d = driver(rt, load(rt))
    step(rt, d, map_number=2, x=1, y=1)
    d.step(pt(rt, x=1, y=1, party={0: {"hp": 9, "status": PSN}}))
    fainted = {"party": {0: {"hp": 0, "status": 0}}, "poison_fainted": True}
    buttons, phase = d.step(pt(rt, x=1, y=2, **fainted))
    assert phase == "park" and buttons["Up"]
    buttons, phase = d.step(pt(rt, x=1, y=1, **fainted))
    assert phase == "poisoned"
    d2 = driver(rt, load(rt))
    step(rt, d2, map_number=2, x=1, y=1)
    d2.step(pt(rt, x=1, y=1, party={0: {"hp": 9, "status": PSN}}))
    d2.step(pt(rt, x=1, y=2, **fainted))
    buttons, phase = d2.step(pt(rt, battle_mode=1, overworld_ready=False, **fainted))
    assert phase == "poisoned"


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_a_committed_receipt_that_proves_poison_faint_carries_a_passing_poison_record(title):
    """The committed PHYSICAL receipt re-checked through the gate's own pure rules (and the shipped copy is
    byte-identical)."""
    import json
    path = ROOT / f"tests/fixtures/gen2/receipts/{title}.engine_sites.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert path.read_bytes() == (ROOT / f"data/games/gen2_{title}/receipts/{title}.engine_sites.json").read_bytes()
    if "poison_faint" not in receipt["proven"]:
        pytest.skip(f"{title} does not prove poison_faint yet")
    rt = lua()
    F = frame_align(rt)
    p = receipt["poison_alignment"]
    assert F.poison_problem(table(rt, p), p["psn_mask"]) is None
    assert F.poison_emission_problem(table(rt, {"events": lua_list([p["model_event"]])}), table(rt, p)) is None
    assert p["psn_mask"] == PSN and receipt["evidence_level"] == "PHYSICAL"


def test_a_phantom_object_on_the_only_aisle_is_walked_through():
    rt = lua()
    d = driver(rt, load(rt))
    buttons, phase = d.step(pt(rt, map_number=1, x=0, y=2, blocked=lua_list([{"x": 0, "y": 1}, {"x": 1, "y": 2}])))
    assert phase == "travel" and buttons["Up"]


TRAINER_FACTS = dict(FACTS, trainer={"tile": {"x": 3, "y": 1}, "avoid": lua_list([])})


def trainer_driver(rt, PI):
    F = rt.eval("{walk_direction=function() return 'Left' end}")
    return PI.driver(F, table(rt, TRAINER_FACTS), table(rt, {"moves": lua_list(["GROWL", "LEER"])}))


def test_a_trainer_hunt_walks_into_the_sight_line_and_waits():
    rt = lua()
    d = trainer_driver(rt, load(rt))
    buttons, phase = d.step(pt(rt, map_number=2, x=1, y=0))
    assert phase == "hunt" and buttons["Right"]
    buttons, phase = d.step(pt(rt, map_number=2, x=3, y=1))
    assert phase == "hunt" and not any(buttons.values())


def test_trainer_battles_fight_non_stings_and_stall_a_sting_until_poisoned():
    rt = lua()
    d = trainer_driver(rt, load(rt))
    d.step(pt(rt, map_number=2, x=1, y=0))
    fight = {"battle_mode": 2, "active_slot": 0, "active_hp": 20, "foe_sting": False, "overworld_ready": False}
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **fight)[0] == ["A"]                          # FIGHT, no RUN
    assert step(rt, d, ui=ui("move_menu", ["LEER", "SCRATCH"]), **fight)[0] == ["Down"]              # to SCRATCH
    assert step(rt, d, ui=ui("move_menu", ["LEER", "SCRATCH"], 2), **fight)[0] == ["A"]
    assert step(rt, d, ui=ui("yes_no", ["YES", "NO"], prompt="switch"), **fight)[0] == ["Down"]         # NO
    sting = dict(fight, foe_sting=True)
    assert step(rt, d, ui=ui("move_menu", ["LEER", "SCRATCH"]), **sting)[0] == ["A"]                   # LEER
    poisoned = dict(sting, active_psn=True)
    assert step(rt, d, ui=ui("move_menu", ["LEER", "SCRATCH"]), **poisoned)[0] == ["Down"]             # SCRATCH it
    assert step(rt, d, ui=ui("battle_menu", MENU, 4, 2), **dict(sting, active_hp=5))[0] == ["Up"]     # PKMN, not RUN


def test_a_trainer_battle_without_poison_is_a_stop_and_mom_gets_no():
    rt = lua()
    d = trainer_driver(rt, load(rt))
    d.step(pt(rt, map_number=2, x=1, y=0))
    d.step(pt(rt, battle_mode=2, map_number=2, x=3, y=1, overworld_ready=False))
    buttons, why = d.step(pt(rt, map_number=2, x=3, y=1))
    assert buttons is None and "without a poisoned party mon" in why
    d2 = trainer_driver(rt, load(rt))
    assert step(rt, d2, map_number=1, x=1, y=0, overworld_ready=False,
                ui=ui("yes_no", ["YES", "NO"], prompt="mom_save"))[0] == ["Down"]


def test_the_gate_fixture_list_mirrors_the_production_allow_list():
    rt = lua()
    F = frame_align(rt)
    S = rt.execute((ROOT / "lua/gen2/signals.lua").read_text(encoding="utf-8"))
    gate = {name: title for name, title in F.U1_FIXTURES.items()}
    production = {name: title for title, names in S.U1_FIXTURES.items() for name in names.values()}
    assert gate == production


def test_a_bumping_walk_releases_the_direction_so_map_events_run():
    """Gold run 1: holding Up into Mikey kept the step continuing; PlayerEvents (trainer sight) never ran."""
    rt = lua()
    PI = load(rt)
    d = driver(rt, PI)
    held = []
    for _ in range(2 * PI.BUMP_FRAMES):
        buttons, phase = d.step(pt(rt, map_number=1, x=1, y=0))
        held.append(any(buttons.values()))
    assert all(held[:PI.BUMP_FRAMES]) and not any(held[PI.BUMP_FRAMES:])
    buttons, phase = d.step(pt(rt, map_number=1, x=1, y=0))
    assert buttons["Left"]                                    # and tries again


def test_a_walk_bumping_into_an_object_talks_to_it():
    rt = lua()
    PI = load(rt)
    d = driver(rt, PI)
    blocked = lua_list([{"x": 0, "y": 0}])      # the exit tile itself is occupied
    pressed = []
    for _ in range(PI.BUMP_FRAMES + 1):
        buttons, phase = d.step(pt(rt, map_number=1, x=1, y=0, blocked=blocked))
        pressed.append(sorted(k for k, v in buttons.items() if v))
    assert pressed[0] == ["Left"] and pressed[PI.BUMP_FRAMES] == ["A"]


def test_a_ledge_tile_is_walkable_land_and_hops_two_tiles_in_its_direction():
    """Gold run 4: the Route 30 aisle north runs (5,24) -> the HOP_DOWN ledge (4,24) -> (4,23)."""
    rt = lua()
    PI = load(rt)
    # 2x5: (0,0) goal, (0,1) floor, (0,2) ledge (grid 0), (1,2) start, (0,4) floor below a wall (0,3)
    grid = [1, 0,
            1, 0,
            0, 1,
            0, 0,
            1, 0]
    m = a_map(1, grid=grid, width=2, height=5)
    m["ledges"] = lua_list([{"x": 0, "y": 2, "dirs": lua_list(["Down"])}])
    closed_left = dict(ALL, Left=False)          # the observer's passable set excludes HOP_*
    assert PI.step_toward(table(rt, m), table(rt, {"x": 1, "y": 2, "can_step": closed_left}),
                          table(rt, lua_list([{"x": 0, "y": 0}]))) == "Left"
    # standing on the ledge, Down jumps over the wall row to (0,4)
    assert PI.step_toward(table(rt, m), table(rt, {"x": 0, "y": 2, "can_step": ALL}),
                          table(rt, lua_list([{"x": 0, "y": 4}]))) == "Down"
    # without ledge facts the conservative grid has no path
    del m["ledges"]
    assert PI.step_toward(table(rt, m), table(rt, {"x": 1, "y": 2, "can_step": closed_left}),
                          table(rt, lua_list([{"x": 0, "y": 0}])))[0] is None


def test_the_heal_leg_talks_to_the_nurse_then_leaves_by_the_carpet():
    rt = lua()
    PI = load(rt)
    center = a_map(3, grid=[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], width=5, height=3)
    center["warps"] = lua_list([{"x": 1, "y": 2, "destination": "CITY", "carpet": "Down"}])
    facts = dict(FACTS, maps=dict(FACTS["maps"], C=center),
                 heal={"city": "A", "center": "C", "door": {"x": 0, "y": 0}, "stand": {"x": 3, "y": 1},
                       "exit": {"x": 1, "y": 2, "carpet": "Down"}})
    F = rt.eval("{walk_direction=function() return 'Left' end}")
    d = PI.driver(F, table(rt, facts), table(rt, {"moves": lua_list(["LEER"])}))
    hurt = {0: {"hp": 5, "status": 0, "max_hp": 20}}
    buttons, phase = d.step(pt(rt, map_number=1, x=2, y=0, party=hurt))
    assert phase == "travel" and buttons["Left"]                                  # to the door (0,0)
    assert step(rt, d, map_number=3, x=3, y=1, facing="Up", party=hurt)[0] == ["A"]
    for _ in range(12):                                                           # the talk press's hold + release
        d.step(pt(rt, map_number=3, x=3, y=1, facing="Up", party=hurt))
    assert step(rt, d, map_number=3, x=3, y=1, facing="Up", overworld_ready=False, party=hurt,
                ui=ui("yes_no", ["YES", "NO"], prompt="nurse_heal"))[0] == ["A"]   # YES
    full = {0: {"hp": 20, "status": 0, "max_hp": 20}}
    d.step(pt(rt, map_number=3, x=3, y=1, party=full))                            # the press's release frame
    buttons, phase = d.step(pt(rt, map_number=3, x=3, y=1, party=full))
    assert buttons["Down"] or buttons["Left"]                                     # heading for the carpet
    assert step(rt, d, map_number=3, x=1, y=2, party=full)[0] == ["Down"]
    for _ in range(12):                                                           # the carpet press's hold + release
        d.step(pt(rt, map_number=3, x=1, y=2, party=full))
    buttons, phase = d.step(pt(rt, map_number=1, x=1, y=0, party=full))
    assert buttons["Left"]                                                         # back on the route leg


def test_a_worn_mon_in_a_trainer_fight_hands_over_to_a_fitter_mate():
    rt = lua()
    d = trainer_driver(rt, load(rt))
    d.step(pt(rt, map_number=2, x=1, y=0))
    worn = {"battle_mode": 2, "active_slot": 0, "active_hp": 5, "foe_sting": False, "overworld_ready": False}
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **worn)[0] == ["Right"]                       # PKMN
    alone = dict(worn, party={0: {"hp": 5, "status": 0}, 1: {"hp": 3, "status": 0}})
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **alone)[0] == ["A"]                          # FIGHT on


def test_a_worn_party_on_the_way_north_goes_back_for_another_heal():
    """Gold U1f run 1: Mikey and a spinning Don wore the party down after the first heal."""
    rt = lua()
    PI = load(rt)
    center = a_map(3, grid=[1] * 15, width=5, height=3)
    center["warps"] = lua_list([{"x": 1, "y": 2, "destination": "CITY", "carpet": "Down"}])
    back = lua_list([{"map": "A", "side": "Down", "exits": lua_list([{"x": 2, "y": 2}])}])
    facts = dict(FACTS, maps=dict(FACTS["maps"], C=center, K=a_map(4)),
                 heal={"city": "K", "center": "C", "door": {"x": 0, "y": 0}, "stand": {"x": 3, "y": 1},
                       "exit": {"x": 1, "y": 2, "carpet": "Down"}, "back": back})
    F = rt.eval("{walk_direction=function() return 'Left' end}")
    d = PI.driver(F, table(rt, facts), table(rt, {"moves": lua_list(["LEER"])}))
    full = {0: {"hp": 20, "status": 0, "max_hp": 20}}
    # first heal: talk, full HP, leave
    assert step(rt, d, map_number=3, x=3, y=1, facing="Up", party={0: {"hp": 5, "status": 0, "max_hp": 20}})[0] == ["A"]
    for _ in range(12):
        d.step(pt(rt, map_number=3, x=3, y=1, party=full))
    d.step(pt(rt, map_number=3, x=3, y=1, party=full))
    # on the route leg map A with the lead at 5/20: walk the back edge (2,2) instead of the exit (0,0)
    worn = {0: {"hp": 5, "status": 0, "max_hp": 20}}
    buttons, phase = d.step(pt(rt, map_number=1, x=2, y=1, party=worn))
    assert phase == "travel" and buttons["Down"]
    buttons, phase = d.step(pt(rt, map_number=1, x=2, y=2, party=worn))
    assert buttons["Down"]                                                 # cross south
    buttons, phase = d.step(pt(rt, map_number=1, x=2, y=1, party=full))
    assert buttons["Down"]                                   # once due, the heal stands until the nurse
