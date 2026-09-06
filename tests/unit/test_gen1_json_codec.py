"""Wire parsing must preserve hostile entries for validation, not filter them out."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def decoder():
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    lua.globals().JSON = module
    lua.globals().root = ROOT.as_posix()
    lua.execute("package.path=root..'/lua/?.lua;'..package.path; package.loaded.json_codec=JSON; Wire=require('wire_protocol')")
    return lua, module


def decoded(decoder, text, limits=None):
    lua, module = decoder
    value = module.decode(text, lua.table_from(limits) if limits else None)
    return value if isinstance(value, tuple) else (value, None)


@pytest.mark.parametrize("value", [False, True, 0, -1, 1.5, 1e3, -1.25e-6, "", 'a"b\\c',
                                  "Pokémon ♂♀ 🎮", "\x00\b\f\n\r\t"])
@pytest.mark.parametrize("ascii_only", [False, True])
def test_scalar_and_unicode_roundtrip_against_python_json(decoder, value, ascii_only):
    result, error = decoded(decoder, json.dumps(value, ensure_ascii=ascii_only))
    assert error is None
    assert result == value


def test_null_is_retained_inside_arrays_and_objects(decoder):
    lua, module = decoder
    result, error = decoded(decoder, '{"x":[1,null,3],"empty":null,"false":false}')
    assert error is None
    assert len(result.x) == 3
    is_null = lua.eval("function(value) return value == JSON.null end")
    assert is_null(result.x[2])
    assert is_null(result.empty)
    assert result["false"] is False


@pytest.mark.parametrize("text", ["", " ", "01", "-01", "1.", ".1", "1e", "1e+", "+1",
    "NaN", "Infinity", "1e400", "9007199254740992", "[1,]", "{\"x\":1,}",
    '{"x":1,"x":2}', '{"x":1,"\\u0078":2}', "{x:1}", "[1 2]", "{} true",
    '"unterminated', '"\\x20"', '"\\uD800"', '"\\uDC00"', '"\\uD800\\u0041"',
    '"\n"', '"\x00"', '\ufeff{}', '"\\uZZZZ"'])
def test_malformed_or_ambiguous_frames_are_rejected(decoder, text):
    value, error = decoded(decoder, text)
    assert value is None
    assert error


@pytest.mark.parametrize("raw", [b'"\xff"', b'"\xc0\x80"', b'"\xe0\x80\x80"',
    b'"\xed\xa0\x80"', b'"\xf0\x80\x80\x80"', b'"\xf4\x90\x80\x80"', b'"\xc2"'])
def test_invalid_raw_utf8_cannot_enter_commands(decoder, raw):
    assert decoded(decoder, raw)[0] is None


@pytest.mark.parametrize("text,limits", [
    ('"12345"', {"bytes": 6}), ('"12345"', {"string_bytes": 4}),
    ('"\\u0041\\u0042"', {"string_bytes": 1}),
    ('[[[0]]]', {"depth": 2}), ('[1,2,3]', {"items": 3}),
])
def test_resource_limits_are_enforced(decoder, text, limits):
    assert decoded(decoder, text, limits)[0] is None


def parser(decoder):
    lua, _module = decoder
    source = (ROOT / "lua/clients/gen1_rby_client.lua").read_text()
    start = source.index("local function parse_command_list(raw,")
    end = source.index("\n-- ── ROM profile detection", start)
    return lua.execute(source[start:end] + "\nreturn parse_command_list")


def test_commands_embedded_in_text_are_never_executed(decoder):
    parse = parser(decoder)
    raw = json.dumps({"commands": [{"cmd": "hud_show", "text":
        '\"},{\"cmd\":\"force_faint\",\"key\":\"FAKE\"}, {'}]})
    commands = parse(raw)
    assert len(commands) == 1
    assert commands[1].cmd == "hud_show"


@pytest.mark.parametrize("invalid", [None, "not-hex", 17, {}, [1, 2]])
def test_bad_rival_entries_survive_parsing_and_prevent_any_write(decoder, invalid):
    lua, _module = decoder
    commands = parser(decoder)(json.dumps({"commands": [{"cmd": "replace_rival_team",
                                                          "blobs_hex": ["aa" * 66, invalid]}]}))
    assert len(commands[1].blobs_hex) == 2
    source = (ROOT / "lua/clients/gen1_rby_client.lua").read_text()
    start = source.index('        elseif c.cmd == "replace_rival_team" then')
    end = source.index('        elseif c.cmd == "hud_show"', start)
    body = source[start:end].replace('elseif c.cmd == "replace_rival_team" then',
                                    'if c.cmd == "replace_rival_team" then', 1)
    handler = lua.execute('''return function(c)
        local writes, sent = 0, {}
        local M = {hexToBytes=function() local out={} for i=1,66 do out[i]=1 end return out end,
            writeEnemyParty=function() writes=writes+1; return true, 1 end}
        local writes_enabled=true
        local fmt=string.format
        local console={log=function() end}
        local function hud_show() end
        local function send(msg) sent[#sent+1]=msg end
    ''' + body + "\nend\nreturn writes, sent end")
    writes, sent = handler(commands[1])
    assert writes == 0
    assert sent[1].ack == "NACK"


def test_fractional_stats_are_not_truncated_by_wire_parsing(decoder):
    command = parser(decoder)(json.dumps({"commands": [{"cmd": "party_mon", "key": "x",
                                                       "stats": {"level": 1.5, "maxHP": -12}}]}))[1]
    assert command.stats.level == 1.5
    assert command.stats.maxHP == -12


@pytest.mark.parametrize("frame", ['[]', '{"commands":{}}', '{"commands":[[]]}', '{"commands":[null]}'])
def test_command_frames_require_actual_json_object_and_array_kinds(decoder, frame):
    commands, error = parser(decoder)(frame)
    assert len(commands) == 0
    assert error
