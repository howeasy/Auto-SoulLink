-- scenario_gen3_probe_flip.lua -- probe_protected_span_flip_gen3 (an observation, not a gate).
--
-- tools/e2e_duo.py boots A on the byte-pinned companion and B on the published companion with ONE byte flipped inside a protected span, off
-- every anchor. A flipped cartridge the launcher refuses never gets here: duo_gen3_main.lua records `PROBE_ADMISSION client=refused_at_launch`
-- and passes it (SLINK_DUO.probe_admission). A cartridge the client ADMITS reaches this module, which records what it announced; the runner
-- reads the server's verdict and releases it. Nothing here asserts admitted or refused, and nothing may write.
return function(ctx)
    local hello = ctx.last_sent("hello") or {}
    ctx.log(string.format("PROBE_CLIENT admitted artifact_kind=%s companion_abi=%s rom_sha1=%s", tostring(hello.artifact_kind),
                          tostring(hello.companion_abi), tostring(hello.rom_sha1)))
    if not ctx.wait_go("GO", 300) then return false, "the runner never released the probe" end
    ctx.frames(30)
    ctx.log("PROBE_PASSIVE writes=" .. ctx.writes())
    return true, "OBSERVED admitted: the client admitted the flipped cartridge; the server's verdict is the runner's observation"
end
