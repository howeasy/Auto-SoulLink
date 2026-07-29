-- scenario_gen1_whiteout.lua — a REAL cartridge blackout, and the Soul Link fan-out from it.
--
-- WHAT HAS NEVER RUN LIVE: the client's check_whiteout. Every other Gen 1 path has a gate or
-- a duo scenario; this one has only unit tests, which feed the server a synthetic
-- {"event":"whiteout"} and never ask whether a cartridge can produce one.
--
-- HOW THE BLACKOUT IS PRODUCED — the cheap real one, not a lost battle:
--   pokered engine/events/poison.asm:1 ApplyOutOfBattlePoisonDamage runs from the overworld
--   loop (home/overworld.asm:317) on every 4th completed step. For each party mon with
--   1 << PSN set (PSN = 3, constants/battle_constants.asm:64) it decrements HP; a mon that
--   reaches 0 prints "<MON> fainted!". When AnyPartyAlive then returns 0 it prints
--   "blacked out!" and sets wOutOfBattleBlackout = $FF (poison.asm:107-114), which
--   home/overworld.asm:318-320 turns into `jp HandleBlackOut`.
--   HandleBlackOut (home/overworld.asm:756) is the SAME routine the battle path reaches
--   (home/overworld.asm:355-358) — fade out, ResetStatusAndHalveMoneyOnBlackout
--   (engine/events/black_out.asm:1, which ends `predef_jump HealParty`), warp to
--   wLastBlackoutMap. So this is a genuine blackout; only the damage source differs.
--   Cost: set PSN + HP=1 and walk a few steps in an encounter-free town. No RNG, no battle.
--
-- WHAT IT PROVES THAT scenario_gen1_faint DOES NOT.
--   Measured against the real server (server/state.py:1909 _handle_whiteout): on a live
--   cartridge every mon's `faint` reaches the server BEFORE the whiteout does — poison.asm
--   stops on a text box between mons, and the last faint kills its pair anyway. So by the
--   time `whiteout` arrives, `retired` is empty and entry.cause reads "battle", not
--   "whiteout". DO NOT ASSERT ON cause. The one thing only a whiteout can do is the
--   AUTO-REBUILD: _plan_rebuild pulls an alive, fully-boxed pair back into BOTH parties.
--   Nothing else in SLink issues that. So the load-bearing assertion is on B:
--
--       B's boxed half returns to B's party, on B's machine, untouched.
--
--   Control run (whiteout event dropped, everything else identical): B gets box_mon +
--   force_faint and NO party_mon. The assertion can fail.
--
-- SHAPE: both sides start with 2 mons (duo_gen1_main fillers) and the runner links slot0 and
-- slot1 as two pairs. A deposits its slot-1 half, which the sync rule mirrors onto B — that
-- is the boxed alive pair the rebuild will pull back. A then poisons its ONE remaining mon
-- to death, which is exactly the shape of a real Nuzlocke whiteout.
return function(ctx)
    local log, M = ctx.log, ctx.M
    if not ctx.wait_go() then return false, "no go-file" end

    local key0, key1 = ctx.slot_key(0), ctx.slot_key(1)
    if not (key0 and key1) then
        return false, "need two party mons (party=" .. ctx.party_count() .. ")"
    end
    log(string.format("go received; key0=%s key1=%s party=%d", key0, key1, ctx.party_count()))

    -- ── A: box one pair, then really black out ───────────────────────────────
    if ctx.player == "a" then
        ctx.frames(120)                       -- let the link-inject HUD commands drain

        -- THE NUZLOCKE GATE IS A SILENT PRECONDITION. check_whiteout (gen1_rby_client.lua)
        -- returns immediately unless nuzlocke_active, which is M.hasPokeballs(). Without this
        -- assertion a drifted fixture blacks out for real, EVERY A-side check below passes,
        -- no whiteout is ever sent, and the failure surfaces 14400 frames later on B as "the
        -- auto-rebuild did not run" — pointing squarely at the server instead of the bag.
        if not M.hasPokeballs() then
            return false, "hasPokeballs() is false — the client would never emit `whiteout`, "
                          .. "and this scenario would fail on B for the wrong reason"
        end

        -- 1. Deposit our half of pair 1. The client emits party_to_box, and the server's
        --    _handle_party_to_box both mirrors box_mon to B AND drops B's half from
        --    party_keys immediately — so the pair is co-located-in-box server-side without
        --    waiting on B's machine. That co-location is what _alive_pc_mons requires.
        local ok, err = M.depositPartyMon(1)
        if not ok then return false, "depositPartyMon failed: " .. tostring(err) end
        if not ctx.wait_until(function()
                return ctx.find_slot_by_key(key1) == nil or nil
            end, 3600, "our filler to leave the party") then
            return false, "filler never left A's party — nothing to rebuild from later"
        end
        -- party_to_box is debounced 3 frames and then needs one round trip. 240 frames is
        -- ~80x that, not a guess at how long a machine takes.
        ctx.frames(240)
        log("deposited pair-1 half; A is down to one party mon")

        -- 2. Poison the last mon and put it on 1 HP. One poison tick takes 0x0001 -> 0x0000
        --    with no borrow, so the very next multiple-of-4 step faints it (poison.asm:26-41).
        local base = M.PARTY_BASE_ADDR + 0 * M.PARTY_STRUCT_SIZE
        M.write_u8(base + M.STATUS_OFFSET, 0x08)      -- 1 << PSN
        ctx.write_hp(0, 1)
        log(string.format("slot0 poisoned, hp=%d — walking until the poison tick lands",
                          ctx.read_hp(0)))

        -- wOutOfBattleBlackout is not in the memory profile. Derive it from one that is
        -- rather than hardcoding: pret wPartyCount 0xD163 / wOutOfBattleBlackout 0xD12D
        -- (pokered), 0xD162 / 0xD12C (pokeyellow) — the same -0x36 in both, because Yellow
        -- shifts the whole block by -1. Never a literal: a Yellow run would read the
        -- neighbouring byte.
        local blackout_addr = M.PARTY_COUNT_ADDR - 0x36
        local map_before    = M.getCurrentMap()

        -- Latched every frame we yield. saw_all_zero is the exact predicate the client's
        -- check_whiteout evaluates; if it never latches, the client had nothing to detect
        -- and any downstream failure is ours, not the server's.
        local saw_all_zero, saw_blackout_flag = false, false
        local function sample()
            if M.read_u8(blackout_addr) == 0xFF then saw_blackout_flag = true end
            local n = ctx.party_count()
            if n >= 1 and n <= 6 then
                local all_zero = true
                for s = 0, n - 1 do
                    if ctx.read_hp(s) > 0 then all_zero = false break end
                end
                if all_zero then saw_all_zero = true end
            end
        end

        -- 3. Walk. A direction must be HELD; a tap only turns the player. Alternate
        --    Left/Right so a wall on one side cannot stall us, and stay in the town the
        --    fixture parks in — encounter-free ground, so no wild battle can hijack this.
        local dead = false
        for i = 1, 40 do
            ctx.hold(i % 2 == 0 and "Left" or "Right", 24, function()
                sample()
                if ctx.read_hp(0) == 0 then dead = true end
                return dead or nil
            end)
            if dead then break end
        end
        if not dead then
            return false, "poison never ticked — slot0 still at " .. ctx.read_hp(0) .. " HP"
        end
        log("slot0 fainted from poison — the blackout sequence is running")

        -- 4. Advance "<MON> fainted!" and "blacked out!", then the fade and the warp.
        --    ResetStatusAndHalveMoneyOnBlackout ends in HealParty, so HP coming back is
        --    proof HandleBlackOut ran to completion rather than the game wedging on a box.
        local healed = false
        for _ = 1, 200 do
            ctx.hold("A", 6, function() sample() return nil end)
            ctx.frames(12)
            sample()
            if ctx.read_hp(0) > 0 then healed = true break end
        end
        local map_after = M.getCurrentMap()

        if not saw_all_zero then
            return false, "no frame ever had the whole party at 0 HP — check_whiteout could "
                          .. "not have fired (HealParty beat the client's poll)"
        end
        if not saw_blackout_flag then
            return false, "wOutOfBattleBlackout never read 0xFF — the game did not take "
                          .. "HandleBlackOut, so this was a RAM poke, not a blackout"
        end
        log(string.format("blackout confirmed: all-party-0HP seen, wOutOfBattleBlackout=0xFF, "
                          .. "map %d -> %d, healed=%s", map_before, map_after, tostring(healed)))
        if map_after == map_before and not healed then
            return false, "blacked out but never warped or healed — HandleBlackOut wedged"
        end

        -- Stay alive: client.exit() stops this emulator, and B is waiting on commands the
        -- server only issues from events this client still has to send.
        log("staying alive until B reports")
        ctx.wait_partner_done(14400)
        return true, "real blackout produced; whiteout emitted"
    end

    -- ── B: touched by nobody ─────────────────────────────────────────────────
    -- Three things must happen here, all driven from A's machine through the server.
    local boxed = ctx.wait_until(function()
        return ctx.find_slot_by_key(key1) == nil or nil
    end, 14400, "box_mon for our half of pair 1")
    if not boxed then
        return false, "pair-1 half never left B's party — the boxed pair the rebuild needs "
                      .. "was never set up"
    end
    log("BOXED pair-1 half — party is down to one mon")

    -- 1. The partner death. Same latch-or-corroborate shape as scenario_gen1_faint: the
    --    0 HP window is short, and "the mon vanished" alone passes for a no-op force_faint.
    local saw_zero, buried, restored = false, false, false
    local function sample()
        local s = ctx.find_slot_by_key(key0)
        if s and ctx.read_hp(s) == 0 then saw_zero = true end
        if not saw_zero and not buried and not s then
            for i = 0, (M.BOX_MAX_MONS or 20) - 1 do
                local m = M.readMemorialBoxSlot and M.readMemorialBoxSlot(i)
                if m and m.key == key0 then buried = true break end
            end
        end
        if ctx.find_slot_by_key(key1) then restored = true end
    end

    ctx.wait_until(function()
        sample()
        return (saw_zero or buried) or nil
    end, 14400, "the partner's death to arrive")
    if not (saw_zero or buried) then
        return false, "linked mon never died on B — force_faint never applied and it is not "
                      .. "in the memorial box either"
    end
    log(saw_zero and "observed the linked mon at 0 HP" or "linked mon is in the memorial box")

    -- 2. THE WHITEOUT-EXCLUSIVE ASSERTION. Our boxed half comes back to our party on its
    --    own. The only code path in SLink that queues party_mon unprompted is
    --    _handle_whiteout's auto-rebuild (state.py:1930-1938 -> _queue_rebuild_commands).
    --    With the whiteout event dropped, this never arrives — that is the control that
    --    makes the check meaningful rather than decorative.
    ctx.wait_until(function()
        sample()
        return restored or nil
    end, 14400, "the auto-rebuild to restore our boxed half")
    if not restored then
        return false, "the boxed pair was never restored to B's party — A's whiteout did "
                      .. "not reach the server, or the auto-rebuild did not run"
    end
    log("auto-rebuild restored our boxed half — A's whiteout propagated end to end")
    return true, "partner died and the whiteout rebuild landed"
end
