-- test_mailbox_ping.lua — the companion patch's basic liveness, on the PATCHED Radical Red ROM:
--   1. the 'SLNK' beacon appears (proves the CallCallbacks frame hook runs);
--   2. a PING posted through the mailbox is acked ST_OK (proves the dispatcher works);
--   3. the beacon stays stable over ~120 frames of idle (proves 0x0203F800 is free at runtime).
-- PING is a patch-only op the client never sends, so it goes through lua/tests/gen3_gatelib.lua's
-- test-only raw poster (native.lua's ABI and write window, card C5-4b). Cold boot.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("ping")

-- 1. wait for the beacon (t.boot fails the gate if it never comes)
t.boot({ native = false, beacon = 2000, speed = 800 })
t.log(string.format("beacon 'SLNK' seen at frame %d  (sig=0x%08X abi=%d)", t.frame,
                    memory.read_u32_le(t.P.BASE), memory.read_u16_le(t.P.BASE + 4)))

-- 2. PING, poll for the ack (allow several frames)
local r = t.raw_wait("OP_PING", {}, nil, 30)
t.check("PING acked within 30 frames", r ~= nil, t.receipt_str(r))
t.check("PING status OK", t.acked_ok(r), t.receipt_str(r))
t.check("opcode cleared by the dispatcher", memory.read_u16_le(t.P.BASE + 6) == 0)

-- 3. corruption watch: the beacon must stay stable over ~120 frames of idle
local stable = true
for _ = 1, 120 do
    t.step(nil)
    if not t.present() then stable = false; break end
end
t.check("beacon stable over 120 frames (0x0203F800 free at runtime)", stable)
t.finish()
