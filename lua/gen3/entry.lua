-- lua/gen3/entry.lua — composition root for the Gen 3 (FRLG + Radical Red) client.
--
-- `Entry.build(deps)` wires the parts together over the injected, BizHawk-shaped `deps.io`
-- and `deps.ev`, so every bootstrap (P3's shadow_run.lua, P4's run.lua) and the lupa harness
-- build the identical graph. Nothing in lua/gen3/ touches a BizHawk global; a bootstrap
-- builds the io/ev tables and injects them.
--
--   deps.root     repo root path (for dofile / pack files)
--   deps.mode     "observer" (P3: reads + signals over a read-only io; there is no
--                 client.lua yet). Production mode lands in P4.
--   deps.io       read_u8/read_u16/read_u32(addr), read_bytes(addr, len),
--                 rom_read(off, len), framecount(), register(name)
--   deps.ev       on_bus_exec(fn, addr, name) -> id, unregister(id)
--   deps.pack     "gen3_frlg" | "gen3_rr"
--   deps.title    "firered" | "leafgreen" | "radical_red"
--   deps.kind     admission artifact kind ("clean" | "named" | "companion"; default "clean")
--   deps.on_fire  optional kind -> function(signal), run inside the signal hook
--   deps.log      function(text)
--
-- Returns `nil, parts` in observer mode: the leading slot is the client production mode will
-- return, so a caller written against either mode reads `local client, parts = ...`.
--
-- Foundation selection (PLAN §5.1) is hash-first: `Entry.admit` compares the cartridge hash,
-- case-insensitively, against the union of every pack's admission set (the per-artifact
-- rom_sha1/rom_md5 pins in engine_signals.json). A hash in no table is admitted by ANCHORS
-- (every engine site of exactly one admitted pack/title/kind still reads as pinned in ROM),
-- and only then by the header-named family fallback. This file is the ONLY place a
-- foundation is ever named; everything downstream sees pack data.
--
-- There is deliberately NO pure-Lua rehash here (Gen 1 has one): a GBA cartridge is up to
-- 32 MiB and a Lua SHA-1 over it costs minutes at boot. The anchor pass IS the byte-level
-- proof, and it reads a few hundred bytes.
local Entry = {}

local function load_json(json, path)
    local f = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = f:read("*a")
    f:close()
    return assert(json.decode(text))
end

local function file_exists(path)
    local f = io.open(path, "rb")
    if not f then return false end
    f:close()
    return true
end

-- The packs and what each one cannot (yet) say for itself.
--   rom_type     the strings the server routes on (server/adapters/__init__.py:39-41)
--   header_code  GBA header game code -> title, for the named-family fallback only. RR is a
--                FireRed hack and carries FireRed's code, so it takes no part: an RR build
--                with an unknown hash is admitted by anchors or not at all.
Entry.PACKS = {
    gen3_frlg = {
        rom_type = { firered = "firered", leafgreen = "leafgreen" },
        header_code = { BPRE = "firered", BPGE = "leafgreen" },
    },
    gen3_rr = {
        rom_type = { radical_red = "firered_rr" },
    },
}
-- Every pack file Entry.build/Entry.admit reads, as literal repo-relative paths: the release
-- manifest derives what to ship from these literals, so a pack file must be named here or a
-- player never gets it.
Entry.PACK_FILES = {
    gen3_frlg = {
        profile = "data/games/gen3_frlg/profile.json",
        sites = "data/games/gen3_frlg/engine_signals.json",
        checkpoint = "data/games/gen3_frlg/write_checkpoint.json",
    },
    gen3_rr = {
        profile = "data/games/gen3_rr/profile.json",
        sites = "data/games/gen3_rr/engine_signals.json",
        checkpoint = "data/games/gen3_rr/write_checkpoint.json",
    },
}
Entry.ROM_TYPE = {}
for _, pack in pairs(Entry.PACKS) do
    for title, rt in pairs(pack.rom_type) do Entry.ROM_TYPE[title] = rt end
