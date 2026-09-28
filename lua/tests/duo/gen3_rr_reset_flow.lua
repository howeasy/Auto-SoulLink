-- Harness-only phase wrapper around the production RR NPC trade driver.
-- An intentional partial result is a clean client.exit by duo_gen3_main.lua, never a
-- successful trade outcome. The final reset row can PASS only after cold-reload PYDEC.
local F = {}

local function marker(ctx, tag, value)
    if ctx.jlog then ctx.jlog(tag, value)
    else ctx.log(tag .. " " .. tostring(value and value.token or "")) end
end

function F.initial(ctx, d)
    assert(type(d.trade_driver) == "function", "RR trade driver required")
    local wait, go = ctx.wait_until, ctx.wait_go
    local interrupted, completed = nil, nil
    ctx.wait_until = function(pred, secs, what)
        if what == "trade_done" and d.interrupt then
            return wait(function()
                local witness = d.probe and d.probe()
                if witness then
                    interrupted = witness
                    marker(ctx, "RESET_COMMIT_ENTERED", witness)
                    return true -- stop pressing A; the original driver sees no trade_done
                end
                return pred()
            end, secs, what)
        end
        return wait(pred, secs, what)
    end
    ctx.wait_go = function(name, secs)
        if name == "SAVE" and d.stop_before_manual_save then
            local report = ctx.last_sent("trade_done")
            if report and report.uncertain ~= true and type(report.token) == "string"
               and report.token ~= "" and type(report.new_key) == "string"
               and report.new_key ~= "" then
                local proof = d.validate_success and d.validate_success(report)
                if proof then
                    completed = proof
                    marker(ctx, "RESET_NATIVE_SUCCESS_NO_MANUAL_SAVE", proof)
                end
            end
            return false -- never allow a runner SAVE in this scenario
        end
        return go(name, secs)
    end
    local ran, ok, why = pcall(d.trade_driver, ctx)
    ctx.wait_until, ctx.wait_go = wait, go
    if not ran then return false, "reset trade driver raised: " .. tostring(ok) end
    if interrupted then
        if ok or completed or ctx.sent("trade_done") > 0 then
            return false, "reset interruption leaked a trade completion"
        end
        marker(ctx, "RESET_PARTIAL_COMMIT_EXIT", interrupted)
        return false, "EXPECTED_RESET_PARTIAL_COMMIT"
    end
    if completed then
        if ok or ctx.sent("trade_done") == 0 then
            return false, "reset native-success phase lacked a concrete trade_done"
        end
        marker(ctx, "RESET_NATIVE_SUCCESS_EXIT", completed)
        return false, "EXPECTED_NATIVE_SUCCESS_NO_MANUAL_SAVE"
    end
    return false, "reset window not witnessed: " .. tostring(why or ok)
end

function F.reload(ctx, d)
    local key = ctx.D and ctx.D.expected_key
    if type(key) ~= "string" or key == "" then return false, "reset reload expected key missing" end
    local party = ctx.party() or {}
    local found = 0
    for _, mon in ipairs(party) do if mon.key == key then found = found + 1 end end
    if found ~= 1 then return false, "reset battery does not hold expected key exactly once" end
    local counter = d.counter and d.counter()
    if type(d.expected_counter) ~= "number" or d.expected_counter < 0
       or type(counter) ~= "number" or counter ~= d.expected_counter then
        return false, "reset flash counter unavailable or changed"
    end
    marker(ctx, "RESET_RELOADED", {side=ctx.player, key=key, counter=counter})
    if d.require_after_reset then
        local report = ctx.wait_until(function()
            local sent = ctx.last_sent("trade_done")
            if sent and sent.uncertain == true and sent.after_reset == true
               and sent.token == d.token then return sent end
        end, 180, "production after_reset trade_done")
        if not report then return false, "production after_reset uncertainty missing or wrong token" end
        marker(ctx, "RESET_AFTER_RESET", {side=ctx.player, token=report.token, counter=counter})
    end
    return true, "cold-reloaded expected native save without runner SAVE"
end

return F
