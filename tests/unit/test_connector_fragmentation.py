"""lua/connector.lua must survive a line that does not cross the socket in one piece.

WHY THIS EXISTS. The transport is newline-delimited JSON over a non-blocking socket, and
with settimeout(0) LuaSocket may move only PART of a line, reporting how far it got in its
third return value. Both directions used to discard that value:

  * send: the whole line stayed queued, so the next frame re-sent bytes the peer already
    had -- duplicating a prefix in the middle of the stream.
  * receive: the partial was dropped, and LuaSocket had already taken those bytes off the
    socket, so they were gone. The next complete line then arrived with its head missing.

Neither ever fired in practice, because a small JSON line crosses loopback atomically. That
made "lines are small" an unexamined assumption rather than a design, and the Gen 1 ROM
content payload is kilobytes. So this drives connector.lua under lupa with a mock socket
that fragments deliberately.

Every test here was checked against the PRE-FIX connector and fails there -- a
fragmentation test that passes on broken code is worse than none.
"""
from __future__ import annotations

import json
import os

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute connector.lua")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_CONNECTOR = os.path.join(_REPO, "lua", "connector.lua")

_HARNESS = r"""
-- A socket whose send() and receive() move at most CHUNK bytes per call, exactly as a full
-- OS buffer or a split TCP segment would. Records everything the peer actually receives so
-- a duplicated or dropped prefix is visible.
local M = {}
M.sent = {}          -- ordered list of byte-strings the peer received
M.inbox = ""         -- bytes waiting to be read by the client
M.chunk = 8
M.closed = false

local sock = {}
sock.__index = sock

function sock:settimeout(_) end
-- Loopback connects immediately, which is the path _do_connect takes on success.
function sock:connect(_, _) return 1 end
function sock:close() M.closed = true end
function sock:getpeername() return "127.0.0.1", 1 end

-- LuaSocket: send(data, i) is 1-based; returns the index of the last byte written, and on
-- timeout returns nil, "timeout", lastindex.
function sock:send(data, i)
    i = i or 1
    if i > #data then return #data end
    local remaining = #data - i + 1
    local n = math.min(M.chunk, remaining)
    table.insert(M.sent, data:sub(i, i + n - 1))
    local last = i + n - 1
    if last < #data then return nil, "timeout", last end
    return last
end

-- LuaSocket: receive("*l") returns the line, or nil, "timeout", partial.
function sock:receive(_)
    if #M.inbox == 0 then return nil, "timeout", "" end
    local nl = M.inbox:find("\n", 1, true)
    if nl and nl <= M.chunk then
        local line = M.inbox:sub(1, nl - 1)
        M.inbox = M.inbox:sub(nl + 1)
        return line
    end
    local n = math.min(M.chunk, #M.inbox)
    local part = M.inbox:sub(1, n)
    M.inbox = M.inbox:sub(n + 1)
    return nil, "timeout", part
end

M.new = function() return setmetatable({}, sock) end
return M
"""


def _lua_env(chunk: int = 8):
    """Load connector.lua with a fragmenting mock socket in place of the real one."""
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = rt.globals()

    mock = rt.execute(_HARNESS)
    mock.chunk = chunk

    logs = []
    g.console = rt.table_from({"log": lambda s: logs.append(str(s))})

    # connector.lua does `package.loaded["socket"] = nil` then require("socket"), so the
    # stub has to be produced by the loader rather than pre-seeded.
    fake_socket = rt.table_from({
        "socket": rt.table_from({"tcp4": lambda: mock.new()}),
    })
    rt.execute("""
        local fake = ...
        package.preload["socket"] = function() return fake end
    """, fake_socket)

    with open(_CONNECTOR, encoding="utf-8") as f:
        src = f.read()
    connector = rt.execute(src)
    return rt, connector, mock, logs


def _connect(connector, mock):
    connector.init("127.0.0.1", 1)
    connector.pump()
    return connector.connected()


# ── send ─────────────────────────────────────────────────────────────────────────────────
def test_a_long_line_is_sent_exactly_once_across_many_frames():
    """The bytes the peer receives must concatenate to the line, with nothing repeated."""
    rt, c, mock, _ = _lua_env(chunk=8)
    assert _connect(c, mock)
    rt.execute("local m = ...; m.sent = {}", mock)

    payload = json.dumps({"event": "rom_content", "blob": "A" * 4000})
    c.send(payload)
    for _ in range(2000):
        c.pump()

    received = "".join(mock.sent[i] for i in range(1, len(mock.sent) + 1))
    assert received == payload + "\n", (
        f"peer got {len(received)} bytes for a {len(payload) + 1}-byte line — "
        "a partial send was repeated or lost")


