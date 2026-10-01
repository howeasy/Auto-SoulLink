-- T5: native NPC/selection/offer and native PREPARE/scene/save, with independent receipts.
return function(ctx)
    local h = assert(ctx.native_candidate,"T5 candidate carrier not installed")
    h.start(ctx)
    if ctx.phase ~= "initial" then
        if not ctx.wait_until(function() return ctx.find(ctx.D.expected_key) end,120,"reloaded trade identity") then
            return false,"trade identity absent after cold reload"
        end
        h.reloaded(ctx)
        return true,"cold reload observed; initial native-carrier receipts remain required"
    end
    if not ctx.wait_until(function() return h.ready end,120,"server acknowledged native trade capability") then
        h.diagnose("capability hello")
        return false,"candidate capability hello not acknowledged"
    end
    ctx.log("FR_TRADE_CAPABLE")
    if not ctx.wait_go() then return false,"T5 GO missing" end
    local driver=dofile(ctx.D.wt.."/lua/tests/duo/gen3_trade_driver.lua")
    driver.select(ctx,h)
    if ctx.D.native_decline then
        local done = ctx.wait_until(function()
            if ctx.player == "a" then return h.declined end
            return ctx.last_sent("menu_result") and ctx.last_sent("menu_result").choice == 0
        end,120,"native decline")
        if not done then return false,"decline was not acknowledged" end
        ctx.frames(120)
        h.flush_decline()
    else
        -- Only ordinary A inputs drive the native consent/pre-save and scene.
        -- No native witness or party/save bytes are synthesized by this driver.
        local done = ctx.wait_until(function()
            if h.final_seen() then joypad.set({});return true end
            local frame = emu.framecount()
            local phase = memory.read_u32_le(h.manifest.native.BASE+0x48,"System Bus")
            joypad.set((phase == 1 or phase == 3) and frame % 16 < 2 and {A=true} or {})
            return false
        end,900,"native durable trade and server committed final")
        joypad.set({})
        if not done then h.diagnose("native/server final");return false,"native/server trade did not commit" end
    end
    h.capture_final(ctx)
    ctx.log("FR_TRADE_READY_FOR_RELOAD")
    if not ctx.wait_go("RELOAD",180) then return false,"T5 reload release missing" end
    return true,"initial native trade leg; cold reload still required"
end
