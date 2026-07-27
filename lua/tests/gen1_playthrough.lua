--[[
  lua/tests/gen1_playthrough.lua — cold-boot a Gen 1 ROM to a usable SLink test save.

  Driven by tools/gen1_playthrough.py. Produces the battery save that everything else in
  the Gen 1 live-test chain is built on:

      tests/fixtures/gen1/{red,blue,yellow}_{town,battle}.SaveRAM

  WHY A SAVE AND NOT A SAVESTATE: a .SaveRAM is plain SRAM and is NOT BizHawk-version-locked,
  so it survives emulator upgrades. mkstates.py regenerates savestates from it whenever the
  installed BizHawk changes. That makes this script a ONE-SHOT bootstrapper — six runs ever,
  three ROMs x two targets — so its flakiness costs a developer minutes once rather than
  breaking a build repeatedly.

  WHAT THE SAVE NEEDS, and nothing more:
    1. a party with >= 1 mon      (mon keys, faints, memorialize)
    2. Poke Balls in the bag      (the nuzlocke gate reads the real bag pocket)
    3. a position: encounter-free ground (town) or tall grass (battle)
    4. a committed SRAM checksum so the title screen offers CONTINUE

  It does NOT need the Pokedex, Oak's Parcel, badges or money. Note that "Oak gives you the
  Pokedex and five Poke Balls" is FIRERED behaviour — in RBY Oak gives no balls and you buy
  them at the Viridian Mart. Rather than drive a shop menu, we write (POKE_BALL, 5) straight
  into the plaintext bag: five lines, fully deterministic, and the in-game SAVE persists it.

  EVERYTHING IS RAM-REACTIVE. No phase waits on a frame count; each waits on a memory
  condition, because the rival battle alone makes fixed input sequences hopeless.

  SLINK_PLAY_TARGET = "town" | "battle"  (set by the Python launcher)
--]]

-- BizHawk reports `source == "main"` for a top-level --lua= script, so it CANNOT
-- self-locate; os.getenv does inherit from the launcher. Same idiom as every other gate:
-- SLINK_ROOT first, self-location only for a hand-loaded run from the Lua console.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    or (debug.getinfo(1, "S").source or ""):match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(ROOT, "repo root unknown — launch via: python tools/gen1_playthrough.py")

package.path = ROOT .. "/lua/?.lua;" .. ROOT .. "/lua/games/?.lua;"
            .. ROOT .. "/data/games/gen1_rby/?.lua;" .. package.path
package.loaded["memory_gb"] = nil
package.loaded["games.gen1_rby"] = nil
local M = require("memory_gb")
local G = require("games.gen1_rby")

local TARGET = os.getenv("SLINK_PLAY_TARGET") or "town"
local OUT    = ROOT .. "/patch/build/gen1_playthrough_result.txt"

local fmt = string.format
local log_lines = {}

local function emit(s)
    console.log(s)
    log_lines[#log_lines + 1] = s
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(log_lines, "\n") .. "\n"); f:close() end
end

-- client.exit() is ASYNC: the script keeps running after it, which is how a FAIL verdict
-- ended up followed by more log lines and then a PASS. error() unwinds immediately, so the
-- first verdict written is the only one.
local function finish(pass, why)
    emit(fmt("RESULT: %s %s", pass and "PASS" or "FAIL", why or ""))
    client.exit()
    error("slink-playthrough-finished", 0)
end

-- ── Variant address table ────────────────────────────────────────────────────
-- Test-only addresses (naming screen, coordinates, options, menu cursor) that the
-- production profile has no reason to carry. Yellow shifts the 0xD0xx-0xD3xx block by -1;
-- the 0xCCxx menu block is NOT shifted.
local A = {
    red = {
        naming_type = 0xD07D, options = 0xD355, x = 0xD362, y = 0xD361,
        battle_hp = 0xD015, battle_maxhp = 0xD023, enemy_hp = 0xCFE6,
        no_battle_steps = 0xD13C, bag_count = 0xD31D, bag_items = 0xD31E,
        player_name = 0xD158, cur_menu = 0xCC26, max_menu = 0xCC28,
        top_menu_y = 0xCC24, top_menu_x = 0xCC25,
        status5 = 0xD730, party_count = 0xD163, cur_map = 0xD35E,
        font_loaded = 0xCFC4, event_flags = 0xD747,
        in_battle = 0xD057, joy_ignore = 0xCD6B,
    },
    yellow = {
        naming_type = 0xD07C, options = 0xD354, x = 0xD361, y = 0xD360,
        battle_hp = 0xD014, battle_maxhp = 0xD022, enemy_hp = 0xCFE5,
        no_battle_steps = 0xD13B, bag_count = 0xD31C, bag_items = 0xD31D,
        player_name = 0xD157, cur_menu = 0xCC26, max_menu = 0xCC28,
        top_menu_y = 0xCC24, top_menu_x = 0xCC25,   -- 0xCCxx is not shifted
        status5 = 0xD72F, party_count = 0xD162, cur_map = 0xD35D,
        font_loaded = 0xCFC3, event_flags = 0xD746,
        in_battle = 0xD056, joy_ignore = 0xCD6B,
    },
}