def test_several_queued_lines_keep_their_order_and_boundaries():
    rt, c, mock, _ = _lua_env(chunk=5)
    assert _connect(c, mock)
    rt.execute("local m = ...; m.sent = {}", mock)

    lines = [json.dumps({"seq": i, "pad": "x" * (i * 37)}) for i in range(1, 6)]
    for ln in lines:
        c.send(ln)
    for _ in range(4000):
        c.pump()

    received = "".join(mock.sent[i] for i in range(1, len(mock.sent) + 1))
    assert received == "".join(ln + "\n" for ln in lines)
    # And each one is still parseable as its own object.
    assert [json.loads(x) for x in received.splitlines()] == [json.loads(x) for x in lines]


# ── receive ──────────────────────────────────────────────────────────────────────────────
def test_a_line_split_across_frames_is_reassembled_whole():
    rt, c, mock, _ = _lua_env(chunk=8)
    assert _connect(c, mock)

    payload = json.dumps({"commands": [{"cmd": "box_mon", "blob": "B" * 3000}]})
    rt.execute("local m, s = ...; m.inbox = s .. '\\n'", mock, payload)
    for _ in range(2000):
        c.pump()

    got = c.receive()
    assert got is not None, "the split line never completed"
    assert got == payload
    assert json.loads(got)["commands"][0]["cmd"] == "box_mon"
    assert c.receive() is None, "a second line appeared from nowhere"


def test_two_lines_in_one_burst_do_not_merge():
    rt, c, mock, _ = _lua_env(chunk=7)
    assert _connect(c, mock)

    a = json.dumps({"commands": [{"cmd": "first", "pad": "y" * 200}]})
    b = json.dumps({"commands": [{"cmd": "second", "pad": "z" * 200}]})
    rt.execute("local m, x, y = ...; m.inbox = x .. '\\n' .. y .. '\\n'", mock, a, b)
    for _ in range(2000):
        c.pump()

    assert c.receive() == a
    assert c.receive() == b
    assert c.receive() is None


def test_a_reconnect_does_not_prepend_a_half_read_line():
    """A new socket is a new byte stream; stale partials must not leak into it."""
    rt, c, mock, _ = _lua_env(chunk=8)
    assert _connect(c, mock)

    rt.execute("local m = ...; m.inbox = '{\"commands\":[{\"cmd\":\"orph'", mock)
    for _ in range(50):
        c.pump()
    assert c.receive() is None, "an incomplete line was delivered"

    c.disconnect()
    assert not c.connected()

    # Reconnect and deliver a clean line.
    c.init("127.0.0.1", 1)
    c.pump()
    fresh = json.dumps({"commands": [{"cmd": "clean"}]})
    rt.execute("local m, s = ...; m.inbox = s .. '\\n'", mock, fresh)
    for _ in range(500):
        c.pump()
    assert c.receive() == fresh, "the orphaned partial corrupted the next session"


def test_an_absurdly_long_inbound_line_is_dropped_rather_than_buffered_forever():
    """Bounded queues: a peer that never sends a newline must not grow memory without end."""
    rt, c, mock, logs = _lua_env(chunk=4096)
    assert _connect(c, mock)

    rt.execute("local m = ...; m.inbox = string.rep('Z', 5 * 1024 * 1024)", mock)
    for _ in range(4000):
        c.pump()
    assert c.receive() is None
    assert any("exceeded" in x for x in logs), "no cap was applied and nothing was logged"


def test_the_tail_of_an_over_long_line_is_not_delivered_as_a_line():
    """Capping the buffer is not the same as resyncing the stream.

    The cap discarded `_recv_buf` and logged, but set no "skip to the next newline" state,
    so the REST of the oversized line re-accumulated from scratch and was handed to the
    parser as a perfectly ordinary line. Measured before the fix: one "exceeded" log, then
    two lines delivered -- a 1 MB run of Z, and only then the real one.

    It looked harmless only because `parse_command_list` is a pattern scraper that returns
    `{}` on no match rather than raising; it still consumed a pending_labels entry and
    logged a bogus inbound message. The test above could not see any of it because it never
    sends the terminating newline.
    """
    rt, c, mock, logs = _lua_env(chunk=4096)
    assert _connect(c, mock)

    good = '{"commands":[]}'
    rt.execute("local m, g, nl = ...; "
               "m.inbox = string.rep('Z', 5 * 1024 * 1024) .. nl .. g .. nl",
               mock, good, "\n")
    for _ in range(6000):
        c.pump()

    delivered = []
    while True:
        line = c.receive()
        if line is None:
            break
        delivered.append(line)

    assert any("exceeded" in x for x in logs), "no cap was applied"
    assert delivered == [good], (
        f"expected only the valid line to survive the resync, got "
        f"{[(len(d), d[:20]) for d in delivered]}")
