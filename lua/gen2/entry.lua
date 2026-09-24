-- Gen 2 composition: the SOURCE/MODEL candidate graph and the admitted production graph.
-- No emulator global. build_candidate requires explicit candidate_only=true and injected
-- IO/policies; with deps.net it also composes the Gen 2 client (lua/gen2/client.lua) over
-- the same MODEL graph (model_only IO, MODEL_PROBE signals, an injected checkpoint).
-- build is production: admit() passes only a SELECTED, BUILT row whose G1 gate is ADMITTED
-- (owner ruling O-22) AND whose shipped PHYSICAL receipts re-validate now (U1 engine sites,
-- U2 write windows, each bound to its committed fixture-qualification report): Crystal 1.0,
-- Gold and Silver (O-22; Silver's U2 is Gold's receipt, O-23). Crystal 1.1 stays BUILD_ONLY.
-- Either graph stays runtime_started=false until client:start().
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
-- The O-22 proofs a production pack ships as release data: byte copies of the committed
-- tests/fixtures/gen2/receipts/ files (tests/unit/test_gen2_entry.py pins them equal).
-- A pack absent here can never be admitted, whatever its admission.json says.
Entry.RECEIPT_FILES = {
    gen2_crystal={
        engine_sites="data/games/gen2_crystal/receipts/crystal.engine_sites.json",
        write_window="data/games/gen2_crystal/receipts/crystal.write_window.json",
        qualifications={
            crystal_battle="data/games/gen2_crystal/receipts/crystal_battle.qualification.json",
            crystal_town="data/games/gen2_crystal/receipts/crystal_town.qualification.json",
        },
    },
    gen2_gold={
        engine_sites="data/games/gen2_gold/receipts/gold.engine_sites.json",
        write_window="data/games/gen2_gold/receipts/gold.write_window.json",
        qualifications={
            gold_battle="data/games/gen2_gold/receipts/gold_battle.qualification.json",
            -- the Gold U1 engine-site receipt's fixture (card gen2-u1e-poison; S.U1_FIXTURES)
            gold_battle_errand="data/games/gen2_gold/receipts/gold_battle_errand.qualification.json",
            gold_town="data/games/gen2_gold/receipts/gold_town.qualification.json",
        },
    },
    -- O-23: Silver's U2 proof is Gold's write-window receipt (gen2_write_safety M.RECEIPT_TITLE),
    -- valid only while the checkpoint rows stay identical; its U1 proof is its own.
    gen2_silver={
        engine_sites="data/games/gen2_silver/receipts/silver.engine_sites.json",
        write_window="data/games/gen2_silver/receipts/gold.write_window.json",
        qualifications={
            silver_battle="data/games/gen2_silver/receipts/silver_battle.qualification.json",
            gold_battle="data/games/gen2_silver/receipts/gold_battle.qualification.json",
            gold_town="data/games/gen2_silver/receipts/gold_town.qualification.json",
        },
    },
}
-- Permit operation (lua/gen2/writes.lua) -> the U2 write kind that authorizes it. Anything
-- else (write_party_bytes, explode) has no receipt kind and is refused. The box
-- executor's CartRAM spans carry their own kinds (lua/gen2/boxes.lua B.kind_of).
-- battle_faint (O-30): the active faint and a bench faint inside the battle hold; its kind is checked
-- at that hold (gen2_write_safety BATTLE_KINDS), never at the overworld checkpoint.
Entry.WRITE_KIND = {party_faint="party_hp", party_collection="party_collection", battle_faint="battle_faint"}
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

-- The O-22 proofs of one title, re-validated from the shipped receipts: {engine, write,
-- proven, scope}, or nil,why. The validators recompute every verdict from raw records.
local function proofs(root, json, data, title, pack)
    local files = Entry.RECEIPT_FILES[pack]
    if not files then return nil, "no shipped PHYSICAL receipts for " .. tostring(title) end
    local S, M = dofile(root .. "/lua/gen2/signals.lua"), dofile(root .. "/lua/gen2_write_safety.lua")
    local function read(rel) return load_json(json, root .. "/" .. rel) end
    local engine, write, reports = read(files.engine_sites), read(files.write_window), {}
    for fixture, rel in pairs(files.qualifications) do reports[fixture] = read(rel) end
    local proven, why = S.qualified_sites(title, data.sites, engine)
    if not proven then return nil, "U1 engine-site receipt: " .. tostring(why) end
    local bound
    bound, why = S.bind_fixture_qualification(engine, reports[engine.fixture])
    if not bound then return nil, "U1 engine-site receipt: " .. tostring(why) end
    local scope
    scope, why = M.qualified(data.checkpoint, title, write)
    if not scope then return nil, "U2 write-window receipt: " .. tostring(why) end
    bound, why = M.bind_fixture_qualification(write, reports)
    if not bound then return nil, "U2 write-window receipt: " .. tostring(why) end
    return {engine=engine, write=write, proven=proven, scope=scope}
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
                if row.status ~= "BUILT" or matrix.gate.state ~= "ADMITTED" then
                    return false, "Gen 2 catalog status " .. tostring(row.status) .. "; G1 " .. tostring(matrix.gate.state)
                                  .. "; source catalog grants no runtime admission"
                end
                -- The gate row is the grant, never the proof: the receipts must still pass.
                local proof, why = proofs(root, json, candidate.data, candidate.title, candidate.def.pack)
                if not proof then return false, "G1 ADMITTED but the PHYSICAL proof refused: " .. why end
                return true
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

