-- test_mailbox_ping.lua — autonomous BizHawk validation of the Phase-0 companion patch.
--
-- Load in EmuHawk with the PATCHED Radical Red ROM (patch/build/slink_RR.gba):
--   1. waits for the 'SLNK' beacon (proves the CallCallbacks frame hook runs)
--   2. sends a PING opcode and polls for the ack (proves the dispatcher works)
--   3. watches the mailbox for stray writes (proves 0x0203F800 is free at runtime)
-- then writes PASS/FAIL to ping_result.txt and exits. No GUI interaction needed.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ping_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function finish(ok)
    log(ok and "RESULT: PASS" or "RESULT: FAIL")
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit()
end

-- Use the unified System Bus domain (maps 0x02xxxxxx EWRAM and 0x08xxxxxx ROM).
local okd = pcall(memory.usememorydomain, "System Bus")
log("domain System Bus set=" .. tostring(okd))
pcall(function() client.speedmode(800) end)   -- run fast; this is a headless check

local MAX_WAIT = 2000      -- frames to wait for the beacon (~33s)
local beacon_frame = nil
local frame = 0

-- 1. wait for beacon
while frame < MAX_WAIT do
    emu.frameadvance(); frame = frame + 1
    if MB.present() then beacon_frame = frame; break end
end
if not beacon_frame then
    log("FAIL: no 'SLNK' beacon after " .. MAX_WAIT .. " frames (hook never ran?)")
    finish(false); return
end
log("beacon 'SLNK' seen at frame " .. beacon_frame ..
    string.format("  (sig=0x%08X abi=%d)", memory.read_u32_le(MB.BASE),
                  memory.read_u16_le(MB.BASE + 4)))

-- 2. send PING, poll for ack (allow several frames)
local s = MB.send(MB.OP_PING)
log("sent PING seq=" .. s)
local st, reason
for _ = 1, 30 do
    emu.frameadvance(); frame = frame + 1
    st, reason = MB.poll(s)
    if st then break end
end
if st == nil then
    log("FAIL: PING not acked within 30 frames")
    finish(false); return
end
log("PING ack: status=" .. st .. " (2=ok) reason=" .. reason ..
    "  opcode-cleared=" .. tostring(memory.read_u16_le(MB.BASE + 6) == 0))
if st ~= MB.ST_OK then
    log("FAIL: PING status not OK")
    finish(false); return
end

-- 3. corruption watch: beacon must stay stable over ~120 frames of gameplay idle
local stable = true
for _ = 1, 120 do
    emu.frameadvance(); frame = frame + 1
    if not MB.present() then stable = false; break end
end
log("beacon stable over 120 frames: " .. tostring(stable))
if not stable then
    log("FAIL: mailbox region clobbered (0x0203F800 not free)")
    finish(false); return
end

log("PING round-trip + free-region check all good at frame " .. frame)
finish(true)
