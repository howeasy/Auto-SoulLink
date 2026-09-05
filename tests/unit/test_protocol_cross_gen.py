"""Shared session machinery accepts adapter policy, not a hardcoded cartridge format."""
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server.protocol import ProtocolError, SessionGate

ROOT = Path(__file__).resolve().parents[2]
VERSION = "slink-test-session-v1"
NONCE = "a" * 32


@pytest.mark.parametrize("game", ["gen2_crystal", "gen3_frlge", "gen4_hgsspt", "gen5_bw"])
def test_python_and_lua_share_envelopes_with_cartridge_specific_metadata_callbacks(game):
    metadata = {"game_id": game, "profile_hash": "b" * 64, "codec": game + "-test-codec"}
    visits = []

    def policy(contract, player, message, identity):
        visits.append(player)
        assert contract == {"expected": game}
        if message.get("game_id") != game or identity != {"save": "adapter-defined"}:
            raise ProtocolError("adapter refused identity")
        return metadata

    gate = SessionGate(protocol=VERSION, hello_validator=policy)
    owner = object()
    hello = {"event": "hello", "protocol": VERSION, "player": "a", "seq": 0,
             "client_nonce": NONCE, "operation_id": NONCE + ":hello", **metadata}
    gate.admit({"expected": game}, "a", hello, owner, {"save": "adapter-defined"})
    response = gate.response("a", hello, [{"cmd": "hud_show", "text": "shared session"}], hello=True)

    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.globals().metadata_json = json.dumps(metadata)
    lua.globals().version = VERSION
    lua.execute("""
        package.path=root..'/lua/?.lua;'..package.path
        JSON=require('json_codec'); Core=require('client_session')
        local metadata=assert(JSON.decode(metadata_json))
        session=Core.new({player='a',protocol=version,
            new_nonce=function() return string.rep('a',32) end,
            read_metadata=function() return metadata end,
            metadata_matches=function(a,b) return a.game_id==b.game_id and a.profile_hash==b.profile_hash and a.codec==b.codec end})
        assert(session:begin())
        local hello={event='hello'}; assert(session:decorate(hello)); session:queued(hello)
        function receive(text) return session:receive(assert(JSON.decode(text))) end
    """)
    result = lua.globals().receive(json.dumps(response))
    assert len(result) == 1 and result[1].cmd == "hud_show"
    assert lua.globals().session.state == "admitted" and visits == ["a"]
    event = {"event": "tick", "protocol": VERSION, "player": "a", "seq": 1,
             "operation_id": NONCE + ":1", "admission_epoch": gate.epoch,
             "session_id": gate.sessions["a"].session_id}
    assert gate.accept("a", event, owner) is None
    reply = gate.response("a", event, [])
    assert gate.accept("a", event, owner) == reply


def test_invalid_common_hello_never_reaches_cartridge_policy():
    visits = []
    gate = SessionGate(protocol=VERSION, hello_validator=lambda *args: visits.append(args) or {})
    with pytest.raises(ProtocolError, match="identifier"):
        gate.admit({}, "a", {"player": "a", "event": "hello", "protocol": VERSION,
                             "client_nonce": "invalid"}, object())
    assert visits == [] and gate.sessions == {}
