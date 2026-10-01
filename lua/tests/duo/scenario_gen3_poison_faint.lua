-- scenario_gen3_poison_faint.lua — poison_faint_gen3: S-11 `poison_faint` on FR/LG and Emerald
-- (card NAT-LEGS, NAT-LEGS-3).
--
-- FR/LG SYNTH setup, disclosed (O-33): A boots firered_party_poison_synth.sav -- party[0] Squirtle
-- at 1 HP and POISONED on Viridian City's south tile (24,39) (tools/gen3_fixtures.py
-- make-frlg-synth --kind poison). NATIVE: A walks Up/Down between (24,39) and (24,38) (no grass
-- on map 3.1, tools/gba_map.py; never Down from (24,39): Route 1).
-- Emerald SYNTH setup (card NAT-LEGS-3): A boots emerald_poison.sav -- party[0] Mudkip at 1 HP and
-- POISONED on Oldale Town (6,17) (tools/gen3_fixtures.py make-emerald --kind poison; the same tile
-- as `town`). NATIVE: A walks Down/Up between (6,17) and (6,18) -- never Up from (6,17): that is
-- the Pokemon Center's door warp (data/maps/OldaleTown/map.json warp_events (6,16), pret
-- pokeemerald c65e93f2; data/layouts/OldaleTown/map.bin confirms (6,17)/(6,18) are both plain,
-- collision-free street metatiles).
-- Either way, the runner links A's lead with B's slot 0; within four steps the title's own poison
-- step (VAR_POISON_STEP_COUNTER % 4, field_poison.c DoPoisonFieldEffect, no 1-HP floor on either
-- title) takes it to 0 HP, the faint is dismissed with A, and the healthy second party mon keeps
-- the party alive (no whiteout). The client sends faint for the key; the server kills the pair
-- (Soul Link): B receives force_faint and its client writes HP 0 at the overworld checkpoint;
-- both memorials save.
local WALK_FIRST = { firered = "Up", leafgreen = "Up", emerald = "Down" }

local function tap_signals(ctx, kinds)
    local sigs = assert(ctx.session.signals, "the client armed no signal source")
    local drain = sigs.drain
    sigs.drain = function(self)
        local out = drain(self)
        for _, s in ipairs(out) do
            if kinds[s.kind] then ctx.log(ctx.fmt("SIGNAL %s frame=%d address=0x%08X", s.kind, s.frame, s.address)) end
        end
        return out
    end
end

return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local linked = ctx.linked()
    if not linked then return false, "the go-file names no LINKED key" end
    if not ctx.find(linked) then return false, "the linked key " .. linked .. " is not in the party" end
    tap_signals(ctx, { poison_faint = true, faint = true, whiteout = true })
    ctx.log("READY " .. linked)
    if ctx.player == "a" then
        local m = ctx.find(linked)
        if not (m.hp == 1 and m.status & 0x7 == 0 and m.status & 0x8 ~= 0) then
            return false, ctx.fmt("the linked mon is not the fixture's poisoned 1-HP lead (hp=%d status=0x%X)",
                                  m.hp, m.status)
        end
        local play, cp = ctx.play, ctx.cp
        local map = play.map(cp)
        local first = assert(WALK_FIRST[ctx.title], "poison_faint_gen3: no walk direction for title " .. tostring(ctx.title))
        local second = (first == "Up") and "Down" or "Up"
        local steps = 0
        for i = 1, 12 do
            local dir = (i % 2 == 1) and first or second
            local ok = play.step(cp, dir, map, true, false)
            if not ok then return false, "step " .. i .. " " .. dir .. " stalled at " .. play.at(cp) end
            steps = i
            if ctx.sent("faint", linked) > 0 then break end
            local now = ctx.find(linked)
            if now and now.hp == 0 then
                if not ctx.wait_sent("faint", linked, 30) then return false, "HP 0 but no faint sent" end
                break
            end
        end
        if ctx.sent("faint", linked) == 0 then return false, "no faint after " .. steps .. " steps" end
        ctx.log(ctx.fmt("POISON_FAINT %s steps=%d at=%s", linked, steps, play.at(cp)))
        if not ctx.mash_until(function() return ctx.on_field() and ctx.player_idle() and ctx.sent("memorialize_done", linked) > 0 end,
                              600, "A") then
            return false, "the fainted message / memorialize never settled"
        end
        if ctx.received("force_faint") > 0 then return false, "A (the poisoned half) received a force_faint" end
        if ctx.sent("whiteout") > 0 then return false, "a whiteout: the healthy second party mon should have kept the party alive" end
    else
        if not ctx.wait_sent("memorialize_done", linked, 900) then return false, "no memorialize_done for " .. linked end
        if ctx.received("force_faint", linked) == 0 then return false, "B never received force_faint" end
        local h = ctx.hp0(linked)
        if not h then return false, "force_faint never took " .. linked .. " to HP 0 before its memorial" end
        if h.in_battle then return false, "the forced HP 0 landed in a battle; this scenario is overworld" end
    end
    ctx.frames(60)
    local ok, why = ctx.save("poison_faint")
    if not ok then return false, why end
    return true, "memorialized " .. linked
end
