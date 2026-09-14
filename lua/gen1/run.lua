-- lua/gen1/run.lua — BizHawk entry for the Gen 1 client.
--
-- Loaded by lua/slink_gen1.lua (which sets SLINK_HOST / SLINK_PORT / SLINK_PLAYER) or directly
-- by a live gate. Everything game-related is built by lua/gen1/entry.lua; this file only
-- supplies the BizHawk-shaped io, the LuaSocket transport, the HUD and the frame loop.
local _dir = (debug.getinfo(1, "S").source:match("@(.+[/\\])") or "./")
local ROOT = _dir:gsub("[/\\]lua[/\\]gen1[/\\]?$", "")
if ROOT == _dir then ROOT = _dir .. "../.." end
package.path = ROOT .. "/lua/?.lua;" .. package.path

local Entry = dofile(ROOT .. "/lua/gen1/entry.lua")
local C = require("connector")
local H = require("hud")

local host = SLINK_HOST or os.getenv("SLINK_HOST") or "127.0.0.1"
local port = tonumber(SLINK_PORT or os.getenv("SLINK_PORT") or 54321)
local player = SLINK_PLAYER or os.getenv("SLINK_PLAYER") or "a"

local deps = Entry.bizhawk_deps()
local title, header = Entry.detect_title(function(addr) return memory.read_u8(addr, "ROM") end)
if not title then
    console.log("[SLink-gen1] not a Gen 1 cartridge (header '" .. tostring(header) .. "')")
    return
end

local rom_sha1 = (gameinfo and gameinfo.getromhash and gameinfo.getromhash() or ""):lower()
H.init({ screen_w = 160, screen_h = 144 })
C.init(host, port)

local client = Entry.build({
    root = ROOT, io = deps, net = C, hud = H, title = title, player = player, rom_sha1 = rom_sha1,
    log = function(t) console.log(t) end,
})
local ok, why = pcall(function() client:start() end)
if not ok then
    console.log("[SLink-gen1] refused to start: " .. tostring(why))
    return
end
console.log(string.format("[SLink-gen1] %s player %s -> %s:%d (rom %s)", title, player, host, port, rom_sha1:sub(1, 8)))

-- Exposed for live gates and the console.
SLINK_GEN1_CLIENT = client

event.onframeend(function()
    local fok, ferr = pcall(function() client:frame_end() end)
    if not fok then console.log("[SLink-gen1] frame error: " .. tostring(ferr)) end
    H.render()
end)
event.onexit(function() pcall(function() client:stop() end) end)
