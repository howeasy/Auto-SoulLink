--[[
  lua/tests/duo/gen2_route29_inputs.lua -- the gen2_new duo's Route 29 route (card gen2-H1).

  Normal buttons only, from a warm <title>_battle(_ot2) arrival on Route 29 grass (C, G and S battle
  fixtures all saved on Route 29, map 24:3, with the O-10 Ball stack; their qualification receipts'
  boot witnesses). The route is the same on all three titles; the per-title parts come from the context
  (SLINK_GEN2_TITLE: route facts, UI origins, prompt anchors, profile) and SLINK_GEN2_U1_FACTS:
    same source   BattlePack pocket order + menus, pack.asm:627-800 identical in pokecrystal 7a7881d and
                  pokegold 656583c; the battle menu is the 2x2 BattleMenuHeader grid (G.BATTLE_MENU_GRID)
    per title     BattleMenu C core.asm:4881 / G/S :4641; PokeBallEffect nickname ask C item_effects.asm:574
                  / G/S :572; the save menu text differs (C DisplaySaveInfoOnSave vs G/S
                  DisplayNormalContinueData, engine/menus/save.asm) but its prompts are the route facts'
  The same F.driver played this route PHYSICAL on every title's battle fixture (U1: crystal 7c08529,
  gold eac806c, silver 92318de, tests/fixtures/gen2/receipts/<title>.engine_sites.json).
    walk    one held direction per frame between grass tiles (a walk step is 8 frames; the
            direction is re-decided every frame, never a 12-frame press)
    battle  BattleMenu PACK -> the Ball pocket -> POKe BALL -> USE, A through battle text, NO to the
            nickname (_AskGiveNicknameText, item_effects.asm:574-581), until the engine capture
    report  (still phase "battle") the overworld is held back until the driver has printed CAUGHT,
            i.e. until the client sent the capture it observed; the save cannot start earlier
    save    START -> SAVE -> YES -> (overwrite text) -> YES, the native _SaveGameData completion
  The point -> buttons driver IS the U1 gate's (lua/tests/gen2_frame_align.lua F.driver, proven live
  PHYSICAL on these fixtures): 12-frame menu HOLD + one release frame, per-frame walk holds. The UI read
  is the shared scripted gate's observer (qualified UI origins, the N17 battle-menu grid); this file only
  adds the Ball-pocket UI kinds and the catch-nickname prompt (SLINK_GEN2_U1_FACTS, produced by
  tests/live/test_gen2_frame_align.u1_facts) and feeds the engine-capture count in as probe_hits.
  The species clause's reroll (scenario_gen2_species_clause.lua) splits one battle between two drivers:
    R.encounter  walk (as above) into a wild battle, A through its intro text, stop at the BattleMenu with
                 driver.foe = wEnemyMonSpecies (raw, read only once the menu is up: LoadEnemyMon has run by
                 then, so no stale foe from the previous battle); the battle stays up for R.new (catch) or
    R.flee       BattleMenu RUN (grid cell 4, engine/battle/menu.asm:32-45), A through "Got away safely!" /
                 "Can't escape!" (BattleMenu_Run C engine/battle/core.asm:5306-5319, retried up to
                 R.MAX_RUNS), terminal once back in the overworld.
--]]
local R = {}
R.MAX_RUNS = 8   -- ponytail: a L2-4 Route 29 foe rarely blocks a RUN; raise if a lane meets "Can't escape!" often
R.PACK_KINDS = {"pack_items", "pack_balls", "pack_key", "pack_tmhm", "item_submenu"}

