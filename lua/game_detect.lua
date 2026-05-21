--[[
  lua/game_detect.lua — Explicit game module registry and detection dispatcher.

  Loads all game modules, runs detection in priority order, and returns the
  detected game module, variant, profile table, and game_id.

  Usage:
    local game_detect = require("game_detect")
    local detected = game_detect.detect()
    -- detected = { module = <game_module>, variant = <string>,
    --              profile = <profile_table>, game_id = <string> }
--]]

local game_detect = {}

-- Clear stale cached modules from previous script loads (BizHawk reuses Lua state).
package.loaded["games.gen1_rby"]      = nil
package.loaded["games.gen2_crystal"]  = nil
package.loaded["games.gen3_frlge"]    = nil
package.loaded["games.gen4_hgsspt"]   = nil
package.loaded["games.gen5_bw"]       = nil

-- Registry of game modules (add future games here).
-- pcall protects against load-time errors (e.g., missing dependencies on wrong platform).
local game_modules = {}
local _module_names = {
    "games.gen1_rby",
    "games.gen2_crystal",
    "games.gen3_frlge",
    "games.gen4_hgsspt",
    "games.gen5_bw",
}
for _, name in ipairs(_module_names) do
    local ok, mod = pcall(require, name)
    if ok and type(mod) == "table" and mod.detect then
        game_modules[#game_modules + 1] = mod
    else
        -- Surface the load error so silent-drop bugs (e.g. an eager require()
        -- inside the module hitting a path that isn't on package.path yet)
        -- are visible in the console instead of producing a misleading
        -- "no module matched" later. The pcall above keeps us from crashing
        -- the entire dispatcher if one game module is broken.
        console.log(string.format("[game_detect] require(%q) FAILED: %s",
            name, tostring(mod)))
    end
end

-- Sort by detect_priority (descending — higher priority checked first)
table.sort(game_modules, function(a, b)
    return (a.detect_priority or 0) > (b.detect_priority or 0)
end)

--- Run detection across all registered game modules.
--- Returns a table with: module, variant, profile, game_id.
--- Errors if no game module matches the loaded ROM.
function game_detect.detect()
    for _, mod in ipairs(game_modules) do
        local det_ok, detected = pcall(mod.detect)
        if det_ok and detected then
            local variant = mod.detect_variant()
            local profile = mod.profiles[variant]
            if not profile then
                error("[game_detect] ROM detected as " .. mod.display_name ..
                      " variant '" .. variant .. "' but no profile exists yet. " ..
                      "This game variant is not yet supported.")
            end
            return {
                module  = mod,
                variant = variant,
                profile = profile,
                game_id = mod.game_id,
            }
        end
    end
    error("[game_detect] No game module matched the loaded ROM. " ..
          "Ensure the ROM is a supported game (Gen 1: RBY, Gen 3: FRLG / Emerald, Gen 4: HGSS / Platinum, Gen 5: BW / BW2).")
end

return game_detect
