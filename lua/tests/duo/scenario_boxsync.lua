-- scenario_boxsync.lua — native PC storage round-trip through the REAL server loop, both sides.
--
-- Runner orchestration: after go, queues `box_mon {slot-1 key}` to BOTH players (native
-- OP_DEPOSIT_MON via exec_box_mon); each side asserts the mon leaves the party and logs
-- "DEPOSIT_DONE"; the runner then queues `party_mon {same key}` WITHOUT cached stats — the
-- native OP_WITHDRAW_MON recomputes stats, and a statless command is exactly the shape that
-- the WS1 zero-stat guard protects if the native path ever falls back to Lua.
-- PASS bar: mon back in the party with level > 0 and maxHP > 0 (engine-recomputed, never zero).
return function(ctx)
    local log = ctx.log
    if not ctx.wait_go() then return false, "no go-file" end
    local key = ctx.slot_key(1)
    local pre_count = ctx.party_count()
    log("go received; depositing slot1 key=" .. key .. " party=" .. pre_count)

    -- Deposit: the runner queues box_mon right after go; wait for the mon to leave the party.
    local gone = ctx.wait_until(function()
        return ctx.find_slot_by_key(key) == nil or nil
    end, 14400, "deposit of " .. key)
    if not gone then return false, "mon never deposited" end
    if ctx.party_count() ~= pre_count - 1 then
        return false, string.format("post-deposit count %d (expected %d)",
            ctx.party_count(), pre_count - 1)
    end
    log("DEPOSIT_DONE " .. key)

    -- Withdraw: runner queues party_mon (statless) once it sees DEPOSIT_DONE.
    local slot = ctx.wait_until(function()
        return ctx.find_slot_by_key(key)
    end, 14400, "withdraw of " .. key)
    if not slot then return false, "mon never withdrawn" end
    local base = ctx.slot_base(slot)
    local level = memory.read_u8(base + ctx.OFF_LEVEL)
    local maxhp = memory.read_u16_le(base + ctx.OFF_MAXHP)
    log(string.format("withdrawn to slot %d: level=%d maxHP=%d", slot, level, maxhp))
    if level == 0 or maxhp == 0 then
        return false, string.format("ZERO-STAT withdraw (level=%d maxHP=%d)", level, maxhp)
    end
    if ctx.party_count() ~= pre_count then
        return false, string.format("post-withdraw count %d (expected %d)",
            ctx.party_count(), pre_count)
    end
    return true, "deposit + statless withdraw round-trip ok"
end
