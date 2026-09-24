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
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("startmenu")
local ORDER = 0x020370F6      -- sStartMenuOrder (plan); u8[] of action ids
local COUNT = 0x020370F5      -- sNumStartMenuActions — located BY this probe (see the assert below)
local SCAN_LO, SCAN_HI = 0x020370E8, 0x02037110   -- window around it, to FIND the count byte

local function snap()
    local m = {}
    for a = SCAN_LO, SCAN_HI do m[a] = memory.read_u8(a) end
    return m
end
local function hexdump(m)
    local out = {}
    for a = SCAN_LO, SCAN_HI, 8 do
        local b = {}
        for i = 0, 7 do if a + i <= SCAN_HI then b[#b + 1] = string.format("%02X", m[a + i]) end end
        out[#out + 1] = string.format("    0x%08X  %s", a, table.concat(b, " "))
    end
    return table.concat(out, "\n")
end

t.boot({ state = "slink_overworld.State", beacon = 240 })

local before = snap()
t.log("before START:")
t.log(hexdump(before))

-- Open the start menu and let it settle.
t.tap("Start", 90)
local after = snap()
t.log("after START:")
t.log(hexdump(after))

-- The order array is written when the menu is built, so the changed bytes ARE the menu.
local changed = {}
for a = SCAN_LO, SCAN_HI do
    if before[a] ~= after[a] then changed[#changed + 1] = string.format("0x%08X %02X->%02X", a, before[a], after[a]) end
end
t.log("changed: " .. (#changed > 0 and table.concat(changed, "  ") or "(none)"))

if #changed == 0 then
    t.fail("nothing changed — the START press never opened the menu")
end

-- Read the order array itself and look for id 8.
local ids, has8 = {}, false
for i = 0, 12 do
    local v = memory.read_u8(ORDER + i)
    ids[#ids + 1] = string.format("%d", v)
    if v == 8 then has8 = true end
end
t.log(string.format("sStartMenuOrder @0x%08X = [%s]", ORDER, table.concat(ids, " ")))

-- FOUND by this probe's first run: the count sits in the byte immediately below the order array
-- (the classic sNumStartMenuActions / sStartMenuOrder pair), and a normal RR field menu is
-- exactly [1 2 3 4 5 6] — six rows ending in EXIT (id 6, whose action func is StartMenu_Exit
-- 0x0806F541). Asserted rather than dumped so a different RR build fails here loudly instead of
-- silently shifting the row the patch splices into.
local n = memory.read_u8(COUNT)
t.log(string.format("sNumStartMenuActions @0x%08X = %d", COUNT, n))
if n ~= 6 then
    t.fail("expected 6 actions in a normal field start menu, got " .. n)
end
for i = 1, 6 do
    if memory.read_u8(ORDER + i - 1) ~= i then
        t.fail("expected order [1 2 3 4 5 6]; this build differs — re-derive the splice index")
    end
end
if has8 then
    t.fail("id 8 IS present in a normal start menu — hijacking it would break a real row")
end
t.log("id 8 absent, order=[1..6], EXIT(6) last — splice index 5 is correct, slot 8 free to hijack")
t.finish()
