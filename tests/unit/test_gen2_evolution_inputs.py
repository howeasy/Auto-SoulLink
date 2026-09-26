"""Card EVO-U1: the pure evolution leg (lua/tests/gen2_evolution_inputs.lua). No emulator: synthetic points in,
buttons out; plus the frame-align gate's evolution record rules (F.evolution_problem / F.evolution_emission_problem)."""
from __future__ import annotations

from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
EVOLUTION = ROOT / "lua/tests/gen2_evolution_inputs.lua"
POISON = ROOT / "lua/tests/gen2_poison_inputs.lua"
ALIGN = ROOT / "lua/tests/gen2_frame_align.lua"
ALL = {"Up": True, "Down": True, "Left": True, "Right": True}
MENU = ["FIGHT", "<PK><MN>", "PACK", "RUN"]
CATERPIE, METAPOD, TOTODILE, PIDGEY = 10, 11, 158, 16


def lua_list(values):
    return {i + 1: v for i, v in enumerate(values)}


def a_map(number, grid, width=5, height=3):
    return {"map_group": 1, "map_number": number, "map_const": f"M{number}", "width": width, "height": height,
            "grid": lua_list(grid), "warps": {}}


FLOOR = [1] * 15
# hunt map 2: row 0 floor, row 1 grass except x=4, row 2 floor (the city is south of it)
HUNT = [1, 1, 1, 1, 1, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1]
FACTS = {"maps": {"C": a_map(3, FLOOR), "Y": a_map(1, FLOOR), "H": a_map(2, HUNT)},
         "center": "C", "city": "Y", "hunt": "H", "hunt_grass": lua_list([{"x": 1, "y": 1}]),
         "door": {"x": 0, "y": 2}, "exit": {"x": 1, "y": 2, "carpet": "Down"}, "stand": {"x": 3, "y": 1},
         "north": {"exits": lua_list([{"x": 2, "y": 0}]), "side": "Up"},
         "south": {"exits": lua_list([{"x": 2, "y": 2}]), "side": "Down"},
         "target": CATERPIE, "evolves_to": METAPOD, "poison_sting": 40, "run_from_sting": True,
         "damaging_ids": {"33": True, "10": True, "40": True}}


def setup():
    rt = LuaRuntime(unpack_returned_tuples=True)
    PI = rt.execute(POISON.read_text(encoding="utf-8"))
    EV = rt.execute(EVOLUTION.read_text(encoding="utf-8"))
    F = rt.eval("{walk_direction=function() return 'Left' end, "
                "TOWARD_BALLS={pack_items='Right', pack_key='Left', pack_tmhm='Right'}}")
    d = EV.driver(F, PI, rt.table_from(FACTS, recursive=True))
    return rt, EV, d


def mon(species, hp=20, max_hp=20, status=0, pp=20):
    return {"species": species, "hp": hp, "max_hp": max_hp, "status": status, "level": 3, "attack_pp": pp}


LEAD = mon(TOTODILE)
CAUGHT = {0: LEAD, 1: mon(CATERPIE, 16, 16)}


def pt(rt, **fields):
    base = {"map_group": 1, "map_number": 2, "x": 1, "y": 1, "can_step": ALL, "battle_mode": 0,
            "overworld_ready": True, "input_ready": True, "party": {0: LEAD}}
    base.update(fields)
    return rt.table_from(base, recursive=True)


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


def fight(**extra):
    return dict({"battle_mode": 1, "overworld_ready": False, "active_slot": 0, "active_hp": 20, "active_max": 20,
                 "foe_species": PIDGEY, "foe_full": True, "foe_sting": False}, **extra)


def test_the_leg_leaves_the_center_crosses_the_city_and_oscillates_in_the_grass():
    rt, _, d = setup()
    assert step(rt, d, map_number=3, x=1, y=2) == (["Down"], "to-grass")            # the exit carpet
    for _ in range(12):
        d.step(pt(rt, map_number=3, x=1, y=2))
    assert step(rt, d, map_number=1, x=2, y=0) == (["Up"], "to-grass")             # on the north edge: cross
    assert step(rt, d, map_number=2, x=1, y=0)[0] == ["Down"]                      # hunt map: onto the grass
    assert step(rt, d, map_number=2, x=1, y=1) == (["Left"], "hunt")


