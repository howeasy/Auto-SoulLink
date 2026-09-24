--[[
  lua/tests/gen2_u1g_inputs.lua -- card U1G: one engine-site receipt RUN from an O-33 synthetic setup fixture
  (tools/gen2_synth_fixtures.py SYNTH_RECIPES). Called from lua/tests/gen2_frame_align.lua F.main once the fixture has
  arrived through the qualified CONTINUE path; prints one v2 run (RECEIPT) that tests/live/test_gen2_u1g.py merges
  into <title>.engine_sites.json. Only the SETUP is synthetic: every proven site fires from normal buttons.

  Kinds (SLINK_GEN2_U1_FACTS.u1g.kind):
    grass  Route 29 grass, party [Caterpie L6 @342 exp, a 1-cycle egg, 3 fillers], Master Balls, wStepCount $7F.
           Walk: the first step runs DoEggStep and the egg hatches (hatch_species, hatch_finalized; breeding.asm).
           Battle 1: Caterpie TACKLEs until the foe faints, reaches L7 and evolves after the battle
           (evolution_species_published; evolve.asm). Battles 2 and 3: PACK -> MASTER BALL -> USE, NO to the
           nickname: the first catch fills the party (capture_party), the second goes to the box (capture_box,
           capture_box_finalized; item_effects.asm PokeBallEffect .SendToPC).
    kyle   Elm's lab, a lone poisoned Bellsprout at 1 HP, wPoisonStepCount 3: one step faints it and the native
           OverworldWhiteoutScript warps to the synthetic last spawn, VIOLET_CITY. Walk into VioletKylesHouse, talk
           to Kyle (walks up/down), YES, pick the Bellsprout: NPC_TRADE_KYLE (npc_trade_begin, npc_trade_finalized).
    bill   the same whiteout to GOLDENROD_CITY; BillsFamilysHouse, talk to Bill, YES, NO to the nickname:
           givepoke EEVEE, 20 (gift_begin, gift_party_finalized).
  Every nickname prompt ("Give a nickname to", the catch_nickname anchor) takes NO; every other yes/no takes YES.

  Evidence per run (lua/gen2/signals.lua synth_problem): the pinned-hit log, hit alignment, the decoy and the three
  negatives (as every U1 run), plus one live effect record per mutating site: the effect bytes (wPartyCount,
  wPartySpecies, sBoxCount) read when the probe armed and again inside the site's callback. The MODEL production
  decoder rides the same hooks and must emit the kind's events (U.MODEL_EVENTS).
--]]
local U = {}
U.KINDS = {
    grass = {"hatch_species", "hatch_finalized", "evolution_species_published", "capture_box", "capture_box_finalized"},
    kyle = {"npc_trade_begin", "npc_trade_finalized"},
    bill = {"gift_begin", "gift_party_finalized"},
}
-- the model binder's sites per kind (the proven ones plus what their latches need)
U.MODEL_SITES = {
    grass = {"hatch_species", "hatch_finalized", "evolution_species_published", "capture_party",
             "capture_party_finalized", "capture_box", "capture_box_finalized"},
    kyle = {"npc_trade_begin", "npc_trade_finalized"},
    bill = {"gift_begin", "gift_party_finalized"},
}
-- the events the MODEL decoder must emit, exactly: "kind:detail" -> count
U.MODEL_EVENTS = {
    grass = {["capture:egg_hatch:party"]=1, ["capture:wild:party"]=1, ["capture:wild:box"]=1, ["key_change:evolution"]=1},
    kyle = {["key_change:npc_trade"]=1},
    bill = {["capture:gift:party"]=1},
}
U.EFFECT_SYMBOL = {capture_party="wPartyCount", capture_party_finalized="wPartyCount", capture_box="sBoxCount",
    capture_box_finalized="sBoxCount", hatch_species="wPartySpecies", hatch_finalized="wPartySpecies",
    evolution_species_published="wPartySpecies", npc_trade_finalized="wPartySpecies", gift_party_finalized="wPartyCount"}
U.EFFECT_SIZE = {wPartyCount=1, wPartySpecies=6, sBoxCount=1}
U.HOLD = 12
U.BUDGET = {max_frames=120000, max_phase_frames=30000}
U.PKMN_CELL = 2

