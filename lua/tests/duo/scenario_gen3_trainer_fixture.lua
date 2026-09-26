-- scenario_gen3_trainer_fixture.lua — the PRODUCER of tests/fixtures/gen3/*_party_trainer.sav
-- (card G4-SYNTH-TRAINER). Not a test row: tools/gen3_trainer_fixture.py registers and runs it;
-- tools/e2e_duo.py's SCENARIOS never name it.
--
-- B runs linked_faint_active_trainer_gen3's own native T2 preparation, unchanged
-- (lua/tests/gen3_routes.lua enter_trainer: the old-man tutorial, Lv13 training, the heal, Route 2,
-- the gate, the Forest) from its town fixture, and STOPS at that walk's own end marker
-- PREP_ROUTE (41,45): Viridian Forest, one tile west of Bug Catcher Rick 102's sight line
-- (47,45 facing west, sight 5 -> 42..46,45; pret ViridianForest/map.json). It then saves in-game
-- there. The flushed battery is the fixture: CACHED-NATIVE, every byte made by scripted normal
-- input, only cached. A idles until B's RESULT.
local fmt = string.format
local STOP = "PREP_ROUTE map=1.0 at=(41,45)"   -- gen3_routes.lua walk(R.paths.forest)'s end line
local FLOOR, BENCH = 13, 1

local function where(ctx)
    local g, n = ctx.G.map(ctx.cp)
    local x, y = ctx.G.pos(ctx.cp)
    return g == 1 and n == 0 and x == 41 and y == 45, fmt("%d.%d (%d,%d)", g, n, x, y)
end

return function(ctx)
    if ctx.player == "a" then
        local text = ctx.wait_until(ctx.partner_result, ctx.D.timeout_secs or 7200, "B's RESULT")
        if not (text and text:find("\nRESULT: PASS", 1, true)) then return false, "B did not PASS" end
        return true, "idle; B built the trainer fixture"
    end
    if not ctx.wait_go(nil, 1800) then return false, "no go-file" end
    local party = ctx.party() or {}
    local lead, bench = party[1], party[BENCH + 1]
    if not (lead and bench) then return false, "the T2 route needs a lead and a slot-1 mon" end
    local budget = ctx.preparation_budget(lead, FLOOR)
    -- ponytail: enter_trainer is one monolithic native route; its own end-of-Forest log line is
    -- the stop signal, raised through its pcall (with_budget/with_incidental_escape restore
    -- everything on the way out). No route code is copied or edited.
    local log, stopped = ctx.log, false
    ctx.log = function(s)
        log(s)
        if s == STOP then stopped = true; error("TRAINER_FIXTURE_STOP", 0) end
    end
    local _, why = ctx.enter_trainer("trainer_fixture", 102, { level_floor = FLOOR, max_frames = budget,
        target_key = bench.key, target_slot = BENCH, target_hp = bench.hp })
    ctx.log = log
    if not stopped then return false, "trainer route: " .. tostring(why) end
    if ctx.in_battle() then return false, "in battle at the stop tile" end
    local here, at = where(ctx)
    if not here then return false, "stopped at " .. at .. ", not 1.0 (41,45)" end
    local m = (ctx.party() or {})[1]
    if not m or m.level < FLOOR then return false, "the lead is under Lv" .. FLOOR end
    -- enter_trainer demands full HP/status 0 at Rick's first menu: a fixture without it is useless
    if m.hp ~= m.max_hp or m.status ~= 0 then
        return false, fmt("the lead reached the Forest hurt (%d/%d status %d)", m.hp, m.max_hp, m.status)
    end
    local b = ctx.find(bench.key)
    if not (b and b.slot == BENCH and b.hp == bench.hp) then return false, "the bench changed on the route" end
    local saved, swhy = ctx.save("trainer_fixture")
    if not saved then return false, swhy end
    here, at = where(ctx)      -- the save's row search must not have walked us off the tile
    if not here or ctx.in_battle() then return false, "the save moved the player to " .. at end
    ctx.log(fmt("TRAINER_FIXTURE map=1.0 at=(41,45) lead=%s level=%d hp=%d/%d bench=%s hp=%d",
                m.key, m.level, m.hp, m.max_hp, bench.key, bench.hp))
    return true, "saved one tile west of Rick 102's sight line"
end
