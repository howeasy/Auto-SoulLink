--[[
  lua/tests/test_gen1_enemy_moves.lua — Phase 4 enemy moves+PP live verification (Gen 1)

  Reads M.ENEMY_BATTLE_MOVES_ADDR (0xCFED on Red/Blue, 0xCFEC on Yellow) and
  enemy PP at 0xCFFE / 0xCFFD. Display only when in battle.

  Controls:
    F1 → dump active enemy moves + PP
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;" .. _lua_root .. "?.lua;" .. _lua_root .. "games/?.lua;" .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen1_rby"] = nil

local M = require("memory_gb")
local G = require("games.gen1_rby")
M.initProfile(G, G.detect_variant() or "red")
local p = G.profiles[G.detect_variant() or "red"]

local fmt = string.format
local TAG = "[T4-G1]"

console.clear()
console.log(fmt("%s Phase 4 enemy moves+PP (variant=%s)", TAG, G.detect_variant() or "red"))
console.log(fmt("%s enemy_battle_moves_addr=0x%04X  enemy_battle_pp_addr=0x%04X",
    TAG, p.enemy_battle_moves_addr, p.enemy_battle_pp_addr))

local function dump()
    local mp = M.readEnemyBattleMovesAndPP()
    if not mp then
        console.log("  (no enemy battle data — out of battle?)")
        return
    end
    for i = 1, 4 do
        local mark = (mp.moves[i] >= 0 and mp.moves[i] <= 165) and "  " or "??"
        console.log(fmt("    %s move[%d] id=%-3d  pp=%-3d", mark, i - 1, mp.moves[i], mp.pp[i]))
    end
end

local prev_keys = {}
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump() end
    prev_keys = k
end, "phase4_g1_enemy")
