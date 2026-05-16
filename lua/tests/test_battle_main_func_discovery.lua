--[[
  lua/tests/test_battle_main_func_discovery.lua
  =============================================
  Discovers BATTLE_MAIN_FUNC_ADDR and RETURN_FROM_BATTLE_ADDR for CFRU/
  Radical Red — the two nil fields in the radical_red profile in gen3_frlge.lua.

  WHY THIS MATTERS
  ----------------
  SLink uses a fixed 180-frame post-battle cooldown before allowing memorialize
  (party compaction). The correct signal is gBattleMainFunc: CFRU sets it to the
  overworld callback in the SAME instruction sequence that calls EndOfBattleThings,
  so gBattleMainFunc == RETURN_FROM_BATTLE_ADDR is a hardware guarantee that ALL
  post-battle cleanup (FormsRevert, RestoreNonConsumableItems, RecalcStats) is done.

  HOW TO USE
  ----------
  1. Load Radical Red in BizHawk. Load a save in the OVERWORLD.
  2. Open Lua Console and load this script — baseline scan runs automatically.
  3. Enter a battle (wild or trainer — trainer preferred, longer sequence).
  4. Press F1 once during the battle (after the first turn). Monitoring starts
     automatically from that point on every frame — no further input needed.
  5. Play the battle to completion and walk back to the overworld.
  6. Press F2 to print results and the copy-paste profile values.

  OUTPUT
  ------
  Results written to lua/tests/rr_battle_main_func_results.txt
--]]

local fmt = string.format
local r8  = memory.read_u8
local r16 = memory.read_u16_le
local r32 = memory.read_u32_le

-- ── Output file ───────────────────────────────────────────────────────────────

local MANUAL_OUT_PATH = nil  -- override if needed: "C:\\rr_battle_main_func_results.txt"

local _lines  = {}
local OUT_PATH = nil

local function _try_path(p)
    local ok, f = pcall(io.open, p, "w")
    if ok and f then f:write("") f:close() return true end
    return false
end

local function _resolve_out()
    if MANUAL_OUT_PATH and _try_path(MANUAL_OUT_PATH) then return MANUAL_OUT_PATH end
    local ok, info = pcall(debug.getinfo, 1, "S")
    if ok and info and info.source then
        local dir = info.source:match("^@?(.*[\\/])")
        if dir then
            local p = dir .. "rr_battle_main_func_results.txt"
            if _try_path(p) then return p end
        end
    end
    local ok2, rp = pcall(function()
        if gameinfo and gameinfo.getromfilename then return gameinfo.getromfilename() end
    end)
    if ok2 and rp and rp ~= "" then
        local dir = rp:match("^(.*[\\/])")
        if dir then
            local p = dir .. "rr_battle_main_func_results.txt"
            if _try_path(p) then return p end
        end
    end
    if _try_path("rr_battle_main_func_results.txt") then
        return "rr_battle_main_func_results.txt"
    end
end

OUT_PATH = _resolve_out()

local function _flush()
    if not OUT_PATH then return end
    local ok, f = pcall(io.open, OUT_PATH, "w")
    if ok and f then f:write(table.concat(_lines, "\n") .. "\n") f:close() end
end

local function log(s)
    s = s or ""
    table.insert(_lines, s)
    console.log(s)
    _flush()
end

local function sep() log(string.rep("=", 72)) end

-- ── Known CFRU addresses (from radical_red profile) ──────────────────────────

local BATTLE_OUTCOME_ADDR = 0x02023E8A  -- gBattleOutcome (u8)
local BATTLE_MONS_ADDR    = 0x02023BE4  -- gBattleMons base
local BMON0_MAXHP_ADDR    = BATTLE_MONS_ADDR + 0x2C  -- gBattleMons[0].maxHP

-- Vanilla FRLG reference (for orientation only)
local VANILLA_BMF_ADDR    = 0x03004F84
local VANILLA_RFB_ADDR    = 0x08015B59

local IWRAM_BASE = 0x03000000
local IWRAM_END  = 0x03008000

local function is_thumb_rom_ptr(v)
    -- Thumb-mode GBA ROM address: 0x08xxxxxx with bit 0 set
    return (v & 0xFF000001) == 0x08000001
end

-- ── State machine ─────────────────────────────────────────────────────────────
--
--  IDLE          → script just loaded, overworld baseline collected
--  ARMED         → F1 pressed during battle; candidate list built;
--                  per-frame monitoring running automatically every frame
--  DONE          → F2 pressed; analysis printed

local state = "IDLE"

local overworld_snapshot = {}  -- [addr] = value at load time (overworld)
local candidates         = {}  -- [addr] = value at F1 time (during battle)
local prev_vals          = {}  -- [addr] = value seen last frame (for change detection)

