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

  Modes (SLINK_GEN2_U2 = {"mode": ...}):
    town    <title>_town (Elm's lab). idle: party HP-1 (writes.lua) + a current-box deposit of the lead
            mon into the AUTHORITATIVE sBox copy in CartRAM (boxes.lua, owner "active"), both in one
            accepted hold, with the SRAM-closed bus view recorded. Then START menu (refused: the anchor
            does not fire; the 15 predicates are recorded), Elm's script text box (refused:
            wScriptRunning/wScriptFlags), a native SAVE (wGameLogicPaused window if the frame end sees
            it), SaveRAM flushed, then the lab exit warp (refused: wMapStatus) and liveness in New Bark.
    reload  the town run's flushed SaveRAM, cold-booted: CONTINUE, liveness, DUMP (party + CartRAM).
    battle  <title>_battle (Route 29 grass): liveness, walk the grass until a wild battle (bounded), the
            battle window (refused: wBattleMode; a party-only write to the ACTIVE slot is refused and
            faint_party_slot refuses the active slot -- UpdateBattleMonInParty copies the battle struct
            back, so an in-battle KO must target wBattleMonHP: MODEL-only, recorded as U2_BATTLE_MODEL),
            RUN, liveness after the battle.
  A window's accepted anchor hits count only for frames whose START and END both lie inside the window
  (a hold accepted just before a warp begins is idle by construction).

  Printed (JSON after the tag): U2_WRITE, U2_WINDOWS, U2_LIVENESS, U2_SAVE, U2_BATTLE_MODEL, U2_PHASES,
  DUMP (reload). tests/live/test_gen2_write_windows.py re-derives the verdict and writes the receipt.
--]]
local U = {}
U.RESULT = "patch/build/gen2_write_windows_result.txt"
U.INSPECT_GATE = "lua/tests/gen2_inspect_gate.lua"
-- ponytail: live budgets and the per-window observation length, not measured; raise if a run needs longer.
U.OBSERVE = 30
U.BUDGET = {max_frames=60000, max_phase_frames=15000, settle_frames=4}
U.TEXT_KINDS = {text=true, prompt_button=true, wait_button=true}
U.MODES = {town="town", battle="battle", reload="town"}   -- mode -> required fixture target
U.DIRECTIONS = {{"Up", 0, -1}, {"Left", -1, 0}, {"Down", 0, 1}, {"Right", 1, 0}}
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

-- Pure: first step of a BFS over the source grid toward (goal.x, goal.y); "arrived" on the goal.
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
    local queue, head, seen = {{point.x, point.y, false}}, 1, {[key(point.x, point.y)] = true}
    while head <= #queue do
        local node = queue[head]; head = head + 1
        for _, d in ipairs(U.DIRECTIONS) do
            local x, y = node[1] + d[2], node[2] + d[3]
            if x >= 0 and x < map.width and y >= 0 and y < map.height then
                local index, first = key(x, y), node[3] or d[1]
                if not seen[index] and map.grid[index] ~= 0 and not blocked[index]
                   and (node[3] or point.can_step[d[1]] == true) then
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
    for _, d in ipairs(U.DIRECTIONS) do
        local x, y = point.x + d[2], point.y + d[3]
        if x >= 0 and x < map.width and y >= 0 and y < map.height and map.grid[y * map.width + x + 1] == 2
           and point.can_step[d[1]] == true and not blocked[y * map.width + x] then
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
    local d = {terminal="done", phase="idle"}
    -- A native press is HELD 12 frames (gen2_qualify.lua HOLD); overworld walking holds per frame.
    local HOLD, held, hold_left, release = 12, nil, 0, false
    local mark, save_counter, confirmed, waited, here, from = 0, nil, false, 0, nil, nil
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
            if mode == "reload" then go("done"); return {}, d.phase end
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
        elseif p == "post_save" then
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

