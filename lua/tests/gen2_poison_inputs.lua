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
             turn, or a switch to a party mate above LOW_HP (see PI.driver), until a party mon carries PSN, then
             RUN. A party mon fainting in battle is a failure.
    tick     the target is poisoned in the party: oscillate between the two floor park tiles (no grass, no
             encounter) until opts.fainted() -- the probe's poison_faint hit; every 4 steps DoPoisonStep takes
             1 HP (C engine/overworld/events.asm:905-912). The "fainted!" text box takes A.
    park     walk onto the nearest hunt grass tile (the faint leg starts in the grass) -> "poisoned" (terminal);
             a wild battle on the way also hands over.
  facts (SLINK_GEN2_U1_FACTS.poison, tests/live/test_gen2_frame_align.poison_facts):
    maps {name -> _map_facts}, legs {{map, side, exits={{x,y}}}}, hunt_map, park {{x,y},{x,y}},
    moves {POISON_STING=id}, psn_mask (1 << PSN, constants/battle_constants.asm).
--]]
local PI = {}
-- the one shared step rule (ledges from the separate map.ledges field), from beside this file
local Walk = dofile((debug.getinfo(1, "S").source:match("^@(.-)[^/\\]*$") or "lua/tests/") .. "gen2_walk.lua")
PI.DIRECTIONS = Walk.DIRECTIONS
PI.GRASS_COST = 4   -- ponytail: a weight, not a proof; the hunt only needs FEWER Route 29 encounters
PI.HOLD = 12

local fmt = string.format
local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

