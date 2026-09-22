-- P3 checkpoint lane: read-only predicate, joypad-driven forbidden states.
-- Env: SLINK_ROOT, SLINK_GEN3_CHECKPOINT/TITLE, SLINK_GEN3_KIND (required),
-- SLINK_STATE (idle field), SLINK_CHECKPOINT_BATTLE_STATE, SLINK_CHECKPOINT_DOOR_STATE,
-- SLINK_CHECKPOINT_PC_STATE, SLINK_CHECKPOINT_SCRIPT_STATE, SLINK_CHECKPOINT_ROWS.
-- Bare state names resolve under SLINK_STATE_DIR (default E:/Howard/Bizhawk/GBA/State).
-- Always runs the seven core phases. No subset can earn the complete probe's PASS.
-- Artifact rows (those with `artifacts`) run only where "<title>/<kind>" is admitted.
-- SLINK_CHECKPOINT_ROWS (comma list, or "none") narrows them; naming a row the artifact
-- does not admit is a config error, never a silent skip.
-- Pack predicates: gen3_rr/write_checkpoint.json:77-160; CPU:55-62; tasks:161-173.
-- Safety surface: lua/gen3/safety.lua:12,33-38. No writes.lua instance is constructed.
local P = {}
P.STATES = {
    {name="idle", terminal="field_idle_300", expectation="positive"},
    {name="walking", terminal="position_changed_120", expectation="report"},
    {name="start_menu", terminal="field_controls_locked", expectation="negative"},
    {name="dialog", terminal="save_dialog_cb_nonzero", expectation="negative"},
    {name="save", terminal="new_counter_partial_slot_then_14_sectors", expectation="negative"},
    {name="battle", terminal="in_battle_mask_nonzero", expectation="negative"},
    {name="fade", terminal="palette_fade_active_then_map_changed", expectation="negative"},
    {name="pc_menu", terminal="task_pc_main_menu_active_60", expectation="negative",
        artifacts={["radical_red/companion"]=true}},
    {name="script_running", terminal="script_context_not_shutdown_60", expectation="negative",
        artifacts={["firered/clean"]=true, ["radical_red/companion"]=true}},
}

-- Witness addresses. Neither witness touches safety; each reads one engine variable.
-- sGlobalScriptContextStatus: pokefirered.sym:663 0x03000EA8; pret src/script.c
-- CONTEXT_RUNNING 0 / WAITING 1 / SHUTDOWN 2 (docs/gen3_write_checkpoint.md:217). RR keeps
-- it: gen3_rr/write_checkpoint.json binds the same address (literal-pool proven, both ROMs).
P.SCRIPT_STATUS, P.CONTEXT_SHUTDOWN = 0x03000EA8, 2
-- Task_PCMainMenu: pokefirered.sym:6125 0x0808C39C; RR companion exec hook hits=294 while the
-- storage main menu was up (docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt).
P.TASK_PC_MAIN_MENU = 0x0808C39C

function P.script_active(read_u8)
    return read_u8(P.SCRIPT_STATUS) ~= P.CONTEXT_SHUTDOWN
end

-- gTasks layout from the pack's tasks block; func words carry the Thumb bit.
function P.task_active(read_u8, read_u32, tasks, fn)
    for i = 0, tasks.count - 1 do
        local base = tasks.address + i * tasks.struct_size
        if read_u8(base + tasks.is_active_offset) ~= 0
            and read_u32(base + tasks.func_offset) & ~1 == fn then return true end
    end
    return false
end

-- Set of P.STATES indices to run for this artifact.
function P.planned(title, kind, rows_env)
    local artifact, want = tostring(title) .. "/" .. tostring(kind), nil
    if rows_env and rows_env ~= "" then
        want = {}
        for n in rows_env:gmatch("[^,%s]+") do want[n] = true end
    end
    local plan, optional = {}, {none=true}
    for i, spec in ipairs(P.STATES) do
        if not spec.artifacts then plan[i] = true
        else
            optional[spec.name] = true
            local admitted = spec.artifacts[artifact] == true
            assert(not (want and want[spec.name]) or admitted, spec.name .. " not admitted for " .. artifact)
            if admitted and (want == nil or want[spec.name]) then plan[i] = true end
        end
    end
    for n in pairs(want or {}) do assert(optional[n], "unknown checkpoint row: " .. n) end
    return plan
