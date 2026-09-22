-- lua/gen2/run.lua — BizHawk entry for the Gen 2 client (P3b gates only).
--
-- Launchable directly with --lua= for live gates. It builds the SOURCE/MODEL CANDIDATE
-- graph through Entry.build_candidate, never Entry.build: production admission refuses
-- while G1 is PENDING, and the player launcher (lua/slink.lua) is switched here only at
-- the G3 cutover. Everything game-related is built by lua/gen2/entry.lua; this file only
-- supplies the BizHawk-shaped io, the LuaSocket transport, the HUD and the frame loop.
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

local function rom_u8(addr) return memory.read_u8(addr, "ROM") end
local title, header = Entry.detect_title(rom_u8)
if not title then
    console.log("[SLink-gen2] not a Gen 2 cartridge (header '" .. tostring(header) .. "')")
    return
end

local json = dofile(ROOT .. "/lua/json_codec.lua")
local files = Entry.PACK_FILES[Entry.PACKS[title].pack]
local function pack_json(key)
    local handle = assert(io.open(ROOT .. "/" .. files[key], "rb"))
    local value = json.decode(handle:read("*a"))
    handle:close()
    return value
end

-- The actual mapping, observed per call: ROM0/WRAM0/HRAM are bank 0, ROMX is the hROMBank
-- shadow (a shadow, not a mapper read: the binder's bank qualification stays OPEN), WRAMX is
-- SVBK ($FF70, 0 selects 1). reads.lua/signals.lua/writes.lua refuse whatever this refuses.
local HROMBANK = pack_json("profile").titles[title].ram.hROMBank
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
    model_only = true, cart_ram_linear = true,
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
    register = function(name) return emu.getregister(name) end,
    framecount = function() return emu.framecount() end,
    on_bus_exec = function(fn, addr, name, d) return event.on_bus_exec(fn, addr, name, d or "System Bus") end,
    unregister = function(id) return event.unregisterbyid(id) end,
    saveram = function() if client and client.saveram then return client.saveram() end end, -- BizHawk's client lib
}

-- The source-candidate checkpoint: check() refuses until P3b.5 qualifies it, so the hello
-- waits for a battle and no write is attempted. inspect_candidate() is there for the gate.
local checkpoint = dofile(ROOT .. "/lua/gen2_write_safety.lua").new(pack_json("checkpoint"), title, io_,
    dofile(ROOT .. "/lua/gb_checkpoint.lua"), {
        capture = function() return emu.framecount() end,
        valid = function(held) return held == emu.framecount() end,
        admitted = function() return false end, -- production admission is G1 PENDING
        no_conflicting_owner = function() return true end,
        mapped_rom_bank = function() return memory.read_u8(HROMBANK, "System Bus") end,
        effective_wram_bank = wram_bank,
    })

H.init({ screen_w = 160, screen_h = 144 })
C.init(host, port)

local parts, why = Entry.build_candidate({
    candidate_only = true, root = ROOT, title = title, io = io_, net = C, hud = H, player = player,
    checkpoint = checkpoint, log = function(t) console.log(t) end,
    -- ponytail: no ownership proof exists for the candidate graph (P3b.5), so every write is
    -- refused by the permit's authorize policy; the lifetime is the arming frame.
    write_policy = {
        authorize = function() return false end,
        pointer_stable = function() return true end,
        lifetime = { capture = function() return emu.framecount() end,
                     valid = function(token) return token == emu.framecount() end },
        provenance = function() return { site = "lua/gen2/run.lua candidate" } end,
    },
})
if not parts then
    console.log("[SLink-gen2] candidate graph refused: " .. tostring(why))
    return
end
local gen2 = parts.client
local ok, err = pcall(function() gen2:start() end)
if not ok then
    console.log("[SLink-gen2] refused to start: " .. tostring(err))
    return
end
console.log(string.format("[SLink-gen2] *** CANDIDATE GRAPH (Entry.build_candidate, NOT Entry.build): "
                          .. "%s/%s SOURCE/MODEL only, production admission G1 PENDING, no PHYSICAL claim *** "
                          .. "player %s -> %s:%d (rom %s)", parts.pack, title, player, host, port,
                          parts.profile.rom_sha1:sub(1, 8)))

-- Exposed for live gates and the console.
SLINK_GEN2_CLIENT, SLINK_GEN2_PARTS, SLINK_GEN2_CHECKPOINT = gen2, parts, checkpoint

event.onframeend(function()
    local fok, ferr = pcall(function() gen2:frame_end() end)
    if not fok then console.log("[SLink-gen2] frame error: " .. tostring(ferr)) end
    H.render()
end)
event.onexit(function() pcall(function() gen2:stop() end) end)
