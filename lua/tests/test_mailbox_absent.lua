-- test_mailbox_absent.lua — negative control: on an UNPATCHED ROM the mailbox beacon
-- must never appear, so MB.present() stays false and the client falls back to the
-- RAM-poke path (plan §3 graceful degradation). Load with the *clean* RR ROM.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/absent_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function finish(ok)
    log(ok and "RESULT: PASS" or "RESULT: FAIL")
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit()
end

pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(800) end)

local present_seen = false
for _ = 1, 600 do          -- well past the frame-13 mark where the real beacon appears
    emu.frameadvance()
    if MB.present() then present_seen = true; break end
end
log("MB.present() ever true on clean ROM: " .. tostring(present_seen))
log(string.format("word @0x0203F800 = 0x%08X (expected != 0x4B4E4C53)",
                  memory.read_u32_le(MB.BASE)))
finish(not present_seen)