end

-- Counts are conditional on an INDEPENDENT state witness, not on safety's answer.
function P.verdict(row)
    if row.error or not row.reached or row.samples == 0 then return false end
    if row.expectation == "positive" then return row.yes / row.samples >= 0.90 end
    if row.expectation == "negative" then return row.yes == 0 end
    return true
end

function P.build_deps(mem, emulator, native_idle)
    return {
        io = {
            read_u8 = function(a,d) return mem.read_u8(a,d) end,
            read_u16_le = function(a,d) return mem.read_u16_le(a,d) end,
            read_u32_le = function(a,d) return mem.read_u32_le(a,d) end,
        },
        regs = function() return {R15=emulator.getregister("R15"), CPSR=emulator.getregister("CPSR")} end,
        frame = function() return emulator.framecount() end,
        native_idle = native_idle,
    }
end

function P.run()
    local wt = assert(SLINK_ROOT or os.getenv("SLINK_ROOT"), "SLINK_ROOT required")
    local G = dofile(wt .. "/lua/tests/gen3_boot_check.lua")
    local S = dofile(wt .. "/lua/gen3/safety.lua")
    G.open("probe_gen3_checkpoint")
    G.budget = 45000
    local cp, title = G.checkpoint()
    local kind = assert(os.getenv("SLINK_GEN3_KIND"), "SLINK_GEN3_KIND clean/companion required")
    local plan = P.planned(title, kind, os.getenv("SLINK_CHECKPOINT_ROWS"))
    local active, callback_error, hook
    local rows, write_log = {}, {} -- predicate-only evidence; NOT a writer execution test
    local mb
    if title == "radical_red" then
        -- Loading mailbox.lua defines helpers; this probe calls ONLY present/busy.
        mb = dofile(wt .. "/lua/mailbox.lua")
    end
    local function native_idle()
        if mb and mb.present() then return not mb.busy() end
        return true
    end
    local deps = P.build_deps(memory, emu, native_idle)
    local safety = S.new(cp, deps, kind)
    local function field()
        return G.pred_ok(cp,"callback2") and G.pred_ok(cp,"in_battle")
            and G.pred_ok(cp,"field_controls_locked") and G.pred_ok(cp,"script_context_status")
    end
    local function load(name)
        if not name:find("[/\\]") then
            name = (os.getenv("SLINK_STATE_DIR") or "E:/Howard/Bizhawk/GBA/State") .. "/" .. name
        end
        active = nil
        savestate.load(name)
        G.idle(1)
    end
    local idle_state = os.getenv("SLINK_STATE") or "slink_overworld.State"
    local function begin(index, witness)
        local spec = P.STATES[index]
        local row = {name=spec.name, terminal=spec.terminal, expectation=spec.expectation,
            samples=0, yes=0, no=0, reached=false, reason="-", witness=witness}
        rows[index], active = row, row
        G.phase("probe-state", row.name .. " terminal=" .. row.terminal)
        return row
    end
    local function sample()
        if not active then return end
        -- Executed by onframeend, never from an exec hook. Raw R15/CPSR are reported,
        -- not fabricated as BIOS/0x1F. A core sampling mismatch fails the idle gate.
        if active.witness() then
            local ok, reason = safety:check()
            active.samples = active.samples + 1
            if ok then active.yes = active.yes + 1
            else active.no = active.no + 1; active.reason = tostring(reason) end
            local regs = deps.regs()
            active.r15, active.cpsr, active.frame = regs.R15, regs.CPSR, deps.frame()
        end
    end
    local function open_save_dialog()
        G.tap("Start",3,30)
        for _ = 1,14 do
            G.tap("A",3,60)
            if not G.pred_ok(cp,"save_dialog_cb") then return true end
            for _ = 1,12 do
                if G.pred_ok(cp,"callback2") then break end
                G.tap("B",3,20)
            end
            G.tap("B",3,20); G.tap("Start",3,30); G.tap("Down",3,13)
        end
        return false
    end
    -- Position-fed hold: a 3-frame tap only turns the player (census_rr_pc_deposit).
    local function walk(dirs, tx, ty)
        for _, dir in ipairs(dirs) do
            local x, y = G.pos(cp)
            for _ = 1, 48 do
                joypad.set({[dir]=true}); G.advance()
                local nx, ny = G.pos(cp)
                if nx ~= x or ny ~= y then break end
            end
            G.idle(20)
        end
        local x, y = G.pos(cp)
        return x == tx and y == ty, string.format("walk ended at (%d,%d), want (%d,%d)", x, y, tx, ty)
    end
    local function back_out()
        for _ = 1, 16 do
            if field() then return end
            G.tap("B",3,20)
        end
    end
    local ok, err = pcall(function()
        memory.usememorydomain("System Bus") -- G.* reads use the current bus domain
        hook = event.onframeend(function()
            local success, why = pcall(sample)
            if not success then callback_error = tostring(why); if active then active.error = callback_error end end
        end, "SLink-gen3-checkpoint-probe")
        assert(hook and tostring(hook):gsub("[{}]", "") ~= "00000000-0000-0000-0000-000000000000",
            "frame-end registration refused")
        load(idle_state)
        local row = begin(1,function() return true end)
        G.idle(300)
        row.reached = field() and row.samples == 300
        active = nil

        load(idle_state)
        local x,y = G.pos(cp)
        assert(x >= 0 and y >= 0, "invalid walking origin")
        row = begin(2,function() return true end)
        local moved = false
        for i=1,120 do
            joypad.set({[i <= 60 and "Left" or "Right"]=true}); G.advance()
            local nx,ny = G.pos(cp)
            moved = moved or (nx >= 0 and ny >= 0 and (x ~= nx or y ~= ny))
        end
        joypad.set({})
        row.reached = moved and row.samples == 120
        active = nil

        load(idle_state)
        G.tap("Start",3,30)
        row = begin(3,function() return not G.pred_ok(cp,"field_controls_locked") end)
        G.idle(120); row.reached = row.samples > 0; active = nil

        load(idle_state)
        assert(open_save_dialog(), "save prompt not reached for dialog control")
        row = begin(4,function() return not G.pred_ok(cp,"save_dialog_cb") end)
        G.idle(120); row.reached = row.samples > 0; active = nil

        local domain = assert(G.flash_domain(), "flash domain unavailable")
        local before, after = G.save_counter(domain), nil
        assert(before >= 0, "no baseline flash counter")
        row = begin(5,function()
            local counter = G.save_counter(domain)
            if counter > before then after = counter end
            return counter > before and G.sectors_at(domain,counter) < 14
        end)
        local complete = false
        for i=1,7000 do
            joypad.set(i % 16 == 1 and {A=true} or {})
            G.advance()
            if after and G.sectors_at(domain,after) >= 14 then complete=true; break end
        end
        joypad.set({}); row.reached = complete and row.samples > 0; active = nil

        load(os.getenv("SLINK_CHECKPOINT_BATTLE_STATE") or "slink_prebattle.State")
        row = begin(6,function() return not G.pred_ok(cp,"in_battle") end)
        G.idle(120); row.reached = row.samples > 0; active = nil

        load(os.getenv("SLINK_CHECKPOINT_DOOR_STATE") or "slink_door.State")
        local group,number = G.map(cp)
        assert(group >= 0 and number >= 0, "invalid starting map")
        row = begin(7,function() return not G.pred_ok(cp,"palette_fade_active") end)
        local changed = false
        for _=1,1200 do
            joypad.set(changed and {} or {Up=true}); G.advance()
            local g,n = G.map(cp)
            changed = changed or (g >= 0 and n >= 0 and (g ~= group or n ~= number))
            if changed and field() and G.pred_ok(cp,"palette_fade_active") then break end
        end
        joypad.set({}); row.reached = changed and field() and row.samples > 0; active = nil

        if plan[8] then
            -- gba_map 5.4 --bfs 7,8 11,2; PC at (11,1). Five A presses reach the storage menu.
            load(os.getenv("SLINK_CHECKPOINT_PC_STATE") or "slink_pokecenter_full.State")
            local tasks = assert(cp.tasks, "no tasks block")
            local function pc_up()
                return P.task_active(memory.read_u8, memory.read_u32_le, tasks, P.TASK_PC_MAIN_MENU)
            end
            row = begin(8, pc_up)
            local there, where = walk({"Up","Up","Up","Up","Right","Right","Right","Right","Up","Up"}, 11, 2)
            if there then
                G.tap("Up",3,20)
                for _ = 1,6 do
                    if pc_up() then break end
                    G.tap("A",3,0)
                    for _ = 1,120 do if pc_up() then break end; G.advance() end
                end
                G.idle(120)
                row.reached = pc_up() and row.samples >= 60
                if not row.reached then row.reason = "storage menu task not held" end
            else row.reason = where end
            active = nil
            back_out()
        end

        if plan[9] then
            local p = cp.predicates.script_context_status
            assert(p and p.address == P.SCRIPT_STATUS and (p.offset or 0) == 0,
                "pack does not bind sGlobalScriptContextStatus at the sym address")
            -- RR: nurse (7,2) behind MB_COUNTER (7,3), talk from (7,4) facing Up.
            -- FR: Oak (object 4) at (6,3), player at (6,4) facing Up. gba_map 5.4 / 4.3.
            local rr = title == "radical_red"
            load(os.getenv("SLINK_CHECKPOINT_SCRIPT_STATE")
                or (rr and "slink_pokecenter_full.State" or "slink_fr_parcel_deliver.State"))
            local function running() return P.script_active(memory.read_u8) end
            row = begin(9, running)
            local there, where
            if rr then there, where = walk({"Up","Up","Up","Up"}, 7, 4)
            else there, where = walk({}, 6, 4) end
            if there and running() then there, where = false, "script already running before A" end
            if there then
                G.tap("Up",3,20)
                G.tap("A",3,0)
                for _ = 1,60 do if running() then break end; G.advance() end
                G.idle(120)
                row.reached = running() and row.samples >= 60
                if not row.reached then row.reason = "script context not held" end
            else row.reason = where end
            active = nil
            back_out()
        end
    end)
    active = nil
    if hook then pcall(event.unregisterbyid,hook) end
    local passed = ok and callback_error == nil
    for i, spec in ipairs(P.STATES) do
        local row = rows[i]
        if not plan[i] then
            G.log(string.format("PROBE %s SKIP not selected for %s/%s", spec.name, title, kind))
        elseif not row then
            passed = false
            G.log(string.format("PROBE %s FAIL not run", spec.name))
        else
            local good = P.verdict(row)
            passed = passed and good
            G.log(string.format("PROBE %s %s sampled=%d true=%d false=%d terminal=%s reached=%s R15=%s CPSR=%s frame=%s reason=%s",
                row.name, good and "PASS" or "FAIL", row.samples, row.yes, row.no, row.terminal,
                tostring(row.reached), tostring(row.r15), tostring(row.cpsr), tostring(row.frame), row.reason))
        end
    end
    assert(#write_log == 0, "predicate probe write log must be empty")
    G.log("WRITE_LOG count=0 scope=predicate_only no_writes_instance=true native_idle=opcode_queue_only")
    G.finish(passed, ok and (callback_error or "all checkpoint controls") or tostring(err))
end

if (debug.getinfo(1,"S").source or "") == "main" then P.run() end
return P
