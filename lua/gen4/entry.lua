-- lua/gen4/entry.lua -- admission + composition root for the Gen 4 (HGSS / hg-engine) client.
--
-- The ONLY file that names a foundation (PLAN 4.3): everything downstream sees pack data.
-- Admission is HASH-FIRST and never falls back to the header or to anchors:
--   1. the cartridge hash (case-insensitive) must equal a pinned md5 OR sha1 of a pack title
--      (BizHawk getromhash() is the md5 for gamedb ROMs and the sha1 for the rest: C1-1 row j);
--   2. the Platinum pack is bind-only (D3) and is refused by name;
--   3. a VANILLA (HGSS) hit must also pass the static-ARM9 anchors: every arm9 site's pinned bytes
--      (plus the pack's optional `admission_anchors`) must read back from RAM, so an hge ROM
--      (whose arm9 entries are redirected to ov129) can never be admitted as vanilla;
--   4. an hge hit is admitted by hash only.
-- An unknown hash is refused as an unpinned build even when the header says IPKE: never assumed
-- vanilla. `admit_routed` adds the launcher policy so a dofile'd run cannot skip the gate
-- (Gen 3 Entry.admit_routed, MERGE_DRIFT_2026-10-01 item 5).
--
--   args.root, args.json   pack lookup (repo root, lua/json_codec.lua)
--   args.packs             optional {pack = decoded profile.json}; tests/harness inject, default = files
--   args.rom_hash          gameinfo.getromhash() (md5 or sha1)
--   args.read_ram          function(addr, len) -> 1-based byte array | nil, over ARM9 main RAM
--   args.header_code       NDS cart header game code at 0x0C ("IPKE"); Entry.header_code reads it
local Entry = {}

-- Literal repo-relative paths (the release manifest derives what to ship from these literals).
-- `vanilla` = admission also runs the static-ARM9 anchors.
Entry.PACKS = {
    gen4_hgss = { profile = "data/games/gen4_hgss/profile.json", vanilla = true },
    gen4_hge  = { profile = "data/games/gen4_hge/profile.json" },
}
-- Known to the hash table so the refusal can name it; never admitted (D3).
Entry.BIND_ONLY = {
    gen4_pt = { profile = "data/games/gen4_pt/profile.json" },
}
-- Which packs the launcher routes to the rewritten client; the launcher keeps no copy.
Entry.ROUTED = { gen4_hgss = true, gen4_hge = true }

local function load_json(json, path)
    local f = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = f:read("*a")
    f:close()
    return assert(json.decode(text))
end

local function sorted_keys(t)
    local keys = {}
    for k in pairs(t) do keys[#keys + 1] = k end
    table.sort(keys)
    return keys
end

-- FLOORS (F11): a vanilla admission with fewer anchors than this is refused, so a pack edit that
-- drops anchors cannot quietly weaken the hge-vs-vanilla discrimination. Today's HG/SS packs carry
-- 20 arm9 site anchors (including the Battle_Exit closing-frame probe) + 3 admission_anchors (0x02000CD0 hook site and two more); raising the numbers
-- is a conscious edit here, lowering them is a security decision.
Entry.MIN_SITE_ANCHORS, Entry.MIN_ADMISSION_ANCHORS = 20, 3

-- Pinned byte runs a vanilla ROM must show in ARM9 RAM: {name, address, hex}, in a fixed order.
local function anchors_of(title)
    local out = {}
    for _, name in ipairs(sorted_keys(title.sites or {})) do
        local s = title.sites[name]
        if s.image == "arm9" and s.register_hex and s.address then
            out[#out + 1] = { name = name, address = s.address, hex = s.register_hex, site = true }
        end
    end
    for i, a in ipairs(title.admission_anchors or {}) do
        out[#out + 1] = { name = "admission_anchors[" .. i .. "]", address = a.address, hex = a.hex, admission = true }
    end
    return out
end

-- hash -> {pack, title, rom_type, header_code, anchors, bind_only}. A digest repeated across two
-- rows is a hard error naming both (never a silent last-writer-wins).
function Entry.admission_table(args)
    local table_ = {}
    local sets = {}
    for _, pack in ipairs(sorted_keys(Entry.PACKS)) do sets[#sets + 1] = { pack, Entry.PACKS[pack], false } end
    for _, pack in ipairs(sorted_keys(Entry.BIND_ONLY)) do sets[#sets + 1] = { pack, Entry.BIND_ONLY[pack], true } end
    for _, set in ipairs(sets) do
        local pack, def, bind_only = set[1], set[2], set[3]
        local decoded = (args.packs and args.packs[pack]) or load_json(args.json, args.root .. "/" .. def.profile)
        for _, title in ipairs(sorted_keys(decoded.titles)) do
            local t = decoded.titles[title]
            local row = { pack = pack, title = title, rom_type = title, header_code = t.rom.header_code,
                          bind_only = bind_only, anchors = def.vanilla and anchors_of(t) or nil }
            for _, key in ipairs({ "sha1", "md5" }) do
                local digest = t.rom[key]
                if digest then
                    digest = digest:lower()
                    local prior = table_[digest]
                    if prior then
                        error(string.format("[gen4/entry] duplicate %s %s shared by %s/%s and %s/%s",
                            key, digest, prior.pack, prior.title, pack, title), 0)
                    end
                    table_[digest] = row
                end
            end
        end
    end
    return table_
end

-- First anchor that does not read back as pinned, or nil.
local function anchor_failure(row, read_ram)
    if #row.anchors == 0 then return "pack ships no ARM9 anchors (pack gap)" end
    local sites, adm = 0, 0
    for _, a in ipairs(row.anchors) do
        if a.site then sites = sites + 1 end
        if a.admission then adm = adm + 1 end
    end
    if sites < Entry.MIN_SITE_ANCHORS or adm < Entry.MIN_ADMISSION_ANCHORS then
        return string.format("pack ships too few ARM9 anchors (%d site + %d admission, need at least %d + %d)",
            sites, adm, Entry.MIN_SITE_ANCHORS, Entry.MIN_ADMISSION_ANCHORS)
    end
    for _, a in ipairs(row.anchors) do
        local n = #a.hex // 2
        local ok, bytes = pcall(read_ram, a.address, n)
        if not ok or type(bytes) ~= "table" or #bytes ~= n then return a.name .. " is unreadable" end
        for i = 1, n do
            if bytes[i] ~= tonumber(a.hex:sub(2 * i - 1, 2 * i), 16) then
                return a.name .. " does not match the vanilla bytes"
            end
        end
    end
end

-- Returns { pack, title, rom_type, rom_hash, admitted_by = "hash" } or nil, reason.
function Entry.admit(args)
    local hash = tostring(args.rom_hash or ""):lower()
    local code = tostring(args.header_code or "")
    local row = Entry.admission_table(args)[hash]
    if not row then
        return nil, "unpinned build: ROM hash " .. hash .. " is not a pinned Gen 4 cartridge (header "
                    .. code .. "); never assumed vanilla"
    end
    if row.bind_only then
        return nil, row.title .. " is bind-only (D3), not a supported Gen 4 cartridge"
    end
    if code ~= row.header_code then
        return nil, "header " .. code .. " does not match the pinned " .. row.title .. " header " .. row.header_code
    end
    if row.anchors then
        if type(args.read_ram) ~= "function" then return nil, "vanilla admission needs read_ram for the ARM9 anchors" end
        local bad = anchor_failure(row, args.read_ram)
        if bad then return nil, "hash says " .. row.title .. " but ARM9 anchor check failed: " .. bad end
    end
    return { pack = row.pack, title = row.title, rom_type = row.rom_type, rom_hash = hash, admitted_by = "hash" }
end

-- Entry.admit plus the LAUNCHER policy: lua/slink.lua and the Gen 4 run.lua both call this, so a
-- caller that dofiles run.lua directly is held to the same gate. Same return shape as admit.
function Entry.admit_routed(args)
    local admitted, why = Entry.admit(args)
    if not admitted then return nil, why end
    if admitted.admitted_by ~= "hash" then
        return nil, "this " .. tostring(admitted.title) .. " build is not a pinned cartridge"
    end
    if not Entry.ROUTED[admitted.pack] then
        return nil, "the " .. tostring(admitted.pack) .. " pack is not yet routed to the Gen 4 client"
    end
    return admitted
end

-- NDS cartridge header: 4-byte game code at 0x0C (GBATEK DS cartridge header). Platform constant.
function Entry.header_code(rom_read)
    local bytes, out = rom_read(0x0C, 4), {}
    for i = 1, 4 do out[i] = string.char(bytes[i]) end
    return table.concat(out)
end

-- Thin factory: the per-title bound modules over an injected read-only `mem` (u8/u16/u32).
--   deps.root, deps.pack, deps.title, deps.mem, deps.encounter_active (function() -> bool, the
--   client's truthful encounter lifecycle), optional deps.title_profile (decoded title object).
-- The nds/phase_signals entries are the shared module tables; the run/client instantiate them
-- (their config comes from the connector and the platform probe, not from here).
function Entry.build(deps)
    local root = assert(deps.root, "deps.root required")
    local pack = assert(deps.pack, "deps.pack required")
    assert(not Entry.BIND_ONLY[pack], pack .. " is bind-only (D3)")
    local def = assert(Entry.PACKS[pack], "unknown pack " .. tostring(pack))
    local title_name = assert(deps.title, "deps.title required")
    local L = function(rel) return dofile(root .. "/" .. rel) end
    local title = deps.title_profile
    if not title then
        title = assert(load_json(L("lua/json_codec.lua"), root .. "/" .. def.profile).titles[title_name],
                       "unknown title " .. title_name .. " in " .. pack)
    end
    local pk4, Reads, Safety = L("lua/gen4/pk4.lua"), L("lua/gen4/reads.lua"), L("lua/gen4/safety.lua")
    pk4.crypto = L("lua/nds/pkm45_crypto.lua")
    Reads.pk4 = pk4
    local safety = Safety.new(title, assert(deps.mem, "deps.mem required"),
        { reads = Reads, encounter_active = assert(deps.encounter_active, "deps.encounter_active required") })
    return {
        pack = pack, title = title_name, rom_type = title_name, profile = title,
        reads = Reads, pk4 = pk4, safety = safety,
        nds = L("lua/nds/hook_binding.lua"), phase_signals = L("lua/nds/phase_signals.lua"),
    }
end

return Entry
