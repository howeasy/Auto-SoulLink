--[[
  lua/connector.lua — Non-blocking LuaSocket TCP client for SLink.

  Implements Archipelago's lag-free technique: LuaSocket with settimeout(0)
  so send/receive never block BizHawk's emulation thread.

  Protocol: newline-delimited JSON.
    Lua → Python : {"event":"...", "player":"a", "seq":N, ...}\n
    Python → Lua : {"commands":[{"cmd":"..."}]}\n

  Requirements:
    lua/socket.lua                        (LuaSocket wrapper — included)
    lua/x64/socket-windows-5-4.dll        (Lua 5.4 / BizHawk 2.9)
    lua/x64/socket-windows-5-1.dll        (Lua 5.1 / older BizHawk)
    → Copy from: <Archipelago>/data/lua/x64/

  API:
    local C = require("connector")
    C.init(host, port)    -- call once at startup; attempts first connect
    C.send(json_str)      -- queue a message to send (non-blocking)
    C.receive()           -- return next complete response line, or nil
    C.pump()              -- call once per frame: flushes send queue, fills receive queue
    C.connected()         -- returns true if socket is open
    C.disconnect()        -- close the socket (called automatically on error)
--]]

package.loaded["socket"] = nil          -- always reload fresh
local socket = require("socket")

local M = {}

local function _safe_close(sock)
    if sock then pcall(function() sock:close() end) end
end

-- ── Private state ─────────────────────────────────────────────────────────────
local _host, _port
local _sock           = nil
local _connected      = false
local _send_queue     = {}      -- {string} complete wire frames, including LF
local _line_queue     = {}      -- {string} complete received lines ready to read
local _send_bytes, _line_bytes = 0, 0
-- PARTIAL I/O STATE. With settimeout(0) LuaSocket may move only part of a line and reports
-- how far it got in its THIRD return value. Both directions used to discard that: a partial
-- send left the whole line queued and re-sent the bytes the peer already had, and a partial
-- receive dropped the bytes LuaSocket had already taken off the socket. Neither ever fired,
-- because a small JSON line crosses loopback in one piece -- but "small" was an assumption,
-- and the ROM content payload is kilobytes.
local _send_offset    = 0       -- bytes of _send_queue[1] the peer has already taken
local _recv_parts, _recv_size = {}, 0
local _recv_pending   = ""      -- bounded remainder of the last socket chunk
local _ready_line     = nil     -- one complete frame waiting for receive-queue space
local _drop_until_newline = false  -- true while skipping the tail of an over-long line
local MAX_LINE        = 4 * 1024 * 1024   -- matches the server's own per-line cap
local MAX_QUEUE_BYTES = 8 * 1024 * 1024
local MAX_QUEUE_LINES = 128
local READ_CHUNK      = 8192
local IO_BUDGET       = 65536   -- maximum socket bytes per direction, per pump
local _fail_logged = false   -- one connect-failure message per outage
local _reconnect_cd   = 0       -- frames remaining before next reconnect attempt

local RECONNECT_FRAMES = 30     -- ~0.5 s at 60 fps (initial retry interval)
local RECONNECT_MAX   = 1800   -- ~30 s cap (exponential backoff)
local _reconnect_step = RECONNECT_FRAMES  -- current backoff interval
local _discard_on_disconnect = false

local function _clear_receive()
    _line_queue, _line_bytes = {}, 0
    _recv_parts, _recv_size = {}, 0
    _recv_pending, _ready_line = "", nil
    _drop_until_newline = false
end

