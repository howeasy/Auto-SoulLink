--[[
  lua/tests/test_memorialize_gate.lua
  ====================================
  Companion diagnostic for the memorialize race condition fix.

  Runs alongside gen3_frlge_client.lua.  For each battle, it measures the gap
  between gBattleOutcome going non-zero and gBattleMainFunc settling to
  RETURN_FROM_BATTLE_ADDR (the signal that EndOfBattleThings() has completed).

  This answers the key question:
    "Would the old 180-frame cooldown have been sufficient for this battle?"

  ADDRESSES (Radical Red / CFRU — confirmed):
    BATTLE_OUTCOME_ADDR     = 0x02023E8A
    BATTLE_MAIN_FUNC_ADDR   = 0x03004F84
    RETURN_FROM_BATTLE_ADDR = 0x08015B59

  HOW TO USE
  ----------
  1. Load Radical Red in BizHawk with gen3_frlge_client.lua running.
  2. Open a SECOND Lua Console tab and load this script.
  3. Play normally.  Every battle is tracked automatically.
  4. Results print to the console after each battle ends.
     Pay attention to battles where a linked mon dies — those are where
     the race condition would have fired.
  5. Press F1 at any time for a summary of all battles recorded so far.

  WHAT TO LOOK FOR
  ----------------
  - gap_frames > 180 → the old cooldown would have been INSUFFICIENT
  - gap_frames > 0   → EndOfBattleThings still took N frames after outcome
  - cooldown_sufficient = false → the fix was necessary for this battle
]]

local BATTLE_OUTCOME_ADDR     = 0x02023E8A
local BATTLE_MAIN_FUNC_ADDR   = 0x03004F84
local RETURN_FROM_BATTLE_ADDR = 0x08015B59
local OLD_COOLDOWN_FRAMES     = 180

local mem_u8  = memory.read_u8
local mem_u32 = memory.read_u32_le

-- ── State ─────────────────────────────────────────────────────────────────────
local state = "overworld"  -- "overworld" | "in_battle" | "post_battle"
local outcome_frame    = nil   -- frame when gBattleOutcome first went non-zero
local outcome_value    = nil
local signal_frame     = nil   -- frame when gBattleMainFunc settled to RETURN_FROM_BATTLE_ADDR
local prev_outcome     = 0
local prev_main_func   = nil
local current_frame    = 0
local battle_count     = 0
local results          = {}   -- array of result tables

-- ── Result record ─────────────────────────────────────────────────────────────
local function record_result(gap)
    local r = {
        battle_num         = battle_count,
        outcome            = outcome_value,
        outcome_frame      = outcome_frame,
        signal_frame       = signal_frame or -1,
        gap_frames         = gap,
        cooldown_sufficient = (gap <= OLD_COOLDOWN_FRAMES),
        worst_case_note    = (gap > OLD_COOLDOWN_FRAMES) and "*** RACE CONDITION POSSIBLE WITH OLD CODE ***" or "",
    }
    table.insert(results, r)
    return r
end

-- ── Per-battle summary print ──────────────────────────────────────────────────
local function print_result(r)
    local outcome_str = ({[1]="WON",[2]="LOST",[3]="RAN",[4]="RAN",[5]="MON_FLED",[6]="CAUGHT",[7]="CAUGHT"})[r.outcome] or ("outcome="..r.outcome)
    console.log(string.format(
        "[MEMGATE] Battle %d  %-22s  gap=%d frames  %s%s",
        r.battle_num,
        outcome_str,
        r.gap_frames,
        r.cooldown_sufficient and "180f cooldown OK" or "!!! 180f cooldown INSUFFICIENT !!!",
        r.gap_frames == 0 and "  (signal already set at outcome)" or ""))
    if not r.cooldown_sufficient then
        console.log(string.format(
            "[MEMGATE]   -> EndOfBattleThings finished %d frames AFTER the 180f window",
            r.gap_frames - OLD_COOLDOWN_FRAMES))
    end
end

