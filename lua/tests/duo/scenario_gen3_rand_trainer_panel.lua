-- Read-only trainer_brief observation while parked at the committed trainer
-- fixture in Viridian Forest or Emerald Route 102. Python reads the live server's per-player adapter
-- via a test-only status probe, then checks it against an independent ROM read.
return function(ctx)
    local helper = dofile(ctx.D.wt .. "/lua/tests/duo/scenario_gen3_rand_common.lua")
    local ok, why = helper.observe(ctx)
    if not ok then return false, why end
    if not ctx.wait_go("GO", 180) then return false, "no per-ROM trainer oracle release" end
    if ctx.writes() ~= 0 then return false, "trainer observation wrote cartridge RAM" end
    return ctx.save("randomized trainer panel")
end
