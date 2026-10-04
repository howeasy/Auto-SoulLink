-- Gen 2 composition: the SOURCE/MODEL candidate graph and the admitted production graph.
-- No emulator global. build_candidate requires explicit candidate_only=true and injected
-- IO/policies; with deps.net it also composes the Gen 2 client (lua/gen2/client.lua) over
-- the same MODEL graph (model_only IO, MODEL_PROBE signals, an injected checkpoint).
-- build is production: admit() passes only an ACTIVATED OVERLAY row (SELECTED, ADMITTED, runtime_gate G4 ADMITTED,
-- binding_sha256 pin; OVERLAY_ADMISSION D1), AND whose own shipped PHYSICAL receipts re-validate now (U1 engine sites,
-- U2 write windows, each bound to its committed fixture-qualification report, per RECEIPT_FILES[pack][kind]).
-- A CLEAN cartridge is never admitted, whatever its G1 row says: the SLink companion is REQUIRED for Crystal, Gold and
-- Silver (patch-first, owner 2026-10-02); the clean rows and receipts remain only as the overlay's base and evidence
-- (Silver's clean U2 was Gold's receipt, O-23; an overlay has its own). Crystal 1.1 stays BUILD_ONLY. What executes is the admission
-- decision's (kind + the ACTUAL rehashed sha1, D5), read through lua/gen2/artifact.lua's view; never a caller's claim.
-- Either graph stays runtime_started=false until client:start().
local Entry = {}

