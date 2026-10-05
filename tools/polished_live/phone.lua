-- pol-phone: Stage 1 live check of the Pokegear Phone card's virtual SLink contact (DEV evidence).
-- Boots run 1's warp fixture (CONTINUE, native; the fixture sits on ROUTE_29, reached by the engine's own warp).
-- SYNTH writes, each logged: wPokegearFlags = $87 (Pokegear + map/radio/phone cards) and wPhoneList per scenario.
-- Everything else is scripted native input; probes only read.
local L = dofile(os.getenv("SLINK_ROOT") .. "/tools/polished_live/pol_lib.lua")
local fmt = string.format
local J = L.json
local CM = dofile(L.ROOT .. "/data/games/polished_crystal/charmap.lua").glyphs
local ARROW = 240   -- charmap glyph for the filled cursor arrow (charmap.lua glyphs[240])
client.speedmode(400)
L.log(fmt("[phone] boot frame %d rom %s", emu.framecount(), gameinfo.getromhash()))

for _, n in ipairs({"OWPlayerInput", "StartMenu", "SetInitialOptions.joypad_loop", "PokeGear",
                    "PokegearPhoneContactSubmenu", "PokegearPhoneContactSubmenu.Delete", "MakePhoneCallFromPokegear",
                    "SlinkPhone_CallGate", "SlinkPhone_CallerName", "SlinkPhone_CanDelete", "SlinkPhone_CountSetBits",
                    "YesNoBox"}) do
    L.hook(n)
end
local function write(path, s) local f = assert(io.open(path, "w")) f:write(s) f:close() end
local evidence = {scenarios = {}}

local function press(btn, settle) for _ = 1, 2 do L.frame({[btn] = true}) end L.idle(settle or 24) end
local function wait(cond, bound, what)
    local f0 = emu.framecount()
    while not cond() do
        if emu.framecount() - f0 > bound then L.die(what) end
        L.frame()
    end
end
local function row(y)
    local s = {}
    for i, b in ipairs(L.wbytes("wTilemap", y * 20, 20)) do s[i] = CM[b] or "?" end
    return table.concat(s)
