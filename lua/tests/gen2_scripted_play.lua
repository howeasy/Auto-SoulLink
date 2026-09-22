-- Gen 2 source-gated route candidate. Pure point -> buttons/phase/request.
-- No emulator globals, file IO, frame loops, save mutation or party staging.
-- A qualified game observer and lua/scripted_inputs.lua host are injected by
-- the coordinator's gate. Reaching route-saved is never fixture qualification.
local P = {}
local DIRECTIONS = {{"Up",0,-1},{"Left",-1,0},{"Down",0,1},{"Right",1,0}}

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

local function matches(point, map)
    return point.map_group == map.map_group and point.map_number == map.map_number
end

local function warp_to(map, destination)
    for _, warp in ipairs(map.warps) do if warp.destination == destination then return warp end end
    error("source warp missing: " .. destination)
end

-- Conservative source collision graph, restricted by current observed blockers.
-- Directional ledges, dynamic decorations and NPC movement still need live proof.
local function direction(map, point, goal)
    if not integer(point.x,0,map.width-1) or not integer(point.y,0,map.height-1) then
        return nil, "player coordinate outside source map"
    end
    local function key(x,y) return y*map.width+x+1 end
    local function destination(x,y)
        return goal.grass and map.grid[key(x,y)] == 2 or (not goal.grass and x == goal.x and y == goal.y)
    end
    if destination(point.x,point.y) then return "arrived" end
    if type(point.can_step) ~= "table" then return nil, "live collision observation missing" end
    local blocked = {}
    for _, object in ipairs(point.blocked or {}) do blocked[key(object.x,object.y)] = true end
    for _, warp in ipairs(map.warps) do
        if goal.grass or warp.x ~= goal.x or warp.y ~= goal.y then blocked[key(warp.x,warp.y)] = true end
    end
    local queue, head, visited = {{point.x,point.y,false}}, 1, {[key(point.x,point.y)] = true}
    while head <= #queue do
        local node = queue[head]; head = head+1
        for _, delta in ipairs(DIRECTIONS) do
            local x,y = node[1]+delta[2],node[2]+delta[3]
            if x >= 0 and x < map.width and y >= 0 and y < map.height then
                local index = key(x,y)
                local first = node[3] or delta[1]
                if not visited[index] and map.grid[index] ~= 0 and not blocked[index]
                   and (node[3] or point.can_step[delta[1]] == true) then
                    visited[index] = true
                    if destination(x,y) then return first end
                    queue[#queue+1] = {x,y,first}
                end
            end
        end
    end
    return nil, "source route blocked or live collision facts disagree"
end

function P.new(facts, case)
    assert(type(facts) == "table" and facts.schema == "gen2-scripted-route-facts-v1", "source route facts required")
    assert(type(case) == "table" and case.title == facts.title
        and (case.target == "town" or case.target == "battle"), "selected fixture case required")
    assert(type(case.attempt_id) == "string" and #case.attempt_id > 0, "attempt identity required")
    local maps, starter, balls = facts.maps, facts.starter, facts.balls
    local self = {terminal="route-saved",phase="new-game",qualified=false}
    local release, entered, injection_pending, save_counter = false, false, false, nil
    assert(integer(case.title_idle_frames,0,40000), "bounded requested title idle required")
    local title_started = nil

    local function press(button)
        release = true
        return {[button]=true}, self.phase
    end
    local function choose(ui, wanted, columns)
        if type(ui.items) ~= "table" or not integer(ui.cursor,1,#ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local target = nil
        for index, label in ipairs(ui.items) do
            if type(label) ~= "string" then return nil, "invalid menu label" end
            if string.upper(label) == string.upper(wanted) then
                if target then return nil, "ambiguous menu label" end
                target = index
            end
        end
        if not target then return nil, "required native menu item missing: " .. wanted end
        if target == ui.cursor then return press("A") end
        local tx,cx = (target-1)%columns,(ui.cursor-1)%columns
        if tx ~= cx then return press(tx > cx and "Right" or "Left") end
        return press(target > ui.cursor and "Down" or "Up")
    end
    local function walk(point,map,goal)
        local button,why = direction(map,point,goal)
        if not button then return nil,why end
        if button ~= "arrived" then return {[button]=true},self.phase end
        -- A carpet warp (COLL_WARP_CARPET_*) fires only on a push toward its edge; standing on
        -- it is not arrival. The house and lab exits are carpets (route facts warp.carpet).
        if goal.carpet then return press(goal.carpet) end
        return {},self.phase
    end
    local function has_balls(point)
        local pocket = point.ball_pocket
        if type(pocket) ~= "table" or not integer(pocket.count,0,balls.capacity)
           or type(pocket.items) ~= "table" or #pocket.items ~= pocket.count or pocket.terminator ~= 255 then
            return nil,"malformed observed Ball pocket"
        end
        local found = false
        for _, item in ipairs(pocket.items) do
            if not integer(item.id,1,254) or not integer(item.quantity,1,99) then return nil,"malformed Ball slot" end
            if item.id == balls.item then found = true end
        end
        return found
    end

    function self.step(point, frame)
        if type(point) ~= "table" or point.title ~= case.title or point.rom_sha1 ~= facts.rom_sha1
           or point.core_mode ~= "CGB" or point.attempt_id ~= case.attempt_id
           or point.facts_fingerprint ~= facts.fingerprint or not integer(frame,0,math.huge) then
            return nil,"missing or foreign source-bound CGB observation"
        end
        if point.action_error then return nil,"fixture action refused: " .. tostring(point.action_error) end
        if release then release=false; return {},self.phase end
        if self.phase == self.terminal then return {},self.phase end
        if point.has_existing_save and not entered then return nil,"cold NEW GAME requires an empty isolated save lane" end
        if point.ui ~= nil then
            local ui = point.ui
            local origin = type(ui) == "table" and facts.ui_origins[ui.kind]
            if not origin or ui.origin ~= origin.symbol then return nil,"unmapped or unbound native UI state" end
            if point.input_ready ~= true then return {},self.phase end
            if ui.kind == "title" then
                title_started = title_started or frame
                if frame-title_started < case.title_idle_frames then return {},self.phase end
                return press("Start")
            end
            if ui.kind == "main_menu" then
                if entered then return nil,"unexpected reset to main menu" end
                return choose(ui,"NEW GAME",1)
            end
            if ui.kind == "gender" then return choose(ui,"Boy",1) end
            if ui.kind == "name_choices" then
                local index = case.identity == "ot2" and 3 or 2
                if type(ui.items) ~= "table" or not ui.items[index] then return nil,"preset name choices missing" end
                return choose(ui,ui.items[index],1)
            end
            if ui.kind == "clock_hour" or ui.kind == "clock_minute" or ui.kind == "text" then return press("A") end
            if ui.kind == "yes_no" then
                local known = {nickname=true,clock_confirm=true,mom_dst=true,mom_dst_confirm=true,
                    mom_phone=true,elm_mission=true,starter_confirm=true,save_confirm=true}
                if not known[ui.prompt] then return nil,"unmapped yes/no prompt" end
                return choose(ui,ui.prompt == "nickname" and "NO" or "YES",1)
            end
            if ui.kind == "start_menu" and save_counter ~= nil then return choose(ui,"SAVE",1) end
            if ui.kind == "battle_menu" and point.battle_mode == 1 then return choose(ui,"RUN",2) end
            return nil,"UI is not valid for current source route"
        end
        if point.overworld_ready ~= true then return {},self.phase end
        if point.battle_mode ~= 0 then return nil,"unexpected battle state without a mapped UI" end
        if not integer(point.party_count,0,1) then return nil,"route requires at most one played starter" end
        if not entered then
            if not matches(point,maps.PlayersHouse2F) or point.party_count ~= 0 then
                return nil,"NEW GAME did not reach source bedroom with an empty party"
            end
            entered=true
        end
        if matches(point,maps.PlayersHouse2F) then
            self.phase="leave-bedroom"
            return walk(point,maps.PlayersHouse2F,warp_to(maps.PlayersHouse2F,"PLAYERS_HOUSE_1F"))
        end
        if matches(point,maps.PlayersHouse1F) then
            self.phase="mom"
            if point.mom_scene ~= maps.PlayersHouse1F.scenes.SCENE_PLAYERSHOUSE1F_NOOP or point.pokegear_obtained ~= true then
                local trigger = maps.PlayersHouse1F.coord_events[1]
                -- Gold/Silver start Mom from an on-entry scene script, not a coord event
                -- (pokegold maps/PlayersHouse1F.asm:9,15-16): wait; max_phase_frames bounds it.
                if not trigger then return {},self.phase end
                return walk(point,maps.PlayersHouse1F,trigger)
            end
            return walk(point,maps.PlayersHouse1F,warp_to(maps.PlayersHouse1F,"NEW_BARK_TOWN"))
        end
        if point.pokegear_obtained ~= true then return nil,"Mom's normal Pokegear scene was not observed" end
        if matches(point,maps.NewBarkTown) and point.party_count == 0 then
            self.phase="to-elm"
            return walk(point,maps.NewBarkTown,warp_to(maps.NewBarkTown,"ELMS_LAB"))
        end
        if matches(point,maps.ElmsLab) and point.party_count == 0 then
            self.phase="starter"
            if point.lab_scene ~= maps.ElmsLab.scenes.SCENE_ELMSLAB_CANT_LEAVE then return {},self.phase end
            local object = maps.ElmsLab.objects[starter.object]
            local goal = {x=object.x,y=object.y+1}
            if point.x ~= goal.x or point.y ~= goal.y then return walk(point,maps.ElmsLab,goal) end
            return press(point.facing == "Up" and "A" or "Up")
        end
        if point.party_count ~= 1 or point.starter_species ~= starter.species or point.starter_level ~= starter.level
           or point.got_starter ~= true or point.new_bark_scene ~= maps.NewBarkTown.scenes.SCENE_NEWBARKTOWN_NOOP then
            return nil,"played starter grant and west-exit release are not established"
        end
        if case.target == "battle" then
            local found,why = has_balls(point)
            if found == nil then return nil,why end
            if not found then
                if injection_pending then return {},self.phase end
                if not matches(point,maps.ElmsLab) or point.ball_pocket.count ~= 0 then
                    return nil,"O-10 only permits the empty Ball pocket at the settled lab checkpoint"
                end
                self.phase="o10-balls"; injection_pending=true
                -- O-10: test/validation staging only; never a natural ball-acquisition witness.
                return {},self.phase,{kind="o10-ball-pocket",exception="O-10",natural_acquisition=false,
                    attempt_id=case.attempt_id,
                    facts_fingerprint=facts.fingerprint,bank=balls.bank,
                    expected={{address=balls.count_address,value=0},{address=balls.data_address,value=255}},
                    writes={{address=balls.data_address,value=balls.item},{address=balls.data_address+1,value=balls.quantity},
                            {address=balls.data_address+2,value=255},{address=balls.count_address,value=1}}}
            end
            if matches(point,maps.ElmsLab) then
                self.phase="leave-elm"
                return walk(point,maps.ElmsLab,warp_to(maps.ElmsLab,"NEW_BARK_TOWN"))
            end
            if matches(point,maps.NewBarkTown) then
                self.phase="to-route29"
                local target = maps.NewBarkTown.coord_events[1]
                if not target then return nil,"west-exit source coordinate missing" end
                if point.x == 0 and point.y == target.y then return press("Left") end
                return walk(point,maps.NewBarkTown,{x=0,y=target.y})
            end
            if not matches(point,maps.Route29) then return nil,"route left source-supported maps" end
            self.phase="route29-grass"
            local button,why = direction(maps.Route29,point,{grass=true})
            if not button then return nil,why end
            if button ~= "arrived" then return {[button]=true},self.phase end
        elseif not matches(point,maps.ElmsLab) then return nil,"town fixture must remain inside Elm's lab" end
        self.phase="native-save"
        if not integer(point.save_success_counter,0,math.huge) then return nil,"native successful-save witness missing" end
        if save_counter == nil then save_counter=point.save_success_counter end
        if point.save_success_counter > save_counter and point.saved_at_least_once == 1 then
            self.phase=self.terminal
            return {},self.phase
        end
        return press("Start")
    end
    return self
end

function P.run(host, observe, facts, case, on_phase, on_request)
    assert(type(host) == "table" and type(host.run) == "function", "shared scripted-input host required")
    assert(type(observe) == "function", "qualified source-bound game observer required")
    local driver = P.new(facts,case)
    return host.run({name=case.name,terminal=driver.terminal,max_frames=case.max_frames,
        max_phase_frames=case.max_phase_frames,settle_frames=case.settle_frames,terminal_idle=true},
        function(frame)
            local point = observe()
            local buttons,phase,request = driver.step(point,frame)
            if buttons == nil then error(phase,0) end
            return buttons,phase,point,request
        end,on_phase,on_request)
end

return P
