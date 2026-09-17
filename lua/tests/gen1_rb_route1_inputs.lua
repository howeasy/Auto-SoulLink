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
-- Waypoints are the parcel route's own southbound paths (proven live), ending ON Route 1.
local paths={
    mart_exit={{3,7}},                                             -- Mart door -> Viridian (29,19)
    viridian_south={{29,20},{19,20},{19,30},{20,30},{20,36}},      -- past the edge -> Route 1
    route_south={{10,4},{14,4},{14,14},{9,14},{9,22},{12,22},{12,24},{8,24},{8,31},{10,31},{10,35}},
}
M.PARK={10,35}
function M.new(expected)
    assert(expected and (expected.player=="a" or expected.player=="b"),"R/B route identity required")
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
            assert(type(point.run_attempts)=="number" and point.run_attempts<8,"wild RUN attempt bound exceeded")
            if point.text_box==0x0B then -- BATTLE_MENU_TEMPLATE
                if point.menu_y~=14 or point.menu_max~=1 then return idle(),"unknown-wild-menu" end
                if point.menu_x==9 then return tap("Right",frame),"wild-select-right-column" end
                if point.menu_x~=15 then return idle(),"unknown-wild-menu" end
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
            assert(self.closing<=1800,"Mart menu did not close")
            return tap("B",frame),"close-mart-menu"
        end
        if point.map==0x2A then return follow("mart_exit",point) end
        if point.map==1 then return follow("viridian_south",point) end
        if point.map==0x0C then
            if point.x==M.PARK[1] and point.y==M.PARK[2] then return idle(),"route1-parked" end
            return follow("route_south",point)
        end
        return idle(),"unknown-map"
    end
    return self
end
return M
