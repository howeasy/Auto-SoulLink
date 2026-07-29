-- scenario_gen1_explode.lua — Explode Mode: the survivor detonates instead of just dying.
--
-- With --explode-mode, a linked partner's death sends the survivor `force_explode` rather
-- than the deferred `force_faint`. Gen 3 needed the companion patch for this; Gen 1 does it
-- from RAM, because the engine takes the player's chosen move from wPlayerSelectedMove.
--
-- The chain:
--   A's linked mon dies
--     -> the server's death path checks adapter.supports_explode_mode() — Gen 1 now returns
--        true, where it used to fall back to force_faint
--     -> B receives force_explode
--     -> B's client writes Explosion (move 153) into the ACTIVE battler's move slot 0 plus
--        its PP, mirrors it into the party struct, and sets wPlayerMoveListIndex +
--        wPlayerSelectedMove
--
-- B has to be IN A BATTLE for any of that to be meaningful — the handler refuses otherwise
-- and falls back to a plain faint, which is the correct behaviour but not what this tests.
-- The battle is simulated by writing wIsInBattle, exactly as the rivalswap scenario does:
-- the code under test reads that address, and everything else here is real.
return function(ctx)
    local log = ctx.log
    local M = ctx.M
    if not ctx.wait_go() then return false, "no go-file" end

    local key0 = ctx.slot_key(0)
    if not key0 then return false, "no mon in slot 0" end
    log(string.format("go received; key=%s party=%d", key0, ctx.party_count()))

    if ctx.player == "b" then
        -- Be the survivor, and be in a battle so there is an active battler to coerce.
        M.write_u8(M.BATTLE_FLAG_ADDR, 1)           -- IN_BATTLE_WILD
        M.write_u8(M.PLAYER_MON_NUMBER_ADDR, 0)     -- slot 0 is out
        -- Give slot 0 a move that is NOT Explosion, so "it was already 153" cannot pass.
        M.write_u8(M.BATTLE_MON_MOVES_ADDR, 33)     -- Tackle
        log("in battle with Tackle in slot 0, waiting for the partner to die")

        local armed = ctx.wait_until(function()
            local mv = M.read_u8(M.BATTLE_MON_MOVES_ADDR)
            local sel = M.read_u8(M.PLAYER_SELECTED_MOVE_ADDR)
            if mv == M.MOVE_EXPLOSION or sel == M.MOVE_EXPLOSION then return true end
            -- A plain force_faint instead would zero our HP — that is the FALLBACK path,
            -- not explode, and must be reported as such rather than passing.
            if ctx.read_hp(0) == 0 then return "fainted" end
            return nil
        end, 14400, "force_explode to arrive")

        if armed == "fainted" then
            return false, "got force_faint, not force_explode — the adapter gate did not fire"
        end
        if not armed then
            return false, "force_explode never arrived"
        end
        local mv = M.read_u8(M.BATTLE_MON_MOVES_ADDR)
        local sel = M.read_u8(M.PLAYER_SELECTED_MOVE_ADDR)
        local idx = M.read_u8(M.PLAYER_MOVE_LIST_INDEX_ADDR)
        log(string.format("armed: moveSlot0=%d selectedMove=%d listIndex=%d", mv, sel, idx))
        if sel ~= M.MOVE_EXPLOSION then
            return false, "wPlayerSelectedMove is not Explosion — the engine would not use it"
        end
        M.write_u8(M.BATTLE_FLAG_ADDR, 0)
        return true, "force_explode armed Explosion on the active battler"
    end

    -- A: die, which is what triggers the partner's explosion.
    ctx.frames(180)
    ctx.write_hp(0, 0)
    log("killed our half — B should be coerced into Explosion")
    ctx.wait_partner_done(14400)
    return true, "faint emitted for " .. key0
end
