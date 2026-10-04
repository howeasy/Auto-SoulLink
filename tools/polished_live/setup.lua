-- tools/polished_live/setup.lua -- build the SYNTH Polished save (O-33), launched by `harness.py setup`.
-- NATIVE: cold boot of the overlay, title, NEW GAME, initial options (left at defaults with B), Elm's speech,
-- clock/gender/name prompts (A), arrival in PLAYERS_HOUSE_2F, and the final START -> SAVE that writes SRAM.
-- SYNTH (written into WRAM between those two native steps, disclosed in docs/polished/LIVE_RESULTS.md):
-- the five-mon party (harness.py synth_party, OT = this save's wPlayerID/wPlayerName), the ball pocket
-- (99 Poke Balls) and the saved position (ROUTE_29 step 48,12: tall grass). Nothing else is written.
local L = dofile(os.getenv("SLINK_ROOT") .. "/tools/polished_live/pol_lib.lua")
local fmt = string.format
local synth = L.json.decode(L.slurp(assert(os.getenv("POL_SYNTH"), "POL_SYNTH unset")))
client.speedmode(1600)
L.log(fmt("[setup] cold boot, rom %s frame %d", gameinfo.getromhash(), emu.framecount()))

for _, name in ipairs({"OWPlayerInput", "SetInitialOptions.joypad_loop", "StartMenu", "SaveMenu", "SaveGameData",
                       "YesNoBox", "BlinkCursor", "NamingScreen", "TitleScreenMain", "MainMenu"}) do
    L.hook(name)
end

-- 1. native intro to the bedroom (PLAYERS_HOUSE_2F = group 24 #7)
if not L.to_overworld(24, 7, 120, 60000, "setup") then L.die("intro did not reach PLAYERS_HOUSE_2F") end
L.log(fmt("[setup] hits: title %d mainmenu %d options %d naming %d yesno %d", L.hits.TitleScreenMain,
          L.hits.MainMenu, L.hits["SetInitialOptions.joypad_loop"], L.hits.NamingScreen, L.hits.YesNoBox))
local id = {L.rw("wPlayerID"), L.rw("wPlayerID", 1)}
local name = L.wbytes("wPlayerName", 0, 8)
L.log(fmt("[setup] native player: id %02x%02x name %s party %d", id[1], id[2], L.hex(name), L.rw("wPartyCount")))

-- 2. SYNTH writes (WRAM), all while the overworld idles
local party = synth.party
L.ww("wPartyCount", 0, #party)
for slot, mon in ipairs(party) do
    local s = L.unhex(mon.struct_hex)
    s[7], s[8] = id[1], id[2]                                     -- party_struct ID (+6,+7) = the save's own ID
    for i, b in ipairs(s) do L.ww("wPartyMons", (slot - 1) * 48 + i - 1, b) end
    for i = 1, 8 do L.ww("wPartyMonOTs", (slot - 1) * 11 + i - 1, name[i]) end
    for i = 9, 11 do L.ww("wPartyMonOTs", (slot - 1) * 11 + i - 1, 0) end
    for i, b in ipairs(L.unhex(mon.nick_hex)) do L.ww("wPartyMonNicknames", (slot - 1) * 11 + i - 1, b) end
end
local balls = {#synth.balls}
for _, row in ipairs(synth.balls) do balls[#balls + 1] = row[1] balls[#balls + 1] = row[2] end
balls[#balls + 1] = 0xFF
for i, b in ipairs(balls) do L.ww("wNumBalls", i - 1, b) end
local pos = synth.position
local MODE = os.getenv("POL_POSMODE") or "warp"
L.ww("wMapGroup", 0, pos[1]) L.ww("wMapNumber", 0, pos[2]) L.ww("wXCoord", 0, pos[3]) L.ww("wYCoord", 0, pos[4])
if MODE == "warp" then
    -- exactly what Script_warp (engine/overworld/scripting.asm) writes after the four position bytes: the
    -- overworld loop then runs MAPSETUP_WARP, which loads the map header, tileset, blocks and objects natively
    L.ww("wDefaultSpawnpoint", 0, 0xFF)
    memory.write_u8(L.SYM.hMapEntryMethod[2], 0xF1, "System Bus")  -- MAPSETUP_WARP (map_setup_constants.asm)
    L.ww("wMapStatus", 0, 1)
end
L.log(fmt("[setup] SYNTH written (%s): party %d, balls %s, position %d:%d (%d,%d)", MODE, #party, L.hex(balls),
          pos[1], pos[2], pos[3], pos[4]))
if MODE == "warp" then
    if not L.to_overworld(pos[1], pos[2], 60, 3000, "setup-warp") then L.die("MAPSETUP_WARP did not land") end
end
L.log(fmt("[setup] loaded map header: tileset %d width %d height %d (Route 29 = tileset 1, 30x9)",
          L.rw("wMapTileset"), L.rw("wMapWidth"), L.rw("wMapHeight")))
client.screenshot(L.RUN .. "/before_save.png")
L.idle(4)

-- 3. native START -> SAVE -> YES
local f0 = emu.framecount()
while not L.after("StartMenu", f0) do
    if emu.framecount() - f0 > 600 then L.die("START menu never opened") end
    L.pulse("Start")
end
L.idle(30)
local count, save_row = L.rw("wMenuItemsList"), nil
local items = {}
for i = 1, count do
    items[i] = L.rw("wMenuItemsList", i)
    if items[i] == 4 then save_row = i end                           -- STARTMENUITEM_SAVE
end
L.log(fmt("[setup] start menu items %s, SAVE row %s", table.concat(items, ","), tostring(save_row)))
if not save_row then L.die("no SAVE row in the start menu") end
local f1 = emu.framecount()
while not L.after("SaveMenu", f1) do
    if emu.framecount() - f1 > 1200 then L.die("SAVE never selected") end
    L.pulse(L.rw("wMenuCursorY") == save_row and "A" or "Down")
end
local f2 = emu.framecount()
while not L.after("SaveGameData", f2) do
    if emu.framecount() - f2 > 1800 then L.die("SaveGameData never ran") end
    L.pulse("A")                                                     -- YES (default) on every save prompt
end
L.log(fmt("[setup] SaveGameData ran at frame %d", L.hit.SaveGameData))
L.idle(240)
-- close any remaining text/menu without touching another prompt
if not L.to_overworld(pos[1], pos[2], 60, 1800, "setup-after-save") then
    L.log("[setup] note: overworld not idle after save (menu/text still open?)")
end

-- 4. the SRAM image now carries a real save
local version = L.rc("sSaveVersion") * 256 + L.rc("sSaveVersion", 1)
local sum = 0
for at = L.cart("sGameData"), L.cart("sGameDataEnd") - 1 do sum = (sum + memory.read_u8(at, "CartRAM")) & 0xFFFF end
local stored = L.rc("sChecksum") + 256 * L.rc("sChecksum", 1)
L.log(fmt("[setup] SRAM sSaveVersion %04X checksum computed %04X stored %04X; wSavedAtLeastOnce %d",
          version, sum, stored, L.rw("wSavedAtLeastOnce")))
L.check("native save present (checksum matches)", sum == stored and version ~= 0 and version ~= 0xFFFF)
L.check("SYNTH party survived to the save", L.rw("wPartyCount") == #party, L.rw("wPartyCount"))
L.finish("polished-setup")
