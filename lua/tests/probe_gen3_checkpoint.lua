-- P3 checkpoint lane: read-only predicate, joypad-driven forbidden states.
-- Env: SLINK_ROOT, SLINK_GEN3_CHECKPOINT/TITLE, SLINK_GEN3_KIND (required),
-- SLINK_STATE (idle field), SLINK_CHECKPOINT_BATTLE_STATE, SLINK_CHECKPOINT_DOOR_STATE,
-- SLINK_CHECKPOINT_PC_STATE, SLINK_CHECKPOINT_SCRIPT_STATE, SLINK_CHECKPOINT_ROWS, and per reason
-- row its state_env (below). G4 2b battle-window rows (bw_*) also read SLINK_CHECKPOINT_INTRO_STATE,
-- SLINK_CHECKPOINT_OLDMAN_STATE, SLINK_CHECKPOINT_POKEDUDE_STATE and SLINK_BW_HASHES (a JSON file:
-- {"pack": sha256, "source": sha, "states": {"<state basename>": {"state": sha256,
-- "fixture": sha256, "prep": "<normal-input preparation receipt>"}}}; the ROM hash is the loaded
-- ROM's own, gameinfo.getromhash()). A bw row without all five receipt hashes fails.
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
        reason="battle_commit", args={battler=0}, witness="battle_input_trainer",
        state_env="SLINK_CHECKPOINT_TRAINER_BATTLE_STATE", state="slink_pretrainer.State",
        artifacts={["firered/clean"]=true, ["leafgreen/clean"]=true},
        note="trainer battle parked at the action menu (gBattleTypeFlags & BATTLE_TYPE_TRAINER); "
            .. "battler 0 is uncommitted so the guard holds. RR holds battle_commit: see "
            .. "battle_commit_held_rr"},
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

