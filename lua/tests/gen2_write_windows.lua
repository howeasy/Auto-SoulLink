--[[
  lua/tests/gen2_write_windows.lua -- card gen2-U2: the Gen 2 write checkpoint on the RUNNING cartridge
  (docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md row U2; docs/gen2/GEN2_BINDING_PLAN.md P3b.5;
  source facts docs/gen2/reviews/OMP_U2_WRITE_WINDOW_FACTS_2026-09-23.md incl. the O8 predicate audit).

  Result file: patch/build/gen2_write_windows_result.txt (RESULT: PASS|FAIL, last line).

  Boots a qualified fixture WARM, arrives through the inspect gate's source-qualified CONTINUE path
  (lua/tests/gen2_inspect_gate.lua G.arrive), then hooks the pack checkpoint PC
  (write_checkpoint.json primary.execution_before: OWPlayerInput before `call CheckAPressOW`) and runs
  lua/gen2_write_safety.lua's held evaluation (anchors in ROM + System Bus, PC, bounded caller word,
  hROMBank shadow, SVBK, serial, the 15 pack predicates) inside that synchronous CPU hold. Every
  harness write is TEST-ONLY and goes through the shared lua/write_permit.lua (party: lua/gen2/writes.lua;
  box: lua/gen2/boxes.lua + a permit-backed CartRAM executor); the writer's authorize policy is true
  ONLY inside an accepted hold. Inputs are normal buttons: 12-frame HOLD menu presses, overworld
  walking holds a direction per frame (a walk step is 8 frames).

  Modes (SLINK_GEN2_U2 = {"mode": ..., "qualification_attempt_id": <the fixture's qualification attempt>}):
    town    <title>_town (Elm's lab). idle: party HP-1 (writes.lua) + a current-box deposit of the lead
            mon into the AUTHORITATIVE sBox copy in CartRAM (boxes.lua, owner "active"), both in one
            accepted hold, with the SRAM-closed bus view recorded. Then START menu (refused by
            wScriptRunning/wScriptMode, and the OWPlayerInput anchor stays silent inside it), Elm's
            script text box (wScriptRunning/wScriptMode/wScriptFlags), a native SAVE (the
            wGameLogicPaused window, 62+ frames: REQUIRED), SaveRAM flushed and its exact bytes (CartRAM +
            RTC trailer) kept as <case>.u2_saved.SaveRAM (U.saved_path), then the lab exit warp (wMapStatus)
            and liveness in New Bark. The snapshot, not the SaveRAM file, is the post-save image: Gold/Silver
            keep the window stack and sScratch in SRAM, so the menu close and overworld after the save (and
            EmuHawk's exit-time flush) rewrite that file.
    reload  the town run's flushed SaveRAM, cold-booted: its CartRAM hash before any frame, CONTINUE,
            liveness, the persisted party HP + active/backing box bytes, DUMP (party + CartRAM).
    battle  <title>_battle (Route 29 grass): liveness, walk the grass until a wild battle (bounded), the
            battle window (wBattleMode; faint_party_slot refuses the active slot -- UpdateBattleMonInParty
            copies the battle struct back, so an in-battle KO must target wBattleMonHP: MODEL-only),
            RUN, liveness after the battle.
    battle_faint  <title>_battle (card O-30, U.battle_faint_main): one catch, then a wild battle whose battle
            holds (write_checkpoint.json battle_hold) kill the bench mon, then the active lead; the native
            faint and whiteout follow (engine-read oracle order). Adds the battle_faint write kind.
  Per window the RAW mechanism is recorded: frames, frames open at BOTH edges (only their anchor hits
  count: a hold accepted just before a warp begins is idle by construction), raw in-bank anchor hits and
  inspect_candidate's refusal reasons at them, accepted holds, the failing-predicate set of every frame,
  and a party write attempted outside any hold with its before/after bytes (the permit refuses it: the
  authority is an accepted hold, so the window's own evidence is the hits + predicates above).

  Printed: U2_RUN <json> (the run record lua/gen2_write_safety.lua M.run_problem/M.qualified recompute;
  evidence_level PHYSICAL only from this file's own BizHawk entry, MODEL under any library caller) and
  DUMP (reload). tests/live/test_gen2_write_windows.py re-derives it and assembles the receipt.
--]]
local U = {}
U.RESULT = "patch/build/gen2_write_windows_result.txt"
U.INSPECT_GATE = "lua/tests/gen2_inspect_gate.lua"
-- ponytail: live budgets and the per-window observation length, not measured; raise if a run needs longer.
U.OBSERVE = 30
U.BUDGET = {max_frames=60000, max_phase_frames=15000, settle_frames=4}
U.TEXT_KINDS = {text=true, prompt_button=true, wait_button=true}
U.MODES = {town="town", battle="battle", reload="town",   -- mode -> required fixture target
           boxes="battle", boxes_reset="battle", boxes_reload="battle", hello="battle", battle_faint="battle"}
-- the one shared step rule (ledges from the separate map.ledges field), from beside this file
local W = dofile((debug.getinfo(1, "S").source:match("^@(.-)[^/\\]*$") or "lua/tests/") .. "gen2_walk.lua")
U.DIRECTIONS = W.DIRECTIONS
U.REPULSE = 60
local fmt = string.format

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end
local function matches(point, map) return point.map_group == map.map_group and point.map_number == map.map_number end
local function hex(bytes)
    local out = {}
    for i = 1, #bytes do out[i] = fmt("%02x", bytes[i]) end
    return table.concat(out)
end

-- Pure: first step of a BFS over the source grid (the gen2_walk.lua step rule) toward (goal.x, goal.y);
-- "arrived" on the goal.
function U.step_toward(map, point, goal)
    if not integer(point.x, 0, map.width - 1) or not integer(point.y, 0, map.height - 1) then
        return nil, "player coordinate outside the source map"
    end
    if point.x == goal.x and point.y == goal.y then return "arrived" end
    if type(point.can_step) ~= "table" then return nil, "live collision observation missing" end
    local function key(x, y) return y * map.width + x + 1 end
    local blocked = {}
    for _, object in ipairs(point.blocked or {}) do blocked[key(object.x, object.y)] = true end
    for _, warp in ipairs(map.warps or {}) do
        if warp.x ~= goal.x or warp.y ~= goal.y then blocked[key(warp.x, warp.y)] = true end
    end
    local step = W.stepper(map, point.can_step)
    local queue, head, seen = {{point.x, point.y, false}}, 1, {[key(point.x, point.y)] = true}
    while head <= #queue do
        local node = queue[head]; head = head + 1
        for _, d in ipairs(U.DIRECTIONS) do
            local x, y = step(node[1], node[2], d, not node[3])
            if x then
                local index, first = key(x, y), node[3] or d[1]
                if not seen[index] and not blocked[index] then
                    if x == goal.x and y == goal.y then return first end
                    seen[index] = true
                    queue[#queue + 1] = {x, y, first}
                end
            end
        end
    end
    return nil, fmt("no source path from %d,%d to %d,%d", point.x, point.y, goal.x, goal.y)
end

-- Pure: the next grass tile next to the player, preferring the one just left (oscillate in the grass).
function U.grass_step(map, point, from)
    if type(point.can_step) ~= "table" then return nil, "live collision observation missing" end
    local blocked, best = {}, nil
    for _, object in ipairs(point.blocked or {}) do blocked[object.y * map.width + object.x] = true end
    local step = W.stepper(map, point.can_step)
    for _, d in ipairs(U.DIRECTIONS) do
        local x, y, tile = step(point.x, point.y, d, true)
        if tile == 2 and not blocked[y * map.width + x] then
            if from and from.x == x and from.y == y then return d[1] end
            best = best or d[1]
        end
    end
    if best then return best end
    return nil, fmt("no steppable grass tile next to %d,%d", point.x, point.y)
end

-- Pure driver: point -> buttons, phase. The harness adds point.accepted (accepted holds so far),
-- point.write_done, point.window_frames (frames of the open window) and point.battle_attempted.
function U.driver(mode, maps)
    assert(U.MODES[mode], "unknown U2 mode " .. tostring(mode))
    local d = {terminal="done", phase="idle", stage=1}   -- stage: boxes_reset's op round (Safety.BOX_OPS)
    -- A native press is HELD 12 frames (gen2_qualify.lua HOLD); overworld walking holds per frame.
    local HOLD, held, hold_left, release = 12, nil, 0, false
    local mark, save_counter, confirmed, waited, here, from = 0, nil, false, 0, nil, nil
    local ops_mark
    local function press(button)
        release, held, hold_left = true, button, HOLD - 1
        return {[button]=true}, d.phase
    end
    local function go(phase) d.phase, waited = phase, 0 end
    local function choose(ui, wanted, columns)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local target
        for index, label in ipairs(ui.items) do
            if type(label) == "string" and label:upper() == wanted then
                if target then return nil, "ambiguous menu label" end
                target = index
            end
        end
        if not target then return nil, "required native menu item missing: " .. wanted end
        if target == ui.cursor then return press("A") end
        local tx, cx = (target - 1) % columns, (ui.cursor - 1) % columns
        if tx ~= cx then return press(tx > cx and "Right" or "Left") end
        return press(target > ui.cursor and "Down" or "Up")
    end
    function d.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        if point.write_error then return nil, "idle hold write refused: " .. tostring(point.write_error) end
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, d.phase end
        if release then release = false; return {}, d.phase end
        if d.phase == d.terminal then return {}, d.phase end
        waited = waited + 1
        local ui, ready, idle, p = point.ui, point.input_ready == true, point.overworld_ready == true, d.phase
        local text = ui ~= nil and U.TEXT_KINDS[ui.kind] == true
        -- liveness gate: every later phase needs a NEW accepted hold after the previous window.
        local function live(next_phase)
            if idle and point.accepted > mark then go(next_phase); return true end
            return false
        end
        if p == "idle" then
            if not idle or point.accepted < 1 or (mode == "town" and not point.write_done) then return {}, p end
            mark = point.accepted
            if mode == "reload" or mode == "boxes_reload" then go("done"); return {}, d.phase end
            if mode == "boxes_reset" then go("ops"); return {}, d.phase end
            if mode == "battle" then go("walk"); return {}, d.phase end
            go("start_menu")
            return press("Start")
        elseif p == "start_menu" then
            if ui and ui.kind == "start_menu" then
                if ready and point.window_frames >= U.OBSERVE then go("start_close"); return press("B") end
                return {}, p
            end
            if idle and waited > U.REPULSE then waited = 0; return press("Start") end
            return {}, p
        elseif p == "start_close" then
            if idle then mark = point.accepted; go("face"); return {}, d.phase end
            if ui and ui.kind == "start_menu" and ready and waited > U.REPULSE then waited = 0; return press("B") end
            return {}, p
        elseif p == "face" then
            if not idle or point.accepted <= mark then return {}, p end
            local ahead = false
            for _, object in ipairs(point.blocked or {}) do
                if object.x == point.x and object.y == point.y - 1 then ahead = true end
            end
            if not ahead then return nil, "no object above the player (Elm expected at x, y-1)" end
            if point.facing ~= "Up" then return press("Up") end
            go("talk")
            return press("A")
        elseif p == "talk" then
            if text then
                if ready and point.window_frames >= U.OBSERVE then go("talk_close"); return press("A") end
                return {}, p
            end
            if ui ~= nil and ready then return nil, "unexpected UI while talking: " .. tostring(ui.kind) end
            if idle and waited > U.REPULSE then waited = 0; return press("A") end
            return {}, p
        elseif p == "talk_close" then
            if idle then mark = point.accepted; go("to_save"); return {}, d.phase end
            if text and ready then return press("A") end
            return {}, p
        elseif p == "to_save" then
            if live("save") then save_counter = point.save_success_counter; return press("Start") end
            return {}, p
        elseif p == "save" then
            if not integer(point.save_success_counter, 0, math.huge) then return nil, "native save witness missing" end
            if point.save_success_counter > save_counter then mark = point.accepted; go("post_save"); return {}, d.phase end
            if ui ~= nil then
                if not ready then return {}, p end
                if ui.kind == "start_menu" then return choose(ui, "SAVE", 1) end
                if ui.kind == "yes_no" and ui.prompt == "save_confirm" then confirmed = true; return choose(ui, "YES", 1) end
                if ui.kind == "yes_no" and ui.prompt == "save_overwrite" then return choose(ui, "YES", 1) end
                if ui.kind == "prompt_button" and confirmed and ui.prompt == "save_overwrite_text" then return press("A") end
                return nil, "UI is not valid while saving: " .. tostring(ui.kind) .. "/" .. tostring(ui.prompt)
            end
            if idle and waited > U.REPULSE then waited = 0; return press("Start") end
            return {}, p
        elseif p == "ops" then   -- boxes_reset: the checkpoint hook runs this stage's ops; then a fresh hold
            if point.ops_done then
                if ops_mark == nil then ops_mark = point.accepted
                elseif idle and point.accepted > ops_mark then
                    mark, ops_mark = point.accepted, nil
                    -- stage 3 ends UNSAVED: done flushes the reset image (no native save)
                    go(d.stage == 3 and "done" or "to_save")
                end
            end
            return {}, d.phase
        elseif p == "post_save" then
            if mode == "boxes_reset" then
                if live("ops") then d.stage = d.stage + 1 end
                return {}, d.phase
            end
            if live("exit") then return {}, d.phase end
            if ui and ui.kind == "start_menu" and ready and waited > U.REPULSE then waited = 0; return press("B") end
            return {}, p
        elseif p == "exit" then
            if not matches(point, maps.ElmsLab) or point.map_status ~= 2 then go("warp"); return {}, d.phase end
            if ui ~= nil then
                if text and ready then return press("A") end   -- the aide's potion scene (coord event)
                if ready and not text then return nil, "unexpected UI on the way out: " .. tostring(ui.kind) end
                return {}, p
            end
            if not idle then return {}, p end
            local warp
            for _, row in ipairs(maps.ElmsLab.warps) do
                if row.destination == "NEW_BARK_TOWN" then warp = warp or row end
            end
            if not warp then return nil, "lab exit warp missing from the route facts" end
            local button, why = U.step_toward(maps.ElmsLab, point, warp)
            if not button then return nil, why end
            if button == "arrived" then return press(warp.carpet or "Down") end
            return {[button]=true}, p
        elseif p == "warp" then
            if matches(point, maps.NewBarkTown) and idle then mark = point.accepted; go("post_warp") end
            return {}, d.phase
        elseif p == "post_warp" then
            live("done")
            return {}, d.phase
        elseif p == "walk" then
            if integer(point.battle_mode, 1, 255) then go("battle"); return {}, d.phase end
            if not idle then return {}, p end
            if here and (here.x ~= point.x or here.y ~= point.y) then from = here end
            here = {x=point.x, y=point.y}
            local button, why = U.grass_step(maps.Route29, point, from)
            if not button then return nil, why end
            return {[button]=true}, p
        elseif p == "battle" then
            if point.battle_mode == 0 then
                if idle then mark = point.accepted; go("post_battle") end
                return {}, d.phase
            end
            if ui == nil or not ready then return {}, p end
            if ui.kind == "battle_menu" then
                if point.window_frames < U.OBSERVE or point.battle_attempted ~= true then return {}, p end
                return choose(ui, "RUN", 2)
            end
            if text then return press("A") end
            return nil, "UI is not valid in battle: " .. tostring(ui.kind)
        elseif p == "post_battle" then
            live("done")
            return {}, d.phase
        end
        return nil, "unknown phase " .. tostring(p)
    end
    return d
end

-- Pure: which negative window the frame that just ran belongs to (nil = none).
function U.window_for(phase, point)
    if integer(point.battle_mode, 1, 255) then return "battle" end
    if point.game_paused ~= 0 then return "save_paused" end
    if (phase == "exit" or phase == "warp") and point.map_status ~= 2 then return "mid_warp" end
    if phase == "start_menu" and point.ui and point.ui.kind == "start_menu" then return "start_menu" end
    if (phase == "talk" or phase == "talk_close") and point.ui and U.TEXT_KINDS[point.ui.kind] then return "script_text" end
    return nil
end

local function read_json(ctx, rel)
    local f = assert(io.open(ctx.root .. "/" .. rel, "rb"), "cannot open " .. rel)
    local text = f:read("a")
    f:close()
    return assert(ctx.json.decode(text, {items=1000000}), rel .. " malformed")
end

function U.inspect_gate(root)
    local previous = SLINK_GEN2_GATE_LIBRARY
    SLINK_GEN2_GATE_LIBRARY = true
    local ok, IG = pcall(dofile, root .. "/" .. U.INSPECT_GATE)
    SLINK_GEN2_GATE_LIBRARY = previous
    assert(ok and type(IG) == "table", "cannot load " .. U.INSPECT_GATE .. ": " .. tostring(IG))
    return IG
end

-- The flushed post-save SaveRAM image of a town run (the reload candidate and the persistence evidence).
function U.saved_path(dir, case_name) return dir .. "/" .. case_name .. ".u2_saved.SaveRAM" end

local live_api   -- set only by this file's own BizHawk entry below; a library caller cannot claim it

function U.main(api, getenv, SG, IG)
    local evidence = (live_api ~= nil and api == live_api) and "PHYSICAL" or "MODEL"
    local root = getenv("SLINK_ROOT") or SLINK_ROOT or "."
    local lines, failures = {}, 0
    local function log(s)
        lines[#lines + 1] = s
        local f = io.open(root .. "/" .. U.RESULT, "w")
        if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    end
    local function check(what, ok, detail)
        if not ok then failures = failures + 1 end
        log(fmt("  [%s] %s%s", ok and "ok" or "FAIL", what, detail ~= nil and ("  -- " .. tostring(detail)) or ""))
        return ok
    end
    local function finish(extra)
        log(fmt("RESULT: %s %s (%d checks failed)", failures == 0 and "PASS" or "FAIL", extra or "u2", failures))
        return failures == 0
    end
    log("[gen2_write_windows] U2 checkpoint + write windows")

    local ok, ctx = pcall(function()
        IG = IG or U.inspect_gate(root)
        SG = SG or IG.scripted_gate(root)
        local c = SG.context(api, getenv)
        assert(c.qualify ~= nil and c.qualify.stage == "boot", "SLINK_GEN2_QUALIFY stage \"boot\" required")
        c.u2 = assert(c.json.decode(assert(getenv("SLINK_GEN2_U2"), "SLINK_GEN2_U2 missing")))
        assert(U.MODES[c.u2.mode] == c.case.target, "U2 mode does not fit the fixture target")
        assert(type(c.u2.qualification_attempt_id) == "string" and c.u2.qualification_attempt_id ~= "",
               "SLINK_GEN2_U2 qualification_attempt_id missing")
        return c
    end)
    if not check("environment, facts, profile and running ROM/CGB bound", ok, not ok and ctx or nil) then
        return finish("bad environment")
    end
    ctx.log = log
    local json, profile, title, mode = ctx.json, ctx.profile, ctx.env.title, ctx.u2.mode
    local L = function(rel) return dofile(ctx.root .. "/" .. rel) end
    local pack = read_json(ctx, "data/games/gen2_" .. title .. "/write_checkpoint.json")
    local primary = pack.titles[title].primary
    local Safety, Evaluator = L("lua/gen2_write_safety.lua"), L("lua/gb_checkpoint.lua")
    local Writes, Boxes, Permit = L("lua/gen2/writes.lua"), L("lua/gen2/boxes.lua"), ctx.Permit
    local owner = primary.ownership_requirements
    local HROM, SVBK, bank = owner.rom_bank_shadow.address, owner.wram_bank_register.address, primary.execution_before.bank

    -- Frame-end predicate reads by the pack rows' own banks (never the live SVBK).
    local rows = {}
    for _, row in ipairs(primary.state_predicates) do
        assert(row.address < 0xD000 or row.address >= 0xE000 or row.bank == 1,
               "WRAMX predicate outside bank 1: " .. row.symbol)
        rows[row.symbol] = row
    end
    local function pred_read(addr)
        if addr >= 0xD000 and addr < 0xE000 then return api.read_u8(0x1000 + addr - 0xD000, "WRAM") end
        if addr >= 0xC000 and addr < 0xD000 then return api.read_u8(addr - 0xC000, "WRAM") end
        return api.read_u8(addr, "System Bus")
    end

    local function effective_wram_bank()
        local v = api.read_u8(SVBK, "System Bus") % 8
        return v == 0 and 1 or v
    end
    local checkpoint = Safety.new(pack, title,
        {read_u8=api.read_u8, domains=api.domains, domain_size=api.domain_size, register=api.register},
        Evaluator, {
            capture=api.framecount, valid=function(held) return held == api.framecount() end,
            admitted=function(t, sha) return t == title and sha == ctx.env.rom_sha1 end,
            no_conflicting_owner=function() return true end,
            mapped_rom_bank=function() return api.read_u8(HROM, "System Bus") end,
            effective_wram_bank=effective_wram_bank,
        })

    if mode == "hello" then
        return U.hello_main({api=api, ctx=ctx, SG=SG, IG=IG, log=log, check=check, finish=finish, title=title})
    end
    if mode == "battle_faint" then
        return U.battle_faint_main({api=api, ctx=ctx, SG=SG, IG=IG, log=log, check=check, finish=finish,
            profile=profile, Safety=Safety, primary=primary, pack=pack, title=title, evidence=evidence, getenv=getenv,
            HROM=HROM, bank=bank, checkpoint=checkpoint, failures=function() return failures end})
    end
    if U.BOX_MODES[mode] then
        return U.box_main({api=api, ctx=ctx, SG=SG, IG=IG, log=log, check=check, finish=finish, profile=profile,
            mode=mode, Safety=Safety, primary=primary, pack=pack, title=title, evidence=evidence, getenv=getenv,
            HROM=HROM, bank=bank, checkpoint=checkpoint, failures=function() return failures end})
    end

    -- The ONLY authority for a harness write: an accepted hold, inside the checkpoint callback.
    -- Every byte written is charged to the harness scope armed around it (the run record lists them).
    local in_hold, scope_now, wrote_scopes = false, nil, {}
    local function charge() wrote_scopes[tostring(scope_now)] = true end
    local lifetime = {capture=api.framecount, valid=function(token) return token == api.framecount() end}
    local writes = Writes.new(profile, {
        write_u8=function(addr, value, domain) charge(); api.write_u8(addr, value, domain) end,
        bank_valid=function(b, addr, n)
            if addr >= 0xC000 and addr + n <= 0xD000 then return b == 0 end
            return addr >= 0xD000 and addr + n <= 0xE000 and b == effective_wram_bank()
        end}, Permit, {
            authorize=function() return in_hold end,
            pointer_stable=function() return true end,   -- ponytail: the party array is fixed WRAM
            lifetime=lifetime,
            provenance=function() return {site="lua/tests/gen2_write_windows.lua", scope="TEST-ONLY"} end,
        })
    local flat, length = profile.derived.active_box_flat, profile.derived.active_box_copy_length
    local box_permit = Permit.new({
        write_u8=function(addr, value) charge(); api.write_u8(addr, value, "CartRAM") end,
        domains={CartRAM={bounds=function(addr, n) return addr >= flat and addr + n <= flat + length end,
            mapped=function() return in_hold end, pointer_stable=function() return true end}},
        lifetime=lifetime,
        provenance=function(_, _, _, reason) return {site="lua/tests/gen2_write_windows.lua", scope=reason} end,
    })
    local boxes = Boxes.new(profile, {
        preflight=function(req)
            if not in_hold then return nil, "no accepted checkpoint hold" end
            if ctx.sym("wCurBox")[1] ~= req.observed_state.current_box
               or ctx.sym("wSavedAtLeastOnce")[1] ~= req.observed_state.saved_at_least_once then
                return nil, "observed box state changed"
            end
            if api.domain_size("CartRAM") < 32768 then return nil, "CartRAM smaller than 32 KiB" end
            for _, span in ipairs(req.before_spans) do
                local live = api.read_range(span.address, #span.bytes, "CartRAM")
                for i = 1, #span.bytes do if live[i] ~= span.bytes[i] then return nil, "box preimage changed" end end
            end
            return {mapping_qualified=true, domain="CartRAM", domain_size=32768}
        end,
        execute=function(_, spans)
            local span = spans[1]
            scope_now = "u2-test-box-write"
            box_permit:scope(scope_now, nil, function()
                box_permit:write_batch({{domain="CartRAM", addr=span.address, bytes=span.bytes}})
            end)
            return {status="written", completed=#span.bytes}
        end,
    })

    -- Inside an accepted hold: party HP-1 through writes.lua, then the lead mon deposited into the
    -- current box's authoritative sBox copy through boxes.lua. TEST-ONLY scoped writes.
    local function idle_write(frame, reason)
        local c = profile.constants
        assert(ctx.sym("wPartyCount")[1] >= 1, "empty party")
        local hp = ctx.sym("wPartyMon1HP", 0, 2)
        local value = hp[1] * 256 + hp[2]
        assert(value >= 2, "lead mon HP below 2")
        local written = {(value - 1) // 256, (value - 1) % 256}
        scope_now = "u2-test-party-write"
        writes:arm(scope_now)
        writes:write_party_bytes(0, c.MON_HP, written)
        writes:disarm()
        local cur, saved = ctx.sym("wCurBox")[1], ctx.sym("wSavedAtLeastOnce")[1]
        local before = api.read_range(flat, length, "CartRAM")
        local backing = profile.storage_boxes[cur + 1].flat
        local backing_before = api.read_range(backing, length, "CartRAM")
        local bus_address = 0xA000 + flat % 0x2000
        local bus_value = api.read_u8(bus_address, "System Bus")
        local record = ctx.sym("wPartyMon1", 0, 32)
        local plan = boxes.plan_deposit({current_box=cur, saved_at_least_once=saved}, cur, before,
            {bytes=record, ot=ctx.sym("wPartyMonOTs", 0, 11), nickname=ctx.sym("wPartyMonNicknames", 0, 11),
             species_marker=record[1]})
        assert(plan.owner == "active" and plan.spans[1].address == flat, "deposit is not to the authoritative sBox copy")
        boxes.commit(plan)
        return {frame=frame, reason=reason, party={slot=0, offset=c.MON_HP, address=profile.ram.wPartyMon1HP,
                    bank=profile.ram_bank.wPartyMon1HP, before_hex=hex(hp), written_hex=hex(written),
                    readback_hex=hex(ctx.sym("wPartyMon1HP", 0, 2))},
                box={current_box=cur, saved_at_least_once=saved, flat=flat, length=length,
                    backing_flat=backing, backing_before_hex=hex(backing_before), owner=plan.owner,
                    count_before=before[1], count_after=plan.after[1], before_hex=hex(before),
                    after_hex=hex(plan.after), readback_hex=hex(api.read_range(flat, length, "CartRAM")),
                    bus={address=bus_address, value=bus_value, cartram_value=before[1]}}}
    end

    -- reload: the cold-booted CartRAM, hashed before the first emulated frame of this run.
    local boot_digest = mode == "reload" and SG.cart_digest(api) or nil
    local arrived, detail, state = IG.arrive(ctx, SG)
    if not check("post-CONTINUE overworld arrival", arrived, detail) then
        state.release()
        return finish("no arrival")
    end

    local rec = {accepted=0, raw=0, seen=0, seen_raw=0, other_bank=0, refused=0, reasons={}, distinct=0,
                 frame_reasons={}, hits={}, windows={}, order={}, errors={}, pending=mode == "town", write=nil, prev=nil}
    local function bounded(into, reason, n)   -- at most 16 distinct reasons per histogram
        local distinct = 0
        for _ in pairs(into) do distinct = distinct + 1 end
        if into[reason] ~= nil or distinct < 16 then into[reason] = (into[reason] or 0) + (n or 1) end
    end
    local function on_checkpoint()
        local fine, err = pcall(function()
            local hit_bank = api.read_u8(HROM, "System Bus")
            if hit_bank ~= bank then rec.other_bank = rec.other_bank + 1; return end
            rec.raw = rec.raw + 1
            local report = checkpoint:inspect_candidate()
            if report.candidate_match ~= true then
                rec.refused = rec.refused + 1
                bounded(rec.reasons, report.reason)
                bounded(rec.frame_reasons, report.reason)
                return
            end
            rec.accepted = rec.accepted + 1
            if #rec.hits < 8 then   -- MEASURED PC register and hROMBank byte, never the pack echo
                rec.hits[#rec.hits + 1] = {frame=api.framecount(), pc=api.register("PC"), bank=hit_bank}
            end
            if rec.pending then
                rec.pending, in_hold = false, true
                local wrote, result = pcall(idle_write, api.framecount(), report.reason)
                in_hold = false
                rec.write = wrote and result or {error=tostring(result)}
            end
        end)
        in_hold = false
        if not fine and #rec.errors < 8 then rec.errors[#rec.errors + 1] = tostring(err) end
    end
    local handle = api.on_bus_exec(on_checkpoint, primary.execution_before.pc, "SLink-gen2-u2-checkpoint", "System Bus")

    -- A party write attempted outside any hold, through the SAME writer and authorize policy, with the
    -- slot's HP bytes before and after (a byte-level control; the window's authority evidence is its
    -- anchor hits and failing predicates).
    local function attempt(window, slot, battle)
        local base = profile.ram.wPartyMon1HP + slot * profile.constants.PARTYMON_STRUCT_LENGTH - profile.ram.wPartyMon1
        local before = hex(ctx.sym("wPartyMon1", base, 2))
        scope_now = "u2-negative-" .. window
        local wrote, why = pcall(function()
            writes:arm(scope_now)
            writes:write_party_bytes(slot, profile.constants.MON_HP, {0, 1})
        end)
        writes:disarm()
        local out = {slot=slot, refused=not wrote, reason=tostring(why), before_hex=before}
        if battle then
            local snapshot = {mode=ctx.sym("wBattleMode")[1], link_mode=pred_read(rows.wLinkMode.address),
                              battle_type=ctx.sym("wBattleType")[1], active_slot=slot}
            scope_now = "u2-negative-battle-faint"
            local fainted, faint_why = pcall(function()
                writes:arm(scope_now)
                writes:faint_party_slot(slot, snapshot)
            end)
            writes:disarm()
            out.faint_refused, out.faint_reason = not fainted, tostring(faint_why)
        end
        out.after_hex = hex(ctx.sym("wPartyMon1", base, 2))
        return out
    end

    local base = SG.qualify_observer(ctx)
    local model
    local function observe()
        local point = base()
        point.accepted, point.write_done = rec.accepted, rec.write ~= nil and rec.write.error == nil
        point.write_error = rec.write and rec.write.error
        point.map_status = pred_read(rows.wMapStatus.address)
        point.game_paused = pred_read(rows.wGameLogicPaused.address)
        point.window_frames = rec.prev and rec.windows[rec.prev].frames or 0
        point.battle_attempted = rec.windows.battle ~= nil and rec.windows.battle.write ~= nil
        return point
    end
    -- Frame-end window bookkeeping: hits during a frame count for a window only when the window was
    -- open at both ends of that frame.
    local function account(phase, point)
        local name = U.window_for(phase, point)
        local accepted, raw, reasons = rec.accepted - rec.seen, rec.raw - rec.seen_raw, rec.frame_reasons
        rec.seen, rec.seen_raw, rec.frame_reasons = rec.accepted, rec.raw, {}
        local both = name ~= nil and rec.prev == name
        rec.prev = name
        if not name then return end
        local w = rec.windows[name]
        if not w then
            w = {frames=0, both_edges=0, raw=0, accepted=0, edge_raw=0, reasons={}, sets={}, set_order={}}
            rec.windows[name] = w
            rec.order[#rec.order + 1] = name
        end
        w.frames = w.frames + 1
        if both then
            w.both_edges, w.raw, w.accepted = w.both_edges + 1, w.raw + raw, w.accepted + accepted
            for reason, n in pairs(reasons) do bounded(w.reasons, reason, n) end
        else
            w.edge_raw = w.edge_raw + raw   -- the opening frame: hits before the window began
        end
        local key = table.concat(Safety.failing_predicates(primary, pred_read), ",")
        if not w.sets[key] then w.sets[key], w.set_order[#w.set_order + 1] = 0, key end
        w.sets[key] = w.sets[key] + 1
        if w.write == nil and w.frames >= 2 then
            if name ~= "battle" then
                w.write = attempt(name, 0, false)
            elseif point.ui and point.ui.kind == "battle_menu" then
                local slot = ctx.sym("wCurBattleMon")[1]
                w.write = attempt(name, slot, true)
                local off = profile.ram.wPartyMon1HP - profile.ram.wPartyMon1 + slot * profile.constants.PARTYMON_STRUCT_LENGTH
                model = {active_slot=slot, party_hp_hex=hex(ctx.sym("wPartyMon1", off, 2)),
                         battle_hp_hex=hex(ctx.sym("wBattleMonHP", 0, 2)),
                         rule="UpdateBattleMonInParty copies wBattleMon over party slot wCurBattleMon; "
                              .. "an in-battle KO must write wBattleMonHP (MODEL-only here)"}
            end
        end
    end

    local driver = U.driver(mode, ctx.facts.maps)
    local idle = {}
    for _, name in ipairs(SG.BUTTONS) do idle[name] = false end
    local host = ctx.Host.new({step=SG.button_step(ctx), frame=api.framecount, idle=idle})
    local phases, save = {}, nil
    local played, outcome = pcall(host.run, {name="u2-" .. mode, terminal=driver.terminal,
        max_frames=U.BUDGET.max_frames, max_phase_frames=U.BUDGET.max_phase_frames,
        settle_frames=U.BUDGET.settle_frames, terminal_idle=true},
        function()
            local point = observe()
            account(driver.phase, point)
            local buttons, phase = driver.step(point)
            if buttons == nil then error(phase, 0) end
            return buttons, phase, point
        end,
        function(_, phase, frame)
            phases[#phases + 1] = {phase=phase, frame=frame, accepted=rec.accepted}
            if phase == "post_save" then
                local digest = SG.cart_digest(api)
                local bytes, snapshot = SG.flush(ctx, digest), U.saved_path(ctx.env.dir, ctx.case.name)
                local f = assert(io.open(snapshot, "wb"), "cannot write " .. snapshot)
                assert(f:write(bytes), "cannot write " .. snapshot)
                f:close()
                local c = profile.constants
                save = {frame=frame, saves=state.saves, cartram_sha256=digest, flushed=true,
                        party_hp_hex=hex(ctx.sym("wPartyMon1HP", 0, 2)), mon_hp=c.MON_HP}
            end
        end)
    api.unregister(handle)
    state.release()
    check("scripted " .. mode .. " route completed with normal buttons", played, not played and outcome or nil)
    check("checkpoint callback raised no error", #rec.errors == 0, rec.errors[1])

    local windows = {}
    for _, name in ipairs(rec.order) do
        local w, sets = rec.windows[name], json.array({})
        for _, key in ipairs(w.set_order) do
            local symbols = json.array({})
            for symbol in key:gmatch("[^,]+") do symbols[#symbols + 1] = symbol end
            sets[#sets + 1] = {symbols=symbols, frames=w.sets[key]}
        end
        windows[name] = {frames=w.frames, both_edges=w.both_edges, raw=w.raw, accepted=w.accepted,
                         edge_raw=w.edge_raw, refusals=json.object(w.reasons), failing_sets=sets,
                         write=w.write or json.null}
    end
    local scopes = json.array({})
    for scope in pairs(wrote_scopes) do scopes[#scopes + 1] = scope end
    table.sort(scopes)
    local persist = json.null
    if mode == "reload" and played then
        local cur = ctx.sym("wCurBox")[1]
        persist = {current_box=cur, party_hp_hex=hex(ctx.sym("wPartyMon1HP", 0, 2)),
                   active_box_hex=hex(api.read_range(flat, length, "CartRAM")),
                   backing_box_hex=hex(api.read_range(profile.storage_boxes[cur + 1].flat, length, "CartRAM"))}
        log("DUMP " .. json.encode(IG.dump(api, profile)))
    end
    local run = {schema=Safety.RUN_SCHEMA, mode=mode, title=title, evidence_level=evidence, result="FAIL",
        rom_sha1=ctx.env.rom_sha1, pack_commit=pack.source.commit, fixture=ctx.case.name,
        fixture_sha256=ctx.qualify.stage_fingerprint, attempt_id=ctx.case.attempt_id,
        qualification_attempt_id=ctx.u2.qualification_attempt_id, core_mode="CGB", input_mode="normal_buttons",
        harness_write_scopes=scopes,
        liveness={accepted=rec.accepted, raw=rec.raw, refused=rec.refused, other_bank=rec.other_bank,
                  refusals=json.object(rec.reasons), hits=json.array(rec.hits)},
        phases=json.array(phases), windows=json.object(windows), write=rec.write or json.null,
        save=save or json.null, boot_cartram_sha256=boot_digest or json.null, persist=persist,
        battle_model=model or json.null}

    -- The gate's own verdict: the SAME recomputation M.qualified runs on the receipt.
    if played then
        local problem = Safety.run_problem(run, mode, primary)
        check("run record proves the " .. mode .. " controls", problem == nil, problem)
        if mode == "battle" then
            local w = windows.battle or {}
            check("battle: faint_party_slot refuses the active slot as unqualified", type(w.write) == "table"
                  and tostring(w.write.faint_reason):find("active faint timing is not qualified", 1, true) ~= nil)
        end
    end
    run.result = failures == 0 and "PASS" or "FAIL"
    log("U2_RUN " .. json.encode(run))
    return finish()
end

-- ── card BOX: the box runs (boxes, boxes_reset, boxes_reload) ────────────────────────────────────
-- boxes   <title>_battle: two catches by the U1 inputs (lua/tests/gen2_frame_align.lua F.driver: walk the
--         Route 29 grass, Poke Ball, NO to the nickname, native SAVE; the O-10 ball stack is the fixture's
--         own), then the PRODUCTION executor (lua/gen2/boxes.lua B.executor, B.cart_gate) runs
--         Safety.BOX_OPS.boxes, one op per accepted checkpoint hold, and the CartRAM is flushed WITHOUT a
--         save (<case>.u2_reset.SaveRAM, U.reset_path): an unsaved active-sBox edit plus a backing sBox14 edit.
-- boxes_reset  that image cold-booted (the reset-before-save control): the party, active sBox, its
--         backing slot and sBox14 as CONTINUE left them, then Safety.BOX_OPS.boxes_reset and a native SAVE
--         (<case>.u2_saved.SaveRAM).
-- boxes_reload that save cold-booted: the persisted party, active sBox, backing slot and sBox14.
-- The executor's permits authorize only inside an accepted hold (TEST scope u2-box-ops); `written` is the
-- permit kind of every span in emission order (provenance, not a claim).
U.BOX_MODES = {boxes=true, boxes_reset=true, boxes_reload=true}
U.FRAME_ALIGN = "lua/tests/gen2_frame_align.lua"
U.PACK_KINDS = {"pack_items", "pack_balls", "pack_key", "pack_tmhm", "item_submenu"}
function U.reset_path(dir, case_name) return dir .. "/" .. case_name .. ".u2_reset.SaveRAM" end
function U.saved2_path(dir, case_name) return dir .. "/" .. case_name .. ".u2_saved2.SaveRAM" end

-- Pure driver for mode boxes: idle -> two F.driver catches (each ends in a native save) -> post_save ->
-- ops (the hook runs them) -> done. point adds accepted, party_count, ops_done.
function U.box_driver(F, map)
    local d = {terminal="done", phase="idle"}
    local catch, inner, base, mark, settle = 0, nil, nil, nil, false
    function d.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        local idle = point.overworld_ready == true and point.ui == nil
        if d.phase == "idle" then
            mark = mark or point.accepted
            if idle and point.accepted > mark then d.phase = "walk"; inner = nil end
            if d.phase == "idle" then return {}, d.phase end
        end
        if d.phase == "post_save" then
            if idle and point.accepted > mark then d.phase = "ops" end
            return {}, d.phase
        end
        if d.phase == "ops" then
            if point.ops_done then d.phase = d.terminal end
            return {}, d.phase
        end
        if d.phase == d.terminal then return {}, d.phase end
        if settle then
            if not idle then return {}, d.phase end
            settle = false
        end
        if inner == nil then
            catch, inner, base = catch + 1, F.driver(map), point.party_count
        end
        point.probe_hits = {capture_party = point.party_count - base}
        local buttons, phase = inner.step(point)
        if buttons == nil then return nil, "catch " .. catch .. ": " .. tostring(phase) end
        if inner.phase == inner.terminal then
            inner, settle = nil, true
            if catch == 2 then d.phase, mark = "post_save", point.accepted; return {}, d.phase end
            return {}, d.phase
        end
        d.phase = inner.phase
        return buttons, d.phase
    end
    return d
end

function U.box_main(e)
    local api, ctx, SG, IG, log, check, finish = e.api, e.ctx, e.SG, e.IG, e.log, e.check, e.finish
    local profile, mode, Safety, primary, json = e.profile, e.mode, e.Safety, e.primary, ctx.json
    local L = function(rel) return dofile(ctx.root .. "/" .. rel) end
    local Boxes, Writes, Reads, Rom, Wire = L("lua/gen2/boxes.lua"), L("lua/gen2/writes.lua"),
        L("lua/gen2/reads.lua"), L("lua/gen2/rom.lua"), L("lua/gen2/wire.lua")
    local F
    do
        local previous = SLINK_GEN2_GATE_LIBRARY
        SLINK_GEN2_GATE_LIBRARY = true
        local ok, lib = pcall(dofile, ctx.root .. "/" .. U.FRAME_ALIGN)
        SLINK_GEN2_GATE_LIBRARY = previous
        assert(ok and type(lib) == "table", "cannot load " .. U.FRAME_ALIGN .. ": " .. tostring(lib))
        F = lib
    end
    if mode == "boxes" then
        -- The U1 gate's pack-UI origins and catch prompt join this run's UI context before the hooks.
        local u1 = assert(json.decode(assert(e.getenv("SLINK_GEN2_U1_FACTS"), "SLINK_GEN2_U1_FACTS missing")))
        for _, kind in ipairs(U.PACK_KINDS) do ctx.facts.ui_origins[kind] = assert(u1.pack_ui[kind], "U1 facts lack " .. kind) end
        SG.MENU_KINDS.item_submenu = true
        local prompts = {}
        for k, v in pairs(ctx.obs.prompts) do prompts[k] = v end
        for k, v in pairs(ctx.prompts) do prompts[k] = v end
        for k, v in pairs(u1.prompts) do prompts[k] = v end
        ctx.prompts = prompts
    end
    local d, ram = profile.derived, profile.ram
    local boot_digest = mode ~= "boxes" and SG.cart_digest(api) or nil
    local arrived, detail, state = IG.arrive(ctx, SG)
    if not check("post-CONTINUE overworld arrival", arrived, detail) then
        state.release()
        return finish("no arrival")
    end

    -- The production executor behind TEST-scoped permits: authority = an accepted hold.
    local in_hold, wrote, written = false, false, {}
    local function effective_wram_bank()
        local v = api.read_u8(0xFF70, "System Bus") % 8
        return v == 0 and 1 or v
    end
    local io_ = {cart_ram_linear=true, read_u8=api.read_u8, domain_size=api.domain_size,
        read_range=function(a, n, dom) return api.read_range(a, n, dom) end,
        write_u8=function(a, v, dom) wrote = true; api.write_u8(a, v, dom) end,
        bank_valid=function(b, addr, n)
            if addr >= 0xC000 and addr + n <= 0xD000 then return b == 0 end
            return addr >= 0xD000 and addr + n <= 0xE000 and b == effective_wram_bank()
        end}
    local lifetime = {capture=api.framecount, valid=function(token) return token == api.framecount() end}
    local reads = assert(Reads.new(profile, io_))
    local writes = Writes.new(profile, io_, ctx.Permit, {
        authorize=function(op) return in_hold and op == "party_collection" end,
        pointer_stable=function() return true end, lifetime=lifetime,
        provenance=function() written[#written + 1] = "party_collection"
            return {site="lua/tests/gen2_write_windows.lua", scope="TEST-ONLY"} end})
    local gate = Boxes.cart_gate({Permit=ctx.Permit, profile=profile, io=io_, lifetime=lifetime,
        check=function() return in_hold end,
        provenance=function(_, _, _, reason) written[#written + 1] = tostring(reason):sub(5)
            return {site="lua/tests/gen2_write_windows.lua", scope="TEST-ONLY"} end})
    local pp, mail = {}, {}
    for _, move in ipairs(read_json(ctx, "data/games/gen2_" .. e.title .. "/moves.json").moves) do pp[move.id] = move.pp end
    for _, id in ipairs(read_json(ctx, "data/games/gen2_" .. e.title .. "/items.json").mail_ids) do mail[id] = true end
    local rom = Rom.new(profile, {read_u8=api.read_u8})
    local exec = Boxes.executor({profile=profile, reads=reads, key=Wire.mon_key, writes=writes,
        box=Boxes.new(profile, gate), io=io_, base_stats=rom.base_stats, move_pp=function(id) return pp[id] end,
        mail=mail, covers=function() return true end})

    local regions = {{flat=d.active_box_flat}}
    for _, row in ipairs(profile.storage_boxes) do regions[#regions + 1] = {flat=row.flat} end
    local function region(flat) return hex(api.read_range(flat, Safety.BOX_COPY, "CartRAM")) end
    local function party_hex() return hex(api.read_range(ram.wPartyCount, Safety.PARTY_BLOCK, "System Bus")) end
    local function snapshot_regions()
        local out = {}
        for i, r in ipairs(regions) do out[i] = region(r.flat) end
        return out
    end
    local cur = ctx.sym("wCurBox")[1]
    local layout = {active_flat=d.active_box_flat, memorial_flat=profile.storage_boxes[14].flat, current_box=cur}
    local function box_bytes()
        return {party_hex=party_hex(), active_hex=region(d.active_box_flat),
                backing_hex=region(profile.storage_boxes[cur + 1].flat), memorial_hex=region(layout.memorial_flat)}
    end
    local control = mode == "boxes_reset" and box_bytes() or nil
    local party_before = ctx.sym("wPartyCount")[1]

    local want = Safety.BOX_OPS[mode] or {}
    local rec = {accepted=0, raw=0, refused=0, other_bank=0, reasons={}, hits={}, errors={}}
    local ops, keys, driver = {}, nil, nil
    local function run_op()
        local w = want[#ops + 1]
        if (w.stage or 1) ~= (driver.stage or 1) then return end
        if keys == nil then
            local party = assert(reads.read_party())
            assert(#party.mons == 3, "the ops need the lead and two catches in the party")
            keys = {assert(Wire.mon_key(party.mons[2])), assert(Wire.mon_key(party.mons[3]))}
        end
        local before, pb = snapshot_regions(), party_hex()
        written = {}
        in_hold = true
        local ok, why = exec[w.op](keys[w.key], w.defer and {defer_backing=true} or nil)
        in_hold = false
        local after, changed = snapshot_regions(), json.array({})
        for i, r in ipairs(regions) do
            if after[i] ~= before[i] then changed[#changed + 1] = {flat=r.flat, before_hex=before[i], after_hex=after[i]} end
        end
        local kinds = json.array({})
        for _, k in ipairs(written) do kinds[#kinds + 1] = k end
        ops[#ops + 1] = {op=w.op, key=keys[w.key], ok=ok == true, reason=why or json.null, frame=api.framecount(),
                         stage=w.stage or 1, deferred=w.defer == true and ok == true and why ~= nil,
                         written=kinds, party_before_hex=pb, party_after_hex=party_hex(), changed=changed}
        if ok ~= true then log("  op " .. #ops .. " " .. w.op .. " refused: " .. tostring(why)) end
    end
    local function on_checkpoint()
        local fine, err = pcall(function()
            local hit_bank = api.read_u8(e.HROM, "System Bus")
            if hit_bank ~= e.bank then rec.other_bank = rec.other_bank + 1; return end
            rec.raw = rec.raw + 1
            local report = e.checkpoint:inspect_candidate()
            if report.candidate_match ~= true then
                rec.refused = rec.refused + 1
                rec.reasons[report.reason] = (rec.reasons[report.reason] or 0) + 1
                return
            end
            rec.accepted = rec.accepted + 1
            if #rec.hits < 8 then rec.hits[#rec.hits + 1] = {frame=api.framecount(), pc=api.register("PC"), bank=hit_bank} end
            if driver and driver.phase == "ops" and #ops < #want and (#ops == 0 or ops[#ops].ok) then run_op() end
        end)
        in_hold = false
        if not fine and #rec.errors < 8 then rec.errors[#rec.errors + 1] = tostring(err) end
    end
    local handle = api.on_bus_exec(on_checkpoint, primary.execution_before.pc, "SLink-gen2-u2-box-checkpoint", "System Bus")

    local base = SG.qualify_observer(ctx)
    local function observe()
        local point = base()
        point.accepted, point.party_count = rec.accepted, ctx.sym("wPartyCount")[1]
        local stage = driver and driver.stage or 1
        local next_op = want[#ops + 1]
        point.ops_done = next_op == nil or (next_op.stage or 1) > stage or (#ops > 0 and not ops[#ops].ok)
        if point.ui and point.ui.kind == "pack_balls" then point.ball_cursor = F.ball_cursor(SG.screen(ctx)) end
        if point.ui and point.ui.kind == "battle_menu" then
            local menu = SG.parse_menu(SG.screen(ctx), ctx.obs.screen.width, ctx.obs.screen.height, SG.BATTLE_MENU_GRID)
            if menu then point.ui.items, point.ui.cursor, point.ui.columns = menu.items, menu.cursor, menu.columns
            else point.input_ready = false end
        end
        return point
    end
    driver = mode == "boxes" and U.box_driver(F, ctx.facts.maps.Route29) or U.driver(mode, ctx.facts.maps)
    local idle = {}
    for _, name in ipairs(SG.BUTTONS) do idle[name] = false end
    local host = ctx.Host.new({step=SG.button_step(ctx), frame=api.framecount, idle=idle})
    local phases, save, save2, reset, catch = {}, nil, nil, nil, nil
    local function keep(path)
        local digest = SG.cart_digest(api)
        local bytes = SG.flush(ctx, digest)
        local f = assert(io.open(path, "wb"), "cannot write " .. path)
        assert(f:write(bytes), "cannot write " .. path)
        f:close()
        return {cartram_sha256=digest, flushed=true, frame=api.framecount()}
    end
    local played, outcome = pcall(host.run, {name="u2-" .. mode, terminal=driver.terminal,
        max_frames=U.BUDGET.max_frames * 2, max_phase_frames=24000, settle_frames=30, terminal_idle=true},
        function(frame)
            local point = observe()
            local buttons, phase = driver.step(point)
            if buttons == nil then
                log(F.state_line("stall", frame, driver.phase, point, "-"))
                local shown, rows = pcall(SG.screen, ctx)
                if shown then for y, row in ipairs(rows) do log(fmt("  screen %02d |%s|", y, table.concat(row))) end end
                error(phase, 0)
            end
            return buttons, phase, point
        end,
        function(_, phase, frame)
            phases[#phases + 1] = {phase=phase, frame=frame, accepted=rec.accepted}
            if phase == "post_save" and save == nil then
                save = keep(U.saved_path(ctx.env.dir, ctx.case.name))
                catch = {party_before=party_before, party_after=ctx.sym("wPartyCount")[1]}
            elseif phase == "post_save" then
                save2 = keep(U.saved2_path(ctx.env.dir, ctx.case.name))
            elseif phase == "done" and (mode == "boxes" or mode == "boxes_reset") then
                reset = keep(U.reset_path(ctx.env.dir, ctx.case.name))   -- NO save: the reset control image
            end
        end)
    api.unregister(handle)
    state.release()
    check("scripted " .. mode .. " route completed with normal buttons", played, not played and outcome or nil)
    check("checkpoint callback raised no error", #rec.errors == 0, rec.errors[1])
    local run = {schema=Safety.RUN_SCHEMA, mode=mode, title=e.title, evidence_level=e.evidence, result="FAIL",
        rom_sha1=ctx.env.rom_sha1, pack_commit=e.pack.source.commit, fixture=ctx.case.name,
        fixture_sha256=ctx.qualify.stage_fingerprint, attempt_id=ctx.case.attempt_id,
        qualification_attempt_id=ctx.u2.qualification_attempt_id, core_mode="CGB", input_mode="normal_buttons",
        harness_write_scopes=json.array(wrote and {"u2-box-ops"} or {}),
        liveness={accepted=rec.accepted, raw=rec.raw, refused=rec.refused, other_bank=rec.other_bank,
                  refusals=json.object(rec.reasons), hits=json.array(rec.hits)},
        phases=json.array(phases), windows=json.object({}), layout=layout, ops=json.array(ops),
        save=save or json.null, save2=save2 or json.null, reset=reset or json.null,
        catch=mode == "boxes" and catch or json.null,
        control=control or json.null, boot_cartram_sha256=boot_digest or json.null,
        persist=(mode == "boxes_reload" and played) and box_bytes() or json.null}
    if played then
        local problem = Safety.run_problem(run, mode, primary)
        check("run record proves the " .. mode .. " controls", problem == nil, problem)
    end
    if mode == "boxes_reload" and played then log("DUMP " .. json.encode(IG.dump(api, profile))) end
    run.result = e.failures() == 0 and "PASS" or "FAIL"
    log("U2_RUN " .. json.encode(run))
    return finish()
end

-- ── card O-30: the in-battle faint (battle_faint) ─────────────────────────────────────────────────────
-- battle_faint  <title>_battle: ONE catch by the U1 inputs (F.driver: walk the Route 29 grass, Poke Ball, NO to
--         the nickname, native SAVE), then the grass again into a second wild battle, fought with a status move
--         (FIGHT, never RUN). The pack's battle hold (write_checkpoint.json battle_hold: BattleTurn before
--         `call DetermineMoveOrder`) is hooked; inside the FIRST accepted hold of that battle the harness kills
--         the BENCH mon (the catch; lua/gen2/writes.lua faint_party_slot), inside the NEXT one the ACTIVE lead,
--         now the last able mon (faint_active_battler: battle HP 0, the party mirror, wBattlePlayerAction =
--         USEITEM LAST). Observation-only hooks at the pack's oracles (HandlePlayerMonFaint, LostBattle, the
--         foe's EnemyTurn_EndOpponentProtectEndureDestinyBond) stamp the engine order (seq). The native faint
--         and whiteout run; liveness after the warp. TEST scope u2-battle-faint; authority = an accepted hold.
U.BF_PASSIVE = {"GROWL", "LEER", "TAIL WHIP", "SAND-ATTACK", "DEFENSE CURL", "FORESIGHT", "SPLASH"}
U.BF_ORACLES = {HandlePlayerMonFaint="faint", LostBattle="lost", EnemyTurn_EndOpponentProtectEndureDestinyBond="enemy_turn"}
U.BF_TRACE = 64

-- Pure driver: idle -> catch (F.driver) -> hunt -> battle -> post_battle -> done.
function U.battle_faint_driver(F, map)
    local d = {terminal="done", phase="idle"}
    local HOLD, held, hold_left, release = 12, nil, 0, false
    local inner, base, mark, settle, here, from = nil, nil, nil, false, nil, nil
    local function press(button)
        release, held, hold_left = true, button, HOLD - 1
        return {[button]=true}, d.phase
    end
    local function choose(ui, wanted, columns)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local target
        for index, label in ipairs(ui.items) do
            if type(label) == "string" and label:upper() == wanted then
                if target then return nil, "ambiguous menu label" end
                target = index
            end
        end
        if not target then return nil, "required native menu item missing: " .. wanted end
        if target == ui.cursor then return press("A") end
        local tx, cx = (target - 1) % columns, (ui.cursor - 1) % columns
        if tx ~= cx then return press(tx > cx and "Right" or "Left") end
        return press(target > ui.cursor and "Down" or "Up")
    end
    function d.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        local idle = point.overworld_ready == true and point.ui == nil
        if d.phase == "idle" then
            mark = mark or point.accepted
            if idle and point.accepted > mark then d.phase = "catch" end
            return {}, d.phase
        end
        if d.phase == "catch" then
            if inner == nil then inner, base = F.driver(map), point.party_count end
            point.probe_hits = {capture_party = point.party_count - base}
            local buttons, phase = inner.step(point)
            if buttons == nil then return nil, "catch: " .. tostring(phase) end
            if inner.phase == inner.terminal then d.phase, settle = "hunt", true end
            return buttons, d.phase
        end
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, d.phase end
        if release then release = false; return {}, d.phase end
        if d.phase == d.terminal then return {}, d.phase end
        local ui, ready = point.ui, point.input_ready == true
        if d.phase == "hunt" then
            if integer(point.battle_mode, 1, 255) then d.phase = "battle"; return {}, d.phase end
            if not idle then return {}, d.phase end
            settle = false
            if here and (here.x ~= point.x or here.y ~= point.y) then from = here end
            here = {x=point.x, y=point.y}
            local button, why = F.walk_direction(map, point, from)
            if not button then return nil, why end
            return {[button]=true}, d.phase
        elseif d.phase == "battle" then
            if point.battle_mode == 0 then
                -- the whiteout: Script_BattleWhiteout's text in the overworld, then the warp
                if idle then mark = point.accepted; d.phase = "post_battle"; return {}, d.phase end
                if ui ~= nil and ready and U.TEXT_KINDS[ui.kind] then return press("A") end
                return {}, d.phase
            end
            if ui == nil or not ready then return {}, d.phase end
            if ui.kind == "battle_menu" then return choose(ui, "FIGHT", 2) end
            if ui.kind == "move_menu" then
                if type(ui.items) ~= "table" then return nil, "move list unreadable" end
                for _, name in ipairs(U.BF_PASSIVE) do
                    for _, label in ipairs(ui.items) do
                        if type(label) == "string" and label:upper() == name then return choose(ui, name, 1) end
                    end
                end
                return nil, "the lead knows no status move"
            end
            if U.TEXT_KINDS[ui.kind] then return press("A") end
            return nil, "UI is not valid in the battle: " .. tostring(ui.kind) .. "/" .. tostring(ui.prompt)
        elseif d.phase == "post_battle" then
            if idle and point.accepted > mark then d.phase = d.terminal end
            return {}, d.phase
        end
        return nil, "unknown phase " .. tostring(d.phase)
    end
    return d
end

function U.battle_faint_main(e)
    local api, ctx, SG, IG, log, check, finish = e.api, e.ctx, e.SG, e.IG, e.log, e.check, e.finish
    local profile, Safety, primary, json = e.profile, e.Safety, e.primary, ctx.json
    local hold = assert(e.pack.titles[e.title].battle_hold, "pack battle_hold missing")
    local L = function(rel) return dofile(ctx.root .. "/" .. rel) end
    local Writes = L("lua/gen2/writes.lua")
    local F
    do
        local previous = SLINK_GEN2_GATE_LIBRARY
        SLINK_GEN2_GATE_LIBRARY = true
        local ok, lib = pcall(dofile, ctx.root .. "/" .. U.FRAME_ALIGN)
        SLINK_GEN2_GATE_LIBRARY = previous
        assert(ok and type(lib) == "table", "cannot load " .. U.FRAME_ALIGN .. ": " .. tostring(lib))
        F = lib
    end
    -- The U1 facts: pack UI + catch prompt for the catch, the move/party UI origins for the fight.
    local u1 = assert(json.decode(assert(e.getenv("SLINK_GEN2_U1_FACTS"), "SLINK_GEN2_U1_FACTS missing")))
    for _, kind in ipairs(U.PACK_KINDS) do ctx.facts.ui_origins[kind] = assert(u1.pack_ui[kind], "U1 facts lack " .. kind) end
    SG.MENU_KINDS.item_submenu = true
    local prompts = {}
    for k, v in pairs(ctx.obs.prompts) do prompts[k] = v end
    for k, v in pairs(ctx.prompts) do prompts[k] = v end
    for k, v in pairs(u1.prompts) do prompts[k] = v end
    ctx.prompts = prompts
    local FI = L(F.FAINT_INPUTS)
    FI.prepare(ctx, SG, u1)

    local arrived, detail, state = IG.arrive(ctx, SG)
    if not check("post-CONTINUE overworld arrival", arrived, detail) then
        state.release()
        return finish("no arrival")
    end

    local in_hold, wrote = false, false
    local function effective_wram_bank()
        local v = api.read_u8(0xFF70, "System Bus") % 8
        return v == 0 and 1 or v
    end
    local io_ = {write_u8=function(a, v, dom) wrote = true; api.write_u8(a, v, dom) end,
        bank_valid=function(b, addr, n)
            if addr >= 0xC000 and addr + n <= 0xD000 then return b == 0 end
            return addr >= 0xD000 and addr + n <= 0xE000 and b == effective_wram_bank()
        end}
    local lifetime = {capture=api.framecount, valid=function(token) return token == api.framecount() end}
    local writes = Writes.new(profile, io_, ctx.Permit, {
        authorize=function(op) return in_hold and op == "battle_faint" end,
        pointer_stable=function() return true end, lifetime=lifetime,
        provenance=function() return {site="lua/tests/gen2_write_windows.lua", scope="TEST-ONLY"} end}, hold.write)

    local seq, driver = 0, nil
    local rec = {accepted=0, raw=0, refused=0, other_bank=0, reasons={}, hits={}, errors={}}
    local bh = {accepted=0, raw=0, refused=0, other_bank=0, reasons={}, hits={}}
    local bw, trace = {}, {}
    local function on_checkpoint()
        local fine, err = pcall(function()
            local hit_bank = api.read_u8(e.HROM, "System Bus")
            if hit_bank ~= e.bank then rec.other_bank = rec.other_bank + 1; return end
            rec.raw = rec.raw + 1
            local report = e.checkpoint:inspect_candidate()
            if report.candidate_match ~= true then
                rec.refused = rec.refused + 1
                rec.reasons[report.reason] = (rec.reasons[report.reason] or 0) + 1
                return
            end
            rec.accepted = rec.accepted + 1
            if #rec.hits < 8 then rec.hits[#rec.hits + 1] = {frame=api.framecount(), pc=api.register("PC"), bank=hit_bank} end
        end)
        if not fine and #rec.errors < 8 then rec.errors[#rec.errors + 1] = tostring(err) end
    end
    local targets = hold.write.targets
    local function byte_hex(name, n)
        return hex(api.read_range(targets[name].address, n, "System Bus"))
    end
    -- One write inside an accepted battle hold: the bench (the catch) first, then the active lead.
    local function battle_write(frame)
        local active = ctx.sym("wCurBattleMon")[1]
        local slot = #bw == 0 and (active == 0 and 1 or 0) or active
        local off = slot * profile.constants.PARTYMON_STRUCT_LENGTH
        local c = profile.constants
        local r = {seq=seq, frame=frame, slot=slot, active_slot=active,
                   status_before_hex=hex(ctx.sym("wPartyMon1", off + c.MON_STATUS, 1)),
                   hp_before_hex=hex(ctx.sym("wPartyMon1", off + c.MON_HP, 2)),
                   battle_hp_before_hex=byte_hex("wBattleMonHP", 2), action_before_hex=byte_hex("wBattlePlayerAction", 1)}
        local snapshot = {mode=ctx.sym("wBattleMode")[1], battle_type=ctx.sym("wBattleType")[1], active_slot=active,
                          link_mode=api.read_u8(ctx.profile.ram.wLinkMode, "System Bus")}
        in_hold = true
        local ok, why = pcall(function()
            writes:arm("battle_hold")
            if slot == active then writes:faint_active_battler(slot, snapshot) else writes:faint_party_slot(slot, snapshot) end
        end)
        writes:disarm()
        in_hold = false
        r.ok, r.reason = ok, ok and json.null or tostring(why)
        r.status_after_hex = hex(ctx.sym("wPartyMon1", off + c.MON_STATUS, 1))
        r.hp_after_hex = hex(ctx.sym("wPartyMon1", off + c.MON_HP, 2))
        r.battle_hp_after_hex, r.action_after_hex = byte_hex("wBattleMonHP", 2), byte_hex("wBattlePlayerAction", 1)
        bw[#bw + 1] = r
        if not ok then log("  battle write " .. #bw .. " refused: " .. tostring(why)) end
    end
    local hb = hold.execution_before.bank
    local function on_battle_hold()
        local fine, err = pcall(function()
            local hit_bank = api.read_u8(e.HROM, "System Bus")
            if hit_bank ~= hb then bh.other_bank = bh.other_bank + 1; return end
            bh.raw = bh.raw + 1
            local report = e.checkpoint:inspect_candidate("battle_hold")
            if report.candidate_match ~= true then
                bh.refused = bh.refused + 1
                bh.reasons[report.reason] = (bh.reasons[report.reason] or 0) + 1
                return
            end
            bh.accepted, seq = bh.accepted + 1, seq + 1
            if #bh.hits < 8 then bh.hits[#bh.hits + 1] = {frame=api.framecount(), pc=api.register("PC"), bank=hit_bank, seq=seq} end
            if driver and driver.phase == "battle" and #bw < 2 and (#bw == 0 or bw[1].ok) then battle_write(api.framecount()) end
        end)
        in_hold = false
        if not fine and #rec.errors < 8 then rec.errors[#rec.errors + 1] = "battle hold: " .. tostring(err) end
    end
    local handles = {api.on_bus_exec(on_checkpoint, primary.execution_before.pc, "SLink-gen2-u2-bf-checkpoint", "System Bus"),
                     api.on_bus_exec(on_battle_hold, hold.execution_before.pc, "SLink-gen2-u2-bf-hold", "System Bus")}
    for name, what in pairs(U.BF_ORACLES) do
        local o = assert(hold.oracles[name], "pack oracle missing: " .. name)
        local want = {}
        for i = 1, #o.expected_hex, 2 do want[#want + 1] = tonumber(o.expected_hex:sub(i, i + 1), 16) end
        handles[#handles + 1] = api.on_bus_exec(function()
            if not driver or driver.phase ~= "battle" or #trace >= U.BF_TRACE then return end
            if api.read_u8(e.HROM, "System Bus") ~= o.bank then return end
            local live = api.read_range(o.address, #want, "System Bus")
            for i = 1, #want do if live[i] ~= want[i] then return end end
            seq = seq + 1
            trace[#trace + 1] = {seq=seq, what=what, frame=api.framecount()}
        end, o.address, "SLink-gen2-u2-bf-" .. what, "System Bus")
    end

    local base = SG.qualify_observer(ctx)
    local function observe()
        local point = base()
        point.accepted, point.party_count = rec.accepted, ctx.sym("wPartyCount")[1]
        if point.ui and point.ui.kind == "pack_balls" then point.ball_cursor = F.ball_cursor(SG.screen(ctx)) end
        if point.ui and point.ui.kind == "battle_menu" then
            local menu = SG.parse_menu(SG.screen(ctx), ctx.obs.screen.width, ctx.obs.screen.height, SG.BATTLE_MENU_GRID)
            if menu then point.ui.items, point.ui.cursor, point.ui.columns = menu.items, menu.cursor, menu.columns
            else point.input_ready = false end
        end
        if point.ui and point.ui.kind == "move_menu" then
            local list = FI.move_list(SG.screen(ctx))
            if list then point.ui.items, point.ui.cursor, point.ui.columns = list.items, list.cursor, list.columns
            else point.input_ready = false end
        end
        return point
    end
    driver = U.battle_faint_driver(F, ctx.facts.maps.Route29)
    local party_before = ctx.sym("wPartyCount")[1]
    local catch
    local idle = {}
    for _, name in ipairs(SG.BUTTONS) do idle[name] = false end
    local host = ctx.Host.new({step=SG.button_step(ctx), frame=api.framecount, idle=idle})
    local phases = {}
    local played, outcome = pcall(host.run, {name="u2-battle_faint", terminal=driver.terminal,
        max_frames=U.BUDGET.max_frames * 2, max_phase_frames=24000, settle_frames=30, terminal_idle=true},
        function(frame)
            local point = observe()
            local buttons, phase = driver.step(point)
            if buttons == nil then
                log(F.state_line("stall", frame, driver.phase, point, "-"))
                local shown, rows = pcall(SG.screen, ctx)
                if shown then for y, row in ipairs(rows) do log(fmt("  screen %02d |%s|", y, table.concat(row))) end end
                error(phase, 0)
            end
            return buttons, phase, point
        end,
        function(_, phase, frame)
            phases[#phases + 1] = {phase=phase, frame=frame, accepted=rec.accepted}
            if phase == "hunt" and catch == nil then catch = {party_before=party_before, party_after=ctx.sym("wPartyCount")[1]} end
        end)
    for _, handle in ipairs(handles) do api.unregister(handle) end
    state.release()
    check("scripted battle_faint route completed with normal buttons", played, not played and outcome or nil)
    check("hook callbacks raised no error", #rec.errors == 0, rec.errors[1])
    local run = {schema=Safety.RUN_SCHEMA, mode="battle_faint", title=e.title, evidence_level=e.evidence, result="FAIL",
        rom_sha1=ctx.env.rom_sha1, pack_commit=e.pack.source.commit, fixture=ctx.case.name,
        fixture_sha256=ctx.qualify.stage_fingerprint, attempt_id=ctx.case.attempt_id,
        qualification_attempt_id=ctx.u2.qualification_attempt_id, core_mode="CGB", input_mode="normal_buttons",
        harness_write_scopes=json.array(wrote and {"u2-battle-faint"} or {}),
        liveness={accepted=rec.accepted, raw=rec.raw, refused=rec.refused, other_bank=rec.other_bank,
                  refusals=json.object(rec.reasons), hits=json.array(rec.hits)},
        phases=json.array(phases), windows=json.object({}),
        battle_hold={accepted=bh.accepted, raw=bh.raw, refused=bh.refused, other_bank=bh.other_bank,
                     refusals=json.object(bh.reasons), hits=json.array(bh.hits)},
        battle_writes=json.array(bw), trace=json.array(trace), catch=catch or json.null}
    if played then
        local problem = Safety.run_problem(run, "battle_faint", primary, hold)
        check("run record proves the battle_faint controls", problem == nil, problem)
    end
    run.result = e.failures() == 0 and "PASS" or "FAIL"
    log("U2_RUN " .. json.encode(run))
    return finish()
end

-- ── card gen2-hello-flap: the PRODUCTION client (lua/gen2/run.lua, unmodified) across a wild battle ─────
-- hello   <title>_battle: arrival, then run.lua is loaded with a counting stand-in transport (always
--         connected; every line it is handed is recorded) and a no-op HUD, so the production graph hellos
--         at its own checkpoint hold; then the battle inputs (walk the grass, stay in the battle, RUN).
--         Evidence: HELLO frames (exactly one), battle frames, and the frames whose frame-end SVBK was not 1
--         (the known-positive control: the mapping flip that made the client re-hello, C
--         engine/battle_anims/anim_commands.asm:1413, bg_effects.asm:2562,2589).
function U.hello_main(e)
    local api, ctx, SG, IG, log, check, finish = e.api, e.ctx, e.SG, e.IG, e.log, e.check, e.finish
    local arrived, detail, state = IG.arrive(ctx, SG)
    if not check("post-CONTINUE overworld arrival", arrived, detail) then
        state.release()
        return finish("no arrival")
    end
    local lines, frames = {}, {}
    package.loaded.connector = {init=function() end, pump=function() end, receive=function() return nil end,
        connected=function() return true end, disconnect=function() end,
        send=function(line)
            lines[#lines + 1] = line
            if line:find('"event":"hello"', 1, true) then frames[#frames + 1] = api.framecount() end
            return true
        end}
    package.loaded.hud = setmetatable({}, {__index=function() return function() end end})
    SLINK_PLAYER = "a"
    local loaded, why = pcall(dofile, ctx.root .. "/lua/gen2/run.lua")
    if not check("production client admitted and started", loaded and SLINK_GEN2_CLIENT ~= nil, why) then
        state.release()
        return finish("no client")
    end
    local battle_frames, off_bank, battle_hellos = 0, 0, 0
    local base = SG.qualify_observer(ctx)
    local driver = U.driver("battle", ctx.facts.maps)
    local stay = 0
    local function observe()
        local point = base()
        -- the driver's liveness clock: frames since the client's own hello (sent at ITS checkpoint hold)
        point.accepted = #frames >= 1 and api.framecount() - frames[1] + 1 or 0
        point.map_status, point.game_paused = 2, 0
        if integer(point.battle_mode, 1, 255) then
            battle_frames, stay = battle_frames + 1, stay + 1
            if api.read_u8(0xFF70, "System Bus") % 8 > 1 then off_bank = off_bank + 1 end
        end
        point.window_frames, point.battle_attempted = stay, stay >= 600   -- ~10 s in the battle, then RUN
        if point.ui and point.ui.kind == "battle_menu" then
            local menu = SG.parse_menu(SG.screen(ctx), ctx.obs.screen.width, ctx.obs.screen.height, SG.BATTLE_MENU_GRID)
            if menu then point.ui.items, point.ui.cursor, point.ui.columns = menu.items, menu.cursor, menu.columns
            else point.input_ready = false end
        end
        return point
    end
    local idle = {}
    for _, name in ipairs(SG.BUTTONS) do idle[name] = false end
    local host = ctx.Host.new({step=SG.button_step(ctx), frame=api.framecount, idle=idle})
    local played, outcome = pcall(host.run, {name="hello-" .. e.title, terminal=driver.terminal,
        max_frames=U.BUDGET.max_frames, max_phase_frames=U.BUDGET.max_phase_frames, settle_frames=30,
        terminal_idle=true}, function()
            local point = observe()
            local buttons, phase = driver.step(point)
            if buttons == nil then error(phase, 0) end
            return buttons, phase, point
        end)
    state.release()
    if SLINK_GEN2_CLIENT then pcall(function() SLINK_GEN2_CLIENT:stop() end) end
    local record = {hello_frames=ctx.json.array(frames), sent=#lines, battle_frames=battle_frames,
                    off_bank_battle_frames=off_bank}
    log("HELLO_COUNT " .. ctx.json.encode(record))
    check("walk -> wild battle -> RUN -> overworld", played, not played and outcome or nil)
    check("the battle ran with WRAMX unmapped at frame end (the flap condition occurred)", off_bank > 0, off_bank)
    check("exactly one hello across the battle", #frames == 1, #frames)
    return finish()
end

if SLINK_GEN2_GATE_LIBRARY then return U end

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset -- launch via tools/run_gb_gate.py")
local IG = U.inspect_gate(ROOT)
local SG = IG.scripted_gate(ROOT)
local api = SG.bizhawk()
live_api = api
api.domains = function() return memory.getmemorydomainlist() end
U.main(api, os.getenv, SG, IG)
api.exit()
error("slink-gate-finished", 0)   -- client.exit() is asynchronous; stop here for real