function U.main(api, getenv, SG, IG)
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

    -- The ONLY authority for a harness write: an accepted hold, inside the checkpoint callback.
    local in_hold = false
    local lifetime = {capture=api.framecount, valid=function(token) return token == api.framecount() end}
    local writes = Writes.new(profile, {
        write_u8=function(addr, value, domain) api.write_u8(addr, value, domain) end,
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
        write_u8=function(addr, value) api.write_u8(addr, value, "CartRAM") end,
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
            box_permit:scope("u2-test-box-write", nil, function()
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
        writes:arm("u2-test-party-write")
        writes:write_party_bytes(0, c.MON_HP, written)
        writes:disarm()
        local cur, saved = ctx.sym("wCurBox")[1], ctx.sym("wSavedAtLeastOnce")[1]
        local before = api.read_range(flat, length, "CartRAM")
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
                    backing_flat=profile.storage_boxes[cur + 1].flat, owner=plan.owner,
                    count_before=before[1], count_after=plan.after[1], before_hex=hex(before),
                    after_hex=hex(plan.after), readback_hex=hex(api.read_range(flat, length, "CartRAM")),
                    bus={address=bus_address, value=bus_value, cartram_value=before[1]}}}
    end

    local arrived, detail, state = IG.arrive(ctx, SG)
    if not check("post-CONTINUE overworld arrival", arrived, detail) then
        state.release()
        return finish("no arrival")
    end

    local rec = {accepted=0, seen=0, other_bank=0, refused=0, reasons={}, distinct=0, windows={}, order={}, errors={},
                 pending=mode == "town", write=nil, prev=nil}
    local function on_checkpoint()
        local fine, err = pcall(function()
            if api.read_u8(HROM, "System Bus") ~= bank then rec.other_bank = rec.other_bank + 1; return end
            local report = checkpoint:inspect_candidate()
            if report.candidate_match ~= true then
                rec.refused = rec.refused + 1
                if rec.reasons[report.reason] or rec.distinct < 16 then   -- bounded distinct reasons
                    if not rec.reasons[report.reason] then rec.distinct = rec.distinct + 1 end
                    rec.reasons[report.reason] = (rec.reasons[report.reason] or 0) + 1
                end
                return
            end
            rec.accepted = rec.accepted + 1
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

    -- A refused-write attempt outside any hold, through the SAME writer and authorize policy.
    local function attempt(window, slot, battle)
        local base = profile.ram.wPartyMon1HP + slot * profile.constants.PARTYMON_STRUCT_LENGTH - profile.ram.wPartyMon1
        local before = ctx.sym("wPartyMon1", base, 2)
        local wrote, why = pcall(function()
            writes:arm("u2-negative-" .. window)
            writes:write_party_bytes(slot, profile.constants.MON_HP, {0, 1})
        end)
        writes:disarm()
        local out = {slot=slot, refused=not wrote, reason=tostring(why),
                     party_unchanged=hex(ctx.sym("wPartyMon1", base, 2)) == hex(before)}
        if battle then
            local snapshot = {mode=ctx.sym("wBattleMode")[1], link_mode=pred_read(rows.wLinkMode.address),
                              battle_type=ctx.sym("wBattleType")[1], active_slot=slot}
            local fainted, faint_why = pcall(function()
                writes:arm("u2-negative-battle-faint")
                writes:faint_party_slot(slot, snapshot)
            end)
            writes:disarm()
            out.faint_refused, out.faint_reason = not fainted, tostring(faint_why)
            out.party_unchanged = out.party_unchanged and hex(ctx.sym("wPartyMon1", base, 2)) == hex(before)
        end
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
        local hits = rec.accepted - rec.seen
        rec.seen = rec.accepted
        if name and rec.prev == name then rec.windows[name].accepted = rec.windows[name].accepted + hits end
        rec.prev = name
        if not name then return end
        local w = rec.windows[name]
        if not w then
            w = {frames=0, accepted=0, failing={}}
            rec.windows[name] = w
            rec.order[#rec.order + 1] = name
        end
        w.frames = w.frames + 1
        for _, symbol in ipairs(Safety.failing_predicates(primary, pred_read)) do w.failing[symbol] = true end
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
                SG.flush(ctx, digest)
                local c = profile.constants
                save = {frame=frame, saves=state.saves, cartram_sha256=digest, flushed=true,
                        party_hp_hex=hex(ctx.sym("wPartyMon1HP", 0, 2)), mon_hp=c.MON_HP,
                        paused_frames=rec.windows.save_paused and rec.windows.save_paused.frames or 0}
            end
        end)
    api.unregister(handle)
    state.release()
    check("scripted " .. mode .. " route completed with normal buttons", played, not played and outcome or nil)
    check("checkpoint callback raised no error", #rec.errors == 0, rec.errors[1])

    local windows = {}
    for _, name in ipairs(rec.order) do
        local w, failing = rec.windows[name], json.array({})
        for symbol in pairs(w.failing) do failing[#failing + 1] = symbol end
        table.sort(failing)
        windows[name] = {frames=w.frames, accepted=w.accepted, failing=failing, write=w.write or json.null}
    end
    local reasons = {}
    for reason, count in pairs(rec.reasons) do reasons[reason] = count end
    log("U2_PHASES " .. json.encode(json.array(phases)))
    log("U2_WINDOWS " .. json.encode(json.object(windows)))
    log("U2_LIVENESS " .. json.encode({accepted=rec.accepted, refused=rec.refused, other_bank=rec.other_bank,
        reasons=json.object(reasons), pc=primary.execution_before.pc, bank=bank}))
    if rec.write then log("U2_WRITE " .. json.encode(rec.write)) end
    if save then log("U2_SAVE " .. json.encode(save)) end
    if model then log("U2_BATTLE_MODEL " .. json.encode(model)) end
    if mode == "reload" and played then log("DUMP " .. json.encode(IG.dump(api, profile))) end

    -- The gate's own verdict; tests/live/test_gen2_write_windows.py re-derives it independently.
    local function window_ok(name, need_frames, symbols)
        local w = windows[name]
        if not check(name .. " window observed", w ~= nil and w.frames >= need_frames, w and w.frames) then return end
        check(name .. ": no accepted checkpoint hold inside the window", w.accepted == 0, w.accepted)
        check(name .. ": a party write attempt is refused by ownership and changes nothing",
              w.write ~= json.null and w.write.refused and w.write.reason:find("ownership refused", 1, true) ~= nil
              and w.write.party_unchanged, w.write ~= json.null and w.write.reason or "not attempted")
        if symbols then
            local hit = false
            for _, symbol in ipairs(w.failing) do if symbols[symbol] then hit = true end end
            check(name .. ": the stated predicate refuses the window", hit, table.concat(w.failing, ","))
        end
    end
    if played and mode == "town" then
        local w = rec.write or {}
        check("idle hold wrote party HP and the current-box deposit", w.error == nil and w.party ~= nil
              and w.party.readback_hex == w.party.written_hex and w.box.readback_hex == w.box.after_hex, w.error)
        window_ok("start_menu", U.OBSERVE, nil)
        window_ok("script_text", U.OBSERVE, {wScriptRunning=true, wScriptFlags=true})
        window_ok("mid_warp", 1, {wMapStatus=true})
        if windows.save_paused then window_ok("save_paused", 1, {wGameLogicPaused=true}) end
        check("native save flushed", save ~= nil)
    elseif played and mode == "battle" then
        window_ok("battle", U.OBSERVE, {wBattleMode=true})
        local w = windows.battle
        check("battle: faint_party_slot refuses the active slot",
              w and w.write ~= json.null and w.write.faint_refused
              and w.write.faint_reason:find("active faint timing is not qualified", 1, true) ~= nil)
    end
    return finish()
end

if SLINK_GEN2_GATE_LIBRARY then return U end

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset -- launch via tools/run_gb_gate.py")
local IG = U.inspect_gate(ROOT)
local SG = IG.scripted_gate(ROOT)
local api = SG.bizhawk()
api.domains = function() return memory.getmemorydomainlist() end
U.main(api, os.getenv, SG, IG)
api.exit()
error("slink-gate-finished", 0)   -- client.exit() is asynchronous; stop here for real
