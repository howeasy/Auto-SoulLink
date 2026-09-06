"""Actual client fragments must distinguish queued bytes from a refused send."""
from pathlib import Path

from lupa import LuaRuntime

CLIENT = Path(__file__).resolve().parents[2] / "lua/clients/gen1_rby_client.lua"


def test_refused_send_does_not_consume_sequence_or_response_label():
    source = CLIENT.read_text(encoding="utf-8")
    block = source[source.index("local seq            = 0"):source.index("-- ── Command dispatcher")]
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        fmt=string.format; PLAYER_ID='a'; accepted=false; online=true; attempts=0
        console={log=function() end}; hud_show=function() end
        json_encode=function(evt) return tostring(evt.seq) end
        C={connected=function() return online end, send=function(wire)
            attempts=attempts+1; last_wire=wire; return accepted,'queue full'
        end}
    """)
    client = lua.execute(block + "\nreturn {send=send, state=function() return seq,#pending_labels end}")
    event = lua.table_from({"event": "safe"})
    assert client.send(event, "safe", True)[0] is False
    assert client.state() == (0, 0)
    lua.globals().accepted = True
    assert client.send(event, "safe", True) is True
    assert client.state() == (1, 1)
    assert lua.globals().last_wire == "1"
    lua.globals().online = False
    assert client.send(event, "safe", True)[0] is False
    assert client.state() == (1, 1)
    assert lua.globals().attempts == 2


def test_safe_notification_survives_busy_disconnected_and_full_queue_states():
    source = CLIENT.read_text(encoding="utf-8")
    start = source.index("    if pending_safe and C.connected()")
    block = source[start:source.index("    -- 10. Tick event", start)]
    lua = LuaRuntime()
    lua.execute("""
        pending_safe=true; post_battle_frames=0; safe=true; online=true; accepted=false
        attempts=0; nuzlocke_active=true; last_area_id='route_1'
        C={connected=function() return online end}
        M={isPartyWriteSafe=function() return safe end, getPartyCount=function() return 1 end}
        build_party_snapshot=function() return {} end
        send=function() attempts=attempts+1; return accepted end
    """)
    run = lua.execute("return function()\n" + block + "\nend")
    run()
    assert lua.globals().pending_safe is True and lua.globals().attempts == 1
    for name, value, reset in (("online", False, True), ("safe", False, True), ("post_battle_frames", 1, 0)):
        lua.globals()[name] = value
        run()
        assert lua.globals().pending_safe is True and lua.globals().attempts == 1
        lua.globals()[name] = reset
    lua.globals().accepted = True
    run()
    assert lua.globals().pending_safe is False and lua.globals().attempts == 2
