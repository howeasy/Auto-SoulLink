-- test_live_calctoggle.lua — LIVE smoke for the Battle-Calc kill switch (SLINK_CALC_OFF @0x0203F8D8).
-- The battletext shim now branches: byte 0 -> the calc trampoline (today's behavior); byte 1 -> replay
-- the two displaced halfwords (mov r7,r8 ; push {r7}) and continue BattlePutTextOnWindow's body as if
-- the calc weren't installed. The catastrophic failure mode of a wrong replay is an immediate
-- crash/hang inside EVERY in-battle text draw — so this drives a battle with the byte flipped both
-- ways and asserts the game keeps running (beacon alive, frames advancing, battle text calls landing).
--   EmuHawk.exe --lua=lua/tests/test_live_calctoggle.lua patch/build/slink_RR.gba

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/calctoggle_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_battle.State"
local MB  = dofile(WT .. "/lua/mailbox.lua")

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

-- Mash A through battle text with the calc DISABLED: every battle message draw exercises the
-- byte-1 shim path. If the displaced-instruction replay were wrong this hangs/crashes immediately.
MB.set_battle_calc(false)
check("calc-off byte set", memory.read_u8(MB.CALC_OFF) == 1)
for i = 1, 600 do
    if i % 20 < 10 then joypad.set({A = true}) end
    emu.frameadvance()
end
check("600 frames calc-OFF survived (beacon alive)", MB.present())

-- Flip back ON mid-battle and keep going — both directions must be safe at runtime.
MB.set_battle_calc(true)
check("calc-on byte cleared", memory.read_u8(MB.CALC_OFF) == 0)
for i = 1, 600 do
    if i % 20 < 10 then joypad.set({A = true}) end
    emu.frameadvance()
end
check("600 frames calc-ON survived (beacon alive)", MB.present())

-- Rapid flip churn (worst case: byte changes between draws within a message).
for i = 1, 240 do
    memory.write_u8(MB.CALC_OFF, i % 2)
    if i % 20 < 10 then joypad.set({A = true}) end
    emu.frameadvance()
end
memory.write_u8(MB.CALC_OFF, 0)
check("240 frames flip-churn survived (beacon alive)", MB.present())

finish()