def test_before_the_catch_other_species_run_and_the_target_is_weakened_then_balled():
    rt, _, d = setup()
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **fight())[0] == ["Right"]       # toward RUN
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **fight(foe_species=CATERPIE))[0] == ["A"]   # FIGHT
    assert step(rt, d, ui=ui("move_menu", ["SCRATCH", "LEER"]), **fight(foe_species=CATERPIE))[0] == ["A"]
    hurt = fight(foe_species=CATERPIE, foe_full=False)
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **hurt)[0] == ["Down"]            # toward PACK
    assert step(rt, d, ui=ui("pack_items"), **hurt)[0] == ["Right"]
    assert step(rt, d, ui=ui("pack_balls"), ball_cursor="ball", **hurt)[0] == ["A"]
    assert step(rt, d, ui=ui("yes_no", ["YES", "NO"], prompt="catch_nickname"), **hurt)[0] == ["Down"]


def test_after_the_catch_the_target_is_sent_out_once_then_the_lead_fights():
    rt, _, d = setup()
    b = fight(party=CAUGHT)
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **b)[0] == ["Right"]              # PKMN cell
    assert step(rt, d, ui=ui("battle_party"), party_cursor=0, **b)[0] == ["Down"]
    assert step(rt, d, ui=ui("battle_party"), party_cursor=1, **b)[0] == ["A"]
    assert step(rt, d, ui=ui("battle_mon_menu", ["SWITCH", "STATS", "CANCEL"]), **b)[0] == ["A"]
    t = fight(party=CAUGHT, active_slot=1, active_hp=16, active_max=16)
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **t)[0] == ["Right"]             # sent: straight back
    assert step(rt, d, ui=ui("battle_party"), party_cursor=1, **t)[0] == ["Up"]
    lead = fight(party={0: LEAD, 1: mon(CATERPIE, 12, 16)})
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **lead)[0] == ["A"]               # the lead fights it out
    alone = fight(party={0: mon(TOTODILE, 3), 1: mon(CATERPIE, 16, 16)}, active_slot=1, active_hp=16, active_max=16)
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **alone)[0] == ["A"]              # worn lead: target FIGHTs
    assert step(rt, d, ui=ui("move_menu", ["STRING SHOT", "TACKLE"]), **alone)[0] == ["Down"]  # its damaging move
    nobody = fight(party={0: mon(TOTODILE, 3), 1: mon(CATERPIE, 5, 16)}, active_slot=1, active_hp=5, active_max=16)
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **nobody)[0] == ["Right"]         # toward RUN
    assert step(rt, d, ui=ui("battle_menu", MENU, 2, 2), **nobody)[0] == ["Down"]


def test_a_sting_foe_is_run_from_and_an_empty_damaging_pp_backs_out():
    rt, _, d = setup()
    assert step(rt, d, ui=ui("battle_menu", MENU, 2, 2), **fight(party=CAUGHT, foe_sting=True))[0] == ["Down"]
    t = fight(party=CAUGHT, active_slot=1, active_hp=16, active_max=16, active_pp=lua_list([0, 0]))
    assert step(rt, d, ui=ui("move_menu", ["TACKLE", "STRING SHOT"]), **t)[0] == ["B"]


def test_a_worn_party_walks_to_the_nurse_and_back():
    rt, _, d = setup()
    hurt = {0: LEAD, 1: mon(CATERPIE, 6, 16)}
    assert step(rt, d, map_number=2, x=2, y=1, party=hurt) == (["Down"], "heal")          # toward the south edge
    assert step(rt, d, map_number=2, x=2, y=2, party=hurt) == (["Down"], "heal")          # on it: cross
    assert step(rt, d, map_number=1, x=0, y=1, party=hurt)[0] == ["Down"]                  # to the door
    assert step(rt, d, map_number=3, x=3, y=1, facing="Up", party=hurt)[0] == ["A"]
    for _ in range(12):
        d.step(pt(rt, map_number=3, x=3, y=1, facing="Up", party=hurt))
    assert step(rt, d, map_number=3, x=3, y=1, overworld_ready=False, party=hurt,
                ui=ui("yes_no", ["YES", "NO"], prompt="nurse_heal"))[0] == ["A"]
    d.step(pt(rt, map_number=3, x=3, y=1, party=CAUGHT))
    assert step(rt, d, map_number=3, x=3, y=1, party=CAUGHT)[1] == "to-grass"
    no_pp = {0: LEAD, 1: mon(CATERPIE, 16, 16, pp=2)}
    assert step(rt, d, map_number=2, x=2, y=1, party=no_pp)[1] == "heal"                  # PP out: heal too


