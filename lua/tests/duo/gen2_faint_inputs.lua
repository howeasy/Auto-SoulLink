--[[
  lua/tests/duo/gen2_faint_inputs.lua -- make ONE party mon faint in a Route 29 wild battle, normal buttons only
  (card gen2-H1c; shared with the U1d battle_faint proof, lua/tests/gen2_frame_align.lua).

  Shape of gen2_route29_inputs.lua: FI.prepare(ctx, SG, u1) before SG.hooks, FI.new(ctx, SG, F, opts) ->
  driver, observe, spec for F.play. Title-neutral: every per-title site comes from SLINK_GEN2_U1_FACTS.
    opts.target     party slot (0-based) that must faint; nil = whatever leads (U1d's lead faint)
    opts.fainted()  true once the engine faint was observed (the duo: the production binder's battle_faint
                    event for the target key; U1d: its battle_faint hit)
    opts.moves      move names to prefer in the FIGHT list (default FI.PASSIVE_MOVES), else the first move
    opts.max_battles  wild battles tried before giving up (default 3; the target may win a battle instead)
  It never saves: callers run F.driver with phase "save" afterwards (duo_gen2_main.lua h.save).

  Input plan = docs/gen2/reviews/OMP_O15_FAINT_FACTS_2026-09-23.md (15ed52e1), pinned decomps only.
  Phases walk -> battle -> ... -> "fainted" (terminal: back in the overworld, fainted() true).
    walk    F.walk_direction between Route 29 grass tiles until wBattleMode != 0
    battle  target not active: BattleMenu PKMN BY POSITION (grid cell 2; the label is the <PKMN> glyph,
            engine/battle/menu.asm:44) -> the party list -> the target -> SWITCH (BattleMenu_PKMN ->
            BattleMonMenu -> TryPlayerSwitch, C engine/battle/core.asm:5060-5117, 5156-5229)
            target active and alive: FIGHT -> GROWL/TAIL WHIP/LEER by label (MoveSelectionScreen, C core.asm:
            5332-5432): never damage the foe, never RUN before the faint (RUN can end the battle, :3680-3790).
            Every foe hit deals >= MIN_DAMAGE 2 (effect_commands.asm:3093-3098), so a 14-HP catch faints in
            <= 7 hits; Growl has 38 PP
            after the faint: "Use next #MON?" -> YES, the default (AskUseNextPokemon, core.asm:2695-2722,
            data/text/battle.asm:214-216) -> ForcePlayerMonChoice (:2723, only fit mons selectable) -> the
            first living other mon -> RUN, retried through "Can't escape!" (BattleMenu_Run, :5306-5319;
            G/S Route 29 reaches L4, a L4 Rattata may outspeed the L5 Totodile)
            bail: a Splash-only foe (day/morning Hoppip, data/pokemon/evos_attacks.asm:2521-2531) can never
            faint us: RUN before switching and walk into the next encounter
  Party list geometry (source, not measured): PartyMenu2DMenuData cursor start y=1 x=0, cursor offset
  `dn 2, 0` (two rows per mon), nicknames at hlcoord 3,1 stepping 2*SCREEN_WIDTH (C engine/pokemon/
  party_menu.asm:81-103, 661-667): the ▶ sits in screen column 0, row 1 + 2*i for list entry i.
  FACTS (SLINK_GEN2_U1_FACTS, tests/live/test_gen2_frame_align.u1_facts, owned by U1d):
    faint_ui = {move_menu = MoveSelectionScreen.interpret_joypad, battle_party = PartyMenuSelect,
                battle_mon_menu = BattleMonMenu -> code site}, prompts.next_mon = ["Use next"].
--]]
local FI = {}
FI.UI_KINDS = {"move_menu", "battle_party", "battle_mon_menu"}
FI.MENU_KINDS = {move_menu=true, battle_mon_menu=true}   -- boxed menus: SG.parse_menu reads them
-- Status moves a Route 29 catch knows at L2-4 (O15 F1/F2: Hoothoot GROWL, Rattata TAIL WHIP; Totodile LEER).
FI.PASSIVE_MOVES = {"GROWL", "TAIL WHIP", "SAND-ATTACK", "DEFENSE CURL", "FORESIGHT", "LEER", "SPLASH"}
FI.MAX_BATTLES = 3
FI.PKMN_CELL = 2       -- BattleMenu 2x2 grid FIGHT|PKMN / PACK|RUN (engine/battle/menu.asm:32-45): by position
FI.SPLASH = 150        -- constants/move_constants.asm SPLASH; a foe knowing nothing else cannot hurt us

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

function FI.prepare(ctx, SG, u1)
    for _, kind in ipairs(FI.UI_KINDS) do
        ctx.facts.ui_origins[kind] = assert(u1.faint_ui and u1.faint_ui[kind], "SLINK_GEN2_U1_FACTS lacks faint_ui." .. kind)
    end
    for kind in pairs(FI.MENU_KINDS) do SG.MENU_KINDS[kind] = true end
    assert(u1.prompts and u1.prompts.next_mon, "SLINK_GEN2_U1_FACTS lacks the next_mon prompt")
    ctx.prompts.next_mon = u1.prompts.next_mon
end

-- Pure: the party list entry (0-based) the ▶ points at, from the decoded screen rows; nil if none/ambiguous.
function FI.party_cursor(rows)
    local found
    for y, row in ipairs(rows) do
        if row[1] == "▶" then
            if found or (y - 2) % 2 ~= 0 then return nil end
            found = (y - 2) // 2
        end
    end
    return found
end

-- Pure point -> buttons, phase. point adds: fainted, active_slot, party_hp (0-based slot -> hp), party_cursor.
function FI.driver(F, map, opts)
    local self = {terminal="fainted", phase="walk", battles=0}
    local HOLD, held, hold_left, release = 12, nil, 0, false
    local here, from, target, switched = nil, nil, opts.target, false
    local max_battles = opts.max_battles or FI.MAX_BATTLES
    local passive = opts.moves or FI.PASSIVE_MOVES
    local function press(button)
        release, held, hold_left = true, button, HOLD - 1
        return {[button]=true}, self.phase
    end
    -- wanted: a label, or a 1-based cell index (the PKMN glyph cell).
    local function choose(ui, wanted, columns)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local index = type(wanted) == "number" and wanted or nil
        for i, label in ipairs(index == nil and ui.items or {}) do
            if type(label) == "string" and label:upper() == wanted then index = index and -1 or i end
        end
        if index == -1 then return nil, "ambiguous menu label " .. wanted end
        if not integer(index, 1, #ui.items) then return nil, "required native menu item missing: " .. tostring(wanted) end
        if index == ui.cursor then return press("A") end
        local tx, cx = (index - 1) % columns, (ui.cursor - 1) % columns
        if tx ~= cx then return press(tx > cx and "Right" or "Left") end
        return press(index > ui.cursor and "Down" or "Up")
    end
    local function pick_move(ui)
        if type(ui.items) ~= "table" then return nil, "move list unreadable" end
        for _, name in ipairs(passive) do
            for _, label in ipairs(ui.items) do
                if type(label) == "string" and label:upper() == name then return choose(ui, name, 1) end
            end
        end
        return choose(ui, tostring(ui.items[1]):upper(), 1)
    end
    local function living_other(point)
        for slot = 0, 5 do
            local hp = point.party_hp[slot]
            if slot ~= target and type(hp) == "number" and hp > 0 then return slot end
        end
    end
    function self.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, self.phase end
        if release then release = false; return {}, self.phase end
        if self.phase == self.terminal then return {}, self.phase end
        if self.phase == "walk" and integer(point.battle_mode, 1, 255) then
            if point.battle_mode ~= 1 then return nil, "not a wild battle" end
            self.phase, self.battles, switched = "battle", self.battles + 1, false
        end
        if self.phase == "battle" and integer(point.active_slot, 0, 5) then
            target = target == nil and point.active_slot or target   -- opts.target nil: the lead fights
            if point.active_slot == target then switched = true end
        end
        local ui = point.ui
        if ui ~= nil then
            if self.phase ~= "battle" then return nil, "UI is not valid in phase " .. self.phase .. ": " .. tostring(ui.kind) end
            if point.input_ready ~= true then return {}, self.phase end
            local done = point.fainted == true
            if ui.kind == "battle_menu" then
                if done or (point.foe_harmless and not switched) then return choose(ui, "RUN", 2) end
                return choose(ui, switched and "FIGHT" or FI.PKMN_CELL, 2)
            end
            if ui.kind == "battle_party" then
                local want = (done or switched) and living_other(point) or target
                if want == nil then return nil, "no living party mon left to send out" end
                if not integer(point.party_cursor, 0, 5) then return {}, self.phase end
                if point.party_cursor == want then return press("A") end
                return press(point.party_cursor < want and "Down" or "Up")
            end
            if ui.kind == "battle_mon_menu" then return choose(ui, "SWITCH", 1) end
            if ui.kind == "move_menu" then
                if done then return press("B") end
                return pick_move(ui)
            end
            if ui.kind == "yes_no" then
                if ui.prompt ~= "next_mon" then return nil, "unmapped battle yes/no prompt: " .. tostring(ui.prompt) end
                return choose(ui, "YES", 1)
            end
            if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
            return nil, "UI is not valid in battle: " .. tostring(ui.kind)
        end
        if point.overworld_ready ~= true then return {}, self.phase end
        if self.phase == "battle" then
            if point.fainted == true then self.phase = self.terminal return {}, self.phase end
            if target ~= nil and point.party_hp[target] == 0 then
                return nil, "the target is at 0 HP but the engine faint was never observed"
            end
            if self.battles >= max_battles then return nil, "the target survived " .. self.battles .. " battles" end
            self.phase = "walk"
        end
        if here and (here.x ~= point.x or here.y ~= point.y) then from = here end
        here = {x=point.x, y=point.y}
        local button, why = F.walk_direction(map, point, from)
        if not button then return nil, why end
        return {[button]=true}, self.phase
    end
    return self
end

function FI.new(ctx, SG, F, opts)
    local driver = FI.driver(F, ctx.facts.maps.Route29, opts)
    local base = SG.qualify_observer(ctx)
    local function observe()
        local point = base()
        point.fainted = opts.fainted() == true
        local battle = ctx.reads.read_battle()
        point.active_slot = battle and battle.mode ~= 0 and battle.active_slot or nil
        local foe = battle and battle.mode ~= 0 and ctx.reads.read_battle_mon("enemy") or nil
        if foe then
            point.foe_harmless = true
            for _, move in ipairs(foe.moves) do
                if move ~= 0 and move ~= FI.SPLASH then point.foe_harmless = false end
            end
        end
        point.party_hp = {}
        local party = ctx.reads.read_party()
        for _, m in ipairs(party and party.mons or {}) do point.party_hp[m.slot] = m.hp end
        if point.ui and point.ui.kind == "battle_party" then point.party_cursor = FI.party_cursor(SG.screen(ctx)) end
        return point
    end
    local budget = F.BUDGET
    local spec = {name="duo-gen2-faint", terminal=driver.terminal, terminal_idle=true,
                  max_frames=opts.max_frames or budget.max_frames,
                  max_phase_frames=math.min(opts.max_phase_frames or budget.max_phase_frames,
                                            opts.max_frames or budget.max_frames),
                  settle_frames=budget.settle_frames}
    return driver, observe, spec
end

return FI
