-- Pure R/B Route 1 hunt for the duo lane. From the parking tile (10,35) pace the grass column
-- until a wild battle starts, then CATCH (FIGHT once while the foe is at full HP, then
-- throw the bag's Poke Ball), RUN, or switch the linked slot in for a bounded faint window.
-- Same shape as gen1_rb_route1_inputs: point -> buttons,
-- phase; the caller owns frames. The battle itself is played through gen1_battle_driver.lua,
-- whose synchronous step(buttons) is bridged with a coroutine so it still costs one frame per
-- buttons returned from here.
--
-- Terminal phases: "caught" (party grew), "escaped" (mode "run": RUN succeeded),
-- "out-of-balls" (the throw failed, no ball left, RUN succeeded), "linked-fainted",
-- "linked-active-menu" and failures "linked-survived-3-battles", "hunt-exhausted",
-- "whiteout", "stuck".
local M = {}
M.PARK = {10, 35}
-- Route 1 grass at the parking tile: pret maps/Route1.blk + gfx/blocksets/overworld.bst, grass
-- tile $52 read at the half-block's bottom-right tile (engine/battle/wild_encounters.asm:27-31)
-- -> steps x 10-11, y 32-35. (10,36) is the Pallet Town edge: never walk there.
M.GRASS = {{10, 33}, {10, 35}}
M.MAX_ENCOUNTERS = 6

local function idle() return {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false} end
local function tap(key, frame) local b = idle(); b[key] = frame % 16 < 2; return b end
local function move(point, target)
    local b = idle()
    if point.x < target[1] then b.Right = true
    elseif point.x > target[1] then b.Left = true
    elseif point.y < target[2] then b.Down = true
    elseif point.y > target[2] then b.Up = true end
    return b
end

-- Fields gen1_scripted_play's point lacks: the foe's HP for the fight/throw decision and the
-- bag index of the first ball (MASTER..POKE = 1..4, constants/item_constants.asm:10-13).
-- rd(addr) reads one System Bus byte; symbols is the title's pret .sym table.
function M.extend_point(point, rd, symbols)
    local function u16(name) local a = assert(symbols[name], name); return rd(a) * 256 + rd(a + 1) end
    point.enemy_hp, point.enemy_max_hp = u16("wEnemyMonHP"), u16("wEnemyMonMaxHP")
    point.ball_index = nil
    local n = rd(assert(symbols.wNumBagItems))
    for i = 0, math.min(n, 20) - 1 do
        local id = rd(symbols.wBagItems + 2 * i)
        if id >= 1 and id <= 4 and point.ball_index == nil then point.ball_index = i end
    end
    return point
end

-- Poke Ball odds at this HP, ItemUseBall (engine/items/item_effects.asm): Rand1 (0-255) <=
-- catch rate always holds for Pidgey/Rattata (255); W = floor(floor(maxhp*255/12) /
-- max(floor(hp/4), 1)); caught when W > 255 or Rand2 <= W.
function M.catch_odds(hp, maxhp)
    local w = math.floor(math.floor(maxhp * 255 / 12) / math.max(math.floor(hp / 4), 1))
    if w >= 255 then return 1 end
    return (w + 1) / 256
end

-- opts.driver   gen1_battle_driver built by the caller with a step that yields the buttons
-- opts.step     that same yielding step (for text-advancing taps between driver calls)
-- opts.rd       read_u8 on the System Bus;  opts.symbols  the title's pret .sym table
-- opts.mode     "catch" | "run" | "sacrifice" | "switch-hold"; opts.log optional line sink
-- opts.switch_slot 0-based linked party slot; opts.move_slot 1-based move to play
-- opts.fainted() read-only engine-faint receipt predicate for sacrifice mode.
function M.new(expected, opts)
    assert(expected and (expected.player == "a" or expected.player == "b"), "R/B route identity required")
    assert(opts and opts.driver and opts.step and opts.rd and opts.symbols, "hunt needs driver/step/rd/symbols")
    local D, step, rd, S = opts.driver, opts.step, opts.rd, opts.symbols
    local mode = opts.mode or "catch"
    assert(mode == "catch" or mode == "run" or mode == "sacrifice" or mode == "switch-hold",
           "mode catch|run|sacrifice|switch-hold")
    if mode == "sacrifice" then
        assert(type(opts.move_slot) == "number" and opts.move_slot >= 1 and opts.move_slot <= 4
               and type(opts.fainted) == "function", "sacrifice needs a move slot and faint receipt")
    end
    local log = opts.log or function() end
    local self = {last_frame = -1, encounters = 0, target = 1, battle_co = nil, stage = "begin",
                  party_before = nil, terminal = nil, receipts = {}}

    local function u16(name) local a = S[name]; return rd(a) * 256 + rd(a + 1) end
    local function foe() return u16("wEnemyMonHP"), u16("wEnemyMonMaxHP") end
    local function balls()
        local n, total = rd(S.wNumBagItems), 0
        for i = 0, math.min(n, 20) - 1 do
            local id = rd(S.wBagItems + 2 * i)
            if id >= 1 and id <= 4 then total = total + rd(S.wBagItems + 2 * i + 1) end
        end
        return total
    end
    local function ball_index()
        local n = rd(S.wNumBagItems)
        for i = 0, math.min(n, 20) - 1 do
            local id = rd(S.wBagItems + 2 * i)
            if id >= 1 and id <= 4 then return i end
        end
        return nil
    end
    local function mash(btn, frames)
        for i = 1, frames do step({[btn] = i % 16 < 2}) end
    end
    -- The next battle menu after the driver's last A press, tapping B through anything that
    -- waits for a button (level-up stats box, caught/dex screens, the nickname prompt = NO).
    local function wait_menu(budget)
        local used = 0
        while used < budget do
            local r = D.wait_menu(240)
            used = used + r.frames
            if r.ok then return "menu" end
            if r.why == "battle_over" then return "battle_over" end
            mash("B", 32); used = used + 32
        end
        return "timeout"
    end
    local function run_until_escaped()
        for _ = 1, 10 do
            local t = D.run(600)
            self.receipts[#self.receipts + 1] = "run:" .. tostring(t.why)
            if t.ok then return "ran" end
            if t.why == "battle_over" then return "battle_over" end
            if t.why ~= "battle_menu_again" then
                local m = wait_menu(1200)
                if m ~= "menu" then return m end
            end
        end
        return "stuck"
    end
    -- One battle, start to finish. Returns the outcome; the caller decides what it means.
    local function plan()
        self.stage = "intro"
        local m = wait_menu(1800)
        if m ~= "menu" then return m end
        if mode == "run" then self.stage = "run"; return run_until_escaped() end
        if mode == "sacrifice" or mode == "switch-hold" then
            -- pret engine/battle/core.asm:2329-2419: PKMN -> PartyMenuInit (row = physical
            -- slot) -> SWITCH/STATS/CANCEL. Driver.switch_to verifies Y/X and cursor.
            self.stage = "switch"
            local switched = D.switch_to(opts.switch_slot or 1, 900)
            self.receipts[#self.receipts + 1] = "switch:" .. tostring(switched.why)
            if mode == "sacrifice" and opts.fainted() then return "linked-fainted" end
            if not switched.ok then return "stuck" end
            log("[hunt] linked slot " .. tostring(opts.switch_slot or 1) .. " active")
            if mode == "switch-hold" then
                self.stage = "hold"
                m = wait_menu(1800)
                return m == "menu" and "linked-active-menu" or m
            end
            for turn = 1, 60 do
                if opts.fainted() then return "linked-fainted" end
                self.stage = "linked-turn"
                m = wait_menu(1800)
                if opts.fainted() then return "linked-fainted" end
                if m ~= "menu" then return m end
                local chosen = D.choose("FIGHT")
                if not chosen.ok then return "stuck" end
                local move = D.commit_move(opts.move_slot, 900)
                self.receipts[#self.receipts + 1] = "gentle:" .. tostring(move.why)
                log("[hunt] linked move turn " .. turn .. " -> " .. tostring(move.why))
                if opts.fainted() then return "linked-fainted" end
                if move.why == "battle_over" then return "battle_over" end
            end
            return "stuck"
        end
        local dmax = nil -- largest Tackle damage seen so far (a non-crit roll is 217-255/255 of base)
        for turn = 1, 4 do
            local hp, maxhp = foe()
            local odds = M.catch_odds(hp, maxhp)
            local throw = odds >= 0.99 or turn == 4 or (dmax ~= nil and hp <= dmax + 1)
                or (hp < maxhp and odds >= 0.8)
            log(string.format("[hunt] turn %d foe hp %d/%d odds %.2f dmax %s -> %s", turn, hp, maxhp, odds,
                              tostring(dmax), throw and "throw" or "fight"))
            if throw then break end
            self.stage = "fight"
            local c = D.choose("FIGHT")
            if not c.ok then self.receipts[#self.receipts + 1] = "fight:" .. tostring(c.why); return c.why == "battle_over" and "battle_over" or "stuck" end
            local t = D.commit_move(1)
            self.receipts[#self.receipts + 1] = "move1:" .. tostring(t.why)
            if not t.ok and t.why == "battle_over" then return "battle_over" end
            m = wait_menu(1800)
            if m ~= "menu" then return m end
            local after = foe()
            local dealt = hp - after
            if dealt > 0 then dmax = math.max(dmax or 0, math.ceil(dealt * 255 / 217)) end
        end
        while true do
            local idx = ball_index()
            if not idx then self.stage = "no-balls"; return run_until_escaped() end
            self.stage = "throw"
            local t = D.use_item(idx, 600)
            self.receipts[#self.receipts + 1] = "throw:" .. tostring(t.why)
            log("[hunt] threw ball index " .. idx .. " -> " .. tostring(t.why))
            -- caught: dex/nickname prompts (B = NO) then the battle ends; failed: the menu returns
            m = wait_menu(3600)
            if m ~= "menu" then return m end
        end
    end

    function self.step(handshake, status, point, frame)
        assert(type(frame) == "number" and frame > self.last_frame, "hunt frame did not advance")
        self.last_frame = frame
        assert(point and type(point.map) == "number" and type(point.x) == "number" and type(point.y) == "number"
            and type(point.battle) == "number" and type(point.party_count) == "number", "complete read-only hunt point required")
        if self.terminal then return idle(), self.terminal end
        if point.battle ~= 0 and point.battle ~= 1 then
            self.terminal = point.battle == 255 and "whiteout" or "unexpected-battle"
            return idle(), self.terminal
        end
        if point.battle == 1 and not self.battle_co then
            assert(point.battle_type == 0 and type(point.party_hp) == "number" and point.party_hp > 0,
                   "unexpected special battle or whiteout")
            self.encounters = self.encounters + 1
            self.party_before = point.party_count
            self.balls_before = balls()
            self.battle_co = coroutine.create(plan)
            log(string.format("[hunt] encounter %d at (%d,%d) mode=%s balls=%d", self.encounters, point.x, point.y, mode, self.balls_before))
        end
        if self.battle_co then
            local ok, res = coroutine.resume(self.battle_co)
            assert(ok, "battle plan error: " .. tostring(res))
            if coroutine.status(self.battle_co) ~= "dead" then return res or idle(), "wild-" .. self.stage end
            self.battle_co = nil
            self.outcome = res
            log("[hunt] battle outcome " .. tostring(res) .. " receipts " .. table.concat(self.receipts, ","))
            self.receipts = {}
            if res == "stuck" or res == "timeout" then self.terminal = "stuck"; return idle(), self.terminal end
            if res == "linked-fainted" or res == "linked-active-menu" then
                self.terminal = res
                return idle(), self.terminal
            end
            return idle(), "wild-" .. tostring(res)
        end
        if point.battle ~= 0 then return idle(), "wild-ending" end
        if self.outcome then
            -- the battle is over: classify it once, from the game's own state
            local o = self.outcome
            self.outcome = nil
            if mode == "sacrifice" then
                if opts.fainted() then self.terminal = "linked-fainted"
                elseif self.encounters >= 3 then self.terminal = "linked-survived-3-battles" end
            elseif point.party_count > self.party_before then self.terminal = "caught"
            elseif mode == "run" then self.terminal = "escaped"
            elseif balls() == 0 then self.terminal = "out-of-balls"
            elseif self.encounters >= M.MAX_ENCOUNTERS then self.terminal = "hunt-exhausted" end
            log(string.format("[hunt] after battle: outcome=%s result=%s party=%d balls=%d -> %s",
                              o, tostring(point.battle_result), point.party_count, balls(), self.terminal or "hunt again"))
            if self.terminal then return idle(), self.terminal end
        end
        if point.font_loaded or point.joy_ignore ~= 0 then return tap("B", frame), "close-text" end
        if point.map ~= 0x0C then return idle(), "unknown-map" end
        local target = M.GRASS[self.target]
        if point.x == target[1] and point.y == target[2] then
            self.target = 3 - self.target
            target = M.GRASS[self.target]
        end
        return move(point, target), "pace-grass"
    end
    return self
end
return M
