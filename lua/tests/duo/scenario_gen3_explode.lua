-- scenario_gen3_explode.lua — explode_gen3 (RR only; server --explode-mode).
--
-- Scripted normal inputs only (Codex C4-6b finding 5: the old port's direct HP poke is gone).
-- The runner links the two party LEADS and releases A only once B reports READY_ACTIVE.
--   A: a wild battle on the fixture's grass, choosing only a no-damage move until its linked
--      lead faints -- a natural engine faint (ENGINE_FAINT_SITE) the client reports as `faint`;
--      the server answers with force_explode for B's partner (Explode Mode) instead of
--      force_faint. The rest of A's battle is the scripted-play battle policy; A saves after its
--      own memorial.
--   B: parked on the action menu with the linked lead as battler 0 (no input: pressing A would
--      commit our own move). The KEYED force_explode must arrive, and then the ENGINE must
--      execute Explosion for that battler: gBattleResults.lastUsedMovePlayer, which
--      HandleAction_UseMove stamps with the move it starts executing and battle start resets
--      (pret src/battle_main.c:2316,4021-4022), must read MOVE_EXPLOSION after the command and
--      not before it. A stamped move slot alone (the old bar) proves the commit write, not the
--      execution. B then finishes the battle, waits for its memorial and saves.
-- BLOCKED like the other "battle"-target RR scenarios (tests/fixtures/gen3/rr_battle{,_b}.sav
-- are not built) and on the lastUsedMovePlayer offset being FR's (+0x22) on RR, unverified.
local fmt = string.format
local MOVE_EXPLOSION = 153           -- pret include/constants/moves.h

local function a_side(ctx, linked)
    if not ctx.hunt("explode a") then return false, "no wild encounter" end
    local fainted, why = ctx.lose_active(linked, "explode a")
    if not fainted then return false, "the linked lead did not faint: " .. tostring(why) end
    ctx.log("LINKED_FAINTED " .. linked)
    if ctx.in_battle() then
        local ok, err = ctx.try(ctx.play.fight_through, ctx.cp, 4000)
        if not ok and not (type(err) == "table" and err.whiteout) then
            return false, "after the faint: " .. tostring(err)
        end
    end
    ctx.play.wait_scene_settled(ctx.cp, 3000)
    if ctx.sent("faint", linked) == 0 then return false, "the client never sent faint for " .. linked end
    if not ctx.wait_sent("memorialize_done", linked, 1800) then return false, "own mon never memorialized" end
    local ok, why2 = ctx.save("explode")
    if not ok then return false, why2 end
    return true, "natural faint of the active linked " .. linked
end

local function b_side(ctx, linked)
    if not ctx.hunt("explode b") then return false, "no wild encounter" end
    if ctx.SP.verify_fight_cursor(ctx.cp, "incidental_battle") ~= "fight" then
        return false, "never reached the action menu"
    end
    if ctx.battler_slot() ~= 0 then return false, "the linked lead is not battler 0" end
    local before = ctx.last_used_move_player()
    if before == MOVE_EXPLOSION then return false, "lastUsedMovePlayer already reads Explosion" end
    ctx.log(fmt("READY_ACTIVE %s last_used=%d", linked, before))
    if not ctx.wait_received("force_explode", linked, 1500) then
        return false, "no keyed force_explode for " .. linked
    end
    local executed = ctx.wait_until(function()
        return ctx.last_used_move_player() == MOVE_EXPLOSION or nil
    end, 180, "the engine to execute Explosion")
    if not executed then
        return false, fmt("the engine never executed Explosion (lastUsedMovePlayer=%d)", ctx.last_used_move_player())
    end
    ctx.log(fmt("EXPLOSION_EXECUTED %s battler_slot=%d last_used=%d", linked, ctx.battler_slot(),
                ctx.last_used_move_player()))
    if ctx.in_battle() then
        local ok, err = ctx.try(ctx.play.fight_through, ctx.cp, 4000)
        if not ok and not (type(err) == "table" and err.whiteout) then
            return false, "after the Explosion: " .. tostring(err)
        end
    end
    ctx.log(fmt("resolved: outcome=%d", ctx.battle_outcome()))
    ctx.play.wait_scene_settled(ctx.cp, 3000)
    if not ctx.wait_sent("memorialize_done", linked, 1800) then
        return false, "the partner never memorialized after the Explosion"
    end
    local ok, why = ctx.save("explode")
    if not ok then return false, why end
    return true, "keyed force_explode executed natively"
end

return function(ctx)
    if not ctx.wait_go(nil, 1800) then return false, "no go-file" end
    local linked = ctx.linked()
    local lead = linked and ctx.find(linked)
    if not lead or lead.slot ~= 0 then return false, "the LINKED key must be the party lead" end
    if ctx.player == "a" then return a_side(ctx, linked) end
    return b_side(ctx, linked)
end
