-- Pure R/B walk from the Viridian Mart (after the first ball purchase) back to Route 1's
-- south edge tile (10,35), the parking tile the duo scenarios start from. Same shape as
-- gen1_rb_parcel_inputs: point -> buttons, phase; the caller owns frames. Wild battles on the
-- way are escaped with RUN exactly as the parcel route does.
-- The shared input shapes (idle/hold/tap/move): this file's own directory locates the module,
-- the way the sibling drivers are already loaded.
local function here() return (debug.getinfo(1, "S").source or ""):match("^@(.*[/\\])") or "" end
local C = dofile(here() .. "gen1_inputs_common.lua")
local idle, hold, tap, move = C.idle, C.hold, C.tap, C.move

local M = {}
-- Waypoints are the parcel route's own southbound paths (proven live), ending ON Route 1. They are
-- lane facts (P3b-e): F.WAYPOINTS.ROUTE1, copied in by `with_facts`.
local paths={}
function M.with_facts(facts)
    assert(facts and facts.WAYPOINTS and facts.WAYPOINTS.ROUTE1, "route1 needs a facts table")
    for name, tiles in pairs(facts.WAYPOINTS.ROUTE1) do
        if name ~= "park" then paths[name] = tiles end
    end
    M.PARK = facts.WAYPOINTS.ROUTE1.park
    return facts
end
M.with_facts(dofile(here() .. "gen1_rb_facts.lua")) -- load-time defaults for external readers
function M.new(expected)
    assert(expected and (expected.player=="a" or expected.player=="b"),"R/B route identity required")
    local F = M.with_facts(expected.facts or dofile(here() .. "gen1_rb_facts.lua"))
    local self={last_frame=-1,segments={},wild_active=false,closing=0}
    local function follow(name, point)
        local targets=paths[name]
        local index=self.segments[name] or 1
        while targets[index] and point.x==targets[index][1] and point.y==targets[index][2] do index=index+1 end
        self.segments[name]=index
        if not targets[index] then return idle(),name.."-arrival" end
        return move(point,targets[index]),name
    end
    function self.step(handshake,status,point,frame)
        assert(type(frame)=="number" and frame>self.last_frame,"route1 frame did not advance")
        self.last_frame=frame
        assert(point and type(point.map)=="number" and type(point.x)=="number" and type(point.y)=="number"
            and type(point.battle)=="number","complete read-only route point required")
        if point.battle~=0 then
            assert(point.battle==1 and point.battle_type==0 and type(point.party_hp)=="number" and point.party_hp>0,
                "unexpected trainer, special battle or whiteout")
            self.wild_active=true
            assert(type(point.run_attempts)=="number" and point.run_attempts<F.TUNING.wild_run_attempt_bound,
                "wild RUN attempt bound exceeded")
            if point.text_box==F.MENU.BATTLE.template then -- BATTLE_MENU_TEMPLATE
                if point.menu_y~=F.MENU.BATTLE.menu_y or point.menu_max~=F.MENU.BATTLE.menu_max then
                    return idle(),"unknown-wild-menu"
                end
                if point.menu_x==F.MENU.BATTLE.left_x then return tap("Right",frame),"wild-select-right-column" end
                if point.menu_x~=F.MENU.BATTLE.right_x then return idle(),"unknown-wild-menu" end
                if point.menu_index==0 then return tap("Down",frame),"wild-select-run" end
                if point.menu_index~=1 then return idle(),"unknown-wild-menu" end
                return tap("A",frame),"wild-attempt-run"
            end
            if point.text_box==nil or point.text_box==0 then return idle(),"wild-text-state-unknown" end
            return tap("A",frame),"wild-dialogue"
        end
        if self.wild_active then
            assert(point.battle_result==2 and type(point.party_hp)=="number" and point.party_hp>0,
                "wild battle ended without observed escape")
            self.wild_active=false
        end
        -- The parcel route ends inside the Mart's purchase UI: close it before walking.
        if point.font_loaded or point.joy_ignore~=0 then
            self.closing=self.closing+1
            assert(self.closing<=F.TUNING.stall_bound,"Mart menu did not close")
            return tap("B",frame),"close-mart-menu"
        end
        if point.map==F.MAP.VIRIDIAN_MART then return follow("mart_exit",point) end
        if point.map==F.MAP.VIRIDIAN_CITY then return follow("viridian_south",point) end
        if point.map==F.MAP.ROUTE_1 then
            if point.x==M.PARK[1] and point.y==M.PARK[2] then return idle(),"route1-parked" end
            return follow("route_south",point)
        end
        return idle(),"unknown-map"
    end
    return self
end
return M
