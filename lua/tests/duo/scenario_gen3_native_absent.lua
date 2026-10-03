-- scenario_gen3_native_absent.lua — native_absent_gen3 (RR only): the clean-RR REFUSAL PROOF.
--
-- Patch-first (owner 2026-10-02): the SLink companion patch is REQUIRED for Radical Red and a clean
-- (unpatched) cartridge is refused at launch (lua/gen3/entry.lua Entry.admit_routed). tools/e2e_duo.py
-- boots A on the companion build and B on the CLEAN dump (`rom_kind`), and flags B `expect_refused`.
--   B (clean): never reaches this module. lua/tests/duo/duo_gen3_main.lua passes it at launch ONLY if
--      lua/gen3/run.lua refused the cartridge with the "needs the SLink companion patch" verdict and
--      built no client (REFUSED_AT_LAUNCH, WRITES 0): no hello, no command, no native write, no save.
--   A (companion): boots and connects ALONE. After the go-file (written once B's refusal is on its
--      receipt) it settles; nothing may reach it and it may write nothing -- B's refusal links nothing,
--      commits nothing. Neither side saves (`no_save`).
local fmt = string.format

return function(ctx)
    if ctx.player == "b" then
        return false, "b is a refusal-proof side (expect_refused): the driver ends it at launch; it never runs a scenario"
    end
    if not ctx.wait_go() then return false, "no go-file" end
    ctx.frames(120)                       -- the post-hello traffic (link panel etc.) is over before the baseline
    local writes0, rx0 = ctx.writes(), ctx.rx_count()
    ctx.frames(600)
    local writes, rx = ctx.writes() - writes0, ctx.rx_count() - rx0
    ctx.log(fmt("PROBE_SETTLED writes=%d rx=%d", writes, rx))
    if writes ~= 0 then
        return false, fmt("the companion wrote %d time(s) while its partner was refused at launch", writes)
    end
    if rx ~= 0 then
        return false, fmt("the companion received %d command(s) while its partner was refused at launch", rx)
    end
    return true, "companion: booted alone; the refused clean partner linked nothing and caused no write"
end
