"""Neutral scanner contract plus real generated Gen 2 bindings; no emulator."""
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "lua/token_scanner.lua"


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """Pure Lua controls need no disk-writing state fixture."""
    yield


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    scanner = lua.eval("dofile")(SCANNER.as_posix())
    policy = lua.eval('{glyphs={[1]="A",[2]="A",[3]="é",[4]="<TOKEN>"}, '
                      'terminator=0, max_length=5, '
                      'unknown=function(b,i) return string.format("[%02X:%d]",b,i) end}')
    return lua, scanner, policy


def test_exact_tokens_aliases_unknown_policy_and_every_terminator_boundary():
    lua, scanner, policy = runtime()
    decode = scanner.new(policy)
    assert decode(lua.table_from([1, 2, 3, 4, 9])) == "AAé<TOKEN>[09:5]"
    assert decode(lua.table_from([])) == ""
    for where in range(5):
        raw = [1] * 5
        raw[where] = 0
        assert decode(lua.table_from(raw)) == "A" * where
    assert decode(lua.table_from([1] * 5)) == "AAAAA"  # Bounded names need not terminate.
    assert decode(lua.table_from([0] + [1] * 5))[0] is None  # Bound applies before termination.


@pytest.mark.parametrize("expression", [
    "nil", "false", "42", '"ABC"', "{}",
    '{glyphs={},terminator=0,max_length=5}',
    '{glyphs={},terminator=0,unknown=function() return "?" end}',
    '{glyphs={},max_length=5,unknown=function() return "?" end}',
])
def test_missing_explicit_policy_is_a_constructor_error(expression):
    lua, scanner, _ = runtime()
    with pytest.raises(LuaError):
        scanner.new(lua.eval(expression))


@pytest.mark.parametrize("field,expression", [
    ("terminator", "-1"), ("terminator", "256"), ("terminator", "1.5"),
    ("max_length", "-1"), ("max_length", "1.5"), ("max_length", "math.huge"),
    ("max_length", "0/0"), ("unknown", '"hex"'),
    ("glyphs", '{[256]="bad"}'), ("glyphs", '{[-1]="bad"}'),
    ("glyphs", '{["1"]="bad"}'), ("glyphs", "{[1]=false}"),
    ("glyphs", 'setmetatable({}, {__index=function() return "fake" end})'),
])
def test_malformed_policy_refuses(field, expression):
    lua, scanner, policy = runtime()
    policy[field] = lua.eval(expression)
    with pytest.raises(LuaError):
        scanner.new(policy)


@pytest.mark.parametrize("expression", [
    "nil", "false", '"ABC"', "{1,false}", "{1,-1}", "{1,256}", "{1,1.5}",
    "{1,0/0}", "{1,math.huge}", "{[1]=1,[3]=1}", "{[0]=1}", "{[1.5]=1}",
    "{[1]=1,extra=2}", "{1,0,false}", "{1,0,256}",
    "setmetatable({1}, {__len=function() return 0 end})",
])
def test_malformed_stream_returns_refusal_not_prefix(expression):
    lua, scanner, policy = runtime()
    policy.unknown = lua.eval('function() error("callback must not run") end')
    result = scanner.new(policy)(lua.eval(expression))
    assert isinstance(result, tuple) and result[0] is None and isinstance(result[1], str)
    assert "handler failed" not in result[1]


@pytest.mark.parametrize("handler", [
    'function() return nil,"unmapped byte" end',
    "function() return 42 end", "function() return false end",
    'function() error("broken policy") end',
])
def test_unknown_policy_cannot_return_partial_success(handler):
    lua, scanner, policy = runtime()
    policy.unknown = lua.eval(handler)
    got, reason = scanner.new(policy)(lua.table_from([1, 9]))
    assert got is None and isinstance(reason, str)


def test_unknown_callback_not_called_after_terminator():
    lua, scanner, policy = runtime()
    policy.unknown = lua.eval('function() error("unexpected unknown") end')
    assert scanner.new(policy)(lua.table_from([1, 0, 9])) == "A"


def test_configuration_and_input_snapshot_are_stable_during_callback():
    lua, scanner, _ = runtime()
    exercise = lua.eval('''function(Scanner)
        local bytes, glyphs = {9,2}, {[2]="B"}
        local decoder = Scanner.new({glyphs=glyphs, terminator=0, max_length=2,
            unknown=function() bytes[2]=3; glyphs[2]="changed"; return "?" end})
        return decoder(bytes), decoder({2})
    end''')
    assert exercise(scanner) == ("?B", "B")


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_real_gen2_charmap_is_a_second_injected_binding(title):
    lua, scanner, _ = runtime()
    pack = ROOT / "data/games" / f"gen2_{title}"
    charmap = lua.eval("dofile")((pack / "charmap.lua").as_posix())
    profile = json.loads((pack / "profile.json").read_text(encoding="utf-8"))["titles"][title]
    policy = lua.table_from({"glyphs": charmap.glyphs, "terminator": charmap.terminator,
                             "max_length": profile["constants"]["NAME_LENGTH"],
                             "unknown": lua.eval('function(b) return string.format("<$%02X>",b) end')})
    decode = scanner.new(policy)
    assert charmap.encoding["<ENEMY>"] == charmap.encoding["⁂"] == 0x3f
    assert decode(lua.table_from([0x49, 0x3f, 0x80, 0x50, 0x81])) == "<MOM><ENEMY>A"
    assert decode(lua.table_from([1, 0x50])) == "<$01>"
    assert decode(lua.table_from([0x80] * 11)) == "A" * 11
    assert decode(lua.table_from([0x80] * 12))[0] is None
