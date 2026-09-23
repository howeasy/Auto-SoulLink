-- scenario_gen3_whiteout.lua — whiteout_gen3: one whiteout, one rebuild from both PCs.
--
-- The runner links both slot-1 mons. A (battle fixture) deposits its half at the Viridian PC by
-- hand; the server mirrors box_mon to B (town fixture), whose client deposits it. Both report
-- DEPOSITED_FOR_REBUILD and the runner writes BOTH_BOXED only once the SERVER's own party_keys
-- drop both keys (assert_whiteout_both_boxed, shared with Gen 1): the rebuild picks only pairs
-- boxed on both sides (server/state.py _plan_rebuild). A then walks back to the Route 1 grass
-- with its lone starter and chooses only a no-damage move until it faints -> whiteout. The
-- client sends `whiteout`; the server answers rebuild_start + party_mon to A and party_mon to B
-- (server/state.py _queue_rebuild_commands); both clients withdraw at their checkpoints, A gets
-- rebuild_done, and both save. A whiteout during the walk itself counts: it is the same event.
local function a_side(ctx, linked)
    ctx.walk_to_pc("whiteout a")
    local gone, why = ctx.pc_deposit("whiteout a deposit")
    if gone ~= linked then return false, "the deposit moved " .. tostring(gone or why) .. ", not " .. linked end
    ctx.log("DEPOSITED_FOR_REBUILD " .. linked)
    if not ctx.wait_go("BOTH_BOXED", 1800) then return false, "the runner never wrote BOTH_BOXED" end
    local ok, err = ctx.try(function()
        ctx.walk_pc_to_grass("whiteout a")
        if not ctx.hunt("whiteout a") then error("no wild encounter", 0) end
        local lead = (ctx.party() or {})[1]
        if not lead then error("party unreadable in battle", 0) end
        local fainted, lwhy = ctx.lose_active(lead.key, "whiteout a")
        if not fainted then error("the lone starter did not faint: " .. tostring(lwhy), 0) end
    end)
    if not ok and not (type(err) == "table" and err.whiteout) then
        return false, "the whiteout run: " .. tostring(err)
    end
    if not ctx.mash_until(function() return ctx.sent("whiteout") > 0 end, 180, "A") then
        return false, "the client never sent whiteout"
    end
    ctx.play.wait_scene_settled(ctx.cp, 6000)          -- the heal-location landing and its text
    ctx.log("WHITED_OUT at " .. ctx.play.where(ctx.cp))
    if not ctx.wait_received("party_mon", linked, 900) then return false, "no rebuild party_mon" end
    if not ctx.wait_sent("sync_retrieve_done", linked, 600) then return false, "the rebuild withdraw was not acknowledged" end
    if not ctx.wait_received("rebuild_done", nil, 300) then return false, "no rebuild_done" end
    if not ctx.find(linked) then return false, linked .. " is not back in the party" end
    return true
end

local function b_side(ctx, linked)
    if not ctx.wait_received("box_mon", linked, 1800) then return false, "no mirrored box_mon" end
    if not ctx.wait_sent("stats_cache", linked, 300) then return false, "the mirrored deposit was not acknowledged" end
    ctx.log("MIRROR_DEPOSITED " .. linked)
    ctx.log("DEPOSITED_FOR_REBUILD " .. linked)
    if not ctx.wait_go("BOTH_BOXED", 1800) then return false, "the runner never wrote BOTH_BOXED" end
    if not ctx.wait_received("party_mon", linked, 1800) then return false, "no rebuild party_mon" end
    if not ctx.wait_sent("sync_retrieve_done", linked, 600) then return false, "the rebuild withdraw was not acknowledged" end
    if not ctx.find(linked) then return false, linked .. " is not back in the party" end
    ctx.log("MIRROR_WITHDRAWN " .. linked)
    return true
end

return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local linked = ctx.linked()
    local mon = linked and ctx.find(linked)
    if not mon or mon.slot ~= 1 then return false, "the LINKED key must be party slot 1" end
    local ok, why
    if ctx.player == "a" then ok, why = a_side(ctx, linked) else ok, why = b_side(ctx, linked) end
    if not ok then return false, why end
    ctx.frames(60)
    ok, why = ctx.save("whiteout")
    if not ok then return false, why end
    return true, "pair " .. linked .. " rebuilt after the whiteout"
end