local function _queue_line(line)
    if #_line_queue >= MAX_QUEUE_LINES or _line_bytes + #line > MAX_QUEUE_BYTES then
        return false
    end
    _line_queue[#_line_queue + 1] = line
    _line_bytes = _line_bytes + #line
    return true
end

local function _append_receive(part)
    if _drop_until_newline or #part == 0 then return end
    if _recv_size + #part > MAX_LINE then
        console.log("[SLink] inbound line exceeded " .. MAX_LINE
                    .. " bytes — discarding it and resyncing at the next newline")
        _recv_parts, _recv_size = {}, 0
        _drop_until_newline = true
        return
    end
    -- Coalesce small fragments. Repeated one-byte receives must not create
    -- millions of table entries or repeatedly copy the entire growing frame.
    local n = #_recv_parts
    if n > 0 and #_recv_parts[n] + #part <= READ_CHUNK then
        _recv_parts[n] = _recv_parts[n] .. part
    else
        _recv_parts[n + 1] = part
    end
    _recv_size = _recv_size + #part
end

local function _feed_receive(chunk)
    local start = 1
    while start <= #chunk do
        local newline = chunk:find("\n", start, true)
        _append_receive(chunk:sub(start, newline and newline - 1 or #chunk))
        if not newline then return end
        if _drop_until_newline then
            _drop_until_newline = false
        else
            local line = table.concat(_recv_parts)
            -- Allow CRLF framing without deleting illegal CR bytes inside JSON.
            if line:sub(-1) == "\r" then line = line:sub(1, -2) end
            if not _queue_line(line) then
                _ready_line = line
                _recv_pending = chunk:sub(newline + 1)
                _recv_parts, _recv_size = {}, 0
                return
            end
        end
        _recv_parts, _recv_size = {}, 0
        start = newline + 1
    end
end

-- ── Internal: connect attempt ─────────────────────────────────────────────────
-- Non-blocking connect: settimeout(0) so BizHawk never stalls.
-- On loopback this connects in < 1 ms; over LAN the OS returns EINPROGRESS
-- and the next pump() detects completion via a zero-length send.
local function _do_connect()
    _safe_close(_sock)
    _sock = nil
    _connected = false

    local s, err = socket.socket.tcp4()
    if not s then return false, err end

    s:settimeout(0)                     -- fully non-blocking (including connect)
    local ok, cerr = s:connect(_host, _port)

    if ok then
        -- Immediate success (common on loopback when server is running)
        _sock = s
        _connected = true
        _reconnect_step = RECONNECT_FRAMES  -- reset backoff on success
        return true
    elseif cerr == "timeout" or cerr == "Operation already in progress" then
        -- Connection in progress — store socket, we'll check on next pump()
        _sock = s
        _connected = false
        return false, "connecting"
    else
        _safe_close(s)
        return false, cerr
    end
end

-- Check if a pending non-blocking connect has completed.
local function _check_pending_connect()
    if not _sock or _connected then return end
    -- Attempt a zero-length send to probe the connection state.
    -- LuaSocket send returns: bytes_sent, err_msg, partial_idx
    -- On connected socket: 0, nil  (success)
    -- On still-connecting: nil, "timeout"  (not ready yet)
    -- On failed connect:   nil, "closed"/"refused"  (give up)
    local bytes, err = _sock:send("")
    if bytes then
        -- Send succeeded → connected
        _connected = true
        _reconnect_step = RECONNECT_FRAMES
        console.log(string.format("[SLink] TCP connected to %s:%d", _host, _port))
    elseif err == "timeout" then
        -- Still connecting, check again next frame
        return
    else
        -- Connect failed
        _safe_close(_sock)
        _sock = nil
    end
end

-- ── Public API ────────────────────────────────────────────────────────────────

--- Call once at script startup. Attempts an initial connection (non-blocking).
function M.init(host, port, options)
    -- Explicit initialization starts a different stream/run. In particular, a
    -- partial outgoing frame must not be delivered to a newly selected server.
    _send_queue, _send_bytes, _send_offset = {}, 0, 0
    _discard_on_disconnect = options and options.discard_on_disconnect == true or false
    _clear_receive()
    _host, _port = host, port
    local ok, err = _do_connect()
    if ok then
        console.log(string.format("[SLink] TCP connected to %s:%d", host, port))
    elseif err == "connecting" then
        console.log(string.format(
            "[SLink] TCP connecting to %s:%d (non-blocking)…", host, port))
    else
        console.log(string.format(
            "[SLink] TCP connect failed (%s:%d): %s — will retry every ~2 s",
            host, port, tostring(err)))
    end
end

--- Returns true while the socket is open and healthy.
function M.connected()
    return _connected
end

--- Queue a JSON string to be sent on the next pump().
--- The caller must NOT append \n — pump() does that.
function M.send(json_str)
    local reason
    if type(json_str) ~= "string" or #json_str == 0 then
        reason = "outbound frame must be a nonempty string"
    elseif #json_str > MAX_LINE then
        reason = "outbound frame exceeded " .. MAX_LINE .. " bytes"
    elseif json_str:find("[\r\n]") then
        reason = "outbound frame contains an unescaped line ending"
    elseif #_send_queue >= MAX_QUEUE_LINES or _send_bytes + #json_str + 1 > MAX_QUEUE_BYTES then
        reason = "outbound queue is full"
    end
    if reason then
        console.log("[SLink] send refused: " .. reason)
        return false, reason
    end
    local line = json_str .. "\n"
    _send_queue[#_send_queue + 1] = line
    _send_bytes = _send_bytes + #line
    return true
end

--- Return the next complete received line (without \n), or nil if none ready.
function M.receive()
    if not _connected or #_line_queue == 0 then return nil end
    local line = table.remove(_line_queue, 1)
    _line_bytes = _line_bytes - #line
    return line
end

--- Diagnostic snapshot; returned values cannot alter the internal limits.
function M.queue_status()
    return {send_lines = #_send_queue, send_bytes = _send_bytes, send_offset = _send_offset,
            receive_lines = #_line_queue, receive_bytes = _line_bytes,
            partial_receive_bytes = _recv_size, pending_receive_bytes = #_recv_pending,
            ready_receive_bytes = _ready_line and #_ready_line or 0,
            max_line = MAX_LINE, max_queue_bytes = MAX_QUEUE_BYTES,
            max_queue_lines = MAX_QUEUE_LINES, io_budget = IO_BUDGET, read_chunk = READ_CHUNK}
end

--- Call once per frame. Drives:
---   1. Reconnect logic when disconnected.
---   2. Send all queued lines (non-blocking; stops on timeout/error).
---   3. Receive all complete lines currently buffered (non-blocking).
function M.pump()
    -- ── Check pending non-blocking connect ────────────────────────────────────
    if _sock and not _connected then
        _check_pending_connect()
        if not _connected then return end  -- still connecting or failed
    end

    -- ── Reconnect (with exponential backoff) ──────────────────────────────────
    if not _connected then
        _reconnect_cd = _reconnect_cd - 1
        if _reconnect_cd <= 0 then
            _reconnect_cd = _reconnect_step
            -- Exponential backoff: double interval each failure, cap at RECONNECT_MAX
            _reconnect_step = math.min(_reconnect_step * 2, RECONNECT_MAX)
            local ok, err = _do_connect()
            if ok then
                console.log(string.format("[SLink] Reconnected to %s:%d", _host, _port))
                _fail_logged = false
            elseif err and err ~= "connecting" then
                -- Say WHY, once per outage. Silence here is the worst possible first-run
                -- experience: the emulator looks fine, the script looks fine, and nothing
                -- happens. Logged once rather than every backoff tick so a long outage does
                -- not bury the console.
                if not _fail_logged then
                    _fail_logged = true
                    console.log(string.format(
                        "[SLink] Cannot reach the server at %s:%d (%s). Is it running? " ..
                        "Start it with:  python -m server.server", _host, _port, tostring(err)))
                end
            end
            -- If err == "connecting", _check_pending_connect will handle it next frame
        end
        return
    end

    -- ── Send ──────────────────────────────────────────────────────────────────
    -- Sends lines from the queue one at a time.
    -- settimeout(0) means send() returns immediately if the OS buffer is full
    -- having written only PART of the line. That is handled rather than assumed
    -- away: the comment here used to claim "a single JSON line is never > 64 KB",
    -- which stopped being true the moment a ROM content payload was sent.
    local send_budget = IO_BUDGET
    while #_send_queue > 0 and send_budget > 0 do
        local line = _send_queue[1]
        -- Resume at the first byte the peer has NOT taken. send(data, i) is 1-based and
        -- both success and timeout report the index of the last byte written, so the
        -- offset survives however many frames the OS buffer stays full.
        local last_requested = math.min(#line, _send_offset + send_budget)
        local bytes, err, lastindex = _sock:send(line, _send_offset + 1, last_requested)
        if not bytes and err ~= "timeout" then
            -- "closed" or other error
            console.log("[SLink] TCP send error: " .. tostring(err) .. " — disconnecting")
            M.disconnect()
            return
        end
        local progress = bytes or lastindex or _send_offset
        if type(progress) ~= "number" or progress % 1 ~= 0
            or progress < _send_offset or progress > last_requested then
            console.log("[SLink] invalid socket send offset — disconnecting")
            M.disconnect()
            return
        end
        local advanced = progress - _send_offset
        _send_offset = progress
        send_budget = send_budget - advanced
        if _send_offset == #line then
            _send_bytes = _send_bytes - #line
            table.remove(_send_queue, 1)
            _send_offset = 0
        end
        if not bytes or advanced == 0 then break end
    end

    -- ── Receive ───────────────────────────────────────────────────────────────
    -- Fixed-size reads bound allocation inside LuaSocket itself. A *l read can
    -- allocate an unlimited complete line before a Lua-side size check sees it.
    if _ready_line then
        if not _queue_line(_ready_line) then return end
        _ready_line = nil
    end
    if #_recv_pending > 0 then
        local pending = _recv_pending
        _recv_pending = ""
        _feed_receive(pending)
    end
    local receive_budget = IO_BUDGET
    while not _ready_line and #_line_queue < MAX_QUEUE_LINES and receive_budget > 0 do
        local requested = math.min(READ_CHUNK, receive_budget)
        local data, err, partial = _sock:receive(requested)
        local chunk = data or partial or ""
        if type(chunk) ~= "string" or #chunk > requested then
            console.log("[SLink] invalid socket receive size — disconnecting")
            M.disconnect()
            return
        end
        receive_budget = receive_budget - #chunk
        if #chunk > 0 then _feed_receive(chunk) end
        if not data and err ~= "timeout" then
            -- "closed" or other error
            console.log("[SLink] TCP receive error: " .. tostring(err) .. " — disconnecting")
            M.disconnect()
            return
        end
        if not data or #chunk == 0 then break end
    end
end

--- Close the socket and schedule a reconnect attempt.
function M.disconnect()
    _safe_close(_sock)
    _sock = nil
    _connected = false
    -- A new socket starts a new byte stream: resuming a half-written line or prepending a
    -- half-read one would corrupt the first message of the next session.
    _send_offset = 0
    if _discard_on_disconnect then _send_queue, _send_bytes = {}, 0 end
    -- Completed responses belong to the old stream too. They must not execute
    -- after disconnect or after a different save/client session reconnects.
    _clear_receive()
    _reconnect_cd = RECONNECT_FRAMES      -- first retry after ~0.5 s
    _reconnect_step = RECONNECT_FRAMES    -- reset backoff
end

return M
