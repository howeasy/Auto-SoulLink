-- test_live_events.lua — LIVE validation of the EvRing event-push producers on a patched ROM.
-- The patch's frame hook watches gBattleResults' faint counters (0x03004F90: player @+0, foe @+1 —
-- they bump only AFTER Sturdy/Sash/Endure resolve) and pushes EV_PLAYER_FAINT / EV_FOE_FAINT /
-- EV_OUTCOME edges into the EvRing @0x0203FD10; Lua drains them via MB.events_drain().
--
-- In the in-battle savestate we SIMULATE counter bumps by writing the counters directly (the
-- producer keys off deltas, not who wrote them), then assert the right events come out, including
-- the multi-bump (delta > 1 -> one event per faint) and overflow (ring full -> drop + flag) paths.
--   EmuHawk.exe --lua=lua/tests/test_live_events.lua patch/build/slink_RR.gba

local WT  = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/events_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_battle.State"
local MB  = dofile(WT .. "/lua/mailbox.lua")

local PFC = 0x03004F90   -- gBattleResults.playerFaintCounter
local OFC = 0x03004F91   -- gBattleResults.foeFaintCounter

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end
local function abort(why) fails = fails + 1; log("ABORT: " .. why); finish() end

pcall(function() client.speedmode(400) end)
pcall(memory.usememorydomain, "System Bus")
local ok_ss = pcall(savestate.load, STATE)
for _ = 1, 30 do emu.frameadvance() end
if not MB.present() then abort("beacon never appeared (unpatched ROM?)  ss_loaded=" .. tostring(ok_ss)); return end

MB.events_init()
for _ = 1, 5 do emu.frameadvance() end
local evs = MB.events_drain()
check("ring quiet after init", #evs == 0, "#evs=" .. #evs)

-- Single player-faint bump -> exactly one EV_PLAYER_FAINT with the new counter value.
local p0 = memory.read_u8(PFC)
memory.write_u8(PFC, p0 + 1)
for _ = 1, 5 do emu.frameadvance() end
evs = MB.events_drain()
check("one player-faint event", #evs == 1 and evs[1].type == MB.EV_PLAYER_FAINT,
      string.format("#evs=%d type=%s", #evs, tostring(evs[1] and evs[1].type)))
check("event carries the counter", evs[1] and evs[1].a == (p0 + 1) % 256,
      string.format("a=%s want=%d", tostring(evs[1] and evs[1].a), (p0 + 1) % 256))

-- Multi-bump in one frame (double KO) -> one event per faint.
local o0 = memory.read_u8(OFC)
memory.write_u8(OFC, o0 + 2)
for _ = 1, 5 do emu.frameadvance() end
evs = MB.events_drain()
local foe = 0
for _, e in ipairs(evs) do if e.type == MB.EV_FOE_FAINT then foe = foe + 1 end end
check("delta 2 -> two foe-faint events", foe == 2, "#foe=" .. foe)

-- Overflow: 10 bumps without draining -> 8 kept, overflow flagged, then the ring recovers.
local p1 = memory.read_u8(PFC)
for i = 1, 10 do
    memory.write_u8(PFC, (p1 + i) % 256)
    emu.frameadvance()
end
for _ = 1, 3 do emu.frameadvance() end
local got, ovf = MB.events_drain()
check("ring kept 8 of 10", #got == 8, "#got=" .. #got)
check("overflow flagged + cleared", ovf == true)
memory.write_u8(PFC, (memory.read_u8(PFC) + 1) % 256)
for _ = 1, 5 do emu.frameadvance() end
got, ovf = MB.events_drain()
check("ring recovers after overflow", #got == 1 and ovf == false,
      string.format("#got=%d ovf=%s", #got, tostring(ovf)))

finish()
