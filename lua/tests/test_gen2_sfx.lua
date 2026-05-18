--[[
  lua/tests/test_gen2_sfx.lua — Phase 7 SFX dispatch live discovery (Gen 2 Crystal)

  Same purpose as Gen 1: identify the correct SFX dispatch address + IDs
  for Crystal before enabling automatic SFX playback in the profile.

  Per pret/pokecrystal: wMapMusic (~0xC201), wMusicID (~0xC0FB), wCurSFX
  (~0xC17A). Crystal SFX IDs per data/audio/sfx_pointers.asm.

  Controls:
    F1 → write 0x86 (capture chime candidate) to 0xC0FB
    F2 → write 0x71 (faint thump candidate) to 0xC0FB
    F3 → write 0x86 to 0xC17A (alt)
    F4 → M.playSfx("capture")
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
package.path = _src .. "?.lua;" .. _lua_root .. "?.lua;" .. _lua_root .. "games/?.lua;" .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen2_crystal"] = nil

local M = require("memory_gb")
local G = require("games.gen2_crystal")
M.initProfile(G, "crystal")

local fmt = string.format
local TAG = "[T7-G2]"

console.clear()
console.log(fmt("%s Phase 7 SFX dispatch discovery (Crystal)", TAG))
console.log("  F1=write 0x86 to 0xC0FB  F2=write 0x71 to 0xC0FB")
console.log("  F3=write 0x86 to 0xC17A  F4=M.playSfx('capture')")

local function w(addr, id)
    M.write_u8(addr, id)
    console.log(fmt("  wrote 0x%02X to 0x%04X", id, addr))
end

local prev_keys = {}
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then w(0xC0FB, 0x86) end
    if k["F2"] and not prev_keys["F2"] then w(0xC0FB, 0x71) end
    if k["F3"] and not prev_keys["F3"] then w(0xC17A, 0x86) end
    if k["F4"] and not prev_keys["F4"] then
        local ok = M.playSfx("capture")
        console.log("  M.playSfx('capture') -> " .. tostring(ok))
    end
    prev_keys = k
end, "phase7_g2_sfx")
