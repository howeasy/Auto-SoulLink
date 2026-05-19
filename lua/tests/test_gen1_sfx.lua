--[[
  lua/tests/test_gen1_sfx.lua — Phase 7 SFX dispatch live discovery (Gen 1)

  IMPORTANT: Phase 7 ships with SFX dispatch DISABLED by default in the
  profile (SFX_DISPATCH_ADDR=nil) because writing to a wrong address can
  corrupt game state. This script is a SAFE diagnostic that:
    1. Lets you experiment with candidate dispatch addresses + SFX IDs.
    2. Reports back what triggered correctly.
    3. Once verified, you can populate the profile SFX_DISPATCH_ADDR +
       sfx_ids and SFX will play automatically on capture/faint/whiteout.

  Per pret/pokered conventions, SFX dispatch is typically via wMusicID
  (0xD35B) + wAudioFadeOutControl (0xC002) and a few related registers.
  The exact write protocol depends on the engine version.

  Controls (write candidate SFX IDs to candidate addresses):
    F1 → write 0x88 (SFX_GET_ITEM_1) to 0xD35B (wMusicID candidate)
    F2 → write 0xB4 (SFX_FAINT_FALL) to 0xD35B
    F3 → write 0x86 (SFX_LEVEL_UP) to 0xD35B
    F4 → write 0x88 to 0xC02A (alternative dispatch candidate)
    F5 → run the abstracted M.playSfx("capture") (currently no-op until
         profile is populated)

  PASS: pressing F1/F2 produces the expected sound effect in BizHawk.
        Note: writes may need to occur during a "quiet" frame (no music
        playing) — try pressing F-key on the OVERWORLD pause screen.
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
package.path = _src .. "?.lua;" .. _lua_root .. "?.lua;" .. _lua_root .. "games/?.lua;" .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen1_rby"] = nil

local M = require("memory_gb")
local G = require("games.gen1_rby")
M.initProfile(G, G.detect_variant() or "red")

local fmt = string.format
local TAG = "[T7-G1]"

console.clear()
console.log(fmt("%s Phase 7 SFX dispatch discovery (variant=%s)", TAG, G.detect_variant() or "red"))
console.log("  F1=write SFX_GET_ITEM_1 (0x88) to 0xD35B")
console.log("  F2=write SFX_FAINT_FALL (0xB4) to 0xD35B")
console.log("  F3=write SFX_LEVEL_UP   (0x86) to 0xD35B")
console.log("  F4=write 0x88 to 0xC02A (alt dispatch)")
console.log("  F5=M.playSfx('capture') (no-op until profile populated)")

local function w(addr, id, label)
    M.write_u8(addr, id)
    console.log(fmt("  wrote 0x%02X to 0x%04X  (%s)", id, addr, label))
end

local prev_keys = {}
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then w(0xD35B, 0x88, "SFX_GET_ITEM_1") end
    if k["F2"] and not prev_keys["F2"] then w(0xD35B, 0xB4, "SFX_FAINT_FALL") end
    if k["F3"] and not prev_keys["F3"] then w(0xD35B, 0x86, "SFX_LEVEL_UP") end
    if k["F4"] and not prev_keys["F4"] then w(0xC02A, 0x88, "alt dispatch") end
    if k["F5"] and not prev_keys["F5"] then
        local ok = M.playSfx("capture")
        console.log("  M.playSfx('capture') -> " .. tostring(ok) .. " (false means profile not configured)")
    end
    prev_keys = k
end, "phase7_g1_sfx")