-- Per-frame records accumulated during ARMED state
-- Each: { f=frame_num, outcome=u8, maxhp=u16, changes={[addr]={from,to}} }
local records     = {}
local frame_num   = 0
local outcome_frame = nil  -- frame_num when gBattleOutcome first != 0

-- Settle events: { frame_num, addr, from, to, frames_after_outcome }
local settles = {}

-- ── Phase 0: Overworld baseline ───────────────────────────────────────────────

sep()
log("[PHASE 0] Overworld baseline — recording IWRAM Thumb ROM ptrs")

local baseline_n = 0
for addr = IWRAM_BASE, IWRAM_END - 4, 4 do
    local ok, v = pcall(r32, addr)
    if ok and is_thumb_rom_ptr(v) then
        overworld_snapshot[addr] = v
        baseline_n = baseline_n + 1
    end
end
log(fmt("  %d Thumb ROM ptrs found in IWRAM at load time.", baseline_n))
log("")
log("  Instructions:")
log("  1. Enter a battle (trainer preferred).")
log("  2. Press F1 ONCE during the battle — monitoring starts automatically.")
log("  3. Play the battle to the end and return to the overworld.")
log("  4. Press F2 for results.")
sep()

-- ── F1: Arm monitoring ────────────────────────────────────────────────────────

local function do_arm()
    if state ~= "IDLE" then
        console.log("[F1] Already armed — monitoring is running.")
        return
    end

    local outcome = r8(BATTLE_OUTCOME_ADDR)
    local maxhp   = r16(BMON0_MAXHP_ADDR)

    log(fmt("[F1] Arming — outcome=%d  bmon0_maxHP=%d", outcome, maxhp))

    -- Build candidate list: IWRAM addrs holding a Thumb ROM ptr that DIFFERS
    -- from the overworld baseline (overworld-stable ptrs are not gBattleMainFunc).
    -- Always include vanilla reference addr for cross-check.
    local n = 0
    for addr = IWRAM_BASE, IWRAM_END - 4, 4 do
        local ok, v = pcall(r32, addr)
        if ok and is_thumb_rom_ptr(v) then
            local base_v = overworld_snapshot[addr]
            if base_v == nil or base_v ~= v then
                candidates[addr] = v
                prev_vals[addr]  = v
                n = n + 1
            end
        end
    end

    -- Force-include vanilla reference even if unchanged
    do
        local ok, v = pcall(r32, VANILLA_BMF_ADDR)
        if ok and not candidates[VANILLA_BMF_ADDR] then
            candidates[VANILLA_BMF_ADDR] = v
            prev_vals[VANILLA_BMF_ADDR]  = v
            n = n + 1
        end
    end

    log(fmt("  %d candidates armed. Monitoring every frame automatically.", n))
    log("  Play the battle out fully, then press F2 for results.")

    state = "ARMED"
    frame_num = 0
end

-- ── Per-frame automatic monitoring (runs every frame while ARMED) ─────────────

local function monitor_frame()
    frame_num = frame_num + 1

    local outcome = r8(BATTLE_OUTCOME_ADDR)
    local maxhp   = r16(BMON0_MAXHP_ADDR)

    if outcome_frame == nil and outcome ~= 0 then
        outcome_frame = frame_num
        console.log(fmt("[AUTO] gBattleOutcome first non-zero: frame %d (outcome=%d)",
            frame_num, outcome))
    end

    local rec = { f = frame_num, outcome = outcome, maxhp = maxhp, changes = {} }

    for addr, _ in pairs(candidates) do
        local ok, v = pcall(r32, addr)
        if ok then
            local prev = prev_vals[addr]
            if prev ~= nil and prev ~= v then
                rec.changes[addr] = { from = prev, to = v }

                -- Settle: new value is a Thumb ROM ptr, different from arming value
                if is_thumb_rom_ptr(v) and v ~= candidates[addr] then
                    local after = outcome_frame and (frame_num - outcome_frame) or nil
                    table.insert(settles, {
                        frame        = frame_num,
                        addr         = addr,
                        from         = prev,
                        to           = v,
                        after        = after,
                        outcome      = outcome,
                    })
                    console.log(fmt(
                        "[AUTO] SETTLE 0x%08X: 0x%08X→0x%08X  outcome=%d  after_outcome=%s",
                        addr, prev, v, outcome,
                        after ~= nil and tostring(after) or "before_outcome"))
                end
            end
            prev_vals[addr] = v
        end
    end

    records[frame_num] = rec
end

-- ── F2: Analysis ──────────────────────────────────────────────────────────────

