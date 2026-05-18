--[[
  lua/tests/test_gen4_stat_stages.lua — Locate per-battler statChanges[7] in Gen 4 RAM.
  READ-ONLY. Run during an active battle.

  Goal:
    Find BATTLE_INFO_BASE_OFF + BATTLE_INFO_STRIDE + BATTLE_INFO_STAT_STAGES_OFF
    such that a battler at index 0 (player_L) with statChanges[7]=[+2, 0, 0, 0, 0, 0, 0]
    after Swords Dance produces a recognizable signature in the RAM scan.

  Methodology:
    1. Enter a battle (no buffs applied).
    2. Press F1 → "baseline capture" (all stat stages neutral).
    3. Use Swords Dance with your active mon (atk +2).
    4. Press F2 → "post-buff capture".
    5. Press F3 → diff: prints addresses where atk changed (typically 0 → 2,
       or +6 → +8 depending on signed/unsigned encoding).

  After identifying the location:
    • BATTLE_INFO_BASE_OFF = address of the byte that changed
    • BATTLE_INFO_STAT_STAGES_OFF = 0 (assuming statChanges is the first field after
      whatever wrapper, otherwise: walk back ~8 bytes from the changed byte and search
      for a pattern where 7 consecutive bytes look like stat stages.)
    • BATTLE_INFO_STRIDE = byte distance to the next BattleMon entry — confirm by
      checking that battler 1 (enemy_L) has its statChanges starting at base + stride.

  Where to test:
    Any battle with a Swords Dance / Growl-using mon. Easiest: starter with Tail Whip
    (atk → 0 on foe) or any wild fight where the player uses a stat-mod move.
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen4_hgsspt/?.lua;"
           .. package.path

package.loaded["memory_nds"] = nil
package.loaded["gen4_hgsspt"] = nil

local M    = require("memory_nds")
local game = require("gen4_hgsspt")

local variant = game.detect_variant()
local profile = game.profiles[variant] or game.profiles.heartgold
M.applyProfile(profile)
local RAM = profile.RAM_DOMAIN or "Main RAM"

local function log(msg) console.log("[STAT-SCAN] " .. msg) end
local function r8(a) return memory.read_u8(a, RAM) end

local PLAYER_BATTLE_OFF = profile.PLAYER_BATTLE_OFF
local SCAN_LO = PLAYER_BATTLE_OFF - 0x3000
local SCAN_HI = PLAYER_BATTLE_OFF + 0x3000

local capture_baseline = nil
local capture_buffed   = nil

local function capture(label)
    local base = M.init()
    if not base then log("Save not loaded"); return nil end
    local c = {}
    for off = SCAN_LO, SCAN_HI do
        c[off] = r8(base + off)
    end
    log(string.format("Captured %s @ frame %d (%d bytes)", label,
        emu.framecount and emu.framecount() or -1, SCAN_HI - SCAN_LO + 1))
    return c
end

local function compare()
    if not capture_baseline or not capture_buffed then
        log("Need both F1 (baseline) and F2 (post-Swords-Dance) captures before F3 comparison.")
        return
    end
    -- Look for: byte changed from {0|6} → {2|8} (atk +2 in either signed or unsigned encoding).
    local hits = {}
    for off = SCAN_LO, SCAN_HI do
        local b = capture_baseline[off]
        local p = capture_buffed[off]
        if (b == 0 and p == 2) or (b == 6 and p == 8) or (b == 0xFE and p == 0x02) then
            hits[#hits + 1] = {off=off, before=b, after=p}
        end
    end
    log(string.format("Found %d offsets with atk-stage delta (+2):", #hits))
    -- Cluster nearby hits — true statChanges array gives one hit per modified stage.
    -- A neat 7-byte (or 8-byte with padding) cluster is the giveaway.
    for i, h in ipairs(hits) do
        local rel = h.off - PLAYER_BATTLE_OFF
        log(string.format("  [%d] base+0x%X  (%s 0x%X from PLAYER_BATTLE)  %d → %d",
            i, h.off, rel >= 0 and "+" or "-", math.abs(rel), h.before, h.after))
        if i >= 30 then log("  ... (truncated)"); break end
    end
    -- Heuristic: if there's a cluster of 7-8 hits within a 16-byte window,
    -- that's likely the statChanges array.
    if #hits >= 1 then
        log("Tip: for each candidate, read 7 consecutive bytes — a real statChanges array")
        log("     should be { 8, 6, 6, 6, 6, 6, 6 } (unsigned) or { 2, 0, 0, 0, 0, 0, 0 } (signed)")
        log("     after a Swords Dance. The first index in that pattern = BATTLE_INFO_BASE_OFF +")
        log("     BATTLE_INFO_STAT_STAGES_OFF for battler 0.")
    end
end

log(string.format("Gen 4 stat-stage scanner — variant=%s, scan=0x%X..0x%X", variant, SCAN_LO, SCAN_HI))
log("Sequence: enter battle → F1 (baseline) → Swords Dance → F2 (buffed) → F3 (compare)")

event.onframestart(function()
    local k = input.get()
    if k["F1"] then capture_baseline = capture("baseline (no buffs)") end
    if k["F2"] then capture_buffed   = capture("post-Swords-Dance (+2 ATK)") end
    if k["F3"] then compare() end
end)