local MAP = { PALLET = 0x00, ROUTE_1 = 0x0C, HOUSE_1F = 0x25, HOUSE_2F = 0x26, OAKS_LAB = 0x28 }
local POKE_BALL = 0x04
-- bits 0-2 = TEXT_DELAY_FAST(%001), bit 6 = BATTLE_SHIFT (SET, no switch prompt),
-- bit 7 = BIT_BATTLE_ANIMATION set = animations OFF (pret engine/battle/animations.asm:424).
local OPTIONS_FAST = 0xC1

local variant = G.detect_variant()
if not variant then finish(false, "ROM is not Gen 1 Red/Blue/Yellow") end
M.initProfile(G, variant)
local base = variant:gsub("_ap", "")
local a = A[base == "yellow" and "yellow" or "red"]
local is_yellow = (base == "yellow")

emit(fmt("[gen1-play] variant=%s target=%s", variant, TARGET))

-- ── Primitives ───────────────────────────────────────────────────────────────
local frame = 0
local function step(buttons)
    if buttons then joypad.set(buttons) end
    emu.frameadvance()
    frame = frame + 1
end

local r8 = function(x) return memory.read_u8(x, "System Bus") end
local w8 = function(x, v) memory.write_u8(x, v, "System Bus") end

local function in_field()
    -- Safe to drive: no script owns the joypad and no map-transition flag is up.
    return r8(a.joy_ignore) == 0 and (r8(a.status5) % 0x100) < 0x80
end

--- Wait for `pred` pressing NOTHING.
---
--- A is dangerous as an idle action: the player's bedroom has an SNES, and mashing A in
--- front of it reopens its text box forever — the player never moves, directions are
--- swallowed, and the run wedges at (3,6). Anywhere we are merely WAITING for the game to
--- settle, press nothing at all.
local function idle(pred, max_frames)
    local start = frame
    while frame - start < max_frames do
        if pred and pred() then return true end
        step(nil)
    end
    return pred == nil or pred()
end

--- Alternate A / Start / nothing on an 8-frame phase so a held button cannot auto-repeat
--- past a menu. Bails the instant `pred` is true.
--- ONLY for the intro and cutscenes, where text genuinely has to be advanced — never as a
--- generic wait once the player is on their feet (see `idle`).
--- Low duty cycle ON PURPOSE: A for 2 frames out of every 16, and `pred` checked every
--- frame. Holding A for a long run overshoots anything that appears mid-press — that is
--- how the RIVAL naming menu got dismissed into the letter grid while the player's own
--- menu (checked at the right moment) was handled correctly.
local function mash(pred, max_frames, buttons)
    local start = frame
    while frame - start < max_frames do
        if pred and pred() then return true end
        local phase = (frame - start) % 16
        local b = nil
        if phase < 2 then b = {A = true}
        elseif phase == 8 then b = {Start = true} end
        if buttons then b = buttons end
        step(b)
    end
    return pred == nil or pred()
end

--- Coordinate servo: step toward (tx,ty) on whichever axis is off, flipping axis when a
--- coordinate stops changing (furniture / ledge / wall). Handles wild battles en route.
local rig_battle  -- forward declaration

-- A direction must be HELD to walk. Tapping it only turns the player to face that way —
-- which is why a per-frame servo pivots in place forever. One overworld step is 16 frames;
-- hold a little longer than that, bailing early if the stop condition fires.
local STEP_FRAMES = 20

