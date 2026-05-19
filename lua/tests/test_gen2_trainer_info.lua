--[[
  lua/tests/test_gen2_trainer_info.lua — Phase 5 trainer class+id verification (Crystal)

  Working hypothesis: TRAINER_CLASS_ADDR=0xD233, TRAINER_ID_ADDR=0xD234. Verify
  by entering Falkner (class_id should be 1) or Bugsy (class_id 3), etc.

  Controls:
    F1 → dump class_id + trainer_id + resolved class/name
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
package.path = _src .. "?.lua;" .. _lua_root .. "?.lua;" .. _lua_root .. "games/?.lua;" .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen2_crystal"] = nil
package.loaded["games.gen2_crystal_trainers"] = nil

local M = require("memory_gb")
local G = require("games.gen2_crystal")
local TRAINERS = require("games.gen2_crystal_trainers")
M.initProfile(G, "crystal")
local p = G.profiles.crystal

local fmt = string.format
local TAG = "[T5-G2]"

console.clear()
console.log(fmt("%s Phase 5 trainer info (Crystal)", TAG))
console.log(fmt("%s TRAINER_CLASS_ADDR=0x%04X  TRAINER_ID_ADDR=0x%04X (TENTATIVE)",
    TAG, p.TRAINER_CLASS_ADDR, p.TRAINER_ID_ADDR))

local function dump()
    local cls = M.read_u8(p.TRAINER_CLASS_ADDR)
    local tid = M.read_u8(p.TRAINER_ID_ADDR)
    local class_name, trainer_name = TRAINERS.resolve(cls, tid)
    console.log(fmt("  class_id=%d  trainer_id=%d", cls, tid))
    console.log(fmt("  resolved class='%s'  name='%s'", class_name, trainer_name))
    if cls > 67 then
        console.log("  !! class_id > 67 — likely wrong address (Crystal classes are 0..67)")
    end
end

local prev_keys = {}
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump() end
    prev_keys = k
end, "phase5_g2_trainer")
