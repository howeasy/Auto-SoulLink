--[[
  lua/tests/gen1_inputs_common.lua — the input-shape helpers every gen1_rb_* driver had its own
  copy of.

  WHY THIS EXISTS. `idle`, `hold`, `tap` and `move` were duplicated across seven drivers, and
  the copies had drifted apart in whitespace and parameter names while staying behaviourally
  identical (forest/route22's `move` built its table through `hold("Right")`; the others set the
  key directly — the same table either way). A change to the tap cadence or to the button set
  had to be made seven times, and a miss would show up as one driver quietly pressing a
  different key.

  WHAT IS NOT HERE, deliberately: the helpers whose copies DIFFER in behaviour —
  `check_point` (a movement helper in gen1_rb_forest_inputs.lua, a point-validation assertion in
  gen1_rb_route22_inputs.lua), `bounded` (the y_ball_gate copy takes a point for its message),
  `M.extend_point` and each driver's `M.new`. Unifying those would be a behaviour change, and
  the emulator lane is the test for them, not this file.

  HOW IT IS LOADED. Each driver locates this module with its own one-line `here()` idiom —
  the same way the drivers already dofile gen1_battle_driver.lua and each other. `here` stays
  per-file on purpose: it is the bootstrap that locates this module, so it cannot come from it.

  BUTTON SET: A, B, Start, Select and the four directions, all false. `tap` re-pulses on the
  shared 16-frame cadence (two frames pressed) rather than holding, which is what the native
  menus and text boxes expect.
--]]

local M = {}

function M.idle()
    return {A = false, B = false, Start = false, Select = false,
            Up = false, Down = false, Left = false, Right = false}
end

function M.hold(name)
    local b = M.idle()
    b[name] = true
    return b
end

function M.tap(key, frame)
    local b = M.idle()
    b[key] = frame % 16 < 2
    return b
end

function M.move(point, target)
    local b = M.idle()
    if point.x < target[1] then b.Right = true
    elseif point.x > target[1] then b.Left = true
    elseif point.y < target[2] then b.Down = true
    elseif point.y > target[2] then b.Up = true end
    return b
end

return M
