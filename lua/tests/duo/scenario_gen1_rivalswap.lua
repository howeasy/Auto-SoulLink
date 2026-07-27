-- scenario_gen1_rivalswap.lua — the rival fights you with your PARTNER'S actual team.
--
-- Gen 3 needed the native companion patch for this, because `gEnemyParty` is encrypted and
-- checksummed. Gen 1 has no encryption, no checksums and no ASLR, so the swap is a plain
-- 404-byte copy over wEnemyPartyCount / species list / wEnemyMons / wEnemyMonOT /
-- wEnemyMonNicks — no patched ROM anywhere in this test.
--
-- The whole chain, on real hardware:
--   A walks into a battle whose wCurOpponent is a RIVAL class (225/242/243 = RIVAL1/2/3
--     in OPP space; the raw class + OPP_ID_OFFSET(200))
--     -> the client's stability gate sees the id hold steady and emits trainer_battle_start
--     -> the server checks it against adapter.rival_trainer_ids() and the run's
--        rival_team_swap flag, then sends replace_rival_team carrying B's cached party
--        blobs (which only exist because the client puts blob_hex on every snapshot and
--        party_blob_size() lets the server keep 66-byte Gen 1 blobs at all)
--     -> A's client writes them into the enemy party and acks rival_team_replaced
--
-- The battle itself is SIMULATED by writing wIsInBattle and wCurOpponent rather than
-- walking into a real trainer: the fixture starts in Pallet, where no rival exists, and
-- the code under test reads exactly those two addresses. What is NOT faked is anything
-- that matters — the event, the server decision, the blobs, and the 404-byte write.
return function(ctx)
    local log = ctx.log
    local M = ctx.M
    if not ctx.wait_go() then return false, "no go-file" end

    local key0 = ctx.slot_key(0)
    log(string.format("go received; our key=%s party=%d", tostring(key0), ctx.party_count()))

    if ctx.player == "b" then
        -- B does nothing but exist: its party is the payload. It must stay alive long
        -- enough for its blob_hex snapshots to reach the server and for A to finish.
        log("standing by so my party can be handed to A's rival")
        ctx.wait_partner_done(14400)
        return true, "supplied the partner team"
    end

    -- Let B's first tick land so the server has its blobs cached; without them
    -- queue_rival_team_swap refuses with "partner has no cached party blobs".
    ctx.frames(600)

    local before_count = M.read_u8(M.ENEMY_COUNT_ADDR)
    local before_first = M.read_u8(M.ENEMY_BASE_ADDR)
    log(string.format("enemy party before: count=%d firstSpecies=0x%02X",
                      before_count, before_first))

    -- Enter a "rival" battle: trainer battle (wIsInBattle = 2) against RIVAL1 (OPP 225).
    M.write_u8(M.BATTLE_FLAG_ADDR, 2)
    M.write_u8(M.CUR_OPPONENT_ADDR, 225)
    log("simulated a RIVAL1 trainer battle (wIsInBattle=2, wCurOpponent=225)")

    -- The client's gate waits for the opponent id to hold steady for a few frames before
    -- announcing, so hold the state while it does.
    local replaced = ctx.wait_until(function()
        local n = M.read_u8(M.ENEMY_COUNT_ADDR)
        local sp = M.read_u8(M.ENEMY_BASE_ADDR)
        -- The swap landed when the enemy party changes to something non-empty.
        if n >= 1 and n <= 6 and sp ~= 0 and (n ~= before_count or sp ~= before_first) then
            return true
        end
        return nil
    end, 14400, "replace_rival_team to be applied")

    if not replaced then
        return false, string.format(
            "enemy party never replaced (count=%d first=0x%02X)",
            M.read_u8(M.ENEMY_COUNT_ADDR), M.read_u8(M.ENEMY_BASE_ADDR))
    end

    local n = M.read_u8(M.ENEMY_COUNT_ADDR)
    local sp = M.read_u8(M.ENEMY_BASE_ADDR)
    local lvl = M.read_u8(M.ENEMY_BASE_ADDR + 0x21)
    local term = M.read_u8(M.ENEMY_SPECIES_LIST_ADDR + n)
    log(string.format("rival team swapped in: count=%d species=0x%02X level=%d", n, sp, lvl))

    -- Structural checks on the write itself: a wrong stride or a missing terminator would
    -- have the engine send out garbage on the first turn.
    if term ~= 0xFF then
        return false, string.format("species list not 0xFF-terminated (got 0x%02X)", term)
    end
    if lvl == 0 then
        return false, "enemy mon level is 0 — the +0x21 level offset did not land"
    end

    M.write_u8(M.BATTLE_FLAG_ADDR, 0)     -- leave the battle state clean
    ctx.wait_partner_done(7200)
    return true, string.format("rival team replaced (%d mons)", n)
end