Entry.PACKS = {
    crystal={pack="gen2_crystal", artifact="pokecrystal", revision="1.0", rom_type="Crystal"},
    gold={pack="gen2_gold", artifact="pokegold", revision="US", rom_type="Gold"},
    silver={pack="gen2_silver", artifact="pokesilver", revision="US", rom_type="Silver"},
    -- DEV-GRADE (P3a): admitted by Entry.admit_polished only, never by Entry.admit's catalog/G4/receipt gate;
    -- composed by compose_polished (lua/gen2/polished.lua holds the reads), qualification DEV_OVERLAY_SHA1.
    polished={pack="polished_crystal", artifact="polishedcrystal", revision="3.2.3", rom_type="polished_crystal",
              dev=true},
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
    -- dev pack: only what run.lua, Entry.admit_polished and compose_polished read (lua/gen2/polished.lua
    -- P.PROFILE/P.CHARMAP + the force_faint evolution table + the client's area_map)
    polished_crystal={
        profile="data/games/polished_crystal/profile.json",
        charmap="data/games/polished_crystal/charmap.lua",
        evolutions="data/games/polished_crystal/evolutions.json",
        area_map="data/games/polished_crystal/area_map.json",
    },
}
-- The O-22 proofs a production pack ships as release data: byte copies of the committed
-- tests/fixtures/gen2/receipts/ files (tests/unit/test_gen2_entry.py pins them equal).
-- A pack absent here can never be admitted, whatever its admission.json says.
-- D4 (docs/gen2/OVERLAY_ADMISSION.md): proofs are per ARTIFACT KIND. .clean is the O-22 set, unchanged; .overlay holds the
-- proofs captured on the PATCHED cartridge itself under receipts/overlay/, never shared with clean (every overlay
-- qualification is a fresh boot/re-save/reload on the overlay ROM). Silver's overlay has its OWN write window: the
-- O-23 Gold-for-Silver reuse is clean-only. proofs() has no fallback from overlay to clean.
Entry.RECEIPT_FILES = {
    gen2_crystal={
        clean={
            engine_sites="data/games/gen2_crystal/receipts/crystal.engine_sites.json",
            write_window="data/games/gen2_crystal/receipts/crystal.write_window.json",
            qualifications={
                crystal_battle="data/games/gen2_crystal/receipts/crystal_battle.qualification.json",
                crystal_town="data/games/gen2_crystal/receipts/crystal_town.qualification.json",
                -- card U1G: the committed O-33 disclosures (the admission trust root for the synthetic runs' bytes)
                crystal_synth_grass="data/games/gen2_crystal/receipts/crystal_synth_grass.synth.json",
                crystal_synth_kyle="data/games/gen2_crystal/receipts/crystal_synth_kyle.synth.json",
                crystal_synth_bill="data/games/gen2_crystal/receipts/crystal_synth_bill.synth.json",
            },
        },
        overlay={
            engine_sites="data/games/gen2_crystal/receipts/overlay/crystal.engine_sites.json",
            write_window="data/games/gen2_crystal/receipts/overlay/crystal.write_window.json",
            qualifications={
                crystal_battle="data/games/gen2_crystal/receipts/overlay/crystal_battle.qualification.json",
                crystal_town="data/games/gen2_crystal/receipts/overlay/crystal_town.qualification.json",
                crystal_synth_grass="data/games/gen2_crystal/receipts/overlay/crystal_synth_grass.synth.json",
                crystal_synth_kyle="data/games/gen2_crystal/receipts/overlay/crystal_synth_kyle.synth.json",
                crystal_synth_bill="data/games/gen2_crystal/receipts/overlay/crystal_synth_bill.synth.json",
            },
        },
    },
    gen2_gold={
        clean={
            engine_sites="data/games/gen2_gold/receipts/gold.engine_sites.json",
            write_window="data/games/gen2_gold/receipts/gold.write_window.json",
            qualifications={
                gold_battle="data/games/gen2_gold/receipts/gold_battle.qualification.json",
                -- the Gold U1 engine-site receipt's fixture (card gen2-u1e-poison; S.U1_FIXTURES)
                gold_battle_errand="data/games/gen2_gold/receipts/gold_battle_errand.qualification.json",
                gold_town="data/games/gen2_gold/receipts/gold_town.qualification.json",
                gold_synth_grass="data/games/gen2_gold/receipts/gold_synth_grass.synth.json",
                gold_synth_kyle="data/games/gen2_gold/receipts/gold_synth_kyle.synth.json",
                gold_synth_bill="data/games/gen2_gold/receipts/gold_synth_bill.synth.json",
            },
        },
        overlay={
            engine_sites="data/games/gen2_gold/receipts/overlay/gold.engine_sites.json",
            write_window="data/games/gen2_gold/receipts/overlay/gold.write_window.json",
            qualifications={
                gold_battle="data/games/gen2_gold/receipts/overlay/gold_battle.qualification.json",
                gold_battle_errand="data/games/gen2_gold/receipts/overlay/gold_battle_errand.qualification.json",
                gold_town="data/games/gen2_gold/receipts/overlay/gold_town.qualification.json",
                gold_synth_grass="data/games/gen2_gold/receipts/overlay/gold_synth_grass.synth.json",
                gold_synth_kyle="data/games/gen2_gold/receipts/overlay/gold_synth_kyle.synth.json",
                gold_synth_bill="data/games/gen2_gold/receipts/overlay/gold_synth_bill.synth.json",
            },
        },
    },
    -- O-23 (clean only): Silver's U2 proof is Gold's write-window receipt (gen2_write_safety M.RECEIPT_TITLE),
    -- valid only while the checkpoint rows stay identical; its U1 proof is its own.
    gen2_silver={
        clean={
            engine_sites="data/games/gen2_silver/receipts/silver.engine_sites.json",
            write_window="data/games/gen2_silver/receipts/gold.write_window.json",
            qualifications={
                silver_battle="data/games/gen2_silver/receipts/silver_battle.qualification.json",
                gold_battle="data/games/gen2_silver/receipts/gold_battle.qualification.json",
                gold_town="data/games/gen2_silver/receipts/gold_town.qualification.json",
                -- card U1G: silver_town is the base of the synthetic kyle/bill runs
                silver_town="data/games/gen2_silver/receipts/silver_town.qualification.json",
                silver_synth_grass="data/games/gen2_silver/receipts/silver_synth_grass.synth.json",
                silver_synth_kyle="data/games/gen2_silver/receipts/silver_synth_kyle.synth.json",
                silver_synth_bill="data/games/gen2_silver/receipts/silver_synth_bill.synth.json",
            },
        },
        overlay={
            engine_sites="data/games/gen2_silver/receipts/overlay/silver.engine_sites.json",
            write_window="data/games/gen2_silver/receipts/overlay/silver.write_window.json",
            qualifications={
                silver_battle="data/games/gen2_silver/receipts/overlay/silver_battle.qualification.json",
                silver_town="data/games/gen2_silver/receipts/overlay/silver_town.qualification.json",
                silver_synth_grass="data/games/gen2_silver/receipts/overlay/silver_synth_grass.synth.json",
                silver_synth_kyle="data/games/gen2_silver/receipts/overlay/silver_synth_kyle.synth.json",
                silver_synth_bill="data/games/gen2_silver/receipts/overlay/silver_synth_bill.synth.json",
            },
        },
    },
}
-- Permit operation (lua/gen2/writes.lua) -> the U2 write kind that authorizes it. Anything
-- else (write_party_bytes) has no receipt kind and is refused. The box
-- executor's CartRAM spans carry their own kinds (lua/gen2/boxes.lua B.kind_of).
-- battle_faint (O-30): the active faint and a bench faint inside the battle hold; its kind is checked
-- at that hold (gen2_write_safety BATTLE_KINDS), never at the overworld checkpoint.
-- battle_bench (O-32): a bench faint on receipt, at a battle frame end (gen2_write_safety BENCH_KINDS).
-- W-3/W-4 (owner 2026-09-26, Gen 1 parity) reuse the WINDOW proofs of the moment they write at, not new
-- kinds: explode lands at the battle hold (battle_faint's held evaluation), the rival party at a battle
-- frame end (battle_bench's evaluate_frame). Their effect is proved by the live gates, not the receipt.
Entry.WRITE_KIND = {party_faint="party_hp", party_collection="party_collection", battle_faint="battle_faint",
                    battle_bench="battle_bench", battle_explode="battle_faint", enemy_party="battle_bench"}
local titles = {"crystal", "gold", "silver"}
local order = {"profile", "admission", "sites", "checkpoint", "area_map", "statics", "encounters",
               "species", "evolutions", "gifts", "moves", "trainers", "map_names", "items", "charmap"}

local function hex(value, width) return type(value) == "string" and #value == width and value:match("^%x+$") ~= nil end

local function load_json(json, path)
    local handle = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = handle:read("*a")
    handle:close()
    return assert(json.decode(text))
end

local function load_pack(root, json, title)
    local def = assert(Entry.PACKS[title], "unsupported selected Gen 2 title")
    assert(not def.dev, "a dev title has no Gen 2 production pack")
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
    assert(matrix.schema_version == 2 and matrix.foundation == "gen2_gsc" and matrix.pack == def.pack
           and matrix.title == title and matrix.selected_revision == def.revision
           and matrix.source_lock_sha256 == wrapper.source.lock_sha256, "admission/source catalog mismatch")
    assert(matrix.unknown_hash_policy == "REFUSE" and matrix.gate and matrix.gate.id == "G1",
           "explicit fail-closed Gen 2 admission policy required")
    return data, profile, def
end

-- D3: the EXECUTED artifact's facts (kind, rom_sha1, binding_sha256, sites, checkpoint, header anchors, ROM-valued
-- profile coordinates), from lua/gen2/artifact.lua. Clean is the pack itself; an overlay is its pinned binding
-- sidecar. A refusal here never falls back to the clean pack.
local function view_of(root, json, data, title, row)
    local Artifact = dofile(root .. "/lua/gen2/artifact.lua")
    return Artifact.view(root, json, data, title, row)
end

-- The catalog row an ACTUAL rehashed sha1 names, of the kind the admission decision gave (never a caller's claim).
local function find_view(root, json, data, title, kind, sha1)
    local found
    for _, row in ipairs(data.admission.artifacts) do
        if row.kind == kind and row.sha1 == sha1 then
            if found then return nil, "ambiguous " .. kind .. " catalog rows for " .. tostring(sha1) end
            found = row
        end
    end
    if not found then return nil, "no " .. kind .. " catalog row for the executed ROM " .. tostring(sha1) end
    return view_of(root, json, data, title, found)
end

-- D5: every executed anchor, read from the view: its engine sites (+ preludes), its checkpoint anchors and its header
-- anchors. (A clean view whose header anchors are not filled yet derives them from the pack's area map.)
local function source_anchors(data, title, view)
    local anchors = {}
    local sites = assert(view.sites, "source engine sites required")
    for _, site in pairs(sites) do
        anchors[#anchors + 1] = {offset=site.rom_offset, hex=site.expected_hex}
        if site.prelude then anchors[#anchors + 1] = {offset=site.prelude.rom_offset, hex=site.prelude.expected_hex} end
    end
    local checkpoint = assert(view.checkpoint.primary.anchors, "source checkpoint anchors required")
    for _, anchor in pairs(checkpoint) do anchors[#anchors + 1] = {offset=anchor.rom_offset, hex=anchor.expected_hex} end
    -- lua/gen2/artifact.lua fills header anchors for both kinds (clean from the area map).
    for _, anchor in pairs(assert(view.anchors, "header anchors required")) do
        anchors[#anchors + 1] = {offset=anchor.offset, hex=anchor.hex}
    end
    assert(#anchors > 0, "required source anchor inventory empty")
    return anchors
end

-- The O-22 proofs of one title and ARTIFACT KIND (view.kind), re-validated from the shipped receipts: {engine, write,
-- proven, scope}, or nil,why. The validators recompute every verdict from raw records and bind every run to the
-- view's executed sha1, kind and binding. No view, or a kind with no receipt set, proves nothing (no clean fallback).
local function proofs(root, json, data, title, pack, view)
    if type(view) ~= "table" then return nil, "artifact view required" end
    local group = Entry.RECEIPT_FILES[pack]
    local files = group and group[view.kind]
    if not files then return nil, "no shipped PHYSICAL " .. tostring(view.kind) .. " receipts for " .. tostring(title) end
    local S, M = dofile(root .. "/lua/gen2/signals.lua"), dofile(root .. "/lua/gen2_write_safety.lua")
    local function read(rel) return load_json(json, root .. "/" .. rel) end
    local engine, write, reports = read(files.engine_sites), read(files.write_window), {}
    for fixture, rel in pairs(files.qualifications) do reports[fixture] = read(rel) end
    local proven, why = S.qualified_sites(title, data.sites, engine, view)
    if not proven then return nil, "U1 engine-site receipt: " .. tostring(why) end
    local bound
    -- a v2 receipt (card U1G) binds each run to its own report: it takes them all by fixture name
    bound, why = S.bind_fixture_qualification(engine, engine.runs and reports or reports[engine.fixture], view)
    if not bound then return nil, "U1 engine-site receipt: " .. tostring(why) end
    local scope
    scope, why = M.qualified(data.checkpoint, title, write, view)
    if not scope then return nil, "U2 write-window receipt: " .. tostring(why) end
    bound, why = M.bind_fixture_qualification(write, reports, view)
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
                local row = candidate.row
                if row.kind ~= "clean" and row.kind ~= "overlay" then
                    return false, "Gen 2 artifact kind " .. tostring(row.kind) .. " is not admitted"
                end
                if row.selection ~= "SELECTED" then return false, "artifact selection " .. tostring(row.selection) .. " is not admitted" end
                -- Patch-first (owner 2026-10-02): the companion is REQUIRED for every Gen 2 title, so
                -- a clean cartridge is never admitted, whatever its row and gate say.
                if row.kind == "clean" then
                    return false, "this " .. candidate.title .. " cartridge needs the SLink companion patch; "
                                  .. "prepare it through the Manager or /patcher"
                end
                -- D1: an activated overlay row carries its own G4 grant and its binding pin.
                local grant, gate = "G4", row.runtime_gate
                if row.status ~= "ADMITTED" then
                    return false, "Gen 2 catalog status " .. tostring(row.status) .. " for the overlay; source catalog grants no runtime admission"
                end
                if type(gate) ~= "table" or gate.id ~= "G4" or gate.state ~= "ADMITTED" then
                    return false, "overlay runtime gate G4 is not ADMITTED"
                end
                if not hex(gate.grant_fingerprint, 64) then return false, "overlay G4 grant fingerprint missing or malformed" end
                if not hex(row.binding_sha256, 64) then return false, "overlay execution binding pin missing or malformed" end
                local view, why = view_of(root, json, candidate.data, candidate.title, row)
                if not view then return false, row.kind .. " execution view refused: " .. tostring(why) end
                if view.kind ~= row.kind or view.rom_sha1 ~= row.sha1 then
                    return false, "execution view is not the catalog row's artifact"
                end
                -- The gate row is the grant, never the proof: this artifact's own receipts must still pass.
                local proof
                proof, why = proofs(root, json, candidate.data, candidate.title, candidate.def.pack, view)
                if not proof then return false, grant .. " ADMITTED but the PHYSICAL proof refused: " .. why end
                candidate.view = view
                return true
            end,
            anchors=function(candidate) return source_anchors(candidate.data, candidate.title, candidate.view) end,
            kind=function(candidate, mode)
                if mode == "sha1" and (candidate.row.kind == "clean" or candidate.row.kind == "overlay") then
                    return candidate.row.kind
                end
                return nil, "unsupported Gen 2 artifact kind/mode"
            end,
            describe=function(candidate, kind)
                return {pack=candidate.def.pack, title=candidate.title, kind=kind,
                        foundation="gen2_gsc", rom_type=candidate.def.rom_type,
                        binding_sha256=kind == "overlay" and candidate.row.binding_sha256 or nil}
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
-- decision: production only, the admission decision (kind + the ACTUAL rehashed sha1) that names what executes (D5).
local function compose(deps, title, production, decision)
    local ok, result = pcall(function()
        if not production then assert(deps.candidate_only == true, "explicit candidate_only=true required") end
        assert(not production or (type(decision) == "table" and decision.title == title and decision.rehashed == true),
               "production composes only an admitted decision")
        local root = assert(deps.root, "root required")
        local io_ = assert(deps.io, "explicit IO required")
        local load = function(path) return dofile(root .. "/" .. path) end
        local json, Admission = load("lua/json_codec.lua"), load("lua/admission.lua")
        local data, profile, def = load_pack(root, json, assert(title, "selected title required"))
        assert(type(io_.read_u8) == "function" and type(io_.domain_size) == "function", "explicit ROM IO required")
        local size = io_.domain_size("ROM")
        assert(size == profile.derived.rom_size, "candidate ROM size mismatch")
        local function read_rom(offset) return io_.read_u8(offset, "ROM") end
        -- D5: identity is the decision's (kind + actual sha1); a candidate is the clean pack. deps.artifact_kind never
        -- chooses what production composes.
        local kind = production and decision.kind or "clean"
        local executed_sha = production and decision.rom_sha1 or profile.rom_sha1
        assert(Admission.sha1(read_rom, size) == executed_sha, "candidate ROM hash mismatch")
        local view = assert(find_view(root, json, data, title, kind, executed_sha))
        assert(view.kind == kind and view.rom_sha1 == executed_sha, "execution view differs from the admitted artifact")
        assert(Admission.anchors_match(source_anchors(data, title, view), {size=size, read_u8=read_rom}, "sha1"),
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
            proof = assert(proofs(root, json, data, title, def.pack, view))
            local hrom = assert(profile.ram.hROMBank, "hROMBank coordinate required")
            local function held() return io_.framecount() end
            local function still(token) return token == io_.framecount() end
            -- Host observations exactly as the U2 PHYSICAL gate made them (lua/tests/gen2_write_windows.lua):
            -- the hROMBank shadow, SVBK (0 selects 1), a same-frame hold.
            checkpoint = load("lua/gen2_write_safety.lua").new(data.checkpoint, title, io_, load("lua/gb_checkpoint.lua"), {
                capture=held, valid=still,
                admitted=function(t, sha) return t == title and sha == executed_sha end,
                -- ponytail: the production graph is the only writer; save/trade/serial ownership is the
                -- pack predicates' job (wGameLogicPaused, wLinkMode, hSerialConnectionStatus, SC).
                no_conflicting_owner=function() return true end,
                mapped_rom_bank=function() return io_.read_u8(hrom, "System Bus") end,
                effective_wram_bank=function()
                    local svbk = io_.read_u8(0xFF70, "System Bus") % 8
                    return svbk == 0 and 1 or svbk
                end,
            }, proof.write, view)
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
        local hold_facts = view.checkpoint
        local writes = Writes.new(profile, io_, Permit, write_policy, hold_facts.battle_hold.write)
        -- ROM-valued profile coordinates are the executed artifact's (an overlay may relocate them)
        local rom_profile = profile
        if view.profile_rom ~= nil then
            local merged = {}
            for name, entry in pairs(profile.rom) do merged[name] = entry end
            for name, entry in pairs(view.profile_rom) do merged[name] = entry end
            rom_profile = {}
            for name, value in pairs(profile) do rom_profile[name] = value end
            rom_profile.rom = merged
        end
        local rom = Rom.new(rom_profile, io_)
        local client
        if production or deps.net ~= nil then
            local Signals, Registry, GB = load("lua/gen2/signals.lua"), load("lua/hook_registry.lua"),
                                          load("lua/gb_hook_binding.lua")
            local options = {title=title, profile=data.profile, pack=data.sites, io=io_,
                Registry=Registry, GB=GB, reads=reads, owner="SLink-gen2", max_pending=64,
                areas=data.area_map, encounters=data.encounters, statics=data.statics, gifts=data.gifts}
            local signals
            if production then
                -- signals.new registers exactly the receipt's proven sites, under PHYSICAL authority.
                options.runtime_qualification, options.view = proof.engine, view
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
                -- PHONE-NAMES: the profile's overlay.phone.stage (wUnusedMapBuffer) carries the names
                local ph = profile.overlay and profile.overlay.phone
                phone = panel and load("lua/gen2/phone.lua").new(panel, io_, Panel.writes(io_, Permit), deps.log,
                    ph and {stage=ph.stage, charmap=data.charmap,
                            encode=load("lua/gen2/trade_overlay.lua").encode_name} or nil)
            end
            -- P4.3b native trade: only a profile whose overlay .sym carries the P4.3a trade family
            -- (gen_gen2_profile trade_block); the client still gates on the kind and the cap bit.
            -- D5: production's kind is the decision's; only the MODEL candidate takes a caller's artifact_kind.
            local client_kind = production and decision.kind or deps.artifact_kind
            local trade
            if profile.overlay and profile.overlay.trade then
                local T = load("lua/gen2/trade_overlay.lua")
                trade = T.new(profile, io_, Permit, T.holdable(data.items), data.charmap)
            end
            client = load("lua/gen2/client.lua").new({
                trade=trade, artifact_kind=client_kind,
                reads=reads, wire=wire, writes=writes, rom=rom, boxes=boxes, panel=panel, phone=phone,
                safety={check=function(kind) return checkpoint:check(kind) end},
                signals=signals,
                -- production only: the held checkpoint PC the client hooks (writes + hello readiness)
                checkpoint_pc=production and view.checkpoint.primary.execution_before.pc or nil,
                -- O-30: the battle hold the client hooks for in-battle deaths. Production composes it only
                -- behind a receipt covering battle_faint; until then battle deaths wait for the checkpoint.
                battle_hold=(not production or checkpoint:covers("battle_faint"))
                    and hold_facts.battle_hold or nil,
                -- O-32: bench deaths land on receipt; only with the hold (which settles the switch-in race)
                -- and, in production, a receipt covering battle_bench
                battle_bench=(not production or (checkpoint:covers("battle_faint") and checkpoint:covers("battle_bench"))),
                -- W-4: the rival swap writes at a battle frame end, so it needs the battle_bench proof too
                rival_swap=(not production or checkpoint:covers("battle_bench")),
                contest_mask=hold_facts.contest_mask,
                net=deps.net, json=json, hud=assert(deps.hud, "explicit hud required"), io=io_,
                profile=profile, sites=view.sites, area_map=data.area_map,
                player=assert(deps.player, "explicit player required"), rom_type=def.rom_type,
                rom_sha1=executed_sha, log=deps.log,
                evolutions=data.evolutions.evolutions, -- force_faint's evolved-identity fallback
                hello_session=load("lua/hello_session.lua"), reply_dispatch=load("lua/reply_dispatch.lua"),
                owed_reports=load("lua/owed_reports.lua"),
            })
        end
        assert(io_.domain_size("ROM") == size and Admission.sha1(read_rom, size) == executed_sha
               and io_.domain_size("ROM") == size, "candidate ROM changed during composition")
        return {pack=def.pack, title=title, profile=profile, data=data, reads=reads, writes=writes,
                rom=rom, client=client, checkpoint=checkpoint, production_admitted=production,
                artifact_kind=production and decision.kind or deps.artifact_kind or "clean", runtime_rom_sha1=executed_sha,
                view=view,
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
local HEADERS = {PM_CRYSTAL="crystal", POKEMON_GLD="gold", POKEMON_SLV="silver", PKPCRYSTAL="polished"}
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

-- C-PACK + C-COMPOSE (docs/polished/CLIENT.md): the Polished overlay's client, under the DEV-GRADE authority of
-- Entry.admit_polished (overlay sha1 only). Its pack is profile + charmap + evolutions (P.load pins the first two to
-- one source), never the vanilla 15-file pack, admission matrix or receipts. What it composes, and what it does not:
--   reads   lua/gen2/polished.lua P.new; wire = P.wire (DDDDDD:OOOO:SSS:TT keys, 70-byte party blobs)
--   panel   lua/gen2/panel.lua over profile.overlay (the same SLNK mailbox, ABI 3): only for companion_abi, the
--           server's companion evidence; the overlay advertises caps 0, so it never paints or plays a sound
--   signals C-SITES: signals.lua S.new_polished registers ONE hook, capture_party (03:652B, the wild party catch), at
--           DEV_OVERLAY evidence (no receipt: physical_firing OPEN); no other engine site, so no PC/evolution events
--   safety  refuses every write kind, so writes/boxes/phone/trade/checkpoint/battle holds are all absent (nil)
--   pc_boxes the READ-ONLY newbox census (P.census over lua/gen2/polished_boxes.lua, C-BOX): a scan counts only with
--           a real save (sSaveVersion + sChecksum anchors) and all 20 boxes decoded, else pc_boxes stays [] with no
--           generation. NEWBOX 7's WRAM-domain mapping is still unexercised on a Polished save, so an unflagged
--           pointer, a Bad Egg or an all-zero image never reads as a (possibly empty) COMPLETE census. No box write.
--   hello   p.hello_unheld: with no checkpoint PC to hold, the first hello waits only for a live game (party +
--           player readable, not the title screen), not the OWPlayerInput checkpoint
--   areas   data/games/polished_crystal/area_map.json (C-AREA, 605 maps): area_id/loc_name from (group, number); a pair
--           with no row still falls back to area_id "" and map_G_N. It passes the SAME flat-row contract load_pack
--           asserts for the vanilla area_map (source artifact + commit, group*256+number key), inline below
local function compose_polished(deps, decision)
    local ok, result = pcall(function()
        assert(type(decision) == "table" and decision.title == "polished" and decision.kind == "overlay"
               and decision.rehashed == true and decision.qualification == "DEV_OVERLAY_SHA1"
               and decision.foundation == "gen2_polished",
               "Polished composes only its admitted dev overlay decision")
        local root = assert(deps.root, "root required")
        local io_ = assert(deps.io, "explicit IO required")
        assert(io_.model_only ~= true, "the Polished client requires live IO, not model_only")
        assert(type(io_.read_u8) == "function" and type(io_.domain_size) == "function", "explicit ROM IO required")
        local load = function(path) return dofile(root .. "/" .. path) end
        local json, Admission, P = load("lua/json_codec.lua"), load("lua/admission.lua"), load("lua/gen2/polished.lua")
        local profile, charmap, wrapper = P.load(root, json)
        local evolutions = load_json(json, root .. "/" .. Entry.PACK_FILES.polished_crystal.evolutions)
        assert(evolutions.schema == "polished-evolutions-v1" and type(evolutions.source) == "table"
               and evolutions.source.lock_sha256 == wrapper.source.lock_sha256
               and evolutions.source.rom_sha1 == wrapper.source.rom_sha1, "pack source mismatch: evolutions")
        local area_map = load_json(json, root .. "/" .. Entry.PACK_FILES.polished_crystal.area_map)
        local maps = 0
        for id, row in pairs(area_map) do
            assert(type(row) == "table" and type(row.source) == "table"
                   and row.source.artifact == Entry.PACKS.polished.artifact and row.source.commit == wrapper.source.commit
                   and type(row.map_group) == "number" and type(row.map_number) == "number"
                   and tonumber(id) == row.map_group * 256 + row.map_number,
                   "area-map source/identity mismatch")
            maps = maps + 1
        end
        assert(maps > 0, "area-map source rows missing")
        local size = io_.domain_size("ROM")
        assert(size == profile.derived.rom_size, "Polished ROM size mismatch")
        -- the executed bytes are the admitted overlay's, re-hashed through the live IO
        assert(decision.rom_sha1 == profile.overlay.rom_sha1
               and Admission.sha1(function(offset) return io_.read_u8(offset, "ROM") end, size) == decision.rom_sha1,
               "Polished ROM hash mismatch")
        local decode_name = deps.decode_name or load("lua/token_scanner.lua").new({
            glyphs=charmap.glyphs, terminator=charmap.terminator, max_length=profile.derived.name_length,
            unknown=function(byte) return string.format("<$%02X>", byte) end})
        local base = assert(P.new(profile, io_, decode_name))
        local census, census_why = P.census(load("lua/gen2/polished_boxes.lua"), io_, decode_name, deps.log)
        assert(census, census_why)
        local reads = setmetatable({read_current_box_num=census.read_current_box_num,
                                    read_active_box=census.read_active_box,
                                    read_storage_box=census.read_storage_box}, {__index=base})
        local hud = assert(deps.hud, "explicit hud required")
        local Panel = load("lua/gen2/panel.lua")
        -- (F-3) the panel's write path is structurally inert at milestone A (caps 0, no Polished write receipt): a
        -- writes object that REFUSES every write, not Panel.writes over an always-valid permit whose only brake is the
        -- ROM caps byte. A refusal raises (gb_panel's callers surface it: request_sfx errors, service() returns nil, why
        -- which the client logs) and is recorded in .log; nothing reaches io.write_u8.
        local panel_writes = {log={}}
        function panel_writes.arm(_, reason) panel_writes.reason = reason end
        function panel_writes.disarm() panel_writes.reason = nil end
        function panel_writes.write_bytes(_, addr, bytes)
            local why = "Polished panel write refused: no Polished write receipt (" .. tostring(panel_writes.reason) .. ")"
            panel_writes.log[#panel_writes.log + 1] = {addr=addr, n=#bytes, why=why}
            error(why, 0)
        end
        local panel = assert(Panel.new(profile, charmap, io_, panel_writes, hud.sanitize or function(s) return s end))
        -- C-SITES (milestone B): ONE engine site, capture_party (signals.lua S.new_polished), under this DEV-GRADE
        -- admission only. A refused binder (anchor bytes differ, malformed pack) degrades to the inert binder: the
        -- client keeps its hello and party ticks, registers nothing, and says why once in the log.
        local Signals, Registry, GB = load("lua/gen2/signals.lua"), load("lua/hook_registry.lua"),
                                      load("lua/gb_hook_binding.lua")
        local pack = load_json(json, root .. "/data/games/polished_crystal/engine_signals.json")
        local function signals(authority)
            local binder, why = Signals.new_polished({title="polished", qualification=decision.qualification,
                profile=profile, pack=pack, io=io_, reads=reads, key_fn=P.mon_key, areas=area_map,
                authority=authority, Registry=Registry, GB=GB, owner="SLink-gen2-polished", max_pending=64})
            if binder then return binder end
            if deps.log then deps.log("[SLink-gen2] Polished engine sites refused: " .. tostring(why)) end
            return {drain=function() return {} end, status=function() return {} end,
                    boundary=function() end, abandon=function() end, close=function() return true end}
        end
        local client = load("lua/gen2/client.lua").new({
            artifact_kind=decision.kind, foundation=P.FOUNDATION, reads=reads, wire=P.wire, panel=panel,
            safety={check=function(kind) return false, "no Polished write receipt for " .. tostring(kind) end},
            signals=signals, hello_unheld=true,
            net=deps.net, json=json, hud=hud, io=io_, profile=profile, sites={}, area_map=area_map,
            player=assert(deps.player, "explicit player required"), rom_type=P.ROM_TYPE,
            rom_sha1=decision.rom_sha1, log=deps.log, evolutions=evolutions.evolutions,
            hello_session=load("lua/hello_session.lua"), reply_dispatch=load("lua/reply_dispatch.lua"),
            owed_reports=load("lua/owed_reports.lua"),
        })
        return {pack="polished_crystal", title="polished", profile=profile, panel=panel, panel_writes=panel_writes,
                data={profile=wrapper, charmap=charmap, evolutions=evolutions, area_map=area_map}, reads=reads, client=client,
                production_admitted=false, artifact_kind=decision.kind, runtime_rom_sha1=decision.rom_sha1,
                runtime_started=false, qualification="DEV_OVERLAY_SHA1"}
    end)
    if not ok then return nil, tostring(result) end
    return result
end

-- Production: the admitted title's graph (see compose). deps = admit()'s root, rom_size and
-- read_rom_u8, plus live io (not model_only), net, hud, player and log.
function Entry.build(deps)
    if deps.title == "polished" then
        local decision, reason = Entry.admit_polished(deps)
        if not decision then return nil, reason end
        return compose_polished(deps, decision)
    end
    local decision, reason = Entry.admit(deps)
    if not decision then return nil, reason end
    if deps.title ~= nil and deps.title ~= decision.title then
        return nil, "admitted title " .. decision.title .. " differs from the requested " .. tostring(deps.title)
    end
    return compose(deps, decision.title, true, decision)
end

-- DEV-GRADE Polished admission, separate from Entry.admit: the exact overlay sha1 of
-- data/polished/overlay_provenance.json only; the clean release is refused with the companion message.
-- deps = {root, rom_size, read_rom_u8}. The decision, or nil, why.
function Entry.admit_polished(deps)
    local ok, P = pcall(dofile, tostring(deps.root) .. "/lua/gen2/polished.lua")
    if not ok then return nil, tostring(P) end
    return P.admit(deps)
end

-- tools/gen_gen2_admission.py --promote-overlays (D6): does a PROSPECTIVE overlay row (binding_sha256 set) pass its own
-- binding and receipts under the production validators? true, or nil,why. Writes nothing.
function Entry.activation_proof(root, title, row)
    local ok, result, why = pcall(function()
        local json = dofile(root .. "/lua/json_codec.lua")
        local data, _, def = load_pack(root, json, title)
        local view, view_why = view_of(root, json, data, title, row)
        if not view then return nil, view_why end
        local proof, proof_why = proofs(root, json, data, title, def.pack, view)
        if not proof then return nil, proof_why end
        return true
    end)
    if not ok then return nil, tostring(result) end
    return result, why
end

return Entry
