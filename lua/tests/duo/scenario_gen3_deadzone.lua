-- scenario_gen3_deadzone.lua — deadzone_gen3 (D-3 on FRLG).
--
-- A: one wild encounter on Route 1, then RUN (the action cursor steered to RUN(3) through
--    HandleInputChooseAction's bit toggles). The client sends a species-bearing no_catch and the
--    server locks route_1 as a dead zone; the runner releases B only once /api/status says so
--    (assert_dead_zone_new, shared with Gen 1).
-- B: catches on the locked route. The server refuses the capture (force_faint + memorialize);
--    the HP-0 watcher logs FAINTED <key> when the client's write lands, RETIRED <key> follows
--    the memorialize_done. Both save.
return function(ctx)
    if ctx.player == "a" then
        if not ctx.wait_go() then return false, "no go-file" end
        if not ctx.hunt("deadzone a") then return false, "no wild encounter" end
        local ok, why = ctx.run_away("deadzone a")
        if not ok then return false, why end
        if not ctx.wait_sent("no_catch", nil, 120) then return false, "the client sent no no_catch" end
        local msg = ctx.last_sent("no_catch") or {}
        ctx.log(ctx.fmt("NO_CATCH area=%s species=%s", tostring(msg.area_id), tostring(msg.species_id)))
        ok, why = ctx.save("deadzone")
        if not ok then return false, why end
        return true, "ran; route locked"
    end
    ctx.hp0_tag = "FAINTED"
    if not ctx.wait_go(nil, 1800) then return false, "no go-file" end
    local key, why = ctx.catch("deadzone b")
    if not key then return false, "hunt ended " .. tostring(why) end
    ctx.log("CAUGHT " .. key)
    if not ctx.wait_until(function() return ctx.hp0(key) end, 300, "the refused capture at HP 0") then
        return false, "the dead-zone capture " .. key .. " was never force-fainted"
    end
    if not ctx.wait_sent("memorialize_done", key, 600) then return false, "no memorialize_done for " .. key end
    ctx.log("RETIRED " .. key)
    local ok, why2 = ctx.save("deadzone")
    if not ok then return false, why2 end
    return true, "dead-zone capture " .. key .. " retired"
end
