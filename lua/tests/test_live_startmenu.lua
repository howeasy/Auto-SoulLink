-- test_live_startmenu.lua — READ-ONLY recon of RR's START menu action list.
--
-- The §6 plan hijacks start-menu action id 8 (a dead second PLAYER row that only
-- SetUpStartMenu_Link appends) rather than growing a 14th id, because the description and action
-- arrays abut exactly — desc[13] IS act[0].text — so a 14th id cannot own a description without
-- re-encoding compiled CFRU immediates.
--
-- That whole approach rests on id 8 being ABSENT from the menu a real player opens. Static
-- reasoning says so; this proves it on the live build, and pins sStartMenuOrder / the action
-- count at the same time. Writes nothing.
--
--   python tools/run_gate.py lua/tests/test_live_startmenu.lua --timeout 180
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/startmenu_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local ORDER = 0x020370F6      -- sStartMenuOrder (plan); u8[] of action ids
local COUNT = 0x020370F5      -- sNumStartMenuActions — located BY this probe (see the assert below)
local SCAN_LO, SCAN_HI = 0x020370E8, 0x02037110   -- window around it, to FIND the count byte

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function finish(ok)
    log(ok and "RESULT: PASS" or "RESULT: FAIL")
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit()
end

pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(400) end)

local function snap()
    local t = {}
    for a = SCAN_LO, SCAN_HI do t[a] = memory.read_u8(a) end
    return t
end
local function hexdump(t)
    local out = {}
    for a = SCAN_LO, SCAN_HI, 8 do
        local b = {}
        for i = 0, 7 do if a + i <= SCAN_HI then b[#b + 1] = string.format("%02X", t[a + i]) end end
        out[#out + 1] = string.format("    0x%08X  %s", a, table.concat(b, " "))
    end
    return table.concat(out, "\n")
end

assert(pcall(savestate.load, SDIR .. "/slink_overworld.State"), "no overworld savestate")
emu.frameadvance()
local up = false
for _ = 1, 240 do emu.frameadvance(); if MB.present() then up = true; break end end
log("beacon: " .. tostring(up))

local before = snap()
log("before START:")
log(hexdump(before))

-- Open the start menu and let it settle.
for f = 1, 90 do
    joypad.set(f <= 3 and { Start = true } or {})
    emu.frameadvance()
end
local after = snap()
log("after START:")
log(hexdump(after))

-- The order array is written when the menu is built, so the changed bytes ARE the menu.
local changed = {}
for a = SCAN_LO, SCAN_HI do
    if before[a] ~= after[a] then changed[#changed + 1] = string.format("0x%08X %02X->%02X", a, before[a], after[a]) end
end
log("changed: " .. (#changed > 0 and table.concat(changed, "  ") or "(none)"))

if #changed == 0 then
    log("FAIL: nothing changed — the START press never opened the menu")
    finish(false); return
end

-- Read the order array itself and look for id 8.
local ids, has8 = {}, false
for i = 0, 12 do
    local v = memory.read_u8(ORDER + i)
    ids[#ids + 1] = string.format("%d", v)
    if v == 8 then has8 = true end
end
log(string.format("sStartMenuOrder @0x%08X = [%s]", ORDER, table.concat(ids, " ")))

-- FOUND by this probe's first run: the count sits in the byte immediately below the order array
-- (the classic sNumStartMenuActions / sStartMenuOrder pair), and a normal RR field menu is
-- exactly [1 2 3 4 5 6] — six rows ending in EXIT (id 6, whose action func is StartMenu_Exit
-- 0x0806F541). Asserted rather than dumped so a different RR build fails here loudly instead of
-- silently shifting the row the patch splices into.
local n = memory.read_u8(COUNT)
log(string.format("sNumStartMenuActions @0x%08X = %d", COUNT, n))
if n ~= 6 then
    log("FAIL: expected 6 actions in a normal field start menu, got " .. n)
    finish(false); return
end
for i = 1, 6 do
    if memory.read_u8(ORDER + i - 1) ~= i then
        log("FAIL: expected order [1 2 3 4 5 6]; this build differs — re-derive the splice index")
        finish(false); return
    end
end
if has8 then
    log("FAIL: id 8 IS present in a normal start menu — hijacking it would break a real row")
    finish(false); return
end
log("id 8 absent, order=[1..6], EXIT(6) last — splice index 5 is correct, slot 8 free to hijack")
finish(true)
