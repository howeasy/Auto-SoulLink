"""The two driver-facts tables are one shape with foundation-specific values (P3b-e).

`lua/tests/gen1_pure_facts.lua` (pureRGB) and `lua/tests/gen1_rb_facts.lua` (vanilla Red/Blue) are
what the shared R/B harness drivers read every game literal from: `gen1_scripted_play.P.new` loads
one into `expected.facts`, and each driver takes it from there (`M.with_facts`, or `o.facts` for the
battle driver). A driver that still carries a literal cannot be pointed at another foundation, and a
twin that drifts from the pure file would silently hand a lane the other foundation's numbers.

Pure Lua through lupa: no emulator, no ROM, no server.
"""

from __future__ import annotations

import os
import re

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_TESTS = os.path.join(_REPO, "lua", "tests")
PURE = "gen1_pure_facts.lua"
RB = "gen1_rb_facts.lua"

# The drivers that took their literals out of the facts table (P3b-e). gen1_y_ball_gate_inputs.lua
# (Yellow's lab driver) is now in it: its 225/0x2d went to F.TRAINER.OPP_RIVAL1 / F.MOVE.GROWL.
DRIVERS = (
    "gen1_rb_ball_gate_inputs.lua",
    "gen1_rb_parcel_inputs.lua",
    "gen1_rb_route1_inputs.lua",
    "gen1_rb_save_inputs.lua",
    "gen1_rb_pc_inputs.lua",
    "gen1_rb_forest_inputs.lua",
    "gen1_rb_route22_inputs.lua",
    "gen1_rb_hunt_inputs.lua",
    "gen1_rb_mart_signature.lua",
    "gen1_rb_point_fields.lua",
    "gen1_battle_driver.lua",
    "gen1_scripted_play.lua",
    # the P3b-e tail: Yellow's lab driver, the Center route, the cold-trade planner, the shared
    # input shapes and the gate library.
    "gen1_y_ball_gate_inputs.lua",
    "gen1_rb_center_inputs.lua",
    "gen1_cold_trade_inputs.lua",
    "gen1_inputs_common.lua",
    "gen1_gate.lua",
)

# Literals that must not survive in those files: the rival opponent id, the single battle-core bank
# filter, the vanilla START-menu arithmetic, the Red-list fallback in the Mart signature and the
# item-list ball scan. Matched against code with comments stripped, so a comment may still name them.
REPLACED = {
    "rival opponent id": r"\b225\b",
    "battle-bank filter": r"==\s*0x0F",
    "START menu count": r"save\s*\+\s*3",
    "Mart Red-list fallback": r"INVENTORY\.red",
    "item-list ball scan": r"id\s*>=\s*1\s+and\s+id\s*<=\s*4",
    "Growl's move id": r"0x2d",
    "16-frame tap cadence": r"%\s*16\s*<\s*2",
}

# Exactly the keys the two tables disagree on. `BANKS.<hook>` is the engine-signal site bank:
# pureRGB moved EndOfBattle ($04 -> $3A) and TryEvolvingMon ($0E -> $2C), and 23 of its sites are
# hooks a vanilla cartridge does not have at all (the twin carries `false` for those). The rest are
# the foundations' own values: the parcel flag pureRGB deleted, its HYPER_BALL, the START-menu
# row-index change, and the renumbered rival opponent id.
EXPECTED_DELTA = frozenset({
    "MENU.BAG.watched",
    "BANKS.apex_commit",
    "BANKS.apex_preflight",
    "BANKS.apex_recalc_call",
    "BANKS.battle_end",
    "BANKS.cable_partial_save",
    "BANKS.cable_trade_add",
    "BANKS.cable_trade_remove",
    "BANKS.capture_box_begin",
    "BANKS.capture_box_end",
    "BANKS.capture_party_begin",
    "BANKS.capture_party_end",
    "BANKS.changebox_full_save",
    "BANKS.daycare_withdraw",
    "BANKS.evolve",
    "BANKS.evolve_species_store",
    "BANKS.npc_trade_add",
    "BANKS.npc_trade_done",
    "BANKS.npc_trade_remove",
    "BANKS.pc_deposit",
    "BANKS.pc_release",
    "BANKS.pc_withdraw",
    "BANKS.trainer_staging",
    "BANKS.transform",
    "BANKS.transform_hp_hi",
    "BANKS.transform_hp_lo",
    "CATCH.hunt_ball_max",
    "EVENT.OAK_GOT_PARCEL",
    "EVENT.OAK_GOT_PARCEL_EXISTS",
    "EVENT.OAK_GOT_PARCEL_SUBSTITUTE",
    "ITEM.BALL_IDS",
    "MENU.START.max_minus_save",
    "TRAINER.OPP_ID_OFFSET",
    "TRAINER.OPP_RIVAL1",
})


@pytest.fixture(scope="module")
def lua():
    return LuaRuntime(unpack_returned_tuples=True)


def _dofile(lua, name):
    path = os.path.join(_TESTS, name).replace(chr(92), "/")
    return lua.execute(f'return dofile("{path}")')


def _facts(lua, name):
    return _dofile(lua, name)


