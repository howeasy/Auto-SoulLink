-- Harness-only RR trade wrapper. The runner owns an external OS guard handle; this module
-- observes the production client's actual tick fields while that handle is held and after it
-- is released, then drives the unchanged native trade scenario in the same two EmuHawk PIDs.
local trade = dofile((debug.getinfo(1, "S").source:match("@(.+[/\\])") or "") .. "scenario_gen3_trade.lua")

return function(ctx)
    if not ctx.rr then return false, "journal lock probe needs the RR companion" end
    if not ctx.wait_go() then return false, "no initial GO" end
    local phase, hidden, recovered = "arm", false, false
    local tick_fields = ctx.session.driver.tick_fields
    ctx.session.driver.tick_fields = function(...)
        local fields = tick_fields(...)
        if type(fields) == "table" then
            if phase == "hold" and not hidden and fields.party_hidden == true then
                hidden = true
                ctx.log(ctx.fmt("JOURNAL_PROBE_HIDDEN player=%s frame=%d", ctx.player, emu.framecount()))
            elseif phase == "release" and hidden and not recovered
                   and fields.party_hidden ~= true and type(fields.party) == "table" and #fields.party > 0 then
                recovered = true
                ctx.log(ctx.fmt("JOURNAL_PROBE_RECOVERED player=%s frame=%d party=%d",
                                ctx.player, emu.framecount(), #fields.party))
            end
        end
        return fields
    end
    ctx.log(ctx.fmt("JOURNAL_PROBE_ARMED player=%s frame=%d", ctx.player, emu.framecount()))
    if not ctx.wait_go("LOCK_HELD", 120) then return false, "external OS guard was never held" end
    phase = "hold"
    if not ctx.wait_until(function() return hidden end, 120, "hidden tick under OS guard") then
        return false, "no production hidden tick while OS guard was held"
    end
    if not ctx.wait_go("LOCK_RELEASED", 120) then return false, "external OS guard was not released" end
    phase = "release"
    if not ctx.wait_until(function() return recovered end, 120, "visible tick after guard release") then
        return false, "party did not recover in the same client session"
    end
    if not ctx.wait_go("TRADE_GO", 120) then return false, "runner never released native trade" end
    return trade(ctx)
end
