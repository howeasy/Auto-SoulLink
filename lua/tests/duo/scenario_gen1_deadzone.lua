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
-- Both sides point the wild table at a level-2 MAGIKARP, which cannot appear on Route 1 by
-- chance and cannot damage anything (SPLASH only) — see lua/tests/duo/gen1_hunt.lua.
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
    if not H.force_wild(H.MAGIKARP, 2) then
        return false, "no GRASS_RATE_ADDR in this profile — cannot choose the encounter"
    end

    -- The runner reads this to check both cartridges are on ONE map: Soul Link pairs and
    -- locks by area, so two fixtures on different routes share nothing to test.
    local area = ctx.G.resolve_area(M.getCurrentMap())
    if area == "" then return false, string.format("map 0x%02X resolves to no area",
                                                   M.getCurrentMap()) end
    log(string.format("AREA %s", area))
    log(string.format("MAP 0x%02X role=%s balls=%d party=%d",
                      M.getCurrentMap(), ctx.player, H.balls(), ctx.party_count()))

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
    local mon, merr = H.hunt("catch", 20)
    if not mon then return false, merr end
    log(string.format("CAUGHT %s species=0x%02X level=%d in a DEAD area",
                      mon.key, mon.species_index, mon.level))

    local how = H.wait_retired(mon.key, 7200)
    if not how then
        return false, "caught inside a dead zone and the mon is still alive and ours — "
                   .. "the area lock did not reach this cartridge"
    end
    log("REFUSED " .. mon.key .. " (" .. how .. ")")
    ctx.wait_partner_done(9000)
    return true, "dead-zone refusal: " .. mon.key
end
