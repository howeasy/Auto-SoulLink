-- Gen 2 source-candidate composition and fail-closed production admission.
-- No emulator global or production activation. build_candidate requires explicit
-- candidate_only=true and injected IO/policies; with deps.net it also composes the
-- Gen 2 client (lua/gen2/client.lua) over the same MODEL graph (model_only IO,
-- MODEL_PROBE signals, an injected checkpoint), still runtime_started=false until
-- client:start(). build/admit cannot promote the current BUILT, G1-PENDING catalogs.
local Entry = {}

Entry.PACKS = {
    crystal={pack="gen2_crystal", artifact="pokecrystal", revision="1.0", rom_type="Crystal"},
    gold={pack="gen2_gold", artifact="pokegold", revision="US", rom_type="Gold"},
    silver={pack="gen2_silver", artifact="pokesilver", revision="US", rom_type="Silver"},
}
-- Every CURRENT generated pack artifact is literal for bundle-closure tooling.
-- Legacy Crystal item_names/species_types/gender_ratios JSON is not an input.
Entry.PACK_FILES = {
    gen2_crystal={
        admission="data/games/gen2_crystal/admission.json",
        area_map="data/games/gen2_crystal/area_map.json",
        charmap="data/games/gen2_crystal/charmap.lua",
        encounters="data/games/gen2_crystal/encounter_tables.json",
        sites="data/games/gen2_crystal/engine_signals.json",
        evolutions="data/games/gen2_crystal/evolutions.json",
        gifts="data/games/gen2_crystal/gifts.json",
        items="data/games/gen2_crystal/items.json",
        map_names="data/games/gen2_crystal/map_names.json",
        moves="data/games/gen2_crystal/moves.json",
        profile="data/games/gen2_crystal/profile.json",
        species="data/games/gen2_crystal/species_index.json",
        statics="data/games/gen2_crystal/static_encounters.json",
        trainers="data/games/gen2_crystal/trainers.json",
        checkpoint="data/games/gen2_crystal/write_checkpoint.json",
    },
    gen2_gold={
        admission="data/games/gen2_gold/admission.json",
        area_map="data/games/gen2_gold/area_map.json",
        charmap="data/games/gen2_gold/charmap.lua",
        encounters="data/games/gen2_gold/encounter_tables.json",
        sites="data/games/gen2_gold/engine_signals.json",
        evolutions="data/games/gen2_gold/evolutions.json",
        gifts="data/games/gen2_gold/gifts.json",
        items="data/games/gen2_gold/items.json",
        map_names="data/games/gen2_gold/map_names.json",
        moves="data/games/gen2_gold/moves.json",
        profile="data/games/gen2_gold/profile.json",
        species="data/games/gen2_gold/species_index.json",
        statics="data/games/gen2_gold/static_encounters.json",
        trainers="data/games/gen2_gold/trainers.json",
        checkpoint="data/games/gen2_gold/write_checkpoint.json",
    },
    gen2_silver={
        admission="data/games/gen2_silver/admission.json",
        area_map="data/games/gen2_silver/area_map.json",
        charmap="data/games/gen2_silver/charmap.lua",
        encounters="data/games/gen2_silver/encounter_tables.json",
        sites="data/games/gen2_silver/engine_signals.json",
        evolutions="data/games/gen2_silver/evolutions.json",
        gifts="data/games/gen2_silver/gifts.json",
        items="data/games/gen2_silver/items.json",
        map_names="data/games/gen2_silver/map_names.json",
        moves="data/games/gen2_silver/moves.json",
        profile="data/games/gen2_silver/profile.json",
        species="data/games/gen2_silver/species_index.json",
        statics="data/games/gen2_silver/static_encounters.json",
        trainers="data/games/gen2_silver/trainers.json",
        checkpoint="data/games/gen2_silver/write_checkpoint.json",
    },
}
local titles = {"crystal", "gold", "silver"}
local order = {"profile", "admission", "sites", "checkpoint", "area_map", "statics", "encounters",
               "species", "evolutions", "gifts", "moves", "trainers", "map_names", "items", "charmap"}

local function load_json(json, path)
    local handle = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = handle:read("*a")
    handle:close()
    return assert(json.decode(text))
end

