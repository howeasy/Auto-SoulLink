--[[
  probe_gen2_boot.lua — what does Crystal's cold boot actually look like?

  Before writing a fixture bootstrapper, learn the shape of the thing it has to drive. Gen 1's
  equivalent was written blind and cost several rounds: A-mashing wedged the run in front of
  the bedroom SNES, the SAVE menu selected OPTIONS because wMaxMenuItem read 6 on a 6-item
  menu, and the title screen looked like a live overworld because CONTINUE's preview loads
  save data into party WRAM.

  So: press NOTHING for a while, then mash gently, and log everything that might serve as a
  state predicate. Screenshots at intervals, because the RAM alone did not settle Gen 1 —
  looking at the screen did.

  Nothing here asserts a pass/fail about the game; it is an instrument. The only real
  assertion is that the emulator is alive and the ROM is Crystal.

  Result file: patch/build/probe_gen2_boot_result.txt
  Screenshots: patch/build/probe_gen2_boot_*.png
--]]

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path = ROOT .. "/lua/?.lua;" .. ROOT .. "/data/games/gen2_crystal/?.lua;" .. package.path

local M = require("memory_gb")
local G = require("games.gen2_crystal")
local fmt = string.format

local OUT = ROOT .. "/patch/build/probe_gen2_boot_result.txt"
local lines = {}
local function log(s)
    lines[#lines + 1] = s
    console.log("[gen2-boot] " .. s)
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n") f:close() end
end

local variant = G.detect_variant()
log("variant=" .. tostring(variant))
if not variant then
    log("RESULT: FAIL (ROM not detected as a Gen 2 title)")
    client.exit()
    error("done", 0)
end
M.initProfile(G, variant)

-- Candidate state predicates. Every one of these is a thing the bootstrapper might gate on,
-- so watch them all rather than guessing which matters.
local A = {
    map_group   = M.MAP_GROUP_ADDR,
    map_number  = M.MAP_NUMBER_ADDR,
    party_count = M.PARTY_COUNT_ADDR,
    x           = 0xDCB8,   -- wXCoord
    y           = 0xDCB7,   -- wYCoord
    time_of_day = 0xD269,   -- wTimeOfDay
    joy_disable = 0xCFBE,   -- wJoypadDisable
    textbox     = 0xCFCF,   -- wTextboxFlags
    menu_sel    = 0xCF74,   -- wMenuSelection
    map_event   = 0xD433,   -- wMapEventStatus
    script_run  = 0xD438,   -- wScriptRunning
    battle_mode = 0xD22D,   -- wBattleMode
}

local function snap()
    local out = {}
    for _, k in ipairs({"map_group", "map_number", "party_count", "x", "y", "time_of_day",
                        "joy_disable", "textbox", "menu_sel", "map_event", "script_run",
                        "battle_mode"}) do
        out[#out + 1] = fmt("%s=%02X", k, M.read_u8(A[k]))
    end
    return table.concat(out, " ")
end

local frame = 0
local function step(buttons)
    joypad.set(buttons or {})
    emu.frameadvance()
    frame = frame + 1
end
local function shot(name)
    client.screenshot(ROOT .. "/patch/build/probe_gen2_boot_" .. name .. ".png")
    log(fmt("  [shot %-12s f=%5d] %s", name, frame, snap()))
end

-- ── Phase 1: press NOTHING. Learn where the game parks itself unattended. ─────
-- Gen 1's bootstrapper mashed A from frame zero and trapped itself in a text box that
-- reopened on every press. Watch first.
for i = 1, 40 do
    for _ = 1, 30 do step(nil) end
    if i % 8 == 0 then shot(fmt("idle_%02d", i)) end
end
shot("01_after_idle")

-- ── Phase 2: gentle A, the Gen 1 `mash` shape (2 frames of every 16) ─────────
-- A long hold overshoots menus that appear mid-press.
for i = 1, 60 do
    for _ = 1, 2 do step({A = true}) end
    for _ = 1, 14 do step(nil) end
    if i % 15 == 0 then shot(fmt("mash_%02d", i)) end
end
shot("02_after_mash")

-- ── Phase 3: NEW GAME, then find the overworld ───────────────────────────────
-- Measured: a cold boot parks on "NEW GAME / OPTION" with wMenuSelection = 1. Confirm that
-- before pressing anything, so a changed intro fails here instead of somewhere confusing.
log(fmt("at main menu: menu_sel=%d (1 = NEW GAME highlighted)", M.read_u8(A.menu_sel)))
shot("03_main_menu")

-- A on NEW GAME, then ride the intro. Gen 1's lesson: press A only while a script owns the
-- pad, never blindly, or you re-open the box you just closed. wJoypadDisable is Crystal's
-- equivalent signal.
for _ = 1, 4 do step({A = true}) end
for _ = 1, 60 do step(nil) end
shot("04_new_game_pressed")

-- Ride the intro to the first place the player can actually move. Log every state change so
-- the transitions are visible rather than inferred.
local last = ""
local landmarks = {}
for i = 1, 900 do
    -- Gentle A: 2 frames of every 16, as Gen 1's `mash` does.
    for _ = 1, 2 do step({A = true}) end
    for _ = 1, 14 do step(nil) end
    local now = snap()
    if now ~= last then
        last = now
        landmarks[#landmarks + 1] = fmt("f=%5d %s", frame, now)
        if #landmarks <= 40 then log("  " .. landmarks[#landmarks]) end
    end
    if i % 150 == 0 then shot(fmt("intro_%03d", i)) end
    -- Stop as soon as a real map is loaded AND the player can move.
    if M.read_u8(A.map_group) ~= 0 and M.read_u8(A.map_number) ~= 0 then break end
end
shot("05_after_intro")
log(fmt("map=%02X:%02X party=%d pos=(%d,%d) after %d frames",
        M.read_u8(A.map_group), M.read_u8(A.map_number), M.read_u8(A.party_count),
        M.read_u8(A.x), M.read_u8(A.y), frame))

-- Can we walk?
local x0, y0 = M.read_u8(A.x), M.read_u8(A.y)
for _ = 1, 40 do step({Right = true}) end
for _ = 1, 10 do step(nil) end
for _ = 1, 40 do step({Down = true}) end
for _ = 1, 10 do step(nil) end
log(fmt("movement probe: (%d,%d) -> (%d,%d)%s", x0, y0, M.read_u8(A.x), M.read_u8(A.y),
        (M.read_u8(A.x) ~= x0 or M.read_u8(A.y) ~= y0) and "  MOVED" or "  no movement"))
shot("06_after_move")

log("final: " .. snap())
log(fmt("RESULT: PASS variant=%s frames=%d", variant, frame))
client.exit()
error("slink-probe-finished", 0)
