--[[
  lua/tests/gen2_playthrough.lua — cold-boot Crystal to a usable SLink test save.

  Driven by tools/gen2_playthrough.py. Produces the battery save the Gen 2 live-test chain
  is built on:

      tests/fixtures/gen2/crystal_town.SaveRAM

  Same shape as gen1_playthrough.lua, and for the same reason: a .SaveRAM is plain SRAM and
  is NOT BizHawk-version-locked, so it survives emulator upgrades. This is a ONE-SHOT
  bootstrapper whose output is committed.

  IT NEVER WRITES SRAM. It writes WRAM and then drives the in-game SAVE menu, letting the
  game serialise and checksum for itself. That is not stylistic: Gen 2 VERIFIES a checksum
  on load (VerifyChecksum -> SaveFileCorruptedText) and Crystal keeps a SECOND copy in
  sBackupGameData that the loader can silently fall back to, so a hand-written SRAM image
  would either be rejected outright or — worse — load stale backup data that looks fine.
  Driving the menu sidesteps both.

  WHAT THE SAVE NEEDS:
    1. a party with >= 1 mon      (mon keys, faints, memorialize)
    2. Poke Balls in the Balls pocket (the nuzlocke gate reads the real pocket)
    3. encounter-free ground
    4. a committed save so the title screen offers CONTINUE

  WHERE IT PARKS: the player's bedroom, PLAYERS_HOUSE_2F (map 24:7).

  That is the map the intro ends on, so the fixture costs zero navigation. It also satisfies
  what "town" means for a fixture — mkstates.py's rule is encounter-free ground, and an
  interior has no encounters at all. Going outside would mean driving Mom's Pokegear scene,
  which ends in a DST yes/no that loops back on itself (maps/PlayersHouse1F.asm) — pure flake
  surface for a fixture that gains nothing by being outdoors.

  THERE IS NO `battle` TARGET, deliberately. Tall grass means Route 29, and New Bark Town's
  west exit is held by coord_events at (1,8)/(1,9) firing SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU
  until Elm hands over a starter — so a grass fixture has to drive Mom's scene AND the whole
  lab sequence. The only things that consume Gen 1's `battle` fixture are the playthrough /
  deadzone / dupes duo scenarios, which are declared `games: ("gen1",)`: those rules are
  enforced server-side and are generation-independent, so Gen 1 already covers them. Paying
  for a Gen 2 grass fixture would buy a second copy of coverage that exists.

  EVERYTHING IS RAM-REACTIVE. No phase waits on a frame count.
--]]

-- BizHawk reports `source == "main"` for a top-level --lua= script, so it CANNOT
-- self-locate; os.getenv does inherit from the launcher.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    or (debug.getinfo(1, "S").source or ""):match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(ROOT, "repo root unknown — launch via: python tools/gen2_playthrough.py")

package.path = ROOT .. "/lua/?.lua;" .. ROOT .. "/lua/games/?.lua;"
            .. ROOT .. "/data/games/gen2_crystal/?.lua;" .. package.path
package.loaded["memory_gb"] = nil
package.loaded["games.gen2_crystal"] = nil
local M = require("memory_gb")
local G = require("games.gen2_crystal")

local TARGET = os.getenv("SLINK_PLAY_TARGET") or "town"
local OUT    = ROOT .. "/patch/build/gen2_playthrough_result.txt"

local fmt = string.format
local log_lines = {}

local function emit(s)
    console.log(s)
    log_lines[#log_lines + 1] = s
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(log_lines, "\n") .. "\n"); f:close() end
end

-- client.exit() is ASYNC — the script keeps running after it, which in Gen 1 let a FAIL
-- verdict be followed by more log lines and then a PASS. error() unwinds immediately.
local function finish(pass, why)
    emit(fmt("RESULT: %s %s", pass and "PASS" or "FAIL", why or ""))
    client.exit()
    error("slink-playthrough-finished", 0)
end

local variant = G.detect_variant()
if not variant then finish(false, "ROM is not a Gen 2 title") end
M.initProfile(G, variant)

