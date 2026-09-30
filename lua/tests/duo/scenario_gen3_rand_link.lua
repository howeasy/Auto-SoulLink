-- Natural capture/link on the randomized pair. Reuse the existing ordinary-input
-- Route 1 driver and its native-save witnesses; no species or capture injection.
return function(ctx)
    local helper = dofile(ctx.D.wt .. "/lua/tests/duo/scenario_gen3_rand_common.lua")
    local ok, why = helper.observe(ctx)
    if not ok then return false, why end
    return dofile(ctx.D.wt .. "/lua/tests/duo/scenario_gen3_link.lua")(ctx)
end