end
-- A header-named vanilla family (an unknown-hash cartridge that still says BPRE/BPGE) reads
-- the clean artifact's pack data; if its bytes really differ, the site check refuses it.
Entry.BASE_KIND = { named = "clean" }

-- ── admission ────────────────────────────────────────────────────────────────────────

-- The artifact table for one pack: title -> kind -> artifact (rom_sha1, rom_md5, sites).
function Entry.artifacts(root, json, pack)
    local files = assert(Entry.PACK_FILES[pack], "unknown pack " .. tostring(pack))
    local out = {}
    for title, entry in pairs(load_json(json, root .. "/" .. files.sites).titles) do
        out[title] = entry.artifacts
    end
    return out
end

-- hash (lowercase sha1 or md5) -> { pack, title, kind, rom_type } over every pack's
-- admission set. Both digests are indexed: they cannot collide (40 vs 32 hex digits) and
-- BizHawk's gameinfo hash is not the same digest on every core.
function Entry.admission_table(root, json)
    local table_ = {}
    for pack, def in pairs(Entry.PACKS) do
        for title, artifacts in pairs(Entry.artifacts(root, json, pack)) do
            for kind, artifact in pairs(artifacts) do
                local row = { pack = pack, title = title, kind = kind,
                              rom_type = def.rom_type[title] }
                for _, key in ipairs({ "rom_sha1", "rom_md5" }) do
                    if artifact[key] then table_[artifact[key]:lower()] = row end
                end
            end
        end
    end
    return table_
end

-- Every engine site of one artifact still reads as pinned in this ROM.
local function anchors_hold(artifact, rom_read)
    for _, site in pairs(artifact.sites) do
        local hex = site.expected_hex
        local n = #hex // 2
        if type(site.rom_offset) ~= "number" then return false end
        local bytes = rom_read(site.rom_offset, n)
        if type(bytes) ~= "table" or #bytes ~= n then return false end
        for i = 1, n do
            if bytes[i] ~= tonumber(hex:sub(2 * i - 1, 2 * i), 16) then return false end
        end
    end
    return true
end

-- Every admitted (pack, title, kind) whose anchors all hold in this ROM.
function Entry.anchor_matches(args)
    local matches = {}
    for pack, def in pairs(Entry.PACKS) do
        for title, artifacts in pairs(Entry.artifacts(args.root, args.json, pack)) do
            for kind, artifact in pairs(artifacts) do
                if anchors_hold(artifact, args.rom_read) then
                    matches[#matches + 1] = { pack = pack, title = title, kind = kind,
                                              rom_type = def.rom_type[title] }
                end
            end
        end
    end
    table.sort(matches, function(a, b)
        return a.pack .. a.title .. a.kind < b.pack .. b.title .. b.kind
    end)
    return matches
end

-- Decide the foundation for the loaded cartridge.
--   args.root, args.json   pack lookup
--   args.rom_hash          gameinfo.getromhash() (any case; sha1 or md5)
--   args.rom_read          function(offset, length) -> {bytes} over the flat ROM
--   args.header_code       the GBA header game code ("BPRE"), for the named fallback
-- Returns { pack, title, kind, rom_type, rom_hash, admitted_by } or nil, reason;
-- admitted_by is "hash", "anchors" or "header".
function Entry.admit(args)
    local hash = tostring(args.rom_hash or ""):lower()
    local hit = Entry.admission_table(args.root, args.json)[hash]
    if hit then
        return { pack = hit.pack, title = hit.title, kind = hit.kind,
                 rom_type = hit.rom_type, rom_hash = hash, admitted_by = "hash" }
    end
    local code = tostring(args.header_code or "")
    if args.rom_read then
        local matches = Entry.anchor_matches(args)
        if #matches == 1 then
            local m = matches[1]
            return { pack = m.pack, title = m.title, kind = m.kind, rom_type = m.rom_type,
                     rom_hash = hash, admitted_by = "anchors" }
        elseif #matches > 1 then
            local names = {}
            for i, m in ipairs(matches) do names[i] = m.pack .. "/" .. m.title .. "/" .. m.kind end
            return nil, "ambiguous: the anchors of " .. table.concat(names, ", ")
                        .. " all hold: header " .. code .. ", hash " .. hash
        end
    end
    for pack, def in pairs(Entry.PACKS) do
        local title = def.header_code and def.header_code[code]
        if title then
            return { pack = pack, title = title, kind = "named", rom_type = def.rom_type[title],
                     rom_hash = hash, admitted_by = "header" }
        end
    end
    return nil, "header " .. code .. " is not an admitted Gen 3 cartridge: hash " .. hash
