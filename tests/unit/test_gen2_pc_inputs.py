"""Card gen2-u1f-pc: the pure Bill's PC leg (lua/tests/gen2_pc_inputs.lua) and the frame-align gate's whiteout and
U1f emission rules (lua/tests/gen2_frame_align.lua). No emulator: synthetic points in, buttons out."""
from __future__ import annotations

from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
PCI = ROOT / "lua/tests/gen2_pc_inputs.lua"
PI = ROOT / "lua/tests/gen2_poison_inputs.lua"
ALIGN = ROOT / "lua/tests/gen2_frame_align.lua"
ALL = {"Up": True, "Down": True, "Left": True, "Right": True}


def lua_list(values):
    return {i + 1: v for i, v in enumerate(values)}


def a_map(number, width=5, height=3, grid=None):
    return {"map_group": 1, "map_number": number, "map_const": f"M{number}", "width": width, "height": height,
            "grid": lua_list(grid or [1] * (width * height)), "warps": {}}


FACTS = {"maps": {"R": a_map(1, grid=[1, 1, 1, 1, 1, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1]), "C": a_map(2)},
         "to_grass": {"R": {"kind": "grass"}},
         "to_pc": {"R": {"kind": "edge", "side": "Left", "exits": lua_list([{"x": 0, "y": 0}])}, "C": {"kind": "pc"}},
         "pc_stand": {"x": 2, "y": 1}}


def setup(mode):
    rt = LuaRuntime(unpack_returned_tuples=True)
    pi = rt.execute(PI.read_text(encoding="utf-8"))
    pc = rt.execute(PCI.read_text(encoding="utf-8"))
    return rt, pc.driver(pi, rt.table_from(FACTS, recursive=True), rt.table_from({"mode": mode}))


def pt(rt, **fields):
    base = {"map_group": 1, "map_number": 2, "x": 2, "y": 1, "can_step": ALL, "battle_mode": 0, "facing": "Up",
            "overworld_ready": True, "input_ready": True, "party_count": 3, "box_count": 0, "cur_box": 0, "pc_cursor": 0}
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
    if pressed and (fields.get("ui") or phase == "pc"):
        for _ in range(12):
            d.step(pt(rt, **fields))
    return pressed, phase


TOP = ["BILL's PC", "GOLD's PC", "TURN OFF"]
BILLS = ["WITHDRAW <PK><MN>", "DEPOSIT <PK><MN>", "CHANGE BOX", "MOVE <PK><MN> W/O MAIL", "SEE YA!"]


def test_grass_mode_walks_to_grass_or_hands_a_battle_over():
    rt, d = setup("grass")
    assert d.step(pt(rt, map_number=1, x=0, y=2))[0]["Up"]
    assert d.step(pt(rt, map_number=1, x=0, y=1))[1] == "grass"
    rt, d = setup("grass")
    assert d.step(pt(rt, map_number=1, battle_mode=1, overworld_ready=False))[1] == "grass"


def test_pc_mode_crosses_to_the_center_and_uses_the_pc_from_below():
    rt, d = setup("pc")
    assert d.step(pt(rt, map_number=1, x=0, y=0))[0]["Left"]
    assert step(rt, d, facing="Down") == (["Up"], "pc")
    assert step(rt, d) == (["A"], "pc")