-- Test-only addresses the production profile has no reason to carry.
--
-- CRYSTAL ONLY, on purpose. Gold and Silver are in scope for CORRECTNESS (routing, profile
-- keys, encounter tables) but not for live testing — there are no dumps to test against.
-- Filling this table for them from pret would put addresses no one has ever executed next to
-- addresses proven on hardware, with nothing to tell them apart.
local A = {
    options     = 0xCFCC,   -- wOptions
    x           = 0xDCB8,   -- wXCoord
    y           = 0xDCB7,   -- wYCoord
    menu_sel    = 0xCF74,   -- wMenuSelection — holds a STARTMENUITEM_* id, not a row index
    textbox     = 0xCFCF,   -- wTextboxFlags
    joy_disable = 0xCFBE,   -- wJoypadDisable
    saved_once  = 0xD4B4,   -- wSavedAtLeastOnce
    time_of_day = 0xD269,   -- wTimeOfDay
    script_run  = 0xD438,   -- wScriptRunning
    map_event   = 0xD433,   -- wMapEventStatus
}
if variant ~= "crystal" and variant ~= "crystal_ap" then
    finish(false, fmt("variant %s has no live-test address table — Gold/Silver are "
                      .. "supported for correctness only (no dumps to verify against)",
                      variant))
end
if TARGET ~= "town" then
    finish(false, fmt("unknown target %q — Gen 2 builds only `town`; see this file's header "
                      .. "for why there is no grass fixture", TARGET))
end

emit(fmt("[gen2-play] variant=%s target=%s", variant, TARGET))

-- ── Primitives ───────────────────────────────────────────────────────────────
local frame = 0
local function step(buttons)
    joypad.set(buttons or {})
    emu.frameadvance()
    frame = frame + 1
end

local r8 = function(x) return memory.read_u8(x, "System Bus") end
local w8 = function(x, v) memory.write_u8(x, v, "System Bus") end

local function mapid() return r8(M.MAP_GROUP_ADDR) * 256 + r8(M.MAP_NUMBER_ADDR) end
local function shot(n) client.screenshot(ROOT .. "/patch/build/gen2_play_" .. n .. ".png") end

--- Wait pressing NOTHING. Gen 1's hard-won rule: A is dangerous as an idle action, because
--- anything that reopens a text box on A turns a wait into a permanent wedge.
local function idle(pred, max_frames)
    local start = frame
    while frame - start < max_frames do
        if pred and pred() then return true end
        step(nil)
    end
    return pred == nil or pred()
end

--- Gentle A: 2 frames out of every 16, checking `pred` every frame. A long hold overshoots
--- anything that appears mid-press, which is how Gen 1's naming menu got dismissed into the
--- letter grid. Only for the intro and cutscenes, never as a generic wait.
local function mash(pred, max_frames)
    local start = frame
    while frame - start < max_frames do
        if pred and pred() then return true end
        step(((frame - start) % 16 < 2) and {A = true} or nil)
    end
    return pred == nil or pred()
end

--- A button must be HELD to register; a 1-frame tap is swallowed. Release afterwards so the
--- next hold reads as a fresh press edge.
local function hold(btn, frames, stop)
    for _ = 1, (frames or 12) do
        if stop and stop() then return true end
        step({[btn] = true})
    end
    step(nil)
    return stop and stop() or false
end

-- ── Boot ─────────────────────────────────────────────────────────────────────
client.speedmode(6399)

-- MEASURED (lua/tests/probe_gen2_boot.lua on Crystal): pressing nothing for ~1200 frames
-- lands on the title screen; gentle A from there reaches "NEW GAME / OPTION" with
-- wMenuSelection = 1. wTimeOfDay and wBattleMode both read garbage transiently during the
-- transitions, so neither is usable as a boot predicate — this is why the probe existed.
idle(nil, 1200)
mash(function() return r8(A.menu_sel) == 1 end, 1200)
emit(fmt("[gen2-play] main menu at f=%d: menu_sel=%d (1 = NEW GAME)", frame, r8(A.menu_sel)))
shot("01_main_menu")