--- Advance a RUNNING SCRIPT's text, and only that.
---
--- wJoyIgnore is nonzero exactly while a script owns the joypad — Oak's stop scene, the
--- lab intro, the rival's demand. Those need A or they never finish. When wJoyIgnore is 0
--- we are free, and pressing A is actively harmful: in the bedroom it reopens the SNES
--- text box forever, which is what wedged every early run at (3,6).
local function advance_script()
    if r8(a.joy_ignore) ~= 0 then
        if frame % 16 < 2 then step({A = true}) else step(nil) end
    else
        step(nil)
    end
end

local function hold_dir(btn, frames, stop)
    for _ = 1, frames do
        if stop and stop() then return true end
        step({[btn] = true})
    end
    step(nil)   -- release, so the next hold registers as a fresh press
    return stop and stop() or false
end

local function walk_to(map, tx, ty, max_frames, label)
    local start, last, stall, axis = frame, nil, 0, "y"
    local moved, blocked = 0, 0
    local function arrived()
        return r8(a.cur_map) == map and r8(a.x) == tx and r8(a.y) == ty
    end
    while frame - start < max_frames do
        if r8(a.in_battle) ~= 0 then rig_battle(1800) end
        if not in_field() then advance_script() goto continue end
        local cm, cx, cy = r8(a.cur_map), r8(a.x), r8(a.y)
        if cm == map and cx == tx and cy == ty then return true end
        local key = cm * 65536 + cx * 256 + cy
        if key == last then
            stall = stall + 1
        else
            stall, last, moved, blocked = 0, key, moved + 1, 0
        end
        -- Two stalled holds means this axis is blocked (wall, furniture, ledge) — try the
        -- other one. mkstate.lua's amplitude sweep, made coordinate-driven.
        if stall > 2 then
            axis = (axis == "y") and "x" or "y"
            stall = 0
            blocked = blocked + 1
        end
        -- BOTH axes blocked: we are in a concave spot and heading straight at the target
        -- cannot work. Oak's Lab is the real case — the player lands at (5,3) with Oak
        -- above and the starter table to the right, so both "toward the target" moves are
        -- walls. Detour perpendicular for a couple of tiles, then resume the servo.
        if blocked >= 2 then
            local detours = (axis == "y") and {"Left", "Right"} or {"Up", "Down"}
            hold_dir(detours[(moved % 2) + 1], STEP_FRAMES * 2, arrived)
            blocked = 0
        end

        local btn = nil
        if axis == "y" and cy ~= ty then
            btn = (cy < ty) and "Down" or "Up"
        elseif axis == "x" and cx ~= tx then
            btn = (cx < tx) and "Right" or "Left"
        elseif cy ~= ty then
            btn = (cy < ty) and "Down" or "Up"
        elseif cx ~= tx then
            btn = (cx < tx) and "Right" or "Left"
        end
        if btn then
            hold_dir(btn, STEP_FRAMES, function()
                return arrived() or r8(a.in_battle) ~= 0 or not in_field()
            end)
        else
            step(nil)
        end
        ::continue::
    end
    -- N4: report WHERE it wedged. "never reached (x,y)" alone is useless for diagnosis.
    emit(fmt("[gen1-play] walk_to(%s map=0x%02X -> %d,%d) FAILED: at map=0x%02X (%d,%d) "
             .. "tiles_moved=%d joyIgnore=%d status5=0x%02X",
             label or "?", map, tx, ty, r8(a.cur_map), r8(a.x), r8(a.y),
             moved, r8(a.joy_ignore), r8(a.status5)))
    return false
end

--- Rig any battle to a one-turn win: top up our HP, drop the enemy to 1, and A-mash.
--- A-mash selects FIGHT (cursor default) then move slot 1, which is a damaging move for
--- every starter (Tackle / Scratch / Thundershock). This is a test fixture, not a run —
--- a real battle can crit, miss, speed-tie or be LOST, and any of those derails the script.
rig_battle = function(max_frames)
    local start = frame
    while frame - start < max_frames do
        if r8(a.in_battle) == 0 then return true end
        local mx = M.read_u16_be(a.battle_maxhp)
        if mx > 0 then M.write_u16_be(a.battle_hp, mx) end
        M.write_u16_be(a.enemy_hp, 1)
        step((math.floor(frame / 4) % 2 == 0) and {A = true} or nil)
    end
    return r8(a.in_battle) == 0
end

