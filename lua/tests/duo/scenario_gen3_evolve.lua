-- scenario_gen3_evolve.lua — evolve_gen3: S-8 `evolve_species_store` on FR/LG (card NAT-LEGS).
--
-- SYNTH setup, disclosed (O-33): A boots firered_party_evolve_synth.sav, whose party[0] Squirtle
-- is Lv15 and one EXP short of Lv16 (tools/gen3_fixtures.py make-frlg-synth --kind evolve). The
-- runner links A's slot-0 Squirtle with B's slot 0 (server staging). NATIVE: a Route 1 wild
-- battle, Tackle until it ends, the level-up and the post-battle evolution scene -- A presses
-- only (B cancels an evolution, pret evolution_scene.c). A Gen 3 evolution keeps PID:OTID, so the
-- client publishes WARTORTLE on its next tick (lua/gen3/client.lua on_signal); the oracle reads
-- the server's links.json half and A's saved party. B idles on its town fixture.
local SQUIRTLE, WARTORTLE = 7, 8

--- Log every validated engine signal of `kinds` as the session drains it (harness-side tee on
--- the client's own signal source; nothing is filtered, delayed or changed).
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
    if ctx.player == "b" then
        ctx.log("READY " .. linked)
        if not ctx.wait_until(ctx.partner_done, 1500, "A's RESULT") then return false, "A never finished" end
        return true, "idled while A evolved"
    end
    local m = ctx.find(linked)
    if not (m and m.species == SQUIRTLE and m.level == 15) then
        return false, "the linked key " .. linked .. " is not the fixture's Lv15 Squirtle"
    end
    tap_signals(ctx, { evolve_species_store = true, battle_begin = true, battle_end = true })
    ctx.log("READY " .. linked)
    if not ctx.hunt("evolve") then return false, "no wild encounter" end
    for turn = 1, 15 do
        local t = ctx.SP.verify_fight_cursor(ctx.cp, "incidental_battle")
        if t == nil then break end
        if t == "party" then return false, "a forced party menu came up" end
        local ok, why = ctx.use_move(0)                        -- slot 0: TACKLE
        if not ok then return false, "turn " .. turn .. ": " .. why end
        local r = ctx.await_turn(600, "A")                     -- A only: never cancel the evolution
        if r == "over" then break end
        if r ~= "action" then return false, "no decision point after TACKLE (" .. tostring(r) .. ")" end
    end
    local evolved = ctx.mash_until(function()
        local now = ctx.find(linked)
        return now and now.species == WARTORTLE and ctx.on_field() and ctx.player_idle() and now
    end, 300, "A")
    if not evolved then return false, "the linked key never read WARTORTLE back on the field" end
    ctx.log(ctx.fmt("EVOLVED %s species=%d level=%d frame=%d", linked, evolved.species, evolved.level,
                    emu.framecount()))
    ctx.frames(300)                                            -- ticks carry the new species
    if ctx.sent("key_change") > 0 then return false, "a Gen 3 evolution must not change the key" end
    local ok, why = ctx.save("evolve")
    if not ok then return false, why end
    return true, "evolved " .. linked .. " to WARTORTLE"
end
