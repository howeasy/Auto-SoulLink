--[[
  lua/tests/gen2_pc_inputs.lua -- card gen2-u1f-pc: after the U1e chain's closing whiteout, walk to Route 29 grass
  (the second catch is F.driver's), then work Bill's PC at the Cherrygrove #MON CENTER with normal buttons only.
  Shape of lua/tests/gen2_poison_inputs.lua: PC.prepare(ctx, SG, u1) before SG.hooks; PC.new(ctx, SG, F, PI, opts)
  -> driver, observe, spec for F.play. opts.mode = "grass" (terminal "grass": on a Route 29 grass tile, or a wild
  battle already up) | "pc" (terminal "pc-done": the six PC operations done, back on the overworld).

  PC operations, in order (party [lead, catch 1, catch 2] after the second catch; BOX1 and BOX2 empty):
    1 deposit party slot 1 (catch 1)   -> pc_deposit_begin/_complete      done: party 2
    2 withdraw it (the last box slot)  -> pc_withdraw_begin/_complete     done: party 3
    3 CHANGE BOX to BOX2 (+ its save)  -> change_box_begin/_loaded        done: wCurBox = BOX1 + 1
    4 deposit party slot 2 (catch 1)   -> pc_deposit_*                    done: party 2
    5 release it from BOX2             -> pc_release_box_begin/_complete  done: box count - 1
    6 release party slot 1 (catch 2)   -> pc_release_party_begin/_complete done: party 1
  Each step is closed by its RAM effect (wPartyCount, sBoxCount, wCurBox), never by a button count.
  UI (facts.pc.ui, all from the pinned source; tests/live/test_gen2_frame_align.u1f_facts):
    pc_top          PokemonCenterPC.loop  BILL's PC | <PLAYER>'s PC | TURN OFF
    bills_pc        _BillsPC.loop         WITHDRAW | DEPOSIT | CHANGE BOX | MOVE W/O MAIL | SEE YA!
    deposit_list    _DepositPKMN.HandleJoypad   list cursor = wBillsPC_CursorPosition + wBillsPC_ScrollPosition
    deposit_menu    _DepositPKMN.Submenu        DEPOSIT | STATS | RELEASE | CANCEL
    withdraw_list   _WithdrawPKMN.Joypad        (same cursor RAM)
    withdraw_menu   BillsPC_Withdraw            WITHDRAW | STATS | RELEASE | CANCEL
    box_list        _ChangeBox.loop             BOX1..BOX14 (SetDefaultBoxNames)
    box_menu        BillsPC_ChangeBoxSubmenu    SWITCH | NAME | PRINT | QUIT
  yes/no: "Release <PK><MN>?" YES; "…will be saved. OK?" YES; the save overwrite YES; every text box A.
--]]
local PC = {}
PC.HOLD = 12
PC.WAIT_FRAMES = 600
PC.YES_NO_SETTLE = 8   -- the scripted gate's UI_SETTLE_FRAMES

local fmt = string.format
local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end
local function on(point, map) return point.map_group == map.map_group and point.map_number == map.map_number end

function PC.prepare(ctx, SG, u1)
    local pc = assert(u1.pc, "SLINK_GEN2_U1_FACTS lacks pc")
    for kind, site in pairs(pc.ui) do ctx.facts.ui_origins[kind] = site end
    for _, kind in ipairs(pc.menus) do SG.MENU_KINDS[kind] = true end
    for _, kind in ipairs(pc.loops) do SG.LOOP_KINDS[kind] = true end
end

-- Pure: the PC plan's next step, given the observed counts; steps close on their RAM effect.
PC.STEPS = {"deposit", "withdraw", "change_box", "deposit", "release_box", "release_party"}

-- Pure point -> buttons, phase. point adds: party_count, box_count (active box), cur_box, pc_cursor (list index).
function PC.driver(PI, facts, opts)
    local mode = opts.mode
    local self = {terminal=mode == "grass" and "grass" or "pc-done", phase=mode == "grass" and "to-grass" or "to-pc",
                  op_index=1}
    local held, hold_left, release, waited = nil, 0, false, 0
    local start   -- counts when the PC was reached
    local function press(button)
        release, held, hold_left = true, button, PC.HOLD - 1
        return {[button]=true}, self.phase
    end
    -- by label prefix (Bill's PC rows read "WITHDRAW <PK><MN>", the top menu "BILL's PC")
    local function choose(ui, wanted, columns)
        columns = columns or 1
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local index
        for i, label in ipairs(ui.items) do
            if type(label) == "string" and label:upper():sub(1, #wanted) == wanted then
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
        if not button then button = PI.step_toward(map, {x=point.x, y=point.y, can_step=point.can_step}, goals) end
        if not button then
            local open = {x=point.x, y=point.y, can_step={Up=true, Down=true, Left=true, Right=true}}
            if PI.step_toward(map, open, goals) and waited < PC.WAIT_FRAMES then
                waited = waited + 1
                return {}, self.phase
            end
            return nil, why
        end
        waited = 0
        if button == "arrived" then return nil, "arrived" end
        return {[button]=true}, self.phase
    end
    local op = function() return PC.STEPS[self.op_index] end
    -- the list index a step works on
    local function target()
        local o = op()
        if o == "deposit" then return self.op_index == 1 and 1 or 2 end
        if o == "release_party" then return 1 end
        if o == "withdraw" or o == "release_box" then return (start.box_step or 1) - 1 end
    end
    local function advance(point)
        if not start or not integer(point.party_count, 1, 6) or not integer(point.box_count, 0, 20) then return end
        local o = op()
        local done = (o == "deposit" and point.party_count == 2)
            or (o == "withdraw" and point.party_count == 3)
            or (o == "change_box" and point.cur_box == start.box + 1)
            or (o == "release_box" and point.box_count == start.box_step - 1)
            or (o == "release_party" and point.party_count == 1)
        if done then
            self.op_index = self.op_index + 1
            if PC.STEPS[self.op_index] == "withdraw" or PC.STEPS[self.op_index] == "release_box" then
                start.box_step = point.box_count   -- the mon to take is the last one deposited
            end
        end
    end
    local function battle(point, ui)
        if ui.kind == "battle_menu" then
            if point.battle_mode ~= 1 then return nil, "battle menu outside a wild battle" end
            return choose(ui, "RUN", 2)
        end
        if ui.kind == "move_menu" then return press("B") end
        if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
        return nil, "UI is not valid in battle: " .. tostring(ui.kind)
    end
    local function list(point)
        local t = target()
        local o = op()
        local wanted = (point.ui.kind == "deposit_list" and (o == "deposit" or o == "release_party"))
            or (point.ui.kind == "withdraw_list" and (o == "withdraw" or o == "release_box"))
        if not wanted then return press("B") end
        if not integer(point.pc_cursor, 0, 20) then return {}, self.phase end
        if point.pc_cursor == t then return press("A") end
        return press(point.pc_cursor < t and "Down" or "Up")
    end
    local function pc_ui(point, ui)
        local o = op()
        if ui.kind == "pc_top" then return choose(ui, o and "BILL" or "TURN OFF") end
        if ui.kind == "bills_pc" then
            local row = ({deposit="DEPOSIT", release_party="DEPOSIT", withdraw="WITHDRAW", release_box="WITHDRAW",
                          change_box="CHANGE BOX"})[o] or "SEE YA"
            return choose(ui, row)
        end
        if ui.kind == "deposit_list" or ui.kind == "withdraw_list" then return list(point) end
        if ui.kind == "deposit_menu" then
            return choose(ui, o == "deposit" and "DEPOSIT" or o == "release_party" and "RELEASE" or "CANCEL")
        end
        if ui.kind == "withdraw_menu" then
            return choose(ui, o == "withdraw" and "WITHDRAW" or o == "release_box" and "RELEASE" or "CANCEL")
        end
        if ui.kind == "box_list" then
            if o ~= "change_box" then return press("B") end
            return choose(ui, fmt("BOX%d", start.box + 2))
        end
        if ui.kind == "box_menu" then return choose(ui, o == "change_box" and "SWITCH" or "QUIT") end
        if ui.kind == "yes_no" then
            if ui.prompt == "release" or ui.prompt == "change_box_save" or ui.prompt == "save_overwrite" then
                return choose(ui, "YES")
            end
            -- A stale yes/no context: after a release the box is gone but no newer UI origin has run yet
            -- (ReleasePKMN_ByePKMN's DelayFrames, bills_pc.asm; live U1f Crystal run 4). Wait for the next origin.
            if ui.prompt == nil then return {}, self.phase end
            return nil, "unmapped PC yes/no prompt: " .. tostring(ui.prompt)
        end
        if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
        return nil, "UI is not valid at the PC: " .. tostring(ui.kind)
    end
    local function travel(point, plan)
        for name, leg in pairs(plan) do
            local map = facts.maps[name]
            if map and on(point, map) then
                if leg.kind == "edge" then
                    local buttons, why = walk(map, point, leg.exits)
                    if why == "arrived" then return {[leg.side]=true}, self.phase end
                    return buttons, why
                end
                if leg.kind == "warp" then
                    local buttons, why = walk(map, point, {leg.tile})
                    if why == "arrived" then
                        if leg.carpet then return press(leg.carpet) end
                        return {}, self.phase   -- a stair warp fires on arrival
                    end
                    return buttons, why
                end
                if leg.kind == "grass" then
                    local grass = {}
                    for y = 0, map.height - 1 do
                        for x = 0, map.width - 1 do
                            if map.grid[y * map.width + x + 1] == 2 then grass[#grass + 1] = {x=x, y=y} end
                        end
                    end
                    local buttons, why = walk(map, point, grass)
                    if why == "arrived" then self.phase = self.terminal return {}, self.phase end
                    return buttons, why
                end
                if leg.kind == "pc" then
                    local stand = facts.pc_stand
                    local buttons, why = walk(map, point, {stand})
                    if why ~= "arrived" then return buttons, why end
                    self.phase = "pc"
                    start = start or {box=point.cur_box, party=point.party_count}
                    if point.facing ~= "Up" then return press("Up") end
                    if op() then return press("A") end
                    self.phase = self.terminal
                    return {}, self.phase
                end
            end
        end
        return nil, fmt("map %s:%s is not on the source plan", tostring(point.map_group), tostring(point.map_number))
    end
    function self.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, self.phase end
        if release then release = false; return {}, self.phase end
        if self.phase == self.terminal then return {}, self.phase end
        advance(point)
        local ui = point.ui
        if integer(point.battle_mode, 1, 255) then
            if mode == "grass" then self.phase = self.terminal return {}, self.phase end   -- F.driver takes the battle
            if ui == nil or point.input_ready ~= true then return {}, self.phase end
            return battle(point, ui)
        end
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if self.phase == "pc" then return pc_ui(point, ui) end
            if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
            return nil, "UI is not valid in phase " .. self.phase .. ": " .. tostring(ui.kind)
        end
        if point.overworld_ready ~= true then return {}, self.phase end
        return travel(point, mode == "grass" and facts.to_grass or facts.to_pc)
    end
    return self
end

function PC.new(ctx, SG, F, PI, opts)
    local facts = assert(ctx.u1.pc, "SLINK_GEN2_U1_FACTS lacks pc")
    local driver = PC.driver(PI, facts, opts)
    local base = SG.qualify_observer(ctx)
    local ram, api = facts.ram, ctx.api
    local function cart(sym) return api.read_u8(sym.bank * 0x2000 + sym.addr - 0xA000, "CartRAM") end
    local yes_no_since
    local function observe()
        local point = base()
        -- The release yes/no (PlaceYesNoBox at 14,11 over the WITHDRAW/DEPOSIT submenu, bills_pc.asm .release /
        -- BillsPCDepositFuncRelease) shares the screen with the submenu's own cursor, so the boxed parser refuses
        -- it (live U1f Crystal run 2). Read its YES/NO rows directly; ready 8 frames after it appeared.
        local ui = point.ui
        if ui and ui.kind == "yes_no" and ui.items == nil then
            yes_no_since = yes_no_since or api.framecount()
            local rows = SG.screen(ctx)
            local cursor
            for _, row in ipairs(rows) do
                local text = table.concat(row)
                if text:find("▶YES", 1, true) then cursor = 1 end
                if text:find("▶NO", 1, true) then cursor = cursor and -1 or 2 end
            end
            if cursor == 1 or cursor == 2 then
                ui.items, ui.cursor, ui.columns = {"YES", "NO"}, cursor, 1
                point.input_ready = api.framecount() - yes_no_since >= PC.YES_NO_SETTLE
            end
        else
            yes_no_since = nil
        end
        point.cur_box = ctx.sym("wCurBox")[1]
        point.box_count = cart(ram.sBoxCount)
        point.pc_cursor = api.read_u8(ram.wBillsPC_CursorPosition.addr, "System Bus")
            + api.read_u8(ram.wBillsPC_ScrollPosition.addr, "System Bus")
        return point
    end
    local spec = {name="u1f-" .. opts.mode, terminal=driver.terminal, terminal_idle=true,
                  max_frames=opts.max_frames, max_phase_frames=opts.max_phase_frames,
                  settle_frames=F.BUDGET.settle_frames}
    return driver, observe, spec
end

return PC