def _canon(value):
    """A lupa table as plain Python data (strings key -> dict, else a list), scalars as they are.

    `table` is a lupa Lua table, so `.keys()` is the Lua iterator, not `dict.keys` (SIM118 is a
    false positive on this file's lupa calls).
    """
    if not hasattr(value, "keys"):
        return value
    keys = list(value.keys())  # noqa: SIM118
    if any(isinstance(k, str) for k in keys):
        return {k: _canon(value[k]) for k in keys if isinstance(k, str)}
    return [_canon(value[k]) for k in keys]


def _leaves(table, prefix=""):
    """Leaf name -> canonical value, walking string keys only."""
    out = {}
    for key in table.keys():  # noqa: SIM118
        if not isinstance(key, str):
            continue
        value = table[key]
        path = f"{prefix}.{key}".lstrip(".")
        if isinstance(_canon(value), dict):
            out.update(_leaves(value, path))
        else:
            out[path] = _canon(value)
    return out


# ── shape ───────────────────────────────────────────────────────────────────────────────────────


def test_both_tables_carry_the_same_groups_and_leaf_names(lua):
    pure, rb = _dofile(lua, PURE), _dofile(lua, RB)
    groups = lambda t: {k for k in t.keys() if isinstance(k, str)}  # noqa: E731, SIM118
    assert groups(pure) == groups(rb)
    assert len(groups(pure)) == 16
    assert set(_leaves(pure)) == set(_leaves(rb))


def test_only_the_expected_keys_differ(lua):
    pure, rb = _leaves(_dofile(lua, PURE)), _leaves(_dofile(lua, RB))
    assert frozenset(k for k in pure if pure[k] != rb[k]) == EXPECTED_DELTA


@pytest.mark.parametrize(("key", "vanilla", "pure"), [
    ("TRAINER.OPP_RIVAL1", 225, 221),
    ("TRAINER.OPP_ID_OFFSET", 200, 197),
    ("EVENT.OAK_GOT_PARCEL", 56, 37),
    ("EVENT.OAK_GOT_PARCEL_EXISTS", True, False),
    ("CATCH.hunt_ball_max", 4, 5),
    ("MENU.START.max_minus_save", 3, 2),
])
def test_the_foundational_deltas(lua, key, vanilla, pure):
    *parents, leaf = key.split(".")
    nodes = (_dofile(lua, RB), _dofile(lua, PURE))
    for part in parents:
        nodes = tuple(node[part] for node in nodes)
    assert nodes[0][leaf] == vanilla
    assert nodes[1][leaf] == pure


def test_the_ball_sets_are_the_foundations_item_use_ball_dispatch(lua):
    rb, pure = _dofile(lua, RB), _dofile(lua, PURE)
    assert [rb["ITEM"]["BALL_IDS"][i] for i in range(1, 5)] == [1, 2, 3, 4]
    assert [pure["ITEM"]["BALL_IDS"][i] for i in range(1, 7)] == [1, 2, 3, 4, 5, 8]


@pytest.mark.parametrize("name", DRIVERS)
def test_no_replaced_literal_survives_in_the_drivers(name):
    with open(os.path.join(_TESTS, name), encoding="utf-8") as handle:
        text = handle.read()
    code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    for what, pattern in REPLACED.items():
        assert not re.search(pattern, code), f"{name}: {what} still inline"


def test_the_module_constants_are_populated_at_load(lua):
    """The lane's tables arrive through `with_facts`, which the drivers also call from `new` --
    but `duo_gen1_main` reads Route22.RIVAL1 (3036) and Forest.MAX_ENCOUNTERS (2804) BEFORE it
    builds those drivers, so the vanilla defaults have to be in place at dofile time."""
    assert _dofile(lua, "gen1_rb_route22_inputs.lua")["RIVAL1"] == 225
    assert _dofile(lua, "gen1_rb_forest_inputs.lua")["MAX_ENCOUNTERS"] == 60
    assert _dofile(lua, "gen1_rb_hunt_inputs.lua")["GRASS"][1][1] == 10
    assert _dofile(lua, "gen1_rb_route1_inputs.lua")["PARK"][1] == 10
    assert _dofile(lua, "gen1_rb_pc_inputs.lua")["OFF"]["list"] == 86


# ── behaviour: a driver follows the table it was handed, not the one it was born with ───────────


def _identity(lua, facts):
    return lua.table(player="a", run_id="r", rom_sha1="s", context_generation=1,
                     physical_instance="p", title="red", facts=facts)


def _handshake(lua):
    return lua.table(ready=True, run_id="r", player="a", rom_sha1="s", context_generation=1,
                     physical_instance="p")


def _status(lua):
    return lua.table(observation_loop=True,
                     context=lua.table(context_generation=1, physical_instance="p"),
                     host=lua.table(owner_id="p", held=False),
                     runtime=lua.table(connected=True, session_state="admitted", failed=False))


def _step(lua, driver, point, frame=10):
    return driver.step(_handshake(lua), _status(lua), point, frame)


