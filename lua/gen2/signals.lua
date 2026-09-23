-- Gen 2 typed guard binder: MODEL probes, and production only through a PHYSICAL receipt. No emulator globals.
-- Shared hook_registry owns registration, callback faults, queues and cleanup;
-- gb_hook_binding owns ROM/bus anchor, PC and bank-shadow validation.
-- Current engine_signals packs are SOURCE_CANDIDATE, never runtime authority by themselves.
-- new(options) registers production hooks ONLY for sites a PHYSICAL engine-site receipt
-- (options.runtime_qualification, schema gen2-engine-site-receipt-v1, written by the live gate
-- lua/tests/gen2_frame_align.lua via tests/live/test_gen2_frame_align.py) proves, for a title from
-- its OWN PHYSICAL receipt (PHYSICAL_TITLES: each title's receipt title is itself; no Silver-from-Gold
-- shortcut, Silver's capture rows differ). Every other site stays unregistered.
-- Registration is not admission: runtime admission stays with admission.json/entry.lua (O-22, U3).
-- new_model(options) requires explicit MODEL_PROBE authority and model_only IO.
-- Options: title, profile/pack wrappers, Registry, GB, io, reads (gen2/reads),
-- authority={kind,allow_model_registration,capture,valid}, owner,max_pending,
-- areas (generated area_map), encounters (generated encounter_tables),
-- statics (generated static_encounters).
-- Authority.capture returns {generation,operation}; valid checks the same held
-- observation. Operation ids must distinguish native attempts. boundary() is
-- mandatory on failure/cancel/reset/reload/source change. The model API does not
-- manufacture these missing engine witnesses or claim a physical receipt.
--
-- A boundary retires latches, never queued events: everything finalized before it is
-- delivered by the next drain() in engine order. The one drop is a latch-creating
-- observation (SETTLED kinds) whose stamp is not the current held one; it is counted in
-- status().drops with its reason. A refusal (need()) is a value: no event, the reason in
-- status().refusals, open latches retired, later signals keep flowing. assert/error in
-- the capture path is reserved for invariant breaks (corrupt site metadata, broken io,
-- impossible latch state) and still stops the shared registry.
local S = {}

local function integer(value, low, high)
    return type(value) == "number" and value == math.floor(value) and value >= low and value <= high
end
local function callable(value) return type(value) == "function" or type(value) == "userdata" end
local function need(ok, why)
    if not ok then error({refusal=why}, 0) end
    return ok
end
local function copy(value)
    if type(value) ~= "table" then return value end
    assert(getmetatable(value) == nil, "plain Gen 2 fact/snapshot table required")
    local result = {}
    for key, item in pairs(value) do result[key] = copy(item) end
    return result
end
local function same_source(left, right)
    for _, key in ipairs({"artifact","repo","commit","rom_sha1","sym_sha256","map_sha256",
                           "lock_sha256","build_provenance_sha256"}) do
        assert(type(left[key]) == "string" and left[key] == right[key], "Gen 2 source mismatch: " .. key)
    end
end
local function key(mon)
    need(type(mon) == "table" and integer(mon.species_id,1,251) and integer(mon.ot_id,0,65535)
         and integer(mon.dv_word,0,65535), "complete decoded Gen 2 identity required")
    return string.format("%04X:%04X:%02X",mon.dv_word,mon.ot_id,mon.species_id)
end
local CPU = {ld=true,ldh=true,call=true,ret=true,jp=true,jr=true,push=true,pop=true,
    inc=true,dec=true,add=true,sub=true,adc=true,sbc=true,["and"]=true,["or"]=true,xor=true,
    cp=true,di=true,ei=true,rst=true,scf=true,ccf=true,nop=true,bit=true,res=true,set=true,
    farcall=true,callfar=true,predef=true,lb=true}
local BOUNDARIES = {failure=true,cancel=true,reset=true,reload=true,source_change=true}
local RESET_SITES = {soft_reset="reset",new_game="reset",continue_confirmed="reload",battle_end="failure"}
local STARTS = {
    capture_party={collection="party",selector="last"},
    capture_box={collection="box",selector="first"},
    hatch_species={collection="party",selector="current"},
    contest_box_inserted={collection="box",selector="first"},
    pc_deposit_begin={collection="party",selector="current",operation="deposit",allow_egg=true},
    pc_withdraw_begin={collection="box",selector="current",operation="withdraw",allow_egg=true},
    pc_release_party_begin={collection="party",selector="current",operation="release_party",allow_egg=true},
    pc_release_box_begin={collection="box",selector="current",operation="release_box",allow_egg=true},
    npc_trade_begin={collection="party",selector="current",operation="npc_trade"},
}
local FINALS = {
    capture_party_finalized={prior="capture_party",acquisition="wild"},
    capture_box_finalized={prior="capture_box",acquisition="wild"},
    hatch_finalized={prior="hatch_species",acquisition="egg_hatch"},
    contest_box_finalized={prior="contest_box_inserted",acquisition="contest"},
}
local OPERATIONS = {pc_deposit_complete="pc_deposit_begin",pc_withdraw_complete="pc_withdraw_begin",
    pc_release_party_complete="pc_release_party_begin",pc_release_box_complete="pc_release_box_begin",
    npc_trade_finalized="npc_trade_begin",change_box_loaded="change_box_begin"}
-- Events that only mean something once a later read settles them: stale ones are dropped.
local SETTLED = {observation=true,faint=true}
-- wBattleType values a scripted static can hold at its catch: NORMAL, FORCESHINY, TRAP,
-- FORCEITEM, CELEBI, SUICUNE (the generated pack resolves each row's own).
local STATIC_TYPES = {[0]=true,[7]=true,[9]=true,[10]=true,[11]=true,[12]=true}
local FAINTS = {battle_faint={cause="battle",slot="wCurBattleMon"},poison_faint={cause="poison",slot="wCurPartyMon"}}
-- Operation starts whose routine has a native failure/cancel branch between start and
-- completion (DepositPokemon .BoxFull, TryWithdrawPokemon .PartyFull, ChangeBoxSaveGame
-- .refused): a new start of the same kind supersedes the unconsumed one (counted in drops).
local SUPERSEDES = {change_box_begin=true}
for name,rule in pairs(STARTS) do if rule.operation then SUPERSEDES[name] = true end end
-- BizHawk 2.11.1 Gambatte emu.getregister has PC/SP/A..L (plus the bank names) and no pairs
-- (docs/purergb/PLAN.md A15): a pair is always composed from its halves, never requested (Gen 1
-- reads HL alike).
local PAIRS = {AF={"A","F"},BC={"B","C"},DE={"D","E"},HL={"H","L"}}
-- PC and SP are the 16-bit singles; every other single is 8-bit.
local WIDTH = {PC=65535,SP=65535}
local OPEN = {
    gift_static="Qualified scripted-gift/static caller and final destination context is OPEN",
    link_trade="Native transaction/received identity/save witness context is OPEN",
    contest_party_finalized="Contest-buffer to appended party identity correlation is OPEN",
    contest_selected="Provisional contest buffer is not final acquisition",
}

S.RECEIPT_SCHEMA = "gen2-engine-site-receipt-v1"
-- title -> the receipt title that may authorize its engine sites. Every title has its own live
-- receipt path (lua/tests/gen2_frame_align.lua) and is authorized only by its own receipt: Silver's
-- three capture rows sit 2 bytes below Gold's (docs/gen2/reviews/OMP_U1_BATTLE_FACTS_2026-09-23.md O10),
-- unlike the write-window RECEIPT_TITLE (lua/gen2_write_safety.lua) where Silver follows Gold.
S.PHYSICAL_TITLES = {crystal="crystal", gold="gold", silver="silver"}
S.RECEIPT_NEGATIVES = {"wrong_pack_byte","script_bytecode_arm","wrong_bank_hit"}

local COUNT = 9007199254740991
local function hex64(value) return type(value) == "string" and #value == 64 and value:match("^%x+$") ~= nil end

-- The proven site set of a PHYSICAL receipt, or nil,why. Pure: the caller decodes the file.
-- Summary flags are never trusted: alignment, RAM effect and decoy verdicts are recomputed
-- from the receipt's raw measurements. A site is proven only when the receipt names it and
-- recorded a live hit at exactly the bank/PC/bytes the pack pins, and the receipt belongs to
-- this title, ROM, pack and qualified battle fixture (normal buttons, CGB, no harness write).
-- A proven site none of whose ANY-mode predecessors is proven is dropped (it could never
-- publish); an ALL-mode site needs every predecessor proven.
function S.qualified_sites(title, pack, receipt)
    local owner = S.PHYSICAL_TITLES[title]
    if not owner then
        return nil,"Gen 2 runtime signal qualification is OPEN for " .. tostring(title) .. ": no PHYSICAL receipt path"
    end
    if type(receipt) ~= "table" or receipt.schema ~= S.RECEIPT_SCHEMA or receipt.evidence_level ~= "PHYSICAL"
       or receipt.result ~= "PASS" then
        return nil,"PHYSICAL engine-site qualification receipt required"
    end
    local data = type(pack) == "table" and type(pack.titles) == "table" and pack.titles[title]
    if type(data) ~= "table" or type(data.sites) ~= "table" or type(pack.source) ~= "table" or receipt.title ~= owner
       or receipt.rom_sha1 ~= pack.source.rom_sha1 or receipt.pack_commit ~= pack.source.commit
       or type(pack.specs_sha256) ~= "string" or receipt.pack_specs_sha256 ~= pack.specs_sha256 then
        return nil,"qualification receipt belongs to another title, ROM or engine-site pack"
    end
    if receipt.fixture ~= owner .. "_battle" or receipt.core_mode ~= "CGB" or receipt.input_mode ~= "normal_buttons"
       or type(receipt.harness_write_scopes) ~= "table" or next(receipt.harness_write_scopes) ~= nil
       or not hex64(receipt.fixture_sha256) or type(receipt.attempt_id) ~= "string" or receipt.attempt_id == ""
       or type(receipt.qualification_attempt_id) ~= "string" or receipt.qualification_attempt_id == "" then
        return nil,"qualification receipt is not a normal-button CGB run of the qualified battle fixture"
    end
    local a, d = receipt.frame_alignment, receipt.decoy
    if receipt.bank_check ~= "live" or type(a) ~= "table" or a.passed ~= true
       or not integer(a.armed,0,COUNT) or a.callback ~= a.armed
       -- TryAddMonToParty bumps wPartyCount before GeneratePartyMonStats (C move_mon.asm:3-19), frames ahead of
       -- the capture_party site: the baseline is the wild_ready party, the change frame at or before the callback.
       or not integer(a.battle_party,0,5) or a.callback_party ~= a.battle_party+1 or a.post_party ~= a.callback_party
       or not integer(a.party_changed,0,COUNT) or a.party_changed > a.callback
       or not integer(a.aligned_hits,1,COUNT) or a.misaligned_hits ~= 0 then
        return nil,"qualification receipt lacks the live bank check or the frame-alignment measurements"
    end
    if type(d) ~= "table" or not integer(d.raw,1,COUNT) or d.accepted ~= 0 or d.bank_rejects ~= d.raw then
        return nil,"qualification receipt wrong-bank decoy did not fire raw and reject every hit by bank"
    end
    for _,name in ipairs(S.RECEIPT_NEGATIVES) do
        if type(receipt.negatives) ~= "table" or receipt.negatives[name] ~= "refused" then
            return nil,"qualification receipt negative control not refused: " .. name
        end
    end
    if type(receipt.proven) ~= "table" or type(receipt.sites) ~= "table" then
        return nil,"qualification receipt names no proven sites"
    end
    local proven = {}
    for _,name in ipairs(receipt.proven) do
        local site, hit = data.sites[name], receipt.sites[name]
        if type(site) ~= "table" or type(site.guards) ~= "table" or type(hit) ~= "table"
           or not integer(hit.hits,1,COUNT)
           or hit.bank ~= site.bank or hit.addr ~= site.addr or hit.pc ~= site.addr
           or hit.expected_hex ~= site.expected_hex or not integer(hit.first_frame,0,COUNT) then
            return nil,"qualification receipt site differs from the pack or has no live hit: " .. tostring(name)
        end
        proven[name] = true
    end
    local changed = true
    while changed do
        changed = false
        for name in pairs(proven) do
            local prior = data.sites[name].guards.requires_prior
            if type(prior) == "table" then
                local all, found = prior.mode == "ALL", 0
                for _,start in ipairs(type(prior.site_ids) == "table" and prior.site_ids or {}) do
                    if proven[start] then found = found+1 end
                end
                if found == 0 or (all and found ~= #prior.site_ids) then proven[name], changed = nil, true end
            end
        end
    end
    if next(proven) == nil then return nil,"qualification receipt proves no registrable site" end
    return proven
end

-- U3 binding: true when a PHYSICAL engine-site receipt ran on exactly the fixture bytes a
-- passed full-chain fixture qualification report (tests/fixtures/gen2/receipts/<fixture>.qualification.json,
-- decoded by the caller) recorded, from that report's attempt; else nil,why. Pure.
function S.bind_fixture_qualification(receipt, qualification)
    if type(receipt) ~= "table" or type(qualification) ~= "table" then return nil,"receipt and qualification report required" end
    if qualification.schema ~= "fixture-qualification-v1" or qualification.passed ~= true
       or type(qualification.errors) ~= "table" or next(qualification.errors) ~= nil then
        return nil,"fixture qualification report did not pass"
    end
    if type(qualification.attempt_id) ~= "string" or qualification.attempt_id ~= receipt.qualification_attempt_id then
        return nil,"engine-site receipt names another qualification attempt"
    end
    local rows = qualification.fixtures
    local row = type(rows) == "table" and #rows == 1 and rows[1]
    local artifact = type(row) == "table" and type(row.artifacts) == "table" and row.artifacts.fixture
    local provenance = type(row) == "table" and row.provenance
    if type(artifact) ~= "table" or type(provenance) ~= "table" or row.passed ~= true or row.name ~= receipt.fixture
       or provenance.title ~= receipt.title or provenance.rom_sha1 ~= receipt.rom_sha1 then
        return nil,"qualification report has no passed row for the receipt's fixture, title and ROM"
    end
    if not hex64(receipt.fixture_sha256) or artifact.sha256 ~= receipt.fixture_sha256 then
        return nil,"engine-site receipt ran on other fixture bytes than the qualified ones"
    end
    return true
end

local build
function S.new(options)
    if type(options) ~= "table" or options.runtime_qualification == nil then
        return nil,"explicit Gen 2 runtime qualification is required"
    end
    local ok, proven, why = pcall(S.qualified_sites, options.title, options.pack, options.runtime_qualification)
    if not ok then return nil,"malformed Gen 2 qualification input: " .. tostring(proven) end
    if not proven then return nil,why end
    local ok,result,reason,failed = pcall(build,options,proven)
    if not ok then return nil,tostring(result) end
    return result,reason,failed
end

function build(options, proven)
    assert(type(options) == "table", "Gen 2 model options required")
    local io, authority = assert(options.io), assert(options.authority)
    if proven then
        assert(io.model_only ~= true and authority.kind == "PHYSICAL_RUNTIME",
               "PHYSICAL runtime authority and live IO required")
    else
        assert(io.model_only == true and authority.kind == "MODEL_PROBE"
               and authority.allow_model_registration == true, "explicit MODEL probe authority required")
    end
    local evidence = proven and "PHYSICAL" or "MODEL"
    local physical_status = proven and "SITE_FIRING_RECEIPTED" or "OPEN"
    assert(callable(authority.capture) and callable(authority.valid), "held model operation authority required")
    assert(callable(io.bank_valid), "actual mapped bank observations required")
    local profile, pack = copy(options.profile), copy(options.pack)
    local title = options.title
    assert(({crystal=true,gold=true,silver=true})[title], "selected Gen 2 title required")
    assert(profile.schema == "gen2-profile-v1" and pack.schema == "gen2-engine-signals-v1",
           "generated profile and engine-site schemas required")
    for name in pairs(profile.titles) do assert(name == title,"profile title mismatch") end
    for name in pairs(pack.titles) do assert(name == title,"engine-site title mismatch") end
    local p, data = assert(profile.titles[title]), assert(pack.titles[title])
    same_source(profile.source,pack.source)
    assert(p.artifact == pack.source.artifact and p.rom_sha1 == pack.source.rom_sha1,
           "selected profile artifact differs")
    assert(pack.runtime_admission == "NOT_GRANTED" and pack.f3_complete == false,
           "model path requires explicitly unqualified candidate metadata")
    local statics = options.statics
    if statics ~= nil then
        assert(statics.schema == "gen2-static-encounters-v1" and type(statics.encounters) == "table",
               "generated static-encounter pack required")
        same_source(statics.source,pack.source)
    end
    local reads = assert(options.reads,"independent Gen 2 reads binding required")
    assert(callable(reads.read_party) and callable(reads.read_active_box),"party/active-box readers required")
    local Registry, GB = assert(options.Registry), assert(options.GB)
    assert(type(Registry.new) == "function" and type(GB.new) == "function","shared hook factories required")
    local binding = GB.new(io,{bus_domain="System Bus",rom_domain="ROM",bank_domain="System Bus",
        bank_address=assert(p.ram.hROMBank),pc_register="PC",sp_register="SP"})
    local ids, by_id, grouped, descriptors, source_points = {}, {}, {}, {}, {}
    for name in pairs(data.sites) do
        if not proven or proven[name] then ids[#ids+1] = name end
    end
    table.sort(ids)
    assert(#ids > 0,"engine sites unavailable")
    -- Script bytecode is data: an anchor overlapping ANY declared script range is refused by
    -- address, whatever symbol or instructions the site claims.
    -- Point-symbol coordinates are pack-wide generated facts: collected from every site, also
    -- the ones a PHYSICAL receipt leaves unregistered.
    local scripts = {}
    for _,site in pairs(data.sites) do
        assert(type(site.point_symbols) == "table","source point-symbol facts required")
        for symbol,point in pairs(site.point_symbols) do
            assert(integer(point.bank,0,255) and integer(point.addr,0,65535),"invalid source point")
            if p.ram[symbol] ~= nil then assert(p.ram[symbol] == point.addr,"profile/point address mismatch") end
            local bank = p.ram_bank[symbol] or p.sram_bank[symbol]
            if bank ~= nil then assert(bank == point.bank,"profile/point bank mismatch") end
            if source_points[symbol] then
                assert(source_points[symbol].addr == point.addr and source_points[symbol].bank == point.bank,
                       "conflicting generated point-symbol coordinates")
            end
            source_points[symbol] = point
        end
        local script = type(site.guards) == "table" and site.guards.script_context
        if script then
            assert(integer(script.bank,0,255) and integer(script.addr,0,65535) and type(script.expected_hex) == "string",
                   "invalid script-bytecode range")
            scripts[#scripts+1] = {bank=script.bank,lo=script.addr,hi=script.addr+#script.expected_hex//2}
        end
        -- Generated label-to-next-label script spans (the whole script, not just the checked prefix).
        for _,span in ipairs(type(site.guards) == "table" and site.guards.script_spans or {}) do
            assert(integer(span.bank,0,255) and integer(span.addr,0,65535) and integer(span["end"],span.addr+1,65536),
                   "invalid script-bytecode span")
            scripts[#scripts+1] = {bank=span.bank,lo=span.addr,hi=span["end"]}
        end
    end
    for _,name in ipairs(ids) do
        local site = data.sites[name]
        assert(site.kind == "CPU_INSTRUCTION" and site.maturity == "SOURCE_CANDIDATE"
               and site.runtime_enabled == false and site.physical_firing == "OPEN",
               name .. ": CPU source candidate required")
        assert(site.symbol ~= "Script_Whiteout" and site.symbol ~= "OverworldWhiteoutScript",
               "script bytecode cannot be a bus-exec hook")
        assert(type(site.expected_hex) == "string" and integer(site.addr,0,65535), name .. ": anchor required")
        for _,range in ipairs(scripts) do
            assert(site.bank ~= range.bank or site.addr+#site.expected_hex//2 <= range.lo or site.addr >= range.hi,
                   name .. ": script bytecode cannot be a bus-exec hook (anchor overlaps script data)")
        end
        assert(type(site.instructions) == "table" and #site.instructions > 0,"CPU instruction proof required")
        for _,instruction in ipairs(site.instructions) do
            assert(type(instruction) == "string" and CPU[instruction:match("^(%w+)")],
                   "unsupported CPU instruction or script bytecode")
        end
        assert(site.event_role == "OBSERVATION" or site.event_role == "CLASSIFICATION_ONLY", "invalid signal role")
        assert(type(site.signal) == "string" and type(site.phase) == "string" and type(site.guards) == "table",
               "typed site metadata required")
        if site.signal == "evolution_species" then
            assert(type(site.identity_migration) == "table" and type(site.identity_migration.old_species_by_new) == "table",
                   name .. ": generated pre-evolution table required")
        end
        by_id[name] = site
        local group_id = string.format("bank%03d_pc%04X",site.bank,site.addr)
        if not grouped[group_id] then
            grouped[group_id] = {id=group_id,members={}}
            descriptors[#descriptors+1] = grouped[group_id]
        end
        table.insert(grouped[group_id].members,name)
    end
    for _,name in ipairs(ids) do
        local prior = by_id[name].guards.requires_prior
        if prior then
            assert(prior.mode == "ANY" and prior.scope == "current_operation" and prior.consume_once == true
                   and type(prior.site_ids) == "table" and #prior.site_ids > 0,"invalid acquisition latch contract")
            -- ANY mode: every predecessor is a pack site and at least one is registered (a PHYSICAL
            -- receipt may leave the others unregistered; their latches then never open).
            local registered = false
            for _,start in ipairs(prior.site_ids) do
                assert(data.sites[start],"missing acquisition predecessor")
                registered = registered or by_id[start] ~= nil
            end
            assert(registered,"no registered acquisition predecessor")
            local invalidations = {}
            for _,reason in ipairs(prior.invalidate_on or {}) do invalidations[reason] = true end
            for reason in pairs(BOUNDARIES) do assert(invalidations[reason],"missing acquisition invalidation") end
        end
        local final = FINALS[name]
        if final then
            assert(prior and #prior.site_ids == 1 and prior.site_ids[1] == final.prior,
                   "missing source-required successful insertion latch")
            local required = final.acquisition == "wild" and "wBattleType"
                             or final.acquisition == "egg_hatch" and "wCurPartyMon" or "wCurBox"
            assert(type(prior.match_symbols) == "table" and #prior.match_symbols == 1
                   and prior.match_symbols[1] == required,"missing source acquisition-context match")
        end
        if OPERATIONS[name] then
            assert(prior and #prior.site_ids == 1 and prior.site_ids[1] == OPERATIONS[name],
                   "missing source-required operation predecessor")
        end
        local g = by_id[name].guards
        if name == "whiteout_before_heal" then
            assert(g.required == true and g.registers and integer(g.registers.DE,0,65535)
                   and #g.stack_words_equals == 2 and g.stack_words_equals[1].sp_offset == 0
                   and g.stack_words_equals[2].sp_offset == 4 and #g.memory_equals == 2
                   and g.memory_equals[1].symbol == "wScriptBank" and g.memory_equals[2].symbol == "wScriptPos"
                   and g.script_context and g.script_context.symbol == "Script_Whiteout",
                   "complete pre-HealParty CPU caller/script guards required")
        end
        for _,condition in ipairs(g.memory_equals or {}) do
            local source = by_id[name].point_symbols[condition.symbol]
            assert(source and source.addr == condition.addr and source.bank == condition.bank,
                   "guard and source-symbol coordinates disagree")
        end
    end
    local service, current, latches, refusals = nil,nil,{},{}
    local carried, drops, active = {},{},nil
    -- Acquisition starts (a mon already inserted) retired without their final, plus refused
    -- acquisition starts: a client must never read such a battle as a miss (N3-3).
    local refused_acquisitions = 0
    local self = {}
    local function retire(name)
        if latches[name] and STARTS[name] and not STARTS[name].operation then
            refused_acquisitions = refused_acquisitions+1
        end
        latches[name] = nil
    end
    local function retire_all() for name in pairs(latches) do retire(name) end end
    local function clear(reason)
        retire_all()
        self.last_boundary = reason
        -- Finalized batches survive the boundary in engine order (drain delivers them).
        if service then for _,batch in ipairs(service:drain()) do carried[#carried+1] = batch end end
    end
    local function stamp()
        local value = authority.capture()
        assert(type(value) == "table" and (type(value.generation) == "string" or integer(value.generation,0,9007199254740991))
               and type(value.operation) == "string" and value.operation ~= "", "operation identity malformed")
        need(authority.valid(value) == true,"OPEN: held observation unavailable")
        if current and (current.generation ~= value.generation or current.operation ~= value.operation) then clear("operation_changed") end
        current = copy(value)
        return value
    end
    local function point(site,name)
        local source = site.point_symbols[name] or source_points[name]
        if source then return source end
        assert(p.ram[name] ~= nil and p.ram_bank[name] ~= nil,"OPEN: missing source scalar " .. name)
        return {addr=p.ram[name],bank=p.ram_bank[name]}
    end
    local function memory(source,width)
        assert(width == 1 or width == 2,"unsupported guard width")
        need(io.bank_valid(source.bank,source.addr,width) == true,"OPEN: unmapped guard memory")
        local value = 0
        for i=width-1,0,-1 do
            local byte = io.read_u8(source.addr+i,"System Bus")
            assert(integer(byte,0,255),"guard byte unavailable")
            value = value*256+byte
        end
        return value
    end
    local function scalar(site,name) return memory(point(site,name),1) end
    local function register(name)
        local pair = PAIRS[name]
        if pair then return register(pair[1])*256+register(pair[2]) end
        local value = io.register(name)
        need(integer(value,0,WIDTH[name] or 255),"OPEN: CPU register " .. name .. " unavailable")
        return value
    end
    local function guards(name,site,context)
        local g = site.guards
        if next(g) then assert(g.required == true and g.combine == "ALL","required guard conjunction missing") end
        for reg,expected in pairs(g.registers or {}) do
            if register(reg) ~= expected then return false,"register guard refused" end
        end
        for flag,expected in pairs(g.flags or {}) do
            local place = ({Z=128,C=16})[flag]
            assert(place and (expected == 0 or expected == 1),"invalid flag guard")
            if math.floor(register("F")/place)%2 ~= expected then return false,"flag guard refused" end
        end
        for _,condition in ipairs(g.memory_equals or {}) do
            assert(condition.width == 1 or condition.byte_order == "little","unsupported guard endianness")
            if memory(condition,condition.width) ~= condition.value then return false,"memory guard refused" end
        end
        for _,condition in ipairs(g.stack_words_equals or {}) do
            assert(condition.width == 2 and condition.byte_order == "little"
                   and integer(condition.sp_offset,0,32),"invalid source stack guard")
            assert(callable(io.stack_valid),"stack bounds reader required")
            need(io.stack_valid(context.sp,condition.sp_offset+2) == true,"OPEN: bounded mapped stack context unavailable")
            local lo,hi = io.read_u8(context.sp+condition.sp_offset,"System Bus"),io.read_u8(context.sp+condition.sp_offset+1,"System Bus")
            assert(integer(lo,0,255) and integer(hi,0,255),"stack bytes unavailable")
            if lo+hi*256 ~= condition.value then return false,"caller-stack guard refused" end
        end
        local prior = g.requires_prior
        if prior then
            local found
            for _,start in ipairs(prior.site_ids) do
                local held = latches[start]
                if held then
                    if found then return false,"ambiguous prior acquisition" end
                    found = held
                end
            end
            if not found then return false,"required prior success/identity unavailable" end
            for _,symbol in ipairs(prior.match_symbols or {}) do
                if found.fields[symbol] ~= scalar(site,symbol) then
                    return false,"prior scalar context changed",found.site_id
                end
            end
        end
        return true
    end
    local function receiver(rule,site)
        local snapshot,why
        if rule.collection == "party" then snapshot,why = reads.read_party()
        else snapshot,why = reads.read_active_box() end
        need(snapshot, "OPEN: receiver snapshot unavailable: " .. tostring(why))
        need(integer(snapshot.count,1,rule.collection == "party" and 6 or 20),"occupied receiver required")
        local slot = rule.selector == "first" and 0 or rule.selector == "last" and snapshot.count-1
                     or scalar(site,"wCurPartyMon")
        need(integer(slot,0,snapshot.count-1),"receiver slot unavailable")
        local mon = copy(snapshot.mons[slot+1])
        need(mon and (rule.allow_egg or mon.is_egg == false),"final acquisition cannot be an unhatched egg")
        mon.key = key(mon)
        local matches = 0
        for _,other in ipairs(snapshot.mons) do if key(other) == mon.key then matches=matches+1 end end
        need(matches == 1,"ambiguous receiver identity")
        return {mon=mon,count=snapshot.count,slot=slot,box_index=snapshot.box_index,collection=rule.collection}
    end
    local function collections()
        local party,pwhy = reads.read_party()
        local box,bwhy = reads.read_active_box()
        need(party and box,"OPEN: complete party/active-box snapshots required: " .. tostring(pwhy or bwhy))
        return {party=party,box=box}
    end
    local function sequence(before,after,removed,appended)
        local expected = {}
        for i,mon in ipairs(before.mons) do if i-1 ~= removed then expected[#expected+1] = key(mon) end end
        if appended then expected[#expected+1] = appended end
        need(after.count == #expected,"operation count/topology differs")
        for i,value in ipairs(expected) do need(key(after.mons[i]) == value,"operation compaction/identity differs") end
    end
    local function operation_event(name,site)
        local prior = OPERATIONS[name]
        local before = assert(latches[prior],"operation snapshot unavailable")
        if name == "change_box_loaded" then
            local after,why = reads.read_active_box()
            need(after and after.box_index == before.requested,"changed-box destination differs: " .. tostring(why))
            return {kind="box_change",site_id=name,old_box=before.box_index,new_box=after.box_index,
                    active_box=after,persistence="OPEN"}
        end
        local after = collections()
        need(after.box.box_index == before.collections.box.box_index,"current box changed during operation")
        local action = STARTS[prior].operation
        local event = {site_id=name,old_key=before.mon.key,identity_scope="party_and_active_box_only",
                       global_identity_qualification="OPEN"}
        if action == "deposit" then
            sequence(before.collections.party,after.party,before.slot,nil)
            sequence(before.collections.box,after.box,nil,before.mon.key)
            event.kind,event.mon,event.box_index = "party_to_box",copy(after.box.mons[after.box.count]),after.box.box_index
        elseif action == "withdraw" then
            sequence(before.collections.box,after.box,before.slot,nil)
            sequence(before.collections.party,after.party,nil,before.mon.key)
            event.kind,event.mon,event.box_index = "box_to_party",copy(after.party.mons[after.party.count]),after.box.box_index
        elseif action == "release_party" or action == "release_box" then
            local source = action == "release_party" and "party" or "box"
            local other = source == "party" and "box" or "party"
            sequence(before.collections[source],after[source],before.slot,nil)
            sequence(before.collections[other],after[other],nil,nil)
            event.kind,event.collection,event.mon = "pc_release",source,copy(before.mon)
            event.box_index = source == "box" and after.box.box_index or nil
        else
            assert(action == "npc_trade", "unknown operation policy")
            local received = receiver({collection="party",selector="last"},site)
            need(received.mon.key ~= before.mon.key,"NPC trade identity did not change")
            sequence(before.collections.party,after.party,before.slot,received.mon.key)
            sequence(before.collections.box,after.box,nil,nil)
            event.kind,event.new_key,event.mon,event.reason = "key_change",received.mon.key,received.mon,"npc_trade"
        end
        if event.mon then event.mon.key = key(event.mon) end
        return event
    end
    local function area(site)
        local group,number = scalar(site,"wMapGroup"),scalar(site,"wMapNumber")
        local row = options.areas and options.areas[tostring(group*256+number)]
        need(type(row) == "table" and type(row.area_id) == "string" and row.source
             and row.source.artifact == pack.source.artifact and row.source.commit == pack.source.commit,
             "OPEN: source-qualified ordinary area unavailable")
        return row.area_id
    end
    local function final_event(name,site,accepted)
        local rule = FINALS[name]
        local before = assert(latches[rule.prior],"prior acquisition lost")
        local after = receiver(STARTS[rule.prior],site)
        need(after.count == before.count and after.slot == before.slot and after.box_index == before.box_index,
             "receiver topology changed during acquisition")
        if rule.acquisition == "egg_hatch" then
            need(after.mon.dv_word == before.mon.dv_word and after.mon.species_id == before.mon.species_id,
                 "hatch identity changed beyond source OT finalization")
        else need(after.mon.key == before.mon.key,"receiver identity changed during acquisition") end
        local acquisition,zone,classifications = rule.acquisition,nil,{}
        local classifier = after.collection == "party" and "roamer_party_finalized" or "roamer_box_finalized"
        -- Script_loadwildmon writes bit 7 in both pinned scripting.asm handlers; a scripted
        -- static catches through the same PokeBallEffect fork and finalizes here, with
        -- wBattleType/wBattleScriptFlags still live (cleared only by CleanUpBattleRAM/reloadmap).
        local scripted = acquisition == "wild" and math.floor(scalar(site,"wBattleScriptFlags")/128)%2 == 1
        if scripted then
            -- NORMAL battle type alone does not prove ordinary wild origin (many fixed statics
            -- use it): only selected source rows sharing (map, species, runtime type) qualify it.
            local battle_type,group,number = scalar(site,"wBattleType"),scalar(site,"wMapGroup"),scalar(site,"wMapNumber")
            for _,row in ipairs(statics and STATIC_TYPES[battle_type] and statics.encounters or {}) do
                if row.map_group == group and row.map_number == number and row.species == after.mon.species_id
                   and row.runtime_battle_type == battle_type and row.applicability.selected == true then
                    if row.source_unused ~= false or row.kind == "tutorial" or (zone and zone ~= row.area_id) then
                        zone = false
                        break
                    end
                    zone = row.area_id
                end
            end
            need(zone,"OPEN: scripted/static acquisition caller policy unavailable")
            -- Gen 1 canon (O-3, lua/gen1/client.lua static_<map>_<dex>): a static is its own gift
            -- area and never consumes the route's; a legend_<species> row keeps it (O-21).
            if zone ~= "legend_" .. after.mon.species_id then
                zone = string.format("static_%d_%d",group*256+number,after.mon.species_id)
            end
            if after.collection == "box" then
                -- SendMonIntoBox copies wEnemyMonDVs into the new first record; its .full branch
                -- inserts nothing, leaving a pre-existing mon first and the box count unchanged.
                -- ponytail: a DV-word match only (~1/65536 false pass if the stale first mon shares DVs); add the unchanged box count if it must be airtight
                local dvs = memory(point(site,"wEnemyMonDVs"),2)
                need(after.mon.dv_word == dvs%256*256+math.floor(dvs/256),
                     "OPEN: box-full static: the first box record is not the caught battle mon")
            end
            acquisition = "static"
        elseif acquisition == "wild" and accepted[classifier] then
            local encounters = options.encounters
            assert(type(encounters) == "table", "OPEN: roamer species policy unavailable")
            same_source(encounters.source,pack.source)
            local allowed = false
            for _,row in ipairs(encounters.roamers.initial) do if row.species == after.mon.species_id then allowed=true end end
            need(allowed,"OPEN: species is not a selected-title roamer")
            acquisition,zone,classifications = "roamer","legend_" .. after.mon.species_id,{classifier}
        elseif acquisition == "wild" then
            local battle_type = scalar(site,"wBattleType")
            -- Specialized/static catch policy is not inferred from a map or key.
            need(battle_type == 0 or battle_type == 4 or battle_type == 8,
                 "OPEN: specialized/static acquisition policy unavailable")
            zone = area(site)
        elseif acquisition == "egg_hatch" then zone = "gift_daycare"
        elseif acquisition == "contest" then zone = "national_park_contest" end
        return {kind="capture",site_id=name,acquisition=acquisition,area_id=zone,destination=after.collection,
                slot=after.slot,box_index=after.box_index,mon=after.mon,classifications=classifications,
                identity_scope="observed_destination_only",global_identity_qualification="OPEN"}
    end
    -- Same-frame identity of the fainting record: the party struct at the engine's own
    -- index (UpdateFaintedPlayerMon reads wCurBattleMon; DamageMonIfPoisoned indexes
    -- wCurPartyMon). Battle copy-back has not run, but DVs/OT/species never change in battle.
    local function faint_event(name,site)
        local rule = FAINTS[name]
        local party,why = reads.read_party()
        need(party,"OPEN: party snapshot unavailable: " .. tostring(why))
        local slot = scalar(site,rule.slot)
        need(integer(slot,0,party.count-1),"faint slot unavailable")
        local mon = copy(party.mons[slot+1])
        need(mon.is_egg == false,"an egg cannot faint")
        mon.key = key(mon)
        return {kind="faint",site_id=name,cause=rule.cause,slot=slot,mon=mon,phase=site.phase}
    end
    -- evolve.asm .skip_unown: `ld [hl], a` stored the new species (A) at wPartySpecies+slot
    -- after the struct copy; the hook is the following `push hl`. The old species is the
    -- generated unique pre-evolution of A, never wEvolutionOldSpecies (ForgetMove's
    -- wListMovesLineSpacing store aliases it; docs/gen2/gen2_engine_sites.md).
    local function evolution_event(name,site)
        local slot,new = scalar(site,"wCurPartyMon"),register("A")
        need(register("HL") == point(site,"wPartySpecies").addr+slot,"species-list store does not name wCurPartyMon")
        need(scalar(site,"wLinkMode") == 0,"OPEN: link-trade evolution belongs to the link_trade transaction")
        local party,why = reads.read_party()
        need(party,"OPEN: party snapshot unavailable: " .. tostring(why))
        need(integer(slot,0,party.count-1),"evolution slot unavailable")
        local mon = copy(party.mons[slot+1])
        need(mon.is_egg == false and mon.species_id == new,"evolved record does not carry the published species")
        local old = site.identity_migration.old_species_by_new[tostring(new)]
        need(integer(old,1,251),"species has no source pre-evolution")
        mon.key = key(mon)
        local old_key = key({species_id=old,ot_id=mon.ot_id,dv_word=mon.dv_word})
        for i,other in ipairs(party.mons) do
            if i ~= slot+1 then
                local k = key(other)
                need(k ~= mon.key and k ~= old_key,"ambiguous evolution identity")
            end
        end
        return {kind="key_change",site_id=name,reason="evolution",old_key=old_key,new_key=mon.key,mon=mon,
                slot=slot,identity_scope="party_only",global_identity_qualification="OPEN"}
    end
    local function process(prepared)
        -- bank first: a wrong-bank hit (the common one) stamps and allocates nothing. Deferring
        -- the stamp is safe: every accepted hit and drain() stamp before any latch is read.
        -- ponytail: it also lets binding:context's hard byte/PC assert fire BEFORE a held-invalid
        -- refusal; safe only while authority.valid() cannot fail (the client epoch authority,
        -- lua/gen2/client.lua). A physical authority that can report invalid must turn that assert
        -- into a refusal here, or a transient race latches failed for the whole session.
        local context = binding:context(prepared.anchor)
        if not context then return nil end
        local held = stamp()
        assert(io.bank_valid(context.bank,context.pc,#prepared.anchor.expected) == true,
               "OPEN: actual mapped ROM bank unavailable")
        local accepted,events,consume,starts,invalidated = {},{},{},{},{}
        for _,name in ipairs(prepared.members) do
            active = name
            local yes,why,invalid = guards(name,by_id[name],context)
            if yes then accepted[name] = true else refusals[name] = why end
            if invalid then invalidated[invalid] = true end
        end
        for _,name in ipairs(prepared.members) do
            if accepted[name] then
                active = name
                local site = by_id[name]
                if RESET_SITES[name] then clear(RESET_SITES[name]) end
                if STARTS[name] then
                    local before = receiver(STARTS[name],site)
                    before.fields = {}
                    for _,symbol in ipairs({"wBattleType","wCurPartyMon","wCurBox"}) do
                        if site.point_symbols[symbol] then before.fields[symbol] = scalar(site,symbol) end
                    end
                    before.generation,before.operation = held.generation,held.operation
                    before.site_id = name
                    if STARTS[name].operation then
                        before.collections = collections()
                        local matches = 0
                        for _,snapshot in pairs(before.collections) do
                            for _,mon in ipairs(snapshot.mons) do if key(mon) == before.mon.key then matches=matches+1 end end
                        end
                        need(matches == 1,"operation identity ambiguous across party/active box")
                    end
                    starts[name] = before
                elseif name == "change_box_begin" then
                    assert(callable(reads.read_current_box_num),"current-box reader required")
                    local old,why = reads.read_current_box_num()
                    local requested = register("E")
                    need(integer(old,0,13) and integer(requested,0,13),"box-change context unavailable: " .. tostring(why))
                    starts[name] = {site_id=name,box_index=old,requested=requested,fields={},
                                    generation=held.generation,operation=held.operation}
                elseif FAINTS[name] then
                    events[#events+1] = faint_event(name,site)
                elseif site.signal == "evolution_species" then
                    events[#events+1] = evolution_event(name,site)
                elseif FINALS[name] then
                    events[#events+1] = final_event(name,site,accepted)
                    consume[FINALS[name].prior] = true
                elseif OPERATIONS[name] then
                    events[#events+1] = operation_event(name,site)
                    consume[OPERATIONS[name]] = true
                elseif site.event_role == "CLASSIFICATION_ONLY" then
                    -- The matching final consumes one latch and decorates one event.
                elseif name == "whiteout_before_heal" then
                    local party,why = reads.read_party()
                    need(party and party.count > 0,"OPEN: pre-heal party snapshot unavailable: " .. tostring(why))
                    for _,mon in ipairs(party.mons) do
                        need(mon.is_egg or mon.hp == 0,"pre-heal whiteout party still has live HP")
                        mon.key = key(mon)
                    end
                    events[#events+1] = {kind="whiteout",site_id=name,party=party,phase=site.phase}
                elseif OPEN[name] or OPEN[site.signal] then
                    refusals[name] = "OPEN: " .. (OPEN[name] or OPEN[site.signal])
                else
                    -- The refused-acquisition count in engine order (a battle's start/end
                    -- observations bracket its captures; drain order would not).
                    events[#events+1] = {kind="observation",site_id=name,signal=site.signal,phase=site.phase,
                                        semantic_publication="OPEN",refused_acquisitions=refused_acquisitions}
                end
            end
        end
        assert(#events <= 1,"multiple semantic events at one shared CPU site")
        need(authority.valid(held) == true,"held identity changed while sampling")
        local superseded = {}
        for name in pairs(starts) do
            active = name
            if latches[name] and SUPERSEDES[name] then
                superseded[#superseded+1] = name
            else
                need(latches[name] == nil,"duplicate acquisition start in one operation")
            end
            need(not ((name == "capture_party" and latches.capture_box) or (name == "capture_box" and latches.capture_party)),
                 "ambiguous capture destinations in one operation")
        end
        for _,name in ipairs(superseded) do
            local drop = drops[name] or {count=0}
            drop.count,drop.reason = drop.count+1,"superseded: the prior attempt ended on a native failure/cancel branch"
            drops[name] = drop
        end
        for name in pairs(consume) do latches[name] = nil end
        for name in pairs(invalidated) do retire(name) end
        for name,value in pairs(starts) do latches[name] = value end
        if #events == 0 then return nil end
        for _,event in ipairs(events) do
            event.evidence_level,event.physical_status,event.runtime_authorized = evidence,physical_status,proven ~= nil
        end
        return {kind=proven and "gen2_batch" or "gen2_model_batch",events=events,context=context,generation=held.generation,
                operation=held.operation,evidence_level=evidence,physical_status=physical_status,runtime_authorized=proven ~= nil}
    end
    local error_message, failed
    service,error_message,failed = Registry.new({owner=options.owner,max_pending=options.max_pending,sites=descriptors,
        validate=function(group)
            local result = {id=group.id,members=group.members}
            for _,name in ipairs(group.members) do
                local site = by_id[name]
                local checked = binding:validate({id=name,bank=site.bank,address=site.addr,capture_offset=0,
                    rom_offset=site.rom_offset,expected_hex=site.expected_hex})
                if not result.anchor or #checked.expected > #result.anchor.expected then result.anchor = checked end
                local script = site.guards.script_context
                if script then
                    -- Read-only expected-data validation through the shared GB
                    -- checker. This descriptor is NEVER passed to register().
                    binding:validate({id=name .. "_script_data",bank=script.bank,address=script.addr,
                        capture_offset=0,rom_offset=script.bank == 0 and script.addr
                            or script.bank*0x4000+script.addr-0x4000,expected_hex=script.expected_hex})
                end
            end
            return result
        end,
        register=function(prepared,callback,name) return binding:register(prepared.anchor,callback,name) end,
        unregister=function(handle) return binding:unregister(handle) end,
        valid_handle=function(handle) return binding:valid_handle(handle) end,
        capture=function(prepared)
            active = nil
            local ok,value = pcall(process,prepared)
            if ok then return value end
            if type(value) == "table" and type(value.refusal) == "string" then
                refusals[active or prepared.id] = value.refusal
                if active and STARTS[active] and not STARTS[active].operation then
                    refused_acquisitions = refused_acquisitions+1
                end
                -- ponytail: a refusal retires every open latch (fail closed); per-latch
                -- invalidation only if a refusal ever strands an unrelated operation.
                retire_all()
                return nil
            end
            clear("guard_or_identity_failure"); error(value,0)
        end,
    })
    if not service then return nil,error_message,failed end
    function self:drain()
        local ok,held = pcall(stamp)
        if not ok then
            refusals.drain = type(held) == "table" and held.refusal or tostring(held)
            clear("stale_drain")
        end
        local batches = carried
        carried = {}
        for _,batch in ipairs(service:drain()) do batches[#batches+1] = batch end
        local result = {}
        for _,batch in ipairs(batches) do
            local event = batch.events[1]
            if not SETTLED[event.kind] or (ok and batch.generation == held.generation and batch.operation == held.operation) then
                result[#result+1] = batch
            else
                local drop = drops[event.site_id] or {count=0}
                drop.count,drop.reason = drop.count+1,"stale epoch: observed before the current held operation"
                drops[event.site_id] = drop
            end
        end
        return result
    end
    function self:boundary(reason)
        assert(BOUNDARIES[reason],"explicit failure/cancel/reset/reload/source_change boundary required")
        clear(reason)
    end
    -- An abandoned timeline (a savestate load or rewind) is NOT a natural boundary: the engine
    -- never reached it, so nothing observed on the timeline the player left may be delivered --
    -- finalized batches included, unlike clear() -- and every open latch is retired (R4 S2).
    function self:abandon(reason)
        retire_all()
        self.last_boundary = reason
        local count = #carried
        carried = {}
        count = count+#service:drain()
        if count > 0 then
            local drop = drops.abandoned_timeline or {count=0}
            drop.count,drop.reason = drop.count+count,"abandoned timeline: " .. tostring(reason)
            drops.abandoned_timeline = drop
        end
    end
    function self:status()
        local result = service:status()
        result.runtime_authorized,result.physical_status,result.evidence_level = proven ~= nil,physical_status,evidence
        result.registered_sites = copy(ids)
        result.refusals,result.open_obligations,result.drops = copy(refusals),copy(OPEN),copy(drops)
        result.refused_acquisitions = refused_acquisitions
        result.pending_acquisitions = 0
        for _ in pairs(latches) do result.pending_acquisitions = result.pending_acquisitions+1 end
        return result
    end
    function self:close() clear("close"); return service:close() end
    return self
end

function S.new_model(options)
    local ok,result,why,failed = pcall(build,options)
    if not ok then return nil,tostring(result) end
    return result,why,failed
end
return S