local fmt = string.format
local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end
local function on(point, map) return point.map_group == map.map_group and point.map_number == map.map_number end
local function hex(bytes) local out = {} for i, b in ipairs(bytes) do out[i] = fmt("%02x", b) end return table.concat(out) end

-- Pure: the event key the model counts.
function U.event_key(e)
    if e.kind == "key_change" then return "key_change:" .. tostring(e.reason) end
    if e.kind == "capture" then return fmt("capture:%s:%s", tostring(e.acquisition), tostring(e.destination)) end
    return tostring(e.kind)
end

-- Pure: nil when the model events are exactly the kind's, else why.
function U.model_problem(kind, events)
    local counts = {}
    for _, e in ipairs(events or {}) do local k = U.event_key(e) counts[k] = (counts[k] or 0) + 1 end
    for k, n in pairs(U.MODEL_EVENTS[kind]) do
        if counts[k] ~= n then return fmt("the model emitted %d %s events, not %d", counts[k] or 0, k, n) end
    end
    for k in pairs(counts) do if not U.MODEL_EVENTS[kind][k] then return "the model emitted an unexpected " .. k end end
    return nil
end

-- Pure: nil when an effect record holds (the validator's rule, restated), else why.
function U.effect_problem(e, arrival)
    if type(e) ~= "table" then return "no effect record" end
    if e.callback ~= e.hit_frame or not integer(e.arming_frame, arrival, e.hit_frame - 1) then
        return e.site .. ": effect not sampled after arrival and before an aligned callback"
    end
    if e.before_hex ~= e.arming_hex or e.before_hex == e.after_hex then return e.site .. ": no live transition" end
    return nil
end

-- Pure point -> buttons, phase. facts = SLINK_GEN2_U1_FACTS.u1g; F = the frame-align gate (walk_direction,
-- TOWARD_BALLS); PI = lua/tests/gen2_poison_inputs.lua (step_toward).
function U.driver(F, PI, facts)
    local kind = facts.kind
    local self = {terminal="done", phase=kind == "grass" and "walk" or "poison", battles=0}
    local held, hold_left, release, waited, here, from = nil, 0, false, 0, nil, nil
    local maps = facts.maps
    local function press(button)
        release, held, hold_left = true, button, U.HOLD - 1
        return {[button]=true}, self.phase
    end
    local function choose(ui, wanted, columns)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local index = type(wanted) == "number" and wanted or nil
        for i, label in ipairs(index == nil and ui.items or {}) do
            if type(label) == "string" and label:upper() == wanted then index = i end
        end
        if not integer(index, 1, #ui.items) then return nil, "required native menu item missing: " .. tostring(wanted) end
        if index == ui.cursor then return press("A") end
        local tx, cx = (index - 1) % columns, (ui.cursor - 1) % columns
        if tx ~= cx then return press(tx > cx and "Right" or "Left") end
        return press(index > ui.cursor and "Down" or "Up")
    end
    local function walk(map, point, goals)
        local button, why = PI.step_toward(map, point, goals)
        if not button then button = PI.step_toward(map, {x=point.x, y=point.y, can_step=point.can_step}, goals) end
        if not button then
            if waited < 600 then waited = waited + 1 return {}, self.phase end
            return nil, why
        end
        waited = 0
        if button == "arrived" then return nil, "arrived" end
        return {[button]=true}, self.phase
    end
    local function party(point) return type(point.party) == "table" and point.party or {count=0, species={}} end
    local function done(point)
        local p = party(point)
        if kind == "grass" then
            for i = 1, p.count do if p.species[i] == facts.egg then return false end end
            return p.species[1] == facts.evolved and p.count == 6 and integer(point.box_count, facts.box_base + 1, 20)
        elseif kind == "kyle" then return p.species[1] == facts.received
        else return p.count == 2 and p.species[2] == facts.received end
    end
    local function battle(point, ui)
        if ui.kind == "battle_menu" then
            if point.battle_mode ~= 1 then return nil, "battle menu outside a wild battle" end
            if party(point).species[1] == facts.lead then return choose(ui, "FIGHT", 2) end
            return choose(ui, "PACK", 2)
        end
        if ui.kind == "move_menu" then
            if type(ui.items) ~= "table" then return nil, "move list unreadable" end
            for _, label in ipairs(ui.items) do
                if type(label) == "string" and label:upper() == "TACKLE" then return choose(ui, "TACKLE", 1) end
            end
            return press("B")
        end
        if F.TOWARD_BALLS[ui.kind] then return press(F.TOWARD_BALLS[ui.kind]) end
        if ui.kind == "pack_balls" then
            if point.ball_cursor == "ball" then return press("A") end
            if point.ball_cursor == "cancel" then return press("Up") end
            return {}, self.phase
        end
        if ui.kind == "item_submenu" then return choose(ui, "USE", 1) end
        if ui.kind == "yes_no" then return choose(ui, ui.prompt == "catch_nickname" and "NO" or "YES", 1) end
        if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
        return nil, "UI is not valid in battle: " .. tostring(ui.kind)
    end
    function self.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, self.phase end
        if release then release = false; return {}, self.phase end
        if self.phase == self.terminal then return {}, self.phase end
        local ui = point.ui
        if integer(point.battle_mode, 1, 255) then
            if kind ~= "grass" then return nil, "a battle started on a " .. kind .. " leg" end
            if ui == nil or point.input_ready ~= true then return {}, self.phase end   -- evolution animation: no input
            return battle(point, ui)
        end
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "yes_no" then
                -- GiveANickname_YesNo after a givepoke reads "Give a nickname to the <MON> you received?", whose
                -- wrapped rows the catch anchor can miss (live Crystal bill run 2): once the gift is in, answer NO
                local received = kind == "bill" and party(point).count >= 2
                return choose(ui, (ui.prompt == "catch_nickname" or received) and "NO" or "YES", 1)
            end
            if ui.kind == "battle_party" then   -- PartyMenuSelect: the trade's mon choice
                if not integer(point.party_cursor, 0, 5) then return {}, self.phase end
                if point.party_cursor == facts.give_slot then return press("A") end
                return press(point.party_cursor < facts.give_slot and "Down" or "Up")
            end
            if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
            return nil, "UI is not valid in phase " .. self.phase .. ": " .. tostring(ui.kind)
        end
        if point.overworld_ready ~= true then return {}, self.phase end
        if done(point) then self.phase = self.terminal return {}, self.phase end
        if kind == "grass" then
            local map = maps[facts.map]
            if not on(point, map) then return nil, "left the grass map" end
            if map.grid[point.y * map.width + point.x + 1] ~= 2 then
                local grass = {}
                for y = 0, map.height - 1 do
                    for x = 0, map.width - 1 do
                        if map.grid[y * map.width + x + 1] == 2 then grass[#grass + 1] = {x=x, y=y} end
                    end
                end
                local buttons, why = walk(map, point, grass)
                if why ~= "arrived" then return buttons, why end
            end
            self.phase = "walk"
            if here and (here.x ~= point.x or here.y ~= point.y) then from = here end
            here = {x=point.x, y=point.y}
            local button, why = F.walk_direction(map, point, from)
            if not button then return nil, why end
            return {[button]=true}, self.phase
        end
        -- kyle / bill
        local start, city, house = maps[facts.start], maps[facts.city], maps[facts.house]
        if on(point, start) then
            self.phase = "poison"   -- any one step: DoPoisonStep faints the lone mon, the whiteout warps away
            -- a step onto a free tile (live run 1: Up was Elm, the collision byte passes but the object blocks)
            for _, d in ipairs({{"Down", 0, 1}, {"Left", -1, 0}, {"Right", 1, 0}, {"Up", 0, -1}}) do
                local free = type(point.can_step) == "table" and point.can_step[d[1]] == true
                for _, object in ipairs(point.blocked or {}) do
                    if object.x == point.x + d[2] and object.y == point.y + d[3] then free = false end
                end
                if free then return {[d[1]]=true}, self.phase end
            end
            return {}, self.phase
        end
        if on(point, city) then
            self.phase = "to-house"
            local buttons, why = walk(city, point, {facts.door})
            if why == "arrived" then return {}, self.phase end   -- the door warp fires on arrival
            return buttons, why
        end
        if not on(point, house) then
            return nil, fmt("map %s:%s is not on the %s route", tostring(point.map_group), tostring(point.map_number), kind)
        end
        self.phase = "talk"
        -- the NPC's live tile (Kyle walks up and down his column; Bill stands)
        local npc
        for _, object in ipairs(point.blocked or {}) do
            if object.x == facts.npc.x and integer(object.y, facts.npc.y_min, facts.npc.y_max) then npc = object end
        end
        if not npc then
            self.missing = (self.missing or 0) + 1
            if self.missing == 120 and self.log then   -- diagnostics only: the live objects once
                local seen = {}
                for _, o in ipairs(point.blocked or {}) do seen[#seen + 1] = o.x .. "," .. o.y end
                self.log("  U1G no npc at x=" .. facts.npc.x .. "; objects " .. table.concat(seen, " "))
            end
            return {}, self.phase
        end
        local goals = {}
        for _, side in ipairs({{-1, "Right"}, {1, "Left"}}) do
            local x = npc.x + side[1]
            if x >= 0 and x < house.width and house.grid[npc.y * house.width + x + 1] == 1 then
                goals[#goals + 1] = {x=x, y=npc.y, face=side[2]}
                if point.x == x and point.y == npc.y then
                    if point.facing ~= side[2] then return press(side[2]) end
                    return press("A")
                end
            end
        end
        local buttons, why = walk(house, point, goals)
        if why == "arrived" then return {}, self.phase end
        return buttons, why
    end
    return self
end

-- The effect bytes of a symbol, live (sBoxCount in SRAM through the linear CartRAM domain).
local function effect_reader(ctx, facts)
    return function(symbol)
        local e, api, bytes = facts.effects[symbol], ctx.api, {}
        for i = 0, U.EFFECT_SIZE[symbol] - 1 do
            bytes[#bytes + 1] = e.bank ~= nil and api.read_u8(e.bank * 0x2000 + e.addr - 0xA000 + i, "CartRAM")
                or api.read_u8(e.addr + i, "System Bus")
        end
        return hex(bytes)
    end
end

function U.run(F, ctx, SG, g)
    local api, log, check, json = g.api, g.log, g.check, ctx.json
    local facts, title, case = ctx.u1.u1g, ctx.env.title, ctx.case
    local kind = facts.kind
    local claimed = assert(U.KINDS[kind], "unknown U1G kind " .. tostring(kind))
    local PI = dofile(ctx.root .. "/" .. F.POISON_INPUTS)
    local arrival = api.framecount()
    local expect = {}
    for _, name in ipairs(U.MODEL_SITES[kind]) do expect[#expect + 1] = name end
    local probe = F.probe(ctx, g.pack, ctx.u1.decoy, expect)
    local read = effect_reader(ctx, facts)
    local arming, effects = {}, {}
    for symbol in pairs(U.EFFECT_SIZE) do arming[symbol] = {frame=api.framecount(), hex=read(symbol)} end
    -- one record per site: its first hit showing a live transition from the arming read (a shared-PC final such as
    -- HatchEggs.next or return_from_capture also runs for other mons first: live run 1), else its first hit
    function probe.on_hit(name, frame, armed)
        local symbol = U.EFFECT_SYMBOL[name]
        local held = effects[name]
        if symbol and (held == nil or held.after_hex == held.arming_hex) then
            local a, after = arming[symbol], read(symbol)
            if held == nil or after ~= a.hex then
                effects[name] = {site=name, symbol=symbol, wram=facts.effects[symbol].addr, size=U.EFFECT_SIZE[symbol],
                    arming_frame=a.frame, arming_hex=a.hex, before_hex=a.hex, hit_frame=armed, callback=frame,
                    after_hex=after}
            end
        end
    end
    -- the production decoder, MODEL authority, on the same hooks, reading through a live Reads (the box is in SRAM)
    local probe_model = F.poison_model(ctx, g.Signals, g.wrapper, g.pack, {"poison_faint"})
    local live = {cart_ram_linear=true, read_u8=api.read_u8, domain_size=api.domain_size,
                  read_range=function(addr, n, domain) return api.read_range(addr, n, domain) end,
                  bank_valid=probe_model.bank_valid}
    probe_model.close()
    local reads = assert(dofile(ctx.root .. "/lua/gen2/reads.lua").new(ctx.profile, live))
    local packs = {areas=g.read_json("data/games/gen2_" .. title .. "/area_map.json"),
                   encounters=g.read_json("data/games/gen2_" .. title .. "/encounter_tables.json"),
                   statics=g.read_json("data/games/gen2_" .. title .. "/static_encounters.json"),
                   gifts=g.read_json("data/games/gen2_" .. title .. "/gifts.json")}
    -- The production binder resolves point symbols pack-wide, also from unregistered sites (signals.lua build);
    -- the model keeps only its sites, so they carry the pack-wide union (live run 1: wBattleScriptFlags).
    local model_pack = g.read_json("data/games/gen2_" .. title .. "/engine_signals.json")
    local union = {}
    for _, site in pairs(model_pack.titles[title].sites) do
        for symbol, point in pairs(site.point_symbols) do union[symbol] = point end
    end
    for _, name in ipairs(U.MODEL_SITES[kind]) do
        local points = model_pack.titles[title].sites[name].point_symbols
        for symbol, point in pairs(union) do if points[symbol] == nil then points[symbol] = point end end
    end
    local model = F.poison_model(ctx, g.Signals, g.wrapper, model_pack, U.MODEL_SITES[kind], reads, packs)
    -- observation: the scripted gate's point plus the battle menu grid, the Ball cursor, the party and the box count
    local base = SG.qualify_observer(ctx)
    local function observe()
        local point = base()
        if point.ui and point.ui.kind == "pack_balls" then point.ball_cursor = F.ball_cursor(SG.screen(ctx)) end
        if point.ui and point.ui.kind == "battle_menu" then
            local menu = SG.parse_menu(SG.screen(ctx), ctx.obs.screen.width, ctx.obs.screen.height, SG.BATTLE_MENU_GRID)
            if menu then point.ui.items, point.ui.cursor, point.ui.columns = menu.items, menu.cursor, menu.columns
            else point.input_ready = false end
        end
        if point.ui and point.ui.kind == "battle_party" then point.party_cursor = g.FI.party_cursor(SG.screen(ctx)) end
        local count = ctx.sym("wPartyCount")[1]
        point.party = {count=count, species={}}
        for i = 1, math.min(count, 6) do point.party.species[i] = ctx.sym("wPartySpecies", i - 1)[1] end
        local box = facts.effects.sBoxCount
        point.box_count = api.read_u8(box.bank * 0x2000 + box.addr - 0xA000, "CartRAM")
        return point
    end
    facts.box_base = observe().box_count
    local driver = U.driver(F, PI, facts)
    driver.log = log
    local diag = {log=log, frame=api.framecount, screen=function() return SG.screen(ctx) end,
                  where=function() return fmt("PC %04X", api.register("PC")) end, trace=false}
    local played, outcome = F.play(g.host, {name="u1g-" .. kind, terminal=driver.terminal, terminal_idle=true,
        max_frames=U.BUDGET.max_frames, max_phase_frames=U.BUDGET.max_phase_frames,
        settle_frames=F.BUDGET.settle_frames}, driver, observe, diag)
    model.close()
    probe.release()
    g.state.release()
    local record = probe.record
    record.negatives = g.negatives
    record.negatives.wrong_bank_hit = (record.decoy.raw >= 1 and record.decoy.accepted == 0) and "refused" or "NOT refused"
    check("U1G " .. kind .. " leg reached its terminal state natively", played, not played and outcome or nil)

    -- verdict (the validator's rules restated; the receipt is refused by signals.lua whatever this says)
    local problems = {}
    local function need(ok, what) if not ok then problems[#problems + 1] = what end end
    need(record.registry_failed == nil, "hook registry latched a failure")
    need(record.accept_errors == 0, "binder accept faults")
    need(record.aligned >= 1 and record.misaligned == 0, "callback frame != armed frame on some hit")
    for _, name in ipairs(claimed) do
        local s = record.sites[name]
        need(s and s.hits >= 1 and s.pc == s.addr and s.hit_bank == s.bank and s.off_pin == 0, name .. " did not fire at its pin")
        if U.EFFECT_SYMBOL[name] then
            local why = U.effect_problem(effects[name], arrival)
            need(why == nil, tostring(why))
        end
    end
    need(record.decoy.raw >= 1 and record.decoy.accepted == 0 and record.decoy.bank_rejects == record.decoy.raw,
         "wrong-bank decoy not refused")
    for _, name in ipairs({"wrong_pack_byte", "script_bytecode_arm", "wrong_bank_hit"}) do
        need(record.negatives[name] == "refused", "negative control not refused: " .. name)
    end
    need(U.model_problem(kind, model.events) == nil, tostring(U.model_problem(kind, model.events)))
    local list = {}
    for name, e in pairs(effects) do list[#list + 1] = e end
    table.sort(list, function(a, b) return a.site < b.site end)
    log("EFFECTS " .. json.encode(json.array(list)))
    log("U1G_MODEL " .. json.encode({events=json.array(model.events), refusals=json.object(model.refusals or {}),
                                     failed=model.failed or json.null}))
    log("DECOY " .. json.encode({raw=record.decoy.raw, accepted=record.decoy.accepted, bank_rejects=record.decoy.bank_rejects}))
    log("VERDICT " .. json.encode(json.object({problems=json.array(problems)})))
    for _, problem in ipairs(problems) do check(problem, false) end
    if not played or #problems > 0 then return g.finish("no run") end

    local sites, run_effects = {}, {}
    for _, name in ipairs(claimed) do
        local s = record.sites[name]
        sites[name] = {bank=s.bank, addr=s.addr, pc=s.pc, expected_hex=s.expected_hex, symbol=s.symbol,
                       hits=s.hits, raw=s.raw, bank_rejects=s.bank_rejects, first_frame=s.first_frame}
        if effects[name] then run_effects[#run_effects + 1] = effects[name] end
    end
    local counts = {}
    for _, e in ipairs(model.events) do local k = U.event_key(e) counts[k] = (counts[k] or 0) + 1 end
    local run = {schema=g.Signals.RECEIPT_SCHEMA, title=title, evidence_level=g.evidence, result="PASS",
        rom_sha1=g.pack.source.rom_sha1, pack_commit=g.pack.source.commit, pack_specs_sha256=g.pack.specs_sha256,
        fixture=case.synth, attempt_id=case.attempt_id, core_mode="CGB", input_mode="normal_buttons",
        fixture_sha256=ctx.qualify.stage_fingerprint, qualification_attempt_id=ctx.u1.qualification_attempt_id,
        harness_write_scopes=json.array({}), bank_check="live", arrival_frame=arrival,
        frame_alignment={passed=true, aligned_hits=record.aligned, misaligned_hits=record.misaligned,
            rule="every accepted hit's callback frame == the frame being emulated (armed)"},
        negatives=record.negatives, decoy={bank=ctx.u1.decoy.bank, addr=ctx.u1.decoy.addr, raw=record.decoy.raw,
            accepted=record.decoy.accepted, bank_rejects=record.decoy.bank_rejects},
        sites=sites, proven=json.array(claimed), synth=g.read_json(facts.disclosure), effects=json.array(run_effects),
        model_events=counts, u1g_kind=kind}
    -- production: the title's committed receipt plus this run, as one v2 receipt, registers the union
    local committed = g.read_json("tests/fixtures/gen2/receipts/" .. title .. ".engine_sites.json")
    local runs = {}
    for _, r in ipairs(committed.runs or {committed}) do if r.fixture ~= run.fixture then runs[#runs + 1] = r end end
    runs[#runs + 1] = run
    local options = {title=title, profile=g.wrapper, pack=g.pack, reads=ctx.reads, owner="gen2-u1g-production",
        max_pending=8, Registry=dofile(ctx.root .. "/lua/hook_registry.lua"), GB=dofile(ctx.root .. "/lua/gb_hook_binding.lua"),
        io={read_u8=api.read_u8, read_range=api.read_range, register=api.register, framecount=api.framecount,
            on_bus_exec=api.on_bus_exec, unregister=api.unregister, bank_valid=function() return false end,
            stack_valid=function() return false end},
        authority={kind="PHYSICAL_RUNTIME", capture=function() return {generation=1, operation="u1g"} end,
                   valid=function() return false end},
        runtime_qualification={schema=g.Signals.RECEIPT_SCHEMA_V2, title=title, runs=runs}}
    local service, why = g.Signals.new(options)
    local registered = service and service:status().registered_sites or {}
    if service then service:close() end
    local set = {}
    for _, name in ipairs(registered) do set[name] = true end
    local all = true
    for _, name in ipairs(claimed) do all = all and set[name] == true end
    check("production Signals.new registers this run's sites with the committed runs", service ~= nil and all,
          service and table.concat(registered, ",") or why)
    log("PRODUCTION " .. json.encode({registered=json.array(registered), refusal=tostring(why)}))
    if all and service then log("RECEIPT " .. json.encode(run)) end
    return g.finish("u1g-" .. kind)
end

return U
