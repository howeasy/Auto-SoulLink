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
-- COLD BOOT (G5-GATES-LIVE 2026-09-24): the beacon is up by frame ~12, before the game has set its save
-- pointers, and writes:arm refuses until they are live ("safety.lua: invalid pointer: gPokemonStoragePtr").
-- The client never arms that early (it waits for the server hello), so step until an arm would succeed.
-- Idle alone never gets there (3000 frames, run 2); RR sets them when the main menu loads the save
-- (lua/tests/mkstate.lua:38-46), so pulse Start through the intro/title (probe: armable ~8 frames
-- after the first Start at the title). The field is never entered: no A, no CONTINUE.
do
    local never = function() return false end
    local ready = false
    for _ = 1, 3000 do
        ready = pcall(function() t.writes:arm("native", never) end)
        t.writes:disarm()
        if ready then break end
        t.step((_ % 32 == 0) and { Start = true } or nil)
    end
    if not ready then t.fail("save pointers live (native arm possible)", "frame " .. t.frame) end
    t.log(string.format("native arm possible at frame %d", t.frame))
end
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
