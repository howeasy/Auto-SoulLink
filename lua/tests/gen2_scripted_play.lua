-- Gen 2 source-gated route candidate. Pure point -> buttons/phase/request.
-- No emulator globals, file IO (beyond loading its sibling step rule), frame loops, save mutation or party
-- staging. A qualified game observer and lua/scripted_inputs.lua host are injected by
-- the coordinator's gate. Reaching route-saved is never fixture qualification.
local P = {}
-- the one shared step rule (ledges from the separate map.ledges field), from beside this file
local W = (function(dir)   -- beside this file, else $SLINK_ROOT/lua/tests (a copy run from elsewhere)
    local f = io.open(dir .. "gen2_walk.lua", "rb")
    if f then f:close() else dir = (os.getenv("SLINK_ROOT") or ".") .. "/lua/tests/" end
    return dofile(dir .. "gen2_walk.lua")
end)(debug.getinfo(1, "S").source:match("^@(.-)[^/\\]*$") or "lua/tests/")
local DIRECTIONS = W.DIRECTIONS

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

-- Source collision graph (gen2_walk.lua: ledges hop when the facts carry map.ledges), restricted by current
-- observed blockers. Dynamic decorations and NPC movement still need live proof.
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
    -- Observed objects first; when they close every path, retry without them: an object struct can
    -- outlive its sprite on screen (the errand run and Crystal U1e run 1 both read a phantom at Route 29
    -- (11,7), the one-tile aisle west), and a real NPC only bumps the step, re-planned next frame.
    local function search(objects)
        local blocked = {}
        for _, object in ipairs(objects and point.blocked or {}) do blocked[key(object.x,object.y)] = true end
        for _, warp in ipairs(map.warps) do
            if goal.grass or warp.x ~= goal.x or warp.y ~= goal.y then blocked[key(warp.x,warp.y)] = true end
        end
        for _, tile in ipairs(goal.avoid or {}) do blocked[key(tile.x,tile.y)] = true end
        local step = W.stepper(map, point.can_step)
        local queue, head, visited = {{point.x,point.y,false}}, 1, {[key(point.x,point.y)] = true}
        while head <= #queue do
            local node = queue[head]; head = head+1
            for _, delta in ipairs(DIRECTIONS) do
                local x,y = step(node[1],node[2],delta,not node[3])
                if x then
                    local index = key(x,y)
                    local first = node[3] or delta[1]
                    if not visited[index] and not blocked[index] then
                        visited[index] = true
                        if destination(x,y) then return first end
                        queue[#queue+1] = {x,y,first}
                    end
                end
            end
        end
    end
    local found = search(true) or search(false)
    if found then return found end
    local steps, objects = {}, {}
    for _, d in ipairs(DIRECTIONS) do steps[#steps+1] = d[1] .. "=" .. tostring(point.can_step[d[1]]) end
    for _, b in ipairs(point.blocked or {}) do objects[#objects+1] = b.x .. "," .. b.y end
    return nil, string.format("source route blocked or live collision facts disagree at %d,%d goal %s,%s can_step %s blocked %s",
        point.x, point.y, tostring(goal.x), tostring(goal.y), table.concat(steps, " "), table.concat(objects, " "))
end

P.direction = direction   -- exposed for tests/unit/test_gen2_walk.py

function P.new(facts, case)
    assert(type(facts) == "table" and facts.schema == "gen2-scripted-route-facts-v1", "source route facts required")
    assert(type(case) == "table" and case.title == facts.title
        and (case.target == "town" or case.target == "battle"), "selected fixture case required")
    assert(type(case.attempt_id) == "string" and #case.attempt_id > 0, "attempt identity required")
    local maps, starter, balls = facts.maps, facts.starter, facts.balls
    -- The Gold errand (tools/gen2_fixtures.ERRAND_FIXTURES; docs/gen2/reviews/OMP_GOLD_ERRAND_FACTS_2026-09-23.md):
    -- only errand facts carry its events, maps and the naming-screen origin.
    local errand = facts.observer.errand_events ~= nil
    local handed, naming_start = false, true
    local self = {terminal="route-saved",phase="new-game",qualified=false}
    local release, entered, injection_pending, save_counter = false, false, false, nil
    assert(integer(case.title_idle_frames,0,40000), "bounded requested title idle required")
    local title_started = nil

    -- A native press is HELD for HOLD frames: Crystal's main-menu loop (engine/menus/main_menu.asm MainMenuJoypadLoop -> MenuJoypadLoop) samples GetJoypad once per iteration, after WaitBGMap's DelayFrames 4 (home/menu.asm), so a 1-frame press on a fixed re-pulse cadence can stay out of phase forever (live attempt n2-crystal-town-a1..a3). A/B/Start never repeat at any hold (GetMenuJoypad reads the hJoyPressed edge, home/menu.asm:35-48); only a held DIRECTION repeats (hJoyLast via JoyTextDelay: 15 frames, then 5), so a menu direction press stays < 15. The overworld is different: a normal walk step is 8 frames (StepVectors normal rows, engine/overworld/map_objects.asm:367-380; slow 16, bike 4) and DoPlayerMovement reads the HELD hJoyDown (player_movement.asm:14-16), so a 12-frame direction press walks up to two tiles (OMP gen2-O3). Overworld walking therefore never uses press(): walk() holds the direction per frame and re-plans from the observed tile; the only overworld direction presses are a blocked face-turn, a map-edge crossing and a carpet push, where a second step is blocked or absorbed by that re-plan. ponytail: one HOLD for both; split it per context if a route ever needs exactly one tile per press.
    local HOLD, held, hold_left = 12, nil, 0
    local function press(button)
        release, held, hold_left = true, button, HOLD - 1
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

    -- One map at a time, by the two errand events. Edges are source connections (data/maps/attributes.asm),
    -- crossed by pressing the side from the edge tile, like the New Bark west exit above.
    local function edge(point,map,tile,side)
        if point.x == tile.x and point.y == tile.y then return press(side) end
        return walk(point,map,tile)
    end
    function self.errand(point)
        local egg = point.got_egg == true
        if not egg then
            if matches(point,maps.ElmsLab) then
                self.phase="leave-elm"
                return walk(point,maps.ElmsLab,warp_to(maps.ElmsLab,"NEW_BARK_TOWN"))
            end
            if matches(point,maps.NewBarkTown) then
                self.phase="to-route29"
                local target = maps.NewBarkTown.coord_events[1]
                if not target then return nil,"west-exit source coordinate missing" end
                return edge(point,maps.NewBarkTown,{x=0,y=target.y},"Left")
            end
            -- Route 29 west -> Cherrygrove (Route 29 west connection, offset 0) -> north to Route 30 (offset 5).
            if matches(point,maps.Route29) then self.phase="errand-west" return edge(point,maps.Route29,{x=0,y=6},"Left") end
            if matches(point,maps.CherrygroveCity) then
                self.phase="errand-west"
                return edge(point,maps.CherrygroveCity,{x=16,y=0},"Up")
            end
            if matches(point,maps.Route30) then
                self.phase="errand-mr-pokemon"
                return walk(point,maps.Route30,warp_to(maps.Route30,"MR_POKEMONS_HOUSE"))
            end
            -- MrPokemonsHouse's sdefer scene (pokegold maps/MrPokemonsHouse.asm:12-13) walks the player and runs
            -- to the egg and Oak's scene: A-press waits only, taken by the UI branch above.
            if matches(point,maps.MrPokemonsHouse) then self.phase="errand-mr-pokemon" return {},self.phase end
            return nil,"errand left source-supported maps before the egg"
        end
        if matches(point,maps.MrPokemonsHouse) then
            self.phase="errand-egg"
            return walk(point,maps.MrPokemonsHouse,warp_to(maps.MrPokemonsHouse,"ROUTE_30"))
        end
        -- Elm's ROBBED call rings on the first outdoor step (engine/phone/phone.asm:306-317): text + waitbutton.
        if matches(point,maps.Route30) then self.phase="errand-egg" return edge(point,maps.Route30,{x=7,y=53},"Down") end
        if matches(point,maps.CherrygroveCity) then
            -- The rival's coord tiles (33,6)/(33,7) (pokegold maps/CherrygroveCity.asm:558-559, armed by
            -- MrPokemonsHouse.asm:124) are the only way east: rows 4-5 end at x=31 and rows 8-9 at x=33, so the
            -- battle is unavoidable. It is BATTLETYPE_CANLOSE (no whiteout, party healed, no flags); the lead
            -- LEERs until it faints so it gains no experience (inspect_candidate's fresh level-5 guard).
            self.phase="errand-east"
            return edge(point,maps.CherrygroveCity,{x=39,y=6},"Right")
        end
        if matches(point,maps.Route29) then self.phase="errand-east" return edge(point,maps.Route29,{x=59,y=8},"Right") end
        if matches(point,maps.NewBarkTown) then
            self.phase="errand-elm"
            return walk(point,maps.NewBarkTown,warp_to(maps.NewBarkTown,"ELMS_LAB"))
        end
        if matches(point,maps.ElmsLab) then
            -- The officer's coord tiles (4,5)/(5,5) are the lab's only north aisle (MeetCopScript, naming screen);
            -- once he has left, Elm (5,2) is faced from (5,3) and ElmAfterTheftScript takes the egg (:283-309).
            self.phase="errand-elm"
            local elm = maps.ElmsLab.objects.ProfElmScript
            local goal = {x=elm.x,y=elm.y+1}
            for _, object in ipairs(point.blocked or {}) do
                if object.x == goal.x and object.y == goal.y then
                    goal = {x=elm.x,y=elm.y+2}
                    if point.x == goal.x and point.y == goal.y then return {},self.phase end
                end
            end
            if point.x ~= goal.x or point.y ~= goal.y then return walk(point,maps.ElmsLab,goal) end
            return press(point.facing == "Up" and "A" or "Up")
        end
        return nil,"errand left source-supported maps after the egg"
    end

    function self.step(point, frame)
        if type(point) ~= "table" or point.title ~= case.title or point.rom_sha1 ~= facts.rom_sha1
           or point.core_mode ~= "CGB" or point.attempt_id ~= case.attempt_id
           or point.facts_fingerprint ~= facts.fingerprint or not integer(frame,0,math.huge) then
            return nil,"missing or foreign source-bound CGB observation"
        end
        if point.action_error then return nil,"fixture action refused: " .. tostring(point.action_error) end
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, self.phase end
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
            -- Script/text waits (PromptButton, WaitButton, Mom's weekday picker) all take A: map scripts
            -- keep OWPlayerInput from running (engine/overworld/events.asm:241-246), so these are the
            -- only UI a script shows between its yes/no boxes. A on the picker's .loop2
            -- (engine/rtc/timeset.asm:420-423) accepts the shown day, never navigated with Up/Down.
            -- The officer's NameRival (pokegold maps/ElmsLab.asm:508-518): START parks the cursor on END
            -- (engine/menus/naming_screen.asm:404-418), A on END stores the entry (:393-399, :424-428); an empty
            -- entry takes the default rival name (engine/events/specials.asm:80-94). A stray A on a letter only
            -- adds it to the rival's name.
            if ui.kind == "naming" then
                naming_start = not naming_start
                return press(naming_start and "A" or "Start")
            end
            if ui.kind == "clock_hour" or ui.kind == "clock_minute" or ui.kind == "text" or ui.kind == "prompt_button"
               or ui.kind == "wait_button" or ui.kind == "day_picker" then return press("A") end
            if ui.kind == "yes_no" then
                -- SetDayOfWeek (engine/rtc/timeset.asm:385-436) is Mom's own picker, called from
                -- MeetMomScript before the DST questions (maps/PlayersHouse1F.asm:49/40). Its
                -- ConfirmWeekdayText confirm ("<DAY>, is it?", engine/rtc/timeset.asm:531-540,
                -- text at data/text/common_1.asm _OakTimeIsItText) shares the same YesNoBox origin
                -- as every other yes/no prompt. The picker is left on its default (wTempDayOfWeek=SUNDAY,
                -- timeset.asm:398-399; .loop keeps it), so SUNDAY is confirmed, and re-confirmed on a
                -- "No" loop-back (timeset.asm:429 jr c, .loop).
                local known = {nickname=true,clock_confirm=true,mom_dst=true,mom_dst_confirm=true,
                    mom_phone=true,elm_mission=true,starter_confirm=true,save_confirm=true,day_confirm=true,
                    tutorial=errand}
                if not known[ui.prompt] then return nil,"unmapped yes/no prompt" end
                -- The Route 29 catching tutorial: NO (pokegold maps/Route29.asm:47-48 -> Script_RefusedTutorial1,
                -- :89-95): YES would run the auto-input catch and could add its Rattata to the party.
                return choose(ui,(ui.prompt == "nickname" or ui.prompt == "tutorial") and "NO" or "YES",1)
            end
            if ui.kind == "start_menu" and save_counter ~= nil then return choose(ui,"SAVE",1) end
            if ui.kind == "battle_menu" and point.battle_mode == 1 then return choose(ui,"RUN",2) end
            if errand and ui.kind == "battle_menu" and point.battle_mode == 2 then return choose(ui,"FIGHT",2) end
            if errand and ui.kind == "move_menu" and point.battle_mode == 2 then return choose(ui,"LEER",1) end
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
            if errand and not point.gave_egg then return self.errand(point) end
            if matches(point,maps.ElmsLab) then
                if errand and not handed then
                    handed = true
                    self.phase = "errand-handoff"   -- ElmAfterTheftScript ran (EVENT_GAVE_MYSTERY_EGG_TO_ELM)
                    return {},self.phase
                end
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
