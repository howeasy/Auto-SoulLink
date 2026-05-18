--[[
  lua/tests/test_gen1_stat_stages.lua — Phase 2 stat stage live verification (Gen 1)

  Reads wPlayerMonAttackMod..wPlayerMonEvasionMod and wEnemyMonAttackMod..
  wEnemyMonEvasionMod every frame and logs them when they change. Use during
  a wild or trainer battle:
    1. Enter a battle.
    2. Use Growl / Tail Whip / Sand Attack / etc. to modify stages.
    3. Observe the logged values change from 7 (neutral) to other values 1..13.

  PASS criteria:
    - At battle start, all bytes equal 7 (neutral).
    - After Growl, enemy ATK byte decrements (7 → 6 → 5 ...).
    - After Sand Attack, player ACC byte (or enemy ACC byte) drops.
    - Values stay in 1..13 range.

  FAIL criteria:
    - Values are 0xFF / 0x00 / random — wrong address.
    - Values don't change when a stat-modifying move lands.

  Controls:
    F1 → dump current player + enemy stat-stage bytes
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen1_rby/?.lua;"
           .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen1_rby"] = nil

local M = require("memory_gb")
local G = require("games.gen1_rby")

local variant = G.detect_variant()
if not variant then error("[T2-G1] Gen 1 ROM not detected") end
M.initProfile(G, variant)
local p = G.profiles[variant]

local fmt = string.format
local TAG = "[T2-G1]"
local LABELS = {"ATK", "DEF", "SPD", "SPC", "ACC", "EVA"}

console.clear()
console.log(fmt("%s Phase 2 stat-stages audit — variant=%s", TAG, variant))
console.log(fmt("%s player_stat_stages_addr=0x%04X  enemy_stat_stages_addr=0x%04X",
    TAG, p.player_stat_stages_addr, p.enemy_stat_stages_addr))
console.log(fmt("%s Expected encoding: 1..13, neutral=7. Press F1 to dump live values.", TAG))

local function dump()
    console.log(fmt("%s ── stat stages dump ──", TAG))
    console.log("  player:")
    for i = 0, 5 do
        local v = M.read_u8(p.player_stat_stages_addr + i)
        local stage = v - 7  -- centered display
        console.log(fmt("    %s @ 0x%04X = %d (stage %+d)  [%s]",
            LABELS[i + 1], p.player_stat_stages_addr + i, v, stage,
            (v >= 1 and v <= 13) and "ok" or "OUT OF RANGE"))
    end
    console.log("  enemy:")
    for i = 0, 5 do
        local v = M.read_u8(p.enemy_stat_stages_addr + i)
        local stage = v - 7
        console.log(fmt("    %s @ 0x%04X = %d (stage %+d)  [%s]",
            LABELS[i + 1], p.enemy_stat_stages_addr + i, v, stage,
            (v >= 1 and v <= 13) and "ok" or "OUT OF RANGE"))
    end
    -- Also exercise the helper
    local p_stages = M.readPlayerStatStages()
    if p_stages then
        console.log(fmt("  helper readPlayerStatStages() = {%d, %d, %d, %d, %d, %d, %d} (Gen 3 0..12 convention)",
            p_stages[1], p_stages[2], p_stages[3], p_stages[4], p_stages[5], p_stages[6], p_stages[7]))
    else
        console.log("  helper readPlayerStatStages() = nil (values out of 1..13 range or addr unset)")
    end
end

local prev_keys = {}
local prev_state = nil

event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump() end
    prev_keys = k

    -- Auto-log when any byte changes
    local s = ""
    for i = 0, 5 do s = s .. fmt("%02X", M.read_u8(p.player_stat_stages_addr + i)) end
    for i = 0, 5 do s = s .. fmt("%02X", M.read_u8(p.enemy_stat_stages_addr + i)) end
    if prev_state and s ~= prev_state then
        console.log(fmt("%s stages changed: player=%s enemy=%s",
            TAG, s:sub(1, 12), s:sub(13)))
    end
    prev_state = s
end, "phase2_g1_stat_stages")
