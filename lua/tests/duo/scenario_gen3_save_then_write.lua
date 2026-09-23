-- scenario_gen3_save_then_write.lua — save_then_write_gen3: the live regression for the stale
-- sSaveDialogCB defect (C4-6r PRODUCT FINDING; the checkpoint fix is C4-SAVE), plus G4 draft
-- §3.2 rows 1 and 9 (C4-SAVE-ROWS, docs/gen3/research/c4_save_rows_design_2026-09-23.md).
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
--      -> BOXED_OBSERVED -> WRITE_LANDED -> a second save (witness 2) -> the menu leg below.
--      Each save logs SAVE_DISMISSAL: which of the two ways its success box closed.
--   Menu leg, one START-menu session after the second save (no further save is written, so the
--   battery keeps save 2 -- the linked mon boxed -- for the persisted half):
--      row 9: the cursor rests OFF the SAVE row -> DIALOG_WITNESS_FALSE (the stale pointer is
--             non-zero, the live-task witness is false) -> CONTROL_LIVE dialog_witness -> the
--             runner queues party_mon -> CONTROL_REFUSED dialog_witness (the witness re-read on
--             every held frame);
--      row 1: SAVE -> YES -> the overwrite prompt -> SAVE_CANCEL_PROMPT, the same probe held
--             there -> B cancels back to the menu -> SAVE_CANCEL_MENU_REDRAWN, held again ->
--             CONTROL_RELEASED save_cancel -> B closes the menu -> the party_mon lands in the
--             first free frame (sync_retrieve_done + read back in the party; its write-frame
--             witness SAVE_CANCEL_WRITE_FRAME, field free and no START task) and
--             SAVE_CANCEL_FIELD_FREE, which may log AFTER the ACK of that same frame.
--   B: idles (no save).
-- On today's pack step "lands" fails with a named reason: the hold's own clause.
local fmt = string.format
local LAND_SECS = 60
-- start_menu.c's action-id enum: SAVE = 4 (gen3_boot_check.lua:58-64 MENU_ACTION_SAVE)
local MENU_ACTION_SAVE = 4

