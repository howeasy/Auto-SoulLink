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
function sock:send(data, i, j)
    i = i or 1
    j = j or #data
    if i > j then return j end
    local remaining = j - i + 1
    local n = math.min(M.chunk, remaining)
    table.insert(M.sent, data:sub(i, i + n - 1))
    local last = i + n - 1
    if last < j then return nil, "timeout", last end
    return last
end

-- LuaSocket: receive("*l") returns the line, or nil, "timeout", partial.
function sock:receive(pattern)
    if #M.inbox == 0 then return nil, M.receive_error or "timeout", "" end
    if type(pattern) == "number" then
        local n = math.min(M.chunk, #M.inbox, pattern)
        local part = M.inbox:sub(1, n)
        M.inbox = M.inbox:sub(n + 1)
        if n < pattern then return nil, M.receive_error or "timeout", part end
        return part
    end
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


def test_complete_oversized_frame_cannot_bypass_the_limit():
    rt, c, mock, logs = _lua_env(chunk=8 * 1024 * 1024)
    assert _connect(c, mock)
    mock.inbox = "x" * (5 * 1024 * 1024) + '\n{"commands":[]}\n'
    for _ in range(100):
        c.pump()
    assert c.receive() == '{"commands":[]}'
    assert c.receive() is None
    assert any("exceeded" in line for line in logs)


def test_disconnect_discards_complete_responses_from_the_old_stream():
    rt, c, mock, _ = _lua_env(chunk=1024)
    assert _connect(c, mock)
    mock.inbox = '{"commands":[{"cmd":"box_mon","key":"ABCD:1234:01"}]}\n'
    c.pump()
    assert c.queue_status().receive_lines == 1
    c.disconnect()
    assert c.receive() is None
    assert c.queue_status().receive_lines == 0
    c.init("127.0.0.1", 1)
    assert c.receive() is None
    mock.inbox = '{"commands":[]}\n'
    c.pump()
    assert c.receive() == '{"commands":[]}'


def test_receive_backpressure_bounds_memory_without_losing_order():
    rt, c, mock, _ = _lua_env(chunk=1024 * 1024)
    assert _connect(c, mock)
    expected = [json.dumps({"seq": index}) for index in range(1000)]
    mock.inbox = "\n".join(expected) + "\n"
    delivered = []
    for _ in range(20):
        c.pump()
        status = c.queue_status()
        assert status.receive_lines <= status.max_queue_lines
        assert status.receive_bytes <= status.max_queue_bytes
        assert status.partial_receive_bytes <= status.max_line
        assert status.ready_receive_bytes <= status.max_line
        assert status.pending_receive_bytes <= status.read_chunk
        while (line := c.receive()) is not None:
            delivered.append(line)
    assert delivered == expected


@pytest.mark.parametrize("message", ["", None, 17, "{}\n{}", "{}\r", "x" * (4 * 1024 * 1024 + 1)],
                         ids=["empty", "nil", "number", "LF", "CR", "oversized"])
def test_invalid_outbound_frames_are_rejected_before_any_wire_bytes(message):
    rt, c, mock, _ = _lua_env(chunk=1024 * 1024)
    assert _connect(c, mock)
    before = len(mock.sent)
    ok, reason = c.send(message)
    assert ok is False and reason
    c.pump()
    assert len(mock.sent) == before
    assert c.queue_status().send_bytes == 0


def test_outbound_queue_refuses_overflow_and_recovers_after_drain():
    rt, c, mock, _ = _lua_env(chunk=1024)
    assert _connect(c, mock)
    limit = c.queue_status().max_queue_lines
    for _ in range(limit):
        assert c.send("{}") is True
    assert c.send("{}")[0] is False
    assert c.queue_status().send_lines == limit
    c.pump()
    assert c.queue_status().send_lines == 0
    assert c.send("{}") is True


def test_outbound_queue_byte_limit_is_independent_of_message_count():
    rt, c, mock, _ = _lua_env(chunk=1024)
    assert _connect(c, mock)
    frame = "x" * c.queue_status().max_line
    assert c.send(frame) is True
    # Two maximum payloads plus their line terminators exceed the byte cap.
    assert c.send(frame)[0] is False
    status = c.queue_status()
    assert status.send_lines == 1 and status.send_bytes == len(frame) + 1


def test_each_pump_has_a_wire_budget_and_resumes_absolute_send_offsets():
    rt, c, mock, _ = _lua_env(chunk=1024 * 1024)
    assert _connect(c, mock)
    payload = json.dumps({"data": "z" * 300000})
    assert c.send(payload) is True
    wire = ""
    previous = len(mock.sent)
    for _ in range(20):
        c.pump()
        part = "".join(mock.sent[j] for j in range(previous + 1, len(mock.sent) + 1))
        assert len(part) <= c.queue_status().io_budget
        wire += part
        previous = len(mock.sent)
    assert wire == payload + "\n"
    assert c.queue_status().send_offset == c.queue_status().send_bytes == 0


def test_crlf_is_supported_but_raw_carriage_returns_inside_json_are_preserved():
    rt, c, mock, _ = _lua_env(chunk=2)
    assert _connect(c, mock)
    mock.inbox = '{}\r\n{"text":"bad\rinput"}\n'
    for _ in range(100):
        c.pump()
    assert c.receive() == "{}"
    # The strict JSON decoder must see and reject this control character.
    assert c.receive() == '{"text":"bad\rinput"}'


def test_explicit_init_cannot_send_an_old_runs_partial_frame_to_a_new_server():
    rt, c, mock, _ = _lua_env(chunk=2)
    assert _connect(c, mock)
    c.send('{"old":true}')
    c.pump()
    assert c.queue_status().send_offset == 2
    c.init("127.0.0.1", 2)
    before = len(mock.sent)
    c.send("{}")
    for _ in range(10):
        c.pump()
    assert "".join(mock.sent[j] for j in range(before + 1, len(mock.sent) + 1)) == "{}\n"


def test_receive_byte_cap_holds_one_completed_frame_until_consumers_drain():
    rt, c, mock, _ = _lua_env(chunk=1024 * 1024)
    assert _connect(c, mock)
    size = 3 * 1024 * 1024
    frames = [letter * size for letter in "abc"] + ["{}"]
    mock.inbox = "\n".join(frames) + "\n"
    for _ in range(200):
        c.pump()
    status = c.queue_status()
    assert status.receive_lines == 2 and status.receive_bytes == 2 * size
    assert status.ready_receive_bytes == size
    assert status.pending_receive_bytes <= status.read_chunk
    assert [c.receive(), c.receive()] == frames[:2]
    c.pump()
    assert [c.receive(), c.receive()] == frames[2:]
    assert c.receive() is None


@pytest.mark.parametrize("excess", [0, 1])
def test_receive_limit_boundary_is_identical_for_complete_and_split_frames(excess):
    rt, c, mock, _ = _lua_env(chunk=1024 * 1024)
    assert _connect(c, mock)
    payload = "x" * (c.queue_status().max_line + excess)
    mock.inbox = payload + "\n"
    for _ in range(70):
        c.pump()
    assert c.receive() == (None if excess else payload)
    assert c.receive() is None


def test_closed_socket_tail_cannot_deliver_a_command_without_a_live_reply_path():
    rt, c, mock, _ = _lua_env(chunk=1024)
    assert _connect(c, mock)
    mock.inbox = '{"commands":[{"cmd":"force_faint"}]}\n'
    mock.receive_error = "closed"
    c.pump()
    assert c.connected() is False
    assert c.receive() is None
    status = c.queue_status()
    assert status.receive_lines == status.receive_bytes == status.partial_receive_bytes == 0


def test_disconnect_clears_a_backpressured_complete_frame_and_chunk_remainder():
    rt, c, mock, _ = _lua_env(chunk=8192)
    assert _connect(c, mock)
    mock.inbox = '{}\n' * 1000
    c.pump()
    assert c.queue_status().ready_receive_bytes > 0
    assert c.queue_status().pending_receive_bytes > 0
    c.disconnect()
    status = c.queue_status()
    assert status.ready_receive_bytes == status.pending_receive_bytes == 0
    assert status.receive_lines == status.receive_bytes == status.partial_receive_bytes == 0


def test_session_mode_never_flushes_old_outbound_frames_after_disconnect():
    rt, c, mock, _ = _lua_env(chunk=8)
    def sent():
        return "".join(mock.sent[i] for i in range(1, len(mock.sent) + 1))
    c.init("127.0.0.1", 1, rt.table_from({"discard_on_disconnect": True}))
    assert c.send("old event " * 10)
    c.pump()
    assert c.queue_status().send_offset > 0
    c.disconnect()
    status = c.queue_status()
    assert status.send_lines == status.send_bytes == status.send_offset == 0
    previous = sent()
    for _ in range(40):
        c.pump()
    assert sent() == previous
    assert c.send("fresh hello")
    for _ in range(4):
        c.pump()
    assert sent() == previous + "fresh hello\n"
