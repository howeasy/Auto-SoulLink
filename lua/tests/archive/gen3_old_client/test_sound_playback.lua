--[[
  lua/test_sound_playback.lua — Test M.playSE() in BizHawk
  =========================================================
  Load in BizHawk Lua Console with a FireRed/LeafGreen save loaded.

  Controls:
    F1  →  SE_FAINT   (mon faints)
    F2  →  SE_FLEE    (wild flees)
    F3  →  SE_BOO     (ball breaks open)
    F4  →  SE_SUCCESS (ball catches)
    F5  →  SE_FAILURE (action fails)
    F6  →  SE_SHINY   (shiny sparkle)

  Each key press plays the corresponding sound effect via M.playSE().
  Watch the Lua Console for confirmation or error messages.
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
package.path = _src .. "?.lua;" .. package.path
package.loaded["memory_gba"] = nil
local M = require("memory_gba")
M.initProfile()

local SOUNDS = {
    { key = "F1", id = M.SE_FAINT,   name = "SE_FAINT"   },
    { key = "F2", id = M.SE_FLEE,    name = "SE_FLEE"    },
    { key = "F3", id = M.SE_BOO,     name = "SE_BOO"     },
    { key = "F4", id = M.SE_SUCCESS, name = "SE_SUCCESS" },
    { key = "F5", id = M.SE_FAILURE, name = "SE_FAILURE" },
    { key = "F6", id = M.SE_SHINY,   name = "SE_SHINY"   },
}

console.clear()
console.log("=== SLink Sound Playback Test ===")
console.log("Load a save first, then press F-keys to test sounds:")
for _, s in ipairs(SOUNDS) do
    console.log(string.format("  %s  →  %s (id=%d)", s.key, s.name, s.id))
end
console.log("")

-- Warn if SE_SONG_HEADERS is empty (e.g. RR without discovered addresses)
local has_any = false
for _ in pairs(M.SE_SONG_HEADERS) do has_any = true; break end
if not has_any then
    console.log("⚠ WARNING: SE_SONG_HEADERS is empty for this profile!")
    console.log("  Run test_sound_discovery.lua first to find the addresses,")
    console.log("  then add them to the profile in memory.lua.")
    console.log("")
end

local prev_keys = {}

local function on_frame()
    local inp = input.get()
    for _, s in ipairs(SOUNDS) do
        if inp[s.key] and not prev_keys[s.key] then
            local ok = M.playSE(s.id)
            if ok then
                console.log(string.format("[SND] ▶ %s — played OK", s.name))
            else
                console.log(string.format("[SND] ✗ %s — playSE returned false (driver not ready?)", s.name))
            end
        end
    end
    prev_keys = inp
end

event.onframeend(on_frame, "test_sound")
console.log("--- listening for F-key presses ---")
