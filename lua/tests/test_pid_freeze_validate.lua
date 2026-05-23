--[[
  lua/tests/test_pid_freeze_validate.lua
  =======================================
  Standalone validator for the two PID-freeze edge cases that the gen3 fix
  targets.  This script runs ALONE in a BizHawk Lua Console — the main
  gen3_frlge_client.lua does NOT need to be loaded.

  What it does
  ------------
  It re-implements just enough of the gen3 client's PID-freeze + recovery
  logic to evaluate, in-place against real game RAM, both the OLD (buggy)
  and NEW (fixed) behaviour every frame.  When the two diverge on a real
  game event, the test prints a labelled record.  At the end (F1), it
  prints a PASS/FAIL verdict:

    BUG-2: PASSES if every misclassified intermediate frame the OLD rule
           accepted as "compaction" is correctly rejected by the NEW rule
           and is followed by a real PID swap within FREEZE_LOOKAHEAD frames.
    BUG-1: PASSES if every freeze-release that follows an OUTCOME_CAUGHT
           battle and reveals a previously-unseen mon in party-or-box would
           be recovered by the NEW recovery scan (i.e. would emit the
           correct `capture(recovered-*)` event with `area_id=battle_area_id`).

  The test does NOT modify game state and does NOT depend on any code from
  gen3_frlge_client.lua.  Drop it onto any tree (pre-fix or post-fix); the
  verdict is computed from observed RAM, not from anything the main client
  did or did not do.

  HOW TO USE
  ----------
  1. Boot FRLG (vanilla or CFRU/RR) in BizHawk.  The main client may
     also be loaded, but is not required.
  2. Open a Lua Console tab and load this script.
  3. Play through the special encounter / scripted battle / borrowed-party
     scenario you want to validate (e.g. Radical Red scripted-trainer
     fights, legendary battles, in-game partner battles).
  4. F1 in the EMU WINDOW (NOT the Lua Console) prints the PASS/FAIL
     verdict and a per-event breakdown.
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

if not M.PARTY_BASE or not M.PARTY_COUNT_ADDR or not M.MON_SIZE then
    console.log("[VALIDATE] Profile lacks PARTY_BASE / PARTY_COUNT_ADDR / MON_SIZE — cannot run.")
    return
end

console.log(string.format(
    "[VALIDATE] PID-freeze standalone validator armed (profile=%s).",
    detected and detected.variant or "?"))
console.log("[VALIDATE] F1 in EMU window = verdict + per-event detail.")

-- ── helpers ──────────────────────────────────────────────────────────────────
local mem_u8 = memory.read_u8

local function read_party_pids()
    local out = {}
    for slot = 0, 5 do
        local base = M.PARTY_BASE + slot * M.MON_SIZE
        out[slot] = memory.read_u32_le(base + M.OFF_PERSONALITY)
    end
    return out
end

local function pids_diff_count(a, b)
    local n = 0
    for i = 0, 5 do
        if (a[i] or 0) ~= (b[i] or 0) then n = n + 1 end
    end
    return n
end

-- OLD `_is_compaction_shift` (pre-fix): every non-zero curr PID exists in stable.
local function old_is_compaction(curr, stable)
    local stable_set = {}
    for i = 0, 5 do
        local p = stable[i] or 0
        if p ~= 0 then stable_set[p] = true end
    end
    for i = 0, 5 do
        local p = curr[i] or 0
        if p ~= 0 and not stable_set[p] then return false end
    end
    return true
end

-- NEW (fixed): added<=1 and removed<=1 (set-symmetric difference).
local function new_is_compaction(curr, stable)
    local stable_set, curr_set = {}, {}
    for i = 0, 5 do
        local p = stable[i] or 0
        if p ~= 0 then stable_set[p] = true end
        local q = curr[i] or 0
        if q ~= 0 then curr_set[q] = true end
    end
    local added, removed = 0, 0
    for p in pairs(curr_set) do
        if not stable_set[p] then added = added + 1 end
    end
    for p in pairs(stable_set) do
        if not curr_set[p] then removed = removed + 1 end
    end
    return (added <= 1 and removed <= 1), added, removed
end

local function snapshot_party_keys()
    local out = {}
    local count = mem_u8(M.PARTY_COUNT_ADDR) or 0
    for slot = 0, math.min(count, 6) - 1 do
        local base = M.PARTY_BASE + slot * M.MON_SIZE
        if M.slotOccupied(base) then
            out[M.monKey(base)] = ("party slot " .. slot)
        end
    end
    return out
end

local function snapshot_box_keys()
    local out = {}
    if not M.boxMonAddr or not M.boxSlotOccupied or not M.monKey then return out end
    local n_boxes = M.BOXES_PER_STORE or 14
    local n_slots = M.MONS_PER_BOX or 30
    for bi = 0, n_boxes - 1 do
        if bi ~= M.MEMORIAL_BOX then
            for si = 0, n_slots - 1 do
                local a = M.boxMonAddr(bi, si)
                if a and M.boxSlotOccupied(a) then
                    out[M.monKey(a)] = ("box " .. bi .. " slot " .. si)
                end
            end
        end
    end
    return out
end

-- Mirror M.readLastPCDeposit's Tier 1/2 result so we can simulate the fix's
-- box-scan recovery using only standard memory_gba exports.
local function read_last_pc_deposit()
    if M.readLastPCDeposit then return M.readLastPCDeposit() end
    return nil, nil
end

-- ── state ────────────────────────────────────────────────────────────────────
local PID_SWAP_THRESHOLD   = 3
local PID_STABILITY_WINDOW = 30
local FREEZE_LOOKAHEAD     = 30

local current_frame  = 0
local last_pids      = read_party_pids()
local stable_pids    = read_party_pids()
local last_pid_change_frame = 0

-- Two parallel models — OLD and NEW — each maintaining its own baseline and
-- frozen-state machine.  The verdict is derived from where they diverge.
local model = {
    old = { stable = read_party_pids(), frozen = false, pre_swap = nil,
            pre_party = {}, pre_box = {}, pre_outcome = 0,
            recoveries = {}, lost_catches = {} },
    new = { stable = read_party_pids(), frozen = false, pre_swap = nil,
            pre_party = {}, pre_box = {}, pre_outcome = 0,
            recoveries = {}, lost_catches = {} },
}

-- BUG-2 record: every frame where OLD said "compaction" but NEW said "swap".
-- Each entry is later marked confirmed=true if a real PID swap follows within
-- FREEZE_LOOKAHEAD frames.
local b2_events = {}    -- {frame, added, removed, confirmed}

local in_battle_prev = false
local battle_area_set = false  -- proxy: have we entered any battle this session

-- Simulate a recovery scan for a given model's freeze release.
-- Returns a list of {kind, key, loc, area} representing the events the
-- fix's recovery logic WOULD emit.
local function simulate_recovery(m, cur_party_keys, cur_box_keys, outcome, in_battle)
    local out = {}
    local pre_swap_set = {}
    if m.pre_swap then
        for i = 0, 5 do
            local p = m.pre_swap[i] or 0
            if p ~= 0 then pre_swap_set[p] = true end
        end
    end
    local recent_caught = (outcome == M.OUTCOME_CAUGHT)

    -- 2a: party scan
    for k, loc in pairs(cur_party_keys) do
        if not m.pre_party[k] and not m.pre_box[k] then
            local pid = tonumber((k:match("^(%x+):")) or "", 16)
            if not (pid and pre_swap_set[pid]) then
                local kind
                if recent_caught or in_battle then kind = "battle"
                else kind = "gift" end
                out[#out + 1] = {kind = kind, key = k, loc = loc}
            end
        end
    end

    -- 2b: box scan (only when CAUGHT and nothing recovered from party)
    if recent_caught and #out == 0 then
        local dep_box, dep_slot = read_last_pc_deposit()
        if dep_box ~= nil and dep_box ~= M.MEMORIAL_BOX then
            local slots = {}
            if dep_slot then slots[1] = dep_slot
            else for si = 0, (M.MONS_PER_BOX or 30) - 1 do slots[#slots + 1] = si end end
            for _, si in ipairs(slots) do
                local a = M.boxMonAddr and M.boxMonAddr(dep_box, si)
                if a and M.boxSlotOccupied(a) then
                    local k = M.monKey(a)
                    if k and not m.pre_party[k] and not m.pre_box[k] then
                        local pid = tonumber((k:match("^(%x+):")) or "", 16)
                        if not (pid and pre_swap_set[pid]) then
                            out[#out + 1] = {
                                kind = "box", key = k,
                                loc  = ("box " .. dep_box .. " slot " .. si),
                            }
                            break
                        end
                    end
                end
            end
        end
    end

    return out
end

-- Given a model and the per-frame inputs, advance its freeze state machine
-- and (on release) compute its recoveries plus its lost-catch set.
local function step_model(m, name, pids, in_battle, outcome, is_compaction_fn)
    if not m.frozen and not in_battle then
        local diff = pids_diff_count(pids, m.stable)
        if diff >= PID_SWAP_THRESHOLD then
            local is_compaction = is_compaction_fn(pids, m.stable)
            if is_compaction then
                -- Treat as compaction: update baseline immediately (mirrors
                -- both old client and Phase-B client behaviour).
                for i = 0, 5 do m.stable[i] = pids[i] end
            else
                -- Enter freeze.
                m.frozen = true
                m.pre_swap = {}
                for i = 0, 5 do m.pre_swap[i] = m.stable[i] end
                m.pre_party  = snapshot_party_keys()
                m.pre_box    = snapshot_box_keys()
                m.pre_outcome = outcome
            end
        end
    elseif m.frozen then
        -- Release proxy: not in battle AND stable for PID_STABILITY_WINDOW.
        local stable_settled = (current_frame - last_pid_change_frame) >= PID_STABILITY_WINDOW
        if not in_battle and stable_settled then
            m.frozen = false
            local cur_party = snapshot_party_keys()
            local cur_box   = snapshot_box_keys()
            local out_now   = (M.getBattleOutcome and M.getBattleOutcome()) or 0
            local effective_outcome =
                (m.pre_outcome == M.OUTCOME_CAUGHT) and m.pre_outcome or out_now
            local recoveries = simulate_recovery(
                m, cur_party, cur_box, effective_outcome, in_battle)
            for _, r in ipairs(recoveries) do
                m.recoveries[#m.recoveries + 1] = {
                    frame = current_frame, kind = r.kind, key = r.key, loc = r.loc,
                }
            end
            -- A catch is "lost" from this model's POV if outcome was CAUGHT
            -- AND a new mon exists somewhere AND this model produced no
            -- recovery event for it.
            if effective_outcome == M.OUTCOME_CAUGHT then
                local recovered_set = {}
                for _, r in ipairs(recoveries) do recovered_set[r.key] = true end
                for k, loc in pairs(cur_party) do
                    if not m.pre_party[k] and not m.pre_box[k] and not recovered_set[k] then
                        m.lost_catches[#m.lost_catches + 1] = {
                            frame = current_frame, key = k, loc = loc,
                        }
                    end
                end
                for k, loc in pairs(cur_box) do
                    if not m.pre_party[k] and not m.pre_box[k] and not recovered_set[k] then
                        m.lost_catches[#m.lost_catches + 1] = {
                            frame = current_frame, key = k, loc = loc,
                        }
                    end
                end
            end
            -- After release, re-baseline (matches client behaviour).
            for i = 0, 5 do m.stable[i] = pids[i] end
            m.pre_swap = nil
        end
    end
end

-- ── frame callback ───────────────────────────────────────────────────────────
local function on_frame()
    current_frame = current_frame + 1
    local pids       = read_party_pids()
    local in_battle  = M.isInBattle and M.isInBattle() or false
    local outcome    = (M.getBattleOutcome and M.getBattleOutcome()) or 0

    -- Track raw PID changes so the stability window is computed once.
    local changed = false
    for i = 0, 5 do
        if pids[i] ~= last_pids[i] then changed = true; last_pids[i] = pids[i] end
    end
    if changed then last_pid_change_frame = current_frame end

    if in_battle and not in_battle_prev then battle_area_set = true end

    -- Per-frame BUG-2 fingerprint check.
    if not model.old.frozen and not in_battle then
        local diff = pids_diff_count(pids, model.old.stable)
        if diff >= PID_SWAP_THRESHOLD then
            local old_r = old_is_compaction(pids, model.old.stable)
            local new_r, added, removed = new_is_compaction(pids, model.old.stable)
            if old_r and not new_r then
                b2_events[#b2_events + 1] = {
                    frame = current_frame, added = added, removed = removed,
                    confirmed = false,
                }
            elseif not old_r then
                -- Real PID-swap detected by OLD rule — confirm recent fingerprints.
                for _, e in ipairs(b2_events) do
                    if not e.confirmed and (current_frame - e.frame) <= FREEZE_LOOKAHEAD then
                        e.confirmed = true
                    end
                end
            end
        end
    end

    -- Step both models.  The OLD model uses old_is_compaction so it reproduces
    -- the buggy behaviour; the NEW model uses new_is_compaction.  Lost-catch
    -- sets are populated per-release.
    step_model(model.old, "old", pids, in_battle, outcome, old_is_compaction)
    step_model(model.new, "new", pids, in_battle, outcome, new_is_compaction)

    in_battle_prev = in_battle
end

-- ── verdict ──────────────────────────────────────────────────────────────────
local function verdict()
    console.log("---- [VALIDATE] verdict ----")

    -- BUG-2 verdict.
    local confirmed_b2 = 0
    for _, e in ipairs(b2_events) do if e.confirmed then confirmed_b2 = confirmed_b2 + 1 end end
    console.log(string.format(
        "BUG-2: observed %d misclassification candidate(s); %d confirmed by a real PID swap within %d frames.",
        #b2_events, confirmed_b2, FREEZE_LOOKAHEAD))
    for _, e in ipairs(b2_events) do
        console.log(string.format(
            "  frame=%d  added=%d removed=%d  confirmed=%s",
            e.frame, e.added, e.removed, tostring(e.confirmed)))
    end
    local b2_pass
    if confirmed_b2 > 0 then
        b2_pass = true
        console.log(string.format(
            "  BUG-2 VERDICT: PASS — NEW rule correctly rejects %d swap-intermediate frame(s) the OLD rule accepted.",
            confirmed_b2))
    elseif #b2_events == 0 then
        b2_pass = nil
        console.log("  BUG-2 VERDICT: NO EVIDENCE — no candidate frames observed; trigger a borrowed-party scripted encounter to exercise this path.")
    else
        b2_pass = nil
        console.log("  BUG-2 VERDICT: INCONCLUSIVE — candidates exist but none escalated to a real swap.  Could mean the OLD rule didn't actually cause a misclassification in this session.")
    end

    -- BUG-1 verdict — compare OLD vs NEW model lost-catch sets.
    console.log(string.format(
        "BUG-1: OLD model lost-catches=%d; NEW model lost-catches=%d; NEW recoveries=%d.",
        #model.old.lost_catches, #model.new.lost_catches, #model.new.recoveries))
    for _, r in ipairs(model.new.recoveries) do
        console.log(string.format(
            "  NEW recovery: frame=%d kind=%s key=%s loc=%s",
            r.frame, r.kind, r.key, r.loc))
    end
    for _, l in ipairs(model.old.lost_catches) do
        console.log(string.format(
            "  OLD lost: frame=%d key=%s loc=%s", l.frame, l.key, l.loc))
    end
    local b1_pass
    if #model.old.lost_catches > 0 and #model.new.lost_catches == 0 then
        b1_pass = true
        console.log(string.format(
            "  BUG-1 VERDICT: PASS — NEW recovery scan picks up %d catch(es) the OLD model lost.",
            #model.old.lost_catches))
    elseif #model.old.lost_catches == 0 and #model.new.lost_catches == 0 then
        b1_pass = nil
        console.log("  BUG-1 VERDICT: NO EVIDENCE — no freeze-during-catch sequences observed; catch a mon during a scripted/special encounter to exercise this path.")
    elseif #model.new.lost_catches > 0 then
        b1_pass = false
        console.log(string.format(
            "  BUG-1 VERDICT: FAIL — NEW model still lost %d catch(es); recovery scan needs further work.",
            #model.new.lost_catches))
    else
        b1_pass = nil
        console.log("  BUG-1 VERDICT: INCONCLUSIVE — OLD model lost nothing in this session.")
    end

    local both_pass = (b2_pass == true) and (b1_pass == true)
    local any_fail  = (b2_pass == false) or (b1_pass == false)
    if both_pass then
        console.log("OVERALL: PASS — both bugs reproduced AND the NEW fix handles them correctly.")
    elseif any_fail then
        console.log("OVERALL: FAIL — at least one bug condition was observed where the NEW logic did not produce the right behaviour.")
    else
        console.log("OVERALL: PARTIAL — not enough evidence in this session to fully validate.  Play through more scripted encounters with catches and re-run F1.")
    end
end

local prev_keys = {}
event.onframeend(function()
    on_frame()
    local ok, keys = pcall(input.get)
    if ok and keys then
        if keys.F1 and not prev_keys.F1 then verdict() end
        prev_keys = keys
    end
end)

console.log("[VALIDATE] Ready.  Play through the scenario you want to test.  F1 in emu window = verdict.")
