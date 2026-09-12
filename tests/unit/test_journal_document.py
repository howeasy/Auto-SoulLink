"""Actual Lua proof bytes against the existing Python journal representation."""
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server.protocol_journal import _encode

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("text", ["ASCII", "Pokémon", "♂♀¥×", "é漢字🚀", "\x7f", "\b\t\n\f\r\x00",
    r"literal\u000a\u0008\n", '"quoted"\\path', "é\\u000a\n🚀", "C:\\Users\\Zoé\\save.SaveRAM"])
def test_integer_proof_documents_have_identical_python_lua_canonical_bytes(text):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute("package.path=root..'/lua/?.lua;'..package.path; JSON=require('json_codec'); Canonical=require('journal_document')")
    document = {"name": text, "nested": {text: [None, True, False, 0, -19, 9007199254740991]}, "empty": {}}
    lua.globals().wire = json.dumps(document)
    actual = lua.eval("Canonical.encode(assert(JSON.decode(wire)))")
    assert actual == _encode(document)[0]
    assert json.loads(actual) == document


@pytest.mark.parametrize("number", ["0.25", "1.0", "-0.0"])
def test_float_values_do_not_silently_change_journal_proof_hash(number):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute("package.path=root..'/lua/?.lua;'..package.path; Canonical=require('journal_document')")
    value, reason = lua.eval("Canonical.encode({number="+number+"})")
    assert value is None and "integer" in reason
