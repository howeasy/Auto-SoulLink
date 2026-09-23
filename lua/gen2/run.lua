-- lua/gen2/run.lua — BizHawk entry for the Gen 2 PRODUCTION client.
--
-- Builds the graph through Entry.build only: the cartridge must be admitted by its actual
-- sha1 (G1 ADMITTED, owner ruling O-22, with its U1/U2 PHYSICAL receipts re-validated at
-- load). Today that is Crystal 1.0; Gold/Silver (G1 PENDING), an unknown hash or a non-Gen 2
-- cartridge is refused here with a console line and no client. Everything game-related is
-- built by lua/gen2/entry.lua; this file only supplies the BizHawk-shaped live io, the
-- LuaSocket transport, the HUD and the frame loop.
--
-- Exposed for gates and the H1 duo driver (nil unless admitted): SLINK_GEN2_CLIENT (the client;
-- its on_event/handle_command and connector.send are looked up per call, so wrappers work),
-- SLINK_GEN2_PARTS (production_admitted=true, qualification, pack, title, profile, ...),
-- SLINK_GEN2_CHECKPOINT.
--
-- A top-level --lua= script sees source == "main" (no path), so the repo root comes from
-- SLINK_ROOT first, exactly as lua/gen1/run.lua falls back when it has no path.
local _dir = (debug.getinfo(1, "S").source:match("@(.+[/\\])") or "./")
local ROOT = os.getenv("SLINK_ROOT") or _dir:gsub("[/\\]lua[/\\]gen2[/\\]?$", "")
if ROOT == _dir then ROOT = _dir .. "../.." end
package.path = ROOT .. "/lua/?.lua;" .. package.path

local Entry = dofile(ROOT .. "/lua/gen2/entry.lua")
local C = require("connector")
local H = require("hud")

local host = SLINK_HOST or os.getenv("SLINK_HOST") or "127.0.0.1"
local port = tonumber(SLINK_PORT or os.getenv("SLINK_PORT") or 54321)
local player = SLINK_PLAYER or os.getenv("SLINK_PLAYER") or "a"
SLINK_GEN2_CLIENT, SLINK_GEN2_PARTS, SLINK_GEN2_CHECKPOINT = nil, nil, nil

local function rom_u8(addr) return memory.read_u8(addr, "ROM") end
local title, header = Entry.detect_title(rom_u8)
if not title then
    console.log("[SLink-gen2] not a Gen 2 cartridge (header '" .. tostring(header) .. "')")
    return
end

local json = dofile(ROOT .. "/lua/json_codec.lua")
local handle = assert(io.open(ROOT .. "/" .. Entry.PACK_FILES[Entry.PACKS[title].pack].profile, "rb"))
local HROMBANK = json.decode(handle:read("*a")).titles[title].ram.hROMBank
handle:close()

-- The actual mapping, observed per call: ROM0/WRAM0/HRAM are bank 0, ROMX is the hROMBank
-- shadow (the same observation the U2 PHYSICAL gate made), WRAMX is SVBK ($FF70, 0 selects 1).
-- reads.lua/signals.lua/writes.lua refuse whatever this refuses.
local function wram_bank()
    local svbk = memory.read_u8(0xFF70, "System Bus") % 8
    return svbk == 0 and 1 or svbk
end
local function bank_valid(bank, addr, n)
    local last = addr + n - 1
    if last < 0x4000 or (addr >= 0xC000 and last < 0xD000) or (addr >= 0xFF80 and last < 0xFFFF) then
        return bank == 0
    end
    if addr >= 0x4000 and last < 0x8000 then return bank == memory.read_u8(HROMBANK, "System Bus") end
    if addr >= 0xD000 and last < 0xE000 then return bank == wram_bank() end
    return false
end
local io_ = {
    cart_ram_linear = true,
    read_u8 = function(addr, d) return memory.read_u8(addr, d or "System Bus") end,
    read_range = function(addr, len, d)
        local out = {}
        for i = 1, len do out[i] = memory.read_u8(addr + i - 1, d or "System Bus") end
        return out
    end,
    write_u8 = function(addr, v, d) return memory.write_u8(addr, v, d or "System Bus") end,
    bank_valid = bank_valid,
    stack_valid = function(sp, n) return bank_valid(sp < 0xD000 and 0 or wram_bank(), sp, n) end,
    domain_size = function(d) return memory.getmemorydomainsize(d) end,
    domains = function() return memory.getmemorydomainlist() end,
    register = function(name) return emu.getregister(name) end,
    framecount = function() return emu.framecount() end,
    on_bus_exec = function(fn, addr, name, d) return event.on_bus_exec(fn, addr, name, d or "System Bus") end,
    unregister = function(id) return event.unregisterbyid(id) end,
    saveram = function() if client and client.saveram then return client.saveram() end end, -- BizHawk's client lib
}

H.init({ screen_w = 160, screen_h = 144 })
C.init(host, port)

local parts, why = Entry.build({
    root = ROOT, title = title, io = io_, net = C, hud = H, player = player,
    rom_size = memory.getmemorydomainsize("ROM"), read_rom_u8 = rom_u8,
    log = function(t) console.log(t) end,
})
if not parts then
    console.log("[SLink-gen2] " .. title .. " cartridge refused (production admission): " .. tostring(why))
    return
end
local gen2 = parts.client
local ok, err = pcall(function() gen2:start() end)
if not ok then
    console.log("[SLink-gen2] refused to start: " .. tostring(err))
    return
end
console.log(string.format("[SLink-gen2] %s/%s PRODUCTION (%s, G1 %s) player %s -> %s:%d (rom %s)",
                          parts.pack, parts.title, parts.qualification, parts.data.admission.gate.state,
                          player, host, port, parts.profile.rom_sha1:sub(1, 8)))

SLINK_GEN2_CLIENT, SLINK_GEN2_PARTS, SLINK_GEN2_CHECKPOINT = gen2, parts, parts.checkpoint

event.onframeend(function()
    local fok, ferr = pcall(function() gen2:frame_end() end)
    if not fok then console.log("[SLink-gen2] frame error: " .. tostring(ferr)) end
    H.render()
end)
event.onexit(function() pcall(function() gen2:stop() end) end)
