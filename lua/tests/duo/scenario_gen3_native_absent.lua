-- scenario_gen3_native_absent.lua — native_absent_gen3 (RR only, PLAN §14 P5, card C5-5).
--
-- tools/e2e_duo.py's `rom_kind` boots B on the CLEAN Radical Red dump (no companion patch) and A
-- on the usual companion build (GAMES["gen3_rr_new"]._gen3_rom_kind). Both instances receive the
-- SAME apply_trade debug probe (orchestrate_native_absent_gen3, /api/debug/queue_command) once
-- ready. lua/gen3/client.lua:820-824 has no native.apply_trade to dispatch to on EITHER side yet
-- (trade is a later card, not this one): both log a local refusal and send no wire reply and no
-- write. That refusal text is asserted by the Python oracle (assert_native_absent_gen3_saved)
-- directly against the receipt this file writes -- this scenario only has to prove the probe
-- arrived and nothing wrote or crashed.
return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local before = ctx.writes()
    if not ctx.wait_received("apply_trade", nil, 300) then
        return false, "the apply_trade probe never arrived"
    end
    ctx.frames(60)
    local after = ctx.writes()
    if after ~= before then
        return false, "apply_trade wrote " .. (after - before) .. " byte(s); it must refuse cleanly"
    end
    ctx.log("PROBE_SETTLED writes=" .. after)
    return true, "apply_trade probe delivered, no write"
end
