-- Input-only route planner. The caller reads pinned symbols and owns every frame.
-- No emulator, memory, options, event-flag, party or inventory writes occur here.
-- Geometry: pret data/maps/objects/{RedsHouse1F,RedsHouse2F,OaksLab,
-- ViridianCity,ViridianPokecenter}.asm. Story/menu branches: scripts/PalletTown,
-- scripts/OaksLab and engine/{battle/core,menus/naming_screen}.asm.
local M={}
local MAP={pallet=0x00,viridian=0x01,route1=0x0c,house1=0x25,house2=0x26,lab=0x28,center=0x29}
local function integer(v)return type(v)=="number"and v%1==0 and v>=0 end
local function empty()return {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}end
local function key(name)local buttons=empty();if name then buttons[name]=true end;return buttons end
function M.new(options)
    assert(type(options)=="table"and(options.variant=="red"or options.variant=="blue"or options.variant=="yellow"),"route variant required")
    assert(type(options.initiator)=="boolean","explicit route initiator required")
    local limit=options.max_frames or 18000
    assert(integer(limit)and limit>=1,"bounded route frame budget required")
    local self={phase="waiting_enrollment",transitions={},center_ready=false,native_started=false}
    local start,last_frame,last_buttons,last_map
    local target,last_tile,last_motion,axis,blocked,detour_until,detour="",nil,nil,"x",0,nil,nil
    local center_entry_x,center_waypoint,face_until
    local function phase(name,point)
        if self.phase~=name then
            self.phase=name;self.transitions[#self.transitions+1]={phase=name,frame=point.frame,map=point.map,x=point.x,y=point.y}
        end
    end
    local function pulse(point,name)return point.frame%16<2 and key(name or "A")or empty()end
    local function navigate(point,x,y)
        local desired=point.map..":"..x..":"..y
        local tile=point.map..":"..point.x..":"..point.y
        if desired~=target then target=desired;last_tile=nil;last_motion=point.frame;axis="x";blocked=0;detour_until=nil end
        if point.x==x and point.y==y then return empty(),true end
        if tile~=last_tile then last_tile=tile;last_motion=point.frame;blocked=0 end
        if detour_until and point.frame<detour_until then return key(detour),false end
        detour_until=nil
        if point.frame-last_motion>=40 then
            axis=axis=="x"and"y"or"x";last_motion=point.frame;blocked=blocked+1
            if blocked>=2 then
                detour=axis=="x"and(point.y>1 and"Up"or"Down")or(point.x>1 and"Left"or"Right")
                detour_until=point.frame+32;blocked=0;return key(detour),false
            end
        end
        local direction
        if axis=="x"and point.x~=x then direction=point.x<x and"Right"or"Left"
        elseif axis=="y"and point.y~=y then direction=point.y<y and"Down"or"Up"
        elseif point.x~=x then direction=point.x<x and"Right"or"Left"
        else direction=point.y<y and"Down"or"Up"end
        return key(direction),false
    end
    local function decide(point,progress)
        assert(type(point)=="table"and type(progress)=="table","observed route snapshot and handshake required")
        for _,name in ipairs({"frame","map","x","y","battle","joy_ignore","party_count","naming_screen"})do
            assert(integer(point[name]),"invalid route observation: "..name)
        end
        assert(type(point.safe)=="boolean"and type(point.starter)=="boolean","explicit safe/starter observations required")
        assert(not last_frame or point.frame>=last_frame,"route frame moved backwards")
        if not progress.enrolled or not progress.bootstrap or not progress.saved then phase("waiting_enrollment",point);return empty()end
        start=start or point.frame
        assert(point.frame-start<=limit,"input-only route frame budget exhausted")
        if progress.trade_complete then phase("complete",point);return empty()end
        if progress.native_borrowed then self.native_started=true;phase("native_ui",point);return pulse(point)end
        if point.native_query then self.native_started=true;phase("native_query",point);return empty()end
        if self.native_started then phase("waiting_native_completion",point);return empty()end
        if point.map~=last_map then
            target="";last_map=point.map
            if point.map==MAP.center then center_entry_x=nil;center_waypoint=nil;face_until=nil end
        end
        if point.battle~=0 then
            if options.variant=="yellow"and point.battle_type==4 then
                phase("oak_tutorial",point);return pulse(point)
            end
            phase(point.battle==1 and"wild_battle"or"rival_battle",point)
            local menu=point.menu or {}
            if point.battle==1 and menu.top_y==14 and menu.maximum==1 then
                if menu.top_x==9 then return key("Right")end
                if menu.top_x==15 then return menu.index==0 and key("Down")or pulse(point)end
            end
            return pulse(point)
        end
        if point.party_count>0 and not point.starter and point.naming_screen==2 then
            phase("starter_nickname",point)
            local menu=point.menu or {}
            if menu.maximum==1 and menu.top_y==8 and menu.top_x==15 then return pulse(point,"B")end
            return pulse(point)
        end
        if point.joy_ignore~=0 or point.text_active then phase("script_text",point);return pulse(point)end
        if not point.safe then phase("waiting_world_boundary",point);return empty()end
        if point.map==MAP.house2 then phase("bedroom_stairs",point);return navigate(point,7,1)end
        if point.map==MAP.house1 then phase("house_exit",point);return navigate(point,2,7)end
        if point.map==MAP.pallet then phase("pallet_north",point);return navigate(point,10,0)end
        if point.map==MAP.lab then
            if not point.starter then
                phase("choose_starter",point)
                local ball=options.variant=="yellow"and 7 or 6
                -- The table occupies row 3; its west edge is not a walkable
                -- neighbor. Approach the source ball from the south aisle.
                if point.y<4 then return navigate(point,point.x,4)end
                if point.y~=4 or point.x~=ball then return navigate(point,ball,4)end
                if not face_until then face_until=point.frame+2 end
                return point.frame<face_until and key("Up")or pulse(point)
            end
            phase("lab_exit",point);return navigate(point,5,11)
        end
        if point.map==MAP.route1 then phase("route_one_north",point);return navigate(point,10,0)end
        if point.map==MAP.viridian then phase("viridian_center",point);return navigate(point,23,25)end
        if point.map==MAP.center then
            phase("center_receptionist",point)
            if not center_waypoint then center_entry_x=point.x;center_waypoint=1 end
            local targets={{center_entry_x,6},{11,6},{11,3}}
            if center_waypoint<=#targets then
                local row=targets[center_waypoint];local buttons,arrived=navigate(point,row[1],row[2])
                if arrived then center_waypoint=center_waypoint+1 end
                return buttons
            end
            self.center_ready=true;phase("center_ready",point)
            if not progress.linked or not progress.both_at_center then return empty()end
            if not options.initiator then return empty()end
            if not face_until then face_until=point.frame+2 end
            return point.frame<face_until and key("Up")or pulse(point)
        end
        error("input route reached an unplanned map: "..point.map,0)
    end
    function self:buttons(point,progress)
        if last_frame==point.frame and last_buttons~=nil and not progress.native_borrowed and not point.native_query
            and not progress.trade_complete then
            -- Handshake changes may release an idle planner at the same frame.
            if self.phase~="waiting_enrollment"and self.phase~="center_ready"then return key(last_buttons),self.phase end
        end
        local buttons=decide(point,progress)
        last_frame=point.frame;last_buttons=false
        for name,pressed in pairs(buttons)do if pressed then last_buttons=name end end
        return buttons,self.phase
    end
    function self:status()return {phase=self.phase,center_ready=self.center_ready,native_started=self.native_started,transitions=self.transitions}end
    return self
end
return M
