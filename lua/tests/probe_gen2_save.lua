--[[
  probe_gen2_save.lua — the route out of the bedroom, and the SAVE menu's shape.

  Two things the Gen 2 fixture bootstrapper needs and cannot safely guess:

  1. HOW TO LEAVE THE BEDROOM. The cold boot lands on map 0x18:0x07 at (3,3)
     (probe_gen2_boot). Gen 1 learned that coordinate-targeted walking wedges in small rooms
     and that `seek_map` — rotate through directions until the MAP ID changes — is the better
     primitive, because stepping on a warp tile moves you before you reach the target square.

  2. WHICH MENU ROW IS SAVE. Gen 1 hardcoded SAVE_INDEX = 3 and got OPTIONS, because
     wMaxMenuItem read 6 on a 6-item menu and the row count was not the index. Crystal builds
     its START menu from flags — POKéDEX and POKéMON only appear once owned — so a row index
     is even less stable here. Read wMenuSelection, which is the ITEM ID, and log the whole
     menu as the cursor moves so the mapping is observed rather than assumed.

  Result file: patch/build/probe_gen2_save_result.txt
--]]

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path = ROOT .. "/lua/?.lua;" .. ROOT .. "/data/games/gen2_crystal/?.lua;" .. package.path

local M = require("memory_gb")
local G = require("games.gen2_crystal")
local fmt = string.format

local OUT = ROOT .. "/patch/build/probe_gen2_save_result.txt"
local lines = {}
local function log(s)
    lines[#lines + 1] = s
    console.log("[gen2-save] " .. s)
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n") f:close() end
end

local variant = G.detect_variant()
M.initProfile(G, variant)

local MAP_GROUP, MAP_NUM = M.MAP_GROUP_ADDR, M.MAP_NUMBER_ADDR
local X, Y = 0xDCB8, 0xDCB7
local MENU_SEL, JOY_DIS, TEXTBOX = 0xCF74, 0xCFBE, 0xCFCF
local PARTY_COUNT = M.PARTY_COUNT_ADDR

local frame = 0
local function step(b) joypad.set(b or {}) emu.frameadvance() frame = frame + 1 end
local function u8(a) return M.read_u8(a) end
local function mapid() return u8(MAP_GROUP) * 256 + u8(MAP_NUM) end
local function shot(n)
    client.screenshot(ROOT .. "/patch/build/probe_gen2_save_" .. n .. ".png")
end
local function hold(btn, frames)
    for _ = 1, (frames or 16) do step({[btn] = true}) end
    step(nil)
end

-- ── Ride the intro (measured in probe_gen2_boot: ~6240 frames) ───────────────
for _ = 1, 1200 do step(nil) end
for i = 1, 60 do
    for _ = 1, 2 do step({A = true}) end
    for _ = 1, 14 do step(nil) end
end
hold("A", 4)
for i = 1, 900 do
    for _ = 1, 2 do step({A = true}) end
    for _ = 1, 14 do step(nil) end
    if u8(MAP_GROUP) ~= 0 and u8(MAP_NUM) ~= 0 then break end
end
log(fmt("overworld at f=%d map=%04X pos=(%d,%d)", frame, mapid(), u8(X), u8(Y)))
if mapid() == 0 then log("RESULT: FAIL (never reached the overworld)") client.exit() error("x", 0) end
shot("01_bedroom")

-- ── 1. seek_map: rotate directions until the map id changes ─────────────────
local start_map = mapid()
local dirs = {"Down", "Left", "Up", "Right"}
local hops = {}
for hop = 1, 4 do
    local from = mapid()
    local moved = false
    for run = 1, 6 do
        for di = 1, 4 do
            hold(dirs[di], 14 + run * 6)
            for _ = 1, 8 do step(nil) end
            if mapid() ~= from then
                hops[#hops + 1] = fmt("hop %d: %04X -> %04X via %s (run=%d) pos=(%d,%d)",
                                      hop, from, mapid(), dirs[di], run, u8(X), u8(Y))
                log("  " .. hops[#hops])
                moved = true
                break
            end
        end
        if moved then break end
    end
    if not moved then
        log(fmt("  hop %d: stuck on %04X at (%d,%d)", hop, from, u8(X), u8(Y)))
        break
    end
    shot(fmt("02_hop%d", hop))
end
log(fmt("after seek: map=%04X pos=(%d,%d) f=%d", mapid(), u8(X), u8(Y), frame))

-- ── 2. The START menu: what is wMenuSelection for each row? ──────────────────
-- Open it, then walk the cursor down and record the ITEM ID at each stop. Crystal builds
-- this menu from flags, so the row->id mapping depends on progress and must be observed.
local function menu_open() return u8(TEXTBOX) ~= 0 or u8(MENU_SEL) ~= 0 end
local opened = false
for attempt = 1, 12 do
    hold("Start", 10)
    for _ = 1, 24 do step(nil) end
    if u8(MENU_SEL) ~= 0 then opened = true break end
end
log(fmt("START menu opened=%s menu_sel=%d textbox=%d", tostring(opened), u8(MENU_SEL), u8(TEXTBOX)))
shot("03_start_menu")

if opened then
    local seen = {}
    for i = 1, 10 do
        local sel = u8(MENU_SEL)
        seen[#seen + 1] = tostring(sel)
        hold("Down", 6)
        for _ = 1, 10 do step(nil) end
        if u8(MENU_SEL) == sel then break end   -- wrapped or stuck
    end
    log("wMenuSelection walking Down: " .. table.concat(seen, " -> "))
    shot("04_menu_walked")
end

log(fmt("party=%d map=%04X", u8(PARTY_COUNT), mapid()))
log(fmt("RESULT: PASS variant=%s frames=%d", variant, frame))
client.exit()
error("slink-probe-finished", 0)