-- ── G4 2b battle-window rows (card 2B-INTEGRATE-PROBE) ──────────────────────────────────────
-- docs/gen3/research/g4_2b_matrix_plan_2026-09-23.md §4. `bw` names a row of
-- lua/tests/gen3_battle_window_rows.lua (card 2B-OBS): that module owns the witness (arm, hold,
-- done), the floor, the receipt and the verdict (PASS / FAIL / UNREACHED; only PASS passes here).
-- Every frame from the first one after the row's state loads is sampled into it, so N1/N7/N8/N9
-- see their commit/draw frame. Matrix rows already covered, NOT repeated: N2 = battle_move_menu,
-- N10 = battle_intro, N11 = battle_faint_prompt, N12 = battle_animation, N13 = battle_over.
-- Normal joypad only. Input steps beyond tap/idle/mash (bw rows only): {wait=W, frames=n}
-- advances until P.BW_WAITS[W]; {action=n} steers gActionSelectionCursor (0 FIGHT, 1 BAG,
-- 2 POKEMON, 3 RUN; Right/Left flip bit 0, Down/Up bit 1); {slot=n} presses Down until the party
-- cursor is n; {pulse=btn, frames=n, stop=W} presses btn on the 16-frame cadence until W;
-- {throw_ball=true} is gen3_scripted_play's throw_pokeball_from_bag; a bw mash's `stop` names a W.
local FRLG = {["firered/clean"]=true, ["leafgreen/clean"]=true}
-- gap=1: one released frame after every A. With gap=0 the popup-opening A and the SHIFT A of
-- bw_n7_switch were ONE held press (the popup wait is already true on the next frame), so SHIFT
-- was never chosen and the B pulse cancelled the menu: N7 UNREACHED on FR and LG, lane 765beb48.
local TAP_A = {tap="A", frames=3, gap=1}
P.BW_ROWS = {
    {name="bw_n1_action_draw", bw="N1", terminal="ctrl0 HandleChooseActionAfterDma3 then HandleInputChooseAction",
        state_env="SLINK_CHECKPOINT_INTRO_STATE", state="slink_preintro.State",
        inputs={{mash=3000, stop="action_input"}}, hold=30,
        note="sampled from the intro on, so the draw frame is seen before the menu reads input; "
            .. "the intro itself is battle_intro (N10)"},
    {name="bw_n4_bag", bw="N4", terminal="CB2_BagMenuRun + bag input task, fade settled, battle location",
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        inputs={{wait="action_input"}, {action=1}, TAP_A, {wait="bag_input"}},
        note="BAG from the parked wild menu; the move submenu is battle_move_menu (N2)"},
    {name="bw_n5_party", bw="N5", terminal="CB2_UpdatePartyMenu + Task_HandleChooseMonInput, CHOOSE_MON",
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        inputs={{wait="action_input"}, {action=2}, TAP_A, {wait="party_input"}},
        note="POKEMON from the parked wild menu; the forced send-out is battle_faint_prompt (N11)"},
    {name="bw_n6_summary", bw="N6", terminal="CB2_RunPokemonSummaryScreen from the battle party menu",
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        inputs={{wait="action_input"}, {action=2}, TAP_A, {wait="party_input"}, TAP_A,
                {wait="party_popup"}, {tap="Down", frames=3, gap=13}, TAP_A, {wait="summary"}},
        note="the lead's popup row 1 = SUMMARY (pret src/data/party_menu.h:1094 ShiftSummaryCancel)"},
    {name="bw_n7_switch", bw="N7", terminal="CHOSENMONRETURNVALUE, then gBattlerPartyIndexes[0]==selected",
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        inputs={{wait="action_input"}, {action=2}, TAP_A, {wait="party_input"}, {slot=1}, TAP_A,
                {wait="party_popup"}, TAP_A, {pulse="B", frames=3000, stop="turn_over"}},
        note="SHIFT to the healthy slot 1 (both battle fixtures); B only clears battle text; the "
            .. "move animation after it is battle_animation (N12)"},
    {name="bw_n9_run", bw="N9", terminal="TWORETURNVALUES B_ACTION_RUN, then gBattleOutcome==B_OUTCOME_RAN",
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        inputs={{wait="action_input"}, {action=3}, TAP_A, {pulse="B", frames=3000, stop="turn_over"}},
        note="RUN from the parked wild menu; the resolved state is battle_over (N13)"},
    {name="bw_u1_oldman", bw="U1", terminal="OLD_MAN_TUTORIAL bit 9 + ctrl0 in battle_controller_oak_old_man.o",
        state_env="SLINK_CHECKPOINT_OLDMAN_STATE", state="slink_oldman.State", inputs={}, forbid_b=true,
        note="the auto-driven demo, state from mkstates_gen3_tutorials; no input at all"},
    {name="bw_u2_pokedude", bw="U2", terminal="POKEDUDE bit 16 + ctrl0 in battle_controller_pokedude.o",
        state_env="SLINK_CHECKPOINT_POKEDUDE_STATE", state="slink_pokedude.State", inputs={}, forbid_b=true,
        note="NO B while the flag is set: JOY_HELD(B) quits the battle (pret battle_main.c:1455)"},
    -- Last on purpose: throw_pokeball_from_bag ends the WHOLE run through its own G.finish when
    -- the bag cannot be driven; every earlier bw row has logged its BWROW/receipt lines by then.
    {name="bw_n8_item", bw="N8", terminal="ONERETURNVALUE item 4, then gBattleOutcome~=0 or the menu reopens",
        state_env="SLINK_CHECKPOINT_BATTLE_STATE", state="slink_prebattle.State",
        inputs={{wait="action_input"}, {action=1}, {tap="A", frames=3, gap=30}, {throw_ball=true},
                {pulse="B", frames=4000, stop="turn_over"}},
        note="an owned POKE BALL; B clears the dex page and declines the nickname, so a catch "
            .. "reaches gBattleOutcome 7 and is classified ended=outcome=7, not failed"},
}
for _, spec in ipairs(P.BW_ROWS) do
    spec.expectation, spec.reason, spec.artifacts = "bw", "battle_faint", FRLG
    P.REASON_ROWS[#P.REASON_ROWS + 1] = spec
end
-- a1bbc686 (C5-RR-BW-FIX): the RR pack carries battle.commit_hold, so safety refuses
-- battle_commit with battle_commit_hold even at a parked, uncommitted trainer menu (CFRU's parked
-- controller stays live after comm = 3). The trainer tuple therefore signs a REFUSAL on RR.
-- Appended after the bw rows so every FR/LG index is unchanged; it runs on RR only.
P.REASON_ROWS[#P.REASON_ROWS + 1] = {name="battle_commit_held_rr",
    terminal="battle_main_func==HandleTurnActionSelectionState and gBattleCommunication[0]==1 "
        .. "and BATTLE_TYPE_TRAINER",
    expectation="negative", expect_clauses={battle_commit_hold=true}, min_samples=60,
    reason="battle_commit", args={battler=0}, witness="battle_input_trainer",
    state_env="SLINK_CHECKPOINT_TRAINER_BATTLE_STATE", state="slink_pretrainer.State",
    artifacts={["radical_red/companion"]=true},
    note="RR holds battle_commit (pack battle.commit_hold): the parked trainer menu must refuse "
        .. "it by battle_commit_hold"}
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

-- BATTLE_TYPE_TRAINER (pret include/constants/battle.h, bit 3). The trainer row's witness
-- needs it: without it a wild parked menu satisfied battle_input, so a state dir lacking
-- slink_pretrainer.State (with the previous wild state still loaded) PASSED the trainer row.
P.BATTLE_TYPE_TRAINER = 8

--- A bare state name resolves under `dir` (SLINK_STATE_DIR); a path is kept as given.
function P.state_path(name, dir)
    if name:find("[/\\]") then return name end
    return (dir or "E:/Howard/Bizhawk/GBA/State") .. "/" .. name
end

--- true, or false + why. BizHawk 2.11's savestate.load returns false on a missing file instead
--- of raising, which kept the PREVIOUS state loaded under the new row's name (C4-PROBE2 review
--- A-1). Existence is checked first, and only a literal true counts as loaded (OMP A2: nil is a
--- failure too, never "no news is good news").
function P.load_state(path, load_fn, open_fn)
    local f = open_fn(path, "rb")
    if not f then return false, "state missing: " .. path end
    f:close()
    local got = load_fn(path)
    if got ~= true then return false, "savestate.load refused (returned " .. tostring(got) .. "): " .. path end
    return true
