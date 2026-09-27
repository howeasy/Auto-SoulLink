-- O-33 PID setup is explicitly logged. All four catches, both pair formations
-- and both cartridge saves follow the production path through normal input.
return function(ctx)
    if not ctx.wait_go() then return false, "no shiny row GO" end
    local first, why = ctx.catch("ordinary baseline")
    if not first then return false, "hunt ended " .. tostring(why) end
    local cap = ctx.last_sent("capture")
    if not cap or cap.key ~= first then return false, "baseline capture has no native TX" end
    ctx.log("CAUGHT " .. first)
    ctx.jlog("SHINY_BASELINE", cap)
    if not ctx.wait_go("BASE_LINKED") then return false, "baseline pair never linked" end
    if ctx.received("box_mon", first) > 0 and not ctx.wait_sent("sync_retrieve_done", first, 300) then
        return false, "baseline capture never retrieved"
    end
    if not ctx.observe_returned(first) then return false, "baseline capture absent from party" end
    local second
    if ctx.player == "a" then
        if not ctx.hunt("shiny") or not ctx.wild_ready("shiny") then return false, "no shiny setup encounter" end
        local setup = dofile(ctx.D.wt .. "/lua/tests/duo/shiny_setup.lua")
        local before, bad = setup.snapshot(ctx)
        if not before then return false, bad end
        ctx.jlog("SHINY_PREIMAGE", before)
        local packet = ctx.wait_until(function() return ctx.go_value("SHINY_SETUP") end, 120, "shiny setup manifest")
        if not packet then return false, "no disclosed shiny setup" end
        local expected, refused = setup.apply(ctx, packet)
        if not expected then return false, refused end
        ctx.jlog("SYNTH_SHINY_APPLIED", packet)
        second, why = ctx.catch("shiny", true)
        if not second then return false, "hunt ended " .. tostring(why) end
        if second ~= expected then return false, "native shiny capture key differs from setup" end
        cap = ctx.last_sent("capture")
        if not cap or cap.key ~= second then return false, "shiny capture has no native TX" end
        ctx.jlog("SHINY_CAUGHT", cap)
        if not ctx.wait_go("BONUS_LINKED") then return false, "no native bonus pair" end
    else
        if not ctx.wait_go("BONUS_GO") then return false, "no pending shiny bonus" end
        second, why = ctx.catch("bonus partner")
        if not second then return false, "hunt ended " .. tostring(why) end
        cap = ctx.last_sent("capture")
        if not cap or cap.key ~= second or second == first then return false, "bonus capture has no new native TX" end
        ctx.jlog("BONUS_CAUGHT", cap)
        if not ctx.wait_go("BONUS_LINKED") then return false, "no native bonus pair" end
    end
    for _, key in ipairs({first, second}) do
        if ctx.received("force_faint", key) > 0 or ctx.received("memorialize", key) > 0 then
            return false, "shiny row catch was rejected"
        end
        if not ctx.observe_returned(key) then return false, "shiny row catch absent from party" end
    end
    ctx.jlog("SHINY_READY", {first=first, second=second})
    if not ctx.wait_go("SAVE") then return false, "no shiny row SAVE" end
    return ctx.save("shiny bonus")
end
