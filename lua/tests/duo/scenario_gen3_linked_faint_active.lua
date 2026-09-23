-- scenario_gen3_linked_faint_active.lua — linked_faint_active_gen3, the IN-BATTLE path.
--
-- Owner ruling 2026-09-23 (docs/gen3/PLAN.md §0 "In-battle faint"): a benched party mon is set to
-- HP 0 immediately in battle; the active battler is held and applied on switch-out or battle
-- end. The runner links the two party LEADS (slot 0) and releases A only once B reports
-- READY_ACTIVE.
--
--   B: into a wild battle on the fixture's Route 1 grass, parked on the action menu with the
--      linked lead as battler 0 (no input: the menu waits). When the server's force_faint
--      arrives the client must HOLD it (lua/gen3/client.lua battle_write: "active battler") --
--      HP stays > 0 and the session's battle_pending carries the entry. B then switches to slot
--      1 (POKeMON -> slot 1 -> SHIFT); the linked mon is now benched and the held write must land
--      while the battle is still running (BENCH_HP0_IN_BATTLE), not at the battle's end. B runs,
--      waits for its memorial, saves.
--   A: into a wild battle, choosing only a no-damage move (the first move of battler 0 with base
--      power 0 in gBattleMoves, pret) until its linked lead faints -- a natural engine faint
--      through Cmd_tryfaintmon (ENGINE_FAINT_SITE) that the client reports as `faint`. The rest
--      of the battle is the scripted-play battle policy (send out slot 1, fight); a whiteout is
--      an acceptable ending. A waits for its memorial and saves.
local fmt = string.format

local function a_side(ctx, linked)
    if not ctx.hunt("linked_faint_active a") then return false, "no wild encounter" end
    local fainted, why = ctx.lose_active(linked, "linked_faint_active a")
    if not fainted then return false, "the linked lead did not faint: " .. tostring(why) end
    ctx.log("LINKED_FAINTED " .. linked)
    if ctx.in_battle() then
        local ok, err = ctx.try(ctx.play.fight_through, ctx.cp, 4000)
        if not ok and not (type(err) == "table" and err.whiteout) then
            return false, "after the faint: " .. tostring(err)
        end
        if ok and ctx.in_battle() then return false, "the battle never ended after the faint" end
    end
    ctx.play.wait_scene_settled(ctx.cp, 3000)
    if ctx.sent("faint", linked) == 0 then return false, "the client never sent faint for " .. linked end
    if not ctx.wait_sent("memorialize_done", linked, 600) then
        return false, "no memorialize_done for " .. linked
    end
    local ok, why2 = ctx.save("linked_faint_active")
    if not ok then return false, why2 end
    return true, "natural faint of the active linked " .. linked
end

local function b_side(ctx, linked)
    if not ctx.hunt("linked_faint_active b") then return false, "no wild encounter" end
    if ctx.SP.verify_fight_cursor(ctx.cp, "incidental_battle") ~= "fight" then
        return false, "never reached the action menu"
    end
    if ctx.battler_slot() ~= 0 then return false, "the linked lead is not battler 0" end
    ctx.log("READY_ACTIVE " .. linked)
    if not ctx.wait_received("force_faint", linked, 1500) then
        return false, "no force_faint for " .. linked
    end
    ctx.frames(120)                              -- the session flushes battle writes every frame
    local mon, held = ctx.find(linked), ctx.battle_hold(linked)
    if not mon or mon.hp == 0 then return false, "the ACTIVE battler was written instead of held" end
    if not held then return false, "the force_faint for the active battler is not held" end
    ctx.log(fmt("ACTIVE_HOLD %s why=%s hp=%d", linked, tostring(held.why), mon.hp))
    local ok, why = ctx.switch_to(1)
    if not ok then return false, "switch: " .. tostring(why) end
    ctx.log("SWITCHED_OUT " .. linked)
    local h = ctx.wait_until(function()
        return ctx.hp0(linked) or (not ctx.in_battle() and "over") or nil
    end, 90, "HP 0 on the switched-out linked mon")
    local landed = type(h) == "table" and h.in_battle and not h.battler
    if landed then
        ctx.log(fmt("BENCH_HP0_IN_BATTLE %s frame=%d", linked, h.frame))
    else
        local e = ctx.battle_hold(linked)
        ctx.log(fmt("BENCH_HOLD %s why=%s", linked, e and tostring(e.why) or tostring(h)))
    end
    if ctx.in_battle() then
        ok, why = ctx.run_away("linked_faint_active b")
        if not ok then return false, why end
    end
    ctx.play.wait_scene_settled(ctx.cp, 3000)
    if not ctx.wait_sent("memorialize_done", linked, 600) then
        return false, "no memorialize_done for " .. linked
    end
    ok, why = ctx.save("linked_faint_active")
    if not ok then return false, why end
    if not landed then
        return false, "the switched-out linked mon never reached HP 0 in battle (owner ruling "
                   .. "2026-09-23: in-battle faint must work on vanilla)"
    end
    return true, "held while active; HP 0 in battle once switched out"
end

return function(ctx)
    if not ctx.wait_go(nil, 1800) then return false, "no go-file" end
    local linked = ctx.linked()
    local lead = linked and ctx.find(linked)
    if not lead or lead.slot ~= 0 then return false, "the LINKED key must be the party lead" end
    if lead.hp == 0 then return false, "the fixture's linked lead is already fainted" end
    if ctx.player == "a" then return a_side(ctx, linked) end
    return b_side(ctx, linked)
end