--- Leave the current room by SWEEPING, not by aiming at a tile.
---
--- Precise coordinate targeting wedges in small rooms: measured on Red's bedroom, the
--- player pivots at (3,6) with y wall-blocked while only x moves, and never reaches the
--- stairs tile. mkstate.lua solved the same problem by not caring where the exit is —
--- hold a direction, check whether the MAP changed, rotate through directions and grow
--- the run length. Exits are few and rooms are tiny, so a sweep finds them quickly.
local function seek_map(target, max_frames, label)
    local start = frame
    local dirs = {"Up", "Right", "Down", "Left"}
    local di, amp = 1, 1
    local function done() return r8(a.cur_map) == target end
    while frame - start < max_frames do
        if r8(a.in_battle) ~= 0 then rig_battle(1800) end
        if done() then
            idle(function() return in_field() end, 600)   -- let the map load settle
            return true
        end
        if not in_field() then advance_script() goto continue end
        if hold_dir(dirs[di], 12 * amp, done) then
            idle(function() return in_field() end, 600)
            return true
        end
        di = di + 1
        if di > #dirs then di, amp = 1, math.min(amp + 1, 6) end
        ::continue::
    end
    emit(fmt("[gen1-play] seek_map(%s -> 0x%02X) FAILED: still on 0x%02X at (%d,%d)",
             label or "?", target, r8(a.cur_map), r8(a.x), r8(a.y)))
    return false
end

--- Walk to a known WARP TILE and let it fire. Succeeds the moment the map changes, which
--- a coordinate-only walk_to cannot do (stepping onto the tile warps you away, so the
--- "am I at (x,y) on the old map" test can never become true).
--- Warp coordinates come straight from pret's data/maps/objects/<Map>.asm.
local function goto_warp(from_map, tx, ty, to_map, max_frames, label)
    local start, last, stall, axis = frame, nil, 0, "y"
    local function warped() return r8(a.cur_map) == to_map end
    while frame - start < max_frames do
        if warped() then
            idle(function() return in_field() end, 600)
            return true
        end
        if r8(a.in_battle) ~= 0 then rig_battle(1800) end
        if not in_field() then advance_script() goto continue end
        local cx, cy = r8(a.x), r8(a.y)
        local key = cx * 256 + cy
        if key == last then stall = stall + 1 else stall, last = 0, key end
        if stall > 2 then axis = (axis == "y") and "x" or "y"; stall = 0 end
        local btn
        if axis == "y" and cy ~= ty then btn = (cy < ty) and "Down" or "Up"
        elseif axis == "x" and cx ~= tx then btn = (cx < tx) and "Right" or "Left"
        elseif cy ~= ty then btn = (cy < ty) and "Down" or "Up"
        elseif cx ~= tx then btn = (cx < tx) and "Right" or "Left"
        else btn = "Down" end   -- standing on the tile: nudge to trigger the warp
        hold_dir(btn, STEP_FRAMES, warped)
        ::continue::
    end
    emit(fmt("[gen1-play] goto_warp(%s -> 0x%02X) FAILED: on 0x%02X at (%d,%d)",
             label or "?", to_map, r8(a.cur_map), r8(a.x), r8(a.y)))
    return false
end

local function wait_map(map, max_frames)
    -- No A: this is a plain wait, and the bedroom SNES punishes idle A presses.
    return idle(function() return r8(a.cur_map) == map and in_field() end, max_frames)
end

-- ── Party write ──────────────────────────────────────────────────────────────
-- Write a level-5 Squirtle straight into party slot 0 rather than driving the starter
-- cutscene.
--
-- The fixture needs "a party with >= 1 mon" — it does NOT need the story beat that
-- produced it, any more than it needs the Viridian Mart to own Poke Balls. Driving the
-- pickup means threading Oak's stop scene, the rival's demand, a table of three balls
-- flanked by two NPCs (the player lands at (5,3) with Oak above, the rival left and the
-- ball table right — every direction toward the ball is blocked), a YES/NO confirm, a
-- nickname prompt, and then a rigged rival battle. All of that is flake surface for a
-- result we can simply state.
--
-- Struct layout is the same 44 bytes the adapter already reads, verified against pret:
--   +00 species  +01 HP(BE)  +03 boxLevel  +04 status  +05/06 types  +07 catchRate
--   +08..0B moves  +0C OTID(BE)  +0E exp(3)  +11 statExp(5x2)  +1B/1C DVs  +1D..20 PP
--   +21 level  +22 maxHP  +24 Atk  +26 Def  +28 Spd  +2A Spc
local SQUIRTLE_INDEX = 177        -- INTERNAL index (NatDex 7); see G.INDEX_TO_NATDEX
local MOVE_TACKLE, MOVE_TAIL_WHIP = 33, 39
local TYPE_WATER = 0x15

