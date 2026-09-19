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
--   deps.pack        "gen1_rby" | "gen1_purergb" (the data/games directory; default gen1_rby)
--   deps.title       "red" | "blue" | "yellow" | "purered" | "pureblue" | "puregreen"
--   deps.kind        admission artifact kind ("clean" | "overlay"; default "clean")
--   deps.player      "a" | "b"
--   deps.rom_sha1    sha1 of the running cartridge (may differ from clean when patched)
--   deps.log         function(text)
--
-- Foundation selection (PLAN §4 row 1, A3) is hash-first: `Entry.admit` compares the ROM's
-- sha1, case-insensitively, against the union of every pack's admission set. The header
-- title only narrows candidates and words the refusal. This file is the ONLY place a
-- foundation is ever named; everything downstream sees pack data.
local Entry = {}

local function load_json(json, path)
    local f = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = f:read("*a")
    f:close()
    return assert(json.decode(text))
end

-- The packs and what each one cannot (yet) say for itself.
--   rom_type  the strings the server routes on (server/adapters/__init__.py)
--   trade     the companion-patch addresses: vanilla's are the shipped patch (slink.asm:38,
--             trade_service.asm:67-68, the receptionist dispatch at ROM0 $29C3); an overlay
--             pack carries its own `trade` block in profile.json and this default is unused.
--             pureRGB clean ships none, so its panel/trade capability is ABSENT (no $29C3 probe).
--   admission the pack ships an admission.json (sha1 -> {title, kind, ...}); gen1_rby has none
--             yet, so its clean sha1s come from profile.json's per-title rom_sha1
Entry.PACKS = {
    gen1_rby = {
        rom_type = { red = "Red", blue = "Blue", yellow = "Yellow" },
        trade = { receptionist_hook = 0x29C3, dispatch_hex = "21004C063F",
                  service = { bank = 0x3F, addr = 0x4500 }, mailbox = 0xDEE2 },
    },
    gen1_purergb = {
        rom_type = { purered = "PureRed", pureblue = "PureBlue", puregreen = "PureGreen" },
        admission = true,
    },
}
-- Every pack file Entry.build/Entry.admit reads, as literal repo-relative paths: the release
-- manifest (tools/make_release.py, tests/unit/test_make_release_manifest.py) derives what to
-- ship from these literals, so a pack file must be named here or a player never gets it.
Entry.PACK_FILES = {
    gen1_rby = {
        profile = "data/games/gen1_rby/profile.json",
        sites = "data/games/gen1_rby/engine_signals.json",
        checkpoint = "data/games/gen1_rby/write_checkpoint.json",
        area_map = "data/games/gen1_rby/area_map.json",
        statics = "data/games/gen1_rby/static_encounters.json",
    },
    gen1_purergb = {
        profile = "data/games/gen1_purergb/profile.json",
        sites = "data/games/gen1_purergb/engine_signals.json",
        checkpoint = "data/games/gen1_purergb/write_checkpoint.json",
        area_map = "data/games/gen1_purergb/area_map.json",
        statics = "data/games/gen1_purergb/static_encounters.json",
        admission = "data/games/gen1_purergb/admission.json",
        charmap = "data/games/gen1_purergb/charmap.lua",
        species_index = "data/games/gen1_purergb/species_index.json",
        -- The SLink companion overlay (PLAN M3): a distinct artifact with its own profile
        -- (+ the `trade` block), sites and checkpoint (ROM symbols relocate, RAM does not) and
        -- its own admission rows; `<key>_<kind>` is what Entry.build loads for that kind.
        profile_overlay = "data/games/gen1_purergb/profile_overlay.json",
        sites_overlay = "data/games/gen1_purergb/engine_signals_overlay.json",
        checkpoint_overlay = "data/games/gen1_purergb/write_checkpoint_overlay.json",
        admission_overlay = "data/games/gen1_purergb/admission_overlay.json",
    },
}
Entry.ROM_TYPE = {}
for _, pack in pairs(Entry.PACKS) do
    for title, rt in pairs(pack.rom_type) do Entry.ROM_TYPE[title] = rt end
