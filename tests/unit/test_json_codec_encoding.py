import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    lua.globals().JSON = codec
    return lua, codec


@pytest.mark.parametrize("value", [None, True, False, -17, 1.5, 2**53-1, "é😀\x00\b\f\n\r\t\\\"",
                                  [], {}, [1, None, {"nested": []}], {"z": 0, "a": {}}])
def test_typed_values_roundtrip_through_shared_lua_encoder(runtime, value):
    lua, codec = runtime
    decoded = codec.decode(json.dumps(value))
    encoded = codec.encode(decoded)
    assert isinstance(encoded, str), encoded
    assert json.loads(encoded) == value


def test_empty_kinds_and_canonical_key_order(runtime):
    lua, codec = runtime
    assert lua.eval("JSON.encode(JSON.array())") == "[]"
    assert lua.eval("JSON.encode(JSON.object())") == "{}"
    assert lua.eval("JSON.encode({z=2,a=1})") == '{"a":1,"z":2}'
    assert codec.encode(lua.table()) == "{}"


@pytest.mark.parametrize("expression", ["0/0", "math.huge", "9007199254740992",
    "function()end", "setmetatable({},{})", "{[1]=1,[3]=3}", "{[1]=1,a=2}",
    "JSON.object({[1]='not a string key'})", "string.char(255)"])
def test_invalid_values_are_refused_with_an_error(runtime, expression):
    lua, codec = runtime
    encoded, reason = lua.eval("function() return JSON.encode(" + expression + ") end")()
    assert encoded is None and reason


def test_cycles_limits_and_repeated_shared_subtrees(runtime):
    lua, _ = runtime
    assert lua.execute("local t={};t.self=t;local text,err=JSON.encode(t);return text==nil and err~=nil")
    assert lua.execute("local t={a=1};return JSON.encode({left=t,right=t})") == '{"left":{"a":1},"right":{"a":1}}'
    for options in ("{bytes=4}", "{depth=0}", "{items=1}", "{string_bytes=1}"):
        assert lua.eval("function()local text,err=JSON.encode({ab={1}}," + options + ");return text==nil and err~=nil end")()


def test_every_byte_after_long_ascii_span_matches_strict_python_string_parsing(runtime):
    _,codec=runtime
    for byte in range(256):
        wire=b'"'+b'A'*4096+bytes([byte])+b'tail"'
        try:
            expected=json.loads(wire)
        except (ValueError,UnicodeError):
            value,reason=codec.decode(wire)
            assert value is None and reason,byte
        else:
            assert codec.decode(wire)==expected,byte


@pytest.mark.parametrize('tail',['', '\x00\n\t', 'é漢字🚀', '"\\\x7f'])
def test_ascii_spans_keep_escaped_unicode_and_exact_decoded_string_limits(runtime,tail):
    lua,codec=runtime
    value='A'*16384+tail+'Z'*16384
    size=len(value.encode('utf-8'))
    for ascii_only in (False,True):
        wire=json.dumps(value,ensure_ascii=ascii_only)
        assert codec.decode(wire,lua.table_from({'string_bytes':size}))==value
        assert codec.decode(wire,lua.table_from({'string_bytes':size-1}))[0] is None
        assert json.loads(codec.encode(value))==value
