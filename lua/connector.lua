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
local _send_queue     = {}      -- {string} lines waiting to be sent
local _line_queue     = {}      -- {string} complete received lines ready to read
local _reconnect_cd   = 0       -- frames remaining before next reconnect attempt

local RECONNECT_FRAMES = 30     -- ~0.5 s at 60 fps (initial retry interval)
local RECONNECT_MAX   = 1800   -- ~30 s cap (exponential backoff)
local _reconnect_step = RECONNECT_FRAMES  -- current backoff interval

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
function M.init(host, port)
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
    table.insert(_send_queue, json_str)
end

--- Return the next complete received line (without \n), or nil if none ready.
function M.receive()
    if #_line_queue == 0 then return nil end
    return table.remove(_line_queue, 1)
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
            end
            -- If err == "connecting", _check_pending_connect will handle it next frame
        end
        return
    end

    -- ── Send ──────────────────────────────────────────────────────────────────
    -- Sends lines from the queue one at a time.
    -- settimeout(0) means send() returns immediately if the OS buffer is full
    -- (extremely rare for loopback; a single JSON line is never > 64 KB).
    while #_send_queue > 0 do
        local line = _send_queue[1]
        local bytes, err = _sock:send(line .. "\n")
        if bytes then
            table.remove(_send_queue, 1)    -- sent successfully
        elseif err == "timeout" then
            break                           -- OS buffer full; retry next frame
        else
            -- "closed" or other error
            console.log("[SLink] TCP send error: " .. tostring(err) .. " — disconnecting")
            M.disconnect()
            return
        end
    end

    -- ── Receive ───────────────────────────────────────────────────────────────
    -- receive("*l") reads one complete line (up to \n, not including it).
    -- With settimeout(0) it returns nil,"timeout" immediately if no full line.
    while true do
        local line, err = _sock:receive("*l")
        if line then
            table.insert(_line_queue, line)
        elseif err == "timeout" then
            break                           -- no more complete lines right now
        else
            -- "closed" or other error
            console.log("[SLink] TCP receive error: " .. tostring(err) .. " — disconnecting")
            M.disconnect()
            break
        end
    end
end

--- Close the socket and schedule a reconnect attempt.
function M.disconnect()
    _safe_close(_sock)
    _sock = nil
    _connected = false
    _reconnect_cd = RECONNECT_FRAMES      -- first retry after ~0.5 s
    _reconnect_step = RECONNECT_FRAMES    -- reset backoff
end

return M