end

--- The reason-row state witnesses over the pack's battle clauses (plus native/sound), read
--- through r8/r32. None consults the permit.
function P.witnesses(cp, r8, r32)
    local function clause_of(name)
        for _, c in ipairs(assert(cp.battle, "no battle block").clauses) do
            if c.name == name then
                return c.address + (c.offset or 0), c.width, c
            end
        end
    end
    local comm_a = clause_of("battle_comm_0")
    local main_a, _, main_c = clause_of("battle_main_func")
    -- FR/LG name the input-wait flags clause battle_exec_flags_input (C4-BW); RR keeps _idle
    local flags_a = clause_of("battle_exec_flags_input") or clause_of("battle_exec_flags_idle")
    local ctrl_a, _, ctrl_c = clause_of("battle_input_controller")
    local type_a = clause_of("battle_not_link")
    local out_a = clause_of("battle_outcome_open")
    local native = cp.native
    local sound = cp.sound
    local sound_player = sound and sound.player_se1 and sound.player_se1.address
    local function w32(a) return r32(a) end
    local function w8(a) return r8(a) end
    local WIT = {}
    WIT.always = function() return true end
    WIT.battle_input = function()
        return main_c ~= nil and w32(main_a) == main_c.expect and w8(comm_a) == 1
    end
    WIT.battle_input_trainer = function()
        return WIT.battle_input() and w32(type_a) & P.BATTLE_TYPE_TRAINER ~= 0
    end
    WIT.battle_not_input = function()
        return main_c ~= nil and w32(main_a) ~= main_c.expect
    end
    WIT.battle_comm_eq = function(spec) return function() return w8(comm_a) == spec.witness_value end end
    WIT.battle_comm_ge = function(spec) return function() return w8(comm_a) >= spec.witness_value end end
    -- flags ~= 0 alone also holds at the parked action menu (bit 0 pends on the input,
    -- C4-BW), which the battle_faint window admits; busy = not battler 0's action input
    WIT.battle_exec_busy = function()
        return w32(flags_a) ~= 0 and (ctrl_c == nil or w32(ctrl_a) ~= ctrl_c.expect)
    end
    WIT.battle_link = function() return w32(type_a) & 2 ~= 0 end
    WIT.battle_resolved = function() return w8(out_a) ~= 0 end
    WIT.send_out_prompt = function() return w32(ctrl_a) == P.WAIT_FOR_MON_SELECTION end
    WIT.native_idle = function()
        return native ~= nil and w32(native.base) == native.sig
    end
    WIT.sound_driver = function()
        return sound_player ~= nil
            and w32(sound_player + sound.ident_off) == sound.ident_magic
    end
    return WIT
end

--- (witness, stop) for a reason row. battle_comm_eq/_ge are factories over witness_value; every
--- other WIT entry IS the witness (calling it handed begin() a boolean: C4-PROBE, first FR run).
--- Errors, never a silent fallback: an unknown witness or until_witness name, a factory without
--- witness_value, a witness_value on a plain witness, a factory as until_witness (OMP A4).
P.WITNESS_FACTORIES = {battle_comm_eq = true, battle_comm_ge = true}
function P.row_witness(WIT, spec)
    local build = assert(WIT[spec.witness], "unknown witness " .. tostring(spec.witness) .. " in " .. spec.name)
    local factory = P.WITNESS_FACTORIES[spec.witness] == true
    assert(factory == (spec.witness_value ~= nil), spec.name .. ": witness " .. spec.witness
        .. (factory and " is a factory and needs witness_value" or " takes no witness_value"))
    local w = factory and build(spec) or build
    if spec.until_witness == nil then return w, w end
    assert(not P.WITNESS_FACTORIES[spec.until_witness],
        spec.name .. ": until_witness " .. spec.until_witness .. " is a factory")
    return w, assert(WIT[spec.until_witness],
        "unknown until_witness " .. tostring(spec.until_witness) .. " in " .. spec.name)
end

--- B6: every planned row's inputs (and a reason row's witness names) are validated before any
--- row runs, so a malformed spec fails at the start instead of after the emulator work.
function P.validate(plan, WIT)
    for i, spec in ipairs(P.STATES) do
        if plan[i] then
            P.check_inputs(spec)
            if spec.witness ~= nil then P.row_witness(WIT, spec) end
        end
    end
    return true
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

