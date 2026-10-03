-- gen3_rehunt_filter.lua -- the DISCLOSED natural REHUNT_FILTER of link_gen3_rand (and only it).
--
-- Why: a randomized ROM can put a very low catch-rate foe (legendary-grade, rate 3..45) in the Route 1 / Route 102 grass; the pair has
-- only 2-4 Poke Balls and the game's catch RNG then ends the hunt "out-of-balls", which says nothing about the product. This module
-- spends no ball on such a foe: it RUNs (ctx.run_away) and hunts again (ctx.hunt) -- both ordinary-input paths the driver already uses.
-- Nothing is injected, no species is chosen: the foe is whatever the encounter produced, and it is skipped only when ITS catch rate,
-- read from THIS SIDE'S OWN ROM (gSpeciesInfo, 28-byte records, catchRate at +8; never Radical Red data), is below cfg.max_rate.
--
--   cfg = ctx.D.rehunt_filter = { max_rate, max_rehunts, species_info (ROM address), stride, catch_offset }
--
-- No cfg (every other row) -> ctx.catch(label) exactly as before. Unreadable species/rate -> NO filtering, logged, normal catch.
-- Every decision is a REHUNT_FILTER line in the side's receipt (tools/e2e_duo.py notes them in the PYDEC output).
local M = {}

--- The vanilla base catch rate of `species` in this ROM, or nil, why.
function M.catch_rate(ctx, cfg, species)
    if type(species) ~= "number" or species < 1 then return nil, "no foe species" end
    if type(cfg.species_info) ~= "number" or type(cfg.stride) ~= "number" or type(cfg.catch_offset) ~= "number" then
        return nil, "no gSpeciesInfo address/stride/offset configured"
    end
    local ok, value = pcall(ctx.peek_u8, cfg.species_info + species * cfg.stride + cfg.catch_offset)
    if not ok or type(value) ~= "number" or value < 0 or value > 255 then return nil, "the catch-rate byte is unreadable" end
    return value
end

--- Hunt, skipping (RUN + hunt again, no ball) foes below the rate floor, then catch as ctx.catch does. Returns ctx.catch's results.
function M.catch(ctx, label)
    local cfg = ctx.D and ctx.D.rehunt_filter
    if not cfg then return ctx.catch(label) end
    if not ctx.hunt(label) then return nil, "no wild encounter" end
    local rehunts = 0
    while true do
        local species, swhy = ctx.enemy_species()
        local rate, rwhy = M.catch_rate(ctx, cfg, species)
        if not rate then
            ctx.log(ctx.fmt("REHUNT_FILTER unavailable species=%s rehunts=%d reason=%s -- NO filtering, catching as the unfiltered path does",
                tostring(species), rehunts, tostring(species and rwhy or swhy or rwhy)))
            break
        end
        if rate >= cfg.max_rate then
            ctx.log(ctx.fmt("REHUNT_FILTER species=%d catch_rate=%d rehunts=%d verdict=keep floor=%d", species, rate, rehunts, cfg.max_rate))
            break
        end
        if rehunts >= cfg.max_rehunts then
            ctx.log(ctx.fmt("REHUNT_FILTER species=%d catch_rate=%d rehunts=%d verdict=exhausted floor=%d", species, rate, rehunts, cfg.max_rate))
            return nil, ctx.fmt("REHUNT_FILTER exhausted: %d consecutive foes below catch rate %d (last species=%d rate=%d)",
                rehunts + 1, cfg.max_rate, species, rate)
        end
        rehunts = rehunts + 1
        ctx.log(ctx.fmt("REHUNT_FILTER species=%d catch_rate=%d rehunts=%d verdict=skip floor=%d", species, rate, rehunts, cfg.max_rate))
        local ran, why = ctx.run_away(label .. " rehunt-filter")
        if not ran then return nil, "REHUNT_FILTER: the escape failed: " .. tostring(why) end
        if not ctx.hunt(label .. " rehunt-filter") then return nil, "REHUNT_FILTER: re-hunt found no encounter" end
    end
    return ctx.catch(label, true)
end

return M
