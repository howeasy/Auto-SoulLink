-- scenario_gen3_faint_cmd.lua — faint_cmd_gen3 (docs/gen3/PLAN.md §5.5), both halves.
--
-- SERVER-COMMAND / PERSISTENCE ONLY: the runner links the two slot-1 mons and injects A's faint
-- through the debug API (tools/e2e_duo.py orchestrate_faint_cmd_gen3). The server marks the pair
-- DEAD, queues force_faint + memorialize to B and memorialize to A (server/state.py
-- _propagate_faint). Both cartridges stand on the encounter-free town fixture, so B's
-- force_faint can only land through the overworld checkpoint; the HP-0 watcher in
-- duo_gen3_main.lua records it (FORCED_HP0 ... in_battle=0) before memorialize moves the record
-- into the memorial box. Nothing here presses a button until the SAVE.
return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local linked = ctx.linked()
    if not linked then return false, "the go-file names no LINKED key" end
    if not ctx.find(linked) then return false, "the linked key " .. linked .. " is not in the party" end
    ctx.log("READY " .. linked)
    if not ctx.wait_sent("memorialize_done", linked, 600) then
        return false, "no memorialize_done for " .. linked
    end
    if ctx.player == "b" then
        if ctx.received("force_faint", linked) == 0 then return false, "B never received force_faint" end
        local h = ctx.hp0(linked)
        if not h then return false, "force_faint never took " .. linked .. " to HP 0 before its memorial" end
        if h.in_battle then return false, "the forced HP 0 landed in a battle; this scenario is overworld" end
    elseif ctx.received("force_faint") > 0 then
        return false, "A (the initiator) received a force_faint"
    end
    ctx.frames(60)
    local ok, why = ctx.save("faint_cmd")
    if not ok then return false, why end
    return true, "memorialized " .. linked
end