local function give_starter()
    local base = M.PARTY_BASE_ADDR
    for i = 0, M.PARTY_STRUCT_SIZE - 1 do w8(base + i, 0) end

    local otid = M.read_u16_be(M.PLAYER_ID_ADDR)
    w8(base + 0x00, SQUIRTLE_INDEX)
    M.write_u16_be(base + 0x01, 20)          -- current HP
    w8(base + 0x03, 5)                        -- box level
    w8(base + 0x04, 0)                        -- status: healthy
    w8(base + 0x05, TYPE_WATER)
    w8(base + 0x06, TYPE_WATER)               -- monotype: both slots the same
    w8(base + 0x07, 45)                       -- catch rate
    w8(base + 0x08, MOVE_TACKLE)
    w8(base + 0x09, MOVE_TAIL_WHIP)
    M.write_u16_be(base + 0x0C, otid)         -- OT id must match the player's
    w8(base + 0x1B, 0x99)                     -- DVs: Atk 9 / Def 9
    w8(base + 0x1C, 0x99)                     -- DVs: Spd 9 / Spc 9
    w8(base + 0x1D, 35)                       -- PP Tackle
    w8(base + 0x1E, 30)                       -- PP Tail Whip
    w8(base + 0x21, 5)                        -- level
    M.write_u16_be(base + 0x22, 20)           -- max HP
    M.write_u16_be(base + 0x24, 10)           -- Attack
    M.write_u16_be(base + 0x26, 12)           -- Defense
    M.write_u16_be(base + 0x28, 10)           -- Speed
    M.write_u16_be(base + 0x2A, 10)           -- Special

    -- Species list and count, then the parallel name arrays (Gen 1 keeps names outside
    -- the struct — the same shape the rival-team swap has to honour).
    w8(M.PARTY_SPECIES_ADDR, SQUIRTLE_INDEX)
    w8(M.PARTY_SPECIES_ADDR + 1, 0xFF)
    w8(M.PARTY_COUNT_ADDR, 1)
    local NAME = {0x92, 0x98, 0x94, 0x8B, 0x8B, 0x50}    -- "SQUIRTLE" trimmed: S Q U I R @
    for i = 0, 10 do
        w8(M.PARTY_OT_NAMES_ADDR + i, i < 3 and (0x91 + i) or 0x50)   -- short OT name
        w8(M.PARTY_NICKS_ADDR + i, NAME[i + 1] or 0x50)
    end
    return true
end

-- ── Story flags ──────────────────────────────────────────────────────────────
-- Mark Oak's errand done so Pallet's north exit opens.
--
-- Needed only for the `battle` fixture, which has to reach Route 1's tall grass. Pallet's
-- script intercepts you at the north edge until EVENT_GOT_POKEBALLS_FROM_OAK is set, and
-- we deliberately never visit Oak (his starter dialogue traps a script-written party).
--
-- Bit indices from pret constants/event_constants.asm, counting const_skip:
--   0 FOLLOWED_OAK_INTO_LAB   6 PALLET_AFTER_GETTING_POKEBALLS
--   32 FOLLOWED_OAK_INTO_LAB_2 .. 39 OAK_APPEARED_IN_PALLET  (the whole Oak block)
-- wEventFlags is a bit array, so bit N lives at byte N/8, mask 1<<(N%8).
local function mark_oak_errand_done()
    local e = a.event_flags
    w8(e + 0, r8(e + 0) | 0x41)   -- bits 0 and 6
    -- 0xDF, not 0xFF: deliberately LEAVE bit 37 (EVENT_GOT_POKEDEX) clear. Setting it adds
    -- a POKeDEX row to the START menu, which shifts SAVE from index 3 to 4 and made the
    -- save silently select the wrong entry. Nothing here needs the dex.
    w8(e + 4, r8(e + 4) | 0xDF)
end