local function load_pack(root, json, title)
    local def = assert(Entry.PACKS[title], "unsupported selected Gen 2 title")
    local files, data = Entry.PACK_FILES[def.pack], {}
    for _, key in ipairs(order) do
        local path = root .. "/" .. files[key]
        data[key] = key == "charmap" and dofile(path) or load_json(json, path)
    end
    local wrapper = data.profile
    assert(wrapper.schema == "gen2-profile-v1" and type(wrapper.titles) == "table", "generated Gen 2 profile required")
    local profile = assert(wrapper.titles[title], "selected title missing from profile")
    local count = 0
    for _ in pairs(wrapper.titles) do count = count + 1 end
    assert(count == 1 and profile.title == title and profile.artifact == def.artifact, "profile title/artifact mismatch")
    assert(type(wrapper.source) == "table" and wrapper.source.rom_sha1 == profile.rom_sha1
           and wrapper.source.artifact == def.artifact, "profile source mismatch")
    for key, value in pairs(data) do
        if key == "area_map" then
            -- The shared area-map contract is deliberately flat. Its provenance
            -- lives per map row, rather than in a wrapper resembling other packs.
            local maps = 0
            for id, row in pairs(value) do
                assert(type(row) == "table" and type(row.source) == "table"
                       and row.source.artifact == def.artifact and row.source.commit == wrapper.source.commit
                       and type(row.map_group) == "number" and type(row.map_number) == "number"
                       and tonumber(id) == row.map_group * 256 + row.map_number,
                       "area-map source/identity mismatch")
                maps = maps + 1
            end
            assert(maps > 0, "area-map source rows missing")
        elseif key ~= "admission" then
            assert(type(value.source) == "table" and value.source.evidence_level == "SOURCE"
                   and value.source.artifact == def.artifact and value.source.rom_sha1 == profile.rom_sha1
                   and value.source.lock_sha256 == wrapper.source.lock_sha256, "pack source mismatch: " .. files[key])
        end
    end
    local matrix = data.admission
    assert(matrix.schema_version == 1 and matrix.foundation == "gen2_gsc" and matrix.pack == def.pack
           and matrix.title == title and matrix.selected_revision == def.revision
           and matrix.source_lock_sha256 == wrapper.source.lock_sha256, "admission/source catalog mismatch")
    assert(matrix.unknown_hash_policy == "REFUSE" and matrix.gate and matrix.gate.id == "G1",
           "explicit fail-closed Gen 2 admission policy required")
    return data, profile, def
end

