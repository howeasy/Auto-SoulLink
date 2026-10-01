-- scenario_gen3_native_absent.lua — native_absent_gen3 (RR only): the same VALID durable-trade
-- request to a companion cartridge and to a clean one (Codex C4-6b finding 6; RR-DURABLE redesign).
--
-- tools/e2e_duo.py boots A on the companion build and B on the CLEAN Radical Red dump
-- (`rom_kind`), then queues each a well-formed apply_prepare (orchestrate_native_absent_gen3): this
-- side's slot-1 key as old_key.
--   A (companion): the durable client posts OP_TRADE_PREPARE; the producer runs the native "save
--      the game?" dialog, which this side answers with A (only while producer_phase is PRE_SAVE,
--      profile native.TRADE_BASE + 0x48), and apply_ready ok:true follows the native pre-save.
--      Proof = a native write after the command, gSaveCounter advanced, the producer READY.
--   B (clean): no native part, so the client answers apply_ready ok:false and writes nothing.
-- Neither side saves (`no_save`); the oracle reads the receipts.
local fmt = string.format
local SAVE_COUNTER = 0x03005390   -- gSaveCounter (lua/gen3/trade_journal.lua RELOAD_LAYOUTS.firered_rr)

local function trade_base(ctx)
    local JSON = dofile(ctx.D.wt .. "/lua/json_codec.lua")
    local f = assert(io.open(ctx.D.wt .. "/data/games/gen3_rr/profile.json", "rb"))
    local doc = JSON.decode(f:read("a")); f:close()
    return assert(doc.native and doc.native.TRADE_BASE, "gen3_rr profile has no native.TRADE_BASE")
end
local function u32(ctx, addr)
    local v = 0
    for i = 3, 0, -1 do v = v * 256 + ctx.peek_u8(addr + i) end
    return v
end

return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local before = ctx.writes()
    if not ctx.wait_received("apply_prepare", nil, 300) then
        return false, "the apply_prepare never arrived"
    end
    if ctx.player == "b" then
        if not ctx.wait_until(function() return ctx.sent("apply_ready") > 0 end, 60, "apply_ready") then
            return false, "the clean cartridge never answered the prepare"
        end
        ctx.frames(300)
        local after = ctx.writes()
        ctx.log(fmt("PROBE_SETTLED writes=%d", after))
        if after ~= before then
            return false, fmt("the clean cartridge wrote %d time(s); it must refuse cleanly", after - before)
        end
        if ctx.last_sent("apply_ready").ok ~= false then return false, "the clean cartridge said ok" end
        return true, "clean: valid apply_prepare refused, nothing written"
    end
    local phase_addr = trade_base(ctx) + 0x48          -- producer_phase: 0..5, one byte suffices
    local saves0 = u32(ctx, SAVE_COUNTER)
    local n = 0
    local answered = ctx.wait_until(function()
        if ctx.sent("apply_ready") > 0 then ctx.press({}); return true end
        n = n + 1
        ctx.press(ctx.peek_u8(phase_addr) == 1 and n % 16 < 2 and { A = true } or {})
    end, 300, "the native pre-save and apply_ready")
    ctx.press({})
    ctx.log(fmt("PRESAVE_COUNTER before=%d after=%d", saves0, u32(ctx, SAVE_COUNTER)))
    if not answered then
        return false, "the companion never answered the prepare (phase " .. ctx.peek_u8(phase_addr) .. ")"
    end
    if ctx.last_sent("apply_ready").ok ~= true then return false, "the companion refused the valid prepare" end
    if ctx.writes() == before then return false, "the prepare completed without a native write" end
    ctx.log(fmt("NATIVE_PREPARED phase=%d writes=%d", ctx.peek_u8(phase_addr), ctx.writes() - before))
    return true, "companion: valid apply_prepare answered after the native pre-save"
end
