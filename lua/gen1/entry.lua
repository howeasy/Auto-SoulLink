-- lua/gen1/entry.lua — composition root for the Gen 1 client.
--
-- `Entry.build(deps)` wires reads/signals/writes/boxes/rom/safety/client together over the
-- injected BizHawk-shaped `deps.io` and transport `deps.net`, so production (slink_gen1.lua)
-- and the lupa harness build the identical client. Nothing here touches BizHawk globals
-- except `Entry.bizhawk_deps()`.
--
--   deps.root        repo root path (for dofile / data files)
--   deps.io          read_u8(addr, domain?), read_range(addr, len, domain?), write_u8(addr, v, domain?),
--                    on_bus_exec, unregister, framecount, register(name), domains(), saveram?
--   deps.net         init(host, port), send(line), receive(), pump(), connected()
--   deps.hud         show/prompt/set_game_over/set_rebuilding/clear_rebuilding
--   deps.title       "red" | "blue" | "yellow"      deps.player "a" | "b"
--   deps.rom_sha1    sha1 of the running cartridge (may differ from clean when patched)
--   deps.log         function(text)
local Entry = {}

local function load_json(json, path)
    local f = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = f:read("*a")
    f:close()
    return assert(json.decode(text))
end

-- rom_type strings the server routes on (server/adapters/__init__.py)
Entry.ROM_TYPE = { red = "Red", blue = "Blue", yellow = "Yellow" }

function Entry.build(deps)
    local root = assert(deps.root, "deps.root required")
    local L = function(rel) return dofile(root .. "/" .. rel) end
    local json = L("lua/json_codec.lua")
    local R, S, W, B, Rom = L("lua/gen1/reads.lua"), L("lua/gen1/signals.lua"), L("lua/gen1/writes.lua"),
                            L("lua/gen1/boxes.lua"), L("lua/gen1/rom.lua")
    local T, P = L("lua/gen1/trade_overlay.lua"), L("lua/gen1/panel.lua")
    local safety = L("lua/gen1_write_safety.lua")
    local Client = L("lua/gen1/client.lua")

    local title = assert(deps.title, "deps.title required")
    local profile = assert(load_json(json, root .. "/data/games/gen1_rby/profile.json").titles[title], "unknown title " .. title)
    local sites = assert(load_json(json, root .. "/data/games/gen1_rby/engine_signals.json").titles[title]).sites
    local write_checkpoint = assert(load_json(json, root .. "/data/games/gen1_rby/write_checkpoint.json")[title])
    local area_map = load_json(json, root .. "/data/games/gen1_rby/area_map.json")
    -- static (scripted, fixed-species) encounters get their own area id; generated from pret
    local statics = load_json(json, root .. "/data/games/gen1_rby/static_encounters.json").statics

    local bio = deps.io
    -- reads: System Bus, no domain argument
    local reads_io = {
        read_u8 = function(addr) return bio.read_u8(addr, "System Bus") end,
        read_range = function(addr, len) return bio.read_range(addr, len, "System Bus") end,
    }
    local reads = R.new(profile, reads_io)
    local writes = W.new(profile, bio)
    -- boxes write through the same armed gate; CartRAM is the flat 0x8000 image
    local box_io = {
        read_range = reads_io.read_range,
        read_cart = function(off) return bio.read_u8(off, "CartRAM") end,
        write_bytes = function(addr, bytes) return writes:write_bytes(addr, bytes) end,
        write_cart_bytes = function(off, bytes)
            assert(writes.armed, "cart write refused: no armed write window (W-7)")
            -- The panel window's allow predicate speaks System Bus addresses and cannot see
            -- this door at all, so the refusal lives here: painting a menu never touches SRAM.
            assert(writes.armed ~= "panel", "cart write refused: the panel window writes WRAM only")
            for i = 1, #bytes do bio.write_u8(off + i - 1, bytes[i], "CartRAM") end
            -- this door bypasses writes:write_bytes, so the receipt has to be logged here or a
            -- box move leaves no trace at all in writes.log (A2 scenario finding)
            writes.log[#writes.log + 1] = { off = off, n = #bytes, why = writes.armed,
                                            cart = true, frame = bio.framecount() }
        end,
    }
    local boxes = B.new(profile, reads, box_io)
    local rom = Rom.new(profile, bio)
    local trade = T.new(profile, reads_io, writes)
    -- the panel reads the mailbox every frame and needs the clock for its own deadline
    local panel_io = { read_u8 = reads_io.read_u8, framecount = function() return bio.framecount() end }
    local panel = P.new(profile, panel_io, writes, deps.hud and deps.hud.sanitize or function(s) return s end)

    local client = Client.new({
        reads = reads, signals = S, writes = writes, boxes = boxes, rom = rom, safety = safety,
        net = deps.net, json = json, hud = deps.hud, io = bio,
        profile = profile, sites = sites, write_checkpoint = write_checkpoint, area_map = area_map,
        statics = statics, trade = trade, panel = panel,
        player = assert(deps.player, "deps.player required"), rom_type = Entry.ROM_TYPE[title],
        rom_sha1 = deps.rom_sha1, log = deps.log or function() end,
    })
    return client, { profile = profile, sites = sites, reads = reads, writes = writes, boxes = boxes,
                     rom = rom, json = json, panel = panel, box_io = box_io }
end

-- Title from the cartridge header (ROM $0134..$0143): "POKEMON RED"/"POKEMON BLUE"/"POKEMON YELLOW".
function Entry.detect_title(read_rom_u8)
    local chars = {}
    for i = 0, 15 do
        local b = read_rom_u8(0x134 + i)
        if b == 0 then break end
        chars[#chars + 1] = string.char(b)
    end
    local name = table.concat(chars)
    if name:find("RED", 1, true) then return "red" end
    if name:find("BLUE", 1, true) then return "blue" end
    if name:find("YELLOW", 1, true) then return "yellow" end
    return nil, name
end

function Entry.bizhawk_deps()
    local function dom(d) return d or "System Bus" end
    return {
        read_u8 = function(addr, d) return memory.read_u8(addr, dom(d)) end,
        read_range = function(addr, len, d)
            local out = {}
            for i = 1, len do out[i] = memory.read_u8(addr + i - 1, dom(d)) end
            return out
        end,
        write_u8 = function(addr, v, d) return memory.write_u8(addr, v, dom(d)) end,
        on_bus_exec = function(fn, addr, name, d) return event.on_bus_exec(fn, addr, name, dom(d)) end,
        unregister = function(id) return event.unregisterbyid(id) end,
        framecount = function() return emu.framecount() end,
        register = function(name) return emu.getregister(name) end,
        domains = function() return memory.getmemorydomainlist() end,
        saveram = function() if client and client.saveram then return client.saveram() end end,
    }
end

return Entry