-- bw input waits over the previous frame-end sample `s` (gen3_battle_window_rows R.sample)
-- and its bound ctx `c` (c.T = gen3_title_syms, c.W = gen3_battle_window_syms).
P.BW_WAITS = {
    action_input = function(s, c) return s.ctrl[0] == c.T.HANDLE_INPUT_CHOOSE_ACTION end,
    bag_input = function(s, c)
        return s.cb2 == c.T.CB2_BAG_MENU_RUN and s.tasks[c.T.TASK_BAG_MENU_HANDLE_INPUT] == true
            and not s.tasks[c.T.TASK_ANIMATE_WIN0V] and not s.fade
    end,
    party_input = function(s, c)
        return s.cb2 == c.T.CB2_UPDATE_PARTY_MENU and s.tasks[c.T.TASK_CHOOSE_MON] == true and not s.fade
    end,
    party_popup = function(s, c) return s.tasks[c.T.TASK_SELECTION_POPUP] == true and not s.fade end,
    summary = function(s, c) return s.cb2 == c.W.CB2_RUN_SUMMARY_SCREEN and not s.fade end,
    turn_over = function(s, c) return s.outcome ~= 0 or s.ctrl[0] == c.T.HANDLE_INPUT_CHOOSE_ACTION end,
}
P.STEP_KINDS = {"tap", "idle", "mash", "wait", "action", "slot", "pulse", "throw_ball"}
local BW_ONLY = {wait=true, action=true, slot=true, pulse=true, throw_ball=true}

--- Validate a row's input steps before any is pressed: one known kind per step, bw-only kinds
--- only on bw rows, known wait names, and no B at all on a forbid_b row (U2: the Pokedude flag).
function P.check_inputs(spec)
    local held   -- a button a gap-0 tap may still hold: no step since is sure to have released it
    for i, step in ipairs(spec.inputs or {}) do
        local where, kind = spec.name .. " input " .. i, nil
        for _, k in ipairs(P.STEP_KINDS) do
            if step[k] ~= nil then
                assert(kind == nil, where .. ": several step kinds")
                kind = k
            end
        end
        assert(kind, where .. ": unknown input step")
        assert(spec.bw or not BW_ONLY[kind], where .. ": " .. kind .. " is a battle-window step")
        assert(not (spec.forbid_b and (step.tap == "B" or step.pulse == "B")), where .. ": B is forbidden")
        for _, w in ipairs({step.wait or false, step.stop or false}) do
            assert(w == false or P.BW_WAITS[w], where .. ": unknown wait " .. tostring(w))
        end
        assert(kind ~= "pulse" or step.stop, where .. ": a pulse needs a stop")
        -- JOY_NEW needs a released frame between two presses; a wait already true, an action or
        -- slot step already in place, all take zero frames, so only these release a held button
        assert(step.tap == nil or step.tap ~= held,
            where .. ": " .. tostring(held) .. " pressed again with no released frame (the game sees one press)")
        if step.tap then held = (step.gap == 0) and step.tap or nil
        elseif (step.idle or 0) > 0 or kind == "mash" or kind == "pulse" or kind == "throw_ball" then held = nil end
    end
    return true
end

P.BW_HASHES = {"rom", "fixture", "pack", "source", "state"}

-- ── game-confirmed presses (N7 live, lane d8a62085) ────────────────────────────────────────
-- A menu only acts on JOY_NEW: ReadKeys (pret src/main.c:296-300) sets newKeys = input &
-- ~heldKeysRaw once per main-loop pass (:180). A pass that overruns a frame (the popup's window
-- + text work on the A frame, party_menu.c:3044-3059) reads keys on fewer frames than the
-- emulator runs, so a one-frame release between two A taps can go unread: the game saw A held
-- 1925..1931 and never a second press, so SHIFT never fired. P.press therefore reads the game's
-- own gMain.heldKeys (0x030030F0 + 0x2C, include/main.h:31, both titles): it waits until the
-- game has READ the button released, holds until the game has READ it pressed (that read is the
-- JOY_NEW edge), then waits until it reads it released again, then idles `gap`.
P.KEY_BITS = {A = 0x1, B = 0x2, Select = 0x4, Start = 0x8, Right = 0x10, Left = 0x20, Up = 0x40,
              Down = 0x80, R = 0x100, L = 0x200}
P.HELD_KEYS_OFF = 0x2C - 0x04   -- gMain.heldKeys, relative to gMain.callback2 (title syms)
P.PRESS_BOUND = 30