end

-- ── admission ────────────────────────────────────────────────────────────────────────

-- Pure-Lua SHA-1 (FIPS 180-4) over `read_u8(i)` for i in [0, n). Lua 5.4 integers; masked to
-- 32 bits. Used once at boot when BizHawk's gameinfo hash is not the loaded bytes' hash
-- (gameinfo.indatabase() true) or is unknown to every pack.
function Entry.sha1(read_u8, n)
    local M = 0xFFFFFFFF
    local function rol(x, k) return ((x << k) | (x >> (32 - k))) & M end
    local h0, h1, h2, h3, h4 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0
    -- message + 0x80 + zero pad + 64-bit big-endian bit length, as a byte source
    local total = n + 1
    while total % 64 ~= 56 do total = total + 1 end
    total = total + 8
    local bits = n * 8
    local function byte_at(i)
        if i < n then return read_u8(i) end
        if i == n then return 0x80 end
        if i < total - 8 then return 0 end
        return (bits >> (8 * (total - 1 - i))) & 0xFF
    end
    local w = {}
    for chunk = 0, total - 1, 64 do
        for t = 0, 15 do
            local b = chunk + t * 4
            w[t] = (byte_at(b) << 24) | (byte_at(b + 1) << 16) | (byte_at(b + 2) << 8) | byte_at(b + 3)
        end
        for t = 16, 79 do w[t] = rol(w[t - 3] ~ w[t - 8] ~ w[t - 14] ~ w[t - 16], 1) end
        local a, b, c, d, e = h0, h1, h2, h3, h4
        for t = 0, 79 do
            local f, k
            if t < 20 then f, k = (b & c) | ((~b) & d), 0x5A827999
            elseif t < 40 then f, k = b ~ c ~ d, 0x6ED9EBA1
            elseif t < 60 then f, k = (b & c) | (b & d) | (c & d), 0x8F1BBCDC
            else f, k = b ~ c ~ d, 0xCA62C1D6 end
            local tmp = (rol(a, 5) + (f & M) + e + k + w[t]) & M
            e, d, c, b, a = d, c, rol(b, 30), a, tmp
        end
        h0, h1, h2, h3, h4 = (h0 + a) & M, (h1 + b) & M, (h2 + c) & M, (h3 + d) & M, (h4 + e) & M
    end
    return string.format("%08x%08x%08x%08x%08x", h0, h1, h2, h3, h4)
end

-- sha1 (lowercase) -> { pack, title, kind, rom_type } over every pack's admission set.
-- gen1_purergb: admission.json rows; gen1_rby: the per-title profile rom_sha1 (clean).
function Entry.admission_table(root, json)
    local table_ = {}
    for pack, def in pairs(Entry.PACKS) do
        local files = Entry.PACK_FILES[pack]
        if files.admission then
            for _, key in ipairs({ "admission", "admission_overlay" }) do
                if files[key] then
                    for sha, row in pairs(load_json(json, root .. "/" .. files[key])) do
                        table_[sha:lower()] = { pack = pack, title = row.title, kind = row.kind or "clean",
                                                rom_type = def.rom_type[row.title] }
                    end
                end
            end
        else
            for title, t in pairs(load_json(json, root .. "/" .. files.profile).titles) do
                if t.rom_sha1 and not table_[t.rom_sha1:lower()] then
                    table_[t.rom_sha1:lower()] = { pack = pack, title = title, kind = "clean",
                                                   rom_type = def.rom_type[title] }
                end
            end
        end
    end
    return table_
end

