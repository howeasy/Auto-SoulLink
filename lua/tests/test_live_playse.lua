-- test_live_playse.lua — LIVE validation of OP_PLAY_SE (native sound). The client now routes the
-- server's play_sound command to PlaySE via the patch (instead of the fragile Lua m4a SE1 RAM-poke).
-- Headless can't assert audio, so this proves the opcode runs + acks cleanly (no crash) for a real
-- SE id. Load with the PATCHED ROM:  EmuHawk.exe --lua=<this> patch/build/slink_RR.gba
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/playse_result.txt"
local MB  = dofile(WT .. "/lua/mailbox.lua")

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end

pcall(function() client.speedmode(400) end)
pcall(memory.usememorydomain, "System Bus")
local up = false
for _ = 1, 600 do emu.frameadvance(); if MB.present() then up = true; break end end
if not up then log("FAIL: beacon never appeared (unpatched ROM?)"); finish(); return end
log("beacon up")

local seq = MB.play_se(25)   -- SE_SUCCESS (a real FRLG sound-effect id)
check("MB.play_se returned a seq", seq ~= nil, "seq=" .. tostring(seq))
local acked, st = false, nil
if seq then
    for _ = 1, 60 do emu.frameadvance(); st = MB.poll(seq); if st then acked = true; break end end
end
check("opcode acked", acked, "status=" .. tostring(st))
check("ack is ST_OK", st == MB.ST_OK)
check("beacon still present (no crash)", MB.present())
finish()