def _lab_battle_point(lua, facts, opponent):
    return lua.table(map=facts["MAP"]["OAKS_LAB"], x=5, y=5, party_count=1, battle=2,
                     opponent=opponent, menu_y=12, menu_x=5, menu_max=3, menu_index=2, move2=0x2D,
                     move2_pp=10, text_box=0x0B, joy_ignore=0, font_loaded=False, lab_script=0,
                     party_hp=20, battle_result=0)


def test_the_lab_rival_assertion_follows_the_table(lua):
    """The vanilla id passes on the twin; a table that says otherwise refuses it, and the mutated
    id passes. One instance per step: a driver refuses a frame it has already seen."""
    gate = _dofile(lua, "gen1_rb_ball_gate_inputs.lua")
    assert _step(lua, gate.new(_identity(lua, _dofile(lua, RB))),
                 _lab_battle_point(lua, _dofile(lua, RB), 225))
    mutated = _dofile(lua, RB)
    mutated["TRAINER"]["OPP_RIVAL1"] = 999
    with pytest.raises(Exception, match="not lab Rival1"):
        _step(lua, gate.new(_identity(lua, mutated)), _lab_battle_point(lua, mutated, 225))
    assert _step(lua, gate.new(_identity(lua, mutated)), _lab_battle_point(lua, mutated, 999))


def test_the_battle_driver_filters_each_hook_by_its_own_bank(lua):
    """`F.BANKS.<hook>` replaces the single 0x0F literal: the same PC counts under the bank the
    table names and not under any other."""
    module = _dofile(lua, "gen1_battle_driver.lua")
    addresses = {"hLoadedROMBank": 0x1234, "wTopMenuItemX": 1, "wCurrentMenuItem": 2,
                 "wMaxMenuItem": 3, "wMenuWatchedKeys": 4, "wIsInBattle": 5,
                 "wPlayerSelectedMove": 6, "wActionResultOrTookBattleTurn": 7}
    holder = {"addr": None}
    pending = {"fn": None}
    u8 = lambda addr: holder["addr"] if addr == 0x1234 else 0  # noqa: E731
    driver = module.new(lua.table(step=lambda: None, u8=u8, facts=_dofile(lua, RB),
                                  addresses=lua.table(**addresses),
                                  sites=lua.table(display_battle_menu=0x2000),
                                  hook=lambda pc, fn: pending.update(fn=fn) or 1,
                                  unhook=lambda _id: None,
                                  framecount=lambda: 1))
    holder["addr"] = 0x0F
    pending["fn"]()
    holder["addr"] = 0x2C
    pending["fn"]()
    assert driver.hits()["display_battle_menu"]["count"] == 1

    pure = _dofile(lua, PURE)
    pure["BANKS"]["display_battle_menu"] = 0x3A
    pending["fn"] = None
    driver = module.new(lua.table(step=lambda: None, u8=u8, facts=pure,
                                  addresses=lua.table(**addresses),
                                  sites=lua.table(display_battle_menu=0x2000),
                                  hook=lambda pc, fn: pending.update(fn=fn) or 1,
                                  unhook=lambda _id: None,
                                  framecount=lambda: 1))
    holder["addr"] = 0x0F
    pending["fn"]()
    holder["addr"] = 0x3A
    pending["fn"]()
    assert driver.hits()["display_battle_menu"]["count"] == 1


def _save_point(lua, facts, menu_max):
    start = facts["MENU"]["START"]
    return lua.table(map=1, x=10, y=10, battle=0, joy_ignore=0, font_loaded=True,
                     start_menu_save_index=3, menu_y=start["menu_y"], menu_x=start["menu_x"],
                     menu_max=menu_max, menu_index=3, text_box=0)


@pytest.mark.parametrize(("facts_name", "menu_max", "ok"), [
    (RB, 6, True),      # save row 3 + 3 = the vanilla row COUNT
    (RB, 7, True),      # + 1 = the companion SLINK row
    (RB, 5, False),     # the pureRGB arithmetic must not pass here
    (PURE, 5, True),    # save row 3 + 2 = pureRGB's last row INDEX
    (PURE, 6, True),    # + 1 = the companion row
    (PURE, 4, False),
])
def test_the_start_menu_arithmetic_follows_the_lane(lua, facts_name, menu_max, ok):
    facts = _dofile(lua, facts_name)
    driver = _dofile(lua, "gen1_rb_save_inputs.lua").new(_identity(lua, facts))
    if ok:
        assert _step(lua, driver, _save_point(lua, facts, menu_max))
    else:
        with pytest.raises(Exception, match="row count disagrees"):
            _step(lua, driver, _save_point(lua, facts, menu_max))


def test_the_hunt_ball_test_follows_the_lane(lua):
    """pureRGB adds HYPER_BALL $05 and TOWN_MAP $08 is not a ball: the scan is the table's set."""
    hunt = _dofile(lua, "gen1_rb_hunt_inputs.lua")
    assert [hunt.is_ball(i) for i in (1, 4, 5, 8)] == [True, True, False, False]
    hunt.with_facts(_dofile(lua, PURE))
    assert [hunt.is_ball(i) for i in (1, 4, 5, 8)] == [True, True, True, True]