def test_the_six_operations_follow_their_ram_effects():
    rt, d = setup("pc")
    step(rt, d)                                                        # at the PC
    assert step(rt, d, overworld_ready=False, ui=ui("pc_top", TOP))[0] == ["A"]                    # BILL's PC
    assert step(rt, d, overworld_ready=False, ui=ui("bills_pc", BILLS))[0] == ["Down"]             # to DEPOSIT
    assert step(rt, d, overworld_ready=False, ui=ui("bills_pc", BILLS, 2))[0] == ["A"]
    assert step(rt, d, overworld_ready=False, ui=ui("deposit_list"), pc_cursor=0)[0] == ["Down"]   # slot 1
    assert step(rt, d, overworld_ready=False, ui=ui("deposit_list"), pc_cursor=1)[0] == ["A"]
    assert step(rt, d, overworld_ready=False, ui=ui("deposit_menu", ["DEPOSIT", "STATS", "RELEASE", "CANCEL"]))[0] == ["A"]
    # deposited: party 2, box 1 -> withdraw the last box slot (0)
    after = {"party_count": 2, "box_count": 1, "overworld_ready": False}
    assert step(rt, d, ui=ui("deposit_list"), **after)[0] == ["B"]
    assert step(rt, d, ui=ui("bills_pc", BILLS, 2), **after)[0] == ["Up"]
    assert step(rt, d, ui=ui("withdraw_list"), pc_cursor=0, **after)[0] == ["A"]
    assert step(rt, d, ui=ui("withdraw_menu", ["WITHDRAW", "STATS", "RELEASE", "CANCEL"]), **after)[0] == ["A"]
    # withdrawn: party 3, box 0 -> CHANGE BOX to BOX2
    back = {"party_count": 3, "box_count": 0, "overworld_ready": False}
    assert step(rt, d, ui=ui("withdraw_list"), **back)[0] == ["B"]
    assert step(rt, d, ui=ui("bills_pc", BILLS, 1), **back)[0] == ["Down"]
    assert step(rt, d, ui=ui("box_list", ["BOX1", "BOX2", "BOX3", "BOX4"]), **back)[0] == ["Down"]
    assert step(rt, d, ui=ui("box_list", ["BOX1", "BOX2", "BOX3", "BOX4"], 2), **back)[0] == ["A"]
    assert step(rt, d, ui=ui("box_menu", ["SWITCH", "NAME", "PRINT", "QUIT"]), **back)[0] == ["A"]
    assert step(rt, d, ui=ui("yes_no", ["YES", "NO"], prompt="change_box_save"), **back)[0] == ["A"]
    # BOX2: deposit party slot 2
    box2 = dict(back, cur_box=1)
    assert step(rt, d, ui=ui("box_list", ["BOX1", "BOX2", "BOX3", "BOX4"], 2), **box2)[0] == ["B"]
    assert step(rt, d, ui=ui("bills_pc", BILLS, 3), **box2)[0] == ["Up"]
    assert step(rt, d, ui=ui("deposit_list"), pc_cursor=1, **box2)[0] == ["Down"]
    assert step(rt, d, ui=ui("deposit_list"), pc_cursor=2, **box2)[0] == ["A"]
    # deposited into BOX2 -> release it from the box
    rel = dict(box2, party_count=2, box_count=1)
    assert step(rt, d, ui=ui("deposit_list"), **rel)[0] == ["B"]
    assert step(rt, d, ui=ui("withdraw_list"), pc_cursor=0, **rel)[0] == ["A"]
    assert step(rt, d, ui=ui("withdraw_menu", ["WITHDRAW", "STATS", "RELEASE", "CANCEL"]), **rel)[0] == ["Down"]
    assert step(rt, d, ui=ui("yes_no", ["YES", "NO"], prompt="release"), **rel)[0] == ["A"]
    # released from the box -> release party slot 1
    last = dict(rel, box_count=0)
    assert step(rt, d, ui=ui("withdraw_list"), **last)[0] == ["B"]
    assert step(rt, d, ui=ui("bills_pc", BILLS, 1), **last)[0] == ["Down"]
    assert step(rt, d, ui=ui("deposit_list"), pc_cursor=1, **last)[0] == ["A"]
    assert step(rt, d, ui=ui("deposit_menu", ["DEPOSIT", "STATS", "RELEASE", "CANCEL"], 3), **last)[0] == ["A"]
    # done: SEE YA!, TURN OFF, back on the overworld
    done = dict(last, party_count=1)
    assert step(rt, d, ui=ui("deposit_list"), **done)[0] == ["B"]
    assert step(rt, d, ui=ui("bills_pc", BILLS, 2), **done)[0] == ["Down"]
    assert step(rt, d, ui=ui("pc_top", TOP), **done)[0] == ["Down"]
    buttons, phase = d.step(pt(rt, party_count=1, cur_box=1))
    assert phase == "pc-done"