-- ── Bag write ────────────────────────────────────────────────────────────────
-- The nuzlocke gate reads the real bag pocket, so the save must contain balls. RBY has no
-- "Oak gives you balls" moment, and driving the Mart's shop menu buys only flakiness.
local function give_pokeballs(n)
    local count = r8(a.bag_count)
    if count > 20 then count = 0 end
    for i = 0, count - 1 do
        if r8(a.bag_items + i * 2) == POKE_BALL then
            w8(a.bag_items + i * 2 + 1, n)          -- already have them: just set quantity
            return true
        end
    end
    w8(a.bag_items + count * 2, POKE_BALL)
    w8(a.bag_items + count * 2 + 1, n)
    w8(a.bag_items + (count + 1) * 2, 0xFF)         -- terminator
    w8(a.bag_count, count + 1)
    return true
end

-- ── Save ─────────────────────────────────────────────────────────────────────
-- The START menu has NO POKeDEX entry before the parcel errand, so SAVE's index differs
-- from every walkthrough. It is always THIRD FROM THE END, with or without the Pokedex.
-- The SRAM copy of the party, so a save can be CONFIRMED rather than assumed. Gen 1's
-- main save block lives in SRAM bank 1; sPartyCount is System-Bus 0xAF2C there.
local function sram_party_count()
    M.SRAM_BANK = 1
    local ok, v = pcall(M.sram_read_u8, 0xAF2C)
    return ok and v or 0xFF
end

local function save_game(max_frames)
    local start = frame
    -- Every press here is HELD. 1-frame taps do not register — the same thing that made
    -- the player pivot instead of walk and left the naming cursor on NEW NAME.
    -- One Start press is not reliably picked up here, so RETRY until the game confirms a
    -- menu is actually up. wFontLoaded bit 0 is set whenever a text box or menu is loaded
    -- (same signal isInOverworld uses), which beats screenshotting or guessing at cursor
    -- values that also hold stale data from the previous menu.
    local function menu_open() return r8(a.font_loaded) % 2 == 1 end
    for _ = 1, 12 do
        if menu_open() then break end
        hold_dir("Start", 10, menu_open)
        idle(nil, 24)
    end
    emit(fmt("[gen1-play] START menu: cur=%d max=%d topY=%d topX=%d joy=0x%02X",
             r8(a.cur_menu), r8(a.max_menu), r8(a.top_menu_y), r8(a.top_menu_x),
             r8(a.joy_ignore)))
    client.screenshot(ROOT .. "/patch/build/save_startmenu.png")

    -- SAVE is index 3.
    --
    -- Do NOT compute this from wMaxMenuItem: it read 6 here while the menu on screen had
    -- only six entries (max would be 5), and "third from the end" therefore selected
    -- OPTION — confirmed by screenshotting the options screen. This fixture never obtains
    -- the POKeDEX (it skips Oak entirely), so the menu is always:
    --     POKeMON(0) ITEM(1) <NAME>(2) SAVE(3) OPTION(4) EXIT(5)
    local SAVE_INDEX = 3
    while frame - start < max_frames do
        if r8(a.cur_menu) == SAVE_INDEX then break end
        hold_dir("Down", 6, nil)
        idle(nil, 10)
    end
    emit(fmt("[gen1-play] SAVE selected: cur=%d (want %d)", r8(a.cur_menu), SAVE_INDEX))

    -- A to pick SAVE, then A on the "already a file / would you like to save?" prompts.
    for i = 1, 10 do
        hold_dir("A", 4, nil)
        idle(nil, 40)
        emit(fmt("[gen1-play] save A#%d: cur=%d max=%d font=0x%02X sram=%s",
                 i, r8(a.cur_menu), r8(a.max_menu), r8(a.font_loaded),
                 sram_party_count() == 0xFF and "empty" or tostring(sram_party_count())))
        if sram_party_count() ~= 0xFF then break end
    end
    idle(function() return in_field() end, 900)
    return sram_party_count()
end

-- sPlayerName lives at System-Bus 0xA598 in SRAM bank 1. A save that never committed fails
-- here rather than three tools downstream.
local function verify_save()
    M.SRAM_BANK = 1
    local ok, b = pcall(M.sram_read_u8, 0xA598)
    if not ok then return false, "SRAM unreadable" end
    if b == 0 or b == 0xFF then return false, fmt("sPlayerName blank (0x%02X)", b) end
    return true, fmt("sPlayerName[0]=0x%02X", b)
end

-- ── The run ──────────────────────────────────────────────────────────────────
client.speedmode(6399)

