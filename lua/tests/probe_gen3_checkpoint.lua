-- P3 checkpoint lane: read-only predicate, joypad-driven forbidden states.
-- Env: SLINK_ROOT, SLINK_GEN3_CHECKPOINT/TITLE, SLINK_GEN3_KIND (required),
-- SLINK_STATE (idle field), SLINK_CHECKPOINT_BATTLE_STATE, SLINK_CHECKPOINT_DOOR_STATE.
-- Bare state names resolve under SLINK_STATE_DIR (default E:/Howard/Bizhawk/GBA/State).
-- Always runs all seven phases. No subset can earn the complete probe's PASS.
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
}

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
    end)
    active = nil
    if hook then pcall(event.unregisterbyid,hook) end
    local passed = ok and callback_error == nil and #rows == #P.STATES
    for _,row in ipairs(rows) do
        local good = P.verdict(row)
        passed = passed and good
        G.log(string.format("PROBE %s %s sampled=%d true=%d false=%d terminal=%s reached=%s R15=%s CPSR=%s frame=%s reason=%s",
            row.name, good and "PASS" or "FAIL", row.samples, row.yes, row.no, row.terminal,
            tostring(row.reached), tostring(row.r15), tostring(row.cpsr), tostring(row.frame), row.reason))
    end
    assert(#write_log == 0, "predicate probe write log must be empty")
    G.log("WRITE_LOG count=0 scope=predicate_only no_writes_instance=true native_idle=opcode_queue_only")
    G.finish(passed, ok and (callback_error or "all checkpoint controls") or tostring(err))
end

if (debug.getinfo(1,"S").source or "") == "main" then P.run() end
return P
