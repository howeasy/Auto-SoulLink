-- scenario_faint.lua — two-instance soul-link faint propagation.
--
-- Runner orchestration: after both instances hello, the runner links A slot0 <-> B slot0
-- (POST /api/inject_link with the MYKEY values), then writes the go-file.
--   A: zero slot0's HP in the overworld -> production client emits `faint` immediately
--      -> server _handle_faint queues force_faint(B's linked key) + memorialize both.
--   B: assert the linked mon's HP -> 0 (force_faint applied), then both sides assert the
--      mon leaves the party (memorialize to THE DEAD box).
-- PASS bars: A = own faint detected + mon memorialized out of the party.
--            B = linked mon HP==0 + mon memorialized out of the party.
return function(ctx)
    local log = ctx.log
    if not ctx.wait_go() then return false, "no go-file" end
    local key0 = ctx.slot_key(0)
    local pre_count = ctx.party_count()
    log("go received; slot0 key=" .. key0 .. " party=" .. pre_count)

    if ctx.player == "a" then
        -- Give the link-inject commands (jingle/msgbox) a moment to drain, then faint slot 0.
        ctx.frames(120)
        memory.write_u16_le(ctx.slot_base(0) + ctx.OFF_HP, 0)
        log("wrote HP=0 to slot0 (" .. key0 .. ")")
    else
        -- B: wait for the partner's faint to arrive as force_faint on our linked slot-0 mon.
        local fainted = ctx.wait_until(function()
            local s = ctx.find_slot_by_key(key0)
            if s and memory.read_u16_le(ctx.slot_base(s) + ctx.OFF_HP) == 0 then return true end
            -- Already memorialized out of the party counts too (we may poll late at 400x).
            if not ctx.find_slot_by_key(key0) then return true end
            return nil
        end, 14400, "force_faint on " .. key0)
        if not fainted then return false, "linked mon never fainted" end
        log("linked mon fainted (or already memorialized)")
    end

    -- Both sides: the fainted mon must leave the party (memorialize) and the count drop by 1.
    local gone = ctx.wait_until(function()
        return ctx.find_slot_by_key(key0) == nil or nil
    end, 14400, "memorialize of " .. key0)
    if not gone then return false, "mon never memorialized out of the party" end
    local post_count = ctx.party_count()
    log(string.format("memorialized: count %d -> %d", pre_count, post_count))
    if post_count ~= pre_count - 1 then
        return false, string.format("party count %d (expected %d)", post_count, pre_count - 1)
    end
    return true, "faint propagated + memorialized"
end
