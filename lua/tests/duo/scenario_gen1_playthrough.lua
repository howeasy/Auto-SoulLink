-- Real Route 1 encounters, Poke Ball capture and server-created links on two cartridges.
-- The shared hunt driver stocks balls and keeps the fixture's active battler healthy;
-- it does not change the route's species/levels or the cartridge's capture result.
-- Faint/whiteout behavior has separate scenarios. This is not a full human playthrough.
return function(ctx)
    local M, log, fmt = ctx.M, ctx.log, string.format
    if not ctx.wait_go() then return false, "no go-file" end
    local H = dofile(SLINK_DUO.wt .. "/lua/tests/duo/gen1_hunt.lua")(ctx)
    local start_map = M.read_u8(M.MAP_ID_ADDR)
    if M.hasWildEncounters() ~= true then return false, "fixture map has no wild encounters" end
    local stocked, error = H.stock_balls(40)
    if not stocked then return false, error end
    local before, balls_before = H.all_keys(), H.balls()
    log(fmt("MAP 0x%02X party=%d balls=%d; natural encounter table, fixture HP support",
            start_map, ctx.party_count(), balls_before))

    -- A lost FIRST encounter dead-zones this area. Retrying it cannot prove a link.
    -- The shared driver observes ball-use completion and catches in party/box, so
    -- server quarantine cannot turn a successful capture into another hunt.
    local mon, reason = H.hunt("catch", 1)
    if not mon then return false, reason end
    if before[mon.key] then return false, "capture reused a pre-existing key" end
    if H.balls() >= balls_before then return false, "no Poke Ball was consumed" end
    if M.read_u8(M.MAP_ID_ADDR) ~= start_map then return false, "capture driver left the encounter map" end

    -- H.hunt can recover just an identity after an immediate server quarantine.
    -- Read its actual data/location again instead of inventing species or level.
    local found, where
    for _, source in ipairs({
        {"party", M.getPartyCount, M.readPartySlot},
        {"box", M.getBoxCount, M.readBoxSlot},
        {"memorial", M.getMemorialBoxCount, M.readMemorialBoxSlot},
    }) do
        local count = source[2]()
        for slot = 0, count - 1 do
            local candidate = source[3](slot)
            if candidate and candidate.key == mon.key then
                if found then return false, "captured key appears in multiple storage slots" end
                if source[1] == "box" then
                    local base = M.BOX_BASE_ADDR + slot * M.BOX_STRUCT_SIZE
                    candidate.hp = M.box_read_u16_be(base + M.HP_OFFSET)
                    local experience = M.box_read_u8(base + M.OTID_OFFSET + 2) * 65536
                        + M.box_read_u8(base + M.OTID_OFFSET + 3) * 256
                        + M.box_read_u8(base + M.OTID_OFFSET + 4)
                    local facts = ctx.G.readBaseStats(M.gb_variant, ctx.G.toNatDex(candidate.species_index))
                    candidate.level = facts and require("gen1_party_codec").levelFromExperience(facts.growth_rate, experience)
                end
                found, where = candidate, source[1]
            end
        end
    end
    if not found then return false, "captured key is absent from party and storage" end
    if where == "memorial" or not found.hp or found.hp <= 0 then return false, "capture was retired before linking" end
    if not found.species_index or found.species_index <= 0 or not found.level or found.level < 1 then
        return false, "captured record has invalid species or level"
    end
    log(fmt("CAUGHT %s species=0x%02X level=%d on map 0x%02X where=%s",
            found.key, found.species_index, found.level, start_map, where))
    log(fmt("balls %d -> %d", balls_before, H.balls()))
    if not ctx.wait_link_verified(found.key, 9000) then return false, "server did not verify this capture's link" end
    if not ctx.wait_until(function() return ctx.find_slot_by_key(found.key) ~= nil end,
                          3600, "linked capture to return from quarantine") then
        return false, "linked capture remained outside the party"
    end
    ctx.frames(120)
    return true, "caught " .. found.key
end