--- true, frames | false, why. set/advance/held are the joypad, one emulated frame, and the
--- game's gMain.heldKeys; never more than P.PRESS_BOUND frames per phase.
function P.press(btn, set, advance, held, gap)
    local bit, n = assert(P.KEY_BITS[btn], "unknown button " .. tostring(btn)), 0
    local function phase(keys, want, what)
        for _ = 1, P.PRESS_BOUND do
            set(keys); advance(); n = n + 1
            if (held() & bit ~= 0) == want then return true end
        end
        return false, string.format("%s: the game never read %s %s in %d frames", btn, btn, what, P.PRESS_BOUND)
    end
    local ok, why = phase({}, false, "released")
    if ok then ok, why = phase({[btn] = true}, true, "pressed") end
    if ok then ok, why = phase({}, false, "released after the press") end
    if not ok then set({}); return false, why end
    for _ = 1, gap or 0 do set({}); advance(); n = n + 1 end
    return true, n
end
-- struct Pokemon is 100 bytes, hp u16 at +0x56 (pret include/pokemon.h; duo_main.lua:26)
P.PARTY_MON_SIZE, P.MON_HP_OFF = 100, 0x56

--- OMP B5: the menu/party state a live miss needs, from one bw sample (nil: none fed yet).
--- slot1_usable = a second party mon exists with HP > 0 (the N7 SHIFT target).
function P.bw_diag(prefix, s)
    if s == nil then return prefix .. " no sample fed yet" end
    local e = s.extra or {}
    local usable = (e.party_count or 0) >= 2 and (e.slot1_hp or 0) > 0
    return string.format("%s frame=%s ctrl0=%s chosen0=%s bufB0=%s,%s outcome=%s cb2=%s pm_type=%s pm_slot=%s pm_action=%s bag_location=%s fade=%s party_count=%s slot1_hp=%s slot1_usable=%s keys=%s",
        prefix, tostring(s.frame), s.ctrl[0] and string.format("%08X", s.ctrl[0]) or "nil", tostring(s.chosen0),
        tostring(s.ret[0]), tostring(s.ret[1]), tostring(s.outcome), s.cb2 and string.format("%08X", s.cb2) or "nil",
        tostring(s.pm_type), tostring(s.pm_slot), tostring(s.pm_action), tostring(s.bag_location),
        tostring(s.fade), tostring(e.party_count), tostring(e.slot1_hp), tostring(usable),
        e.keys and string.format("%04X", e.keys) or "nil")
end

--- The receipt meta for one bw row, or nil + why when any of the five hashes is absent (the
--- receipt refuses a blank; the row then fails by name instead of the probe dying at log time).
function P.bw_meta(doc, rom, state_path, row)
    local base = state_path:match("[^/\\]+$")
    local st = doc and doc.states and doc.states[base] or {}
    local meta = {row = row, state_path = state_path, prep = st.prep,
        hashes = {rom = rom, fixture = st.fixture, pack = doc and doc.pack, source = doc and doc.source,
                  state = st.state}}
    for _, h in ipairs(P.BW_HASHES) do
        local v = meta.hashes[h]
        if type(v) ~= "string" or v == "" then return nil, "receipt needs the " .. h .. " hash for " .. base end
    end
    return meta
end

--- One witnessed frame of a bw row: the rows module's sample (safety's verdict + the full
--- tuple), fed to the row's accumulator. Returns the sample. Unreadable memory raises.
function P.bw_feed(row, safety, extra)
    local acc = row.bw
    local s = acc.ctx:sample(safety, acc.spec.reason, nil, extra)
    acc.ctx.feed(acc, s)
    return s
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
    if row.blocked then return false, tostring(row.blocked) end
    if row.expectation == "bw" then
        if not row.bw then return false, "battle-window row has no sampler" end
        local status, why = row.bw.ctx.verdict(row.bw)
        return status == "PASS", status .. " " .. why
    end
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

--- (good, why, line): a row's PROBE verdict line. frames = emulator frames the row spent.
function P.row_line(spec, row)
    local good, why = P.verdict(row)
    -- A positive row's floor is derived from its min_samples; state it, so a reader does
    -- not have to re-derive why a rate was refused. Negative/report rows have none.
    local floor = spec.expectation == "positive"
        and string.format(" floor=%d", P.non_irq_floor(row)) or ""
    return good, why, string.format("PROBE %s %s sampled=%d true=%d false=%d irq=%d non_irq_sampled=%d non_irq_true=%d%s terminal=%s reached=%s R15=%s CPSR=%s frame=%s frames=%s clauses=%s verdict=%s%s reason=%s",
        row.name, good and "PASS" or "FAIL", row.samples, row.yes, row.no,
        row.irq or 0, row.non_irq_samples or 0, row.non_irq_yes or 0, floor, row.terminal,
        tostring(row.reached), tostring(row.r15), tostring(row.cpsr), tostring(row.frame),
        tostring(row.frames), P.clause_counts(row), why, spec.note and (" note=" .. spec.note) or "",
        row.reason)
end

