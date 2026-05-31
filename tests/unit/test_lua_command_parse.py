"""
Regression test for the Gen 3 client's hand-rolled command parser.

`parse_command_list` in lua/clients/gen3_frlge_client.lua is NOT a real JSON
decoder — it regex-extracts a fixed allowlist of fields per command.  A command
whose fields aren't in that allowlist silently arrives with nil fields on the
Lua side (this is exactly how `ghost_pos` shipped broken once: the server
relayed full coords, the Python wire-harness parsed them, but the Lua client
dropped mg/mn/x/y/f/mv/an).

This test loads the REAL parse_command_list via lupa (Lua 5.5) and asserts the
ghost_pos coordinate fields survive — catching the parser-allowlist gap that a
server-side or Python-side test cannot.

Skips cleanly if lupa isn't installed.
"""
import re
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

CLIENT = Path(__file__).resolve().parents[2] / "lua" / "clients" / "gen3_frlge_client.lua"


def _extract_parser_source() -> str:
    """Pull the self-contained parse_command_list function out of the client and
    make it global so lupa can call it (it uses only string methods + tonumber)."""
    src = CLIENT.read_text(encoding="utf-8")
    m = re.search(r"local function parse_command_list\(raw\).*?\nend\n", src, re.DOTALL)
    assert m, "could not locate parse_command_list in the client"
    body = m.group(0).replace("local function parse_command_list", "function parse_command_list", 1)
    return body


def _make_parser():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_extract_parser_source())
    return lua, lua.globals().parse_command_list


def test_ghost_pos_fields_survive_lua_parser():
    lua, parse = _make_parser()
    resp = ('{"commands": [{"cmd": "ghost_pos", "mg": 6, "mn": 5, "x": 14, '
            '"y": 13, "f": 2, "mv": 1, "an": 4, "bt": 1, '
            '"imgs": 152332016, "anim": 152330484, "pal": 153784012, '
            '"name": "ALICE", "ts": 1780168465.46}]}')
    cmds = parse(resp)
    assert lua.eval("function(t) return #t end")(cmds) == 1
    c = cmds[1]
    assert c.cmd == "ghost_pos"
    assert (c.mg, c.mn) == (6, 5), "mapGroup/mapNum dropped by the Lua parser"
    assert (c.x, c.y) == (14, 13), "coords dropped by the Lua parser"
    assert c.f == 2 and c.mv == 1, "facing/moving dropped by the Lua parser"
    assert c.an == 4, "animNum (run fidelity) dropped by the Lua parser"
    assert c.bt == 1, "battle flag dropped by the Lua parser"
    # chosen-trainer graphics pointers (ROM addrs as large ints)
    assert c.imgs == 152332016, "trainer images ptr dropped by the Lua parser"
    assert c.anim == 152330484, "trainer anims ptr dropped by the Lua parser"
    assert c.pal == 153784012, "trainer palette ptr dropped by the Lua parser"


def test_ghost_pos_negative_coords_parse():
    """World coords are s16 and can be negative near map origins."""
    _, parse = _make_parser()
    resp = '{"commands": [{"cmd": "ghost_pos", "mg": 3, "mn": 1, "x": -4, "y": -2, "f": 3, "mv": 0, "an": 0}]}'
    c = parse(resp)[1]
    assert (c.x, c.y) == (-4, -2)


def test_ghost_clear_has_no_coords():
    _, parse = _make_parser()
    c = parse('{"commands": [{"cmd": "ghost_clear"}]}')[1]
    assert c.cmd == "ghost_clear"
    assert c.mg is None and c.x is None