-- One composition, two graphs. Candidate (production=false): the explicit source/model
-- graph, never admitted, with an injected checkpoint and write policy. Production (only
-- behind Entry.admit): checkpoint, write policy, signals and the checkpoint hook are built
-- HERE from the re-validated receipts, and the client always exists.
local function compose(deps, title, production)
    local ok, result = pcall(function()
        if not production then assert(deps.candidate_only == true, "explicit candidate_only=true required") end
        local root = assert(deps.root, "root required")
        local io_ = assert(deps.io, "explicit IO required")
        local load = function(path) return dofile(root .. "/" .. path) end
        local json, Admission = load("lua/json_codec.lua"), load("lua/admission.lua")
        local data, profile, def = load_pack(root, json, assert(title, "selected title required"))
        assert(type(io_.read_u8) == "function" and type(io_.domain_size) == "function", "explicit ROM IO required")
        local size = io_.domain_size("ROM")
        assert(size == profile.derived.rom_size, "candidate ROM size mismatch")
        local function read_rom(offset) return io_.read_u8(offset, "ROM") end
        assert(Admission.sha1(read_rom, size) == profile.rom_sha1, "candidate ROM hash mismatch")
        assert(Admission.anchors_match(source_anchors(data, title), {size=size, read_u8=read_rom}, "sha1"),
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
        local checkpoint, write_policy, proof
        if production then
            assert(io_.model_only ~= true, "production requires live IO, not model_only")
            proof = assert(proofs(root, json, data, title, def.pack))
            local hrom = assert(profile.ram.hROMBank, "hROMBank coordinate required")
            local function held() return io_.framecount() end
            local function still(token) return token == io_.framecount() end
            -- Host observations exactly as the U2 PHYSICAL gate made them (lua/tests/gen2_write_windows.lua):
            -- the hROMBank shadow, SVBK (0 selects 1), a same-frame hold.
            checkpoint = load("lua/gen2_write_safety.lua").new(data.checkpoint, title, io_, load("lua/gb_checkpoint.lua"), {
                capture=held, valid=still,
                admitted=function(t, sha) return t == title and sha == profile.rom_sha1 end,
                -- ponytail: the production graph is the only writer; save/trade/serial ownership is the
                -- pack predicates' job (wGameLogicPaused, wLinkMode, hSerialConnectionStatus, SC).
                no_conflicting_owner=function() return true end,
                mapped_rom_bank=function() return io_.read_u8(hrom, "System Bus") end,
                effective_wram_bank=function()
                    local svbk = io_.read_u8(0xFF70, "System Bus") % 8
                    return svbk == 0 and 1 or svbk
                end,
            }, proof.write)
            write_policy = {
                -- Every permit write re-proves the held checkpoint for its receipt kind.
                authorize=function(operation)
                    local kind = Entry.WRITE_KIND[operation]
                    return kind ~= nil and checkpoint:check(kind) == true
                end,
                pointer_stable=function() return true end, -- ponytail: the party array is fixed WRAM
                lifetime={capture=held, valid=still},
                provenance=function() return {site="lua/gen2/entry.lua production", evidence="U2 PHYSICAL receipt"} end,
            }
        else
            write_policy = assert(deps.write_policy, "explicit candidate write policy required")
        end
        local hold_facts = data.checkpoint.titles[title]
        local writes = Writes.new(profile, io_, Permit, write_policy, hold_facts.battle_hold.write)
        local rom = Rom.new(profile, io_)
        local client
        if production or deps.net ~= nil then
            local Signals, Registry, GB = load("lua/gen2/signals.lua"), load("lua/hook_registry.lua"),
                                          load("lua/gb_hook_binding.lua")
            local options = {title=title, profile=data.profile, pack=data.sites, io=io_,
                Registry=Registry, GB=GB, reads=reads, owner="SLink-gen2", max_pending=64,
                areas=data.area_map, encounters=data.encounters, statics=data.statics}
            local signals
            if production then
                -- signals.new registers exactly the receipt's proven sites, under PHYSICAL authority.
                options.runtime_qualification = proof.engine
                signals = function(authority)
                    options.authority = {kind="PHYSICAL_RUNTIME", capture=authority.capture, valid=authority.valid}
                    return Signals.new(options)
                end
            else
                -- The candidate client is MODEL by construction: signals.new_model registers.
                assert(io_.model_only == true, "candidate client requires model_only IO")
                checkpoint = assert(deps.checkpoint, "explicit candidate checkpoint required")
                assert(type(checkpoint.check) == "function", "checkpoint:check required")
                signals = function(authority)
                    options.authority = authority
                    return Signals.new_model(options)
                end
            end
            -- The box executor (card BOX): box_mon / party_mon / memorialize. Every span re-proves the
            -- held checkpoint for its own kind; a kind the receipt never proved refuses before a byte.
            local Boxes, wire = load("lua/gen2/boxes.lua"), load("lua/gen2/wire.lua")
            local lifetime = production and {capture=function() return io_.framecount() end,
                                             valid=function(token) return token == io_.framecount() end}
                             or write_policy.lifetime
            local gate = Boxes.cart_gate({Permit=Permit, profile=profile, io=io_, lifetime=lifetime,
                check=function(kind) return checkpoint:check(kind) == true end,
                provenance=function() return {site="lua/gen2/entry.lua box executor"} end})
            local pp, mail = {}, {}
            for _, move in ipairs(data.moves.moves) do pp[move.id] = move.pp end
            for _, id in ipairs(data.items.mail_ids) do mail[id] = true end
            local boxes = Boxes.executor({profile=profile, reads=reads, key=wire.mon_key, writes=writes,
                box=Boxes.new(profile, gate), io=io_, base_stats=rom.base_stats,
                move_pp=function(id) return assert(pp[id], "unknown move") end, mail=mail,
                covers=function(kind)
                    return type(checkpoint.covers) == "function" and checkpoint:covers(kind) == true
                end})
            -- P4.1f panel: production only; it writes WRAM0 through its own panel permit. A clean
            -- cartridge has no live SLNK service, so it reads ABSENT and never paints.
            local panel, phone
            if production then
                local Panel = load("lua/gen2/panel.lua")
                panel = Panel.new(profile, data.charmap, io_, Panel.writes(io_, Permit),
                                  assert(deps.hud, "explicit hud required").sanitize or function(s) return s end)
                -- P4.5c: the phone calls post +32 through their own one-byte "phone" window
                phone = panel and load("lua/gen2/phone.lua").new(panel, io_, Panel.writes(io_, Permit), deps.log)
            end
            -- P4.3b native trade: only a profile whose overlay .sym carries the P4.3a trade family
            -- (gen_gen2_profile trade_block); the client still gates on the kind and the cap bit.
            -- ponytail: production passes no artifact_kind until the overlay admission lands.
            local trade
            if profile.overlay and profile.overlay.trade then
                local T = load("lua/gen2/trade_overlay.lua")
                trade = T.new(profile, io_, Permit, T.holdable(data.items))
            end
            client = load("lua/gen2/client.lua").new({
                trade=trade, artifact_kind=(not production) and deps.artifact_kind or nil,
                reads=reads, wire=wire, writes=writes, rom=rom, boxes=boxes, panel=panel, phone=phone,
                safety={check=function(kind) return checkpoint:check(kind) end},
                signals=signals,
                -- production only: the held checkpoint PC the client hooks (writes + hello readiness)
                checkpoint_pc=production and data.checkpoint.titles[title].primary.execution_before.pc or nil,
                -- O-30: the battle hold the client hooks for in-battle deaths. Production composes it only
                -- behind a receipt covering battle_faint; until then battle deaths wait for the checkpoint.
                battle_hold=(not production or checkpoint:covers("battle_faint"))
                    and hold_facts.battle_hold or nil,
                contest_mask=hold_facts.contest_mask,
                net=deps.net, json=json, hud=assert(deps.hud, "explicit hud required"), io=io_,
                profile=profile, sites=data.sites.titles[title].sites, area_map=data.area_map,
                player=assert(deps.player, "explicit player required"), rom_type=def.rom_type,
                rom_sha1=profile.rom_sha1, log=deps.log,
                evolutions=data.evolutions.evolutions, -- force_faint's evolved-identity fallback
                hello_session=load("lua/hello_session.lua"), reply_dispatch=load("lua/reply_dispatch.lua"),
            })
        end
        assert(io_.domain_size("ROM") == size and Admission.sha1(read_rom, size) == profile.rom_sha1
               and io_.domain_size("ROM") == size, "candidate ROM changed during composition")
        return {pack=def.pack, title=title, profile=profile, data=data, reads=reads, writes=writes,
                rom=rom, client=client, checkpoint=checkpoint, production_admitted=production,
                runtime_started=false, proven_sites=proof and proof.proven, write_scope=proof and proof.scope,
                qualification=production and "PHYSICAL_RECEIPTED" or "SOURCE_MODEL_CANDIDATE"}
    end)
    if not ok then return nil, tostring(result) end
    return result
end

-- Explicit, non-activated source/model graph; never a production build path.
function Entry.build_candidate(deps)
    return compose(deps, deps.title, false)
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

-- Production: the admitted title's graph (see compose). deps = admit()'s root, rom_size and
-- read_rom_u8, plus live io (not model_only), net, hud, player and log.
function Entry.build(deps)
    local decision, reason = Entry.admit(deps)
    if not decision then return nil, reason end
    if deps.title ~= nil and deps.title ~= decision.title then
        return nil, "admitted title " .. decision.title .. " differs from the requested " .. tostring(deps.title)
    end
    return compose(deps, decision.title, true)
end

return Entry
