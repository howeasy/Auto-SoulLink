-- test_live_events.lua — LIVE validation of the EvRing event-push producers on a patched ROM.
-- The patch's frame hook watches gBattleResults' faint counters (0x03004F90: player @+0, foe @+1 —
-- they bump only AFTER Sturdy/Sash/Endure resolve) and pushes EV_PLAYER_FAINT / EV_FOE_FAINT /
-- EV_OUTCOME edges into the EvRing (profile native.EVR).
--
-- In the in-battle savestate we SIMULATE counter bumps by writing the counters directly (the
-- producer keys off deltas, not who wrote them), then assert the right events come out, including
-- the multi-bump (delta > 1 -> one event per faint) and overflow (ring full -> drop + flag) paths.
-- The client derives these edges from engine sites and never drains the ring, so the drain lives in
-- lua/tests/gen3_gatelib.lua (t.events_init / t.events_drain, writes through the raw poster's window,
-- card C5-4b). Battle savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("events")

local PFC = 0x03004F90   -- gBattleResults.playerFaintCounter
local OFC = 0x03004F91   -- gBattleResults.foeFaintCounter

t.boot({ state = "slink_battle.State", native = false, beacon = 30 })
local EV_PLAYER_FAINT, EV_FOE_FAINT = t.P.EV_PLAYER_FAINT, t.P.EV_FOE_FAINT

t.check("ring reset (events_init)", t.events_init(), t.last_service)
t.idle(5)
local evs = t.events_drain()
t.check("ring quiet after init", #evs == 0, "#evs=" .. #evs)

-- Single player-faint bump -> exactly one EV_PLAYER_FAINT with the new counter value.
local p0 = memory.read_u8(PFC)
memory.write_u8(PFC, p0 + 1)
t.idle(5)
evs = t.events_drain()
t.check("one player-faint event", #evs == 1 and evs[1].type == EV_PLAYER_FAINT,
        string.format("#evs=%d type=%s", #evs, tostring(evs[1] and evs[1].type)))
t.check("event carries the counter", evs[1] and evs[1].a == (p0 + 1) % 256,
        string.format("a=%s want=%d", tostring(evs[1] and evs[1].a), (p0 + 1) % 256))

-- Multi-bump in one frame (double KO) -> one event per faint.
local o0 = memory.read_u8(OFC)
memory.write_u8(OFC, o0 + 2)
t.idle(5)
evs = t.events_drain()
local foe = 0
for _, e in ipairs(evs) do if e.type == EV_FOE_FAINT then foe = foe + 1 end end
t.check("delta 2 -> two foe-faint events", foe == 2, "#foe=" .. foe)

-- Overflow: 10 bumps without draining -> 8 kept, overflow flagged, then the ring recovers.
local p1 = memory.read_u8(PFC)
for i = 1, 10 do
    memory.write_u8(PFC, (p1 + i) % 256)
    t.step(nil)
end
t.idle(3)
local got, ovf = t.events_drain()
t.check("ring kept 8 of 10", #got == 8, "#got=" .. #got)
t.check("overflow flagged + cleared", ovf == true and memory.read_u8(t.P.EVR + 2) == 0)
memory.write_u8(PFC, (memory.read_u8(PFC) + 1) % 256)
t.idle(5)
got, ovf = t.events_drain()
t.check("ring recovers after overflow", #got == 1 and ovf == false,
        string.format("#got=%d ovf=%s", #got, tostring(ovf)))
t.finish()