--- Ride the intro (gender, name, clock) until the player can actually WALK.
---
--- MEASURED THE HARD WAY. The first version of this broke out of the intro the moment
--- wMapGroup/wMapNumber went nonzero, saw 0x1807 at frame 5447, and then read 0x0000 a few
--- hundred frames later: the map registers go live during the intro's own scene loads, long
--- before the player exists. That is the same lie Gen 1 caught (wCurMap read 0x26 from frame
--- ~668, during Oak's speech, on a blank screen) and every cheaper proxy tells it —
--- wJoypadDisable also reads 0 through the dead window.
---
--- So require THREE things, in order, and treat any of them dropping out as "still in the
--- intro": a nonzero map, that map holding STILL for a stretch, and coordinates that
--- actually change when a direction is held. Only the last is real evidence, and the first
--- two exist to keep the walk test away from the intro's menus, where a stray Down would
--- move a cursor instead of a player.
local BEDROOM = 0x1807   -- PLAYERS_HOUSE_2F: map group 24, map 7
local MAP_SETTLE = 120   -- frames a map id must hold before the walk test is attempted

local function ride_intro(max_frames)
    local start, stable_since = frame, nil
    while frame - start < max_frames do
        local before = mapid()
        if before == 0 then
            stable_since = nil
        elseif not stable_since then
            stable_since = frame
        end

        if stable_since and frame - stable_since >= MAP_SETTLE then
            local x0, y0 = r8(A.x), r8(A.y)
            hold("Down", 24, function() return r8(A.x) ~= x0 or r8(A.y) ~= y0 end)
            if r8(A.x) ~= x0 or r8(A.y) ~= y0 then
                -- Confirm it STICKS. A coordinate can also change because a cutscene is
                -- moving the player, and the map can still be torn down afterwards.
                idle(nil, 90)
                if mapid() == before and before ~= 0 then
                    emit(fmt("[gen2-play] walkable at f=%d on %04X (%d,%d)",
                             frame, mapid(), r8(A.x), r8(A.y)))
                    return true
                end
                emit(fmt("[gen2-play] false start at f=%d: moved on %04X, then map became "
                         .. "%04X — still in the intro", frame, before, mapid()))
                stable_since = nil
            end
        end

        -- Gentle A: 2 frames out of every 32. A long hold overshoots anything that appears
        -- mid-press, and the intro is nothing but things that appear mid-press.
        for _ = 1, 2 do step({A = true}) end
        idle(nil, 30)
    end
    return false
end

if not ride_intro(40000) then
    finish(false, fmt("player never became walkable (map=%04X pos=%d,%d joy=0x%02X "
                      .. "script=0x%02X)", mapid(), r8(A.x), r8(A.y),
                      r8(A.joy_disable), r8(A.script_run)))
end
shot("02_after_intro")
if mapid() ~= BEDROOM then
    finish(false, fmt("intro ended on map %04X, expected the bedroom %04X — the intro "
                      .. "changed, so nothing below can be trusted", mapid(), BEDROOM))
end
emit(fmt("[gen2-play] in the bedroom at f=%d (%d,%d), timeOfDay=%d",
         frame, r8(A.x), r8(A.y), r8(A.time_of_day)))

--- Park on a tile where LEFT/RIGHT walking actually works, and refuse to build if none is
--- reachable.
---
--- Every gate proves it has booted into a live game by walking there and back, because that
--- is the only claim the CONTINUE preview cannot fake — it loads the save into the very WRAM
--- the party and coordinates live in, so party counts, map ids and safe-state flags all read
--- correct on a blank screen. The probe uses LEFT/RIGHT only: the title list is a vertical
--- menu, and a stray Down would slide the cursor off CONTINUE onto NEW GAME.
---
--- Which makes WHERE THIS FIXTURE PARKS a hard requirement rather than a detail. Measured:
--- ride_intro leaves the player at (3,4), where the bed is to the left and the desk to the
--- right — both horizontal moves are walls, and every gate hung for 17454 frames on a
--- perfectly live game. Certifying the tile here, once, beats debugging it in each gate.
local function can_walk_horizontally()
    local function round_trip(out)
        local back = (out == "Right") and "Left" or "Right"
        local x0, y0 = r8(A.x), r8(A.y)
        hold(out, 20, function() return r8(A.x) ~= x0 or r8(A.y) ~= y0 end)
        if r8(A.x) == x0 and r8(A.y) == y0 then return false end
        hold(back, 20, function() return r8(A.x) == x0 and r8(A.y) == y0 end)
        return r8(A.x) == x0 and r8(A.y) == y0
    end
    return round_trip("Right") or round_trip("Left")
end

local parked = false
for _, nudge in ipairs({"", "Up", "Up", "Down", "Down", "Down"}) do
    if nudge ~= "" then hold(nudge, 20) end
    if can_walk_horizontally() then parked = true break end
end
if not parked then
    finish(false, fmt("no tile with free horizontal movement near (%d,%d) — every gate "
                      .. "proves it booted by walking left/right, so a fixture parked "
                      .. "between two walls hangs all of them", r8(A.x), r8(A.y)))
end
emit(fmt("[gen2-play] parked at (%d,%d): left/right round trip verified",
         r8(A.x), r8(A.y)))

-- Fast text, SET battle style, battle scene off. Determinism, not speed:
-- constants/ram_constants.asm — TEXT_DELAY_MASK %111, NO_TEXT_SCROLL 4, BATTLE_SHIFT 6,
-- BATTLE_SCENE 7.
w8(A.options, 0xC1)   -- TEXT_DELAY_FAST | BATTLE_SHIFT | BATTLE_SCENE

-- ── Party write ──────────────────────────────────────────────────────────────
-- Write a level-5 Totodile into slot 0 rather than driving Elm's lab. The fixture needs "a
-- party with >= 1 mon"; it does not need the story beat that produced one.
--
-- 48-byte party_struct, straight from pret macros/ram.asm (box_struct + party tail):
--   +00 species  +01 item  +02..05 moves  +06 OTID(BE)  +08 exp(3)  +0B statExp(5x2)
--   +15..16 DVs  +17..1A PP  +1B happiness  +1C pokerus  +1D caughtTime|caughtLevel
--   +1E caughtGender|caughtLocation  +1F level
--   +20 status  +21 unused  +22 HP(BE)  +24 maxHP  +26 Atk  +28 Def  +2A Spd
--   +2C SpAtk  +2E SpDef
--
-- Note +2C AND +2E: Gen 2 split Special, so a Gen 1-shaped writer that stores one value
-- into both is wrong here. That split is exactly the trap waiting in applyPartyStats.
local TOTODILE   = 158        -- Gen 2 species ids are sequential NatDex
local MOVE_SCRATCH, MOVE_LEER = 0x0A, 0x2B

local function give_starter()
    local base = M.PARTY_BASE_ADDR
    for i = 0, M.PARTY_STRUCT_SIZE - 1 do w8(base + i, 0) end

    local otid = M.read_u16_be(M.PLAYER_ID_ADDR)
    w8(base + 0x00, TOTODILE)
    w8(base + 0x01, 0)                        -- no held item
    w8(base + 0x02, MOVE_SCRATCH)
    w8(base + 0x03, MOVE_LEER)
    M.write_u16_be(base + 0x06, otid)         -- OT id must match the player's
    w8(base + 0x15, 0x99)                     -- DVs: Atk 9 / Def 9
    w8(base + 0x16, 0x99)                     -- DVs: Spd 9 / Spc 9
    w8(base + 0x17, 35)                       -- PP Scratch
    w8(base + 0x18, 30)                       -- PP Leer
    w8(base + 0x1B, 70)                       -- happiness (base friendship)
    w8(base + 0x1C, 0)                        -- pokerus: none
    -- CAUGHT DATA. A zeroed block is not merely cosmetic: caught level 0 and location 0
    -- render as garbage on the summary screen, and Gen 2 reads this back when a mon is
    -- deposited. constants/pokemon_data_constants.asm:
    --   +1D  %11000000 caught time (1=MORN)   %00111111 caught level
    --   +1E  %10000000 caught gender (0=male) %01111111 caught location
    w8(base + 0x1D, 0x40 | 5)                 -- caught MORN at level 5
    w8(base + 0x1E, 0x01)                     -- male, location 1 (New Bark Town)
    w8(base + 0x1F, 5)                        -- level
    w8(base + 0x20, 0)                        -- status: healthy
    M.write_u16_be(base + 0x22, 20)           -- current HP
    M.write_u16_be(base + 0x24, 20)           -- max HP
    M.write_u16_be(base + 0x26, 11)           -- Attack
    M.write_u16_be(base + 0x28, 11)           -- Defense
    M.write_u16_be(base + 0x2A, 10)           -- Speed
    M.write_u16_be(base + 0x2C, 10)           -- Sp. Attack
    M.write_u16_be(base + 0x2E, 10)           -- Sp. Defense   <- NOT an alias of +0x2C

    w8(M.PARTY_SPECIES_ADDR, TOTODILE)
    w8(M.PARTY_SPECIES_ADDR + 1, 0xFF)        -- wPartyEnd terminator
    w8(M.PARTY_COUNT_ADDR, 1)

    -- Names live OUTSIDE the struct in parallel arrays, same as Gen 1. Charset is Gen 1's:
    -- 'A' = 0x80, terminator 0x50.
    local NICK = {0x93, 0x8E, 0x93, 0x8E, 0x83, 0x88, 0x8B, 0x84, 0x50}  -- TOTODILE
    for i = 0, 10 do
        w8(M.PARTY_OT_NAMES_ADDR + i, i < 3 and (0x91 + i) or 0x50)      -- short OT name
        w8(M.PARTY_NICKS_ADDR + i, NICK[i + 1] or 0x50)
    end
end

-- ── Balls ────────────────────────────────────────────────────────────────────
-- The nuzlocke gate reads the real Balls pocket. Crystal keeps balls in their OWN pocket
-- (wNumBalls), not the general item list, which is what BAG_COUNT_ADDR points at.
local POKE_BALL = 0x05        -- Gen 2 numbering: Gen 1's 0x04 is GREAT_BALL here

local function give_pokeballs(n)
    local count = r8(M.BAG_COUNT_ADDR)
    if count > M.BAG_MAX_ITEMS then count = 0 end
    for i = 0, count - 1 do
        if r8(M.BAG_ITEMS_ADDR + i * 2) == POKE_BALL then
            w8(M.BAG_ITEMS_ADDR + i * 2 + 1, n)
            return
        end
    end
    w8(M.BAG_ITEMS_ADDR + count * 2, POKE_BALL)
    w8(M.BAG_ITEMS_ADDR + count * 2 + 1, n)
    w8(M.BAG_ITEMS_ADDR + (count + 1) * 2, 0xFF)   -- terminator
    w8(M.BAG_COUNT_ADDR, count + 1)
end

give_starter()
give_pokeballs(10)
emit(fmt("[gen2-play] party=%d species=%d  balls: count=%d first=(0x%02X x%d) hasBalls=%s",
         r8(M.PARTY_COUNT_ADDR), r8(M.PARTY_SPECIES_ADDR), r8(M.BAG_COUNT_ADDR),
         r8(M.BAG_ITEMS_ADDR), r8(M.BAG_ITEMS_ADDR + 1), tostring(M.hasPokeballs())))
if not M.hasPokeballs() then
    finish(false, "hasPokeballs() is false straight after stocking the pocket — the "
                  .. "profile's ball_item_ids or BAG_* addresses are wrong")
end

-- ── Save ─────────────────────────────────────────────────────────────────────
-- sPokemonData's FIRST BYTE is sPartyCount (ram/sram.asm: sPokemonData:: ds
-- wPokemonDataEnd - wPokemonData, and wPokemonData:: opens with wPartyCount::). The save
-- block is in SRAM bank 1, so the flat CartRAM offset is 0x2000 + (0xA865 - 0xA000).
local SPARTY_COUNT_FLAT = 0x2000 + (0xA865 - 0xA000)   -- 0x2865

