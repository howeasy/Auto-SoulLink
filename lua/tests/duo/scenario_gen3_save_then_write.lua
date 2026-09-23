-- scenario_gen3_save_then_write.lua — save_then_write_gen3: the live regression for the stale
-- sSaveDialogCB defect (C4-6r PRODUCT FINDING; the checkpoint fix is C4-SAVE).
--
-- pret start_menu.c: sSaveDialogCB (line 71) is assigned at every save-dialog step and never
-- reset to NULL, so after an in-game save it rests on SaveDialogCB_ReturnSuccess. The overworld
-- checkpoint's `save_dialog_cb == 0` predicate then refused every SLink write for the rest of the
-- session. This scenario proves the defect is EXERCISED (the pointer is stale on an idle field)
-- and that a keyed write still LANDS there -- which it only does once C4-SAVE drops that clause.
--
--   A: START-menu save (witness 1) -> idle overworld -> STALE_SAVE_DIALOG (ctx.stale_predicates
--      names save_dialog_cb) -> WRITE_PROBE_READY <linked> -> the runner queues box_mon ->
--      a fresh keyed RX -> the stats_cache ACK within the bound, no box_mon_failed (no partial)
--      -> BOXED_OBSERVED -> WRITE_LANDED -> a second save (witness 2).
--   B: idles (no save).
-- On today's pack step "lands" fails with a named reason: the hold's own clause.
local fmt = string.format
local LAND_SECS = 60

local function a_side(ctx, linked)
    local ok, why = ctx.save("save_then_write_1")
    if not ok then return false, "the first save: " .. tostring(why) end
    if not ctx.wait_until(function()
        return ctx.G.pred_ok(ctx.cp, "script_context_status") and ctx.G.pred_ok(ctx.cp, "field_controls_locked")
               and ctx.on_field()
    end, 30, "an idle overworld after the save") then
        return false, "the field never went idle after the save"
    end
    ctx.frames(60)
    local stale = ctx.stale_predicates()
    local save_cb
    for _, s in ipairs(stale) do if s:find("^save_dialog_cb=") then save_cb = s end end
    ctx.log(fmt("STALE_SAVE_DIALOG %s", tostring(save_cb)))
    if not save_cb then
        return false, "sSaveDialogCB is clear after the save: this run does not exercise the defect"
    end
    local rx0 = ctx.received("box_mon", linked)
    ctx.log(fmt("WRITE_PROBE_READY %s %s", linked, (ctx.center_state())))
    if not ctx.wait_until(function() return ctx.received("box_mon", linked) > rx0 end, 600,
                          "RX box_mon " .. linked .. " after WRITE_PROBE_READY") then
        return false, "the runner never queued box_mon " .. linked
    end
    if not ctx.wait_sent("stats_cache", linked, LAND_SECS) then
        local held = ctx.queued("box_mon", linked)
        local clause = held and held.why and held.why:match("forbidden state: (%S+)$")
        return false, fmt("the keyed box_mon stayed HELD on an idle field after the save for %ds "
                          .. "(clause %s: %s)", LAND_SECS, tostring(clause), tostring(held and held.why))
    end
    if ctx.sent("box_mon_failed", linked) > 0 then return false, "box_mon_failed: a refused or partial write" end
    if not ctx.observe_boxed(linked) then return false, linked .. " was never read back boxed" end
    ctx.log(fmt("WRITE_LANDED box_mon %s %s", linked, (ctx.center_state())))
    ok, why = ctx.save("save_then_write_2")
    if not ok then return false, "the second save: " .. tostring(why) end
    return true, "a keyed box_mon landed on an idle field after an in-game save"
end

return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local linked = ctx.linked()
    local mon = linked and ctx.find(linked)
    if not mon or mon.slot ~= 1 then return false, "the LINKED key must be party slot 1" end
    if ctx.player == "b" then
        if not ctx.wait_until(ctx.partner_done, 1100, "A's result") then return false, "A never finished" end
        return true, "idle (save_then_write drives only A)"
    end
    return a_side(ctx, linked)
end