--- Log a finished row's PROBE line NOW (OMP B2): a later G.finish -- throw_pokeball_from_bag's
--- own, gen3_scripted_play.lua:2274-2341 -- can end the run without erasing it.
function P.finish_row(row, spent, log)
    row.frames = row.spent0 and spent - row.spent0 or nil
    local good, _, line = P.row_line(P.STATES[row.index], row)
    log(line)
    row.logged = true
    return good
end

--- The end-of-run pass: every planned row's verdict counts; lines only for rows not yet logged
--- (a row cut short by an error) and SKIP / "FAIL not run" for the rest. Returns passed.
function P.summary(rows, plan, title, kind, passed, log)
    for i, spec in ipairs(P.STATES) do
        local row = rows[i]
        if not plan[i] then
            log(string.format("PROBE %s SKIP not selected for %s/%s", spec.name, title, kind))
        elseif not row then
            passed = false
            log(string.format("PROBE %s FAIL not run", spec.name))
        else
            local good, _, line = P.row_line(spec, row)
            passed = passed and good
            if not row.logged then log(line) end
        end
    end
    return passed
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
    G.budget = 90000   -- 2B: the nine bw rows add up to ~20k frames worst case (mash/pulse bounds)
    local cp, title = G.checkpoint()
    local kind = assert(os.getenv("SLINK_GEN3_KIND"), "SLINK_GEN3_KIND clean/companion required")
    local plan = P.planned(title, kind, os.getenv("SLINK_CHECKPOINT_ROWS"))
    local active, callback_error, hook
    local rows = {} -- predicate-only evidence; NOT a writer execution test
    local nb   -- the companion mailbox block (profile.json "native"), RR only
    if title == "radical_red" then
        local f = assert(io.open(wt .. "/data/games/gen3_rr/profile.json", "rb"))
        nb = dofile(wt .. "/lua/json_codec.lua").decode(f:read("a")).native
        f:close()
    end
    -- Present = signature + ABI word; idle = no opcode posted (the slot is free).
    local function native_idle()
        if nb and memory.read_u32_le(nb.BASE) == nb.SIG
           and memory.read_u16_le(nb.BASE + 4) == nb.ABI then
            return memory.read_u16_le(nb.BASE + 6) == 0
        end
        return true
    end
    local deps = P.build_deps(memory, emu, native_idle)
    local safety = S.new(cp, deps, kind)
    local function field()
        return G.pred_ok(cp,"callback2") and G.pred_ok(cp,"in_battle")
            and G.pred_ok(cp,"field_controls_locked") and G.pred_ok(cp,"script_context_status")
    end
    -- true, or false + why; a core phase asserts it, a reason row fails by name (A-1).
    local function load(name)
        local path = P.state_path(name, os.getenv("SLINK_STATE_DIR"))
        active = nil
        local ok, why = P.load_state(path, function(q) return savestate.load(q) end, io.open)
        if ok then G.idle(1) end
        return ok, why
    end
    local function must_load(name)   -- OMP A3: a core phase fails naming the state and the cause
        local ok, why = load(name)
        assert(ok, "core phase state: " .. tostring(why))
    end
    local idle_state = os.getenv("SLINK_STATE") or "slink_overworld.State"
    local function begin(index, witness)
        local spec = P.STATES[index]
        local row = {name=spec.name, terminal=spec.terminal, expectation=spec.expectation,
            expect_clauses=spec.expect_clauses, min_samples=spec.min_samples,
            samples=0, yes=0, no=0, irq=0, non_irq_samples=0, non_irq_yes=0,
            reached=false, reason="-", witness=witness, write_reason=spec.reason, args=spec.args,
            index=index, spent0=G.spent}
        rows[index], active = row, row
        G.phase("probe-state", row.name .. " terminal=" .. row.terminal)
        return row
    end
    local function finish(row)
        active = nil
        P.finish_row(row, G.spent, G.log)
    end
    local bw_ctx, bw_last, bw_doc, rom_sha, SP, bag
    local function sample()
        if not active then return end
        if active.bw then
            local g, n = G.map(cp)
            local x, y = G.pos(cp)
            local extra = {map = g .. "." .. n, pos = x .. "," .. y,
                party_count = memory.read_u8(bw_ctx.T.PARTY_COUNT_ADDR),
                keys = memory.read_u16_le(bw_ctx.T.GMAIN_CALLBACK2_ADDR + P.HELD_KEYS_OFF),
                slot1_hp = memory.read_u16_le(bw_ctx.T.PARTY_BASE + P.PARTY_MON_SIZE + P.MON_HP_OFF)}
            -- N8's receipt_fields: the ball pocket total (SaveBlock1 +0x430, quantity XOR the
            -- low 16 bits of SaveBlock2.encryptionKey; lua/gen3/reads.lua read_balls), every frame
            -- from the load, so the row's first fed sample is the pre-throw baseline (bdbf5736)
            if active.bw.spec.receipt_fields then
                local balls = bag.read_balls()
                extra.balls = balls and balls.ball_count
            end
            bw_last = P.bw_feed(active, safety, extra)
            return
        end
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
        for i, spec in ipairs(P.STATES) do
            if plan[i] and spec.bw and not bw_ctx then
                -- bound once per artifact on the probe's own deps; FR/LG only (for_title refuses RR)
                bw_ctx = dofile(wt .. "/lua/tests/gen3_battle_window_rows.lua").bind(cp, title, deps, wt)
                local path = os.getenv("SLINK_BW_HASHES")
                local f = path and io.open(path, "rb")
                if f then
                    bw_doc = dofile(wt .. "/lua/json_codec.lua").decode(f:read("a"))
                    f:close()
                end
                local got, h = pcall(function() return gameinfo.getromhash() end)
                rom_sha = got and type(h) == "string" and h:lower() or nil
                local pf = assert(io.open(wt .. "/data/games/gen3_frlg/profile.json", "rb"))
                local profile = dofile(wt .. "/lua/json_codec.lua").decode(pf:read("a")).titles[title]
                pf:close()
                bag = dofile(wt .. "/lua/gen3/reads.lua").new(profile, {
                    read_u8 = function(a) return memory.read_u8(a) end,
                    read_u16 = function(a) return memory.read_u16_le(a) end,
                    read_u32 = function(a) return memory.read_u32_le(a) end,
                    read_bytes = function(a, k)
                        local out = {}
                        for j = 1, k do out[j] = memory.read_u8(a + j - 1) end
                        return out
                    end,
                }, cp.pointers)
            end
        end
        local WIT = P.witnesses(cp, function(a) return memory.read_u8(a) end,
                                function(a) return memory.read_u32_le(a) end)
        P.validate(plan, WIT)
        hook = event.onframeend(function()
            local success, why = pcall(sample)
            if not success then callback_error = tostring(why); if active then active.error = callback_error end end
        end, "SLink-gen3-checkpoint-probe")
        assert(hook and tostring(hook):gsub("[{}]", "") ~= "00000000-0000-0000-0000-000000000000",
            "frame-end registration refused")
        must_load(idle_state)
        local row = begin(1,function() return true end)
        G.idle(300)
        row.reached = field() and row.samples == 300
        finish(row)

        must_load(idle_state)
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
        finish(row)

        must_load(idle_state)
        G.tap("Start",3,30)
        row = begin(3,function() return not G.pred_ok(cp,"field_controls_locked") end)
        G.idle(120); row.reached = row.samples > 0; finish(row)

        must_load(idle_state)
        assert(open_save_dialog(), "save prompt not reached for dialog control")
        row = begin(4,function() return dialog_open() end)
        G.idle(120); row.reached = row.samples > 0; finish(row)

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
        joypad.set({}); row.reached = complete and row.samples > 0; finish(row)

        must_load(os.getenv("SLINK_CHECKPOINT_BATTLE_STATE") or "slink_prebattle.State")
        row = begin(6,function() return not G.pred_ok(cp,"in_battle") end)
        G.idle(120); row.reached = row.samples > 0; finish(row)

        must_load(os.getenv("SLINK_CHECKPOINT_DOOR_STATE") or "slink_door.State")
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
        joypad.set({}); row.reached = changed and field() and row.samples > 0; finish(row)

        if plan[8] then
            -- gba_map 5.4 --bfs 7,8 11,2; PC at (11,1). Five A presses reach the storage menu.
            must_load(os.getenv("SLINK_CHECKPOINT_PC_STATE") or "slink_pokecenter_full.State")
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
            finish(row)
            back_out()
        end

        -- script_running runs BEFORE the reason rows: the last one (bw_n8_item) can end the run.
        if plan[9] then
            local p = cp.predicates.script_context_status
            assert(p and p.address == P.SCRIPT_STATUS and (p.offset or 0) == 0,
                "pack does not bind sGlobalScriptContextStatus at the sym address")
            -- RR: nurse (7,2) behind MB_COUNTER (7,3), talk from (7,4) facing Up (gba_map 5.4).
            -- FR/LG: the Viridian woman from P.SCRIPT_TILE, in the mkstates-built state (C4-PROBE2;
            -- the earlier FR row used an externally made Oak-lab state).
            local rr = title == "radical_red"
            must_load(os.getenv("SLINK_CHECKPOINT_SCRIPT_STATE")
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
            finish(row)
            back_out()
        end

        -- ── C4-B2 reason rows: one generic runner, declarative specs ──────────────────────
        local function bw_wait(name)
            local w = P.BW_WAITS[name]
            return function() return bw_last ~= nil and w(bw_last, bw_ctx) end
        end
        local function no_b(btn)   -- belt and braces over check_inputs: never B in a Pokedude battle
            assert(btn ~= "B" or not (bw_last and (bw_last.type or 0) & bw_ctx.K.BATTLE_TYPE_POKEDUDE ~= 0),
                "B refused while BATTLE_TYPE_POKEDUDE is set")
        end
        local function held_keys() return memory.read_u16_le(bw_ctx.T.GMAIN_CALLBACK2_ADDR + P.HELD_KEYS_OFF) end
        local function bw_steps(spec)
            for n, step in ipairs(spec.inputs) do
                if step.throw_ball then
                    G.phase("helper", spec.name .. " throw_pokeball_from_bag: its own G.finish ends the run here")
                end
                if step.tap then
                    no_b(step.tap)
                    local pressed, why = P.press(step.tap, function(k) joypad.set(k) end, G.advance, held_keys,
                        step.gap or 13)
                    if not pressed then G.log("BWPRESS " .. spec.bw .. " " .. n .. " " .. why) end
                elseif step.idle then G.idle(step.idle)
                elseif step.mash then G.mash(step.mash, bw_wait(step.stop))
                elseif step.wait then
                    local w = bw_wait(step.wait)
                    for _ = 1, step.frames or 600 do if w() then break end; G.advance() end
                elseif step.action then
                    for _ = 1, 4 do
                        local c = memory.read_u8(bw_ctx.T.ACTION_CURSOR_ADDR)
                        if c == step.action then break end
                        if (c & 1) ~= (step.action & 1) then G.tap((c & 1) == 0 and "Right" or "Left", 3, 13)
                        else G.tap((c & 2) == 0 and "Down" or "Up", 3, 13) end
                    end
                elseif step.slot then
                    for _ = 1, 8 do
                        if bw_last and bw_last.pm_slot == step.slot then break end
                        G.tap("Down", 3, 13)
                    end
                elseif step.pulse then
                    no_b(step.pulse)
                    local stop = bw_wait(step.stop)
                    for f = 1, step.frames do
                        if stop() then break end
                        joypad.set(f % 16 == 8 and {[step.pulse] = true} or {})
                        G.advance()
                    end
                    joypad.set({})
                elseif step.throw_ball then
                    SP = SP or dofile(wt .. "/lua/tests/gen3_scripted_play.lua")
                    SP.throw_pokeball_from_bag(cp, spec.name)
                end
                G.log(P.bw_diag("BWSTEP " .. spec.bw .. " " .. n, bw_last))   -- one line per step, not per frame
            end
        end
        -- One bw row: state, steps, hold, then its BWROW verdict and first/bad/terminal receipts,
        -- logged now (not at the end) so a later row cannot lose them.
        local function bw_row(i, spec)
            local path = P.state_path(os.getenv(spec.state_env) or spec.state, os.getenv("SLINK_STATE_DIR"))
            local loaded, why = load(path)
            local row = begin(i, function() return false end)
            row.bw, bw_last = bw_ctx:row(spec.bw), nil
            local meta, mwhy = P.bw_meta(bw_doc, rom_sha, path, spec.bw)
            if not loaded then
                row.blocked = "UNREACHED " .. why
            else
                if not meta then row.blocked = mwhy end
                bw_steps(spec)
                for _ = 1, spec.hold or 180 do G.advance() end
            end
            local acc = row.bw
            row.samples, row.yes, row.no = acc.samples, acc.admitted, acc.samples - acc.admitted
            local line, status = bw_ctx.verdict_line(acc)
            row.reason = row.blocked or status
            G.log(line)
            G.log(P.bw_diag("BWLAST " .. spec.bw, bw_last))
            if meta then
                for _, k in ipairs({"first", "bad", "terminal"}) do
                    if acc[k] then G.log(bw_ctx:receipt(acc[k], meta, acc) .. " at=" .. k .. P.bw_diag("", acc[k])) end
                end
            end
            finish(row)
        end
        for i = P.REASON_BASE, #P.STATES do
            if plan[i] and P.STATES[i].bw then bw_row(i, P.STATES[i])
            elseif plan[i] then
                local spec = P.STATES[i]
                local loaded, why = load(os.getenv(spec.state_env) or spec.state)
                -- until_witness: the mash runs to that state, and the row is only reached there
                local witness, stop = P.row_witness(WIT, spec)
                row = begin(i, witness)
                if not loaded then
                    row.blocked, row.reason = "UNREACHED " .. why, why
                else
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
                end
                finish(row)
            end
        end

    end)
    active = nil
    if hook then pcall(event.unregisterbyid,hook) end
    local passed = P.summary(rows, plan, title, kind, ok and callback_error == nil, G.log)
    -- Not evidence: this probe constructs no writer, so there is nothing to count.
    G.log("WRITE_SURFACE none (predicate-only probe) native_idle=opcode_queue_only")
    G.log(string.format("FRAMES spent=%d budget=%d", G.spent, G.budget))   -- OMP C1
    G.finish(passed, ok and (callback_error or "all checkpoint controls") or tostring(err))
end

if (debug.getinfo(1,"S").source or "") == "main" then P.run() end
return P
