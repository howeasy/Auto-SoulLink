-- Gen 2's complete gate flow: native pre-ball faint/RUN, native first balls,
-- then link_gen3's actual catch/link/save. SYNTH affects setup only.
local function hunt(ctx)
    local emerald = ctx.title == "emerald"
    for _ = 1, 240 do
        if ctx.in_battle() then return true end
        local x = ctx.G.pos(ctx.cp)
        local dir = emerald and (x == 3 and "Right" or "Left") or (x == 4 and "Left" or "Right")
        local ok, why = ctx.play.step(ctx.cp, dir, emerald and 6148 or 256, true, false)
        if not ok and why ~= "in_battle" then return false end
    end
    return ctx.in_battle()
end

local function pre_ball(ctx)
    local party = ctx.party()
    local lead, reserve = party and party[1], party and party[2]
    if not lead or lead.slot ~= 0 or lead.hp ~= 1 or not reserve or reserve.hp <= 0 then
        return false, "pre-ball setup needs HP1 lead and a healthy reserve"
    end
    ctx.hp0_tag = "BALL_NATIVE_HP0"
    if not ctx.hunt("pre-ball") or not ctx.wild_ready("pre-ball") then return false, "no pre-ball wild action menu" end
    local species = ctx.enemy_species()
    local ok, why = ctx.lose_active(lead.key, "pre-ball native faint")
    if not ok then return false, why end
    local site
    for _, s in ipairs(ctx.faint_sites()) do
        if s.battler0_slot == 0 and s.party_hp == 0 and s.counter >= 1 then site = s end
    end
    if not site or not ctx.hp0(lead.key) then return false, "no validated native pre-ball faint site/HP0" end
    if not ctx.wait_sent("faint", lead.key, 60) then return false, "native pre-ball faint was not sent" end
    local turn = ctx.await_turn(120, "B")
    if turn ~= "party" then return false, "pre-ball faint never reached the forced party screen" end
    ok, why = ctx.send_out(1)
    if not ok then return false, why end
    ok, why = ctx.run_away("pre-ball")
    if not ok then return false, why end
    if not species or ctx.battle_outcome() ~= 4 then return false, "pre-ball battle did not end by native RUN" end
    ctx.log(ctx.fmt("BALL_PRE_ENCOUNTER species=%d outcome=4", species))
    ctx.jlog("BALL_FAINT", {key=lead.key, hp=0, site=site, sent=ctx.sent("faint", lead.key)})
    return true
end

