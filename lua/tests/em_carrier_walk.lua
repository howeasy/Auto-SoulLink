-- em_carrier_walk.lua -- the Emerald Pokemon Center walk that WAITS for the companion's trade NPC
-- instead of talking to it.
--
-- WHY (whiteout_gen3 on the Emerald companion, final cut b6cd75c6, "step Up stalled at (10,4)"):
-- the companion spawns a wandering trade NPC in every Center (patch/src/trade_targets/
-- native_carrier.h nc_drive_npc; Emerald spawn x=0x11,y=0xb = map (10,4) after the -7 offset,
-- movement type 2 with range 1,1: it roams x 9..11, y 3..5, emerald.h:144-148). (10,3) is the one
-- walkable access to the PC, so the NPC can stand on the route. playlib's recovery for a blocked
-- step taps A four times (clear_dialogue); facing the NPC that opens its Trade menu and the
-- field stays locked until the stall is declared. Here a blocked step NEVER presses A: it idles
-- and retries the SAME direction (the wander moves it off), and only a menu that is already open
-- is backed out of, with B. The budget is bounded and the failure names what blocked it.
--
-- Everything the game supplies is injected, so lupa drives it over a fake (tests/unit/
-- test_gen3_em_carrier_wait.py). deps:
--   pos() -> x, y              the player's tile
--   map() -> id | nil          the map id (a readable change = the path walked into a warp)
--   hold(dir, frames)          hold a direction for `frames` frames
--   idle(frames)               release everything and advance
--   tap_b()                    one B press (the ONLY button this module presses besides directions)
--   quiet() -> bool            field idle: no script running, no menu reading input, controls free
--   carrier() -> x, y | nil    the carrier NPC's tile, nil when it cannot be read
--   wait_at(x, y) -> bool      the player has come to rest on (x, y)
--   finish(ok, msg)            end the run (G.finish)
local M = {}

-- patch/src/trade_targets/emerald.h SLINK_TARGET_CARRIER_LOCAL_ID (a unit test pins the two).
M.CARRIER_LOCAL_ID = 0xF1
M.STEP_HOLD, M.STEP_SETTLE = 12, 4        -- playlib P.step's cadence: one tile per 12-frame press
M.RETRY_IDLE = 30                         -- frames to let the wander move before pressing again
M.BUDGET = 600                            -- idle frames spent on ONE blocked step before failing

local DELTA = { Up = { 0, -1 }, Down = { 0, 1 }, Left = { -1, 0 }, Right = { 1, 0 } }

function M.new(deps)
    local W = {}

    --- One step in `dir`. true when the player moved a tile or the map changed; false, why after
    --- the budget. Never presses A.
    local function step(dir, start_map)
        local x0, y0 = deps.pos()
        local waited = 0
        while true do
            if not deps.quiet() then
                -- a menu or message the NPC (or anything else) opened: back out, never confirm
                deps.tap_b()
                waited = waited + 16
            else
                deps.hold(dir, M.STEP_HOLD)
                deps.idle(M.STEP_SETTLE)
                local now = deps.map()
                if now ~= nil and start_map ~= nil and now ~= start_map then return true end
                local x, y = deps.pos()
                if x ~= x0 or y ~= y0 then return true end
                deps.idle(M.RETRY_IDLE)
                waited = waited + M.STEP_HOLD + M.STEP_SETTLE + M.RETRY_IDLE
            end
            if waited >= M.BUDGET then
                local tx, ty = x0 + DELTA[dir][1], y0 + DELTA[dir][2]
                local cx, cy = deps.carrier()
                if cx == tx and cy == ty then
                    return false, string.format("em center walk blocked by carrier NPC at (%d,%d)", cx, cy)
                end
                return false, string.format("blocked step (%d,%d)->(%d,%d)%s", x0, y0, tx, ty,
                    cx and string.format(" (carrier NPC at (%d,%d), not on the target tile)", cx, cy) or "")
            end
        end
    end

    --- Walk `path` ({ from, to, dirs }). Returns true, or false after deps.finish reported why.
    function W.walk(path, label, name)
        label = string.format("%s (%s)", label, name or "path")
        if not deps.wait_at(path.from[1], path.from[2]) then
            deps.finish(false, label .. ": the player never came to rest on the path's from ("
                .. path.from[1] .. "," .. path.from[2] .. ")")
            return false
        end
        local start_map = deps.map()
        for _, dir in ipairs(path.dirs) do
            local ok, why = step(dir, start_map)
            if not ok then
                deps.finish(false, label .. ": " .. why)
                return false
            end
            local now = deps.map()
            if now ~= nil and start_map ~= nil and now ~= start_map then return true end
        end
        local ex, ey = deps.pos()
        if path.to and (ex ~= path.to[1] or ey ~= path.to[2]) then
            deps.finish(false, string.format("%s: walk ended at (%d,%d), not the path's to (%d,%d)",
                label, ex, ey, path.to[1], path.to[2]))
            return false
        end
        return true
    end

    return W
end

return M