local function sram_party_count()
    local ok, v = pcall(memory.read_u8, SPARTY_COUNT_FLAT, "CartRAM")
    return ok and v or 0xFF
end

--- Open the START menu and PROVE it is live.
---
--- wMenuSelection holds its last value after the menu closes, so "it is nonzero" is not
--- evidence that a menu is up — it is evidence that one once was. Press Down and require the
--- value to CHANGE: only a live menu moves its own cursor.
local function open_start_menu()
    for _ = 1, 15 do
        hold("Start", 10)
        idle(nil, 24)
        local before = r8(A.menu_sel)
        hold("Down", 6)
        idle(nil, 10)
        if r8(A.menu_sel) ~= before then return true end
    end
    return false
end

--- Select SAVE.
---
--- wMenuSelection is a STARTMENUITEM_* ID, not a row index (engine/menus/start_menu.asm:
--- POKEDEX 0, POKEMON 1, PACK 2, STATUS 3, SAVE 4, OPTION 5, EXIT 6). Crystal builds the
--- menu from flags — POKEDEX and POKEMON only appear once owned — so a row index is
--- meaningless, which is precisely the mistake Gen 1 made when it hardcoded SAVE_INDEX = 3
--- and silently opened OPTIONS. Scanning for the id is correct before and after the party
--- write adds a POKEMON row.
local STARTMENUITEM_SAVE = 4

