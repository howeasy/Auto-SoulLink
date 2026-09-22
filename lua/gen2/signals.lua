-- Gen 2 typed guard/model binder. No emulator globals or production activation.
-- Shared hook_registry owns registration, callback faults, queues and cleanup;
-- gb_hook_binding owns ROM/bus anchor, PC and bank-shadow validation.
-- Current engine_signals packs are SOURCE_CANDIDATE, never runtime authority.
-- new(options) refuses until a separately reviewed physical-qualification rebind.
-- new_model(options) requires explicit MODEL_PROBE authority and model_only IO.
-- Options: title, profile/pack wrappers, Registry, GB, io, reads (gen2/reads),
-- authority={kind,allow_model_registration,capture,valid}, owner,max_pending,
-- areas (generated area_map), encounters (generated encounter_tables).
-- Authority.capture returns {generation,operation}; valid checks the same held
-- observation. Operation ids must distinguish native attempts. boundary() is
-- mandatory on failure/cancel/reset/reload/source change. The model API does not
-- manufacture these missing engine witnesses or claim a physical receipt.
local S = {}

local function integer(value, low, high)
    return type(value) == "number" and value == math.floor(value) and value >= low and value <= high
end
local function callable(value) return type(value) == "function" or type(value) == "userdata" end
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
    assert(type(mon) == "table" and integer(mon.species_id,1,251) and integer(mon.ot_id,0,65535)
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
local OPEN = {
    gift_static="Qualified scripted-gift/static caller and final destination context is OPEN",
    link_trade="Native transaction/received identity/save witness context is OPEN",
    evolution_species="Prior species/identity migration context is OPEN",
    contest_party_finalized="Contest-buffer to appended party identity correlation is OPEN",
    contest_selected="Provisional contest buffer is not final acquisition",
}

function S.new(options)
    if type(options) ~= "table" or options.runtime_qualification == nil then
        return nil,"explicit Gen 2 runtime qualification is required"
    end
    return nil,"Gen 2 runtime signal qualification is OPEN; source candidates cannot register production hooks"
end

local function build(options)
    assert(type(options) == "table", "Gen 2 model options required")
    local io, authority = assert(options.io), assert(options.authority)
    assert(io.model_only == true and authority.kind == "MODEL_PROBE"
           and authority.allow_model_registration == true, "explicit MODEL probe authority required")
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
    local reads = assert(options.reads,"independent Gen 2 reads binding required")
    assert(callable(reads.read_party) and callable(reads.read_active_box),"party/active-box readers required")
    local Registry, GB = assert(options.Registry), assert(options.GB)
    assert(type(Registry.new) == "function" and type(GB.new) == "function","shared hook factories required")
    local binding = GB.new(io,{bus_domain="System Bus",rom_domain="ROM",bank_domain="System Bus",
        bank_address=assert(p.ram.hROMBank),pc_register="PC",sp_register="SP"})
    local ids, by_id, grouped, descriptors, source_points = {}, {}, {}, {}, {}
    for name in pairs(data.sites) do ids[#ids+1] = name end
    table.sort(ids)
    assert(#ids > 0,"engine sites unavailable")
    for _,name in ipairs(ids) do
        local site = data.sites[name]
        assert(site.kind == "CPU_INSTRUCTION" and site.maturity == "SOURCE_CANDIDATE"
               and site.runtime_enabled == false and site.physical_firing == "OPEN",
               name .. ": CPU source candidate required")
        assert(site.symbol ~= "Script_Whiteout" and site.symbol ~= "OverworldWhiteoutScript",
               "script bytecode cannot be a bus-exec hook")
        assert(type(site.instructions) == "table" and #site.instructions > 0,"CPU instruction proof required")
        for _,instruction in ipairs(site.instructions) do
            assert(type(instruction) == "string" and CPU[instruction:match("^(%w+)")],
                   "unsupported CPU instruction or script bytecode")
        end
        assert(site.event_role == "OBSERVATION" or site.event_role == "CLASSIFICATION_ONLY", "invalid signal role")
        assert(type(site.signal) == "string" and type(site.phase) == "string" and type(site.guards) == "table",
               "typed site metadata required")
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
            for _,start in ipairs(prior.site_ids) do assert(by_id[start],"missing acquisition predecessor") end
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
    local self = {}
    local function clear(reason)
        latches = {}
        self.last_boundary = reason
        if service then service:drain() end
    end
    local function stamp()
        local value = authority.capture()
        assert(type(value) == "table" and (type(value.generation) == "string" or integer(value.generation,0,9007199254740991))
               and type(value.operation) == "string" and value.operation ~= "", "OPEN: operation identity unavailable")
        assert(authority.valid(value) == true,"OPEN: held observation unavailable")
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
        assert(io.bank_valid(source.bank,source.addr,width) == true,"OPEN: unmapped guard memory")
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
        local value = io.register(name)
        if value == nil and ({A="AF",F="AF",B="BC",C="BC",D="DE",E="DE",H="HL",L="HL"})[name] then
            local pair = io.register(({A="AF",F="AF",B="BC",C="BC",D="DE",E="DE",H="HL",L="HL"})[name])
            assert(integer(pair,0,65535),"OPEN: CPU register " .. name .. " unavailable")
            value = ({A=true,B=true,D=true,H=true})[name] and math.floor(pair/256) or pair%256
        end
        assert(integer(value,0,#name == 1 and 255 or 65535),"OPEN: CPU register unavailable")
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
            assert(callable(io.stack_valid) and io.stack_valid(context.sp,condition.sp_offset+2) == true,
                   "OPEN: bounded mapped stack context unavailable")
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
        assert(snapshot, "OPEN: receiver snapshot unavailable: " .. tostring(why))
        assert(integer(snapshot.count,1,rule.collection == "party" and 6 or 20),"occupied receiver required")
        local slot = rule.selector == "first" and 0 or rule.selector == "last" and snapshot.count-1
                     or scalar(site,"wCurPartyMon")
        assert(integer(slot,0,snapshot.count-1),"receiver slot unavailable")
        local mon = copy(snapshot.mons[slot+1])
        assert(mon and (rule.allow_egg or mon.is_egg == false),"final acquisition cannot be an unhatched egg")
        mon.key = key(mon)
        local matches = 0
        for _,other in ipairs(snapshot.mons) do if key(other) == mon.key then matches=matches+1 end end
        assert(matches == 1,"ambiguous receiver identity")
        return {mon=mon,count=snapshot.count,slot=slot,box_index=snapshot.box_index,collection=rule.collection}
    end
    local function collections()
        local party,pwhy = reads.read_party()
        local box,bwhy = reads.read_active_box()
        assert(party and box,"OPEN: complete party/active-box snapshots required: " .. tostring(pwhy or bwhy))
        return {party=party,box=box}
    end
    local function sequence(before,after,removed,appended)
        local expected = {}
        for i,mon in ipairs(before.mons) do if i-1 ~= removed then expected[#expected+1] = key(mon) end end
        if appended then expected[#expected+1] = appended end
        assert(after.count == #expected,"operation count/topology differs")
        for i,value in ipairs(expected) do assert(key(after.mons[i]) == value,"operation compaction/identity differs") end
    end
    local function operation_event(name,site)
        local prior = OPERATIONS[name]
        local before = assert(latches[prior],"operation snapshot unavailable")
        if name == "change_box_loaded" then
            local after,why = reads.read_active_box()
            assert(after and after.box_index == before.requested,"changed-box destination differs: " .. tostring(why))
            return {kind="box_change",site_id=name,old_box=before.box_index,new_box=after.box_index,
                    active_box=after,persistence="OPEN"}
        end
        local after = collections()
        assert(after.box.box_index == before.collections.box.box_index,"current box changed during operation")
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
            assert(received.mon.key ~= before.mon.key,"NPC trade identity did not change")
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
        assert(type(row) == "table" and type(row.area_id) == "string" and row.source
               and row.source.artifact == pack.source.artifact and row.source.commit == pack.source.commit,
               "OPEN: source-qualified ordinary area unavailable")
        return row.area_id
    end
    local function final_event(name,site,accepted)
        local rule = FINALS[name]
        local before = assert(latches[rule.prior],"prior acquisition lost")
        local after = receiver(STARTS[rule.prior],site)
        assert(after.count == before.count and after.slot == before.slot and after.box_index == before.box_index,
               "receiver topology changed during acquisition")
        if rule.acquisition == "egg_hatch" then
            assert(after.mon.dv_word == before.mon.dv_word and after.mon.species_id == before.mon.species_id,
                   "hatch identity changed beyond source OT finalization")
        else assert(after.mon.key == before.mon.key,"receiver identity changed during acquisition") end
        local acquisition,zone,classifications = rule.acquisition,nil,{}
        local classifier = after.collection == "party" and "roamer_party_finalized" or "roamer_box_finalized"
        if acquisition == "wild" then
            -- Script_loadwildmon writes bit 7 in both pinned scripting.asm
            -- handlers. NORMAL battle type alone does not prove ordinary wild
            -- origin (many fixed statics use it). No guessed story attribution.
            assert(math.floor(scalar(site,"wBattleScriptFlags")/128)%2 == 0,
                   "OPEN: scripted/static acquisition caller policy unavailable")
        end
        if acquisition == "wild" and accepted[classifier] then
            local encounters = options.encounters
            assert(type(encounters) == "table", "OPEN: roamer species policy unavailable")
            same_source(encounters.source,pack.source)
            local allowed = false
            for _,row in ipairs(encounters.roamers.initial) do if row.species == after.mon.species_id then allowed=true end end
            assert(allowed,"OPEN: species is not a selected-title roamer")
            acquisition,zone,classifications = "roamer","legend_" .. after.mon.species_id,{classifier}
        elseif acquisition == "wild" then
            local battle_type = scalar(site,"wBattleType")
            -- Specialized/static catch policy is not inferred from a map or key.
            assert(battle_type == 0 or battle_type == 4 or battle_type == 8,
                   "OPEN: specialized/static acquisition policy unavailable")
            zone = area(site)
        elseif acquisition == "egg_hatch" then zone = "gift_daycare"
        elseif acquisition == "contest" then zone = "national_park_contest" end
        return {kind="capture",site_id=name,acquisition=acquisition,area_id=zone,destination=after.collection,
                slot=after.slot,box_index=after.box_index,mon=after.mon,classifications=classifications,
                identity_scope="observed_destination_only",global_identity_qualification="OPEN"}
    end
    local function process(prepared)
        local held = stamp()
        local context = binding:context(prepared.anchor)
        if not context then return nil end
        assert(io.bank_valid(context.bank,context.pc,#prepared.anchor.expected) == true,
               "OPEN: actual mapped ROM bank unavailable")
        local accepted,events,consume,starts,invalidated = {},{},{},{},{}
        for _,name in ipairs(prepared.members) do
            local yes,why,invalid = guards(name,by_id[name],context)
            if yes then accepted[name] = true else refusals[name] = why end
            if invalid then invalidated[invalid] = true end
        end
        for _,name in ipairs(prepared.members) do
            if accepted[name] then
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
                        assert(matches == 1,"operation identity ambiguous across party/active box")
                    end
                    starts[name] = before
                elseif name == "change_box_begin" then
                    assert(callable(reads.read_current_box_num),"current-box reader required")
                    local old,why = reads.read_current_box_num()
                    local requested = register("E")
                    assert(integer(old,0,13) and integer(requested,0,13),"box-change context unavailable: " .. tostring(why))
                    starts[name] = {site_id=name,box_index=old,requested=requested,fields={},
                                    generation=held.generation,operation=held.operation}
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
                    assert(party and party.count > 0,"OPEN: pre-heal party snapshot unavailable: " .. tostring(why))
                    for _,mon in ipairs(party.mons) do
                        assert(mon.is_egg or mon.hp == 0,"pre-heal whiteout party still has live HP")
                        mon.key = key(mon)
                    end
                    events[#events+1] = {kind="whiteout",site_id=name,party=party,phase=site.phase}
                elseif OPEN[name] or OPEN[site.signal] then
                    refusals[name] = "OPEN: " .. (OPEN[name] or OPEN[site.signal])
                else
                    events[#events+1] = {kind="observation",site_id=name,signal=site.signal,phase=site.phase,
                                        semantic_publication="OPEN"}
                end
            end
        end
        assert(#events <= 1,"multiple semantic events at one shared CPU site")
        assert(authority.valid(held) == true,"held identity changed while sampling")
        for name in pairs(starts) do
            assert(latches[name] == nil,"duplicate acquisition start in one operation")
            if (name == "capture_party" and latches.capture_box) or (name == "capture_box" and latches.capture_party) then
                error("ambiguous capture destinations in one operation")
            end
        end
        for name in pairs(consume) do latches[name] = nil end
        for name in pairs(invalidated) do latches[name] = nil end
        for name,value in pairs(starts) do latches[name] = value end
        if #events == 0 then return nil end
        for _,event in ipairs(events) do
            event.evidence_level,event.physical_status,event.runtime_authorized = "MODEL","OPEN",false
        end
        return {kind="gen2_model_batch",events=events,context=context,generation=held.generation,
                operation=held.operation,evidence_level="MODEL",physical_status="OPEN",runtime_authorized=false}
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
            local ok,value = pcall(process,prepared)
            if not ok then clear("guard_or_identity_failure"); error(value,0) end
            return value
        end,
    })
    if not service then return nil,error_message,failed end
    function self:drain()
        local ok,held = pcall(stamp)
        if not ok then
            refusals.drain = tostring(held)
            clear("stale_drain")
            return {}
        end
        local result = service:drain()
        local current_events = {}
        for _,batch in ipairs(result) do
            if batch.generation == held.generation and batch.operation == held.operation then current_events[#current_events+1] = batch end
        end
        return current_events
    end
    function self:boundary(reason)
        assert(BOUNDARIES[reason],"explicit failure/cancel/reset/reload/source_change boundary required")
        clear(reason)
    end
    function self:status()
        local result = service:status()
        result.runtime_authorized,result.physical_status,result.evidence_level = false,"OPEN","MODEL"
        result.refusals,result.open_obligations = copy(refusals),copy(OPEN)
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