local function do_analysis()
    if state == "IDLE" then
        console.log("[F2] Nothing to analyse — press F1 during a battle first.")
        return
    end
    state = "DONE"

    sep()
    log("[PHASE 2] ANALYSIS")
    sep()
    log(fmt("  Frames monitored: %d", frame_num))
    log(fmt("  gBattleOutcome first non-zero at frame: %s",
        outcome_frame and tostring(outcome_frame) or "NOT SEEN"))
    log(fmt("  Settle events recorded: %d", #settles))
    log("")

    -- ── Stability measurement ────────────────────────────────────────────────
    -- For each settle, count how many subsequent frames the new value held.
    local function stability(ev)
        local n = 0
        for fi = ev.frame + 1, frame_num do
            local rec = records[fi]
            if not rec then break end
            if rec.changes[ev.addr] then break end  -- changed again
            n = n + 1
        end
        return n
    end

    -- ── All settle events ─────────────────────────────────────────────────────
    log("  ALL SETTLE EVENTS:")
    log(fmt("  %-12s  %-12s  %-12s  %-8s  %-8s  %s",
        "IWRAM addr", "from", "to", "after_out", "outcome", "stable_frames"))
    for _, ev in ipairs(settles) do
        log(fmt("  0x%08X  0x%08X  0x%08X  %-8s  %-8d  %d",
            ev.addr, ev.from, ev.to,
            ev.after ~= nil and tostring(ev.after) or "n/a",
            ev.outcome,
            stability(ev)))
    end
    log("")

    -- ── Best candidate ────────────────────────────────────────────────────────
    -- Criteria: settled AFTER gBattleOutcome != 0, stable for ≥30 frames.
    local best, best_stab = nil, 0
    for _, ev in ipairs(settles) do
        if ev.after ~= nil and ev.after >= 0 then
            local s = stability(ev)
            if s >= 30 and s > best_stab then
                best = ev
                best_stab = s
            end
        end
    end

    sep()
    if best then
        log("  RESULT:")
        log("")
        log("  ┌──────────────────────────────────────────────────────────────────┐")
        log(fmt("  │  BATTLE_MAIN_FUNC_ADDR   = 0x%08X", best.addr))
        log(fmt("  │  RETURN_FROM_BATTLE_ADDR = 0x%08X", best.to))
        log(fmt("  │"))
        log(fmt("  │  EndOfBattleThings completed %d frames after gBattleOutcome != 0", best.after))
        log(fmt("  │  (current cooldown = 180 frames)"))
        log("  └──────────────────────────────────────────────────────────────────┘")
        log("")
        log("  Copy-paste into gen3_frlge.lua radical_red profile:")
        log(fmt("      BATTLE_MAIN_FUNC_ADDR      = 0x%08X,", best.addr))
        log(fmt("      RETURN_FROM_BATTLE_ADDR    = 0x%08X,  -- set by EndBattleFlagClearHook", best.to))
        log("")
        log(fmt("  Vanilla reference: BATTLE_MAIN_FUNC_ADDR = 0x%08X  (match: %s)",
            VANILLA_BMF_ADDR, best.addr == VANILLA_BMF_ADDR and "YES" or "NO"))
    else
        log("  No confident result yet.")
        log("")
        log("  Tips:")
        log("  • Make sure F1 was pressed DURING the battle (not before or after)")
        log("  • Try a longer battle — more frames = more data")
        log("  • Check settle events above for partial matches")
        if #settles > 0 then
            log("")
            log("  Closest settle (highest stability, any timing):")
            local top, top_s = nil, 0
            for _, ev in ipairs(settles) do
                local s = stability(ev)
                if s > top_s then top = ev top_s = s end
            end
            if top then
                log(fmt("    addr=0x%08X  to=0x%08X  after_outcome=%s  stable=%d frames",
                    top.addr, top.to,
                    top.after ~= nil and tostring(top.after) or "n/a",
                    top_s))
            end
        end
    end

    -- ── Change frequency table (manual review) ───────────────────────────────
    sep()
    log("  CHANGE FREQUENCY (all candidates that changed at least once):")
    log(fmt("  %-12s  %-12s  %-12s  %s",
        "addr", "armed_val", "final_val", "change_count"))

    local freq = {}  -- addr → { count, final }
    for fi = 1, frame_num do
        local rec = records[fi]
        if rec then
            for addr, ch in pairs(rec.changes) do
                if not freq[addr] then freq[addr] = { count = 0, final = ch.to } end
                freq[addr].count = freq[addr].count + 1
                freq[addr].final = ch.to
            end
        end
    end
    for addr, info in pairs(freq) do
        log(fmt("  0x%08X  0x%08X  0x%08X  %d",
            addr,
            candidates[addr] or 0,
            info.final,
            info.count))
    end

    sep()
    log("  Output: " .. (OUT_PATH or "(console only)"))
end

-- ── Key bindings (edge-triggered) ─────────────────────────────────────────────

local _prev_k = {}

event.onframeend(function()
    local keys = input.get()

    if keys.F1 and not _prev_k.F1 then do_arm() end
    if keys.F2 and not _prev_k.F2 then do_analysis() end

    if state == "ARMED" then monitor_frame() end

    _prev_k = keys
end, "bmf_keys")

console.log("[DISCOVERY] Loaded. F1=arm (during battle)  F2=results")
