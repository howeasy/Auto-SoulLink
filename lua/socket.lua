-----------------------------------------------------------------------------
-- LuaSocket helper module
-- Author: Diego Nehab
-- Source: https://github.com/ArchipelagoMW/Archipelago (MIT licence)
-- Adapted from Archipelago data/lua/socket.lua for SLink.
--
-- Detects OS / arch / Lua version, loads the matching native socket DLL
-- from lua/x64/socket-windows-5-4.dll (Lua 5.4 / BizHawk 2.9)
-- or  lua/x64/socket-windows-5-1.dll (Lua 5.1 / older BizHawk).
--
-- Copy the required DLL from your Archipelago installation:
--   <Archipelago>/data/lua/x64/socket-windows-5-4.dll  →  lua/x64/
-----------------------------------------------------------------------------
local base   = _G
local string = require("string")
local math   = require("math")

local function get_lua_version()
    local major, minor = _VERSION:match("Lua (%d+)%.(%d+)")
    assert(tonumber(major) == 5)
    if tonumber(minor) >= 4 then return "5-4" end
    return "5-1"
end

local function get_os()
    local the_os, ext, arch
    if package.config:sub(1, 1) == "\\" then
        the_os, ext = "windows", "dll"
        arch = os.getenv("PROCESSOR_ARCHITECTURE") or "AMD64"
    else
        the_os, ext = "linux", "so"
        arch = "x86_64"
    end
    arch = arch:find("64") and "x64" or "x86"
    return the_os, ext, arch
end

local function get_socket_path()
    local the_os, ext, arch = get_os()
    -- Resolve relative to this script's own location, not the process CWD.
    -- socket.lua always lives in lua/, so the DLL is always at lua/x64/...
    local src = debug.getinfo(1, "S").source
    local script_dir = src:match("@(.+[/\\])") or ""
    return script_dir .. arch .. "/socket-" .. the_os .. "-" .. get_lua_version() .. "." .. ext
end

local socket_path = get_socket_path()
local socket = assert(
    package.loadlib(socket_path, "luaopen_socket_core"),
    "Cannot load LuaSocket from: " .. socket_path ..
    "\nCopy socket-windows-5-4.dll from Archipelago/data/lua/x64/ into lua/x64/"
)()

local M = {}
if setfenv then setfenv(1, M) else _ENV = M end

M.socket = socket

-----------------------------------------------------------------------------
-- Exported helpers
-----------------------------------------------------------------------------
function connect(address, port, laddress, lport)
    local sock, err = socket.tcp()
    if not sock then return nil, err end
    if laddress then
        local res, err2 = sock:bind(laddress, lport, -1)
        if not res then return nil, err2 end
    end
    local res, err2 = sock:connect(address, port)
    if not res then return nil, err2 end
    return sock
end

function bind(host, port, backlog)
    local sock, err = socket.tcp()
    if not sock then return nil, err end
    sock:setoption("reuseaddr", true)
    local res, err2 = sock:bind(host, port)
    if not res then return nil, err2 end
    res, err2 = sock:listen(backlog)
    if not res then return nil, err2 end
    return sock
end

try = socket.newtry()

function choose(table)
    return function(name, opt1, opt2)
        if base.type(name) ~= "string" then
            name, opt1, opt2 = "default", name, opt1
        end
        local f = table[name or "nil"]
        if not f then base.error("unknown key (" .. base.tostring(name) .. ")", 3)
        else return f(opt1, opt2) end
    end
end

BLOCKSIZE = 2048

return M
