-- scenario_gen3_reconnect.lua — reconnect_gen3 (C-2 then C-1 on FRLG), by phase.
--
--   initial    both: the runner has linked the slot-1 mons; report RECONNECT_READY. A then
--              idles until the runner kills its EmuHawk; B waits for B_DONE and saves.
--   same_save  A relaunched on its own battery: report the accepted hello, idle until
--              A_DONE_SAME. No save (the runner copies the battery out and compares bytes).
--   wrong_save A relaunched on another OT's save: the server must refuse the hello (the
--              WRONG SAVE hud_show), and the client must write NOTHING -- WRITES is the count of
--              armed-sink write log lines (lua/gen3/writes.lua via entry's log), which is every
--              write the client can make. No save.
return function(ctx)
    if ctx.phase == "same_save" then
        ctx.log("RECONNECT_HELLO same_save count=" .. ctx.sent("hello"))
        if not ctx.wait_go("A_DONE_SAME", 900) then return false, "the runner never closed the same-save leg" end
        return true, "same-save relaunch accepted"
    end
    if ctx.phase == "wrong_save" then
        ctx.log("RECONNECT_HELLO wrong_save count=" .. ctx.sent("hello"))
        if not ctx.wait_until(ctx.wrong_save_hud, 300, "the WRONG SAVE refusal") then
            return false, "the server never refused the wrong save"
        end
        if not ctx.wait_go("A_DONE_WRONG", 900) then return false, "the runner never closed the wrong-save leg" end
        if ctx.writes() ~= 0 then return false, "the refused cartridge wrote " .. ctx.writes() .. " time(s)" end
        return true, "wrong save refused; nothing written"
    end
    if not ctx.wait_go() then return false, "no go-file" end
    local linked = ctx.linked()
    if not (linked and ctx.find(linked)) then return false, "the LINKED key is not in the party" end
    ctx.log("RECONNECT_READY " .. ctx.player)
    if ctx.player == "a" then
        ctx.wait_until(function() return false end, 1800, "the runner to kill this instance")
        return false, "the runner never killed A"
    end
    if not ctx.wait_go("B_DONE", 1800) then return false, "the runner never released B" end
    local ok, why = ctx.save("reconnect")
    if not ok then return false, why end
    return true, "B online through both relaunches"
end
