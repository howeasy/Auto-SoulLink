-- lua/gen3/run.lua — BizHawk entry for the Gen 3 (FRLG) production client.
--
-- Loaded by lua/slink.lua's Gen 3 route (mirrors lua/gen1/run.lua 1:1, per
-- docs/gen3/research/p4_gen1_contract_map.md §3.5). Everything game-related is built by
-- lua/gen3/entry.lua; this file only supplies the BizHawk-shaped io/ev, the LuaSocket
-- transport, the HUD and the frame loop.
--
-- The foundation (gen3_frlg vs gen3_rr, clean/named) is decided by Entry.admit from the
-- cartridge's hash/anchors/header, never guessed here.
local _dir = (debug.getinfo(1, "S").source:match("@(.+[/\\])") or "./")
local ROOT = _dir:gsub("[/\\]lua[/\\]gen3[/\\]?$", "")
if ROOT == _dir then ROOT = _dir .. "../.." end
package.path = ROOT .. "/lua/?.lua;" .. package.path

local Entry = dofile(ROOT .. "/lua/gen3/entry.lua")
local C = require("connector")
local H = require("hud")

local host = SLINK_HOST or os.getenv("SLINK_HOST") or "127.0.0.1"
local port = tonumber(SLINK_PORT or os.getenv("SLINK_PORT") or 54321)
local player = SLINK_PLAYER or os.getenv("SLINK_PLAYER") or "a"

-- The io/ev adapters (copied from lua/gen3/shadow_run.lua build_io:58-85 / build_ev:92-119,
-- not dofile'd from it: shadow_run.lua is P3's read-only observer bootstrap and is
-- deliberately not shipped in the player release -- tools/make_release.py _LUA_GEN3). This is
-- the same shape, plus the one real write sink and saveram P3 deliberately refused.
local io_ = {
    read_u8    = function(addr) return memory.read_u8(addr, "System Bus") end,
    read_u16   = function(addr) return memory.read_u16_le(addr, "System Bus") end,
    read_u32   = function(addr) return memory.read_u32_le(addr, "System Bus") end,
    read_bytes = function(addr, len)
        local out = {}
        for i = 1, len do out[i] = memory.read_u8(addr + i - 1, "System Bus") end
        return out
    end,
    rom_read = function(off, len)
        local out = {}
        for i = 1, len do out[i] = memory.read_u8(off + i - 1, "ROM") end
        return out
    end,
    framecount = function() return emu.framecount() end,
    register   = function(name) return emu.getregister(name) end,
    write_u8   = function(addr, v) return memory.write_u8(addr, v, "System Bus") end,
    saveram    = function() if client and client.saveram then return client.saveram() end end,
}

-- Hook names prefixed "SLink-gen3-" (never "-shadow-": this instance mutates game state).
local ev = {
    on_bus_exec = function(fn, addr, name)
        return event.on_bus_exec(fn, addr, "SLink-gen3-" .. tostring(name))
    end,
    unregister = function(id) return event.unregisterbyid(id) end,
}

local ok_hc, header_code = pcall(Entry.header_code, io_.rom_read)
local admitted, why = Entry.admit({
    root = ROOT, json = dofile(ROOT .. "/lua/json_codec.lua"),
    rom_hash = gameinfo and gameinfo.getromhash and gameinfo.getromhash() or "",
    rom_read = io_.rom_read, header_code = ok_hc and header_code or "",
})
if not admitted then
    local msg = "[SLink-gen3] refused: " .. tostring(why)
    console.log(msg)
    H.init({ screen_w = 240, screen_h = 160 })
    H.show(msg, 255, 80, 80, 600)
    H.render()
    return
end

H.init({ screen_w = 240, screen_h = 160 })
C.init(host, port)

local client = Entry.build({
    root = ROOT, mode = "production", io = io_, ev = ev, net = C, hud = H,
    pack = admitted.pack, title = admitted.title, kind = admitted.kind, player = player,
    rom_sha1 = admitted.rom_hash, log = function(t) console.log(t) end,
})
local ok, err = pcall(function() client:start() end)
if not ok then
    local msg = "[SLink-gen3] refused to start: " .. tostring(err)
    console.log(msg)
    H.show(msg, 255, 80, 80, 600)
    H.render()
    return
end
console.log(string.format("[SLink-gen3] %s/%s (%s by %s) player %s -> %s:%d (rom %s)",
                          admitted.pack, admitted.title, admitted.kind, admitted.admitted_by,
                          player, host, port, tostring(admitted.rom_hash):sub(1, 8)))

-- Exposed for live gates and the console.
SLINK_GEN3_CLIENT = client

event.onframeend(function()
    local fok, ferr = pcall(function() client:frame_end() end)
    if not fok then console.log("[SLink-gen3] frame error: " .. tostring(ferr)) end
    H.render()
end)
event.onexit(function() pcall(function() client:stop() end) end)
