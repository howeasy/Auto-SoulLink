--[[
  lua/tests/test_gen2_stat_stages.lua — Phase 2 stat stage live verification (Gen 2 Crystal)

  Reads wPlayerStatLevels..+6 and wEnemyStatLevels..+6 every frame; logs when
  any byte changes. Use during a wild/trainer battle:
    1. Enter a battle.
    2. Use stat-modifying moves (Growl, Tail Whip, etc.).
    3. Verify the displayed byte values change from 7 → other values in 1..13.

  IMPORTANT: The Crystal profile addresses for these are *tentative*
  (working hypothesis 0xC68A / 0xC691 from pret SECTION analysis; absolute
  addresses depend on linker output and have not been verified live).
  If F1 dump shows values outside 1..13 in a known-good battle state, the
  address is wrong; sweep ±0x100 with F2 to find the correct one.

  Controls:
    F1 → dump current values + 0x100-byte sweep starting at the profile address
    F2 → wide sweep (0xC600..0xC7FF) — print any 7-byte run where every byte is in 1..13
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen2_crystal/?.lua;"
           .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen2_crystal"] = nil

local M = require("memory_gb")
local G = require("games.gen2_crystal")
M.initProfile(G, "crystal")
local p = G.profiles.crystal

local fmt = string.format
local TAG = "[T2-G2]"
local LABELS = {"ATK", "DEF", "SPD", "SATK", "SDEF", "ACC", "EVA"}

console.clear()
console.log(fmt("%s Phase 2 stat-stages audit (Crystal)", TAG))
console.log(fmt("%s PLAYER_STAT_STAGES_ADDR=0x%04X  ENEMY_STAT_STAGES_ADDR=0x%04X  (BOTH TENTATIVE)",
    TAG, p.PLAYER_STAT_STAGES_ADDR, p.ENEMY_STAT_STAGES_ADDR))
console.log(fmt("%s Press F1 to dump + sweep; F2 for full WRAM0 scan.", TAG))

local function dump()
    console.log(fmt("%s ── stat stages dump ──", TAG))
    console.log("  player:")
    for i = 0, 6 do
        local v = M.read_u8(p.PLAYER_STAT_STAGES_ADDR + i)
        local stage = v - 7
        console.log(fmt("    %s @ 0x%04X = %d (stage %+d)  [%s]",
            LABELS[i + 1], p.PLAYER_STAT_STAGES_ADDR + i, v, stage,
            (v >= 1 and v <= 13) and "ok" or "OUT OF RANGE"))
    end
    console.log("  enemy:")
    for i = 0, 6 do
        local v = M.read_u8(p.ENEMY_STAT_STAGES_ADDR + i)
        local stage = v - 7
        console.log(fmt("    %s @ 0x%04X = %d (stage %+d)  [%s]",
            LABELS[i + 1], p.ENEMY_STAT_STAGES_ADDR + i, v, stage,
            (v >= 1 and v <= 13) and "ok" or "OUT OF RANGE"))
    end
    local p_stages = M.readPlayerStatStages()
    if p_stages then
        console.log(fmt("  helper readPlayerStatStages() = {%d, %d, %d, %d, %d, %d, %d}",
            p_stages[1], p_stages[2], p_stages[3], p_stages[4], p_stages[5], p_stages[6], p_stages[7]))
    else
        console.log("  helper readPlayerStatStages() = nil")
    end
end

local function wide_sweep()
    console.log(fmt("%s ── WRAM0 sweep for 7-byte runs of 1..13 (likely stat-level candidates) ──", TAG))
    local found = 0
    for base = 0xC400, 0xC900 do
        local ok = true
        for i = 0, 6 do
            local v = M.read_u8(base + i)
            if v < 1 or v > 13 then ok = false; break end
        end
        if ok then
            -- Also check the NEXT 7 bytes — wPlayer/wEnemy stat levels are typically adjacent
            local next_ok = true
            for i = 7, 13 do
                local v = M.read_u8(base + i)
                if v < 1 or v > 13 then next_ok = false; break end
            end
            if next_ok then
                console.log(fmt("  CANDIDATE 0x%04X: 14 consecutive bytes all 1..13 (player + enemy?)", base))
                found = found + 1
                if found >= 6 then break end
            end
        end
    end
    if found == 0 then
        console.log("  no candidates — try this during an active battle when stat levels are initialized to 7")
    end
end

local prev_keys = {}
local prev_state = nil

event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump() end
    if k["F2"] and not prev_keys["F2"] then wide_sweep() end
    prev_keys = k

    local s = ""
    for i = 0, 6 do s = s .. fmt("%02X", M.read_u8(p.PLAYER_STAT_STAGES_ADDR + i)) end
    for i = 0, 6 do s = s .. fmt("%02X", M.read_u8(p.ENEMY_STAT_STAGES_ADDR + i)) end
    if prev_state and s ~= prev_state then
        console.log(fmt("%s stages changed: player=%s enemy=%s",
            TAG, s:sub(1, 14), s:sub(15)))
    end
    prev_state = s
end, "phase2_g2_stat_stages")
