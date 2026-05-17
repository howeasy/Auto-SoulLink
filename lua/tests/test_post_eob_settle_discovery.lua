--[[
  lua/tests/test_post_eob_settle_discovery.lua
  ============================================
  Discovers entries for the POST_BATTLE_WRITER_TASKS set in the active
  ROM profile. These are priority-10 task `func` pointers placed in
  gTasks[].func during post-battle exp distribution and level-up animation
  — the writes responsible for the Brock-fight item-swap bug that
  POST_EOB_SAFETY_CAP (formerly POST_EOB_DELAY) was added to mask.

  WHY THIS MATTERS
  ----------------
  M.isPostBattleSettled() in lua/memory_gba.lua reads gTasks[].func every
  frame post-EOB and gates sync writes until no priority-10 task is in
  POST_BATTLE_WRITER_TASKS. CFRU forks the exp-distribution path by
  level-cap state (and possibly other context), so the priority-10 slot
  can hold different function pointers across battles. Run this script
  on multiple battle types — at-cap, under-cap, with-levelup, with-
  evolution — and union the discovered addresses into the profile.

  HOW TO USE
  ----------
  1. Load the ROM (vanilla FR/LG, AP, or Radical Red) in BizHawk.
  2. Load a save in the OVERWORLD with a starter low enough to level up.
  3. Open Lua Console and load this script — it picks up TASKS_BASE_ADDR
     and TASK_STRUCT_SIZE from the active profile via lua/memory_gba.lua.
  4. Enter ANY battle that will produce a level-up (winning gives exp;
     a low-level starter vs a Pidgey is fine). Trainer battles work too.
  5. Win the battle and walk back to the overworld.
  6. Press F2 to print results and the copy-paste profile snippet.

  OUTPUT
  ------
  Lists every unique non-NULL `func` pointer that appeared in any gTasks[]
  slot from battle-end onward, with priority byte and active window.
  Filtering rules used to flag the Task_GiveExpToMon candidate:
    1. Priority must equal 10 (CFRU exp.c:648 — CreateTask(.., 10)).
    2. Task must NOT still be active in the last 60 frames of the settle
       window — those are overworld-resident (Task_WeatherMain etc.).
    3. Task must have been active in the first 90 frames of settle —
       exp distribution starts right after EOB-clear.

  Results written to lua/tests/post_eob_settle_results.txt.
--]]

local fmt = string.format
local r8  = memory.read_u8
local r32 = memory.read_u32_le

-- struct Task layout (pret/pokefirered include/task.h):
--   +0x00  TaskFunc func    (u32, with thumb bit)
--   +0x04  bool8 isActive
--   +0x05  u8 prev
--   +0x06  u8 next
--   +0x07  u8 priority      ← Task_GiveExpToMon is created with priority 10
--   +0x08  s16 data[16]
local TASK_PRIORITY_OFF = 7
local TASK_EXP_PRIORITY = 10

-- ── Load the active profile so we know where gTasks lives ────────────────────

local _dir = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
package.path = _dir .. "..\\?.lua;" .. _dir .. "../?.lua;" .. package.path
local M = require("memory_gba")
local game_detect = require("game_detect")
local detected = game_detect.detect()
M.applyProfile(detected.profile, detected.variant)

if not M.TASKS_BASE_ADDR then
    console.log("[discovery] TASKS_BASE_ADDR is nil for profile '" .. tostring(M.profile_name)
                .. "'. This profile cannot use isPostBattleSettled — exiting.")
    return
end

local TASKS_BASE = M.TASKS_BASE_ADDR
local TASK_SIZE  = M.TASK_STRUCT_SIZE or 40
local NUM_TASKS  = 16

console.log(fmt("[discovery] profile=%s gTasks=0x%08X task_size=%d (16 tasks → %d bytes)",
                M.profile_name, TASKS_BASE, TASK_SIZE, TASK_SIZE * NUM_TASKS))

-- ── Output file ──────────────────────────────────────────────────────────────

local _lines = {}
local OUT_PATH

local function _try_path(p)
    local ok, f = pcall(io.open, p, "w")
    if ok and f then f:write("") f:close() return true end
    return false
end

do
    local p1 = _dir .. "post_eob_settle_results.txt"
    if _try_path(p1) then OUT_PATH = p1
    elseif _try_path("post_eob_settle_results.txt") then
        OUT_PATH = "post_eob_settle_results.txt"
    end
end

