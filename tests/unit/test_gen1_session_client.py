"""Execute the production Lua envelope validator against actual Python responses."""
import copy
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server import gen1_admission as admission
from tests.unit.test_gen1_sessions import contract, hello

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.globals().rom_hash = admission.clean_profiles()["red"]["final_rom_sha1"]
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec'); S=require('gen1_session')
        gameinfo={getromhash=function() return rom_hash:upper() end}
        S.new_nonce=function() return string.rep('1',32) end
        session=S.new('red','a'); assert(session:begin())
        hello={event='hello'}; assert(session:decorate(hello)); session:queued(hello)
        function receive(text) return session:receive(assert(JSON.decode(text))) end
        function queue() local evt={event='tick'}; local ok,err=session:decorate(evt)
            if ok then session:queued(evt) end; return ok,err,evt end
    """)
    spec = contract()
    gate = admission.SessionGate()
    message = hello(spec, client_nonce="1" * 32, operation_id="1" * 32 + ":hello")
    gate.admit(spec, "a", message, object())
    packet = gate.response("a", message, [{"cmd": "hud_show", "text": "admitted"}], hello=True)
    return lua, packet


def receive(client, packet):
    lua, _ = client
    answer = lua.globals().receive(json.dumps(packet))
    return answer if isinstance(answer, tuple) else (answer, None)


@pytest.mark.parametrize("field,value", [("player", "b"), ("protocol", "old"), ("seq", 1),
                                       ("operation_id", "old"), ("session_id", "bad"), ("admission_epoch", "bad")])
def test_wrong_hello_response_never_admits_or_returns_commands(client, field, value):
    lua, packet = client
    packet[field] = value
    commands, error = receive(client, packet)
    assert commands is None and error and lua.globals().session.state != "admitted"


@pytest.mark.parametrize("field,value", [("state", "pending"), ("client_nonce", "2" * 32),
    ("variant", "yellow"), ("final_rom_sha1", "0" * 40), ("content_profile_hash", "0" * 64),
    ("content_profile_schema", "partial-wild-only"), ("patch_version", True),
    ("party_codec", "old"), ("capabilities", {"panel": 0, "sfx": False, "pc_trade": False})])
def test_admission_facts_must_equal_the_actual_cartridge(client, field, value):
    lua, packet = client
    packet["admission"][field] = value
    commands, error = receive(client, packet)
    assert commands is None and error and lua.globals().session.state != "admitted"


@pytest.mark.parametrize("field,value", [("admission_epoch", "old"), ("session_id", "old"),
    ("seq", 1), ("command_index", 2), ("operation_id", "other"), ("player", "b")])
def test_one_invalid_command_refuses_the_whole_response_before_admission(client, field, value):
    lua, packet = client
    packet["commands"].append(copy.deepcopy(packet["commands"][0]))
    packet["commands"][1]["command_index"] = 2
    packet["commands"][0][field] = value
    commands, error = receive(client, packet)
    assert commands is None and error and lua.globals().session.state != "admitted"


def test_admitted_commands_and_ordered_ack_then_duplicate_response(client):
    lua, packet = client
    assert len(receive(client, packet)[0]) == 1
    assert lua.globals().session.state == "admitted"
    ok, _, evt = lua.globals().queue()
    assert ok and evt.seq == 1
    response = {k: packet[k] for k in ("protocol", "player", "admission_epoch", "session_id")}
    response.update(seq=1, operation_id=evt.operation_id, ack="ACK", commands=[])
    assert len(receive(client, response)[0]) == 0
    assert lua.globals().session.pending_count == 0
    response["commands"] = [{**response, "cmd": "force_faint", "key": "9876:1234:99", "command_index": 1}]
    assert len(receive(client, response)[0]) == 0  # duplicate may never execute commands again
    assert lua.globals().session.pending_count == 0


def test_no_events_before_admission_and_bounded_pending_events(client):
    lua, packet = client
    assert lua.globals().queue()[0] is False
    receive(client, packet)
    for sequence in range(1, 129):
        ok, _, evt = lua.globals().queue()
        assert ok and evt.seq == sequence
    assert lua.globals().queue()[0] is False
    assert lua.globals().session.sequence == 128
    lua.execute("session:revoke('disconnect')")
    assert lua.globals().queue()[0] is False
    assert lua.globals().session.pending_count == 0


def test_unknown_rom_and_missing_nonce_api_cannot_negotiate(client):
    lua, _ = client
    lua.execute("rom_hash=string.rep('0',40)")
    assert lua.eval("function() return session:begin() end")()[0] is False
    lua.globals().rom_hash = admission.clean_profiles()["red"]["final_rom_sha1"]
    lua.execute("S.new_nonce=function() return nil,'secure API absent' end")
    assert lua.eval("function() return session:begin() end")()[0] is False


@pytest.mark.parametrize("save_id,name,count,valid,expected", [
    (0, "RED", 0, False, True), (0, "", 0, False, False),
    (0, "RED", 255, False, False), (1, "RED", 1, True, False),
    (0, "OTHER", 1, True, False), (0, "RED", 1, True, True),
])
def test_bound_zero_id_before_starter_survives_but_reset_or_changed_identity_does_not(save_id, name, count, valid, expected):
    source = (ROOT / "lua/clients/gen1_rby_client.lua").read_text(encoding="utf-8")
    block = source[source.index("local function session_identity_valid()"):source.index("local function session_network()")]
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("session={save_id=0,save_name='RED'}")
    lua.globals().M = lua.table_from({"readPlayerId": lambda: save_id, "readPlayerName": lambda: name,
                                    "getPartyCount": lambda: count, "validateROM": lambda: valid})
    check = lua.execute(block + "\nreturn session_identity_valid")
    assert check() is expected
