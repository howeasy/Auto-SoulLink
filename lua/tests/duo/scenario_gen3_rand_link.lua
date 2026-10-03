-- Natural capture/link on the randomized pair. Reuse the existing ordinary-input
-- Route 1 driver and its native-save witnesses; no species or capture injection.
return function(ctx)
    local helper = dofile(ctx.D.wt .. "/lua/tests/duo/scenario_gen3_rand_common.lua")
    local ok, why = helper.observe(ctx)
    if not ok then return false, why end
    -- the disclosed natural REHUNT_FILTER (gen3_rehunt_filter.lua): skips very-low-catch-rate foes without spending a ball; Emerald
    -- runs this same function, so it is covered too
    local filter = dofile(ctx.D.wt .. "/lua/tests/duo/gen3_rehunt_filter.lua")
    return dofile(ctx.D.wt .. "/lua/tests/duo/scenario_gen3_link.lua")(ctx, { catch = filter.catch })
end
