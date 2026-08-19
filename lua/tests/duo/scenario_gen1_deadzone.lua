-- scenario_gen1_deadzone.lua — a REAL failed encounter locks the area for BOTH players.
--
-- The rule (server/state.py:_handle_no_catch): a wild battle that ends without a capture
-- makes that area a dead zone, and any later capture there is retired on arrival
-- (state.py:_handle_capture, `status == AreaStatus.DEAD_ZONE` branch: force_faint +
-- memorialize + a "[x] DZ:" toast).
--
-- Never asserted anywhere before this. A no_catch was OBSERVED once, incidentally, during
-- the playthrough scenario — which is not the same as testing it, and says nothing at all
-- about the half of the rule that matters: what happens to the PARTNER.
--
--   A  meets a real wild Pokemon and KILLS it. A never opens the bag, so a capture is not
--      merely unattempted, it is impossible — and the ball count proves it.
--   B  is released only once the SERVER shows the area locked (the runner withholds B's
--      go-file until then, so the ordering is a fact rather than a hope), then walks the
--      same grass, catches a real Pokemon, and must have it taken away.
--
-- Whatever Route 1 offers is fine: a failed encounter is a failed encounter, so this needs
-- no chosen species. It once forced the wild table to a MAGIKARP for convenience; that never
-- worked, and four hypotheses for why are recorded dead in lua/tests/probe_gen1_wildtable.lua.
return function(ctx)
    local log, M = ctx.log, ctx.M
    local H = dofile(SLINK_DUO.wt .. "/lua/tests/duo/gen1_hunt.lua")(ctx)
    if not ctx.wait_go() then return false, "no go-file" end

    if M.hasWildEncounters() == false then
        return false, string.format("map 0x%02X has no wild encounters (wGrassRate == 0)",
                                    M.getCurrentMap())
    end
    local ok, err = H.stock_balls(40)
    if not ok then return false, err end
    -- NO SPECIES FORCING. This scenario wants a FAILED encounter, and any species fails
    -- just as well as a chosen one. Forcing wGrassMons demonstrably does not change what the
    -- game serves (four hypotheses killed in lua/tests/probe_gen1_wildtable.lua), so
    -- depending on it only added a way to lose.

    -- The runner reads this to check both cartridges are on ONE map: Soul Link pairs and
    -- locks by area, so two fixtures on different routes share nothing to test.
    local area = ctx.G.resolve_area(M.getCurrentMap())
    if area == "" then return false, string.format("map 0x%02X resolves to no area",
                                                   M.getCurrentMap()) end
    log(string.format("AREA %s", area))
    log(string.format("MAP 0x%02X role=%s balls=%d party=%d",
                      M.getCurrentMap(), ctx.player, H.balls(), ctx.party_count()))

    -- B is catching INSIDE an already-locked area, so a lost ball there cannot invalidate
-- anything — let it retry instead of aborting the run. (A's side keeps the default: its
-- failed encounter is the thing being tested, and it must be the FIRST one.)
if ctx.player == "b" then H.retry_on_loss = true end

if ctx.player == "a" then
        local balls0, party0 = H.balls(), ctx.party_count()
        local killed, kerr = H.hunt("kill", 20)
        if not killed then return false, kerr end
        -- H.hunt already checks these; repeat them here because the whole scenario is
        -- worthless if A quietly caught something — a capture would RESOLVE the area
        -- instead of locking it, and B would then be refused for the wrong reason.
        if ctx.party_count() ~= party0 then return false, "A caught something" end
        if H.balls() ~= balls0 then return false, "A spent a ball" end
        log("NOCATCH — wild battle ended, party unchanged, no ball spent")
        -- Do not exit: client.exit() stops this instance emulating, and its client stops
        -- sending. B's half of the rule needs A's connection alive.
        ctx.wait_partner_done(30000)
        return true, "failed the encounter in " .. area
    end

    -- B. The go-file only exists because the server already reported this area dead.
    --
    -- DO NOT REQUIRE H.hunt TO HAND BACK THE MON. Inside a dead zone the server retires the
    -- capture the instant it hears about it, and the client reports it from diff_party on
    -- the very frame the party grows -- so the mon is force-fainted and memorialised before
    -- H.throw() has even returned. Measured over 24 hunts: max_party_seen=3 with
    -- party_now=2 on 22 of them, alongside 11-13 capture(battle) events each answered
    -- force_faint. Asking "did the party grow and stay grown" made a correctly-enforced
    -- rule look like eighteen consecutive failed catches. Two compounding races defeat any
    -- RAM poll here: wPartyCount is incremented BEFORE the mon's struct is written, and the
    -- server round-trip completes inside the throw.
    --
    -- So assert on the DURABLE consequence instead. The memorial box is where a retired
    -- capture ends up and it does not un-grow, which makes it the one signal that cannot be
    -- raced. A ball leaving the bag proves a real throw happened; the memorial box growing
    -- proves the server took the catch away. Together that is exactly the rule under test.
    local mem0   = (M.getMemorialBoxCount and M.getMemorialBoxCount()) or 0
    local balls0 = H.balls()

    -- The return value is a bonus, not a requirement: if the latch happened to win the race
    -- we get a key to name in the log, and if it did not the assertions below still hold.
    local mon = H.hunt("catch", 20)
    local spent = balls0 - H.balls()
    if spent <= 0 then
        return false, "B never threw a ball, so nothing about the dead zone was tested"
    end
    log(string.format("THREW %d ball(s) in a DEAD area (max_party_seen=%s)",
                      spent, tostring(H.max_party_seen)))

    local how = ctx.wait_until(function()
        local mem = (M.getMemorialBoxCount and M.getMemorialBoxCount()) or 0
        if mem > mem0 then return "memorialized" end
        -- Still worth watching: if the latch DID win the race we can also catch the
        -- force_faint, which arrives before the burial.
        if mon and mon.key then
            local slot = ctx.find_slot_by_key(mon.key)
            if slot and ctx.read_hp(slot) == 0 then return "force_faint" end
        end
        return nil
    end, 7200, "the server to retire the dead-zone capture")

    if not how then
        return false, string.format(
            "threw %d ball(s) inside a dead zone and nothing was ever retired — the "
            .. "memorial box stayed at %d, so the area lock did not reach this cartridge",
            spent, mem0)
    end
    log(string.format("REFUSED %s (%s)", mon and mon.key or "<retired before we could read it>", how))
    ctx.wait_partner_done(9000)
    return true, "dead-zone refusal via " .. how
end
