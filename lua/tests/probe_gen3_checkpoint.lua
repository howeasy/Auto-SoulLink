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
-- expect_clauses: every counted refusal of a negative row must name at least one of these
-- safety clause keys (safety.last_clauses after check); any other refusal fails the row.
-- min_samples: witnessed frames the row must count (default 1). A POSITIVE row also needs a
-- non-IRQ denominator of at least max(min_samples, P.POSITIVE_MIN_NON_IRQ): its rate is computed
-- over the non-IRQ samples only, so a raw count says nothing about how many frames the rate rests
-- on.
P.STATES = {
    {name="idle", terminal="field_idle_300", expectation="positive"},
    {name="walking", terminal="position_changed_120", expectation="report"},
    {name="start_menu", terminal="field_controls_locked", expectation="negative",
        expect_clauses={field_controls_locked=true}},
    -- C4-SAVE: sSaveDialogCB is never reset (pret start_menu.c:608-842), so it cannot be what
    -- refuses a live save. The whole dialog runs inside Task_StartMenuHandleInput (:378-394)
    -- under ShowStartMenu's lock (:405, released :586/:598); every physical dialog/save frame on
    -- record names both (checkpoint_*_2026-09-2[23]*.txt: task:N, field_controls_locked:N).
    -- The row's WITNESS is this invocation's transition into StartCB_Save1/Save2 under the live
    -- Task_StartMenuHandleInput (gen3_boot_check.start_menu_witness): a stale sSaveDialogCB after
    -- an earlier save made the old `~= 0` witness pass on ANY submenu's A (Codex cx-3e10776a).
    {name="dialog", terminal="start_menu_save_callback_under_live_task", expectation="negative",
        expect_clauses={task=true, field_controls_locked=true}},
    {name="save", terminal="new_counter_partial_slot_then_14_sectors", expectation="negative",
        expect_clauses={task=true, field_controls_locked=true}},
    {name="battle", terminal="in_battle_mask_nonzero", expectation="negative",
        expect_clauses={in_battle=true, callback1=true, callback2=true}},
    {name="fade", terminal="palette_fade_active_then_map_changed", expectation="negative",
        expect_clauses={palette_fade_active=true}},
    -- Task_PCMainMenu is off the allow-list, so "task" fails on every witnessed frame. The PC is
    -- opened by a script, so script_context_status also refuses; it is counted, not accepted.
    {name="pc_menu", terminal="task_pc_main_menu_active_60", expectation="negative",
        expect_clauses={task=true}, min_samples=60,
        artifacts={["radical_red/companion"]=true}},
    {name="script_running", terminal="script_context_not_shutdown_60", expectation="negative",
        expect_clauses={script_context_status=true}, min_samples=60,
        note="witness=same_byte_as_script_context_status,independent_read_path,not_independent_evidence",
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true, ["radical_red/companion"]=true}},
}