--- ctx.save, then WHICH dismissal closed its success box (the open item of the design, §6).
--- start_menu.c: sSaveDialogDelay (:72) is set to 60 by SaveDialogCB_PrintSaveResult (:813 ->
--- :668) and decremented once per SaveDialog_Wait60FramesOrAButtonHeld call (:673), reached only
--- from SaveDialogCB_ReturnSuccess once the SE is over (:829). A held A returns TRUE with it still
--- > 0 (:674-677); otherwise it returns TRUE when it hits 0 (:679) -- an A held on that very call
--- ends it at the same moment, so 0 reads "the 60-call wait ran out". Nothing else in the saving
--- path touches it (:691-704 is the error path's own wait), so after the box closed it is final;
--- 60 means ReturnSuccess never ran.
local function save(ctx, tag)
    local ok, why = ctx.save(tag)
    if not ok then return false, why end
    local delay = ctx.peek("sSaveDialogDelay", 1)
    if delay >= 60 then
        return false, fmt("%s: SaveDialogCB_ReturnSuccess never ran (sSaveDialogDelay=%d)", tag, delay)
    end
    ctx.log(fmt("SAVE_DISMISSAL %s by=%s delay=%d", tag, delay > 0 and "a_press" or "timeout", delay))
    return true
end

--- Rows 9 and 1 in one START-menu session. Every read is pret's own state (start_menu.c):
--- input_ready = Task_StartMenuHandleInput alive on StartCB_HandleInput (:378-394), save_running =
--- that task on StartCB_Save1/Save2 -- the checkpoint probe's `dialog` row witness
--- (gen3_boot_check.start_menu_witness).
local function menu_leg(ctx, linked)
    local G, cp, S = ctx.G, ctx.cp, ctx.sym
    local input_ready, save_running = G.start_menu_witness(ctx.title)
    if not input_ready then return false, "no START menu witness for title " .. tostring(ctx.title) end
    local function field_free()
        return G.pred_ok(cp, "field_controls_locked") and not ctx.task_live("Task_StartMenuHandleInput")
    end
    local function dialog_cb() return ctx.peek("sSaveDialogCB", 4) end
    local function at(label) return dialog_cb() == (S[label] | 1) end
    local function cursor() return ctx.peek("sStartMenuCursorPos", 1) end
    -- the leg must write NO save: the flash counter itself (gen3_boot_check.save_counter, the word
    -- the loader picks a slot by), not a log line -- a DUMP_SKIPPED/_FAIL save leaves no DUMP
    local dom = G.flash_domain()
    if not dom then return false, "SAVE_COUNTER: no flash memory domain" end
    local counter0 = G.save_counter(dom)

    -- open START with save_via_menu's discipline (gen3_boot_check.lua:421-439): press only on a
    -- free field, then wait for the menu to READ input; a swallowed Start is pressed again
    local opened = false
    for _ = 1, 3 do
        if not ctx.wait_until(field_free, 10, "the field free before START") then break end
        G.tap("Start", 3, 0)
        if ctx.wait_until(input_ready, 5, "Task_StartMenuHandleInput on StartCB_HandleInput") then
            opened = true
            break
        end
    end
    if not opened then return false, "dialog_witness: the START menu never took input" end
    local n, save_row = ctx.peek("sNumStartMenuItems", 1), nil
    for i = 0, n - 1 do
        if ctx.peek("sStartMenuOrder", 1, i) == MENU_ACTION_SAVE then save_row = i; break end
    end
    if not save_row then return false, fmt("no SAVE row in sStartMenuOrder (%d items)", n) end

    -- row 9: rest the cursor on another row. FRLG left it on SAVE after the last save (the
    -- position survives the close), so one Up (Down at row 0) moves it off.
    local off, back = save_row > 0 and "Up" or "Down", save_row > 0 and "Down" or "Up"
    for _ = 1, 4 do
        if cursor() ~= save_row then break end
        G.tap(off, 3, 13)
    end
    local row = cursor()
    if row == save_row or not input_ready() then
        return false, "dialog_witness: the cursor never rested off the SAVE row"
    end
    local stale = dialog_cb()
    if stale == 0 then
        return false, "dialog_witness: sSaveDialogCB is clear after two saves: the stale-pointer case is not exercised"
    end
    if save_running() then
        return false, fmt("dialog_witness: the save-dialog witness reads TRUE with the cursor on row %d "
                          .. "(sSaveDialogCB=0x%08X)", row, stale)
    end
    ctx.log(fmt("DIALOG_WITNESS_FALSE cursor=%d action=%d save_row=%d menu=open stale=0x%08X", row,
                ctx.peek("sStartMenuOrder", 1, row), save_row, stale))
    local clause, why = ctx.hold_probe("dialog_witness", "party_mon", linked, function()
        return input_ready() and cursor() == row and not save_running()
    end, 600)
    if not clause then return false, why end

    -- row 1: SAVE -> "Would you like to save the game?" YES (DisplayYesNoMenuDefaultYes, :719-724)
    -- -> SaveDialogCB_AskSaveHandleInput case 0 (:726-735). With a save on the cartridge :731 is
    -- `(gSaveFileStatus != EMPTY && != INVALID) || !gDifferentSaveFile`, so the overwrite prompt
    -- follows (:745-759) whatever gDifferentSaveFile says; only its text/default differ.
    for _ = 1, n + 2 do
        if cursor() == save_row then break end
        G.tap(back, 3, 13)
    end
    if cursor() ~= save_row or not input_ready() then return false, "save_prompt: the cursor never returned to SAVE" end
    G.tap("A", 3, 0)
    if not ctx.wait_until(function() return save_running() and at("SaveDialogCB_AskSaveHandleInput") end, 10,
                          "SaveDialogCB_AskSaveHandleInput") then
        return false, "save_prompt: the save dialog never asked to save"
    end
    G.tap("A", 3, 0)
    local function at_prompt()
        return save_running() and at("SaveDialogCB_AskOverwriteOrReplacePreviousFileHandleInput")
    end
    if not ctx.wait_until(at_prompt, 10, "SaveDialogCB_AskOverwriteOrReplacePreviousFileHandleInput") then
        return false, "save_prompt: no overwrite prompt after YES (start_menu.c:731)"
    end
    ctx.log(fmt("SAVE_CANCEL_PROMPT %s row=save prompt=%s", linked,
                ctx.peek("gDifferentSaveFile", 1) == 1 and "different_file" or "overwrite"))
    clause, why = ctx.hold_probe("save_prompt", "party_mon", linked, at_prompt, 600, true)
    if not clause then return false, why end
    -- B at the yes/no: case -1 -> SAVECB_RETURN_CANCEL (:775-780) -> StartCB_Save2 redraws the
    -- menu and re-arms StartCB_HandleInput (:589-594); the lock from ShowStartMenu (:405) stays
    G.tap("B", 3, 13)
    if not ctx.wait_until(input_ready, 10, "the START menu redrawn after the cancel") then
        return false, "save_cancel_menu: the menu never came back after B at the overwrite prompt"
    end
    ctx.log(fmt("SAVE_CANCEL_MENU_REDRAWN %s cursor=%d sSaveDialogCB=0x%08X", linked, cursor(), dialog_cb()))
    clause, why = ctx.hold_probe("save_cancel_menu", "party_mon", linked, input_ready, 600, true)
    if not clause then return false, why end
    ctx.log(fmt("CONTROL_RELEASED save_cancel party_mon %s", linked))
    -- The landing's own frame: the client admits and writes in the FIRST free frame, inside that
    -- frame's onframeend pump -- before this script's next per-frame check can log FIELD_FREE
    -- (live 03ab26e7: write + TX, then SAVE_CANCEL_FIELD_FREE). So the witness is read INSIDE the
    -- write (ctx.on_write runs in the client's frame end, the state the write saw): armed only
    -- now, after the release, it can fire for no earlier write.
    local landed
    ctx.on_write("overworld", function(line)
        landed = { frame = tonumber(tostring(line):match("frame (%d+)")) or -1,
                   free = G.pred_ok(cp, "field_controls_locked"),
                   menu = ctx.task_live("Task_StartMenuHandleInput") }
    end)
    -- B at the menu: CloseStartMenu -> UnlockPlayerFieldControls (:436-441, :1003-1009)
    G.tap("B", 3, 13)
    if not ctx.wait_until(field_free, 10, "the field free after B closed START") then
        return false, "SAVE_CANCEL_FIELD_FREE: the field never freed after B closed the START menu"
    end
    ctx.log(fmt("SAVE_CANCEL_FIELD_FREE %s", linked))
    if not ctx.wait_sent("sync_retrieve_done", linked, LAND_SECS) then
        local held = ctx.queued("party_mon", linked)
        return false, fmt("SAVE_CANCEL_FIELD_FREE: the released party_mon never landed (%s)",
                          tostring(held and held.why))
    end
    if ctx.sent("sync_retrieve_failed", linked) > 0 then return false, "sync_retrieve_failed after the cancel" end
    if not ctx.observe_returned(linked) then return false, linked .. " never read back in the party" end
    if #ctx.write_hook_errors() > 0 then return false, "the write-frame read failed: " .. ctx.write_hook_errors()[1] end
    if not landed then return false, "SAVE_CANCEL_WRITE_FRAME: sync_retrieve_done sent, but no overworld write line was seen" end
    if not landed.free or landed.menu then
        return false, fmt("SAVE_CANCEL_WRITE_FRAME: the party_mon wrote at frame %d with field_free=%s "
                          .. "start_menu_task=%s", landed.frame, tostring(landed.free), tostring(landed.menu))
    end
    ctx.log(fmt("SAVE_CANCEL_WRITE_FRAME %s frame=%d field_free=true start_menu_task=false", linked, landed.frame))
    ctx.log(fmt("CONTROL_SETTLED save_cancel party_mon %s", linked))
    local counter1 = G.save_counter(dom)
    if counter1 ~= counter0 then
        return false, fmt("SAVE_COUNTER: the menu leg moved the flash save counter %d -> %d", counter0, counter1)
    end
    ctx.log(fmt("SAVE_COUNTER_UNCHANGED before=%d after=%d", counter0, counter1))
    return true
end

local function a_side(ctx, linked)
    local ok, why = save(ctx, "save_then_write_1")
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
    ok, why = save(ctx, "save_then_write_2")
    if not ok then return false, "the second save: " .. tostring(why) end
    ok, why = menu_leg(ctx, linked)
    if not ok then return false, why end
    return true, "a keyed box_mon landed on an idle field after an in-game save; the save-dialog "
                 .. "witness stayed false off SAVE; the probe was held at the overwrite prompt and "
                 .. "the redrawn menu, and landed once B freed the field"
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
