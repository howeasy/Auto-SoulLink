--[[
  lua/tests/test_faint_counter_gate.lua
  ======================================
  Companion diagnostic for the gBattleResults.playerFaintCounter fast-path
  that replaces the 3-frame FAINT_DEBOUNCE_FRAMES timer when the profile
  exposes BATTLE_RESULTS_ADDR.

  For each battle, it watches the player party for HP transitions to 0 and
  measures the frame gap between:
    • HP=0 first observed in the party struct, and
    • gBattleResults.playerFaintCounter actually incrementing (which only
      happens after Cmd_tryfaintmon commits, i.e. after Sturdy/Focus Sash/
      Endure protection has resolved).

  This answers:
    "Would the new fast-path fire on the same frame as HP=0, or later?
     How much faster than the 3-frame timer is it?"

  ADDRESSES
    BATTLE_RESULTS_ADDR              = 0x03004F90  (gBattleResults, IWRAM)
    BATTLE_RESULTS_PLAYER_FAINTS_OFF = 0x00
    BATTLE_RESULTS_FOE_FAINTS_OFF    = 0x01

  Source: pret/pokefirered include/battle.h (BattleResults struct);
          CFRU include/new/ram_locs_battle.h (preserved address).

  HOW TO USE
  ----------
  1. Load FRLG (vanilla or CFRU/RR) in BizHawk with gen3_frlge_client.lua
     running in one console tab.
  2. Open a SECOND Lua Console tab and load this script.
  3. Play through any wild or trainer battle.
  4. After the battle, results print: gap_frames per faint, plus whether
     the new fast-path would have shaved frames off the old 3-frame timer.
  5. F1 at any time = summary of all faints recorded so far.
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
package.path = _src .. "?.lua;" .. _lua_root .. "?.lua;" .. package.path

local M = require("memory_gba")
local game_detect = require("game_detect")

local detected = game_detect.detect()
if detected and detected.profile then
    M.applyProfile(detected.profile, detected.variant)
end

if not M.BATTLE_RESULTS_ADDR then
    console.log("[FAINT-GATE] Profile '" .. tostring(detected and detected.variant or "?")
        .. "' has no BATTLE_RESULTS_ADDR. Fast-path is disabled on this profile; "
        .. "the 3-frame timer remains in effect. Exiting.")
    return
end

console.log(string.format(
    "[FAINT-GATE] Watching gBattleResults @ 0x%08X (profile=%s).",
    M.BATTLE_RESULTS_ADDR, detected and detected.variant or "?"))
console.log("[FAINT-GATE] Press F1 for summary.")

local mem_u8 = memory.read_u8

-- ── per-faint record ──────────────────────────────────────────────────────────
local records = {}
local battle_count = 0

-- ── per-battle state ─────────────────────────────────────────────────────────
local in_battle_prev = false
local start_pfc      = 0
local start_ofc      = 0
local pending        = {}    -- [slot] = {hp0_frame=<n>}
local last_pfc       = 0
local current_frame  = 0

local FAINT_DEBOUNCE_FRAMES = 3  -- mirror gen3_frlge_client.lua constant

local function read_counters()
    return M.readFaintCounters()
end

local function read_party_hp(slot)
    if not M.PARTY_BASE then return nil end
    local base = M.PARTY_BASE + slot * M.MON_SIZE
    local maxHP = memory.read_u16_le(base + M.OFF_MAX_HP)
    if maxHP == 0 then return nil end
    return memory.read_u16_le(base + M.OFF_HP)
end

-- ── frame callback ────────────────────────────────────────────────────────────
local function on_frame()
    current_frame = current_frame + 1
    local in_battle = M.isInBattle and M.isInBattle() or false

    -- Battle start
    if in_battle and not in_battle_prev then
        battle_count = battle_count + 1
        start_pfc, start_ofc = read_counters()
        last_pfc = start_pfc or 0
        pending = {}
        console.log(string.format(
            "[FAINT-GATE] Battle %d START frame=%d  pfc_start=%d  ofc_start=%d",
            battle_count, current_frame, start_pfc or -1, start_ofc or -1))
    end

    -- In-battle: poll party HP, track HP→0 entry, and counter increments
    if in_battle then
        local count = memory.read_u8(M.PARTY_COUNT_ADDR)
        local curr_pfc = (read_counters())
        if curr_pfc == nil then curr_pfc = last_pfc end

        for slot = 0, count - 1 do
            local hp = read_party_hp(slot)
            if hp == 0 and not pending[slot] then
                pending[slot] = {hp0_frame = current_frame}
            elseif hp and hp > 0 and pending[slot] then
                -- HP recovered (Sturdy/Endure/etc.) — clear without recording.
                console.log(string.format(
                    "[FAINT-GATE]   slot=%d HP recovered after %d frame(s) (transient — Sturdy/Endure?)",
                    slot, current_frame - pending[slot].hp0_frame))
                pending[slot] = nil
            end
        end

        -- Counter incremented this tick — credit one pending slot.
        if curr_pfc > last_pfc then
            local delta = curr_pfc - last_pfc
            for _ = 1, delta do
                -- Pick the oldest pending slot.
                local oldest_slot, oldest_frame = nil, math.huge
                for slot, info in pairs(pending) do
                    if info.hp0_frame < oldest_frame then
                        oldest_slot, oldest_frame = slot, info.hp0_frame
                    end
                end
                if oldest_slot then
                    local gap = current_frame - oldest_frame
                    table.insert(records, {
                        battle_num = battle_count,
                        slot       = oldest_slot,
                        gap_frames = gap,
                        fast_wins  = gap < FAINT_DEBOUNCE_FRAMES,
                    })
                    console.log(string.format(
                        "[FAINT-GATE]   slot=%d FAINT confirmed via counter delta — gap=%d frame(s) (timer would have waited %d)",
                        oldest_slot, gap, FAINT_DEBOUNCE_FRAMES))
                    pending[oldest_slot] = nil
                end
            end
            last_pfc = curr_pfc
        end
    end

    -- Battle end
    if not in_battle and in_battle_prev then
        local pfc_end, ofc_end = read_counters()
        console.log(string.format(
            "[FAINT-GATE] Battle %d END  pfc=%d→%d  ofc=%d→%d",
            battle_count, start_pfc or -1, pfc_end or -1,
            start_ofc or -1, ofc_end or -1))
        pending = {}
    end

    in_battle_prev = in_battle
end

-- ── F1: summary ───────────────────────────────────────────────────────────────
local function summary()
    console.log("---- [FAINT-GATE] summary ----")
    if #records == 0 then
        console.log("[FAINT-GATE] No faints recorded yet.")
        return
    end
    local total, fast_wins, sum_gap = 0, 0, 0
    for _, r in ipairs(records) do
        total = total + 1
        sum_gap = sum_gap + r.gap_frames
        if r.fast_wins then fast_wins = fast_wins + 1 end
        console.log(string.format(
            "  battle=%d slot=%d gap=%d  fast_path_wins=%s",
            r.battle_num, r.slot, r.gap_frames, tostring(r.fast_wins)))
    end
    console.log(string.format(
        "[FAINT-GATE] %d faints, fast-path beat the 3-frame timer in %d (%.0f%%).  avg gap=%.2f frames.",
        total, fast_wins, 100 * fast_wins / total, sum_gap / total))
end

local prev_keys = {}
event.onframeend(function()
    on_frame()
    local ok, keys = pcall(input.get)
    if ok and keys then
        if keys.F1 and not prev_keys.F1 then summary() end
        prev_keys = keys
    end
end)

console.log("[FAINT-GATE] Ready. Engage in battles.")
console.log("[FAINT-GATE]   F1 (in BizHawk EMU WINDOW, not Lua Console) = summary")
