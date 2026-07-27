-- scenario_gen1_dupes.lua — the species clause, fired live for the first time.
--
-- The rule (server/state.py:_check_link_violation, reached from _handle_capture once BOTH
-- players have a pending capture in the same area): with --species-clause, two halves of a
-- pair may not share an evolution family. The LATER capture is rejected — force_faint,
-- memorialize, a "[x] Species clause: ..." prompt, unresolve_area — and the area drops back
-- to PENDING_A/PENDING_B so the rejected player can go again. It does NOT become a dead
-- zone, and no link forms.
--
-- The clause has never fired against a running cartridge, because until now no test could
-- make two independent emulators meet the same species. They can: pokered keeps the current
-- map's wild table in WRAM at wGrassMons and TryDoWildEncounter reads the species straight
-- out of it, so pointing both tables at one species makes the next encounter deterministic
-- without faking any part of the capture. See lua/tests/duo/gen1_hunt.lua for the citations.
--
-- Both sides catch a MAGIKARP. Which one loses depends on which capture reached the server
-- second, so neither side asserts it is the victim: each reports REJECTED or KEPT and the
-- runner requires exactly one of each, plus a server that shows no link and one surviving
-- pending capture.
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

    local area = ctx.G.resolve_area(M.getCurrentMap())
    if area == "" then return false, string.format("map 0x%02X resolves to no area",
                                                   M.getCurrentMap()) end
    log(string.format("AREA %s", area))
    log(string.format("MAP 0x%02X forcing species 0x%02X (natdex %d) at level 2",
                      M.getCurrentMap(), H.MAGIKARP, ctx.G.toNatDex(H.MAGIKARP)))

    local mon, merr = H.hunt("catch", 20)
    if not mon then return false, merr end
    log(string.format("CAUGHT %s species=0x%02X level=%d", mon.key, mon.species_index, mon.level))

    -- Exactly one of the two catches is the later one and gets retired. The other is merely
    -- QUARANTINED to the box until a link forms, which also empties its party slot — so the
    -- verdict must come from HP hitting zero or the memorial box growing, never from the mon
    -- leaving the party. H.wait_retired is the one place that distinction lives.
    local how = H.wait_retired(mon.key, 7200)
    if how then
        log("REJECTED " .. mon.key .. " (" .. how .. ")")
    else
        log("KEPT " .. mon.key)
    end
    ctx.wait_partner_done(12000)
    return true, (how and "rejected " or "kept ") .. mon.key
end