-- ── Summary (F1) ──────────────────────────────────────────────────────────────
local function print_summary()
    console.log("========================================================================")
    console.log(string.format("[MEMGATE] SUMMARY  %d battles recorded", #results))
    console.log("========================================================================")
    if #results == 0 then
        console.log("  No battles recorded yet.")
        return
    end
    local max_gap, max_battle = 0, nil
    local races = 0
    for _, r in ipairs(results) do
        if r.gap_frames > max_gap then max_gap = r.gap_frames; max_battle = r end
        if not r.cooldown_sufficient then races = races + 1 end
    end
    console.log(string.format("  Max gap      : %d frames (battle %d)",
        max_gap, max_battle and max_battle.battle_num or 0))
    console.log(string.format("  Races avoided: %d battles would have fired too early with old code",
        races))
    console.log(string.format("  180f margin  : %d frames headroom in worst case",
        OLD_COOLDOWN_FRAMES - max_gap))
    console.log("========================================================================")
    console.log("  All battles:")
    for _, r in ipairs(results) do
        local outcome_str = ({[1]="WON",[2]="LOST",[3]="RAN",[4]="RAN",[5]="MON_FLED",[6]="CAUGHT",[7]="CAUGHT"})[r.outcome] or tostring(r.outcome)
        console.log(string.format("    #%d  %-8s  gap=%d  %s",
            r.battle_num, outcome_str, r.gap_frames,
            r.cooldown_sufficient and "OK" or "!!! INSUFFICIENT !!!"))
    end
    console.log("========================================================================")
end

-- ── Per-frame logic ───────────────────────────────────────────────────────────
event.onframeend(function()
    current_frame = current_frame + 1
    local outcome   = mem_u8(BATTLE_OUTCOME_ADDR)
    local main_func = mem_u32(BATTLE_MAIN_FUNC_ADDR)

    if state == "overworld" then
        -- Detect battle start: outcome resets to 0 and main_func stops being overworld
        if outcome == 0 and main_func ~= RETURN_FROM_BATTLE_ADDR then
            state = "in_battle"
            battle_count = battle_count + 1
            outcome_frame = nil
            signal_frame  = nil
            outcome_value = nil
            prev_outcome  = 0
            console.log(string.format("[MEMGATE] Battle %d START  frame=%d",
                battle_count, current_frame))
        end

    elseif state == "in_battle" then
        -- Detect outcome becoming non-zero
        if outcome ~= 0 and prev_outcome == 0 then
            outcome_frame = current_frame
            outcome_value = outcome
            console.log(string.format("[MEMGATE] Battle %d  outcome=%d at frame %d",
                battle_count, outcome, current_frame))
        end

        -- Detect signal: gBattleMainFunc settles to RETURN_FROM_BATTLE_ADDR
        if outcome_frame and main_func == RETURN_FROM_BATTLE_ADDR and prev_main_func ~= RETURN_FROM_BATTLE_ADDR then
            signal_frame = current_frame
            local gap = signal_frame - outcome_frame
            local r = record_result(gap)
            print_result(r)
            state = "post_battle"
        end

        -- Safety: if we return to overworld without seeing the signal
        if outcome_frame and main_func == RETURN_FROM_BATTLE_ADDR and state == "in_battle" then
            -- already handled above
        end

    elseif state == "post_battle" then
        -- Wait for gBattleMainFunc to leave RETURN_FROM_BATTLE_ADDR momentarily (battle
        -- start) — OR detect a new battle cycle.  In overworld gBattleMainFunc stays at
        -- RETURN_FROM_BATTLE_ADDR indefinitely, so we use outcome = 0 as the reset.
        if outcome == 0 and main_func ~= RETURN_FROM_BATTLE_ADDR then
            state = "in_battle"
            battle_count = battle_count + 1
            outcome_frame = nil
            signal_frame  = nil
            outcome_value = nil
            prev_outcome  = 0
            console.log(string.format("[MEMGATE] Battle %d START  frame=%d",
                battle_count, current_frame))
        elseif outcome == 0 then
            -- Back to stable overworld
            state = "overworld"
        end
    end

    prev_outcome  = outcome
    prev_main_func = main_func
end)

-- ── F1: Print summary ─────────────────────────────────────────────────────────
event.onmemoryexecute(function()
    print_summary()
end, client.getregister and 0 or 0)  -- placeholder; replaced by hotkey below

local function setup_hotkey()
    if event and event.onkeydown then
        event.onkeydown(function(key)
            if key == "F1" then print_summary() end
        end)
    end
end
setup_hotkey()

-- ── Startup ───────────────────────────────────────────────────────────────────
console.log("========================================================================")
console.log("[MEMGATE] Memorialize gate diagnostic loaded")
console.log(string.format("  BATTLE_OUTCOME_ADDR     = 0x%08X", BATTLE_OUTCOME_ADDR))
console.log(string.format("  BATTLE_MAIN_FUNC_ADDR   = 0x%08X", BATTLE_MAIN_FUNC_ADDR))
console.log(string.format("  RETURN_FROM_BATTLE_ADDR = 0x%08X", RETURN_FROM_BATTLE_ADDR))
console.log(string.format("  Old cooldown threshold  = %d frames", OLD_COOLDOWN_FRAMES))
console.log("")
console.log("  Monitoring every battle automatically.")
console.log("  Press F1 for a summary of all battles recorded.")
console.log("  gap > 180 = old code would have been INSUFFICIENT")
console.log("========================================================================")
