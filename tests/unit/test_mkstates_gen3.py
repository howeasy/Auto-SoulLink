"""mkstates_gen3.lua (C4-PROBE2): the trainer/faint/script states' addresses and routes.

Addresses are checked against both committed .sym files; routes are replayed tile by tile over
the ROM layouts when the FR/LG dumps are on this machine (skipped otherwise, never failed).
"""
import os
import re
import sys
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gba_map  # noqa: E402

SOURCE = (ROOT / "lua/tests/mkstates_gen3.lua").read_text(encoding="utf-8")
DELTA = {"Up": (0, -1), "Down": (0, 1), "Left": (-1, 0), "Right": (1, 0)}
ROMS = {
    "pokefirered.sym": "E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba",
    "pokeleafgreen.sym": "E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba",
}


@pytest.fixture(scope="module")
def mk():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""SLINK_ROOT = 'x'
        dofile = function() return {} end
        os.getenv = function(k) return k == 'SLINK_STATE_DIR' and 'x' or nil end""")
    return lua.execute(SOURCE)


def sym(name, file):
    text = (ROOT / "data/gen3/pret" / file).read_text(encoding="utf-8")
    return int(re.search(rf"^([0-9a-f]{{8}}) \S+ \S+ {name}$", text, re.M).group(1), 16)


@pytest.mark.parametrize("file", sorted(ROMS))
def test_battle_addresses_match_both_syms(mk, file):
    assert sym("gBattleMons", file) == mk.BATTLE_MONS
    assert sym("gMoveSelectionCursor", file) == mk.MOVE_CURSOR
    assert sym("HandleInputChooseMove", file) | 1 == mk.HANDLE_INPUT_CHOOSE_MOVE
    assert sym("WaitForMonSelection", file) | 1 == mk.WAIT_FOR_MON_SELECTION
    assert (mk.BMON_MOVES, mk.BMON_HP, mk.MOVE_TAIL_WHIP, mk.BATTLE_TYPE_TRAINER) == (0x0C, 0x28, 39, 8)


def test_probe_and_builder_agree_on_the_send_out_prompt(mk):
    probe = (ROOT / "lua/tests/probe_gen3_checkpoint.lua").read_text(encoding="utf-8")
    assert f"P.WAIT_FOR_MON_SELECTION = 0x{mk.WAIT_FOR_MON_SELECTION:08X}" in probe


def walk(path):
    x, y = path["from"][1], path["from"][2]
    tiles = []
    for d in path.dirs.values():
        dx, dy = DELTA[d]
        x, y = x + dx, y + dy
        tiles.append((x, y))
    return tiles


@pytest.mark.parametrize("name", ["VIRIDIAN_TO_ROUTE22", "ROUTE22_TO_RIVAL", "DOOR_TO_SCRIPT"])
def test_paths_end_where_they_say(mk, name):
    path = mk[name]
    assert walk(path)[-1] == (path.to[1], path.to[2])


@pytest.mark.parametrize("file", sorted(ROMS))
def test_routes_are_walkable_on_the_rom(mk, file):
    if not os.path.exists(ROMS[file]):
        pytest.skip("ROM not on this machine")
    rom = gba_map.load(ROMS[file], sym_path=ROOT / "data/gen3/pret" / file)
    viridian, route22 = rom.map(3, 1), rom.map(3, 41)
    for m, name in ((viridian, "VIRIDIAN_TO_ROUTE22"), (viridian, "DOOR_TO_SCRIPT"),
                    (route22, "ROUTE22_TO_RIVAL")):
        for x, y in walk(mk[name]):
            assert m.collision[y][x] == 0, (name, x, y)
            assert m.behaviour[y][x] not in gba_map.DEFAULT_AVOID_BEHAVIOURS, (name, x, y)
    # Viridian (0,19) Left lands on the Route 22 start; the next Left hits the rival trigger
    assert gba_map.arrival("left", viridian, mk.VIRIDIAN_TO_ROUTE22.to[2])[2:] == (
        mk.ROUTE22_TO_RIVAL["from"][1], mk.ROUTE22_TO_RIVAL["from"][2])
    trig = (mk.RIVAL_TRIGGER[1], mk.RIVAL_TRIGGER[2])
    assert trig == (mk.ROUTE22_TO_RIVAL.to[1] - 1, mk.ROUTE22_TO_RIVAL.to[2])
    assert trig in {(c.x, c.y) for c in route22.coords}
    # the old-man tutorial triggers (20|22,8) are never stepped on
    assert not {(c.x, c.y) for c in viridian.coords} & set(walk(mk.VIRIDIAN_TO_ROUTE22))
    # the script tile sits right below a static object (the woman at (20,12))
    sx, sy = mk.DOOR_TO_SCRIPT.to[1], mk.DOOR_TO_SCRIPT.to[2]
    assert (sx, sy - 1) in {(o.x, o.y) for o in viridian.objects}
