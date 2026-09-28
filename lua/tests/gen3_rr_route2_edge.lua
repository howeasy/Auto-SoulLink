-- Route 1 south connection (3.19 at 12,39) to Pallet (3.0, offset 0).
-- RR ROM geometry: docs/gen3/research/rr_fixture_route_2026-09-24.md §route2,
-- independently pinned by tests/unit/test_gen3_rr_fixture_route.py.
-- Only a live off-field, non-battle callback at that exact edge admits menu recovery.
-- The binding's play.leave_menu owns B input and verifies that the field holds afterward.
local M = {}
local ROUTE1, EDGE_X, EDGE_Y = 3 * 256 + 19, 12, 39

local function describe(s)
    return string.format("map=%s pos=(%s,%s) field=%s battle=%s callback2=%s tasks=%s",
        tostring(s.map), tostring(s.x), tostring(s.y), tostring(s.field),
        tostring(s.battle), tostring(s.callback2), tostring(s.tasks))
end

local function at_edge(s)
    return s.map == ROUTE1 and s.x == EDGE_X and s.y == EDGE_Y
end

function M.cross(io)
    local before = io.state()
    io.log("ROUTE2_EDGE before " .. describe(before))
    if not at_edge(before) then return false, "not at the pinned Route 1 south edge: " .. describe(before) end
    if before.battle then return false, "battle still active at Route 1 south edge" end

    local function settle_ui(stage)
        local s = io.state()
        if s.battle then return false, "battle active " .. stage end
        if not at_edge(s) then return false, "edge moved " .. stage .. ": " .. describe(s) end
        if not s.field then
            io.log("ROUTE2_EDGE off-field " .. stage .. " " .. describe(s))
            io.leave_menu()
            s = io.state()
            io.log("ROUTE2_EDGE after-menu " .. stage .. " " .. describe(s))
            if not at_edge(s) or not s.field or s.battle then
                return false, "field did not settle at pinned edge " .. stage .. ": " .. describe(s)
            end
        end
        return true
    end

    local ready, why = settle_ui("before-crossing")
    if not ready then return false, why end
    local ok, detail = io.enter_warp()
    if ok then return true end
    local after = io.state()
    io.log("ROUTE2_EDGE first-crossing-failed " .. tostring(detail) .. " " .. describe(after))
    -- A wild encounter can start on the tall-grass connection tile while Down is being
    -- pressed. The route binding's normal flee policy owns this battle; the map/position
    -- and field callbacks must settle again before ONE renewed crossing press.
    if not at_edge(after) or after.field then return false, detail end
    if after.battle then
        io.log("ROUTE2_EDGE crossing battle " .. describe(after))
        if not io.fight_through() or not io.settle() then
            return false, "incidental battle at Route 1 south edge did not settle"
        end
    end
    ready, why = settle_ui("after-failed-crossing")
    if not ready then return false, why end
    io.log("ROUTE2_EDGE retrying one natural Down crossing")
    return io.enter_warp()
end

return M
