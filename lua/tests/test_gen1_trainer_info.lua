--[[
  lua/tests/test_gen1_trainer_info.lua — Phase 5 trainer class+id verification

  Reads wTrainerClass and wTrainerNo + applies the trainers lookup. Use in a
  trainer battle to verify both addresses produce sensible values.

  Controls:
    F1 → dump class_id + trainer_id + resolved class/name strings
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
package.path = _src .. "?.lua;" .. _lua_root .. "?.lua;" .. _lua_root .. "games/?.lua;" .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen1_rby"] = nil
package.loaded["games.gen1_rby_trainers"] = nil

local M = require("memory_gb")
local G = require("games.gen1_rby")
local TRAINERS = require("games.gen1_rby_trainers")
M.initProfile(G, G.detect_variant() or "red")
local p = G.profiles[G.detect_variant() or "red"]

local fmt = string.format
local TAG = "[T5-G1]"

console.clear()
console.log(fmt("%s Phase 5 trainer info (variant=%s)", TAG, G.detect_variant() or "red"))
console.log(fmt("%s trainer_class_addr=0x%04X  trainer_id_addr=0x%04X (BOTH TENTATIVE — verify against pret)",
    TAG, p.trainer_class_addr, p.trainer_id_addr))

local function dump()
    local cls = M.read_u8(p.trainer_class_addr)
    local tid = M.read_u8(p.trainer_id_addr)
    local class_name, trainer_name = TRAINERS.resolve(cls, tid)
    console.log(fmt("  class_id=%d (0x%02X)  trainer_id=%d", cls, cls, tid))
    console.log(fmt("  resolved class='%s'  name='%s'", class_name, trainer_name))
    if cls < 200 or cls > 246 then
        console.log("  !! class_id out of expected range 200..246 — address may be wrong")
    end
end

local prev_keys = {}
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump() end
    prev_keys = k
end, "phase5_g1_trainer")