-- C4-B2: the battle / native / sound reasons. Declarative: each row names the savestate to load
-- (env override first), the normal inputs that reach the state, the reason and args the sample
-- passes to safety:check, and a witness read DIRECTLY from the pack's addresses (an independent
-- read path, not independent evidence -- the same caveat the script row carries). The generic
-- runner below drives them after the seven core phases, so the signed receipts stay valid.
-- state env -> default savestate; inputs are {tap=btn,frames=,gap=} / {idle=n} / {mash=n}.
P.REASON_ROWS = {
    {name="battle_input_wild", terminal="battle_main_func==HandleTurnActionSelectionState and "
        .. "gBattleCommunication[0]==1", expectation="positive", min_samples=60,
        reason="battle_faint", witness="battle_input",
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true, ["radical_red/clean"]=true,
                   ["radical_red/companion"]=true},
        note="wild encounter parked at the action menu; no input"},
    {name="battle_input_trainer", terminal="battle_main_func==HandleTurnActionSelectionState and "
        .. "gBattleCommunication[0]==1", expectation="positive", min_samples=60,
        reason="battle_commit", args={battler=0}, witness="battle_input",
        state_env="SLINK_CHECKPOINT_TRAINER_BATTLE_STATE", state="slink_pretrainer.State",
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true, ["radical_red/companion"]=true},
        note="trainer battle parked at the action menu; battler 0 is uncommitted so the guard holds"},
    {name="battle_move_menu", terminal="gBattleCommunication[0]==2",
        expectation="negative", expect_clauses={battle_comm_0=true},
        reason="battle_faint", witness="battle_comm_eq", witness_value=2,
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        inputs={{tap="A",frames=3,gap=13},{idle=120}},
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true, ["radical_red/companion"]=true},
        note="A on FIGHT opens the move submenu (STATE_WAIT_ACTION_CASE_CHOSEN)"},
    {name="battle_animation", terminal="gBattleControllerExecFlags~=0 and "
        .. "gBattlerControllerFuncs[0]~=HandleInputChooseAction",
        expectation="negative",
        expect_clauses={battle_exec_flags_input=true, battle_input_controller=true, battle_main_func=true},
        reason="battle_faint", witness="battle_exec_busy",
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        inputs={{tap="A",frames=3,gap=13},{tap="A",frames=3,gap=13},{idle=30}},
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true},
        note="two A presses commit a move; the animation holds the exec flags. FR/LG only: the "
            .. "RR pack has no gBattleControllerExecFlags address (reported UNVERIFIED)"},
    {name="battle_faint_prompt", terminal="gBattleMainFunc ~= HandleTurnActionSelectionState",
        expectation="negative", expect_clauses={battle_main_func=true, battle_exec_flags_input=true,
                                                battle_input_controller=true},
        reason="battle_faint", witness="battle_not_input",
        state_env="SLINK_CHECKPOINT_FAINT_STATE", state="slink_prefaint.State",
        inputs={{mash=3000}}, until_witness="send_out_prompt",
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true},
        note="from the lead's HP-0 frame, mash until the forced send-out prompt is up "
            .. "(ctrl==WaitForMonSelection), then hold there"},
    {name="battle_intro", terminal="gBattleMainFunc ~= HandleTurnActionSelectionState",
        expectation="negative", expect_clauses={battle_main_func=true, battle_exec_flags_input=true,
                                                battle_input_controller=true},
        reason="battle_faint", witness="battle_not_input",
        state_env="SLINK_CHECKPOINT_INTRO_STATE", state="slink_preintro.State",
        inputs={},
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true},
        note="battle intro parked before the first action menu"},
    {name="battle_link", terminal="gBattleTypeFlags & 2",
        expectation="negative", expect_clauses={battle_not_link=true},
        reason="battle_faint", witness="battle_link",
        state_env="SLINK_CHECKPOINT_LINK_STATE", state="slink_prelink.State",
        inputs={}, artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true},
        note="link battle at the input wait; FR/LG only (RR link entry is a CFRU unknown)"},
    {name="battle_over", terminal="gBattleOutcome~=0",
        expectation="negative", expect_clauses={battle_outcome_open=true, battle_engine_loaded=true},
        reason="battle_faint", witness="battle_resolved",
        state_env="SLINK_CHECKPOINT_POSTBATTLE_STATE", state="slink_postbattle.State",
        inputs={}, artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true,
                              ["radical_red/companion"]=true},
        note="the state saved after a resolved battle"},
    {name="battle_commit_state3", terminal="gBattleCommunication[0]>=3",
        expectation="negative", expect_clauses={battle_commit_guard=true},
        reason="battle_commit", args={battler=0}, witness="battle_comm_ge", witness_value=3,
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        inputs={{tap="A",frames=3,gap=13},{tap="A",frames=3,gap=13},{tap="A",frames=3,gap=13},
                {idle=240}},
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true, ["radical_red/companion"]=true},
        note="the commit guard: a committed battler (3/4) must refuse the Variant-3 pre-fill"},
    {name="native_idle_field", terminal="companion beacon present and mailbox idle",
        expectation="positive", min_samples=60, reason="native", witness="native_idle",
        state_env="SLINK_STATE", state="slink_overworld.State", inputs={},
        artifacts={["radical_red/companion"]=true},
        note="the native reason outside battle"},
    {name="native_idle_battle", terminal="companion beacon present and mailbox idle in battle",
        expectation="positive", min_samples=60, reason="native", witness="native_idle",
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State", inputs={},
        artifacts={["radical_red/companion"]=true},
        note="the rival-swap frame: native must be postable mid-battle"},
    {name="native_absent", terminal="no native block in this pack",
        expectation="negative", expect_clauses={native_present=true},
        reason="native", witness="always",
        state_env="SLINK_STATE", state="slink_overworld.State", inputs={},
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true, ["radical_red/clean"]=true},
        note="the reason must refuse on a build with no companion"},
    {name="sound_driver", terminal="m4a SE1 ident == ID_NUMBER",
        expectation="positive", min_samples=60, reason="sound", witness="sound_driver",
        state_env="SLINK_STATE", state="slink_overworld.State", inputs={},
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true, ["radical_red/clean"]=true},
        note="the sound reason on a live driver; native_busy is model-only (the probe posts no op)"},
}
for _, spec in ipairs(P.REASON_ROWS) do P.STATES[#P.STATES + 1] = spec end
P.REASON_BASE = #P.STATES - #P.REASON_ROWS + 1

-- Witness addresses. Neither witness calls safety; each reads one engine variable. The script
-- witness reads the SAME byte as the script_context_status predicate: an independent read path,
-- not independent evidence. The pc_menu witness (a gTasks func) is a different variable.
-- sGlobalScriptContextStatus: pokefirered.sym:663 0x03000EA8; pret src/script.c
-- CONTEXT_RUNNING 0 / WAITING 1 / SHUTDOWN 2 (docs/gen3_write_checkpoint.md:217). RR keeps
-- it: gen3_rr/write_checkpoint.json binds the same address (literal-pool proven, both ROMs).
P.SCRIPT_STATUS, P.CONTEXT_SHUTDOWN = 0x03000EA8, 2
-- Task_PCMainMenu: pokefirered.sym:6125 0x0808C39C (the unit test derives it from the .sym;
-- pokeleafgreen.sym has 0x0808C370, so the row stays RR-only); RR companion exec hook hits=294 while the
-- storage main menu was up (docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt).
P.TASK_PC_MAIN_MENU = 0x0808C39C
-- WaitForMonSelection | 1: gBattlerControllerFuncs[0] while the forced send-out party screen is
-- up (pret src/battle_controller_player.c:1297-1311). pokefirered.sym:2021 and
-- pokeleafgreen.sym:2021 agree (0x08030684); battle_faint_prompt is FR/LG-only.
P.WAIT_FOR_MON_SELECTION = 0x08030685
-- FR/LG script_running tile (tools/mkstates_gen3.lua slink_script.State): below the Viridian
-- woman, object 5 at (20,12), MOVEMENT_TYPE_FACE_UP, ViridianCity_EventScript_Woman
-- (lock/faceplayer/msgbox; pret data/maps/ViridianCity/map.json + scripts.inc:168-173).
P.SCRIPT_TILE = {20, 13}

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

-- Count one witnessed frame: safety's ok, reason and last_clauses, plus clause attribution.
function P.tally(row, ok, reason, clauses, cpsr)
    row.samples = row.samples + 1
    -- safety.lua refuses IRQ mode (0x12) by design. Preserve raw/negative
    -- counts; only the positive rate uses the non-IRQ denominator.
    if type(cpsr) == "number" and (cpsr & 0x1F) == 0x12 then
        row.irq = (row.irq or 0) + 1
    else
        row.non_irq_samples = (row.non_irq_samples or 0) + 1
        if ok then row.non_irq_yes = (row.non_irq_yes or 0) + 1 end
    end
    if ok then row.yes = row.yes + 1; return end
    row.no, row.reason = row.no + 1, tostring(reason)
    row.clauses = row.clauses or {}
    local hit = false
    for _, key in ipairs(clauses or {}) do
        row.clauses[key] = (row.clauses[key] or 0) + 1
        hit = hit or (row.expect_clauses or {})[key] == true
    end
    if row.expect_clauses and not hit then
        row.unattributed = (row.unattributed or 0) + 1
        row.misattributed = table.concat(clauses or {"none"}, "+")
    end
end

-- Positive rows: the smallest non-IRQ denominator their 90% rate may rest on (C3-35).
-- safety refuses CPSR mode 0x12 by design, so "sampled=300" can mean five usable frames; the
-- rate must not certify anything on a handful. 30 is a tenth of the idle row's 300 witnessed
-- frames (the only positive row today), and the recorded physical shapes are 276/300 (FR
-- checkpoint_fr_clean_2026-09-23_nonirq.txt:9), 275/300 and 300/300 (RR companion 2026-09-22b:10)
-- -- an order of magnitude above the floor, so no receipt on record could have tripped it.
-- A row that asks for more witnessed frames than this floors at its own min_samples.
P.POSITIVE_MIN_NON_IRQ = 30

function P.non_irq_floor(row)
    return math.max(row.min_samples or 1, P.POSITIVE_MIN_NON_IRQ)
end

-- Counts are conditional on the row's state witness, not on safety's answer. Returns ok, why.
function P.verdict(row)
    if row.error then return false, "callback error: " .. tostring(row.error) end
    if not row.reached then return false, "terminal not reached" end
    local min = row.min_samples or 1
    if row.samples < min then return false, string.format("samples %d < min_samples %d", row.samples, min) end
    if row.expectation == "positive" then
        local eligible = row.non_irq_samples or 0
        if eligible == 0 then return false, "no non-IRQ positive samples" end
        local floor = P.non_irq_floor(row)
        if eligible < floor then
            return false, string.format("non-IRQ samples %d < floor %d", eligible, floor)
        end
        return (row.non_irq_yes or 0) / eligible >= 0.90, "positive rate"
    end
    if row.expectation == "negative" then
        if row.yes > 0 then return false, "accepted " .. row.yes .. " witnessed frames" end
        if not row.expect_clauses then return false, "negative row declares no expect_clauses" end
        if (row.unattributed or 0) > 0 then
            return false, string.format("%d refusals without an expected clause, refused by %s",
                row.unattributed, row.misattributed)
        end
    end
    return true, "-"
end

function P.clause_counts(row)
    local keys, out = {}, {}
    for k in pairs(row.clauses or {}) do keys[#keys + 1] = k end
    table.sort(keys)
    for _, k in ipairs(keys) do out[#out + 1] = k .. ":" .. row.clauses[k] end
    return #out > 0 and table.concat(out, ",") or "-"
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

--- The dialog row's (arm, opened) pair. FR/LG: gen3_boot_check's START-menu witness -- arm =
--- the live menu task reads input (StartCB_HandleInput), opened = its callback then moved to
--- StartCB_Save1/Save2. A title without pinned START-menu code (radical_red): arm records
--- sSaveDialogCB just before the press and opened = it moved since, never the bare `~= 0`.
function P.dialog_witness(G, cp, title)
    local ready, running = G.start_menu_witness(title)
    if ready then return ready, running end
    local before
    return function() before = (G.pred(cp, "save_dialog_cb")); return true end,
           function() return before ~= nil and (G.pred(cp, "save_dialog_cb")) ~= before end
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
    local rows = {} -- predicate-only evidence; NOT a writer execution test
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
            expect_clauses=spec.expect_clauses, min_samples=spec.min_samples,
            samples=0, yes=0, no=0, irq=0, non_irq_samples=0, non_irq_yes=0,
            reached=false, reason="-", witness=witness, write_reason=spec.reason, args=spec.args}
        rows[index], active = row, row
        G.phase("probe-state", row.name .. " terminal=" .. row.terminal)
        return row
    end
    local function sample()
        if not active then return end
        -- Executed by onframeend, never from an exec hook. Raw R15/CPSR are reported,
        -- not fabricated as BIOS/0x1F. A core sampling mismatch fails the idle gate.
        if active.witness() then
            local ok, reason = safety:check(nil, active.write_reason, active.args)
            local regs = deps.regs()
            P.tally(active, ok, reason, safety.last_clauses, regs.CPSR)
            active.r15, active.cpsr, active.frame = regs.R15, regs.CPSR, deps.frame()
        end
    end
    local dialog_armed, dialog_open = P.dialog_witness(G, cp, title)
    local function open_save_dialog()
        G.tap("Start",3,30)
        for attempt = 1,14 do
            -- every press waits for the menu to READ input (a press into its draw is dropped)
            for _ = 1,300 do if dialog_armed() then break end; G.advance() end
            if attempt > 1 then
                G.tap("Down",3,13)
                for _ = 1,300 do if dialog_armed() then break end; G.advance() end
            end
            G.tap("A",3,0)
            for _ = 1,60 do
                if dialog_open() then return true end
                G.advance()
            end
            -- another row's submenu: back out to the field and reopen one row further
            for _ = 1,12 do
                if G.pred_ok(cp,"callback2") then break end
                G.tap("B",3,20)
            end
            G.tap("B",3,20); G.tap("Start",3,30)
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
        row = begin(4,function() return dialog_open() end)
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
                row.reached = pc_up()
                if not row.reached then row.reason = "storage menu task not held" end
            else row.reason = where end
            active = nil
            back_out()
        end

        -- ── C4-B2 reason rows: one generic runner, declarative specs ──────────────────────
        local function clause_of(name)
            for _, c in ipairs(assert(cp.battle, "no battle block").clauses) do
                if c.name == name then
                    return c.address + (c.offset or 0), c.width, c
                end
            end
        end
        local comm_a, comm_w = clause_of("battle_comm_0")
        local main_a, main_w, main_c = clause_of("battle_main_func")
        -- FR/LG name the input-wait flags clause battle_exec_flags_input (C4-BW); RR keeps _idle
        local flags_a = clause_of("battle_exec_flags_input") or clause_of("battle_exec_flags_idle")
        local ctrl_a, _, ctrl_c = clause_of("battle_input_controller")
        local type_a, type_w = clause_of("battle_not_link")
        local out_a, out_w = clause_of("battle_outcome_open")
        local native = cp.native
        local sound = cp.sound
        local sound_player = sound and sound.player_se1 and sound.player_se1.address
        local function w32(a) return memory.read_u32_le(a) end
        local function w16(a) return memory.read_u16_le(a) end
        local function w8(a) return memory.read_u8(a) end
        local WIT = {
            always = function() return true end,
            battle_input = function()
                return main_c ~= nil and w32(main_a) == main_c.expect and w8(comm_a) == 1
            end,
            battle_not_input = function()
                return main_c ~= nil and w32(main_a) ~= main_c.expect
            end,
            battle_comm_eq = function(spec) return function() return w8(comm_a) == spec.witness_value end end,
            battle_comm_ge = function(spec) return function() return w8(comm_a) >= spec.witness_value end end,
            -- flags ~= 0 alone also holds at the parked action menu (bit 0 pends on the input,
            -- C4-BW), which the battle_faint window admits; busy = not battler 0's action input
            battle_exec_busy = function()
                return w32(flags_a) ~= 0 and (ctrl_c == nil or w32(ctrl_a) ~= ctrl_c.expect)
            end,
            battle_link = function() return w32(type_a) & 2 ~= 0 end,
            battle_resolved = function() return w8(out_a) ~= 0 end,
            send_out_prompt = function() return w32(ctrl_a) == P.WAIT_FOR_MON_SELECTION end,
            native_idle = function()
                return native ~= nil and w32(native.base) == native.sig
            end,
            sound_driver = function()
                return sound_player ~= nil
                    and w32(sound_player + sound.ident_off) == sound.ident_magic
            end,
        }
        for i = P.REASON_BASE, #P.STATES do
            if plan[i] then
                local spec = P.STATES[i]
                load(os.getenv(spec.state_env) or spec.state)
                -- battle_comm_eq/_ge are factories over witness_value; every other WIT entry IS
                -- the witness (calling it here handed begin() a boolean: C4-PROBE, first FR run)
                local build = WIT[spec.witness]
                row = begin(i, spec.witness_value ~= nil and build(spec) or build)
                -- until_witness: the mash runs to that state, and the row is only reached there
                local stop = WIT[spec.until_witness] or function() return row.witness() end
                for _, step in ipairs(spec.inputs or {}) do
                    if step.tap then G.tap(step.tap, step.frames or 3, step.gap or 13)
                    elseif step.idle then G.idle(step.idle)
                    elseif step.mash then G.mash(step.mash, stop) end
                end
                local held, arrived = 0, spec.until_witness == nil or stop()
                for _ = 1, spec.hold or 180 do
                    if row.witness() then held = held + 1 end
                    G.advance()
                end
                row.reached = held > 0 and arrived
                if not arrived then row.reason = spec.until_witness .. " never reached"
                elseif not row.reached then row.reason = "state witness never held" end
                active = nil
            end
        end

        if plan[9] then
            local p = cp.predicates.script_context_status
            assert(p and p.address == P.SCRIPT_STATUS and (p.offset or 0) == 0,
                "pack does not bind sGlobalScriptContextStatus at the sym address")
            -- RR: nurse (7,2) behind MB_COUNTER (7,3), talk from (7,4) facing Up (gba_map 5.4).
            -- FR/LG: the Viridian woman from P.SCRIPT_TILE, in the mkstates-built state (C4-PROBE2;
            -- the earlier FR row used an externally made Oak-lab state).
            local rr = title == "radical_red"
            load(os.getenv("SLINK_CHECKPOINT_SCRIPT_STATE")
                or (rr and "slink_pokecenter_full.State" or "slink_script.State"))
            local function running() return P.script_active(memory.read_u8) end
            row = begin(9, running)
            local there, where
            if rr then there, where = walk({"Up","Up","Up","Up"}, 7, 4)
            else there, where = walk({}, P.SCRIPT_TILE[1], P.SCRIPT_TILE[2]) end
            if there and running() then there, where = false, "script already running before A" end
            if there then
                G.tap("Up",3,20)
                G.tap("A",3,0)
                for _ = 1,60 do if running() then break end; G.advance() end
                G.idle(120)
                row.reached = running()
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
            local good, why = P.verdict(row)
            passed = passed and good
            -- A positive row's floor is derived from its min_samples; state it, so a reader does
            -- not have to re-derive why a rate was refused. Negative/report rows have none.
            local floor = spec.expectation == "positive"
                and string.format(" floor=%d", P.non_irq_floor(row)) or ""
            G.log(string.format("PROBE %s %s sampled=%d true=%d false=%d irq=%d non_irq_sampled=%d non_irq_true=%d%s terminal=%s reached=%s R15=%s CPSR=%s frame=%s clauses=%s verdict=%s%s reason=%s",
                row.name, good and "PASS" or "FAIL", row.samples, row.yes, row.no,
                row.irq, row.non_irq_samples, row.non_irq_yes, floor, row.terminal,
                tostring(row.reached), tostring(row.r15), tostring(row.cpsr), tostring(row.frame),
                P.clause_counts(row), why, spec.note and (" note=" .. spec.note) or "", row.reason))
        end
    end
    -- Not evidence: this probe constructs no writer, so there is nothing to count.
    G.log("WRITE_SURFACE none (predicate-only probe) native_idle=opcode_queue_only")
    G.finish(passed, ok and (callback_error or "all checkpoint controls") or tostring(err))
end

if (debug.getinfo(1,"S").source or "") == "main" then P.run() end
return P
