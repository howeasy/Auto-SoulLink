--[[
  lua/tests/test_gen2_enemy_moves.lua — Phase 4 enemy moves+PP live verification (Gen 2)

  Reads wEnemyMon battle-struct moves at 0xD208 and PP at 0xD20E (raw, NOT
  packed PP-Up — battle struct stores live current PP only).

  Controls:
    F1 → dump active enemy moves + PP
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
package.path = _src .. "?.lua;" .. _lua_root .. "?.lua;" .. _lua_root .. "games/?.lua;" .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen2_crystal"] = nil

local M = require("memory_gb")
local G = require("games.gen2_crystal")
M.initProfile(G, "crystal")
local p = G.profiles.crystal

local fmt = string.format
local TAG = "[T4-G2]"

console.clear()
console.log(fmt("%s Phase 4 enemy moves+PP (Crystal)", TAG))
console.log(fmt("%s ENEMY_BATTLE_MOVES_ADDR=0x%04X  ENEMY_BATTLE_PP_ADDR=0x%04X",
    TAG, p.ENEMY_BATTLE_MOVES_ADDR, p.ENEMY_BATTLE_PP_ADDR))

local function dump()
    local mp = M.readEnemyBattleMovesAndPP()
    if not mp then
        console.log("  (no enemy battle data — out of battle?)")
        return
    end
    for i = 1, 4 do
        local mark = (mp.moves[i] >= 0 and mp.moves[i] <= 251) and "  " or "??"
        console.log(fmt("    %s move[%d] id=%-3d  pp=%-2d", mark, i - 1, mp.moves[i], mp.pp[i]))
    end
end

local prev_keys = {}
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump() end
    prev_keys = k
end, "phase4_g2_enemy")