-- Decide the foundation for the loaded cartridge.
--   args.root, args.json           pack lookup
--   args.rom_sha1                  gameinfo.getromhash() (any case; may be BizHawk's database hash)
--   args.indatabase                gameinfo.indatabase() (true = the hash above is not the bytes')
--   args.read_rom_u8, args.rom_size   the flat ROM domain, for the Lua rehash
--   args.header                    the header title (Entry.detect_title's second value), for the reason
-- Returns { pack, title, kind, rom_type, rom_sha1, rehashed } or nil, reason.
function Entry.admit(args)
    local table_ = Entry.admission_table(args.root, args.json)
    local sha = (args.rom_sha1 or ""):lower()
    local hit = table_[sha]
    local rehashed = false
    if (not hit or args.indatabase) and args.read_rom_u8 and args.rom_size then
        sha = Entry.sha1(args.read_rom_u8, args.rom_size)
        hit = table_[sha]
        rehashed = true
    end
    if not hit then
        local header = tostring(args.header or "")
        local reason
        if header:find("POKEMON RED", 1, true) or header:find("POKEMON BLUE", 1, true)
           or header:find("POKEMON GREEN", 1, true) then
            reason = "header " .. header .. " matches no admitted cartridge (a pureRGB or vanilla "
                     .. "build whose sha1 is not in any pack): sha1 " .. sha
        else
            reason = "header " .. header .. " is not an admitted Gen 1 cartridge: sha1 " .. sha
        end
        return nil, reason
    end
    return { pack = hit.pack, title = hit.title, kind = hit.kind, rom_type = hit.rom_type,
             rom_sha1 = sha, rehashed = rehashed }
end

-- ── build ────────────────────────────────────────────────────────────────────────────

-- Reads of $D000-$DFFF go through the flat WRAM domain (bank 1 at 0x1000) when the profile
-- says the foundation banks WRAM (derived.wram_bank_gate): System Bus follows the live
-- SVBK mapping and pureRGB's palette fade runs with bank 2 selected (PLAN §4 row 13, Live 3).
-- Writes are NOT rerouted: writes.lua refuses them outside banks {0,1} instead.
local function bank_safe_io(bio, d)
    if not d.wram_bank_gate then return bio end
    local LO, HI, FLAT = 0xD000, 0xDFFF, 0x1000
    local function is_bus(dom) return dom == nil or dom == "System Bus" end
    local wrapped = {}
    for k, v in pairs(bio) do wrapped[k] = v end
    wrapped.read_u8 = function(addr, dom)
        if is_bus(dom) and addr >= LO and addr <= HI then return bio.read_u8(FLAT + (addr - LO), "WRAM") end
        return bio.read_u8(addr, dom)
    end
    wrapped.read_range = function(addr, len, dom)
        if is_bus(dom) and addr >= LO and addr + len - 1 <= HI then
            return bio.read_range(FLAT + (addr - LO), len, "WRAM")
        end
        return bio.read_range(addr, len, dom)
    end
    return wrapped
end

function Entry.build(deps)
    local root = assert(deps.root, "deps.root required")
    local L = function(rel) return dofile(root .. "/" .. rel) end
    local json = L("lua/json_codec.lua")
    local R, S, W, B, Rom = L("lua/gen1/reads.lua"), L("lua/gen1/signals.lua"), L("lua/gen1/writes.lua"),
                            L("lua/gen1/boxes.lua"), L("lua/gen1/rom.lua")
    local T, P = L("lua/gen1/trade_overlay.lua"), L("lua/gen1/panel.lua")
    local safety = L("lua/gen1_write_safety.lua")
    local Client = L("lua/gen1/client.lua")

    local pack = deps.pack or "gen1_rby"
    local pack_def = assert(Entry.PACKS[pack], "unknown pack " .. tostring(pack))
    local files = Entry.PACK_FILES[pack]
    local title = assert(deps.title, "deps.title required")
    -- the pack file for this artifact kind: profile.json for clean, profile_overlay.json for overlay
    local kind = deps.kind or "clean"
    local function pack_file(key)
        local rel = kind == "clean" and files[key] or files[key .. "_" .. kind]
        return root .. "/" .. assert(rel, pack .. " ships no " .. key .. " for artifact kind " .. kind)
    end
    local profile = assert(load_json(json, pack_file("profile")).titles[title], "unknown title " .. title)
    local sites = assert(load_json(json, pack_file("sites")).titles[title]).sites
    local write_checkpoint = assert(load_json(json, pack_file("checkpoint"))[title])
    local area_map = load_json(json, root .. "/" .. files.area_map)
    -- static (scripted, fixed-species) encounters get their own area id; generated from pret
    local statics = load_json(json, root .. "/" .. files.statics).statics
    -- the pack's glyph table (charmap.lua) and species index, when it ships them
    if files.charmap then profile.charmap = dofile(root .. "/" .. files.charmap) end
    local species_index = files.species_index and load_json(json, root .. "/" .. files.species_index) or nil
    -- companion-patch/overlay addresses: the pack's own block, else the shipped vanilla patch
    profile.trade = profile.trade or pack_def.trade

    local bio = bank_safe_io(deps.io, profile.derived)
    -- reads: System Bus, no domain argument
    local reads_io = {
        read_u8 = function(addr) return bio.read_u8(addr, "System Bus") end,
        read_range = function(addr, len) return bio.read_range(addr, len, "System Bus") end,
    }
    local reads = R.new(profile, reads_io)
    profile.charmap = reads.charmap -- the ONE glyph object; the panel reads it from here
    local writes = W.new(profile, bio)
    -- boxes write through the same armed gate; CartRAM is the flat SRAM image
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
            writes.log[#writes.log + 1] = { addr = off, n = #bytes, why = writes.armed,
                                            cart = true, frame = bio.framecount() }
        end,
    }
    local boxes = B.new(profile, reads, box_io)
    local rom = Rom.new(profile, bio, species_index)
    local trade, panel
    if profile.trade then
        trade = T.new(profile, reads_io, writes)
        -- the panel reads the mailbox every frame and needs the clock for its own deadline
        local panel_io = { read_u8 = reads_io.read_u8, framecount = function() return bio.framecount() end }
        panel = P.new(profile, panel_io, writes, deps.hud and deps.hud.sanitize or function(s) return s end)
    end

    local client = Client.new({
        reads = reads, signals = S, writes = writes, boxes = boxes, rom = rom, safety = safety,
        net = deps.net, json = json, hud = deps.hud, io = bio,
        profile = profile, sites = sites, write_checkpoint = write_checkpoint, area_map = area_map,
        statics = statics, trade = trade, panel = panel,
        player = assert(deps.player, "deps.player required"), rom_type = pack_def.rom_type[title],
        rom_sha1 = deps.rom_sha1, log = deps.log or function() end,
        foundation = pack, artifact_kind = deps.kind or "clean",
    })
    return client, { profile = profile, sites = sites, reads = reads, writes = writes, boxes = boxes,
                     rom = rom, json = json, panel = panel, box_io = box_io, pack = pack }
end

-- Header family from the cartridge header (ROM $0134..$0143): "POKEMON RED"/"BLUE"/"YELLOW"/
-- "GREEN". This NARROWS candidates and gates the launcher route; admission is Entry.admit.
-- PureRed/PureBlue share vanilla's header bytes, so "red" here never means vanilla Red.
function Entry.header_title(read_rom_u8)
    local chars = {}
    for i = 0, 15 do
        local b = read_rom_u8(0x134 + i)
        if b == 0 then break end
        chars[#chars + 1] = string.char(b)
    end
    return table.concat(chars)
end
function Entry.detect_title(read_rom_u8)
    local name = Entry.header_title(read_rom_u8)
    if name:find("RED", 1, true) then return "red" end
    if name:find("BLUE", 1, true) then return "blue" end
    if name:find("YELLOW", 1, true) then return "yellow" end
    if name:find("GREEN", 1, true) then return "green" end
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
        set_register = function(name, value) return emu.setregister(name, value) end,
        domains = function() return memory.getmemorydomainlist() end,
        saveram = function() if client and client.saveram then return client.saveram() end end,
    }
end

return Entry
