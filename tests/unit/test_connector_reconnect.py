"""lua/connector.lua:263 M.disconnect() must not let a pre-drop event outlive the connection.

WHY THIS EXISTS. M.disconnect() reset _send_offset/_recv_buf but left _send_queue intact.
An event queued the same frame the socket died survived into the NEW connection and was
flushed by pump() (connector.lua:195-202) before the client got a chance to queue its
reconnect hello -- every real client calls net.pump() first and only then (re)sends hello
in the same frame_end, e.g. lua/gen1/client.lua:929-941 and
lua/clients/gen3_frlge_client.lua:1912-1937. Since server/server.py:1235-1240 answers any
pre-hello event on a connection with a `noop` + WARNING, that stale event was not merely
reordered ahead of hello -- it was silently dropped by the server anyway, just later and
with a same log noise. Clearing _send_queue in disconnect() drops it locally instead, and a
new connection starts with hello first by construction.

Checked before writing the fix: connector.lua itself is the only caller of M.disconnect()
(on the send-error and receive-error branches) and the only reader of _send_queue --
no other lua/ file touches either, so nothing relies on the queue surviving a drop.
"""
from __future__ import annotations

import json
import os

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute connector.lua")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_CONNECTOR = os.path.join(_REPO, "lua", "connector.lua")

# A minimal non-fragmenting mock: sends succeed in one shot except when `fail_send` is set,
# which reports a hard "closed" error the way a dead peer does -- the SAME error shape
# connector.lua's own send-error branch (`M.send error ... "` -- disconnecting") handles by
# calling M.disconnect(), so the test drops the socket through connector.lua's real code
# path rather than by calling c.disconnect() itself.
_HARNESS = r"""
local M = {}
M.sent = {}
M.closed = false
M.fail_send = false

local sock = {}
sock.__index = sock

function sock:settimeout(_) end
function sock:connect(_, _) return 1 end          -- loopback: connects immediately
function sock:close() M.closed = true end
function sock:getpeername() return "127.0.0.1", 1 end

function sock:send(data, i)
    if M.fail_send then return nil, "closed" end
    i = i or 1
    local rest = data:sub(i)
    table.insert(M.sent, rest)
    return #data
end

function sock:receive(_) return nil, "timeout", "" end

M.new = function() return setmetatable({}, sock) end
return M
"""


def _lua_env():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = rt.globals()

    mock = rt.execute(_HARNESS)
    g.console = rt.table_from({"log": lambda s: None})

    fake_socket = rt.table_from({"socket": rt.table_from({"tcp4": lambda: mock.new()})})
    rt.execute(
        'local fake = ...; package.preload["socket"] = function() return fake end',
        fake_socket,
    )

    with open(_CONNECTOR, encoding="utf-8") as f:
        src = f.read()
    connector = rt.execute(src)
    return rt, connector, mock


def _sent_events(rt, mock):
    n = len(mock.sent)
    blob = "".join(mock.sent[i] for i in range(1, n + 1))
    return [json.loads(s) for s in blob.split("\n") if s]


def test_stale_pre_drop_event_does_not_jump_the_reconnect_hello():
    rt, c, mock = _lua_env()
    c.init("127.0.0.1", 1)
    c.pump()
    assert c.connected()

    # Queued the instant before the peer goes away -- exactly what a client's frame_end can
    # do the same frame the connection dies.
    c.send(json.dumps({"event": "tick", "seq": 1}))

    # Drop the socket via connector.lua's own send-error path, not c.disconnect() directly.
    mock.fail_send = True
    c.pump()
    assert not c.connected(), "a hard send error must drive pump() into disconnect()"

    # Reconnect.
    mock.fail_send = False
    c.init("127.0.0.1", 1)
    assert c.connected()

    # Mirror every real client's frame_end order: pump() first, THEN queue the reconnect
    # hello in the same frame (lua/gen1/client.lua:929-941); the hello itself goes out on
    # the frame's OWN next pump(), same as production.
    c.pump()
    c.send(json.dumps({"event": "hello", "seq": 0}))
    c.pump()

    events = _sent_events(rt, mock)
    assert events, "nothing was sent on the new connection"
    assert events[0]["event"] == "hello", (
        f"hello must be the first thing the new connection sends, got {events!r} -- "
        "a pre-drop event survived disconnect() and jumped ahead of it")
    assert not any(e.get("event") == "tick" for e in events), (
        "the stale pre-drop event must not survive a disconnect() at all")