end

-- The GBA cartridge header: 12-byte game title at $A0, 4-byte game code at $AC (GBATEK 3.2).
-- These are the two platform constants in this file; they are not game addresses.
function Entry.header_code(rom_read)
    local bytes = rom_read(0xAC, 4)
    local out = {}
    for i = 1, 4 do out[i] = string.char(bytes[i]) end
    return table.concat(out)
end
function Entry.header_title(rom_read)
    local bytes, out = rom_read(0xA0, 12), {}
    for i = 1, 12 do
        if bytes[i] == 0 then break end
        out[i] = string.char(bytes[i])
    end
    return table.concat(out)
end

-- ── build ────────────────────────────────────────────────────────────────────────────

function Entry.build(deps)
    local root = assert(deps.root, "deps.root required")
    local mode = deps.mode or "observer"
    -- P4 lands production mode (client.lua); until then any other mode is refused by name
    -- rather than half-built.
    assert(mode == "observer", "deps.mode " .. tostring(mode)
           .. " is not built yet; lua/gen3 is observer-only until P4")
    local L = function(rel) return dofile(root .. "/" .. rel) end
    local json = L("lua/json_codec.lua")
    local Reads, Signals = L("lua/gen3/reads.lua"), L("lua/gen3/signals.lua")

    local pack = assert(deps.pack, "deps.pack required")
    local pack_def = assert(Entry.PACKS[pack], "unknown pack " .. tostring(pack))
    local files = Entry.PACK_FILES[pack]
    local title = assert(deps.title, "deps.title required")
    local kind = deps.kind or "clean"
    local artifact_kind = Entry.BASE_KIND[kind] or kind

    local profile = assert(load_json(json, root .. "/" .. files.profile).titles[title],
                           "unknown title " .. title .. " in " .. pack)
    assert(profile.admitted ~= false,
           title .. " is a known but unadmitted Gen 3 title in " .. pack)
    local title_sites = assert(load_json(json, root .. "/" .. files.sites).titles[title],
                               "pack " .. pack .. " ships no engine sites for " .. title)
    local artifact = assert(title_sites.artifacts[artifact_kind],
                            pack .. "/" .. title .. " ships no artifact of kind " .. artifact_kind)
    local sites = assert(artifact.sites, "artifact " .. artifact_kind .. " ships no sites")
    local write_checkpoint = load_json(json, root .. "/" .. files.checkpoint)[title]

    local io_ = assert(deps.io, "deps.io required")
    -- The pointer symbols (gSaveBlock1Ptr / gSaveBlock2Ptr / gPokemonStoragePtr) live in the
    -- checkpoint pack, so reads gets them as data rather than naming an address itself.
    local reads = Reads.new(profile, io_, write_checkpoint and write_checkpoint.pointers)
    local signals = Signals.new(profile, sites, io_, assert(deps.ev, "deps.ev required"),
                                deps.on_fire)
    -- The checkpoint predicate is a sibling card (lua/gen3/safety.lua, P3 C3-2); bind it
    -- when it has landed so no bootstrap has to know whether it exists yet.
    local safety_rel = "lua/gen3/safety.lua"
    local safety = file_exists(root .. "/" .. safety_rel) and L(safety_rel) or nil

    local parts = {
        pack = pack, title = title, kind = kind, artifact_kind = artifact_kind,
        rom_type = pack_def.rom_type[title], rom_hash = artifact.rom_sha1,
        profile = profile, sites = sites, write_checkpoint = write_checkpoint,
        reads = reads, signals = signals, safety = safety, json = json,
        mode = mode, log = deps.log or function() end,
    }
    return nil, parts
end

return Entry
