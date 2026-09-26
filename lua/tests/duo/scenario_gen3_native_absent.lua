-- scenario_gen3_native_absent.lua — native_absent_gen3 (RR only): the same VALID trade to a
-- companion cartridge and to a clean one (Codex C4-6b finding 6).
--
-- tools/e2e_duo.py boots A on the companion build and B on the CLEAN Radical Red dump
-- (`rom_kind`), then queues each a well-formed apply_trade (orchestrate_native_absent_gen3): the
-- partner fixture's own slot-1 party record as blob_hex, this side's slot-1 key as old_key.
--   A (companion): the client queues it for the native trade (lua/gen3/client.lua C.apply_trade),
--      and the stage (OP_SET_ENEMY_PARTY through the armed native window) must be ACKed by the
--      patch: the FSM only leaves "stage" for the scene/readback phases when the stage transfer
--      completed. Proof = native writes AND the FSM past "stage" (NATIVE_STAGED), or trade_done.
--   B (clean): no native part, so the client refuses ("no trade path on this cartridge") and
--      writes nothing at all (WRITES stays 0).
-- Neither side saves (`no_save`); the oracle reads the receipts.
local fmt = string.format
local PAST_STAGE = { scene = true, scene_lost = true, readback = true }

return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local before = ctx.writes()
    if not ctx.wait_received("apply_trade", nil, 300) then
        return false, "the apply_trade never arrived"
    end
    if ctx.player == "b" then
        ctx.frames(300)
        local after = ctx.writes()
        ctx.log(fmt("PROBE_SETTLED writes=%d", after))
        if after ~= before then
            return false, fmt("the clean cartridge wrote %d time(s); it must refuse cleanly", after - before)
        end
        return true, "clean: valid apply_trade refused, nothing written"
    end
    local last
    local staged = ctx.wait_until(function()
        local phase = ctx.trade_phase()
        if phase ~= last then ctx.log("TRADE_PHASE " .. tostring(phase)); last = phase end
        if PAST_STAGE[phase] or ctx.sent("trade_done") > 0 then return phase or "done" end
        if phase == "fallback" then return "fallback" end
        return nil
    end, 300, "the native stage to complete")
    if not staged then return false, "the companion never completed the native stage" end
    if staged == "fallback" then return false, "the native stage failed (the FSM fell back)" end
    if ctx.writes() == before then return false, "the stage completed without a native write" end
    ctx.log(fmt("NATIVE_STAGED phase=%s writes=%d", staged, ctx.writes() - before))
    return true, "companion: valid apply_trade staged natively"
end
