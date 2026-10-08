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
-- statics (generated static_encounters), gifts (generated gifts.json: card U1G qualifies a givepoke caller from it;
-- without it gift_static stays OPEN), artifact_kind ("rand_overlay": static/gift/roamer species are read from the ROM at
-- the pack's own sites, R4; any other value keeps the pack's).
-- view (new, PHYSICAL only; OVERLAY_ADMISSION D5): the selected artifact view {kind, rom_sha1, base_sha1, binding_sha256,
-- sites}. S.qualified_sites/S.bind_fixture_qualification validate every run against its sha1/kind/binding (nil = the
-- clean pack) and an overlay registers its OWN sites, never the clean pack's.
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
-- The vanilla Gen 2 key (wire.mon_key, gen2_codec.key). options.key_fn replaces it per binder (build).
local function vanilla_key(mon)
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
-- gift_begin (GivePoke entry, C engine/pokemon/move_mon.asm:1619) has a native no-room branch (.FailedToGiveMon)
-- that never reaches a final: a later gift_begin supersedes it.
local SUPERSEDES = {change_box_begin=true, gift_begin=true}
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
-- title -> the fixtures a U1 receipt may run on: an explicit allow-list, no wildcard. Each must also carry its
-- own passed qualification report (bind_fixture_qualification). gold_battle_errand is Gold after the Mr. Pokemon
-- errand, ending where gold_battle ends: the only Gold state that reaches a day POISON_STING foe (card
-- gen2-u1e-poison, main's ruling (1)).
S.U1_FIXTURES = {crystal={"crystal_battle","crystal_synth_grass","crystal_synth_kyle","crystal_synth_bill"},
    gold={"gold_battle","gold_battle_errand","gold_synth_grass","gold_synth_kyle","gold_synth_bill"},
    silver={"silver_battle","silver_synth_grass","silver_synth_kyle","silver_synth_bill"}}
-- card U1G (O-33): the allow-listed fixtures built by tools/gen2_synth_fixtures.py. A run on one of them must carry
-- its disclosure and a live RAM-effect record for every mutating site it proves (S.mutating_site, S.qualified_sites).
S.SYNTH_FIXTURES = {}
for _,title in ipairs({"crystal","gold","silver"}) do
    for _,kind in ipairs({"grass","kyle","bill"}) do S.SYNTH_FIXTURES[#S.SYNTH_FIXTURES+1] = title .. "_synth_" .. kind end
end
S.SYNTH_SCHEMA = "gen2-synth-disclosure-v1"
S.RECEIPT_SCHEMA_V2 = "gen2-engine-site-receipt-v2"
-- card U1G: a site mutates the party or a box when its signal is an acquisition/identity/storage transition and its
-- phase is past the change (not a "before_"/"confirmed_before"/buffer-selection observation). In a synthetic run each
-- such proven site needs its own live effect record, on one of these bytes at the pack's own address.
S.MUTATING_SIGNALS = {capture_party=true, capture_box=true, contest_capture=true, roamer_capture=true,
    evolution_species=true, egg_hatch=true, npc_trade=true, gift_static=true, link_trade=true, pc_deposit=true,
    pc_withdraw=true, pc_release=true}
S.EFFECT_SYMBOLS = {wPartyCount=1, wPartySpecies=6, sBoxCount=1}   -- symbol -> the bytes an effect spans, whole
-- Per-site effect contract: the one symbol whose whole span (at the pack's address) proves that site's mutation. A
-- mutating site absent here can never be proven by a synthetic run.
S.EFFECT_CONTRACT = {capture_party="wPartyCount", capture_party_finalized="wPartyCount", capture_box="sBoxCount",
    capture_box_finalized="sBoxCount", contest_box_inserted="sBoxCount", contest_box_finalized="sBoxCount",
    contest_party_finalized="wPartyCount", hatch_species="wPartySpecies", hatch_finalized="wPartySpecies",
    evolution_species_published="wPartySpecies", npc_trade_finalized="wPartySpecies",
    gift_party_finalized="wPartyCount", gift_box_finalized="sBoxCount", link_trade_received="wPartySpecies",
    link_trade_saved="wPartySpecies", pc_deposit_complete="sBoxCount", pc_withdraw_complete="wPartyCount",
    pc_release_box_complete="sBoxCount", pc_release_party_complete="wPartyCount"}
S.SYNTH_BUILDERS = {["tools/gen2_synth_fixtures.py"]=true}
function S.mutating_site(site)
    return type(site) == "table" and S.MUTATING_SIGNALS[site.signal] == true and type(site.phase) == "string"
        and not site.phase:match("^before_") and not site.phase:match("^confirmed_before")
        and not site.phase:match("_selected_before_")
end
local function synthetic(fixture)
    for _,name in ipairs(S.SYNTH_FIXTURES) do if name == fixture then return true end end
    return false
end
local function u1_fixture(owner, fixture)
    for _,name in ipairs(S.U1_FIXTURES[owner] or {}) do if name == fixture then return true end end
    return false
end

local COUNT = 9007199254740991
local function hex64(value) return type(value) == "string" and #value == 64 and value:match("^%x+$") ~= nil end

-- docs/gen2/OVERLAY_ADMISSION.md D5: the EXECUTED artifact a receipt is checked against. view == nil is the clean pack
-- (every pre-overlay caller); otherwise view = {kind, rom_sha1, base_sha1, binding_sha256, sites} (lua/gen2/artifact.lua).
-- Returns the pack whose title row is the executed one (an overlay swaps in view.sites), the executed sha1, kind and
-- binding; or nil,why.
local function executed(title, pack, view)
    local base = type(pack) == "table" and type(pack.source) == "table" and pack.source.rom_sha1
    if view == nil then
        if not base then return nil,"engine-site pack required" end
        return pack, base, "clean", nil
    end
    if type(view) ~= "table" or not base or type(pack.titles) ~= "table" or type(pack.titles[title]) ~= "table"
       or type(view.rom_sha1) ~= "string" or #view.rom_sha1 ~= 40 then
        return nil,"artifact view required"
    end
    if view.kind == "clean" then
        if view.rom_sha1 ~= base or view.binding_sha256 ~= nil then return nil,"clean view is not this pack ROM" end
        return pack, base, "clean", nil
    end
    if view.kind ~= "overlay" or view.rom_sha1 == base or view.base_sha1 ~= base or not hex64(view.binding_sha256)
       or type(view.sites) ~= "table" then
        return nil,"overlay view is not a bound overlay of this pack"
    end
    local titles, row, effective = {}, {}, {}
    for key,value in pairs(pack.titles) do titles[key] = value end
    for key,value in pairs(pack.titles[title]) do row[key] = value end
    row.sites, titles[title] = view.sites, row
    for key,value in pairs(pack) do effective[key] = value end
    effective.titles = titles
    return effective, view.rom_sha1, "overlay", view.binding_sha256
end
-- A receipt (or one of its runs) belongs to the executed kind only when it says so: an overlay names its kind and
-- binding, a clean one names neither.
local function kind_mismatch(item, kind, binding)
    if kind == "overlay" then return item.artifact_kind ~= "overlay" or item.binding_sha256 ~= binding end
    return (item.artifact_kind ~= nil and item.artifact_kind ~= "clean") or item.binding_sha256 ~= nil
end

-- Pure: nil when a synthetic run's disclosure and live effect records hold, else why (card U1G, O-33). The
-- disclosure names the run's own fixture bytes; each effect is a transition sampled in this run: before_hex read at
-- before_frame (at or after the run's arrival, before the armed frame), after_hex read inside the aligned callback,
-- the two different, and the after bytes never the ones the setup wrote at the same addresses (a synthetic value
-- may be the baseline, never the evidence).
local function synth_disclosure(d)
    return type(d) == "table" and d.schema == S.SYNTH_SCHEMA and S.SYNTH_BUILDERS[d.builder] == true
        and hex64(d.base_sha256) and hex64(d.sha256) and type(d.base_fixture) == "string"
        and type(d.fields) == "table" and #d.fields > 0 and type(d.source_facts) == "table" and #d.source_facts > 0
end
-- Pure: nil when a synthetic run's disclosure and live effect records hold, else why (card U1G, O-33). Each effect is
-- a transition sampled in this run on wPartyCount / wPartySpecies[slot] / sBoxCount at the pack's address: before_hex
-- is the probe's arming-time read (arming_frame at or after the run's arrival, before the hit), after_hex is read in
-- the aligned callback, the two differ, and the after bytes never equal the bytes the setup wrote there (a
-- synthetic value may be the baseline, never the evidence). Every mutating site the run proves has its own record.
local function synth_problem(run, proven, sites)
    local d = run.synth
    if not synth_disclosure(d) or d.sha256 ~= run.fixture_sha256 then
        return "synthetic run without its schema-valid disclosure of these fixture bytes"
    end
    if type(run.effects) ~= "table" or not integer(run.arrival_frame,0,COUNT) then
        return "synthetic run without live effect records"
    end
    local points = {}
    for _,site in pairs(sites) do
        for symbol,point in pairs(type(site.point_symbols) == "table" and site.point_symbols or {}) do
            if S.EFFECT_SYMBOLS[symbol] and integer(point.addr,0,65535) then points[symbol] = point.addr end
        end
    end
    local covered = {}
    for _,e in ipairs(run.effects) do
        if not proven[e.site] then return "effect record names a site this run does not prove: " .. tostring(e.site) end
        -- the site's own contract: its symbol, the whole span, at the pack's address
        local symbol = S.EFFECT_CONTRACT[e.site]
        local size = symbol and S.EFFECT_SYMBOLS[symbol]
        if symbol == nil or e.symbol ~= symbol or points[symbol] == nil or e.wram ~= points[symbol] or e.size ~= size then
            return "effect record is not the site's own effect span at the pack's address: " .. tostring(e.site)
        end
        -- read inside one of the site's own hits: never before its first recorded hit (a shared-PC final such as
        -- HatchEggs.next also runs for other mons first, so the transition may come at a later hit)
        local hit = type(run.sites) == "table" and run.sites[e.site]
        if type(hit) ~= "table" or not integer(hit.first_frame,0,COUNT) or not integer(e.callback,hit.first_frame,COUNT) then
            return "effect record precedes the site's first recorded hit: " .. tostring(e.site)
        end
        for _,field in ipairs({"arming_hex","before_hex","after_hex"}) do
            local v = e[field]
            if type(v) ~= "string" or #v ~= 2*size or not v:match("^%x+$") then return "malformed effect record" end
        end
        if not integer(e.hit_frame,0,COUNT) or e.callback ~= e.hit_frame
           or not integer(e.arming_frame,run.arrival_frame,COUNT) or e.arming_frame >= e.hit_frame then
            return "effect record is not sampled live in this run before its aligned callback: " .. tostring(e.site)
        end
        if e.before_hex:lower() ~= e.arming_hex:lower() then
            return "effect before value is not the probe's arming-time read: " .. tostring(e.site)
        end
        if e.before_hex:lower() == e.after_hex:lower() then return "effect record shows no transition: " .. tostring(e.site) end
        for _,f in ipairs(d.fields) do
            if integer(f.wram,0,65535) and integer(f.size,1,4096) and type(f.new_hex) == "string" then
                local lo, hi = math.max(e.wram, f.wram), math.min(e.wram+size, f.wram+f.size)
                if lo < hi and e.after_hex:sub(2*(lo-e.wram)+1, 2*(hi-e.wram)):lower()
                               == f.new_hex:sub(2*(lo-f.wram)+1, 2*(hi-f.wram)):lower() then
                    return "effect evidence equals the synthetic setup bytes: " .. tostring(e.site)
                end
            end
        end
        covered[e.site] = true
    end
    for name in pairs(proven) do
        if S.mutating_site(sites[name]) and not covered[name] then
            return "synthetic run proves " .. name .. " without a live effect"
        end
    end
    return nil
end

-- The proven site set of a PHYSICAL receipt, or nil,why. Pure: the caller decodes the file.
-- Summary flags are never trusted: alignment, RAM effect and decoy verdicts are recomputed
-- from the receipt's raw measurements. A site is proven only when the receipt names it and
-- recorded a live hit at exactly the bank/PC/bytes the pack pins, and the receipt belongs to
-- this title, ROM, pack and qualified battle fixture (normal buttons, CGB, no harness write).
-- A proven site none of whose ANY-mode predecessors is proven is dropped (it could never
-- publish); an ALL-mode site needs every predecessor proven.
-- card U1G: a v2 receipt ({schema v2, title, runs = {v1 run, ...}}) proves the union of its runs. Each run is checked
-- like a v1 receipt, except that the capture RAM-effect alignment is needed on at least one NON-synthetic run (every
-- run still needs its hit alignment), and a run's sites need their predecessors proven in that SAME run: a run that
-- would lose a site to the closure is refused (no causal prerequisite from another run).
local qualified_run
function S.qualified_sites(title, pack, receipt, view)
    local owner = S.PHYSICAL_TITLES[title]
    if not owner then
        return nil,"Gen 2 runtime signal qualification is OPEN for " .. tostring(title) .. ": no PHYSICAL receipt path"
    end
    if type(receipt) ~= "table" or receipt.schema ~= S.RECEIPT_SCHEMA_V2 then
        return qualified_run(title, pack, receipt, nil, view)
    end
    local effective, rom, kind, binding = executed(title, pack, view)
    if not effective then return nil,rom end
    if receipt.title ~= owner or type(receipt.runs) ~= "table" or #receipt.runs == 0 then
        return nil,"v2 receipt belongs to another title or names no runs"
    end
    if kind_mismatch(receipt, kind, binding) then return nil,"v2 receipt belongs to another artifact kind or binding" end
    local union, live_capture = {}, false
    for index,run in ipairs(receipt.runs) do
        local proven, why = qualified_run(title, pack, run, true, view)
        if not proven then return nil,"run " .. index .. ": " .. tostring(why) end
        if type(run) == "table" and not synthetic(run.fixture) and type(run.frame_alignment) == "table"
           and run.frame_alignment.battle_party ~= nil then live_capture = true end
        for name in pairs(proven) do union[name] = true end
    end
    if not live_capture then return nil,"no non-synthetic run carries the capture RAM-effect frame alignment" end
    return union
end

function qualified_run(title, pack, receipt, v2, view)
    local owner = S.PHYSICAL_TITLES[title]
    if type(receipt) ~= "table" or receipt.schema ~= S.RECEIPT_SCHEMA or receipt.evidence_level ~= "PHYSICAL"
       or receipt.result ~= "PASS" then
        return nil,"PHYSICAL engine-site qualification receipt required"
    end
    local effective, rom, kind, binding = executed(title, pack, view)
    if not effective then
        return nil, view == nil and "qualification receipt belongs to another title, ROM or engine-site pack" or rom
    end
    pack = effective
    local data = type(pack) == "table" and type(pack.titles) == "table" and pack.titles[title]
    if type(data) ~= "table" or type(data.sites) ~= "table" or type(pack.source) ~= "table" or receipt.title ~= owner
       or receipt.rom_sha1 ~= rom or kind_mismatch(receipt, kind, binding) or receipt.pack_commit ~= pack.source.commit
       or type(pack.specs_sha256) ~= "string" or receipt.pack_specs_sha256 ~= pack.specs_sha256 then
        return nil,"qualification receipt belongs to another title, ROM or engine-site pack"
    end
    if not v2 and synthetic(receipt.fixture) then
        return nil,"a synthetic fixture is accepted only inside a v2 receipt run"
    end
    if not u1_fixture(owner, receipt.fixture) or receipt.core_mode ~= "CGB" or receipt.input_mode ~= "normal_buttons"
       or type(receipt.harness_write_scopes) ~= "table" or next(receipt.harness_write_scopes) ~= nil
       or not hex64(receipt.fixture_sha256) or type(receipt.attempt_id) ~= "string" or receipt.attempt_id == ""
       or type(receipt.qualification_attempt_id) ~= "string" or receipt.qualification_attempt_id == "" then
        return nil,"qualification receipt is not a normal-button CGB run of an allow-listed qualified U1 fixture"
    end
    local a, d = receipt.frame_alignment, receipt.decoy
    -- v2: a run without the capture effect (no battle_party) still needs its hit alignment
    local capture_effect = not v2 or (type(a) == "table" and a.battle_party ~= nil)
    if receipt.bank_check ~= "live" or type(a) ~= "table" or a.passed ~= true
       or not integer(a.aligned_hits,1,COUNT) or a.misaligned_hits ~= 0 then
        return nil,"qualification receipt lacks the live bank check or the frame-alignment measurements"
    end
    if capture_effect and (not integer(a.armed,0,COUNT) or a.callback ~= a.armed
       -- TryAddMonToParty bumps wPartyCount before GeneratePartyMonStats (C move_mon.asm:3-19), frames ahead of
       -- the capture_party site: the baseline is the wild_ready party, the change frame at or before the callback.
       or not integer(a.battle_party,0,5) or a.callback_party ~= a.battle_party+1 or a.post_party ~= a.callback_party
       or not integer(a.party_changed,0,COUNT) or a.party_changed > a.callback
       or not integer(a.aligned_hits,1,COUNT) or a.misaligned_hits ~= 0) then
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
    local claimed = {}
    for name in pairs(proven) do claimed[name] = true end
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
    if v2 then
        for name in pairs(claimed) do
            if not proven[name] then return nil,"a proven site lacks its prior in the same run: " .. name end
        end
    end
    if next(proven) == nil then return nil,"qualification receipt proves no registrable site" end
    if v2 then
        if synthetic(receipt.fixture) then
            local why = synth_problem(receipt, proven, data.sites)
            if why then return nil,why end
        elseif receipt.synth ~= nil then
            return nil,"a synthetic disclosure on a non-synthetic fixture"
        end
    end
    return proven
end

-- U3 binding: true when a PHYSICAL engine-site receipt ran on exactly the fixture bytes a
-- passed full-chain fixture qualification report (tests/fixtures/gen2/receipts/<fixture>.qualification.json,
-- decoded by the caller) recorded, from that report's attempt; else nil,why. Pure.
-- card U1G: a v2 receipt takes the reports by fixture name; each run binds to its own report, and a synthetic run
-- binds through its disclosure to its base fixture's report (the base bytes the builder started from).
local bind_run
-- A synthetic run binds to its fixture's COMMITTED disclosure (reports[<fixture>], shipped beside the qualification
-- reports): the same bytes, base and changed fields as the run's own copy; then to the base fixture's passed report.
local function same_fields(a, b)
    if type(a) ~= "table" or type(b) ~= "table" or #a ~= #b then return false end
    for i, f in ipairs(a) do
        local g = b[i]
        if type(f) ~= "table" or type(g) ~= "table" then return false end
        for _, k in ipairs({"symbol","offset","wram","cart","size","old_hex","new_hex"}) do
            if f[k] ~= g[k] then return false end
        end
    end
    return true
end
local function bind_synthetic(run, reports)
    local committed, d = reports[run.fixture], run.synth
    if not synth_disclosure(committed) or not synth_disclosure(d) or committed.sha256 ~= run.fixture_sha256
       or d.sha256 ~= committed.sha256 or d.base_sha256 ~= committed.base_sha256
       or d.base_fixture ~= committed.base_fixture or not same_fields(d.fields, committed.fields) then
        return nil,"synthetic run is not the committed disclosure's fixture bytes"
    end
    return bind_run({fixture=committed.base_fixture, title=run.title, rom_sha1=run.rom_sha1,
                     fixture_sha256=committed.base_sha256, qualification_attempt_id=run.qualification_attempt_id},
                    reports[committed.base_fixture])
end
-- D5: every run is bound to the SELECTED view's executed sha1, kind and binding (nil view = clean) before its report.
local function owned(item, view)
    if type(item) ~= "table" then return false end
    if view == nil then return not kind_mismatch(item, "clean", nil) end
    if type(view) ~= "table" or (view.kind ~= "clean" and view.kind ~= "overlay") or item.rom_sha1 ~= view.rom_sha1 then
        return false
    end
    return not kind_mismatch(item, view.kind, view.kind == "overlay" and view.binding_sha256 or nil)
end
function S.bind_fixture_qualification(receipt, qualification, view)
    if type(receipt) ~= "table" or receipt.schema ~= S.RECEIPT_SCHEMA_V2 then
        if receipt ~= nil and not owned(receipt, view) then
            return nil,"engine-site receipt belongs to another ROM or artifact kind"
        end
        return bind_run(receipt, qualification)
    end
    if type(receipt.runs) ~= "table" or #receipt.runs == 0 or type(qualification) ~= "table" then
        return nil,"v2 receipt and its qualification reports required"
    end
    for index,run in ipairs(receipt.runs) do
        local ok, why
        if not owned(run, view) then return nil,"run " .. index .. ": belongs to another ROM or artifact kind" end
        if type(run) == "table" and synthetic(run.fixture) then
            ok, why = bind_synthetic(run, qualification)
        else
            ok, why = bind_run(run, type(run) == "table" and qualification[run.fixture])
        end
        if not ok then return nil,"run " .. index .. ": " .. tostring(why) end
    end
    return true
end

function bind_run(receipt, qualification)
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
    local ok, proven, why = pcall(S.qualified_sites, options.title, options.pack, options.runtime_qualification,
                                  options.view)
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
    -- the dev Polished title binds only with its own injected key builder (polished.lua P.mon_key): a vanilla
    -- DDDD:OOOO:SS key over a 3-DV-byte, 9-bit-species record would be a silent identity bug
    assert(({crystal=true,gold=true,silver=true})[title] or (title == "polished" and options.key_fn ~= nil),
           "selected Gen 2 title required")
    assert(profile.schema == "gen2-profile-v1" and pack.schema == "gen2-engine-signals-v1",
           "generated profile and engine-site schemas required")
    for name in pairs(profile.titles) do assert(name == title,"profile title mismatch") end
    for name in pairs(pack.titles) do assert(name == title,"engine-site title mismatch") end
    local p, data = assert(profile.titles[title]), assert(pack.titles[title])
    -- D5: an overlay executes its own sites (qualified_sites already proved them against the receipts)
    if proven and options.view ~= nil and options.view.kind == "overlay" then data.sites = copy(options.view.sites) end
    same_source(profile.source,pack.source)
    -- title facts from the profile (vanilla: 14 boxes; NORMAL 0, FISH 4, TREE 8 resolve an area)
    local num_boxes = p.constants.NUM_BOXES
    assert(integer(num_boxes,1,255),"profile NUM_BOXES required")
    local area_types = {}
    for _,t in ipairs(type(p.derived) == "table" and p.derived.area_battle_types or {0,4,8}) do area_types[t] = true end
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
    local gifts = options.gifts
    if gifts ~= nil then
        assert(gifts.schema == "gen2-gifts-v1" and type(gifts.gifts) == "table", "generated gifts pack required")
        same_source(gifts.source,pack.source)
    end
    -- R4 (docs/gen2/RANDOMIZER.md): a randomized companion cartridge (rand_overlay) keeps every site -- the map, the
    -- anchored script command, the InitRoamMons slot -- while UPR rewrote the species/level/item bytes AT that site.
    -- Those are read from the executed ROM instead of the vanilla pack; the site stays the invariant, so a static or
    -- gift elsewhere is still refused. Clean and overlay carts never take this path: their bytes ARE the pack's.
    local randomized = options.artifact_kind == "rand_overlay"
    -- The anchored command as the ROM holds it, or nil unless its opcode and every byte past the `varying` argument
    -- bytes equal the pack's (a moved or rewritten command never qualifies).
    local function rom_command(anchor, varying)
        if type(anchor) ~= "table" or not integer(anchor.flat,0,COUNT) or type(anchor.expected_hex) ~= "string"
           or #anchor.expected_hex < 2*(varying+1) then return nil end
        local bytes = {}
        for i=0,#anchor.expected_hex//2-1 do
            local byte = io.read_u8(anchor.flat+i,"ROM")
            if not integer(byte,0,255) then return nil end
            if (i == 0 or i > varying) and byte ~= tonumber(anchor.expected_hex:sub(2*i+1,2*i+2),16) then return nil end
            bytes[i] = byte
        end
        return bytes
    end
    if randomized then
        -- loadwildmon species, level / givepoke species, level, item (C/G macros/scripts/events.asm); a row whose
        -- command does not hold is unselected here (fail closed for that site only)
        local function from_rom(rows, varying, fields)
            for _,row in ipairs(rows) do
                local command = rom_command(row.rom, varying)
                if command then
                    for i,field in ipairs(fields) do row[field] = command[i] end
                else row.applicability = {selected=false} end
            end
        end
        if statics then
            statics = copy(statics)
            from_rom(statics.encounters, 2, {"species","level"})
        end
        if gifts then
            gifts = copy(gifts)
            local givepoke = {}
            for _,row in ipairs(gifts.gifts) do if row.operation == "givepoke" then givepoke[#givepoke+1] = row end end
            from_rom(givepoke, 3, {"species","level","item"})
        end
    end
    -- Roamer slot index's species: the pack's, or on a randomized cart the `ld a, <species>` immediate InitRoamMons
    -- stores into wRoamMon<index>Species (C wildmons.asm:493-524, G:488-529; 3E xx EA lo hi per slot); nil if the
    -- instruction is not that store.
    local function roamer_species(index, row)
        if not randomized then return row.species end
        -- the executed artifact's ROM coordinates (an overlay may relocate them), else the clean profile's
        local coords = options.rom_coords or p.rom
        local init = type(coords) == "table" and coords.InitRoamMons
        local store = p.ram["wRoamMon" .. index .. "Species"]
        if type(init) ~= "table" or not integer(init.flat,0,COUNT) or not integer(store,0,65535) then return nil end
        local base = init.flat + 5*(index-1)
        local function at(i) return io.read_u8(base+i,"ROM") end
        if at(0) ~= 0x3E or at(2) ~= 0xEA or at(3) ~= store%256 or at(4) ~= store//256 then return nil end
        return at(1)
    end
    local reads = assert(options.reads,"independent Gen 2 reads binding required")
    -- options.key_fn (e.g. polished.lua P.mon_key): mon -> key | nil, why. It owns its own field and species
    -- bounds; the vanilla 1..251 bound applies only to the default builder.
    local key, max_species = vanilla_key, 251
    if options.key_fn ~= nil then
        local key_fn = options.key_fn
        assert(callable(key_fn), "key_fn must be callable")
        max_species = 0x1FF -- ponytail: the widest injected key's species field (polished_codec.key, 9-bit)
        key = function(mon)
            local k, why = key_fn(mon)
            need(type(k) == "string", "complete decoded Gen 2 identity required: " .. tostring(why))
            return k
        end
    end
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
                    if row.source_unused ~= false or row.kind == "tutorial"
                       or type(row.static_area_id) ~= "string" or (zone and zone ~= row.static_area_id) then
                        zone = false
                        break
                    end
                    zone = row.static_area_id
                end
            end
            need(zone,"OPEN: scripted/static acquisition caller policy unavailable")
            -- Gen 1 canon (O-3, lua/gen1/client.lua static_<map>_<dex>), pack-owned since
            -- gen2-static-canon: the row names its own area -- keyed by the lowercase MAP
            -- CONSTANT, not group*256+number -- so the same static in Crystal, Gold and Silver
            -- is ONE gift area and a cross-title pair links there (O-16). A legend_<species>
            -- row carries that namespace in the same column, and a static never consumes
            -- the route's ordinary area (O-21).
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
            -- the zone is the slot's pack species (legend_<species>): on a randomized cart the caught species is
            -- whatever UPR stored in that slot, the area stays the slot's own
            local slot
            for index,row in ipairs(encounters.roamers.initial) do
                if roamer_species(index,row) == after.mon.species_id then
                    need(slot == nil or slot == row.species,"OPEN: species matches two roamer slots")
                    slot = row.species
                end
            end
            need(slot,"OPEN: species is not a selected-title roamer")
            acquisition,zone,classifications = "roamer","legend_" .. slot,{classifier}
        elseif acquisition == "wild" then
            local battle_type = scalar(site,"wBattleType")
            -- Specialized/static catch policy is not inferred from a map or key.
            need(area_types[battle_type] == true,
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
        need(integer(old,1,max_species),"species has no source pre-evolution")
        mon.key = key(mon)
        local prior = copy(mon)   -- the same record under its pre-evolution species: every other key field kept
        prior.species_id = old
        local old_key = key(prior)
        for i,other in ipairs(party.mons) do
            if i ~= slot+1 then
                local k = key(other)
                need(k ~= mon.key and k ~= old_key,"ambiguous evolution identity")
            end
        end
        return {kind="key_change",site_id=name,reason="evolution",old_key=old_key,new_key=mon.key,mon=mon,
                slot=slot,identity_scope="party_only",global_identity_qualification="OPEN"}
    end
    -- card U1G: gift_begin is GivePoke's entry, reached from Script_givepoke once it has read the command's argument
    -- bytes (C engine/overworld/scripting.asm:1922-1945). A gifts.json row's rom anchor IS its givepoke command
    -- (expected_hex = $2d species level item trainer, macros/scripts/events.asm givepoke), so wScriptBank:wScriptPos
    -- must sit exactly one command past it: the caller is that row, of this map, with its exact arguments.
    local function gift_start(name,site,held)
        local group,number,bank = scalar(site,"wMapGroup"),scalar(site,"wMapNumber"),scalar(site,"wScriptBank")
        local pos = memory(point(site,"wScriptPos"),2)
        local row
        for _,r in ipairs(gifts.gifts) do
            local anchor = type(r.rom) == "table" and r.rom
            if r.operation == "givepoke" and type(r.applicability) == "table" and r.applicability.selected == true
               and r.map_group == group and r.map_number == number and anchor and anchor.bank == bank
               and integer(anchor.addr,0,65535) and type(anchor.expected_hex) == "string"
               and anchor.expected_hex:sub(1,2):lower() == "2d" and #anchor.expected_hex == 10
               and pos == anchor.addr + #anchor.expected_hex//2 then
                need(row == nil,"ambiguous givepoke caller")
                row = r
            end
        end
        need(row and type(row.area_id) == "string" and integer(row.species,1,max_species) and integer(row.level,1,100)
             and integer(row.item,0,255), "OPEN: the gift caller is not a qualified givepoke row")
        local party,why = reads.read_party()
        need(party,"OPEN: party snapshot unavailable: " .. tostring(why))
        return {site_id=name,row=row,count=party.count,fields={},generation=held.generation,operation=held.operation}
    end
    -- gift_party_finalized (GivePoke.skip_nickname, B = 0: the party branch): TryAddMonToParty appended the gift and
    -- GivePoke set wCurPartyMon to it (move_mon.asm:1619-1631).
    local function gift_event(name,site)
        local before = assert(latches.gift_begin,"prior gift lost")
        local party,why = reads.read_party()
        need(party,"OPEN: party snapshot unavailable: " .. tostring(why))
        local slot = party.count-1
        need(party.count == before.count+1 and scalar(site,"wCurPartyMon") == slot,"the gift is not the one appended mon")
        local mon = copy(party.mons[slot+1])
        local id = point(site,"wPlayerID")
        local player = memory(id,1)*256 + memory({addr=id.addr+1,bank=id.bank},1)   -- big-endian dw
        need(mon.is_egg == false and mon.species_id == before.row.species and mon.level == before.row.level
             and mon.held_item == before.row.item and mon.ot_id == player,"the appended mon is not the row's gift")
        mon.key = key(mon)
        for i,other in ipairs(party.mons) do
            if i ~= slot+1 then need(key(other) ~= mon.key,"ambiguous gift identity") end
        end
        return {kind="capture",site_id=name,acquisition="gift",area_id=before.row.area_id,gift_id=before.row.id,
                destination="party",slot=slot,mon=mon,classifications={},identity_scope="observed_destination_only",
                global_identity_qualification="OPEN"}
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
                    need(integer(old,0,num_boxes-1) and integer(requested,0,num_boxes-1),
                         "box-change context unavailable: " .. tostring(why))
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
                elseif name == "gift_begin" and gifts then
                    starts[name] = gift_start(name,site,held)
                elseif name == "gift_party_finalized" and gifts then
                    events[#events+1] = gift_event(name,site)
                    consume.gift_begin = true
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

-- C-SITES (docs/polished/CLIENT.md, milestone B): the DEV-GRADE Polished binder, reached only from lua/gen2/entry.lua
-- compose_polished (the admitted overlay sha1, qualification DEV_OVERLAY_SHA1). S.new keeps refusing Polished (no
-- PHYSICAL receipt path) and S.new_model keeps refusing its pack schema; nothing above is shared or changed. This
-- registers exactly ONE site, capture_party = PokeBallEffect+0x18B `rst FarCall SetCaughtData`, the first instruction
-- after the party-record/OT/nickname rst CopyBytes (item_effects.asm: `inc [hl]` on wPartyCount precedes them, so the
-- catch is the LAST party slot). A full party jumps to .SendToPC and a contest catch branches off before the copy, so
-- neither reaches it. No finalized site is registered, so there is no nickname latch: the wild party catch is
-- published AT the site, under the same battle-type/scripted/area rules final_event applies to a vanilla wild catch.
-- Events carry evidence DEV_OVERLAY / physical_status OPEN. What a PHYSICAL receipt proves (qualified_sites: a live
-- hit at the PC and the capture RAM-effect frame alignment, never from synthetic data) stays UNPROVEN: status().unproven.
-- Options: title="polished", qualification="DEV_OVERLAY_SHA1", profile (the Polished title table), pack (the generated
-- polished-engine-signals-v1 wrapper), io (live), reads (polished.lua), key_fn (P.mon_key), areas (area_map),
-- authority {capture, valid}, Registry, GB, owner, max_pending.
S.POLISHED_SITE, S.POLISHED_PHASE = "capture_party", "post_insert_post_nickname_copy"
S.POLISHED_UNPROVEN = {"a live exec hit at the capture_party PC on a running cartridge",
    "the capture RAM-effect frame alignment (signals.lua qualified_sites live_capture: no non-synthetic run)"}
-- POL-BATTLE: the battle sites the composed Polished client may bind, with the phase each carries in the
-- generated pack. new_polished refuses an id that is not listed here, or a pack row whose phase differs, so a
-- re-pinned site cannot be bound under a stale contract. Explode Mode's window is explode_hold (the
-- `call DetermineMoveOrder` in BattleTurn); the Rival Team Swap gate is rival_swap_gate (SendInUserPkmn's
-- enemy branch). battle_faint is an OBSERVATION boundary, not a write: polished_writes.lua has no faint
-- writer, and BATTLE_FLOW 1.3 makes a party-record write at that boundary a write the copy-back erases.
S.POLISHED_BATTLE_SITES = {
    battle_faint = "before_party_copyback",
    battle_faint_copyback_return = "after_party_copyback",
    battle_end = "before_end_processing",
    wild_ready = "after_enemy_load",
    trainer_ready = "trainer_party_build_entry",
    explode_hold = "before_turn_ordering",
    rival_swap_gate = "enemy_party_ptr_selected",
}
function S.new_polished(options)
    local ok,result,why,failed = pcall(function()
        local o = options
        assert(type(o) == "table" and o.title == "polished" and o.qualification == "DEV_OVERLAY_SHA1",
               "the Polished DEV_OVERLAY_SHA1 admission is required")
        local io, authority, reads, profile, pack = assert(o.io), assert(o.authority), assert(o.reads), o.profile, o.pack
        assert(io.model_only ~= true and callable(io.bank_valid), "live IO required")
        assert(callable(authority.capture) and callable(authority.valid), "held operation authority required")
        assert(callable(o.key_fn) and callable(reads.read_party), "Polished key builder and party reader required")
        assert(type(profile) == "table" and profile.title == "polished" and type(profile.ram) == "table"
               and type(profile.ram_bank) == "table" and type(profile.derived) == "table", "generated Polished profile required")
        assert(type(pack) == "table" and pack.schema == "polished-engine-signals-v1" and pack.runtime_admission == "NOT_GRANTED"
               and pack.f3_complete == false and type(pack.source) == "table" and pack.source.rom_sha1 == profile.rom_sha1,
               "generated Polished engine-site pack required")
        local data = type(pack.titles) == "table" and pack.titles.polished_crystal
        local site = type(data) == "table" and type(data.sites) == "table" and data.sites[S.POLISHED_SITE]
        assert(type(site) == "table" and site.status == "RESOLVED" and site.kind == "CPU_INSTRUCTION"
               and site.maturity == "SOURCE_CANDIDATE" and site.runtime_enabled == false and site.physical_firing == "OPEN"
               and site.phase == S.POLISHED_PHASE, "capture_party: the re-pinned CPU source candidate required")
        assert(type(site.expected_hex) == "string" and integer(site.bank,0,255) and integer(site.addr,0,65535),
               "capture_party: anchor required")
        assert(type(site.instructions) == "table" and #site.instructions > 0,"CPU instruction proof required")
        for _,instruction in ipairs(site.instructions) do
            assert(type(instruction) == "string" and CPU[instruction:match("^(%w+)")],
                   "unsupported CPU instruction or script bytecode")
        end
        assert(type(site.point_symbols) == "table","source point-symbol facts required")
        for _,symbol in ipairs({"wBattleType","wBattleScriptFlags","wMapGroup","wMapNumber"}) do
            local point = site.point_symbols[symbol]
            assert(type(point) == "table" and integer(point.bank,0,255) and integer(point.addr,0,65535),
                   "invalid source point " .. symbol)
            if profile.ram[symbol] ~= nil then
                assert(profile.ram[symbol] == point.addr and profile.ram_bank[symbol] == point.bank,
                       "profile/point address mismatch")
            end
        end
        local area_types = {}
        for _,t in ipairs(assert(profile.derived.area_battle_types, "profile area_battle_types required")) do
            area_types[t] = true
        end
        local function key(mon)
            local k, kwhy = o.key_fn(mon)
            need(type(k) == "string", "complete decoded Gen 2 identity required: " .. tostring(kwhy))
            return k
        end
        local function byte(symbol)
            local point = site.point_symbols[symbol]
            need(io.bank_valid(point.bank,point.addr,1) == true,"OPEN: unmapped guard memory")
            local value = io.read_u8(point.addr,"System Bus")
            assert(integer(value,0,255),"guard byte unavailable")
            return value
        end
        local binding = assert(o.GB).new(io,{bus_domain="System Bus",rom_domain="ROM",bank_domain="System Bus",
            bank_address=assert(profile.ram.hROMBank),pc_register="PC",sp_register="SP"})
        local refusals, drops, refused = {}, {}, 0
        -- POL-BATTLE: the battle sites the composed client binds, opted into EXPLICITLY. capture_party stays the
        -- only site registered by default (entry.lua composes without battle_sites and test_polished_sites.py
        -- pins that); a caller that composes lua/gen2/polished_battle.lua names the ids it needs. Every id is
        -- re-validated from the generated pack with capture_party's discipline -- RESOLVED CPU_INSTRUCTION,
        -- SOURCE_CANDIDATE, physical_firing OPEN, runtime_enabled false, phase equal to the pack row, and a PC
        -- PINNED BY BYTE SEQUENCE (find_hex == expected_hex) rather than a hand-typed offset. The hROMBank
        -- guard and the PC/byte re-check at fire time are gb_hook_binding's, unchanged.
        local battle_ids, battle_sites, registered_sites = {}, {}, {}
        registered_sites[1] = {id=S.POLISHED_SITE}
        for _, id in ipairs(o.battle_sites or {}) do
            assert(type(id)=="string" and S.POLISHED_BATTLE_SITES[id] ~= nil,"unknown Polished battle site: "..tostring(id))
            assert(battle_sites[id] == nil,"duplicate Polished battle site: "..id)
            local row = type(data.sites) == "table" and data.sites[id]
            assert(type(row) == "table",id..": absent from the generated Polished engine-site pack")
            assert(row.status == "RESOLVED" and row.kind == "CPU_INSTRUCTION" and row.maturity == "SOURCE_CANDIDATE"
                   and row.runtime_enabled == false and row.physical_firing == "OPEN"
                   and row.phase == S.POLISHED_BATTLE_SITES[id],id..": re-pinned CPU source candidate required")
            assert(type(row.find_hex) == "string" and type(row.expected_hex) == "string"
                   and row.expected_hex == row.find_hex and #row.expected_hex % 2 == 0,
                   id..": the PC must be pinned by byte sequence read out of the ROM")
            assert(integer(row.bank,1,255) and integer(row.addr,0x4000,0x7FFF) and integer(row.rom_offset,0,0x7FFFFF)
                   and integer(row.hex_len,1,32),id..": anchor required")
            if id == "battle_faint_copyback_return" then
                assert(callable(authority.capture_faint), id..": client-owned faint capture authority required")
                assert(row.hex_len == 3 and row.expected_hex == "CDC334"
                       and type(row.instructions) == "table" and #row.instructions == 1
                       and row.instructions[1] == "call UpdateEnemyMonInParty",
                       id..": player-copy return instruction proof required")
                assert(type(row.point_symbols) == "table", id..": source point-symbol facts required")
                for _, symbol in ipairs({"wBattleMode", "wCurBattleMon", "wLinkMode",
                                         "wBattleMonHP", "wBattleMonStatus", "wPlayerSubStatus2"}) do
                    local point = row.point_symbols[symbol]
                    assert(type(point) == "table" and integer(point.bank,0,1)
                           and integer(point.addr,0xC000,0xDFFF)
                           and ((point.addr < 0xD000 and point.bank == 0)
                                or (point.addr >= 0xD000 and point.bank == 1)),
                           id..": invalid source point "..symbol)
                    if profile.ram[symbol] ~= nil then
                        assert(profile.ram[symbol] == point.addr and profile.ram_bank[symbol] == point.bank,
                               id..": profile/point address mismatch "..symbol)
                    end
                end
                -- The profile omits this point; qualify the generated pair against the pinned overlay symbol,
                -- but all callback reads still use the row, never an address fallback.
                local sub = row.point_symbols.wPlayerSubStatus2
                assert(sub.bank == 0 and sub.addr == 0xC4E2, id..": SUBSTATUS2 point differs from pinned symbol")
            end
            battle_ids[#battle_ids+1], battle_sites[id] = id, row
            registered_sites[#registered_sites+1] = {id=id}
        end
        local WINDOWS = {explode_hold="battle_hold",rival_swap_gate="rival_swap"}
        for id in pairs(WINDOWS) do
            if battle_sites[id] ~= nil then
                assert(callable(o.on_write_window),id..": an on_write_window callback is required for a write window")
            end
        end
        local function wram(name, span)
            local addr, bank = profile.ram[name], profile.ram_bank[name]
            need(addr ~= nil and integer(bank,0,255),"OPEN: "..name.." is not in the generated Polished profile")
            need(io.bank_valid(bank,addr,span or 1) == true,"OPEN: unmapped guard memory")
            if span == nil then
                local value = io.read_u8(addr,"System Bus")
                assert(integer(value,0,255),"guard byte unavailable")
                return value
            end
            local low = io.read_u8(addr,"System Bus")
            local high = io.read_u8(addr+1,"System Bus")
            assert(integer(low,0,255) and integer(high,0,255),"guard word unavailable")
            return low + high * 256
        end
        local function batch(events, context, held)
            return {kind="polished_dev_batch",events=events,context=context,generation=held.generation,
                    operation=held.operation,evidence_level="DEV_OVERLAY",physical_status="OPEN",runtime_authorized=false}
        end
        -- The client's one observation seam (lua/gen2/client.lua on_observation) keys on site_id, so every
        -- battle fact rides the same batch shape a vanilla observation uses.
        local function observation(id, row, extra)
            local event = {kind="observation",site_id=id,signal=row.signal,phase=row.phase,
                           refused_acquisitions=refused,evidence_level="DEV_OVERLAY",physical_status="OPEN",
                           runtime_authorized=false}
            for key, value in pairs(extra or {}) do event[key] = value end
            return event
        end
        local function capture_party(prepared, context, held)
            local party, pwhy = reads.read_party()
            need(party,"OPEN: receiver snapshot unavailable: "..tostring(pwhy))
            need(integer(party.count,1,6),"occupied receiver required")
            local slot = party.count-1 -- selector "last"
            local mon = copy(party.mons[slot+1])
            need(mon and mon.is_egg == false,"final acquisition cannot be an unhatched egg")
            mon.key = key(mon)
            for i,other in ipairs(party.mons) do
                if i ~= slot+1 then need(key(other) ~= mon.key,"ambiguous receiver identity") end
            end
            need(math.floor(byte("wBattleScriptFlags")/128)%2 == 0,"OPEN: scripted/static acquisition caller policy unavailable")
            need(area_types[byte("wBattleType")] == true,"OPEN: specialized/static acquisition policy unavailable")
            local row = o.areas and o.areas[tostring(byte("wMapGroup")*256+byte("wMapNumber"))]
            need(type(row) == "table" and type(row.area_id) == "string" and row.area_id ~= "" and type(row.source) == "table"
                 and row.source.artifact == pack.source.artifact and row.source.commit == pack.source.commit,
                 "OPEN: source-qualified ordinary area unavailable")
            local event = {kind="capture",site_id=S.POLISHED_SITE,acquisition="wild",area_id=row.area_id,destination="party",
                slot=slot,mon=mon,classifications={},identity_scope="observed_destination_only",
                global_identity_qualification="OPEN",evidence_level="DEV_OVERLAY",physical_status="OPEN",runtime_authorized=false}
            return batch({event},context,held)
        end
        -- before_party_copyback: the battle struct is authoritative and the party record is stale (BATTLE_FLOW
        -- 1.3), so the fact is read from the battle struct and stamped by the client, never from the party.
        local function faint_boundary(prepared, context, held)
            local mode = wram("wBattleMode")
            need(mode == 1 or mode == 2,"OPEN: not in a battle at the copyback boundary")
            local slot = wram("wCurBattleMon")
            need(slot <= (assert(profile.constants).PARTY_LENGTH - 1),"OPEN: active battle slot out of range")
            return batch({observation(prepared.id,battle_sites[prepared.id],
                                     {battle={slot=slot,hp=wram("wBattleMonHP",2),max_hp=wram("wBattleMonMaxHP",2),
                                              mode=mode,link_mode=wram("wLinkMode")}})},context,held)
        end
        -- This instruction is after the unconditional player copyback CALL, not its entry.
        -- Point reads are bank-checked on both sides; native HP is BIG-endian.
        local function faint_copyback_return(prepared, context, held)
            local row = battle_sites[prepared.id]
            local function point(name, span)
                local p = row.point_symbols[name]
                local n = span or 1
                need(io.bank_valid(p.bank,p.addr,n) == true,"OPEN: unmapped observer memory "..name)
                local first = io.read_u8(p.addr,"System Bus")
                local second = span and io.read_u8(p.addr+1,"System Bus") or nil
                need(io.bank_valid(p.bank,p.addr,n) == true,"OPEN: observer bank changed "..name)
                need(integer(first,0,255) and (not span or integer(second,0,255)),
                     "OPEN: observer byte unavailable "..name)
                return span and first * 256 + second or first
            end
            local b = {mode=point("wBattleMode"), slot=point("wCurBattleMon"),
                       hp=point("wBattleMonHP",2), status=point("wBattleMonStatus"),
                       link_mode=point("wLinkMode"), fainted=math.floor(point("wPlayerSubStatus2")/4)%2 == 1}
            if (b.mode ~= 1 and b.mode ~= 2) or not integer(b.slot,0,5)
               or b.hp ~= 0 or b.status ~= 0 or b.link_mode ~= 0 or not b.fainted then return nil end
            local captured = authority.capture_faint(b,held)
            if captured == nil then return nil end
            need(authority.valid(held) == true,"OPEN: observer epoch changed")
            return batch({observation("battle_faint",row,
                {source_site_id=prepared.id,battle=b,capture=captured})},context,held)
        end
        -- A write window fires on EVERY turn / every send-out. Silence is the normal outcome: the wiring layer
        -- answers nil when nothing is owed, and only a landed write is published.
        local function write_window(prepared, context, held)
            local outcome = o.on_write_window(prepared.id,context)
            if outcome == nil then return nil end
            assert(type(outcome) == "table" and outcome.ok == true and type(outcome.result) == "table",
                   prepared.id..": a write-window outcome must be {ok=true, result={...}}")
            assert(outcome.result.reason == WINDOWS[prepared.id],
                   prepared.id..": a write may only land at its own declared gate")
            return batch({observation(prepared.id,battle_sites[prepared.id],{write=outcome.result})},context,held)
        end
        local wrong_bank_hits = {}
        local function process(prepared)
            if prepared.id == "battle_faint_copyback_return" then
                local bank = io.read_u8(profile.ram.hROMBank,"System Bus")
                need(integer(bank,0,255),"OPEN: observer ROM bank unavailable")
                if bank ~= prepared.anchor.bank then
                    wrong_bank_hits[prepared.id] = (wrong_bank_hits[prepared.id] or 0) + 1
                    return nil -- bounded counters only; never stamp or advance the client's clock
                end
            end
            local context = binding:context(prepared.anchor)
            if not context then return nil end -- another bank mapped at this PC: nothing stamped
            local held = authority.capture()
            assert(type(held) == "table" and type(held.operation) == "string" and held.operation ~= "",
                   "operation identity malformed")
            need(authority.valid(held) == true,"OPEN: held observation unavailable")
            if prepared.id == S.POLISHED_SITE then return capture_party(prepared,context,held) end
            if prepared.id == "battle_faint" then return faint_boundary(prepared,context,held) end
            if prepared.id == "battle_faint_copyback_return" then return faint_copyback_return(prepared,context,held) end
            if WINDOWS[prepared.id] ~= nil then return write_window(prepared,context,held) end
            return batch({observation(prepared.id,battle_sites[prepared.id])},context,held)
        end
        local service, message, fault = assert(o.Registry).new({owner=o.owner,max_pending=o.max_pending,
            sites=registered_sites,
            validate=function(descriptor)
                local row = descriptor.id == S.POLISHED_SITE and site or assert(battle_sites[descriptor.id])
                return {id=descriptor.id,anchor=binding:validate({id=descriptor.id,bank=row.bank,address=row.addr,
                    capture_offset=0,rom_offset=row.rom_offset,expected_hex=row.expected_hex})}
            end,
            register=function(prepared,callback,name) return binding:register(prepared.anchor,callback,name) end,
            unregister=function(handle) return binding:unregister(handle) end,
            valid_handle=function(handle) return binding:valid_handle(handle) end,
            capture=function(prepared)
                local done,value = pcall(process,prepared)
                if done then return value end
                if type(value) == "table" and type(value.refusal) == "string" then
                    refusals[prepared.id] = value.refusal
                    -- only an ACQUISITION refusal counts against the encounter slot; a battle site that
                    -- declines is a writer window that was not open, not a catch the engine lost
                    if prepared.id == S.POLISHED_SITE then refused = refused+1 end
                    return nil
                end
                error(value,0)
            end,
        })
        if not service then return nil,message,fault end
        local self = {}
        function self:drain() return service:drain() end
        -- no latches: a natural boundary retires nothing, queued captures are delivered by the next drain
        function self:boundary(reason)
            assert(BOUNDARIES[reason],"explicit failure/cancel/reset/reload/source_change boundary required")
        end
        -- an abandoned timeline (savestate load/rewind) delivers nothing it observed (as build's abandon)
        function self:abandon(reason)
            local count = #service:drain()
            if count > 0 then
                local drop = drops.abandoned_timeline or {count=0}
                drop.count,drop.reason = drop.count+count,"abandoned timeline: " .. tostring(reason)
                drops.abandoned_timeline = drop
            end
        end
        function self:status()
            local status = service:status()
            status.runtime_authorized,status.physical_status,status.evidence_level = false,"OPEN","DEV_OVERLAY"
            -- the same id list build() publishes, so a consumer reads it one way on either binder
            local registered = {S.POLISHED_SITE}
            for _, id in ipairs(battle_ids) do registered[#registered+1] = id end
            status.registered_sites,status.refusals,status.drops = registered,copy(refusals),copy(drops)
            status.wrong_bank_hits = copy(wrong_bank_hits)
            status.refused_acquisitions,status.pending_acquisitions = refused,0
            status.unproven = copy(S.POLISHED_UNPROVEN)
            return status
        end
        function self:close() return service:close() end
        return self
    end)
    if not ok then return nil,tostring(result) end
    return result,why,failed
end
return S
