--[[
  lua/tests/test_gen5_doubles.lua — Gen 5 doubles / triples / rotation detector

  Validates BATTLE_MODE_ADDR (doubleTripleFlag) for the current variant.
  Run during an active battle — the script polls the address each frame and
  logs the decoded mode whenever it changes.

  Address values (per NDS-Ironmon-Tracker BattleHandlerGen5.lua):
    0 = single, 1 = double, 2 = triple, 3 = rotation

  Use this to confirm:
    1. The address value (0x2A62F8 for Black US, etc.) is correct
    2. The flag transitions 0→1 when entering a double battle
    3. M.isDoubleBattle() returns true when mode == 1, 2, or 3
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen5_bw/?.lua;"
           .. package.path
package.loaded["memory_nds"] = nil
package.loaded["gen5_bw"] = nil

local M = require("memory_nds")
local game = require("gen5_bw")

local fmt = string.format
local function log(msg) console.log("[T3-G5] " .. msg) end

local variant = game.detect_variant()
local profile = game.profiles[variant]
local mode_addr = profile and profile.BATTLE_MODE_ADDR or nil
M.applyProfile(profile)
log(fmt("variant=%s  BATTLE_MODE_ADDR=0x%X", variant, mode_addr or 0))

local MODE_NAME = { [0] = "single", [1] = "double", [2] = "triple", [3] = "rotation" }
local last_mode = -1
local last_in_battle = false

console.clear()
log("test_gen5_doubles loaded — start a battle to see mode transitions")

event.onframeend(function()
    if not M.init() then return end
    local in_battle = M.isInBattle()
    if in_battle ~= last_in_battle then
        log(fmt("battle %s", in_battle and "STARTED" or "ENDED"))
        last_in_battle = in_battle
    end
    if not mode_addr then return end
    local mode = memory.read_u8(mode_addr, "Main RAM")
    if mode ~= last_mode then
        log(fmt("mode = %d (%s)  isDoubleBattle=%s",
            mode, MODE_NAME[mode] or "?", tostring(M.isDoubleBattle())))
        last_mode = mode
    end
end, "test_gen5_doubles")
