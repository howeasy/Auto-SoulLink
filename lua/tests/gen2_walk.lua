--[[
  lua/tests/gen2_walk.lua -- the one step rule every Gen 2 scripted walker plans with (gen2_scripted_play
  direction, gen2_write_windows U.step_toward / U.grass_step, gen2_frame_align F.walk_direction,
  gen2_poison_inputs PI.step_toward). Pure; no emulator globals.

  Ledges come from a SEPARATE facts field, map.ledges = {{x, y, dirs={"Down", ...}}} (tools/gen2_fixtures.map_ledges),
  never from the route-facts grid: _map_facts keeps HOP_* out of the walkable grid and its output is
  fingerprinted into every fixture qualification receipt. Without map.ledges the rule is the old conservative
  grid (ledges are walls).

  One press of a direction from a tile (pokegold/pokecrystal engine/overworld/player_movement.asm .Normal):
    .TryStep first: walkable land ahead is a plain one-tile step. A HOP_* tile is LAND (.CheckWalkable,
      :735-741), so a ledge ahead is steppable even though the live observer's passable set (fingerprinted,
      test_gen2_scripted_gate.lua point.can_step) leaves HOP_* out.
    .TryJump only when that step bumps: standing ON a ledge whose hop direction this is jumps two tiles
      (.TryJump reads wPlayerTileCollision, the stood-on tile, :354-377; STEP_LEDGE).
--]]
local W = {}
W.DIRECTIONS = {{"Up", 0, -1}, {"Left", -1, 0}, {"Down", 0, 1}, {"Right", 1, 0}}

-- W.stepper(map, can_step) -> step(x, y, d, first): where one press of d (a W.DIRECTIONS row) from (x, y)
-- lands and that tile's grid class (1 land, 2 grass), or nil. `first` = the player's own tile, where the
-- live permission can_step[d] must also allow a plain step onto a non-ledge tile.
function W.stepper(map, can_step)
    local width, height, grid = map.width, map.height, map.grid
    local hop = {}
    for _, l in ipairs(map.ledges or {}) do
        local dirs = {}
        for _, d in ipairs(l.dirs) do dirs[d] = true end
        hop[l.y * width + l.x + 1] = dirs
    end
    local function class(x, y)
        if x < 0 or x >= width or y < 0 or y >= height then return 0 end
        local k = y * width + x + 1
        return hop[k] and 1 or grid[k]
    end
    return function(x, y, d, first)
        local nx, ny = x + d[2], y + d[3]
        local tile = class(nx, ny)
        if tile ~= 0 then
            if first and can_step[d[1]] ~= true and not hop[ny * width + nx + 1] then return nil end
            return nx, ny, tile
        end
        local here = hop[y * width + x + 1]
        if here and here[d[1]] then
            nx, ny = x + 2 * d[2], y + 2 * d[3]
            tile = class(nx, ny)
            if tile ~= 0 then return nx, ny, tile end
        end
        return nil
    end
end

return W