-- Before SG.hooks(ctx): the pack-UI origins join the watched UI origins, the item submenu reads as a
-- menu and the catch-nickname prompt classifies (the U1 gate's in-memory preparation, same facts).
function R.prepare(ctx, SG, u1)
    for _, kind in ipairs(R.PACK_KINDS) do
        ctx.facts.ui_origins[kind] = assert(u1.pack_ui[kind], "SLINK_GEN2_U1_FACTS lacks " .. kind)
    end
    SG.MENU_KINDS.item_submenu = true
    local prompts = {}
    for _, source in ipairs({ctx.obs.prompts, ctx.prompts, u1.prompts}) do
        for k, v in pairs(source) do prompts[k] = v end
    end
    assert(prompts.catch_nickname, "SLINK_GEN2_U1_FACTS lacks the catch_nickname prompt")
    ctx.prompts = prompts
end

-- opts.captures() -> engine capture events the production client received (capture_party_finalized);
-- opts.reported() -> true once CAUGHT was printed; opts.settled() (optional) -> true once the save may start
-- (h.link_settled: linked and no box op left, so no CartRAM edit lands after the witness, C<->G reconnect
-- RED run 1). Returns driver, observe, host spec.
function R.new(ctx, SG, F, opts)
    local driver = F.driver(ctx.facts.maps.Route29)
    local base = SG.qualify_observer(ctx)
    local function observe()
        local point = base()
        point.probe_hits = {capture_party=opts.captures()}
        if point.ui and point.ui.kind == "pack_balls" then point.ball_cursor = F.ball_cursor(SG.screen(ctx)) end
        -- The report gate: a finished catch stays in phase "battle" (F.driver idles while the overworld
        -- is not ready) until the capture went out on the wire.
        if driver.phase == "battle" and point.overworld_ready and opts.captures() >= 1
            and (not opts.reported() or (opts.settled ~= nil and not opts.settled())) then
            point.overworld_ready = false
        end
        return point
    end
    local budget = F.BUDGET
    local spec = {name="duo-gen2-link", terminal=driver.terminal, terminal_idle=true,
                  max_frames=opts.max_frames or budget.max_frames,
                  max_phase_frames=math.min(opts.max_phase_frames or budget.max_phase_frames,
                                            opts.max_frames or budget.max_frames),
                  settle_frames=budget.settle_frames}
    return driver, observe, spec
end

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end
local TEXT = {text=true, prompt_button=true, wait_button=true}

-- The 12-frame menu HOLD + one release frame (F.driver's press) and its 2-column label choice.
local function presser(self)
    local HOLD, held, hold_left, release = 12, nil, 0, false
    local p = {}
    function p.press(button)
        release, held, hold_left = true, button, HOLD - 1
        return {[button]=true}, self.phase
    end
    function p.busy()
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, self.phase end
        if release then release = false; return {}, self.phase end
    end
    function p.choose(ui, wanted, columns)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local target
        for index, label in ipairs(ui.items) do
            if type(label) == "string" and label:upper() == wanted then
                if target then return nil, "ambiguous menu label" end
                target = index
            end
        end
        if not target then return nil, "required native menu item missing: " .. wanted end
        if target == ui.cursor then
            local buttons, phase = p.press("A")
            return buttons, phase, true   -- the third value: A pressed on the wanted item
        end
        local tx, cx = (target - 1) % columns, (ui.cursor - 1) % columns
        if tx ~= cx then return p.press(tx > cx and "Right" or "Left") end
        return p.press(target > ui.cursor and "Down" or "Up")
    end
    return p
end

-- Pure point -> buttons, phase: walk -> battle -> "encounter" (terminal at the wild BattleMenu, driver.foe).
function R.encounter_driver(F, map)
    local self = {terminal="encounter", phase="walk"}
    local p, here, from = presser(self), nil, nil
    function self.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        local busy, phase = p.busy()
        if busy then return busy, phase end
        if self.phase == self.terminal then return {}, self.phase end
        if integer(point.battle_mode, 1, 255) then
            if point.battle_mode ~= 1 then return nil, "not a wild battle" end
            self.phase = "battle"
        elseif self.phase == "battle" then
            return nil, "the battle ended before its menu"
        end
        local ui = point.ui
        if ui ~= nil then
            if self.phase ~= "battle" then return nil, "UI is not valid while walking: " .. tostring(ui.kind) end
            if point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "battle_menu" then
                if not integer(point.foe, 1, 251) then return nil, "wild battle menu without a foe species" end
                self.phase, self.foe = self.terminal, point.foe
                return {}, self.phase
            end
            if TEXT[ui.kind] then return p.press("A") end
            return nil, "UI is not valid before the battle menu: " .. tostring(ui.kind)
        end
        if self.phase == "battle" or point.overworld_ready ~= true then return {}, self.phase end
        if here and (here.x ~= point.x or here.y ~= point.y) then from = here end
        here = {x=point.x, y=point.y}
        local button, why = F.walk_direction(map, point, from)
        if not button then return nil, why end
        return {[button]=true}, self.phase
    end
    return self
end

-- Pure point -> buttons, phase: battle -> "escaped" (terminal back in the overworld). self.runs = RUNs chosen.
function R.flee_driver()
    local self = {terminal="escaped", phase="battle", runs=0}
    local p = presser(self)
    function self.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        local busy, phase = p.busy()
        if busy then return busy, phase end
        if self.phase == self.terminal then return {}, self.phase end
        local ui = point.ui
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "battle_menu" then
                if point.battle_mode ~= 1 then return nil, "battle menu outside a wild battle" end
                local buttons, phase, hit = p.choose(ui, "RUN", 2)
                if hit then
                    self.runs = self.runs + 1
                    if self.runs > R.MAX_RUNS then return nil, "could not escape in " .. R.MAX_RUNS .. " RUNs" end
                end
                return buttons, phase
            end
            if TEXT[ui.kind] then return p.press("A") end
            return nil, "UI is not valid while fleeing: " .. tostring(ui.kind)
        end
        if point.overworld_ready == true and point.battle_mode == 0 then self.phase = self.terminal end
        return {}, self.phase
    end
    return self
end

local function spec_of(F, name, driver, opts)
    local budget = F.BUDGET
    return {name=name, terminal=driver.terminal, terminal_idle=true, max_frames=opts.max_frames or budget.max_frames,
            max_phase_frames=math.min(opts.max_phase_frames or budget.max_phase_frames, opts.max_frames or budget.max_frames),
            settle_frames=budget.settle_frames}
end

function R.encounter(ctx, SG, F, opts)
    local driver, base = R.encounter_driver(F, ctx.facts.maps.Route29), SG.qualify_observer(ctx)
    local function observe()
        local point = base()
        if point.ui and point.ui.kind == "battle_menu" then point.foe = ctx.sym("wEnemyMonSpecies")[1] end
        return point
    end
    return driver, observe, spec_of(F, "duo-gen2-encounter", driver, opts)
end

function R.flee(ctx, SG, F, opts)
    local driver = R.flee_driver()
    return driver, SG.qualify_observer(ctx), spec_of(F, "duo-gen2-flee", driver, opts)
end

return R