local function select_save(max_frames)
    local start = frame
    local seen = {}
    while frame - start < max_frames do
        local sel = r8(A.menu_sel)
        seen[#seen + 1] = tostring(sel)
        if sel == STARTMENUITEM_SAVE then
            emit("[gen2-play] menu ids walked: " .. table.concat(seen, " -> "))
            return true
        end
        hold("Down", 6)
        idle(nil, 10)
    end
    emit("[gen2-play] menu ids walked: " .. table.concat(seen, " -> "))
    return false
end

if not open_start_menu() then
    finish(false, fmt("START menu never opened (menu_sel=%d textbox=0x%02X joy=0x%02X)",
                      r8(A.menu_sel), r8(A.textbox), r8(A.joy_disable)))
end
shot("03_start_menu")
if not select_save(3000) then
    finish(false, fmt("never reached STARTMENUITEM_SAVE (stuck on id %d)", r8(A.menu_sel)))
end
shot("04_save_selected")

-- A to pick SAVE, then A through "would you like to save?" and the saving message. Stop the
-- moment SRAM shows a party — a fixed number of presses would either fall short or run on
-- into whatever menu opens next.
for i = 1, 12 do
    hold("A", 4)
    idle(nil, 60)
    emit(fmt("[gen2-play] save A#%d: menu_sel=%d savedOnce=%d sram_party=%s",
             i, r8(A.menu_sel), r8(A.saved_once),
             sram_party_count() == 0xFF and "empty" or tostring(sram_party_count())))
    if sram_party_count() == r8(M.PARTY_COUNT_ADDR) then break end
end
idle(nil, 300)
shot("05_after_save")

local sram_party = sram_party_count()
if sram_party ~= r8(M.PARTY_COUNT_ADDR) then
    finish(false, fmt("save did not commit: SRAM party=%s, WRAM party=%d, "
                      .. "wSavedAtLeastOnce=%d",
                      sram_party == 0xFF and "0xFF(empty)" or tostring(sram_party),
                      r8(M.PARTY_COUNT_ADDR), r8(A.saved_once)))
end

emit(fmt("[gen2-play] saved at f=%d: party=%d confirmed in SRAM, timeOfDay=%d, map=%04X",
         frame, sram_party, r8(A.time_of_day), mapid()))
finish(true, fmt("variant=%s target=%s party=%d balls=%d map=%04X timeOfDay=%d frames=%d",
                 variant, TARGET, sram_party, M.countPokeballs(), mapid(),
                 r8(A.time_of_day), frame))
