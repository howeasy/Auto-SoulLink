--[[
  lua/tests/gen2_evolution_inputs.lua -- card EVO-U1: a party mon EVOLVES natively after a wild battle (EvolveAfterBattle,
  C engine/pokemon/evolve.asm:9-320, reached from ExitBattle.HandleEndOfBattle, C engine/battle/core.asm:8272-8291; the
  pack's evolution_species_published site is the `push hl` right after the species-list store, evolve.asm:312-317),
  from real play with normal buttons only. Shape of lua/tests/gen2_poison_inputs.lua: EV.new(ctx, SG, F, PI, FI, opts)
  -> driver, observe, spec for F.play. It runs after the U1f PC leg (party [lead], in the Cherrygrove #MON CENTER).

  Stimulus (pinned decomps only): Caterpie and Weedle evolve at level 7 (data/pokemon/evos_attacks.asm
  CaterpieEvosAttacks :169-174, WeedleEvosAttacks :197-202) and learn nothing between 1 and 7, so no move prompt
  interrupts. Day Route 30 (data/wild/johto_grass.asm ROUTE_30; C :1276-1283, G/S :1612-1619 / :1637-1644) holds
  Caterpie L3/L4 in Crystal (slots 2+3 = 50%) and Gold (L3 slot 2 = 30%, L4 slot 5 = 5%), and Weedle L3/L4 in Silver
  (slots 2+5 = 35%). Both species are GROWTH_MEDIUM_FAST (exp = L^3: 27 at L3, 343 at L7) and catch rate 255.
  Exp (GiveExperiencePoints, C core.asm): floor(floor(base_exp / participants) * foe_level / 7). The lead
  (the starter) is sent out first and so always participates: two participants. Route 30 day foes give the target
  11-21 exp each (Pidgey 55, Caterpie 53, Weedle 52, Hoppip 74 base exp; data/pokemon/base_stats/*.asm), so about
  25 wins take a L3 catch to L7.
  Only B cancels the evolution (EvolutionAnimation .WaitFrames_CheckPressedB, engine/movie/evolution_animation.asm):
  this driver presses B only inside battle menus, never at a text box.
  Phases:
    to-grass  center exit carpet -> Cherrygrove north edge -> the nearest Route 30 grass tile
    hunt      oscillate in the grass (F.walk_direction)
    battle    before the catch: a foe of another species -> RUN; the target species -> FIGHT (the first damaging
              move) while it is at full HP, then PACK -> POKe BALL -> USE, NO to the nickname.
              after the catch: the lead switches the target in (PKMN -> SWITCH) so both participate, the target
              switches straight back to the fit lead, and the lead FIGHTs with its first damaging move; a worn active
              mon (<= LOW) hands over to a fit mate, else RUN. A party due at the nurse RUNs from every battle.
              facts.run_from_sting: a POISON_STING foe is run from (a poisoned Caterpie would lose HP on the walk).
              "Use next #MON?" -> YES and a living mate.
    heal      a party mon below HEAL, fainted or with a status -> the Cherrygrove nurse (YES), back to to-grass
    evolved   (terminal) the target's species is the evolved one and the overworld is back
  facts (SLINK_GEN2_U1_FACTS.evolution, tests/live/test_gen2_frame_align.evolution_facts):
    maps {name -> _map_facts}, center, city, hunt, hunt_grass, door {x,y}, exit {x,y,carpet}, stand {x,y},
    north {exits, side} (city -> hunt), south {exits, side} (hunt -> city), target, evolves_to, poison_sting,
    run_from_sting, damaging_ids {tostring(move id) -> true}, approach {map, exits, side} (optional: Route 29 -> city). (the EV.DAMAGING names' constants).
--]]
local EV = {}
EV.HOLD = 12
EV.LOW = 0.4    -- ponytail: a battle mon at or below this HP fraction hands over or runs; tune from live runs
EV.HEAL = 0.6   -- out of battle, below this fraction (or fainted / any status) goes to the nurse
EV.MIN_PP = 6   -- out of battle, fewer PP than this left on a mon's damaging moves goes to the nurse too
EV.WAIT_FRAMES = 600
EV.MAX_UP_PRESSES = 3
EV.PKMN_CELL = 2   -- BattleMenu 2x2 grid FIGHT|PKMN / PACK|RUN (engine/battle/menu.asm:32-45): by position
-- Damaging moves the lead (Totodile: SCRATCH, RAGE at 7) and a Caterpie/Weedle know (evos_attacks.asm).
EV.DAMAGING = {TACKLE=true, SCRATCH=true, ["POISON STING"]=true, RAGE=true, ["WATER GUN"]=true}

local fmt = string.format
local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end
local function on(point, map) return point.map_group == map.map_group and point.map_number == map.map_number end
local function fit(hp, max_hp, fraction)
    return integer(hp, 1, 999) and integer(max_hp, 1, 999) and hp > max_hp * fraction
end

-- Pure: PP left on the damaging moves (facts.damaging_ids: move id -> true) of a moves/pp pair.
function EV.attack_pp(moves, pp, facts)
    local total = 0
    for i, move in ipairs(type(moves) == "table" and moves or {}) do
        if facts.damaging_ids[tostring(move)] and type(pp) == "table" and integer(pp[i], 0, 63) then total = total + pp[i] end
    end
    return total
end

-- Pure: the party slot holding the target (or its evolution), or nil.
function EV.target_slot(point, facts)
    for slot = 0, 5 do
        local mon = type(point.party) == "table" and point.party[slot]
        if mon and (mon.species == facts.target or mon.species == facts.evolves_to) then return slot end
    end
end

-- Pure point -> buttons, phase. point adds: party ({slot -> {hp, max_hp, status, species, level}}), active_slot,
-- active_hp/active_max (the battle copy), foe_species, foe_full, foe_sting, party_cursor, ball_cursor.
function EV.driver(F, PI, facts)
    local self = {terminal="evolved", phase="to-grass", battles=0}
    local held, hold_left, release, waited, ups = nil, 0, false, 0, 0
    local here, from, healing, talked, sent, want, was_battle = nil, nil, false, false, false, nil, false
    local maps = facts.maps
    local center, city, hunt = maps[facts.center], maps[facts.city], maps[facts.hunt]
    local function press(button)
        release, held, hold_left = true, button, EV.HOLD - 1
        return {[button]=true}, self.phase
    end
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
    local function walk(map, point, goals)
        local button, why = PI.step_toward(map, point, goals)
        if not button then button = PI.step_toward(map, {x=point.x, y=point.y, can_step=point.can_step}, goals) end
        if not button then
            local open = {x=point.x, y=point.y, can_step={Up=true, Down=true, Left=true, Right=true}}
            if PI.step_toward(map, open, goals) and waited < EV.WAIT_FRAMES then
                waited = waited + 1
                return {}, self.phase
            end
            return nil, why
        end
        waited = 0
        if button == "arrived" then return nil, "arrived" end
        return {[button]=true}, self.phase
    end
    local function party(point) return type(point.party) == "table" and point.party or {} end
    local function worn(point)
        for _, mon in pairs(party(point)) do
            if mon.hp == 0 or (mon.status or 0) ~= 0 or not fit(mon.hp, mon.max_hp, EV.HEAL)
               or (mon.attack_pp ~= nil and mon.attack_pp < EV.MIN_PP) then return true end
        end
        return false
    end
    -- a living party mate of the active mon above LOW (the target first while it has not been sent out)
    local function mate(point, target)
        if target and target ~= point.active_slot and not sent then
            local mon = party(point)[target]
            if mon and fit(mon.hp, mon.max_hp, EV.LOW) then return target end
        end
        for slot = 0, 5 do
            local mon = party(point)[slot]
            if slot ~= point.active_slot and mon and fit(mon.hp, mon.max_hp, EV.LOW) then return slot end
        end
    end
    local function battle(point, ui)
        local target = EV.target_slot(point, facts)
        if target ~= nil and point.active_slot == target then sent = true end
        if ui.kind == "battle_menu" then
            if point.battle_mode ~= 1 then return nil, "battle menu outside a wild battle" end
            local active_fit = fit(point.active_hp, point.active_max, EV.LOW) and point.active_can_hit ~= false
            if target == nil then
                if point.foe_species ~= facts.target then return choose(ui, "RUN", 2) end
                if point.foe_full == true and active_fit then return choose(ui, "FIGHT", 2) end
                return choose(ui, "PACK", 2)
            end
            -- a sting foe, or a party already due at the nurse (the walk crosses grass): no fight
            if (facts.run_from_sting and point.foe_sting == true) or healing then return choose(ui, "RUN", 2) end
            -- The target only has to be SENT OUT to share the exp; the lead does the fighting (dev run 1: a target
            -- that fought on took a heal trip after nearly every battle).
            if point.active_slot == target or not sent then
                want = mate(point, target)   -- the target while not yet sent, else a fit lead
                if want ~= nil then return choose(ui, EV.PKMN_CELL, 2) end
            end
            if active_fit then return choose(ui, "FIGHT", 2) end
            want = mate(point, target)
            if want ~= nil then return choose(ui, EV.PKMN_CELL, 2) end
            return choose(ui, "RUN", 2)
        end
        if ui.kind == "move_menu" then
            if type(ui.items) ~= "table" then return nil, "move list unreadable" end
            -- the list is the battle mon's move order (ListMoves), so active_pp[i] is row i's PP
            for i, label in ipairs(ui.items) do
                if type(label) == "string" and EV.DAMAGING[label:upper()]
                   and (type(point.active_pp) ~= "table" or integer(point.active_pp[i], 1, 63)) then
                    return choose(ui, label:upper(), 1)
                end
            end
            return press("B")   -- no damaging PP: the battle menu hands over or runs (active_can_hit false)
        end
        if ui.kind == "battle_party" then
            if want == nil or not integer(point.party_cursor, 0, 5) then return press("B") end
            if point.party_cursor == want then return press("A") end
            return press(point.party_cursor < want and "Down" or "Up")
        end
        if ui.kind == "battle_mon_menu" then return choose(ui, "SWITCH", 1) end
        if ui.kind == "yes_no" and ui.prompt == "catch_nickname" then return choose(ui, "NO", 1) end
        if ui.kind == "yes_no" and ui.prompt == "next_mon" then
            want = nil
            for slot = 0, 5 do
                local mon = party(point)[slot]
                if want == nil and slot ~= point.active_slot and mon and integer(mon.hp, 1, 999) then want = slot end
            end
            if want == nil then return nil, "the whole party is down" end
            return choose(ui, "YES", 1)
        end
        if F.TOWARD_BALLS[ui.kind] then
            if target ~= nil then return press("B") end
            return press(F.TOWARD_BALLS[ui.kind])
        end
        if ui.kind == "pack_balls" then
            if target ~= nil then return press("B") end
            if point.ball_cursor == "ball" then ups = 0 return press("A") end
            if point.ball_cursor == "cancel" then
                ups = ups + 1
                if ups > EV.MAX_UP_PRESSES then return nil, "no Poke Ball left in the pocket" end
                return press("Up")
            end
            return {}, self.phase
        end
        if ui.kind == "item_submenu" then return choose(ui, "USE", 1) end
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
            if not was_battle then self.battles, sent, want, was_battle = self.battles + 1, false, nil, true end
            self.phase = "battle"
            -- EvolveAfterBattle runs inside ExitBattle, before CleanUpBattleRAM clears wBattleMode: the animation
            -- has no UI origin, so nothing is pressed until its texts.
            if ui == nil or point.input_ready ~= true then return {}, self.phase end
            return battle(point, ui)
        end
        was_battle = false
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
            if ui.kind == "yes_no" and ui.prompt == "nurse_heal" then return choose(ui, "YES", 1) end
            return nil, "UI is not valid in phase " .. self.phase .. ": " .. tostring(ui.kind)
        end
        if point.overworld_ready ~= true then return {}, self.phase end
        local target = EV.target_slot(point, facts)
        if target ~= nil and party(point)[target].species == facts.evolves_to then
            self.phase = self.terminal
            return {}, self.phase
        end
        if not healing and worn(point) then healing, talked = true, false end
        -- facts.approach (Route 29 -> Cherrygrove): the leg also starts from the battle fixtures' own map
        local approach = facts.approach and maps[facts.approach.map]
        if approach and on(point, approach) then
            local buttons, why = walk(approach, point, facts.approach.exits)
            if why == "arrived" then return {[facts.approach.side]=true}, self.phase end
            return buttons, why
        end
        if healing then
            self.phase = "heal"
            if on(point, center) then
                if talked and not worn(point) then
                    healing = false
                else
                    if point.x ~= facts.stand.x or point.y ~= facts.stand.y then
                        local buttons, why = walk(center, point, {facts.stand})
                        if why == "arrived" then return {}, self.phase end
                        return buttons, why
                    end
                    if point.facing ~= "Up" then return press("Up") end
                    talked = true
                    return press("A")
                end
            elseif on(point, city) then
                local buttons, why = walk(city, point, {facts.door})
                if why == "arrived" then return {}, self.phase end   -- the door warp fires on arrival
                return buttons, why
            elseif on(point, hunt) then
                local buttons, why = walk(hunt, point, facts.south.exits)
                if why == "arrived" then return {[facts.south.side]=true}, self.phase end
                return buttons, why
            else
                return nil, fmt("map %s:%s is not on the heal route", tostring(point.map_group), tostring(point.map_number))
            end
        end
        if on(point, center) then
            self.phase = "to-grass"
            local exit = facts.exit
            if point.x == exit.x and point.y == exit.y then return press(exit.carpet or "Down") end
            local buttons, why = walk(center, point, {exit})
            if why == "arrived" then return press(exit.carpet or "Down") end
            return buttons, why
        end
        if on(point, city) then
            self.phase = "to-grass"
            local buttons, why = walk(city, point, facts.north.exits)
            if why == "arrived" then return {[facts.north.side]=true}, self.phase end
            return buttons, why
        end
        if not on(point, hunt) then
            return nil, fmt("map %s:%s is not on the evolution route", tostring(point.map_group), tostring(point.map_number))
        end
        if hunt.grid[point.y * hunt.width + point.x + 1] ~= 2 then
            self.phase = "to-grass"
            local buttons, why = walk(hunt, point, facts.hunt_grass)
            if why ~= "arrived" then return buttons, why end
        end
        self.phase = "hunt"
        if here and (here.x ~= point.x or here.y ~= point.y) then from = here end
        here = {x=point.x, y=point.y}
        local button, why = F.walk_direction(hunt, point, from)
        if not button then return nil, why end
        return {[button]=true}, self.phase
    end
    return self
end

-- opts.observe: the gate's base observer (battle-menu grid, ball cursor); opts.max_frames bounds the leg.
function EV.new(ctx, SG, F, PI, FI, opts)
    local facts = assert(ctx.u1.evolution, "SLINK_GEN2_U1_FACTS lacks evolution")
    local driver = EV.driver(F, PI, facts)
    local logged_mode
    local function observe()
        local point = opts.observe()
        local battle = ctx.reads.read_battle()
        point.active_slot = battle and battle.mode ~= 0 and battle.active_slot or nil
        if battle and battle.mode ~= 0 then
            local foe = ctx.reads.read_battle_mon("enemy")
            point.foe_species = foe and foe.species_id
            point.foe_full = foe ~= nil and foe.hp == foe.max_hp
            point.foe_sting = false
            for _, move in ipairs(foe and foe.moves or {}) do if move == facts.poison_sting then point.foe_sting = true end end
            local mine = ctx.reads.read_battle_mon("player")
            point.active_hp, point.active_max = mine and mine.hp, mine and mine.max_hp
            point.active_pp, point.active_can_hit = mine and mine.pp, EV.attack_pp(mine and mine.moves, mine and mine.pp, facts) > 0
        end
        if point.ui and point.ui.kind == "battle_party" then point.party_cursor = FI.party_cursor(SG.screen(ctx)) end
        point.party = {}
        local party = ctx.reads.read_party()
        for _, m in ipairs(party and party.mons or {}) do
            point.party[m.slot] = {hp=m.hp, max_hp=m.max_hp, status=m.status, species=m.species_id, level=m.level,
                                   attack_pp=EV.attack_pp(m.moves, m.pp, facts)}
        end
        -- Diagnostics only: one line per battle start/end (party species/level/HP).
        local mode = point.battle_mode
        if ctx.log and mode ~= logged_mode then
            local rows = {}
            for slot = 0, 5 do
                local m = point.party[slot]
                if m then rows[#rows + 1] = fmt("%d:%s/L%s/%s/%s", slot, tostring(m.species), tostring(m.level),
                                                 tostring(m.hp), tostring(m.max_hp)) end
            end
            -- hHours (FixTime's in-game hour, HRAM): the Route 30 day table needs 10:00-17:59 (data/wild/johto_grass.asm)
            local hour = ctx.profile.hram.hHours and ctx.api.read_u8(ctx.profile.hram.hHours, "System Bus")
            ctx.log(fmt("  EV battle=%s #%d hour=%s map=%s:%s xy=%s,%s phase=%s foe=%s party=%s", tostring(mode),
                driver.battles, tostring(hour), tostring(point.map_group), tostring(point.map_number), tostring(point.x),
                tostring(point.y), tostring(driver.phase), tostring(point.foe_species), table.concat(rows, " ")))
            logged_mode = mode
        end
        return point
    end
    local spec = {name="u1-evolution", terminal=driver.terminal, terminal_idle=true,
                  max_frames=opts.max_frames, max_phase_frames=opts.max_phase_frames,
                  settle_frames=F.BUDGET.settle_frames, max_phase_changes=4000}
    return driver, observe, spec
end

return EV