def test_the_evolution_is_never_cancelled_and_ends_the_leg_on_the_overworld():
    rt, _, d = setup()
    evolving = fight(party=CAUGHT, active_slot=1)
    assert step(rt, d, **evolving)[0] == []                                                # no UI origin: idle
    assert step(rt, d, ui=ui("text"), **evolving)[0] == ["A"]                              # A, never B
    done = {0: LEAD, 1: mon(METAPOD, 16, 20)}
    assert step(rt, d, party=done) == ([], "evolved")


def test_the_whole_party_down_at_use_next_is_a_stop():
    rt, _, d = setup()
    down = fight(party={0: mon(TOTODILE, 0), 1: mon(CATERPIE, 0, 16)}, active_slot=1)
    buttons, why = d.step(pt(rt, ui=ui("yes_no", ["YES", "NO"], prompt="next_mon"), **down))
    assert buttons is None and "whole party" in why


def frame_align():
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.globals().SLINK_GEN2_GATE_LIBRARY = True
    return rt, rt.execute(ALIGN.read_text(encoding="utf-8"))


OLD_BY_NEW = {"11": CATERPIE}
GOOD = {"armed": 50, "callback": 50, "slot": 1, "party_count": 2, "a": METAPOD, "hl": 0xDCD8 + 1,
        "list_addr": 0xDCD8 + 1, "list_species": METAPOD, "struct_species": METAPOD, "dvs": 0xABCD, "ot": 0x1234,
        "link_mode": 0, "battle_mode": 1, "pre_list_species": CATERPIE}
EVENT = {"kind": "key_change", "reason": "evolution", "site_id": "evolution_species_published", "slot": 1,
         "old_key": "ABCD:1234:0A", "new_key": "ABCD:1234:0B"}


def test_the_evolution_rule_accepts_the_same_frame_record_and_refuses_each_break():
    rt, F = frame_align()
    table = lambda v: rt.table_from(v, recursive=True)  # noqa: E731
    assert F.evolution_problem(table(GOOD), table(OLD_BY_NEW)) is None
    for field, value, match in [("callback", 51, "armed"), ("slot", 2, "party slot"), ("link_mode", 1, "link"),
                                ("list_species", CATERPIE, "published species"), ("hl", 0xDCD8, "HL"),
                                ("pre_list_species", METAPOD, "pre-evolution")]:
        assert match in F.evolution_problem(table({**GOOD, field: value}), table(OLD_BY_NEW))
    assert "snapshot" in F.evolution_problem(None, table(OLD_BY_NEW))


def test_the_emission_rule_needs_one_key_change_with_the_snapshot_keys():
    rt, F = frame_align()
    table = lambda v: rt.table_from(v, recursive=True)  # noqa: E731
    good, old = table(GOOD), table(OLD_BY_NEW)
    assert F.evolution_emission_problem(table({"events": lua_list([EVENT])}), good, old) is None
    assert "not 1" in F.evolution_emission_problem(table({"events": {}}), good, old)
    assert "not an evolution" in F.evolution_emission_problem(table({"events": lua_list([{**EVENT, "reason": "trade"}])}), good, old)
    assert "another mon" in F.evolution_emission_problem(table({"events": lua_list([{**EVENT, "old_key": "ABCD:1234:0B"}])}), good, old)


def test_the_evolution_site_is_expected_last_only_when_asked():
    _, F = frame_align()
    with_evo = list(F.expect(True, True, True).values())
    assert with_evo[-1] == "evolution_species_published" and with_evo[:-1] == list(F.expect(True, True).values())


def test_a_party_due_at_the_nurse_runs_from_a_battle_on_the_way():
    rt, _, d = setup()
    hurt = {0: LEAD, 1: mon(CATERPIE, 6, 16)}
    assert step(rt, d, map_number=2, x=2, y=1, party=hurt)[1] == "heal"
    assert step(rt, d, ui=ui("battle_menu", MENU, 1, 2), **fight(party=hurt))[0] == ["Right"]   # toward RUN, no switch
    assert step(rt, d, ui=ui("battle_menu", MENU, 2, 2), **fight(party=hurt))[0] == ["Down"]