local function log(line)
    _lines[#_lines + 1] = line
    console.log(line)
end

local function flush()
    if not OUT_PATH then return end
    local ok, f = pcall(io.open, OUT_PATH, "w")
    if ok and f then f:write(table.concat(_lines, "\n") .. "\n") f:close() end
end

-- ── State machine ────────────────────────────────────────────────────────────
-- Three phases:
--   "idle"   — overworld pre-battle, ignore tasks
--   "battle" — in a battle, ignore tasks (we only care post-EOB writes)
--   "settle" — battle just ended; record tasks until next overworld idle

local phase            = "idle"
local was_in_battle    = false
local settle_frames    = 0
local SETTLE_MAX       = 60 * 30  -- 30s safety cap; user should reach overworld first
local task_records     = {}        -- [func_addr] = { count, first, last, priority_seen }
local frame_no         = 0

local function in_battle_now()
    if M.isInBattle then return M.isInBattle() end
    return false
end

local function gMainFunc_returned()
    if not (M.BATTLE_MAIN_FUNC_ADDR and M.RETURN_FROM_BATTLE_ADDR) then
        return false
    end
    return r32(M.BATTLE_MAIN_FUNC_ADDR) == M.RETURN_FROM_BATTLE_ADDR
end

local function scan_tasks()
    for i = 0, NUM_TASKS - 1 do
        local base = TASKS_BASE + i * TASK_SIZE
        local fn   = r32(base)
        if fn ~= 0 then
            local pri = r8(base + TASK_PRIORITY_OFF)
            local rec = task_records[fn]
            if not rec then
                rec = { count = 0, first = settle_frames, last = settle_frames, priorities = {} }
                task_records[fn] = rec
            end
            rec.count = rec.count + 1
            rec.last  = settle_frames
            rec.priorities[pri] = (rec.priorities[pri] or 0) + 1
        end
    end
end

-- ── F2: dump results ─────────────────────────────────────────────────────────

local function priorities_str(priorities)
    -- Format the set of priority bytes seen for this task, e.g. "10" or "0/10".
    local parts = {}
    for p, _ in pairs(priorities) do parts[#parts + 1] = p end
    table.sort(parts)
    for i, p in ipairs(parts) do parts[i] = tostring(p) end
    return table.concat(parts, "/")
end

local function dump_results()
    log("")
    log("══════════════════════════════════════════════════════════════════════")
    log(fmt("Discovery report — profile=%s", M.profile_name))
    log(fmt("Frames sampled in post-EOB settle: %d", settle_frames))
    log("──────────────────────────────────────────────────────────────────────")
    -- Build sorted list
    local sorted = {}
    for fn, rec in pairs(task_records) do
        sorted[#sorted + 1] = {
            fn         = fn,
            count      = rec.count,
            first      = rec.first,
            last       = rec.last,
            priorities = rec.priorities,
        }
    end
    table.sort(sorted, function(a, b) return a.count > b.count end)
    if #sorted == 0 then
        log("No tasks observed during settle. Possible causes:")
        log("  • Battle did not produce exp gain (capture/run-away skip exp)")
        log("  • Script was loaded after battle ended")
        log("  • TASKS_BASE_ADDR is wrong for this profile")
        flush()
        return
    end

    -- Classify tasks. A task is a "post-battle writer" candidate if:
    --   • priority 10 was observed at least once (exp task signature), AND
    --   • last_seen is well before the end of settle (not overworld-resident).
    local OVERWORLD_TAIL = 60   -- last 60 frames of settle = overworld noise
    local EARLY_HEAD     = 90   -- first 90 frames = post-battle window
    local cutoff_last    = math.max(0, settle_frames - OVERWORLD_TAIL)
    local candidates     = {}
    for _, e in ipairs(sorted) do
        local has_pri_10 = e.priorities[TASK_EXP_PRIORITY] and e.priorities[TASK_EXP_PRIORITY] > 0
        local ended_early = e.last < cutoff_last
        local started_early = e.first < EARLY_HEAD
        if has_pri_10 and ended_early and started_early then
            candidates[#candidates + 1] = e
        end
    end

    -- Helper: does the active profile already know about this address?
    local known = {}
    if M.POST_BATTLE_WRITER_TASKS then
        for _, addr in ipairs(M.POST_BATTLE_WRITER_TASKS) do known[addr] = true end
    end

    log("All tasks observed during settle:")
    log(" func (RAM, +thumb)    frames  first  last   priorities")
    for _, e in ipairs(sorted) do
        local note = ""
        if known[e.fn] then
            note = note .. "  ← already in profile POST_BATTLE_WRITER_TASKS"
        end
        local is_candidate = false
        for _, c in ipairs(candidates) do
            if c.fn == e.fn then is_candidate = true; break end
        end
        if is_candidate then note = note .. "  ★ exp/lvl candidate" end
        log(fmt(" 0x%08X       %6d  %5d  %5d   %s%s",
                e.fn, e.count, e.first, e.last, priorities_str(e.priorities), note))
    end
    log("──────────────────────────────────────────────────────────────────────")
    log(fmt("Candidates (priority 10, started in first %d frames, ended >%d frames before settle end):",
            EARLY_HEAD, OVERWORLD_TAIL))
    if #candidates == 0 then
        log("  (none — see troubleshooting at bottom)")
    else
        for _, e in ipairs(candidates) do
            local tag = known[e.fn] and " (already in profile)" or " (NEW)"
            log(fmt("  0x%08X  frames=%d  first=%d  last=%d%s",
                    e.fn, e.count, e.first, e.last, tag))
        end
    end
    log("──────────────────────────────────────────────────────────────────────")
    log("Copy-paste snippet for lua/games/gen3_frlge.lua under the active profile.")
    log("Merge any NEW candidates into the existing POST_BATTLE_WRITER_TASKS list:")
    log("")
    local new_ones = {}
    for _, e in ipairs(candidates) do
        if not known[e.fn] then new_ones[#new_ones + 1] = e.fn end
    end
    log("        POST_BATTLE_WRITER_TASKS     = {")
    -- Existing entries first
    if M.POST_BATTLE_WRITER_TASKS then
        for _, addr in ipairs(M.POST_BATTLE_WRITER_TASKS) do
            log(fmt("            0x%08X,   -- already in profile", addr))
        end
    end
    -- New ones
    for _, addr in ipairs(new_ones) do
        log(fmt("            0x%08X,   -- NEW from this run", addr))
    end
    log("        },")
    log("")
    if #new_ones == 0 and #candidates == 0 then
        log("TROUBLESHOOTING (no priority-10 short-lived task found):")
        log("  • Try a battle that DEFEATS a wild Pokémon (capture/run gives no exp).")
        log("  • Try a battle that LEVELS UP an active mon (more frames of activity).")
        log("  • Press F2 within ~2s of the screen returning to overworld so the")
        log("    settle window stays focused on the post-battle phase.")
        log("  • If a 0x09xxxxxx address appears with priority 10 but ends LATE,")
        log("    it may still be the right answer — CFRU's level-up animation can")
        log("    bridge into overworld. Inspect that row manually.")
    elseif #new_ones == 0 then
        log("(All candidates are already in the profile — no changes needed for this run.)")
    end
    log("──────────────────────────────────────────────────────────────────────")
    log(fmt("Results written to: %s", OUT_PATH or "(no writable path)"))
    flush()
end

-- ── Per-frame hook ───────────────────────────────────────────────────────────

local function tick()
    frame_no = frame_no + 1
    local in_b = in_battle_now()
    if phase == "idle" then
        if in_b then phase = "battle" end
    elseif phase == "battle" then
        if not in_b then
            -- Battle ended (isInBattle just flipped false). Enter settle
            -- immediately — Task_GiveExpToMon runs BETWEEN this transition
            -- and gBattleMainFunc's return, so waiting for EOB-clear here
            -- would miss the exp task entirely.
            phase         = "settle"
            settle_frames = 0
            log(fmt("[discovery] entering settle phase at frame %d (isInBattle false; gBattleMainFunc returned=%s)",
                    frame_no, tostring(gMainFunc_returned())))
        end
    elseif phase == "settle" then
        settle_frames = settle_frames + 1
        scan_tasks()
        if in_b or settle_frames >= SETTLE_MAX then
            log(fmt("[discovery] exiting settle phase at frame %d (settle_frames=%d, in_battle=%s)",
                    frame_no, settle_frames, tostring(in_b)))
            dump_results()
            phase = "idle"
        end
    end
    was_in_battle = in_b
end

-- ── Register hooks ───────────────────────────────────────────────────────────

event.onframeend(tick)
event.onmemoryexecute = event.onmemoryexecute  -- unused; kept for symmetry

local function on_f2()
    log("[discovery] F2 pressed — forcing results dump.")
    dump_results()
end

local ok_input = pcall(function()
    event.onkeyup = event.onkeyup or function() end
end)

-- Poll F2 in tick() (BizHawk Lua doesn't expose proper key callbacks across versions)
local _prev_f2 = false
event.onframeend(function()
    local ok, keys = pcall(input.get)
    if not ok or not keys then return end
    local pressed = keys.F2 == true
    if pressed and not _prev_f2 then on_f2() end
    _prev_f2 = pressed
end)

log(fmt("[discovery] script loaded. profile=%s. Enter a battle, win it, walk to overworld, press F2.",
        M.profile_name))
flush()
