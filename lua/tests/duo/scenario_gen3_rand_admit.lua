-- Correct pair, other-player ROM, and mixed-kind legs are selected by the
-- runner's ACTUAL ROM launches. The server's verdict is the Python oracle.
return function(ctx)
    local helper = dofile(ctx.D.wt .. "/lua/tests/duo/scenario_gen3_rand_common.lua")
    local ok, why = helper.observe(ctx)
    if not ok then return false, why end
    if not ctx.wait_go("GO", 180) then return false, "no admission verdict release" end
    ctx.frames(30)
    ctx.log("RAND_PASSIVE writes=" .. ctx.writes() .. " phase=" .. ctx.phase)
    if ctx.writes() ~= 0 then return false, "admission-only leg wrote cartridge RAM" end
    return true, "admission leg observed; verdict belongs to server/PYDEC"
end