end
local function rows(a, b) local o = {} for y = a, b do o[#o + 1] = fmt("%02d|%s|", y, row(y)) end return o end
local function screen() return table.concat(rows(0, 17), "\n") end
local function count(text, pat) local n = 0 for _ in text:gmatch(pat) do n = n + 1 end return n end
local function plist() return L.hex(L.wbytes("wPhoneList", 0, 5)) end
local function state() return L.rw("wJumptableIndex") end
local function cur() return L.rw("wPokegearPhoneCursorPosition"), L.rw("wPokegearPhoneScrollPosition") end
local function shot(name) client.screenshot(fmt("%s/%s.png", L.RUN, name)) end

if not L.to_overworld(24, 3, 60, 8000, "continue") then L.die("CONTINUE did not reach ROUTE_29") end
local flags0 = L.rw("wPokegearFlags")
L.ww("wPokegearFlags", 0, 0x87)
local list0 = plist()
L.log(fmt("[phone] SYNTH wPokegearFlags %02X -> %02X; native wPhoneList at boot %s", flags0, L.rw("wPokegearFlags"), list0))

local function open_phone()
    local s0 = emu.framecount()
    while not L.after("StartMenu", s0) do
        if emu.framecount() - s0 > 600 then L.die("START menu never opened") end
        L.pulse("Start")
    end
    L.idle(30)
    local r
    for i = 1, L.rw("wMenuItemsList") do if L.rw("wMenuItemsList", i) == 7 then r = i end end  -- STARTMENUITEM_POKEGEAR
    if not r then L.die("no POKEGEAR row in the START menu") end
    local s1 = emu.framecount()
    while not L.after("PokeGear", s1) do
        if emu.framecount() - s1 > 1200 then L.die("PokeGear never ran") end
        L.pulse(L.rw("wMenuCursorY") == r and "A" or "Down")
    end
    local c0 = emu.framecount()
    while not (L.rw("wPokegearCard") == 2 and state() == 0x0a) do               -- POKEGEARCARD_PHONE, PHONEJOYPAD
        if emu.framecount() - c0 > 1200 then L.die("the Phone card never reached its joypad state") end
        L.pulse(L.rw("wPokegearCard") < 2 and "Right" or nil)
    end
    L.idle(40)
end
local function close_pokegear()
    local f0, since = emu.framecount(), nil
    while true do
        if emu.framecount() - f0 > 1500 then L.die("could not leave the Pokegear") end
        if L.ow_idle() then
            since = since or emu.framecount()
            if emu.framecount() - since > 40 then return end
            L.frame()
        else since = nil L.pulse("B") end
    end
end
local function cursor_to(index)                   -- index = scroll + cursor, 0-based, pressing Up/Down one at a time
    for _ = 1, 40 do
        local c, s = cur()
        if c + s == index then return end
        press(c + s < index and "Down" or "Up", 12)
    end
    L.die("cursor never reached index " .. index)
end
local function list_text() return table.concat(rows(3, 11), "\n") end

-- one SLink entry: A on the row -> Call/Cancel (no Delete) -> A on Call -> entry text, no call -> B -> list, cursor intact
local function open_slink(tag, index)
    cursor_to(index)
    local c, s = cur()
    local calls0, gate0, sub0 = L.hits.MakePhoneCallFromPokegear, L.hits.SlinkPhone_CallGate, L.hits.PokegearPhoneContactSubmenu
    local caller0, list_before = L.rw("wCurCaller"), plist()
    press("A", 30)
    L.check(tag .. ": A opened the contact submenu", L.hits.PokegearPhoneContactSubmenu == sub0 + 1)
    local menu = table.concat(rows(6, 11), "\n")
    shot(tag .. "_submenu")
    L.check(tag .. ": submenu offers Call and Cancel", menu:find("Call", 1, true) and menu:find("Cancel", 1, true), menu)
    L.check(tag .. ": submenu offers no Delete (Mom/Elm style)", not menu:find("Delete", 1, true), menu)
    L.check(tag .. ": wPokegearPhoneSubmenuCursor on Call", L.rw("wPokegearPhoneSubmenuCursor") == 0)
    press("A", 10)
    wait(function() return L.hits.SlinkPhone_CallGate > gate0 end, 300, tag .. ": Call never reached SlinkPhone_CallGate")
    L.idle(40)
    local box = table.concat(rows(12, 17), "\n")
    shot(tag .. "_entry")
    local sel = L.rw("wPokegearPhoneSelectedPerson")
    L.check(tag .. ": the SLink entry text box shows", box:find("SLink is linked.", 1, true) ~= nil, box)
    L.check(tag .. ": no phone call placed (MakePhoneCallFromPokegear not entered)", L.hits.MakePhoneCallFromPokegear == calls0)
    L.check(tag .. ": wCurCaller untouched", L.rw("wCurCaller") == caller0, fmt("%02X", L.rw("wCurCaller")))
    L.check(tag .. ": selected person is the virtual id 38", sel == 38, sel)
    press("B", 10)
    wait(function() return state() == 0x0a end, 300, tag .. ": B did not return to PHONEJOYPAD")
    L.idle(40)
    local back = screen()
    shot(tag .. "_back")
    local c2, s2 = cur()
    L.check(tag .. ": back on the list, cursor/scroll intact", c2 == c and s2 == s, fmt("%d/%d -> %d/%d", c, s, c2, s2))
    L.check(tag .. ": back text is the native prompt", back:find("Whom do you want", 1, true) ~= nil)
    L.check(tag .. ": wPhoneList untouched by the SLink entry", plist() == list_before, plist())
    L.check(tag .. ": the cursor arrow sits on the SLink row", L.rw("wTilemap", (4 + 2 * c2) * 20 + 1) == ARROW
            and row(4 + 2 * c2):find("SLink:", 1, true) ~= nil, row(4 + 2 * c2))
    return {menu = menu, entry_box = box, back = back, cursor = {c2, s2}}
end

local function scenario(tag, bytes, expect_rows, on_screen)
    local before = plist()
    for i = 1, 5 do L.ww("wPhoneList", i - 1, bytes[i]) end
    L.log(fmt("[phone] SYNTH wPhoneList %s -> %s (%s)", before, plist(), tag))
    open_phone()
    local text = list_text()
    shot(tag .. "_list")
    L.log(fmt("[phone] %s list (wNumSetBits %d):\n%s", tag, L.rw("wNumSetBits"), text))
    for y, want_text in pairs(expect_rows) do
        L.check(fmt("%s: row %d reads %q", tag, y, want_text), row(y):find(want_text, 1, true) ~= nil, row(y))
    end
    on_screen = on_screen or 1   -- s4: the 5th row is below the fold until the native scroll
    L.check(fmt("%s: %d SLink row(s) on the first screen", tag, on_screen), count(text, "SLink:") == on_screen)
    return {tag = tag, phone_list = plist(), num_set_bits = L.rw("wNumSetBits"), list = text}
end

-- S0: no native contact -> SLink is the only row
local s0 = scenario("s0", {0, 0, 0, 0, 0}, {[4] = "SLink:", [5] = "   Soul Link"})
s0.entry = open_slink("s0", 0)
close_pokegear()
evidence.scenarios[#evidence.scenarios + 1] = s0

-- S1: Mom only
local s1 = scenario("s1", {0x01, 0, 0, 0, 0}, {[4] = "Mom:", [6] = "SLink:", [7] = "   Soul Link"})
s1.entry = open_slink("s1", 1)
close_pokegear()
evidence.scenarios[#evidence.scenarios + 1] = s1

-- S4: Mom, Prof.Elm, Joey, Wade -> SLink is the 5th row, reached by the native scroll
local s4 = scenario("s4", {0x09, 0xC0, 0, 0, 0}, {[4] = "Mom:", [6] = "Prof.Elm:", [8] = "Joey:", [10] = "Wade:"}, 0)
cursor_to(4)
local c, s = cur()
local scrolled = list_text()
shot("s4_scrolled")
L.check("s4: Down past the 4th row scrolls (cursor 3, scroll 1)", c == 3 and s == 1, fmt("%d/%d", c, s))
L.check("s4: exactly one SLink row after the scroll", count(scrolled, "SLink:") == 1)
L.check("s4: scrolled list ends with the SLink row", row(10):find("SLink:", 1, true) ~= nil and row(4):find("Prof.Elm:", 1, true) ~= nil, scrolled)
s4.scrolled = scrolled
s4.entry = open_slink("s4", 4)
close_pokegear()
evidence.scenarios[#evidence.scenarios + 1] = s4

-- S3: Mom, Prof.Elm, Joey -> SLink entry, then DELETE Joey natively, then a native call to Mom (control)
local s3 = scenario("s3", {0x09, 0x40, 0, 0, 0}, {[4] = "Mom:", [6] = "Prof.Elm:", [8] = "Joey:", [10] = "SLink:"})
s3.entry = open_slink("s3", 3)
cursor_to(2)
local sub0, del0, yn0 = L.hits.PokegearPhoneContactSubmenu, L.hits["PokegearPhoneContactSubmenu.Delete"], L.hits.YesNoBox
press("A", 30)
local menu = table.concat(rows(6, 11), "\n")
shot("s3_joey_submenu")
L.check("s3: Joey's submenu offers Delete", L.hits.PokegearPhoneContactSubmenu == sub0 + 1 and menu:find("Delete", 1, true) ~= nil, menu)
press("Down", 12)
press("A", 10)
wait(function() return L.hits.YesNoBox > yn0 end, 300, "s3: Delete never asked YES/NO")
L.idle(30)
shot("s3_delete_prompt")
press("A", 10)                                                      -- YES (the native default row)
wait(function() return plist() ~= "0940000000" end, 600, "s3: YES never deleted Joey")
L.idle(40)
local after = list_text()
shot("s3_after_delete")
L.log("[phone] s3 after deleting Joey:\n" .. after)
L.check("s3: Joey's native bit cleared (wPhoneList 0900000000)", plist() == "0900000000", plist())
L.check("s3: list after delete = Mom, Prof.Elm, SLink", row(4):find("Mom:", 1, true) and row(6):find("Prof.Elm:", 1, true)
        and row(8):find("SLink:", 1, true) and not row(10):find("%a"), after)
L.check("s3: the SLink row neither vanished nor duplicated", count(after, "SLink:") == 1)
L.check("s3: wNumSetBits = 3 (2 native + SLink)", L.rw("wNumSetBits") == 3, L.rw("wNumSetBits"))
s3.after_delete = after
-- control: the native call path still rings Mom
cursor_to(0)
local calls0 = L.hits.MakePhoneCallFromPokegear
press("A", 30)
press("A", 10)                                                      -- Call
wait(function() return L.hits.MakePhoneCallFromPokegear > calls0 end, 600, "s3: Mom's call never reached MakePhoneCallFromPokegear")
L.idle(60)
shot("s3_mom_call")
L.check("s3: a native contact still places a real call", L.rw("wCurCaller") == 1, L.rw("wCurCaller"))
local f0 = emu.framecount()
while state() ~= 0x0a do
    if emu.framecount() - f0 > 3000 then L.die("Mom's call never hung up") end
    L.pulse("A")
end
L.idle(60)
if L.hits.PokegearPhoneContactSubmenu > sub0 + 2 then press("B", 30) end   -- a trailing A opened a submenu: cancel it
L.check("s3: back on the Phone card after the call", state() == 0x0a)
close_pokegear()
evidence.scenarios[#evidence.scenarios + 1] = s3

evidence.pokegear_flags_before = flags0
evidence.phone_list_at_boot = list0
evidence.hits = L.hits
write(L.RUN .. "/phone.json", J.encode(evidence))
L.finish("pol-phone")
