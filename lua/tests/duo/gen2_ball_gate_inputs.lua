--[[
  lua/tests/duo/gen2_ball_gate_inputs.lua -- the gen2_ball_gate duo's two scripted legs (card DUO-WAVE-D, D-2).
  Facts: docs/gen2/reviews/DUO_WAVE_D_FACTS_2026-09-24.md section 1.

  Pure point -> buttons, phase over lua/tests/gen2_scripted_play.lua (P), run with the errand route facts on a warm
  <title>_town[_ot2] fixture (Elm's lab after the starter, EMPTY Ball pocket) as case.resume + case.natural_balls:
  no O-10 staging, the errand's aide gives the first Balls (C maps/ElmsLab.asm:498-504, G :455-461).
    mode "pre"   lab -> New Bark -> Route 29 GRASS before the errand: terminal "pre-grass" on a grass tile or once a
                 wild battle is up (duo_gen2_main.lua h.encounter / h.flee take it from there). Balls here refuse.
    mode "post"  Route 29 -> the whole errand (Mr. Pokemon, the rival loss, Elm, the aide's Balls; pre-Ball wild
                 battles are RUN by P) -> back on Route 29: terminal "post-grass" on a grass tile or on the first
                 post-Ball wild battle, handed over UNANSWERED to the link catch (P would RUN it, and a RUN with
                 Balls sends no_catch and resolves route_29). Reaching Route 29 after the errand with no Balls or
                 more than the aide's five refuses (no natural acquisition, or an O-10 stack).
--]]
local B = {}
B.AIDE_BALLS = 5   -- giveitem POKE_BALL, 5 (C maps/ElmsLab.asm:504, G :461)

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

-- Poke Balls in the observed pocket (the route facts' ball item), or nil for a malformed pocket.
local function balls(point, item)
    local pocket = point.ball_pocket
    if type(pocket) ~= "table" or type(pocket.items) ~= "table" then return nil end
    local n = 0
    for _, row in ipairs(pocket.items) do
        if row.id == item then n = n + row.quantity end
    end
    return n
end

function B.driver(P, facts, case, mode)
    assert(mode == "pre" or mode == "post", "ball gate leg mode pre|post required")
    local c = {}
    for k, v in pairs(case) do c[k] = v end
    c.target, c.resume, c.natural_balls = "battle", true, true
    local inner = P.new(facts, c)
    local route29, item = facts.maps.Route29, facts.balls.item
    local self = {terminal=mode .. "-grass", phase="start"}
    local frame = 0
    local function done()
        self.phase = self.terminal
        return {}, self.phase
    end
    function self.step(point)
        frame = frame + 1
        if self.phase == self.terminal then return {}, self.phase end
        if type(point) ~= "table" then return nil, "observation missing" end
        local on29 = point.map_group == route29.map_group and point.map_number == route29.map_number
        local n = balls(point, item)
        if n == nil then return nil, "malformed observed Ball pocket" end
        if on29 and mode == "pre" and point.got_egg ~= true then
            if n > 0 then return nil, "Poke Balls before the errand: not a zero-Ball start" end
            if integer(point.battle_mode, 1, 255) then return done() end
            if point.ui ~= nil then return inner.step(point, frame) end   -- text on the way
            if point.overworld_ready ~= true then return {}, self.phase end
            local button, why = P.direction(route29, point, {grass=true})
            if not button then return nil, why end
            if button == "arrived" then return done() end
            self.phase = "pre-walk"
            return {[button]=true}, self.phase
        end
        if on29 and mode == "post" and point.gave_egg == true then
            if n < 1 or n > B.AIDE_BALLS then
                return nil, string.format("%d Poke Balls after the errand: not the aide's natural Balls", n)
            end
            if integer(point.battle_mode, 1, 255) then return done() end
            if point.ui == nil and point.overworld_ready == true
               and P.direction(route29, point, {grass=true}) == "arrived" then return done() end
        end
        local buttons, phase, request = inner.step(point, frame)
        if buttons == nil then return nil, phase end
        if request ~= nil then return nil, "the ball gate route never stages: " .. tostring(request.kind) end
        self.phase = phase
        return buttons, phase
    end
    return self
end

return B
