-- test_mailbox_absent.lua — negative control: on the UNPATCHED Radical Red ROM the companion beacon
-- must never appear, and lua/gen3/native.lua must refuse every op as "native absent" (PLAN §5), AND
-- the launcher must refuse the cartridge outright: patch-first (owner 2026-10-02) makes the companion
-- REQUIRED, so Entry.admit_routed returns the "needs the SLink companion patch" verdict for it.
-- Run with the *clean* RR ROM (tests/live/test_lua_gates.py stages it as patch/build/rr_clean.gba).
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("absent")
t.boot({ kind = "clean", beacon = false, speed = 800 })

local present_seen = false
for _ = 1, 600 do          -- well past the frame-13 mark where the real beacon appears
    t.step(nil)
    if t.present() then present_seen = true; break end
end
t.check("beacon never present on the clean ROM", not present_seen,
        string.format("word @0x%08X = 0x%08X (beacon 0x%08X)", t.P.BASE,
                      memory.read_u32_le(t.P.BASE), t.P.SIG))

local job, why = t.native:play_sound(25)
t.check("native refuses an op as absent", job == nil and why == "native absent", tostring(why))
local ok, swhy = t.native:service()
t.check("native:service reports absent", ok == nil and swhy == "native absent", tostring(swhy))
t.check("native reports idle (absence is safe for the Lua fallback)", t.native:idle() == true)

local routed, rwhy = t.routed()
t.check("the launcher refuses the clean RR: the companion patch is required",
        routed == nil and tostring(rwhy):find("needs the SLink companion patch", 1, true) ~= nil, tostring(rwhy))
t.finish()
