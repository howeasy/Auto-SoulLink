-- tools/polished_live/explore.lua -- run-2 read-only explorations, launched by `harness.py explore` (no SLink client).
-- POL_EXPLORE=B: Pokemon Center 2F trade receptionist, DelayFrame-bridge stack samples per script phase.
-- POL_EXPLORE=C: the real Pokegear from the START menu, icon strip / cursor / tile usage per native card.
-- Boots the run-1 warp fixture (CONTINUE, native). SYNTH writes, each logged and disclosed in LIVE_RESULTS.md:
--   B: EVENT_GAVE_MYSTERY_EGG_TO_ELM (wEventFlags bit 33, the receptionist's checkevent) + the engine warp to
--      POKECENTER_2F (group 20 #1) step (5,3), the square Script_LeftCableTradeCenter walks the player to.
--   C: wPokegearFlags = $87 (POKEGEAR_OBTAINED_F + MAP/RADIO/PHONE card bits; EXPN bit 3 left clear).
-- Everything else is native input. Probes only read; logs go to files at milestones, never per frame.
local L = dofile(os.getenv("SLINK_ROOT") .. "/tools/polished_live/pol_lib.lua")
local fmt = string.format
local J = L.json
local WHICH = os.getenv("POL_EXPLORE") or "B"
client.speedmode(300)
L.log(fmt("[explore] %s boot frame %d rom %s", WHICH, emu.framecount(), gameinfo.getromhash()))

for _, name in ipairs({"OWPlayerInput", "StartMenu", "BlinkCursor", "YesNoBox", "TitleScreenMain", "MainMenu",
                       "SetInitialOptions.joypad_loop", "PokeGear", "InitPokegearTilemap", "FixPlayerEVsAndStats",
                       "CheckPartyForMail", "Special_WaitForLinkedFriend", "Special_WaitForLinkedFriend.done",
                       "Special_TryQuickSave", "SlinkTradeWaitGate", "SlinkTradeTimeoutGate", "SlinkTradeProposerService", "SlinkTradeExit"}) do
    L.hook(name)
end
local function write(path, s) local f = assert(io.open(path, "w")) f:write(s) f:close() end

if not L.to_overworld(24, 3, 60, 8000, "continue") then L.die("CONTINUE did not reach ROUTE_29") end

-- the engine's own warp (Script_warp bytes), never a bare position poke
local function warp(group, number, x, y)
    L.ww("wMapGroup", 0, group) L.ww("wMapNumber", 0, number) L.ww("wXCoord", 0, x) L.ww("wYCoord", 0, y)
    L.ww("wDefaultSpawnpoint", 0, 0xFF)
    memory.write_u8(L.SYM.hMapEntryMethod[2], 0xF1, "System Bus")  -- MAPSETUP_WARP
    L.ww("wMapStatus", 0, 1)
end

if WHICH == "B" then
    local ev = L.rw("wEventFlags", 4)
    L.ww("wEventFlags", 4, ev | 0x02)                                -- event 33 = byte 4 bit 1
    L.log(fmt("[explore] SYNTH wEventFlags+4 %02X -> %02X (EVENT_GAVE_MYSTERY_EGG_TO_ELM)", ev, L.rw("wEventFlags", 4)))
    warp(20, 1, 5, 3)
    L.log("[explore] SYNTH engine warp -> POKECENTER_2F (20:1) step (5,3)")
    if not L.to_overworld(20, 1, 60, 3000, "warp-pc2f") then L.die("MAPSETUP_WARP to POKECENTER_2F did not land") end
    L.log(fmt("[explore] header: tileset %d width %d height %d (map_constants POKECENTER_2F = 8x4); at (%d,%d)",
              L.rw("wMapTileset"), L.rw("wMapWidth"), L.rw("wMapHeight"), L.rw("wXCoord"), L.rw("wYCoord")))
    L.check("POKECENTER_2F header loaded (8x4)", L.rw("wMapWidth") == 8 and L.rw("wMapHeight") == 4)
    client.screenshot(L.RUN .. "/pc2f.png")

    -- bridge samples, tagged by phase; at most 300 per phase
    local phase = "overworld"
    local stacks, order, counts = {}, {}, {}
    L.hook("SlinkDelayFrameBridge", function(right_bank)
        if not right_bank then return end
        local n = counts[phase] or 0
        if n >= 300 then return end
        counts[phase] = n + 1
        local sp = emu.getregister("SP")
        local bytes = {}
        for i = 0, 31 do bytes[#bytes + 1] = L.bus((sp + i) & 0xFFFF) end
        local key = fmt("%s|%04X|%s|b%02X|s%d", phase, sp, L.hex(bytes), L.rombank(), L.bus(0xFF70) % 8)
        if not stacks[key] then stacks[key] = 0 order[#order + 1] = key end
        stacks[key] = stacks[key] + 1
    end)
    -- known-positive control: the idle overworld here must give the run-1 Route 29 chain
    L.idle(320)
    -- face the receptionist and talk
    for _ = 1, 6 do L.frame({Up = true}) end
    L.idle(10)
    local t0 = emu.framecount()
    phase = "talk"
    while not L.after("FixPlayerEVsAndStats", t0) do
        if emu.framecount() - t0 > 600 then L.die("the receptionist script never reached FixPlayerEVsAndStats") end
        L.pulse("A")
    end
    L.log(fmt("[explore] receptionist script past checkevent (FixPlayerEVsAndStats) at frame %d", L.hit.FixPlayerEVsAndStats))
    local f1 = emu.framecount()
    local seen_yesno = false
    while true do
        local f = emu.framecount()
        if f - f1 > 6000 then L.die("receptionist script did not finish") end
        local w, d = L.hit.SlinkTradeProposerService, L.hit.SlinkTradeExit
        local in_wait = w ~= nil and w > f1 and (d == nil or d < w)
        if in_wait then phase = "overlay_host_wait"
        elseif L.recent("YesNoBox", 2) or (L.hit.YesNoBox and not L.after("CheckPartyForMail", f1) and L.after("YesNoBox", f1)) then
            phase = "yesno" seen_yesno = true
        elseif L.rw("wScriptRunning") ~= 0 then
            phase = L.after("SlinkTradeExit", f1) and "after_wait" or "script"
        else phase = "overworld_after" end
        if phase == "overworld_after" and L.ow_idle() and L.after("SlinkTradeExit", f1) then break end
        if phase == "overlay_host_wait" then L.frame() else L.pulse("A") end   -- A = YES on the prompt, A closes text
        if phase == "overlay_host_wait" and not L.wait_shot then L.wait_shot = true client.screenshot(L.RUN .. "/please_wait.png") end
    end
    L.idle(60)
    L.unhook("SlinkDelayFrameBridge")
    L.log(fmt("[explore] milestones: FixPlayerEVsAndStats %s CheckPartyForMail %s WaitForLinkedFriend %s .done %s TryQuickSave %s YesNoBox %s",
              tostring(L.hit.FixPlayerEVsAndStats), tostring(L.hit.CheckPartyForMail), tostring(L.hit.Special_WaitForLinkedFriend),
              tostring(L.hit["Special_WaitForLinkedFriend.done"]), tostring(L.hit.Special_TryQuickSave), tostring(L.hit.YesNoBox)))
    L.log(fmt("[explore] overlay milestones: wait_gate %s service %s exit %s", tostring(L.hit.SlinkTradeWaitGate), tostring(L.hit.SlinkTradeProposerService), tostring(L.hit.SlinkTradeExit)))
    L.check("the trade prompt was answered YES (CheckPartyForMail ran)", L.hits.CheckPartyForMail > 0)
    L.check("overlay trade service entered and returned without a host", L.hits.SlinkTradeProposerService > 0 and L.hits.SlinkTradeExit > 0)
    L.check("trade gate skipped the native cable wait", L.hits.SlinkTradeWaitGate > 0 and L.hits.Special_WaitForLinkedFriend == 0)
    local out = {}
    for _, key in ipairs(order) do
        local ph, sp, hex, bank, svbk = key:match("^(.-)|(%x+)|(%x+)|b(%x+)|s(%d)$")
        out[#out + 1] = {phase = ph, sp = sp, bytes = hex, rombank = bank, svbk = tonumber(svbk), count = stacks[key]}
        L.log(fmt("[explore] STAGEB stack %s x%d", key, stacks[key]))
    end
    for ph, n in pairs(counts) do L.log(fmt("[explore] STAGEB phase %s: %d samples", ph, n)) end
    write(L.RUN .. "/stacks.json", J.encode(out))
    L.finish("explore-B")
end

-- ── C: Pokegear ────────────────────────────────────────────────────────────────────────────────
local flags0 = L.rw("wPokegearFlags")
L.ww("wPokegearFlags", 0, 0x87)
L.log(fmt("[explore] SYNTH wPokegearFlags %02X -> %02X", flags0, L.rw("wPokegearFlags")))
L.idle(4)
local s0 = emu.framecount()
while not L.after("StartMenu", s0) do
    if emu.framecount() - s0 > 600 then L.die("START menu never opened") end
    L.pulse("Start")
end
L.idle(30)
local row, items = nil, {}
for i = 1, L.rw("wMenuItemsList") do
    items[#items + 1] = L.rw("wMenuItemsList", i)
    if items[#items] == 7 then row = i end                           -- STARTMENUITEM_POKEGEAR
end
L.log(fmt("[explore] start menu items %s, POKEGEAR row %s", table.concat(items, ","), tostring(row)))
if not row then L.die("no POKEGEAR row in the START menu") end
local s1 = emu.framecount()
while not L.after("PokeGear", s1) do
    if emu.framecount() - s1 > 1200 then L.die("PokeGear never ran") end
    L.pulse(L.rw("wMenuCursorY") == row and "A" or "Down")
end
L.log(fmt("[explore] PokeGear entered at frame %d", L.hit.PokeGear))

local JOYPAD_STATE = {[0] = {[1] = true}, [1] = {[4] = true, [6] = true, [8] = true}, [2] = {[0x0a] = true}, [3] = {[0x0e] = true}}
local function vram_tiles(first, last, bank)
    local t = {}
    for id = first, last do
        local b = {}
        for i = 0, 15 do b[#b + 1] = memory.read_u8(bank * 0x2000 + 0x1000 + id * 16 + i, "VRAM") end
        t[fmt("%02X", id)] = L.hex(b)
    end
    return t
end
local cards, union = {}, {}
local function grab_tilemap()
    local tm = L.wbytes("wTilemap", 0, 360)
    for _, v in ipairs(tm) do union[v] = true end
    return tm
end
for card = 0, 3 do
    local c0 = emu.framecount()
    while not (L.rw("wPokegearCard") == card and JOYPAD_STATE[card][L.rw("wJumptableIndex")]) do
        if emu.framecount() - c0 > 1200 then L.die("card " .. card .. " never reached its joypad state") end
        L.pulse(card > 0 and "Right" or nil)
    end
    for i = 1, 90 do L.frame() if i % 30 == 0 then grab_tilemap() end end   -- dwell; union catches redraws
    local tm = grab_tilemap()
    local rows01, attr01 = {}, L.wbytes("wAttrmap", 0, 40)
    for i = 1, 40 do rows01[i] = tm[i] end
    local anim = L.wbytes("wSpriteAnim1", 0, 16)
    local oam = L.wbytes("wShadowOAM", 0, 160)
    client.screenshot(fmt("%s/pokegear_card%d.png", L.RUN, card))
    cards[#cards + 1] = {card = card, jumptable = L.rw("wJumptableIndex"), rows01 = L.hex(rows01), attr01 = L.hex(attr01),
                         tilemap = L.hex(tm), spriteanim1 = L.hex(anim), shadow_oam = L.hex(oam),
                         cursor_x = (anim[5] + anim[7]) & 0xFF, frame = emu.framecount()}
    L.log(fmt("[explore] STAGEC card %d (state %02X) rows0-1 %s | attr %s | anim1 %s cursor x %d", card,
              L.rw("wJumptableIndex"), L.hex(rows01), L.hex(attr01), L.hex(anim), cards[#cards].cursor_x))
end
local ids = {}
for v in pairs(union) do ids[#ids + 1] = v end
table.sort(ids)
local idhex = {}
for i, v in ipairs(ids) do idhex[i] = fmt("%02X", v) end
L.log("[explore] STAGEC tile ids in any card tilemap: " .. table.concat(idhex, " "))
write(L.RUN .. "/pokegear.json", J.encode({flags_before = flags0, cards = cards, union = idhex,
    vram0 = vram_tiles(0x50, 0x7F, 0), vram1 = vram_tiles(0x50, 0x7F, 1)}))
L.check("all four native cards visited", #cards == 4)
L.finish("explore-C")
