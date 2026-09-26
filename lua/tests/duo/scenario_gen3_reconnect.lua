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
        -- the live party + PC bytes as the phase starts; the sink's ATTEMPT counter (writes.lua
        -- `attempted`, counted before each external write) covers everything since boot
        local party0, box0 = ctx.mutable_bytes()
        ctx.log("RECONNECT_HELLO wrong_save count=" .. ctx.sent("hello"))
        if not ctx.wait_until(ctx.wrong_save_hud, 300, "the WRONG SAVE refusal") then
            return false, "the server never refused the wrong save"
        end
        if not ctx.wait_go("A_DONE_WRONG", 900) then return false, "the runner never closed the wrong-save leg" end
        if ctx.writes() ~= 0 then return false, "the refused cartridge wrote " .. ctx.writes() .. " time(s)" end
        -- C-1's stronger claim (Codex receipt audit 2026-09-23): no byte was even ATTEMPTED, and
        -- the live party and PC RAM are what they were, not just "no completed write log line"
        local attempted = ctx.attempted()
        local party1, box1 = ctx.mutable_bytes()
        local party_same, box_same = party1 == party0, box1 == box0
        ctx.log(string.format("WRONG_SAVE_ZERO attempted=%d writes=%d party=%s box=%s", attempted,
                              ctx.writes(), party_same and "unchanged" or "CHANGED",
                              box_same and "unchanged" or "CHANGED"))
        if attempted ~= 0 then return false, "the refused cartridge ATTEMPTED " .. attempted .. " byte(s)" end
        if not (party_same and box_same) then return false, "the refused cartridge's live party/PC RAM changed" end
        return true, "wrong save refused; nothing attempted, party and PC RAM unchanged"
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