def test_an_unmapped_pc_prompt_is_refused():
    rt, d = setup("pc")
    step(rt, d)
    buttons, why = d.step(pt(rt, overworld_ready=False, ui=ui("yes_no", ["YES", "NO"], prompt="mystery")))
    assert buttons is None and "unmapped PC yes/no" in why


def frame_align():
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.globals().SLINK_GEN2_GATE_LIBRARY = True
    return rt, rt.execute(ALIGN.read_text(encoding="utf-8"))


GOOD = {"armed": 900, "callback": 900, "seq": 50, "de": 27, "party_count": 2, "party_hp": [0, 0], "healed_frame": 1200}


@pytest.mark.parametrize("change,match", [
    ({}, None), ({"callback": 901}, "callback frame"), ({"de": 26}, "DE != 27"), ({"party_hp": [0, 3]}, "had HP"),
    ({"party_hp": [0]}, "party snapshot"), ({"healed_frame": 899}, "heal"), ({"seq": 40}, "closing battle faint")])
def test_whiteout_rule(change, match):
    rt, F = frame_align()
    record = dict(GOOD, **change)
    record["party_hp"] = lua_list(record["party_hp"])
    why = F.whiteout_problem(rt.table_from(record, recursive=True), 45)
    assert (why is None) if match is None else (match in why)


EVENTS = [{"kind": "whiteout"}, {"kind": "party_to_box"}, {"kind": "box_to_party"}, {"kind": "box_change"},
          {"kind": "party_to_box"}, {"kind": "pc_release", "collection": "box"},
          {"kind": "pc_release", "collection": "party"}]


@pytest.mark.parametrize("events,match", [
    (EVENTS, None), (EVENTS[:-1], "pc_release_party"), (EVENTS + [{"kind": "whiteout"}], "whiteout"),
    (EVENTS + [{"kind": "faint"}], "unexpected faint")])
def test_u1f_emission_rule(events, match):
    rt, F = frame_align()
    why = F.u1f_emission_problem(rt.table_from({"events": lua_list(events)}, recursive=True))
    assert (why is None) if match is None else (match in why)


def test_the_u1f_expect_order_appends_the_pc_sites_after_the_faints():
    rt, F = frame_align()
    names = list(F.expect(True, True).values())
    assert names[:len(F.EXPECT) + 1] == list(F.expect(True).values())
    assert names[-10:] == list(F.U1F_SITES.values())


def test_the_second_catch_weakens_a_full_hp_foe_once_then_throws():
    rt, F = frame_align()
    d = F.driver(rt.table_from(a_map(1), recursive=True),
                 rt.table_from({"weaken": True, "passive": lua_list(["LEER", "GROWL"])}, recursive=True))
    menu = ui("battle_menu", ["FIGHT", "<PK><MN>", "PACK", "RUN"], 1, 2)
    base = {"battle_mode": 1, "input_ready": True, "hits": {}, "probe_hits": {"capture_party": 0}}

    def go(**fields):
        p = rt.table_from(dict(base, **fields), recursive=True)
        buttons, phase = d.step(p)
        assert buttons is not None, phase
        for _ in range(12):
            d.step(p)
        return sorted(k for k, v in buttons.items() if v)

    assert go(ui=menu, foe_full=True) == ["A"]                                            # FIGHT
    assert go(ui=ui("move_menu", ["LEER", "SCRATCH"]), foe_full=True) == ["Down"]         # not LEER
    assert go(ui=ui("move_menu", ["LEER", "SCRATCH"], 2), foe_full=True) == ["A"]
    assert go(ui=menu, foe_full=False) == ["Down"]                                        # PACK now
    plain = F.driver(rt.table_from(a_map(1), recursive=True))
    p = rt.table_from(dict(base, ui=menu, foe_full=True), recursive=True)
    assert sorted(k for k, v in plain.step(p)[0].items() if v) == ["Down"]              # U1d path: PACK


def test_a_stale_promptless_yes_no_after_a_release_is_waited_out():
    rt, d = setup("pc")
    step(rt, d)
    buttons, phase = d.step(pt(rt, overworld_ready=False, ui=ui("yes_no", ["WITHDRAW", "STATS", "RELEASE", "CANCEL"], 3)))
    assert buttons is not None and not any(buttons.values()) and phase == "pc"