return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    if ctx.D.ball_stock_phase and ctx.D.phase == "post_flip" then
        -- the bag is readable at once, but the client latches has_pokeballs only on its next 30-frame
        -- tick (lua/gen3/client.lua latch_balls via tick_fields): wait for that tick instead of racing it
        -- (frlgc ball_gate fr/lg 2026-10-03: the check ran on the first field frame, before any tick)
        if ctx.balls() ~= 20 then return false, "post-flip SYNTH stock was not read back" end
        if not ctx.wait_until(function() return ctx.session.state.has_pokeballs == true end, 10,
                              "post-flip stock latch") then
            return false, "post-flip SYNTH stock was not read back"
        end
        ctx.jlog("BALL_STOCK_READY", {balls=ctx.balls(), active=ctx.session.state.has_pokeballs})
        ctx.hunt = function() return hunt(ctx) end
        local catch = ctx.catch
        ctx.catch = function(label)
            local key, why = catch(label)
            if key then ctx.jlog("BALL_POST_CATCH", {key=key}) end
            return key, why
        end
        return dofile(ctx.D.wt .. "/lua/tests/duo/scenario_gen3_link.lua")(ctx)
    end
    if ctx.balls() ~= 0 or ctx.session.state.has_pokeballs ~= false then return false, "pre-ball fixture gate already active" end
    local flag = ctx.title == "radical_red" and 0x829 or ctx.title == "emerald" and 1048 or 342
    local flag_before = ctx.game_flag(flag)
    if flag_before ~= false then return false, "native Ball reward already consumed or unreadable" end
    local original_hunt, original_catch = ctx.hunt, ctx.catch
    if ctx.title ~= "radical_red" then ctx.hunt = function() return hunt(ctx) end end
    local before = ctx.attempted()
    local ok, why = pre_ball(ctx)
    if not ok then return false, why end
    ctx.frames(120)
    if ctx.sent("capture") > 0 or ctx.sent("no_catch") > 0 or ctx.received("force_faint") > 0 or ctx.received("memorialize") > 0 then
        return false, "pre-ball action produced an encounter or Soul Link death"
    end
    ctx.jlog("BALL_PRE", {balls=ctx.balls(), active=ctx.session.state.has_pokeballs, attempted=ctx.attempted()-before})
    if not ctx.wait_go("ACQUIRE") then return false, "no native acquisition release" end
    local caught
    local function catch_current()
        if caught then return ctx.run_away("after the legal catch") end
        local key, why = original_catch("post-ball", true)
        if not key then ctx.fail("hunt ended " .. tostring(why)) end
        caught = key
        ctx.jlog("BALL_POST_CATCH", {key=key})
        return true
    end
    local function reward()
        if not ctx.wait_until(function() return ctx.session.state.has_pokeballs == true end, 60, "production Ball latch") then
            ctx.fail("native first Ball did not activate client")
        end
        ctx.jlog("BALL_PICKUP", {flag=flag, before=flag_before, after=ctx.game_flag(flag)})
        ctx.jlog("BALL_FLIP", {balls=ctx.balls(), active=ctx.session.state.has_pokeballs})
        if not ctx.wait_go(ctx.D.ball_stock_phase and "SAVE_GATE" or "CAPTURE") then
            ctx.fail("no post-ball phase release")
        end
    end
    if ctx.title == "radical_red" then
        -- The lead has just fainted. This short re-anchor can itself encounter
        -- a wild mon before the parcel helper is loaded; never inherit FIGHT.
        local walked, walk_why = ctx.flee_incidentals("pre-ball return", function()
            ctx.SP.return_to_grass_origin(ctx.cp, "pre-ball")
        end)
        if not walked then return false, "pre-ball return RUN failed: " .. tostring(walk_why) end
        local rr = dofile(ctx.D.wt .. "/lua/tests/gen3_rr_battle_fixture.lua")
        -- Catch the first encounter on the return from Oak; a setup flee here
        -- would dead-zone the first legal area before the intended catch.
        local function flee_before_reward()
            local ok, why = ctx.run_away("parcel before first Ball")
            if not ok then ctx.fail("pre-ball parcel RUN failed: " .. tostring(why)) end
            ctx.jlog("BALL_PARCEL_FLEE", {outcome=ctx.battle_outcome(), balls=ctx.balls()})
            return true
        end
        if not rr.native_ball_gift(ctx.cp, reward, catch_current, flee_before_reward) then
            return false, "RR native parcel reward failed"
        end
    else
        local x = ctx.G.pos(ctx.cp)
        if ctx.title == "emerald" and x ~= 3 then ctx.play.step(ctx.cp, "Left", 6148, true, false) end
        if ctx.title ~= "emerald" and x ~= 4 then ctx.play.step(ctx.cp, "Right", 256, true, false) end
        if ctx.in_battle() then
            local ran, why = ctx.run_away("pre-ball return")
            if not ran then return false, why end
        end
        if not ctx.face(ctx.title == "emerald" and "Up" or "Right") then
            return false, "native Ball pickup facing was not confirmed"
        end
        if not ctx.mash_until(function() return ctx.balls() == 1 end, 120, "A") then return false, "native item-ball pickup did not grant one Ball" end
        if not ctx.play.wait_scene_settled(ctx.cp, 1800) then return false, "native item-ball text did not settle" end
        reward()
    end
    if ctx.D.ball_stock_phase then return ctx.save("native_gate") end
    ctx.catch = function(label)
        if not caught then
            local why
            caught, why = original_catch(label)
            if not caught then return nil, why end
            ctx.jlog("BALL_POST_CATCH", {key=caught})
        end
        return caught
    end
    local link = dofile(ctx.D.wt .. "/lua/tests/duo/scenario_gen3_link.lua")
    local passed, message = link(ctx)
    ctx.catch, ctx.hunt = original_catch, original_hunt
    return passed, message
end
