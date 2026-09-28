-- Route 1 south connection (3.19 at 12,39) to Pallet (3.0, offset 0).
-- RR ROM geometry: docs/gen3/research/rr_fixture_route_2026-09-24.md §route2,
-- independently pinned by tests/unit/test_gen3_rr_fixture_route.py.
-- Only the observed battle-after-first-crossing state admits recovery. "field" is the
-- pinned callback2+in_battle predicate; callback2/tasks below are logged diagnostics, not
-- separate gates. An off-field nonbattle state has no proven menu identity and is refused.
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
    if not before.field then return false, "off-field before crossing: " .. describe(before) end
    local ok, detail = io.enter_warp()
    if ok then return true end
    local after = io.state()
    io.log("ROUTE2_EDGE first-crossing-failed " .. tostring(detail) .. " " .. describe(after))
    -- A wild encounter can start on the tall-grass connection tile while Down is being
    -- pressed. The route binding's normal flee policy owns this battle; the map/position
    -- and field callbacks must settle again before ONE renewed crossing press.
    if not at_edge(after) then
        return false, "crossing left the pinned edge: " .. tostring(detail) .. " / " .. describe(after)
    end
    if not after.battle or after.field then
        return false, "off-field state is not the witnessed battle: "
            .. tostring(detail) .. " / " .. describe(after)
    end
    io.log("ROUTE2_EDGE crossing battle " .. describe(after))
    if not io.fight_through() or not io.settle() then
        return false, "incidental battle at Route 1 south edge did not settle"
    end
    local recovered = io.state()
    io.log("ROUTE2_EDGE after-battle " .. describe(recovered))
    if not at_edge(recovered) or not recovered.field or recovered.battle then
        return false, "field did not settle at pinned edge after battle: " .. describe(recovered)
    end
    io.log("ROUTE2_EDGE retrying one natural Down crossing")
    local retried, why = io.enter_warp()
    if not retried then
        return false, "retried crossing failed: " .. tostring(why) .. " / " .. describe(io.state())
    end
    return true
end

return M
