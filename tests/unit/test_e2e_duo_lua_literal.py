"""The SLINK_DUO stub's values must be Lua, not Python repr (live CLAUSE-ROWS-G3 load failure)."""
from lupa import LuaRuntime

from tools import e2e_duo as duo


def test_stub_values_load_in_lua_and_keep_string_keys():
    facts = {"1": {"types": [12, 3], "gender_ratio": 31, "family": 1}, "4": {"types": [10, 10]}}
    lua = LuaRuntime()
    t = lua.execute("return " + duo.lua_literal({"clause_facts": facts, "name": 'a"b\c', "on": True, "n": 7}))
    assert t["clause_facts"]["1"]["types"][2] == 3 and t["clause_facts"]["4"]["types"][1] == 10
    assert t["name"] == 'a"b\c' and t["on"] is True and t["n"] == 7
