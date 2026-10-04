-- tools/polished_live/control.lua -- map-corruption control, launched by `harness.py control`. NO SLink client and
-- no write: CONTINUE from the fixture, compare the loaded map header with Route 29's (data/maps/maps.asm: tileset
-- TILESET_JOHTO_TRADITIONAL = 1, map_constants 30x9 blocks), screenshot (confirmation only), walk the grass row.
local L = dofile(os.getenv("SLINK_ROOT") .. "/tools/polished_live/pol_lib.lua")
local fmt = string.format
client.speedmode(800)
for _, name in ipairs({"OWPlayerInput", "SetInitialOptions.joypad_loop", "BlinkCursor"}) do L.hook(name) end
L.log(fmt("[control] kind %s mode %s rom %s", os.getenv("POL_KIND"), os.getenv("POL_POSMODE"), gameinfo.getromhash()))
if not L.to_overworld(24, 3, 60, 8000, "control") then L.die("CONTINUE did not reach ROUTE_29") end
local ts, w, h = L.rw("wMapTileset"), L.rw("wMapWidth"), L.rw("wMapHeight")
L.log(fmt("[control] loaded header: tileset %d width %d height %d blocks ptr %02x%02x at (%d,%d)", ts, w, h,
          L.rw("wMapBlocksPointer", 1), L.rw("wMapBlocksPointer"), L.rw("wXCoord"), L.rw("wYCoord")))
client.screenshot(L.RUN .. "/continue.png")
L.check("map header is Route 29's (tileset 1, 30x9)", ts == 1 and w == 30 and h == 9, fmt("%d %dx%d", ts, w, h))
local f0, dir, steps, lastx = emu.framecount(), "Left", 0, L.rw("wXCoord")
while L.rw("wBattleMode") == 0 and emu.framecount() - f0 < 8000 do
    local x = L.rw("wXCoord")
    if x ~= lastx then steps = steps + 1 lastx = x end
    if x <= 46 then dir = "Right" elseif x >= 51 then dir = "Left" end
    if L.recent("BlinkCursor", 2) then L.pulse("A") else L.frame({[dir] = true}) end
end
local battle = L.rw("wBattleMode") ~= 0
L.idle(60)
client.screenshot(L.RUN .. "/after_walk.png")
L.check("a wild encounter in the grass within 8000 frames", battle,
        fmt("%d steps, %d frames, battle mode %d", steps, emu.framecount() - f0, L.rw("wBattleMode")))
L.finish("polished-control")
