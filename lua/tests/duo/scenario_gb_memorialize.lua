-- scenario_gb_memorialize.lua — a dead pair is buried in the GB memorial box.
--
-- The rule: once BOTH halves of a pair are dead, the server queues `memorialize` to each
-- player, and the client moves the corpse out of the party into the dedicated graveyard
-- box, written straight to SRAM at a fixed CartRAM offset. WHICH box is the generation's
-- own business — Box 12 on Gen 1, Box 14 on Gen 2 — so this scenario never names one: it
-- asks the profile via M.getMemorialBoxCount() and would silently pass on the wrong box if
-- it hardcoded an index here.
--
-- Worth an end-to-end test for three reasons:
--
--   * The deferred-command queue this rides on is the one that used to bind to a nil
--     global; `memorialize` was one of the three commands that crashed the client outright.
--   * The docs disagreed about where Gen 1 even buries mons — .github/copilot-instructions
--     said "current active box, no dedicated memorial box" while the code and the data
--     README said Box 12. Only a live run settles it.
--   * memorialize is ACKed: the server holds the key in pending_memorials until the client
--     replies memorialize_done, and a missing ack means an empty Memorial page forever plus
--     a command that re-queues on every reconnect.
--
-- Both sides carry a filler (see duo_gb_main) because a mon cannot be moved out of a
-- one-mon party.
return function(ctx)
    local log = ctx.log
    local M = ctx.M
    if not ctx.wait_go() then return false, "no go-file" end

    local key0 = ctx.slot_key(0)
    if not key0 then return false, "no mon in slot 0" end
    if ctx.party_count() < 2 then
        return false, "need a filler mon (party=" .. ctx.party_count() .. ")"
    end
    local box_before = M.getBoxCount()
    log(string.format("go received; linked key=%s party=%d box=%d",
                      key0, ctx.party_count(), box_before))

    -- Both sides kill their own half. The server needs both dead before the pair is
    -- memorialized, and A's faint alone would only force_faint B.
    ctx.frames(120)
    ctx.write_hp(0, 0)
    log("killed our half of the pair")

    -- The corpse must LEAVE THE PARTY. That is the observable end of the whole chain:
    -- faint -> server marks the pair dead -> memorialize queued -> deferred until a safe
    -- overworld frame -> depositMemorialMon writes the memorial box -> memorialize_done acked.
    local gone = ctx.wait_until(function()
        return ctx.find_slot_by_key(key0) == nil or nil
    end, 14400, "memorialize to remove the corpse from the party")
    if not gone then
        return false, "dead mon never left the party (memorialize never applied)"
    end

    -- And it must be STORED, not deleted. The memorial box is written directly to SRAM
    -- rather than through the active-box path, so the active box count may not move
    -- — read the memorial box itself.
    local buried = ctx.wait_until(function()
        if M.GENERATION == 1 then
            if M.verifyMemorialKey and M.verifyMemorialKey(key0) then return key0 end
            return nil
        end
        local n = M.getMemorialBoxCount and M.getMemorialBoxCount() or nil
        if not n or n <= 0 then return nil end
        -- Gen 2 box structures do not carry HP; retain that generation's own
        -- reader, but require this exact identity rather than any nonempty box.
        local matches = 0
        for slot = 0, n - 1 do
            local mon = M.readMemorialBoxSlot and M.readMemorialBoxSlot(slot)
            if mon and mon.key == key0 then matches = matches + 1 end
        end
        return matches == 1 and key0 or nil
    end, 3600, "the exact corpse key to appear uniquely in the memorial box")
    -- FATAL. This was a warning, which made the scenario pass whenever the corpse merely
    -- left the party — a condition depositMemorialMon's fall back to depositPartyMon also
    -- satisfies, i.e. the mon going to the ordinary box instead of the graveyard. "Buried in
    -- the graveyard box" is the rule under test; if we cannot confirm it, we have not tested it.
    if not buried then
        return false, "corpse left the party but its exact key was not verified in the memorial box"
    end
    log("verified exact memorial key: " .. buried)

    log("dead pair memorialized")
    ctx.wait_partner_done(7200)
    return true, "memorialized " .. key0
end
