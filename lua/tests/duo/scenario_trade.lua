-- scenario_trade.lua — MVP scripted trade: the runner cross-injects `apply_trade` with each
-- side's slot-0 party blob (logged here as "MYBLOB <hex>"), bypassing the interactive
-- talk-to-ghost menus (server menu flow is pytest-covered; the full joypad flow stays a USER
-- test). Exercises the production client's pending_trade_apply state machine: blob staging
-- (OP_SET_ENEMY_PARTY), the NATIVE trade scene (OP_TRADE_SCENE 21), and the post-trade key
-- migration. PASS bar: slot 0 holds the PARTNER's pre-trade mon (personality:otId swapped).
return function(ctx)
    local log = ctx.log
    local my_key = ctx.slot_key(0)
    local base = ctx.slot_base(0)
    local hex = {}
    for i = 0, ctx.MON_SIZE - 1 do
        hex[#hex + 1] = string.format("%02X", memory.read_u8(base + i))
    end
    log("MYBLOB " .. table.concat(hex))
    log("my slot0 key=" .. my_key)

    -- The runner waits for MYBLOB from both sides, queues apply_trade to both, then writes
    -- the go-file carrying the partner's key as "PARTNER <key>".
    local go = ctx.wait_go()
    if not go then return false, "no go-file" end
    local partner_key
    for _, l in ipairs(go) do partner_key = l:match("^PARTNER (%S+)$") or partner_key end
    if not partner_key then return false, "go-file missing PARTNER key" end
    log("expecting partner mon " .. partner_key)

    -- The native trade scene runs (field fade -> animation -> return). Wait for slot 0 to
    -- become the partner's mon.
    local swapped = ctx.wait_until(function()
        return ctx.slot_key(0) == partner_key or nil
    end, 21600, "slot0 to become " .. partner_key)
    if not swapped then
        return false, "slot0 still " .. ctx.slot_key(0) .. " (expected " .. partner_key .. ")"
    end
    local level = memory.read_u8(base + ctx.OFF_LEVEL)
    local maxhp = memory.read_u16_le(base + ctx.OFF_MAXHP)
    log(string.format("received partner mon: level=%d maxHP=%d", level, maxhp))
    if maxhp == 0 then return false, "received mon has zero maxHP" end
    -- Give the post-trade migration a moment, then confirm the party didn't corrupt.
    ctx.frames(600)
    if ctx.slot_key(0) ~= partner_key then return false, "slot0 changed again after the trade" end
    return true, "native trade scene swapped slot0 to the partner's mon"
end