-- 0-4. Boot, then the two naming screens.
--
-- MEASURED (lua/tests/probe_gen1_boot.lua on Red): wCurMap reads 0x26 from frame ~668,
-- during the Oak intro and long before the player exists — so "am I in the bedroom yet"
-- is NOT a usable start condition. wNamingScreenType goes nonzero at ~2353.
--
-- The naming screen opens on a MENU (NEW NAME / RED / ASH / JACK) with the cursor on
-- NEW NAME. Pressing A there drops into the letter grid, which needs END selected to
-- escape — the probe showed a plain A-mash wedging there permanently. So: mash A only
-- until the screen appears, then immediately Down onto a PRESET and confirm.
-- The preset-name menu has an exact fingerprint. pret's DisplayIntroNameTextBox
-- (engine/movie/oak_speech/oak_speech2.asm:162) sets, right before HandleMenuInput:
--     wCurrentMenuItem = 0   wTopMenuItemX = 1   wTopMenuItemY = 2   wMaxMenuItem = 3
-- so "maxMenuItem == 3 and topY == 2 and topX == 1" identifies it unambiguously.
--
-- wNamingScreenType is NOT the signal — ChoosePlayerName sets it to 0 (NAME_PLAYER_SCREEN)
-- when it enters the LETTER GRID, i.e. it marks the thing we are trying to avoid.
-- Cursor 0 is "NEW NAME", which drops into that grid and needs END selected to escape;
-- an A-mash wedges there forever. So move to a preset first, and verify the cursor moved.
local function on_preset_menu()
    return r8(a.max_menu) == 3 and r8(a.top_menu_y) == 2 and r8(a.top_menu_x) == 1
end

local function handle_naming(which)
    -- Short window: if the menu is not up soon, the A-mash is already past it and into
    -- the letter grid, which finishes itself. Not worth waiting on.
    if not mash(on_preset_menu, 2400) then
        emit(fmt("[gen1-play] naming %d: preset menu missed — letter grid will self-finish",
                 which))
        return false
    end
    for _ = 1, 20 do step(nil) end             -- let the menu draw before touching it
    -- A 1-frame tap does not register (same reason a tapped direction only turns the
    -- player instead of walking). Hold, then VERIFY the cursor actually moved.
    for _ = 1, 8 do
        if r8(a.cur_menu) >= 1 then break end
        hold_dir("Down", 8, function() return r8(a.cur_menu) >= 1 end)
        for _ = 1, 8 do step(nil) end
    end
    emit(fmt("[gen1-play] naming screen %d: cursor=%d at frame %d",
             which, r8(a.cur_menu), frame))
    if r8(a.cur_menu) < 1 then
        return false   -- still on NEW NAME; pressing A would trap us in the letter grid
    end
    for _ = 1, 4 do
        hold_dir("A", 6, nil)
        for _ = 1, 12 do step(nil) end
        if not on_preset_menu() then break end
    end
    -- The screen closes once the name is accepted.
    return mash(function() return not on_preset_menu() end, 1800)
end

-- Take a preset if we happen to catch the menu — it is faster and gives a clean name — but
-- DO NOT gate the run on it. Mashing A through the letter grid also works: it fills the
-- name to its 7-character limit and confirms, which is why every earlier run still reached
-- the bedroom while this detection was "failing". The fixture does not care what the
-- trainer is called, so treating a missed menu as fatal was inventing a blocker.
handle_naming(1)
handle_naming(2)

-- The intro is over when the player can actually WALK. Every proxy for this lied:
--   wCurMap reads 0x26 from frame ~668, during Oak's speech (screenshot: blank screen);
--   wPlayerName already holds a letter before either naming screen;
--   wJoyIgnore/wStatusFlags5 are both 0 during the same dead window.
-- So test it directly — try to move and see whether the coordinates change. That is immune
-- to address guesswork, and it self-heals: if a text box is what is blocking movement
-- (the bedroom SNES), the A press below dismisses it and the next attempt succeeds.
local function wait_until_walkable(max_frames)
    local start = frame
    while frame - start < max_frames do
        local x0, y0 = r8(a.x), r8(a.y)
        hold_dir("Down", 24, function() return r8(a.x) ~= x0 or r8(a.y) ~= y0 end)
        if r8(a.x) ~= x0 or r8(a.y) ~= y0 then return true end
        -- Not walkable yet: nudge whatever is on screen (intro text, cutscene, a text box)
        -- with a SHORT press, then let it breathe before testing again.
        hold_dir("A", 2, nil)
        for _ = 1, 14 do step(nil) end
    end
    return false
end

