-- lua/gen4/run.lua -- BizHawk entry (composition root) for the rewritten Gen 4 (HGSS / hg-engine) client.
--
-- Routed to by the launcher (G3a; docs/gen4/reviews/DECISIONS_2026-10-03_launcher.md) or dofile'd directly
-- by a gate. Mirrors lua/gen3/run.lua: lua/gen4/entry.lua decides admission, lua/gen4/client.lua builds
-- the game driver over the shared core Session; this file only supplies the BizHawk-shaped io, the
-- LuaSocket transport (lua/connector.lua), the HUD (lua/hud.lua) and the frame loop. It names no title
-- address and no pack: those live in the packs and in Entry/Client.
--
-- Entry.admit_routed runs here even though Client.new admits again: a refusal must be shown by name
-- (console + HUD) before anything is built, and a dofile'd run cannot skip the gate.
local _dir = (debug.getinfo(1, "S").source:match("@(.+[/\\])") or "./")
local ROOT = _dir:gsub("[/\\]lua[/\\]gen4[/\\]?$", "")
if ROOT == _dir then ROOT = _dir .. "../.." end
package.path = ROOT .. "/lua/?.lua;" .. package.path

local Entry = dofile(ROOT .. "/lua/gen4/entry.lua")
local Client = dofile(ROOT .. "/lua/gen4/client.lua")
local Inputs = dofile(ROOT .. "/lua/gen4/inputs.lua")
local C = require("connector")
local H = require("hud")
local START_REFUSED = "SLINK COULD NOT START - SEE LOG"
local SCREEN = { screen_w = 256, screen_h = 192 }      -- one NDS screen, the HUD's frame of reference

local host = SLINK_HOST or os.getenv("SLINK_HOST") or "127.0.0.1"
local port = tonumber(SLINK_PORT or os.getenv("SLINK_PORT") or 54321)
local player = SLINK_PLAYER or os.getenv("SLINK_PLAYER") or "a"

local PLAT = Client.PLATFORM
local BUS = PLAT.bus_domain
-- The NDS boot copies the cartridge header to the top of main RAM; the address is a PLATFORM fact
-- (Client.PLATFORM.header_copy, cited there), so run.lua names no address at all.
local HEADER_COPY = PLAT.header_copy

-- BizHawk memory adapters (little-endian), all over the ARM9 system bus the client names.
local io_ = {
    read_u8    = function(addr, domain) return memory.read_u8(addr, domain or BUS) end,
    read_u16   = function(addr, domain) return memory.read_u16_le(addr, domain or BUS) end,
    read_u32   = function(addr, domain) return memory.read_u32_le(addr, domain or BUS) end,
    read_range = function(addr, len, domain)
        local out = {}
        for i = 1, len do out[i] = memory.read_u8(addr + i - 1, domain or BUS) end
        return out
    end,
    write_u8   = function(addr, v) return memory.write_u8(addr, v, BUS) end,
    write_u16  = function(addr, v) return memory.write_u16_le(addr, v, BUS) end,
    write_u32  = function(addr, v) return memory.write_u32_le(addr, v, BUS) end,
    framecount = function() return emu.framecount() end,
    register   = function(name) return emu.getregister(name) end,
    -- Hook names are prefixed "SLink-gen4-": this instance mutates game state.
    on_bus_exec = function(fn, addr, name, domain)
        return event.on_bus_exec(fn, addr, "SLink-gen4-" .. tostring(name), domain or BUS)
    end,
    unregister = function(id) return event.unregisterbyid(id) end,
}

local function refuse(what, why)
    console.log("[SLink-gen4] " .. what .. ": " .. tostring(why))
    H.init(SCREEN)
    H.show(START_REFUSED, 255, 80, 80, 600)
    H.render()
end

local json = dofile(ROOT .. "/lua/json_codec.lua")
local rom_hash = gameinfo and gameinfo.getromhash and gameinfo.getromhash() or ""
local ok_hc, header_code = pcall(Entry.header_code, function(off, len)
    return io_.read_range(HEADER_COPY + off, len)
end)
header_code = ok_hc and header_code or ""
local admitted, why = Entry.admit_routed({
    root = ROOT, json = json, rom_hash = rom_hash, header_code = header_code,
    read_ram = function(addr, len) return io_.read_range(addr, len) end,
})
if not admitted then return refuse("refused", why) end

H.init(SCREEN)
C.init(host, port)

-- The optional inputs (area ids, trainer-name charmap, the ball read). lua/gen4/inputs.lua builds
-- each one from the pack only and omits (never nils) the ones whose pack fact is absent, so the
-- client's own optional seams stay optional.
--
-- `save_array` binds LATE on purpose: Inputs.build runs before Client.new, and the reader over a save
-- array is the CLIENT's read layer (client:save_array, over its own R.save_data -> R.array), not a
-- second copy of it in this file. Until the client exists the seam refuses by name; a producer body
-- only calls it later, after Client.new has bound the local.
local pack_def = Entry.PACKS[admitted.pack]
local client
local inputs = Inputs.build({
    root = ROOT, json = json, pack_profile = pack_def and pack_def.profile, title = admitted.title,
    save_array = function(array_id)
        if not client then return nil, "client not built" end
        return client:save_array(array_id)
    end,
    log = function(t) console.log(t) end,
})
client, why_build = Client.new({
    root = ROOT, json = json, io = io_, net = C, hud = H, player = player,
    rom_hash = rom_hash, header_code = header_code,
    log = function(t) console.log(t) end,
    area_of = inputs.area_of, charmap = inputs.charmap, has_pokeballs = inputs.has_pokeballs,
})
if not client then return refuse("refused to start", why_build) end
local ok, err = pcall(function() client:start() end)
if not ok then return refuse("refused to start", err) end
console.log(string.format("[SLink-gen4] %s/%s (%s) player %s -> %s:%d (rom %s)",
                          admitted.pack, admitted.title, admitted.admitted_by, player, host, port,
                          tostring(admitted.rom_hash):sub(1, 8)))

SLINK_GEN4_CLIENT = client

event.onframeend(function()
    local fok, ferr = pcall(function() client:frame_end() end)
    if not fok then console.log("[SLink-gen4] frame error: " .. tostring(ferr)) end
    H.render()
end)
event.onexit(function() pcall(function() client:stop() end) end)