local function source_anchors(data, title)
    local anchors = {}
    local sites = assert(data.sites.titles[title].sites, "source engine sites required")
    for _, site in pairs(sites) do
        anchors[#anchors + 1] = {offset=site.rom_offset, hex=site.expected_hex}
        if site.prelude then anchors[#anchors + 1] = {offset=site.prelude.rom_offset, hex=site.prelude.expected_hex} end
    end
    local checkpoint = assert(data.checkpoint.titles[title].primary.anchors, "source checkpoint anchors required")
    for _, anchor in pairs(checkpoint) do anchors[#anchors + 1] = {offset=anchor.rom_offset, hex=anchor.expected_hex} end
    for _, row in pairs(data.area_map) do
        anchors[#anchors + 1] = {offset=row.source.header_flat, hex=row.source.header_hex}
    end
    assert(#anchors > 0, "required source anchor inventory empty")
    return anchors
end

function Entry.admit(args)
    local ok, result, reason = pcall(function()
        local root = assert(args.root, "root required")
        local Admission = dofile(root .. "/lua/admission.lua")
        local json = dofile(root .. "/lua/json_codec.lua")
        local engine = Admission.new({
            acquire=function(request)
                return {size=request.rom_size, read_u8=request.read_rom_u8}
            end,
            catalog=function()
                local candidates = {}
                for _, title in ipairs(titles) do
                    local data, profile, def = load_pack(root, json, title)
                    for _, row in ipairs(assert(data.admission.artifacts, "artifact catalog required")) do
                        candidates[#candidates + 1] = {row=row, data=data, profile=profile, def=def, title=title}
                    end
                end
                return candidates
            end,
            hashes=function(candidate) return candidate.row.sha1 and {candidate.row.sha1} or {} end,
            eligible=function(candidate)
                local row, matrix = candidate.row, candidate.data.admission
                if row.selection ~= "SELECTED" then return false, "artifact selection " .. tostring(row.selection) .. " is not admitted" end
                -- No future gate spelling or ADMITTED schema is invented here. The
                -- current catalog is explicitly source inventory, not admission.
                return false, "Gen 2 catalog status " .. tostring(row.status) .. "; G1 " .. tostring(matrix.gate.state)
                              .. "; source catalog grants no runtime admission"
            end,
            anchors=function(candidate) return source_anchors(candidate.data, candidate.title) end,
            kind=function(candidate, mode)
                if mode == "sha1" and candidate.row.kind == "clean" then return "clean" end
                return nil, "unsupported Gen 2 artifact kind/mode"
            end,
            describe=function(candidate, kind)
                return {pack=candidate.def.pack, title=candidate.title, kind=kind,
                        foundation="gen2_gsc", rom_type=candidate.def.rom_type}
            end,
            allow_unknown_hash=false,
        })
        return engine:admit(args)
    end)
    if not ok then return nil, tostring(result) end
    if result == nil then return nil, reason end
    return result
end

-- Explicit, non-activated source/model graph. It is not a production build path
-- and does not manufacture a client, transport, hook handles or an admitted row.
function Entry.build_candidate(deps)
    local ok, result = pcall(function()
        assert(deps.candidate_only == true, "explicit candidate_only=true required")
        local root = assert(deps.root, "root required")
        local io_ = assert(deps.io, "explicit candidate IO required")
        local load = function(path) return dofile(root .. "/" .. path) end
        local json, Admission = load("lua/json_codec.lua"), load("lua/admission.lua")
        local data, profile, def = load_pack(root, json, assert(deps.title, "selected title required"))
        assert(type(io_.read_u8) == "function" and type(io_.domain_size) == "function", "explicit ROM IO required")
        local size = io_.domain_size("ROM")
        assert(size == profile.derived.rom_size, "candidate ROM size mismatch")
        local function read_rom(offset) return io_.read_u8(offset, "ROM") end
        assert(Admission.sha1(read_rom, size) == profile.rom_sha1, "candidate ROM hash mismatch")
        assert(Admission.anchors_match(source_anchors(data, deps.title), {size=size, read_u8=read_rom}, "sha1"),
               "candidate source anchor mismatch")
        local Reads, Writes, Rom = load("lua/gen2/reads.lua"), load("lua/gen2/writes.lua"), load("lua/gen2/rom.lua")
        local Permit = load("lua/write_permit.lua")
        -- Names decode through the pack's ONE charmap and the shared scanner (Gen 1's shape).
        local decode_name = deps.decode_name or load("lua/token_scanner.lua").new({
            glyphs=data.charmap.glyphs, terminator=data.charmap.terminator,
            max_length=profile.derived.name_length,
            unknown=function(byte) return string.format("<$%02X>", byte) end})
        local reads, why = Reads.new(profile, io_, decode_name)
        assert(reads, why)
        local writes = Writes.new(profile, io_, Permit, assert(deps.write_policy, "explicit candidate write policy required"))
        local rom = Rom.new(profile, io_)
        local client
        if deps.net ~= nil then
            -- The client graph is MODEL by construction: signals.new_model is the only binder
            -- that registers (signals.new refuses until P3b.4 PHYSICAL requalification).
            assert(io_.model_only == true, "candidate client requires model_only IO")
            local checkpoint = assert(deps.checkpoint, "explicit candidate checkpoint required")
            assert(type(checkpoint.check) == "function", "checkpoint:check required")
            local Signals, Registry, GB = load("lua/gen2/signals.lua"), load("lua/hook_registry.lua"),
                                          load("lua/gb_hook_binding.lua")
            local title = deps.title
            client = load("lua/gen2/client.lua").new({
                reads=reads, wire=load("lua/gen2/wire.lua"), writes=writes, rom=rom,
                safety={check=function() return checkpoint:check() end},
                signals=function(authority)
                    return Signals.new_model({title=title, profile=data.profile, pack=data.sites, io=io_,
                        Registry=Registry, GB=GB, reads=reads, authority=authority, owner="SLink-gen2",
                        max_pending=64, areas=data.area_map, encounters=data.encounters,
                        statics=data.statics})
                end,
                net=deps.net, json=json, hud=assert(deps.hud, "explicit hud required"), io=io_,
                profile=profile, sites=data.sites.titles[title].sites, area_map=data.area_map,
                player=assert(deps.player, "explicit player required"), rom_type=def.rom_type,
                rom_sha1=profile.rom_sha1, log=deps.log,
                hello_session=load("lua/hello_session.lua"), reply_dispatch=load("lua/reply_dispatch.lua"),
            })
        end
        assert(io_.domain_size("ROM") == size and Admission.sha1(read_rom, size) == profile.rom_sha1
               and io_.domain_size("ROM") == size, "candidate ROM changed during composition")
        return {pack=def.pack, title=deps.title, profile=profile, data=data, reads=reads, writes=writes,
                rom=rom, client=client, production_admitted=false, runtime_started=false,
                qualification="SOURCE_MODEL_CANDIDATE"}
    end)
    if not ok then return nil, tostring(result) end
    return result
end

-- Header family (ROM $0134..$0143). It only picks which pack build_candidate hash-checks.
local HEADERS = {PM_CRYSTAL="crystal", POKEMON_GLD="gold", POKEMON_SLV="silver"}
function Entry.detect_title(read_rom_u8)
    local chars = {}
    for i = 0, 15 do
        local b = read_rom_u8(0x134 + i)
        if b < 0x20 or b > 0x7E then break end
        chars[#chars + 1] = string.char(b)
    end
    local header = table.concat(chars)
    for prefix, title in pairs(HEADERS) do
        if header:sub(1, #prefix) == prefix then return title, header end
    end
    return nil, header
end

function Entry.build(deps)
    local decision, reason = Entry.admit(deps)
    if not decision then return nil, reason end
    return nil, "Gen 2 production runtime composition is not implemented"
end

return Entry
