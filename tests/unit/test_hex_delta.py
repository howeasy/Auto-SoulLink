import copy
import json
import random

import pytest
from lupa.lua54 import LuaError, LuaRuntime

from server.hex_delta import apply, between, recover_before
from server.protocol_journal import JournalError
from tests.unit.test_client_state_store import ROOT


@pytest.fixture
def lua_apply():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute(
        "package.path=root..'/lua/?.lua;'..package.path;JSON=require('json_codec');Delta=require('hex_delta')"
    )
    return lua.eval(
        "function(before,delta)return Delta.apply(before,assert(JSON.decode(delta)))end"
    )


@pytest.mark.parametrize("length", [1, 33, 404, 1122, 32768])
def test_compact_runs_reconstruct_exact_images_in_both_languages(lua_apply, length):
    rng = random.Random(length)
    before = rng.randbytes(length)
    after = bytearray(before)
    for _ in range(min(length, 40)):
        at = rng.randrange(length)
        after[at] = rng.randrange(256)
    old, new = before.hex().upper(), after.hex().upper()
    delta = between(old, new)
    assert apply(old, delta) == new == lua_apply(old, json.dumps(delta))
    assert apply(old, between(old, old)) == old == lua_apply(old, json.dumps(between(old, old)))


@pytest.mark.parametrize(
    "fault",
    [
        "odd",
        "lower",
        "preimage",
        "overlap",
        "negative",
        "past_end",
        "resize",
        "extra",
        "length",
        "run_extra",
    ],
)
def test_invalid_delta_refuses_before_any_apply_result(lua_apply, fault):
    old = "00112233"
    delta = between(old, "00442255")
    if fault == "odd":
        old = "0"
    elif fault == "lower":
        old = "aa112233"
    elif fault == "preimage":
        delta["runs"][0]["before"] = "FF"
    elif fault == "overlap":
        delta["runs"][1]["offset"] = delta["runs"][0]["offset"]
    elif fault == "negative":
        delta["runs"][0]["offset"] = -1
    elif fault == "past_end":
        delta["runs"][1]["offset"] = 4
    elif fault == "resize":
        delta["runs"][0]["after"] = "FF00"
    elif fault == "extra":
        delta["extra"] = True
    elif fault == "length":
        delta["length"] = 5
    else:
        delta["runs"][0]["extra"] = True
    original = copy.deepcopy(delta)
    with pytest.raises(JournalError):
        apply(old, delta)
    with pytest.raises(LuaError):
        lua_apply(old, json.dumps(delta))
    assert delta == original


@pytest.mark.parametrize("prefix", range(5))
def test_partial_recovery_accepts_only_exact_old_or_new_bytes(prefix):
    before = "0011223344"
    after = "FFEEDDCC44"
    delta = between(before, after)
    mixed = after[: prefix * 2] + before[prefix * 2 :]
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute(
        "package.path=root..'/lua/?.lua;'..package.path;JSON=require('json_codec');D=require('hex_delta')"
    )
    recover = lua.eval(
        "function(current,delta)return D.recover_before(current,JSON.decode(delta))end"
    )
    assert recover_before(mixed, delta) == before == recover(mixed, json.dumps(delta))
    with pytest.raises(JournalError):
        recover_before("77" + mixed[2:], delta)
    with pytest.raises(LuaError):
        recover("77" + mixed[2:], json.dumps(delta))
