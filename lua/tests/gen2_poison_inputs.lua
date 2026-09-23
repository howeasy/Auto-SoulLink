--[[
  lua/tests/gen2_poison_inputs.lua -- card gen2-u1e-poison: a party mon faints to OVERWORLD poison
  (DoPoisonStep.DamageMonIfPoisoned, C engine/events/poisonstep.asm:59-99; the faint branch :88-94 is the
  pack's poison_faint site), from real play with normal buttons only. Shape of lua/tests/duo/gen2_faint_inputs.lua:
  PI.new(ctx, SG, F, FI, opts) -> driver, observe, spec for F.play.

  Stimulus (docs/gen2/reviews/OMP_O21_U1E_SITE_FACTS_2026-09-23.md F2; the battle fixtures play at DAY: InitClock's
  default hour 10, C engine/rtc/timeset.asm:50, and the U1d Route 29 catches were Pidgey): a wild mon that knows
  POISON_STING. Weedle and Spinarak learn it at L1 (C/G data/pokemon/evos_attacks.asm WeedleEvosAttacks :197-202,
  SpinarakEvosAttacks :2275-2281); at day Route 30 holds Weedle (C slot 5 = 5%, S slots 2+5 = 35%; data/wild/
  johto_grass.asm ROUTE_30, data/wild/probabilities.asm GrassMonProbTable). Gold has no day poisoner south of
  the Route 30 battle demo (card ruling: Gold waits for its own fixture).
  Phases:
    travel   Route 29 -> CherrygroveCity -> Route 30 (the facts' legs: a source-connection edge per map, crossed by
             holding the side; attributes.asm `connection`), then onto the nearest Route 30 grass tile. Paths are a
             source-grid Dijkstra that prefers floor to grass (fewer encounters); ledges stay walls.
    hunt     oscillate in the grass. A wild battle whose foe knows no POISON_STING: RUN (retried through
             "Can't escape!"). A foe that knows it: FIGHT -> a passive move (LEER/GROWL/...; never damage it) each
             turn until the target (the lead) carries PSN, then RUN. The target fainting in battle is a failure.
    tick     the target is poisoned in the party: oscillate between the two floor park tiles (no grass, no
             encounter) until opts.fainted() -- the probe's poison_faint hit; every 4 steps DoPoisonStep takes
             1 HP (C engine/overworld/events.asm:905-912). The "fainted!" text box takes A.
    park     walk back to park[1] (next to grass, so the faint leg can start) -> "poisoned" (terminal).
  facts (SLINK_GEN2_U1_FACTS.poison, tests/live/test_gen2_frame_align.poison_facts):
    maps {name -> _map_facts}, legs {{map, side, exits={{x,y}}}}, hunt_map, park {{x,y},{x,y}},
    moves {POISON_STING=id}, psn_mask (1 << PSN, constants/battle_constants.asm).
--]]
local PI = {}
PI.DIRECTIONS = {{"Up", 0, -1}, {"Left", -1, 0}, {"Down", 0, 1}, {"Right", 1, 0}}
PI.GRASS_COST = 4   -- ponytail: a weight, not a proof; the hunt only needs FEWER Route 29 encounters
PI.HOLD = 12

local fmt = string.format
local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

-- Pure: first step of a cheapest path (floor 1, grass GRASS_COST) to any goal tile; "arrived" on a goal.
-- Warps are walls (never entered by accident); the first step must be live-steppable.
function PI.step_toward(map, point, goals)
    if not integer(point.x, 0, map.width - 1) or not integer(point.y, 0, map.height - 1) then
        return nil, "player coordinate outside the source map"
    end
    local W = map.width
    local function key(x, y) return y * W + x + 1 end
    local goal = {}
    for _, g in ipairs(goals) do goal[key(g.x, g.y)] = true end
    if goal[key(point.x, point.y)] then return "arrived" end
    if type(point.can_step) ~= "table" then return nil, "live collision observation missing" end
    local blocked = {}
    for _, object in ipairs(point.blocked or {}) do blocked[key(object.x, object.y)] = true end
    for _, warp in ipairs(map.warps or {}) do blocked[key(warp.x, warp.y)] = true end
    -- bucket Dijkstra: costs are small integers
    local best, first, buckets, top = {[key(point.x, point.y)] = 0}, {}, {[0] = {{point.x, point.y}}}, 0
    local cost = 0
    while cost <= top do
        local bucket = buckets[cost] or {}
        local i = 1
        while i <= #bucket do
            local node = bucket[i]; i = i + 1
            local k = key(node[1], node[2])
            if best[k] == cost then
                if goal[k] then return first[k] end
                for _, d in ipairs(PI.DIRECTIONS) do
                    local x, y = node[1] + d[2], node[2] + d[3]
                    if x >= 0 and x < W and y >= 0 and y < map.height then
                        local n = key(x, y)
                        local tile = map.grid[n]
                        local start = node[1] == point.x and node[2] == point.y
                        if tile ~= 0 and not blocked[n] and (not start or point.can_step[d[1]] == true) then
                            local c = cost + (tile == 2 and PI.GRASS_COST or 1)
                            if best[n] == nil or c < best[n] then
                                best[n], first[n] = c, start and d[1] or first[k]
                                buckets[c] = buckets[c] or {}
                                table.insert(buckets[c], {x, y})
                                if c > top then top = c end
                            end
                        end
                    end
                end
            end
        end
        cost = cost + 1
    end
    return nil, fmt("no source path from %d,%d on %s", point.x, point.y, tostring(map.map_const))
end

local function on(point, map) return point.map_group == map.map_group and point.map_number == map.map_number end

-- Pure point -> buttons, phase. point adds: poison_fainted, active_slot, party ({slot -> {hp, status}}),
-- foe_sting (the wild foe knows POISON_STING), target_psn (the active battle mon carries PSN), poison_fainted.
function PI.driver(F, facts, opts)
    local self = {terminal="poisoned", phase="travel", battles=0}
    local held, hold_left, release = nil, 0, false
    local here, from, target = nil, nil, nil
    local maps, hunt = facts.maps, facts.maps[facts.hunt_map]
    local passive = opts.moves
    local function press(button)
        release, held, hold_left = true, button, PI.HOLD - 1
        return {[button]=true}, self.phase
    end
    local function choose(ui, wanted, columns)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local index
        for i, label in ipairs(ui.items) do
            if type(label) == "string" and label:upper() == wanted then
                if index then return nil, "ambiguous menu label " .. wanted end
                index = i
            end
        end
        if not index then return nil, "required native menu item missing: " .. wanted end
        if index == ui.cursor then return press("A") end
        local tx, cx = (index - 1) % columns, (ui.cursor - 1) % columns
        if tx ~= cx then return press(tx > cx and "Right" or "Left") end
        return press(index > ui.cursor and "Down" or "Up")
    end
    local function walk(map, point, goals)
        local button, why = PI.step_toward(map, point, goals)
        if not button then return nil, why end
        if button == "arrived" then return nil, "arrived" end
        return {[button]=true}, self.phase
    end
    local function status(point, slot)
        local mon = type(point.party) == "table" and point.party[slot]
        return mon and mon.hp, mon and mon.status
    end
    local function psn(value) return integer(value, 0, 255) and (value // facts.psn_mask) % 2 == 1 end
    local function battle(point, ui)
        local hunting = self.phase == "hunt"
        local fight = hunting and point.foe_sting == true and point.active_slot == target and point.target_psn ~= true
        if ui.kind == "battle_menu" then
            if point.battle_mode ~= 1 then return nil, "battle menu outside a wild battle" end
            return choose(ui, fight and "FIGHT" or "RUN", 2)
        end
        if ui.kind == "move_menu" then
            if not fight then return press("B") end
            if type(ui.items) ~= "table" then return nil, "move list unreadable" end
            for _, name in ipairs(passive) do
                for _, label in ipairs(ui.items) do
                    if type(label) == "string" and label:upper() == name then return choose(ui, name, 1) end
                end
            end
            return nil, "the target knows no passive move"
        end
        if ui.kind == "yes_no" and ui.prompt == "next_mon" then return nil, "the target fainted in battle before the poison" end
        if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
        return nil, "UI is not valid in battle: " .. tostring(ui.kind)
    end
    function self.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, self.phase end
        if release then release = false; return {}, self.phase end
        if self.phase == self.terminal then return {}, self.phase end
        local ui = point.ui
        if integer(point.battle_mode, 1, 255) then
            if self.phase == "tick" or self.phase == "park" then return nil, "a battle started on the park tiles" end
            if target == nil and integer(point.active_slot, 0, 5) then target = point.active_slot end
            if ui == nil or point.input_ready ~= true then return {}, self.phase end
            return battle(point, ui)
        end
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
            return nil, "UI is not valid in phase " .. self.phase .. ": " .. tostring(ui.kind)
        end
        if point.overworld_ready ~= true then return {}, self.phase end
        target = target or 0   -- the lead (DoPoisonStep walks the whole party; the lead is who meets the foe)
        local hp, st = status(point, target)
        if self.phase == "hunt" or self.phase == "travel" then
            if hp == 0 then return nil, "the target fainted in battle before the poison" end
            if psn(st) then self.phase = "tick" end
        end
        if (self.phase == "tick" or self.phase == "park") and point.poison_fainted == true then self.phase = "park" end
        if self.phase == "park" then
            local buttons, why = walk(hunt, point, {facts.park[1]})
            if why == "arrived" then self.phase = self.terminal return {}, self.phase end
            return buttons, why
        end
        if self.phase == "tick" then
            if not on(point, hunt) then return nil, "left the hunt map while poisoned" end
            if hp == 0 then return {}, self.phase end   -- the faint script is about to run
            local a, b = facts.park[1], facts.park[2]
            local goal = (point.x == a.x and point.y == a.y) and b or a
            local buttons, why = walk(hunt, point, {goal})
            if why == "arrived" then return {}, self.phase end
            return buttons, why
        end
        if self.phase == "travel" then
            if on(point, hunt) then
                local buttons, why = walk(hunt, point, facts.hunt_grass)
                if why ~= "arrived" then return buttons, why end
                self.phase = "hunt"
            else
                for _, leg in ipairs(facts.legs) do
                    local map = maps[leg.map]
                    if on(point, map) then
                        local buttons, why = walk(map, point, leg.exits)
                        if why == "arrived" then return {[leg.side]=true}, self.phase end   -- cross the connection
                        return buttons, why
                    end
                end
                return nil, fmt("map %s:%s is not on the source route", tostring(point.map_group), tostring(point.map_number))
            end
        end
        -- hunt: oscillate between grass tiles (the U1 walk rule)
        if not on(point, hunt) then return nil, "left the hunt map" end
        if here and (here.x ~= point.x or here.y ~= point.y) then from = here end
        here = {x=point.x, y=point.y}
        local button, why = F.walk_direction(hunt, point, from)
        if not button then return nil, why end
        return {[button]=true}, self.phase
    end
    return self
end

-- opts.fainted() true once the probe saw the poison_faint hit; opts.max_frames bounds the leg.
function PI.new(ctx, SG, F, FI, opts)
    local facts = assert(ctx.u1.poison, "SLINK_GEN2_U1_FACTS lacks poison")
    local driver = PI.driver(F, facts, {moves=FI.PASSIVE_MOVES})
    local base = SG.qualify_observer(ctx)
    local sting = facts.moves.POISON_STING
    local function observe()
        local point = base()
        point.poison_fainted = opts.fainted() == true
        local battle = ctx.reads.read_battle()
        point.active_slot = battle and battle.mode ~= 0 and battle.active_slot or nil
        if battle and battle.mode ~= 0 then
            local foe = ctx.reads.read_battle_mon("enemy")
            point.foe_sting = false
            for _, move in ipairs(foe and foe.moves or {}) do if move == sting then point.foe_sting = true end end
            local mine = ctx.reads.read_battle_mon("player")
            point.target_psn = mine ~= nil and (mine.status // facts.psn_mask) % 2 == 1
        end
        point.party = {}
        local party = ctx.reads.read_party()
        for _, m in ipairs(party and party.mons or {}) do point.party[m.slot] = {hp=m.hp, status=m.status} end
        if point.ui and point.ui.kind == "move_menu" then
            local list = FI.move_list(SG.screen(ctx))
            if list then point.ui.items, point.ui.cursor, point.ui.columns = list.items, list.cursor, list.columns
            else point.input_ready = false end
        end
        return point
    end
    local spec = {name="u1e-poison", terminal=driver.terminal, terminal_idle=true,
                  max_frames=opts.max_frames, max_phase_frames=opts.max_phase_frames,
                  settle_frames=F.BUDGET.settle_frames}
    return driver, observe, spec
end

return PI