if not wait_until_walkable(30000) then
    finish(false, fmt("player never became walkable (map=0x%02X pos=%d,%d joy=0x%02X)",
                      r8(a.cur_map), r8(a.x), r8(a.y), r8(a.joy_ignore)))
end
emit(fmt("[gen1-play] walkable at frame %d, map=0x%02X pos=(%d,%d) name0=0x%02X",
         frame, r8(a.cur_map), r8(a.x), r8(a.y), r8(a.player_name)))

-- 5. Bedroom: kill text speed and battle animations. Biggest determinism win available.
w8(a.options, OPTIONS_FAST)   -- fast text, SET style, animations off
emit(fmt("[gen1-play] in bedroom, wOptions=0x%02X", r8(a.options)))

-- 6-9. Bedroom -> 1F -> Pallet -> north edge, which fires Oak's stop script, -> lab.
-- Warp tiles from pret data/maps/objects/: RedsHouse2F stairs (7,1); RedsHouse1F door
-- (2,7); PalletTown -> OaksLab (12,11).
goto_warp(MAP.HOUSE_2F, 7, 1, MAP.HOUSE_1F, 4800, "bedroom stairs")
goto_warp(MAP.HOUSE_1F, 2, 7, MAP.PALLET, 4800, "front door")
-- Heading north out of Pallet trips Oak's stop script, which drives the player to the lab.
-- Pallet's north edge is a map CONNECTION, not a warp_event: stepping onto it heads for
-- Route 1, which is exactly what trips Oak's stop script. He then walks the player to his
-- lab, so the thing to wait for is the LAB map, not Route 1. Oak drives the player during
-- that cutscene, and in_field() keeps us from fighting him for the joypad.
-- DO NOT GO TO OAK'S LAB.
--
-- The only reason to visit was the starter, and give_starter() writes that directly.
-- Going there is actively HARMFUL: Oak's stop script drags you in and parks you in the
-- "which POKeMON do you want?" dialogue (confirmed by screenshot), which the written party
-- does not satisfy. The player then cannot move and START will not open the menu, so the
-- save never happens. Oak only intercepts if you walk NORTH toward Route 1, so simply
-- staying in Pallet skips the entire sequence.
give_starter()
give_pokeballs(5)
w8(a.no_battle_steps, 0)                -- don't let the step-pacer suppress encounters
emit(fmt("[gen1-play] party=%d  bag: count=%d first=(0x%02X x%d)",
         r8(a.party_count), r8(a.bag_count), r8(a.bag_items), r8(a.bag_items + 1)))

-- 14/15. Park on the ground this fixture is for.
--   town   = encounter-free, for overworld/box/memorialize scenarios
--   battle = tall grass, for anything that needs a wild encounter
if TARGET == "battle" then
    mark_oak_errand_done()
    emit(fmt("[gen1-play] story flags set: 0x%02X 0x%02X",
             r8(a.event_flags), r8(a.event_flags + 4)))
    -- Step east of the doorway first, then north — otherwise the servo walks back inside.
    walk_to(MAP.PALLET, 10, 6, 4800, "east of the house")
    goto_warp(MAP.PALLET, 10, 0, MAP.ROUTE_1, 12000, "Pallet -> Route 1")
    emit(fmt("[gen1-play] on ROUTE_1 at (%d,%d)", r8(a.x), r8(a.y)))
else
    walk_to(MAP.PALLET, 5, 6, 2400, "pallet home tile")
    emit(fmt("[gen1-play] in PALLET at (%d,%d)", r8(a.x), r8(a.y)))
end

if r8(a.party_count) < 1 then finish(false, "no party mon — starter phase failed") end

local saved_party = save_game(6000)
-- CONFIRM the save reached SRAM. A 32KB SaveRAM file can exist and still be effectively
-- empty (measured: 138 nonzero bytes, sPartyCount 0xFF) when the menu drive silently
-- failed, so "a file appeared" is not evidence that anything was written.
if saved_party ~= r8(a.party_count) then
    finish(false, fmt("save did not commit: SRAM party=%s, WRAM party=%d",
                      saved_party == 0xFF and "0xFF(empty)" or saved_party, r8(a.party_count)))
end
emit(fmt("[gen1-play] saved at frame %d (party=%d confirmed in SRAM)", frame, saved_party))
finish(true, fmt("variant=%s target=%s party=%d frames=%d",
                 variant, TARGET, r8(a.party_count), frame))