-- Pure: first step of a cheapest path (floor 1, grass GRASS_COST) to any goal tile; "arrived" on a goal.
-- Warps are walls (never entered by accident); the first step must be live-steppable. Steps follow the shared
-- rule (lua/tests/gen2_walk.lua): with map.ledges a HOP_* tile is land and hops from it in its direction.
-- Gold run 4: the Route 30 aisle north runs (5,24) -> the ledge (4,24) -> (4,23) beside Youngster Mikey; the
-- conservative grid (ledges as walls) and the observer's step permissions (HOP_* not passable) both missed it.
function PI.step_toward(map, point, goals, avoid)
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
    for _, warp in ipairs(map.warps or {}) do
        if not goal[key(warp.x, warp.y)] then blocked[key(warp.x, warp.y)] = true end   -- a door only as the goal
    end
    for _, tile in ipairs(avoid or {}) do blocked[key(tile.x, tile.y)] = true end   -- e.g. a trainer's sight line
    local step = Walk.stepper(map, point.can_step)
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
                    local start = node[1] == point.x and node[2] == point.y
                    local x, y, tile = step(node[1], node[2], d, start)
                    if x then
                        local n = key(x, y)
                        if not blocked[n] then
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
    local steps, objects = {}, {}
    for _, d in ipairs(PI.DIRECTIONS) do steps[#steps + 1] = d[1] .. "=" .. tostring(point.can_step[d[1]]) end
    for _, b in ipairs(point.blocked or {}) do objects[#objects + 1] = b.x .. "," .. b.y end
    return nil, fmt("no source path from %d,%d on %s (can_step %s; objects %s)", point.x, point.y,
                    tostring(map.map_const), table.concat(steps, " "), table.concat(objects, " "))
end
-- A path blocked only by a live object or a closed first step waits for it (walking NPCs move on).
PI.WAIT_FRAMES = 600
PI.STUCK_FRAMES = 900   -- diagnostics only
PI.GIVE_UP_FRAMES = 3000
PI.HEAL_FRACTION = 0.6
PI.MAX_HEALS = 3
PI.BUMP_FRAMES = 24   -- ponytail: 3 normal steps (8 frames each); a walk that has not moved in that long is bumping

local function on(point, map) return point.map_group == map.map_group and point.map_number == map.map_number end

-- Pure point -> buttons, phase. point adds: poison_fainted, active_slot, active_hp (the battle copy), party
-- ({slot -> {hp, status}}), foe_sting (the wild foe knows POISON_STING), active_psn (the battle mon carries
-- PSN), party_cursor (battle party list entry under the cursor).
-- Against a POISON_STING foe the active mon passes turns with a passive move; a mon at or below LOW_HP, or one
-- that knows no passive move, is switched out for a living party mate above LOW_HP instead (TryPlayerSwitch
-- passes the turn and the incoming mon takes the hit, the U1d FI trick); with nobody above LOW_HP it RUNs.
-- ANY party mon carrying PSN ends the hunt (DoPoisonStep ticks every poisoned party mon). Silver live run 1:
-- flee failures and stings wore the lead down until a sting fainted it in battle.
PI.LOW_HP = 7
PI.PKMN_CELL = 2   -- BattleMenu 2x2 grid FIGHT|PKMN / PACK|RUN (engine/battle/menu.asm:32-45): by position
function PI.driver(F, facts, opts)
    local self = {terminal="poisoned", phase="travel", battles=0}
    local held, hold_left, release = nil, 0, false
    local here, from = nil, nil
    local maps, hunt = facts.maps, facts.maps[facts.hunt_map]
    local passive, no_passive, fought, healed, talked, heals = opts.moves, {}, false, false, false, 0
    local function press(button)
        release, held, hold_left = true, button, PI.HOLD - 1
        return {[button]=true}, self.phase
    end
    -- wanted: a label, or a 1-based cell index (the PKMN glyph cell).
    local function choose(ui, wanted, columns)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local index = type(wanted) == "number" and wanted or nil
        for i, label in ipairs(index == nil and ui.items or {}) do
            if type(label) == "string" and label:upper() == wanted then
                if index then return nil, "ambiguous menu label " .. wanted end
                index = i
            end
        end
        if not integer(index, 1, #ui.items) then return nil, "required native menu item missing: " .. tostring(wanted) end
        if index == ui.cursor then return press("A") end
        local tx, cx = (index - 1) % columns, (ui.cursor - 1) % columns
        if tx ~= cx then return press(tx > cx and "Right" or "Left") end
        return press(index > ui.cursor and "Down" or "Up")
    end
    local waited, bumped, bumped_at = 0, 0, nil
    local function walk(map, point, goals, avoid)
        local button, why = PI.step_toward(map, point, goals, avoid)
        if not button then
            -- a stale object struct can close the only aisle (Route 29 (11,7), Crystal run 1 / Gold errand a1):
            -- plan without objects; a real NPC only bumps the step
            button = PI.step_toward(map, {x=point.x, y=point.y, can_step=point.can_step}, goals, avoid)
        end
        if not button then
            -- the source grid alone has a path: a live step permission is in the way; wait it out
            local open = {x=point.x, y=point.y, can_step={Up=true, Down=true, Left=true, Right=true}}
            if PI.step_toward(map, open, goals, avoid) and waited < PI.WAIT_FRAMES then
                waited = waited + 1
                return {}, self.phase
            end
            return nil, why
        end
        waited = 0
        if button == "arrived" then bumped = 0 return nil, "arrived" end
        -- Holding a direction into a blocker keeps the player bumping in place, and MapEvents runs no
        -- PlayerEvents (trainer sight included) while a step continues (engine/overworld/events.asm
        -- CheckPlayerState, :155-167). Gold run 1 pushed into Mikey (Route 30 (5,23), sight 1) for 60000
        -- frames and he never saw us. A step that has not moved after BUMP_FRAMES is released for
        -- BUMP_FRAMES so the events (and any trainer) run.
        local at = point.x * 1000 + point.y
        if at == bumped_at then bumped = bumped + 1 else bumped_at, bumped = at, 0 end
        if bumped > PI.GIVE_UP_FRAMES then
            return nil, fmt("the walk has not moved for %d frames at %d,%d (%s)", bumped, point.x, point.y, button)
        end
        if bumped % (2 * PI.BUMP_FRAMES) == PI.BUMP_FRAMES then
            -- Gold run 3: Youngster Mikey (Route 30 (5,23), unbeaten, facing down, sight 1) stood on the only
            -- aisle north and never spotted the player at (5,24) (see the STUCK log). An object on the bumped
            -- tile is talked to instead: a trainer's talk path (TalkToTrainer, home/trainers.asm) starts the
            -- same battle.
            for _, d in ipairs(PI.DIRECTIONS) do
                if d[1] == button then
                    for _, object in ipairs(point.blocked or {}) do
                        if object.x == point.x + d[2] and object.y == point.y + d[3] then return press("A") end
                    end
                end
            end
        end
        if bumped % (2 * PI.BUMP_FRAMES) >= PI.BUMP_FRAMES then return {}, self.phase end
        return {[button]=true}, self.phase
    end
    local function psn(value) return integer(value, 0, 255) and (value // facts.psn_mask) % 2 == 1 end
    local function party(point) return type(point.party) == "table" and point.party or {} end
    local function poisoned(point)
        for _, mon in pairs(party(point)) do if psn(mon.status) and integer(mon.hp, 1, 999) then return true end end
        return false
    end
    local function alive(point)
        for _, mon in pairs(party(point)) do if integer(mon.hp, 1, 999) then return true end end
        return false
    end
    -- a living party mate of the active mon above LOW_HP (party HP; the active mon's own is its battle copy)
    local function relief(point)
        for slot = 0, 5 do
            local mon = party(point)[slot]
            if slot ~= point.active_slot and mon and integer(mon.hp, PI.LOW_HP + 1, 999) then return slot end
        end
    end
    local function any_other(point)
        for slot = 0, 5 do
            local mon = party(point)[slot]
            if slot ~= point.active_slot and mon and integer(mon.hp, 1, 999) then return slot end
        end
    end
    local function is_passive(label)
        for _, name in ipairs(passive) do if label:upper() == name then return true end end
        return false
    end
    -- A TRAINER battle (wBattleMode 2: Gold's Route 30 Mikey on the only aisle north, Don, then Route 31 Wade)
    -- has no RUN (BattleMenu_Run refuses, engine/battle/core.asm): a non-POISON_STING foe is fought with the first
    -- damaging move; a POISON_STING foe gets the wild treatment (passive move / switch) until a party mon carries
    -- PSN, then it is fought too. "Will <PLAYER> change #MON?" (data/text/battle.asm:222-231) takes NO.
    local function battle(point, ui)
        local trainer = point.battle_mode == 2
        local sting = (self.phase == "hunt" or trainer) and point.foe_sting == true and point.active_psn ~= true
            and not poisoned(point)
        local active = point.active_slot
        local fit = integer(point.active_hp, PI.LOW_HP + 1, 999) and not no_passive[active]
        if ui.kind == "battle_menu" then
            if point.battle_mode ~= 1 and not trainer then return nil, "battle menu outside a wild or trainer battle" end
            if sting and fit then return choose(ui, "FIGHT", 2) end
            if sting and relief(point) ~= nil then return choose(ui, PI.PKMN_CELL, 2) end
            -- a trainer fight keeps every party mon standing: a worn active mon hands over to a fitter mate
            if trainer and not sting and not integer(point.active_hp, PI.LOW_HP + 1, 999) and relief(point) ~= nil then
                return choose(ui, PI.PKMN_CELL, 2)
            end
            return choose(ui, trainer and "FIGHT" or "RUN", 2)
        end
        if ui.kind == "move_menu" then
            if type(ui.items) ~= "table" then return nil, "move list unreadable" end
            if sting and fit then
                for _, name in ipairs(passive) do
                    for _, label in ipairs(ui.items) do
                        if type(label) == "string" and label:upper() == name then return choose(ui, name, 1) end
                    end
                end
                no_passive[active] = true   -- this mon passes turns by switching out instead
                return press("B")
            end
            if not trainer then return press("B") end
            for _, label in ipairs(ui.items) do
                if type(label) == "string" and not is_passive(label) then return choose(ui, label:upper(), 1) end
            end
            return nil, "the active mon knows no damaging move"
        end
        if ui.kind == "yes_no" and ui.prompt == "switch" then return choose(ui, "NO", 1) end
        if ui.kind == "battle_party" then
            local want = relief(point) or (trainer and any_other(point) or nil)
            if want == nil or not integer(point.party_cursor, 0, 5) then return press("B") end
            if point.party_cursor == want then return press("A") end
            return press(point.party_cursor < want and "Down" or "Up")
        end
        if ui.kind == "battle_mon_menu" then return choose(ui, "SWITCH", 1) end
        if ui.kind == "yes_no" and ui.prompt == "next_mon" then return nil, "a party mon fainted in battle before the poison" end
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
            if self.phase == "hunt" and point.battle_mode == 2 then fought = true end
            if self.phase == "tick" then return nil, "a battle started on the park tiles" end
            if self.phase == "park" then self.phase = self.terminal return {}, self.phase end   -- the faint leg's battle
            if ui == nil or point.input_ready ~= true then return {}, self.phase end
            return battle(point, ui)
        end
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
            -- Mom's SPECIALCALL_WORRIED on entering Route 31 (pokegold maps/Route31.asm:14-22) runs
            -- MomPhoneLectureScript's "Should I save it?" yesorno (engine/phone/scripts/mom.asm:143-150): NO.
            if ui.kind == "yes_no" and ui.prompt == "mom_save" then return choose(ui, "NO", 1) end
            if ui.kind == "yes_no" and ui.prompt == "nurse_heal" then return choose(ui, "YES", 1) end
            return nil, "UI is not valid in phase " .. self.phase .. ": " .. tostring(ui.kind)
        end
        if point.overworld_ready ~= true then return {}, self.phase end
        if self.phase == "hunt" or self.phase == "travel" then
            for _, mon in pairs(party(point)) do
                if mon.hp == 0 then return nil, "a party mon fainted in battle before the poison" end
            end
            if poisoned(point) then self.phase = "tick" end
            -- main's ruling: the trainer is fought once per save; no poison from him is a stop, not a retry
            if self.phase == "hunt" and fought then return nil, "the trainer battle ended without a poisoned party mon" end
        end
        if (self.phase == "tick" or self.phase == "park") and point.poison_fainted == true then self.phase = "park" end
        if self.phase == "park" then
            -- Hand the faint leg a grass tile, not a floor tile beside one: at the park tile the U1 grass walk
            -- has a single grass neighbour and refused it on a stale permission read (Crystal live runs 2-3).
            local buttons, why = walk(hunt, point, facts.hunt_grass)
            if why ~= "arrived" then return buttons, why end
            self.phase = self.terminal
            return {}, self.phase
        end
        if self.phase == "tick" then
            if not on(point, hunt) then return nil, "left the hunt map while poisoned" end
            if not alive(point) then return nil, "the whole party is down" end
            if not poisoned(point) then return {}, self.phase end   -- the faint script is about to run
            local a, b = facts.park[1], facts.park[2]
            local goal = (point.x == a.x and point.y == a.y) and b or a
            local buttons, why = walk(hunt, point, {goal})
            if why == "arrived" then return {}, self.phase end
            return buttons, why
        end
        if self.phase == "travel" and facts.heal then
            -- Gold run 5: Mikey, Don and Wade's Caterpies wore the party down until the catch fainted in
            -- Wade's battle. Heal first at the Cherrygrove #MON CENTER (PokecenterNurseScript, engine/events/
            -- std_scripts.asm:54-114: A at the nurse across the counter, YES to "Shall we heal your #MON?").
            local h = facts.heal
            local center, city = maps[h.center], maps[h.city]
            -- Gold U1f run 1: Mikey and a spinning Don (Route 30) wore the party to 7 and 1 HP after the
            -- first heal, and Wade's Caterpies then wiped it. Beaten trainers never battle again, so a party
            -- mon below HEAL_FRACTION on the way north goes back to Cherrygrove (Route 30's south connection)
            -- for another heal, at most MAX_HEALS times.
            if healed and heals < PI.MAX_HEALS and not on(point, center) and not on(point, city) then
                for _, mon in pairs(party(point)) do
                    if integer(mon.hp, 1, 999) and integer(mon.max_hp, 1, 999) and mon.hp < mon.max_hp * PI.HEAL_FRACTION then
                        healed, talked = false, false
                    end
                end
            end
            if not healed and h.back then
                for _, leg in ipairs(h.back) do
                    local map = maps[leg.map]
                    if map and on(point, map) then
                        local buttons, why = walk(map, point, leg.exits)
                        if why == "arrived" then return {[leg.side]=true}, self.phase end
                        return buttons, why
                    end
                end
            end
            if on(point, center) then
                local full = true
                for _, mon in pairs(party(point)) do if mon.hp ~= mon.max_hp then full = false end end
                healed = healed or (talked and full)
                if healed then
                    local exit = h.exit
                    if point.x == exit.x and point.y == exit.y then return press(exit.carpet or "Down") end
                    local buttons, why = walk(center, point, {exit})
                    if why == "arrived" then return press(exit.carpet or "Down") end
                    return buttons, why
                end
                if point.x ~= h.stand.x or point.y ~= h.stand.y then
                    local buttons, why = walk(center, point, {h.stand})
                    if why == "arrived" then return {}, self.phase end
                    return buttons, why
                end
                if point.facing ~= "Up" then return press("Up") end
                if not talked then heals = heals + 1 end
                talked = true
                return press("A")
            end
            if not healed and on(point, city) then
                local buttons, why = walk(city, point, {h.door})
                if why == "arrived" then return {}, self.phase end
                return buttons, why
            end
        end
        if self.phase == "travel" then
            if on(point, hunt) and facts.trainer then
                self.phase = "hunt"
            elseif on(point, hunt) then
                local buttons, why = walk(hunt, point, facts.hunt_grass)
                if why ~= "arrived" then return buttons, why end
                self.phase = "hunt"
            else
                for _, leg in ipairs(facts.legs) do
                    local map = maps[leg.map]
                    if on(point, map) then
                        local buttons, why = walk(map, point, leg.exits, leg.avoid)
                        if why == "arrived" then return {[leg.side]=true}, self.phase end   -- cross the connection
                        return buttons, why
                    end
                end
                return nil, fmt("map %s:%s is not on the source route", tostring(point.map_group), tostring(point.map_number))
            end
        end
        if not on(point, hunt) then return nil, "left the hunt map" end
        if facts.trainer then
            -- step into the trainer's sight line and wait: he walks up and the battle starts
            local buttons, why = walk(hunt, point, {facts.trainer.tile}, facts.trainer.avoid)
            if why == "arrived" then return {}, self.phase end
            return buttons, why
        end
        -- hunt: oscillate between grass tiles (the U1 walk rule)
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
    -- Diagnostics only (never an oracle): after STUCK_FRAMES on one tile, log the map-event state and every
    -- map object / object struct once, labels from the title's rgblink .sym (Gold runs 1-2: a blocker at
    -- Route 30 (5,23) with no trainer battle).
    local still, dumped, last, logged_mode, logged_moves = 0, false, nil, nil, false
    local function dump()
        local syms = {}
        local f = io.open(ctx.root .. "/data/gen2/" .. F.SYM[ctx.env.title] .. ".sym", "rb")
        if not f then return end
        for bank, addr, name in f:read("a"):gmatch("(%x%x):(%x%x%x%x) (%S+)") do
            syms[name] = tonumber(addr, 16)
        end
        f:close()
        local function u8(addr) return ctx.api.read_u8(addr, "System Bus") end
        local out = {}
        for _, name in ipairs({"wPlayerStepFlags", "wMapEventStatus", "wEnabledPlayerEvents", "wScriptRunning",
                               "wPlayerMapX", "wPlayerMapY"}) do
            if syms[name] then out[#out + 1] = fmt("%s=%02X", name, u8(syms[name])) end
        end
        ctx.log("  STUCK " .. table.concat(out, " "))
        for i = 0, 15 do   -- MAPOBJECT_LENGTH 16: struct id, sprite, y, x, movement, radius, h1, h2, type, sight, script, flag
            local a = (syms.wMapObjects or 0) + i * 16
            if u8(a + 1) ~= 0 then
                ctx.log(fmt("  STUCK mapobj %d struct=%02X sprite=%02X y=%d x=%d move=%02X type=%02X sight=%d script=%02X%02X flag=%02X%02X",
                    i, u8(a), u8(a + 1), u8(a + 2) - 4, u8(a + 3) - 4, u8(a + 4), u8(a + 8), u8(a + 9),
                    u8(a + 11), u8(a + 10), u8(a + 13), u8(a + 12)))
            end
        end
        local o = ctx.obs.object
        for i = 0, o.count - 1 do
            local a = (syms.wObjectStructs or 0) + i * o.length
            if u8(a) ~= 0 then
                ctx.log(fmt("  STUCK struct %d sprite=%02X mapobj=%d move=%02X dir=%02X facing=%02X x=%d y=%d",
                    i, u8(a), u8(a + 1), u8(a + 3), u8(a + 8), u8(a + 13), u8(a + 16) - 4, u8(a + 17) - 4))
            end
        end
    end
    local function observe()
        local point = base()
        local here = fmt("%s:%s:%s:%s", tostring(point.map_group), tostring(point.map_number), tostring(point.x), tostring(point.y))
        if here == last and point.overworld_ready == true then still = still + 1 else still, last = 0, here end
        if still > PI.STUCK_FRAMES and not dumped and ctx.log then
            dumped = true
            pcall(dump)
        end
        point.poison_fainted = opts.fainted() == true
        local battle = ctx.reads.read_battle()
        point.active_slot = battle and battle.mode ~= 0 and battle.active_slot or nil
        if battle and battle.mode ~= 0 then
            local foe = ctx.reads.read_battle_mon("enemy")
            point.foe_sting = false
            for _, move in ipairs(foe and foe.moves or {}) do if move == sting then point.foe_sting = true end end
            local mine = ctx.reads.read_battle_mon("player")
            point.active_psn = mine ~= nil and (mine.status // facts.psn_mask) % 2 == 1
            point.active_hp = mine and mine.hp
        end
        if point.ui and point.ui.kind == "battle_party" then point.party_cursor = FI.party_cursor(SG.screen(ctx)) end
        point.party = {}
        local party = ctx.reads.read_party()
        for _, m in ipairs(party and party.mons or {}) do
            point.party[m.slot] = {hp=m.hp, status=m.status, max_hp=m.max_hp}
        end
        if point.ui and point.ui.kind == "move_menu" then
            local list = FI.move_list(SG.screen(ctx))
            if list then point.ui.items, point.ui.cursor, point.ui.columns = list.items, list.cursor, list.columns
            else point.input_ready = false end
        end
        -- Diagnostics only: one line per battle start/end and per move choice screen (party HP/status).
        local mode = point.battle_mode
        local moves = point.ui and point.ui.kind == "move_menu" and type(point.ui.items) == "table"
        if ctx.log and (mode ~= logged_mode or (moves and not logged_moves)) then
            local hp = {}
            for slot = 0, 5 do
                local m = point.party[slot]
                if m then hp[#hp + 1] = fmt("%d:%s/%s:%s", slot, tostring(m.hp), tostring(m.max_hp), tostring(m.status)) end
            end
            ctx.log(fmt("  PI %s mode=%s map=%s:%s xy=%s,%s phase=%s active=%s foe_sting=%s party=%s%s",
                moves and "moves" or "battle", tostring(mode), tostring(point.map_group), tostring(point.map_number),
                tostring(point.x), tostring(point.y), tostring(driver.phase), tostring(point.active_slot),
                tostring(point.foe_sting), table.concat(hp, " "),
                moves and (" items=" .. table.concat(point.ui.items, "|")) or ""))
            logged_mode = mode
        end
        logged_moves = moves
        return point
    end
    local spec = {name="u1e-poison", terminal=driver.terminal, terminal_idle=true,
                  max_frames=opts.max_frames, max_phase_frames=opts.max_phase_frames,
                  settle_frames=F.BUDGET.settle_frames}
    return driver, observe, spec
end

return PI
