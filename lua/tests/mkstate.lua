-- mkstate.lua — regenerate the SLink savestates for whatever BizHawk is installed.
--
-- BizHawk savestates are version-locked: a 2.9.1 state makes 2.11.1 stop on a modal dialog,
-- which headlessly reads as a hang. Rather than re-capturing by hand after every emulator
-- upgrade, this rebuilds them from the ROM + its battery save (which is NOT version-locked).
--
-- Driven by tools/mkstates.py through the environment:
--   SLINK_ROOT       repo root
--   SLINK_STATE_OUT  absolute .State path to write (the kind's primary output)
--   SLINK_STATE_DIR  BizHawk's GBA State dir (kinds that write several files)
--   SLINK_STATE_SRC  state to start FROM (the battle kind derives from the overworld one)
--   SLINK_STATE_KIND town | battle
--
-- TWO save locations produce every derivable state. They are mutually exclusive, so move the
-- in-game save between runs and use `--only`:
--   town     STANDING IN FRONT OF A POKéMON CENTER DOOR, in a town
--            -> slink_overworld, slink_door, slink_pokecenter
--            The overworld capture is REJECTED if pacing there triggers a wild battle.
--   battle   STANDING IN TALL GRASS
--            -> slink_prebattle, slink_battle, slink_actionmenu, slink_movemenu
-- Writes patch/build/mkstate_result.txt ending in `RESULT: PASS|FAIL`, then exits.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — run via: python tools/mkstates.py")
local OUT_STATE = assert(os.getenv("SLINK_STATE_OUT"), "SLINK_STATE_OUT unset")
local KIND = os.getenv("SLINK_STATE_KIND") or "overworld"
local OUT = WT .. "/patch/build/mkstate_result.txt"
local MB  = dofile(WT .. "/lua/mailbox.lua")

-- RR / CFRU fixed addresses (NO_ENCRYPT; the same set the duo scenarios use).
local PARTY_COUNT   = 0x02024029
local PARTY_BASE    = 0x02024284
local BATTLE_TYPE   = 0x02022FEC   -- gBattleTypeFlags
local gBattleMons   = 0x02023BE4
local BM_MAXHP      = 0x2C
local CTRL          = 0x03004FE0   -- gBattlerControllerFuncs[0]
local ACTION_MENU   = 0x0802E439   -- action-select controller (same constant the duo uses)
-- The authoritative "player is standing in the walkable field" signal, the same one
-- peer_ghost_npc.lua gates on. A party-count check is NOT enough: RR loads the save into RAM
-- during the intro so the main menu can show CONTINUE stats, so gPlayerParty is already
-- populated while the GAME FREAK splash is still on screen — an earlier version of this script
-- snapshotted the splash because of exactly that. callback2 only becomes CB2_Overworld once
-- the map is actually up.
local CB2           = 0x030030F4
local CB2_OVERWORLD = 0x080565B5
local SCRIPT_CTX2   = 0x03000F9C   -- nonzero while a field script / menu / warp fade is running

local f = io.open(OUT, "w")
local function log(s) console.log("[mkstate] " .. tostring(s)); if f then f:write(tostring(s) .. "\n"); f:flush() end end
local function finish(ok, msg)
    log("RESULT: " .. (ok and "PASS" or "FAIL") .. (msg and (" (" .. msg .. ")") or ""))
    if f then f:close() end
    if client.exitCode then pcall(client.exitCode, ok and 0 or 1) end
    client.exit()          -- no argument: client.exit(n) does NOT exit in 2.11.1
end

local function party_count() return memory.read_u8(PARTY_COUNT) end
local function slot0_pid()   return memory.read_u32_le(PARTY_BASE) end
local function in_battle()   return memory.read_u32_le(BATTLE_TYPE) ~= 0 end
local function fighting()    return memory.read_u16_le(gBattleMons + BM_MAXHP) > 0 end
local function at_menu()     return memory.read_u32_le(CTRL) == ACTION_MENU end
local function poe()         return MB.player_oe() end
-- The CURRENT map, from the SaveBlock1 pointer chain — the same source memory_gba.getCurrentMap
-- uses. The object-event's own map fields (+0x0A/+0x09) LAG a warp: mid-door they still report
-- the map you came from, so a door-transition capture keyed off them lands inside the building.
local SB1_PTR = 0x03003840          -- radical_red profile (lua/games/gen3_frlge.lua)
local function _sb1()
    local p = memory.read_u32_le(SB1_PTR)
    if p < 0x02000000 or p >= 0x02040000 then return nil end
    return p
end
local function mapg()        local p = _sb1(); return p and memory.read_u8(p + 0x04) or 0 end
local function mapn()        local p = _sb1(); return p and memory.read_u8(p + 0x05) or 0 end
local function tx()          return memory.read_s16_le(poe() + 0x10) end
local function ty()          return memory.read_s16_le(poe() + 0x12) end
local function frames(n)     for _ = 1, n do emu.frameadvance() end end

local function in_field()
    local c = party_count()
    return memory.read_u32_le(CB2) == CB2_OVERWORLD
       and memory.read_u8(SCRIPT_CTX2) == 0
       and c >= 1 and c <= 6 and slot0_pid() ~= 0 and not in_battle()
end

local function shot(name) pcall(client.screenshot, WT .. "/patch/build/mkstate_" .. name .. ".png") end

-- Boot from the battery save through the title/CONTINUE intro to the walkable field.
local function boot_to_field()
    local MAX_FRAMES, HOLD = 7200, 60
    local held = 0
    for i = 1, MAX_FRAMES do
        if in_field() then
            held = held + 1
            joypad.set({})                   -- stop mashing the moment the save is up
            if held >= HOLD then
                log(string.format("walkable field at frame %d: map=(%d,%d) tile=(%d,%d) party=%d",
                    emu.framecount(), mapg(), mapn(), tx(), ty(), party_count()))
                return
            end
        else
            held = 0
            -- A takes CONTINUE (the default main-menu entry) and clears the "save loaded" text;
            -- Start skips the copyright/intro cutscene. Gaps between presses so held buttons
            -- don't auto-repeat past a menu.
            local phase = i % 8
            if phase == 0 then joypad.set({ A = true })
            elseif phase == 4 then joypad.set({ Start = true })
            else joypad.set({}) end
        end
        emu.frameadvance()
    end
    joypad.set({})
    shot("stuck")
    finish(false, string.format(
        "never reached the walkable field in %d frames (cb2=%08X script=%d count=%d pid=%08X "
        .. "battle=%s) — see patch/build/mkstate_stuck.png",
        MAX_FRAMES, memory.read_u32_le(CB2), memory.read_u8(SCRIPT_CTX2),
        party_count(), slot0_pid(), tostring(in_battle())))
end

-- Save, then prove it reloads into a usable field. Everything this tool writes goes through
-- here, so a state that cannot be loaded back never reaches the gates.
local function save_verified(path, label, want_field)
    frames(180)                                   -- let map/sprite init settle first
    local want_count, want_pid = party_count(), slot0_pid()
    if not pcall(savestate.save, path) then finish(false, "savestate.save failed: " .. path) end
    frames(30)
    if not pcall(savestate.load, path) then
        finish(false, "written state does not load back: " .. path)
    end
    frames(10)
    if party_count() ~= want_count or slot0_pid() ~= want_pid then
        finish(false, string.format("%s reload mismatch: party %d->%d pid %08X->%08X",
            label, want_count, party_count(), want_pid, slot0_pid()))
    end
    if want_field and memory.read_u32_le(CB2) ~= CB2_OVERWORLD then
        finish(false, string.format("%s is not in the walkable field (cb2=%08X)",
            label, memory.read_u32_le(CB2)))
    end
    log(string.format("saved %s  map=(%d,%d) tile=(%d,%d)", label, mapg(), mapn(), tx(), ty()))
end

-- Hold one button for `n` frames, bailing early when `stop()` says we're done.
local function hold(btn, n, stop)
    for _ = 1, n do
        joypad.set({ [btn] = true }); emu.frameadvance()
        if stop and stop() then joypad.set({}); return true end
    end
    joypad.set({})
    return stop and stop() or false
end

client.speedmode(6399)   -- max; the intro alone is ~500 frames of logos and menus
log("kind=" .. KIND .. " out=" .. OUT_STATE)

-- ── kind = "battle" ─────────────────────────────────────────────────────────────────────────
-- Derived from the overworld state: pace the tall grass the save was made in until a wild
-- encounter fires, then capture the whole battle family in one run.
--   slink_prebattle.State   the last in-grass position before the encounter
--   slink_battle.State      in battle, intro advanced to the action menu
--   slink_actionmenu.State  same context, named for the gates that ask for it
--   slink_movemenu.State    one A press further in (FIGHT -> move list)
if KIND == "battle" then
    local DIR = assert(os.getenv("SLINK_STATE_DIR"), "SLINK_STATE_DIR unset")
    local PRE = DIR .. "/slink_prebattle.State"

    -- Boots from the BATTERY SAVE, not from slink_overworld.State. The two kinds need opposite
    -- terrain — this one has to be in tall grass, and the overworld state must NOT be (a generic
    -- state standing in grass makes every walking scenario randomly trigger an encounter, which
    -- is exactly how the ghost duo scenario became flaky). Each kind depends only on where the
    -- save was made.
    boot_to_field()
    log(string.format("start tile=(%d,%d) party=%d", tx(), ty(), party_count()))

    -- Pace back and forth watching for an encounter, snapshotting a rolling "about to encounter"
    -- candidate as we go. That candidate IS the prebattle state: a position in grass the explode
    -- scenario can walk itself into a battle from.
    --
    -- Deliberately no "walk to a route with grass" step. An earlier version did that and mashed
    -- straight THROUGH the wild battle it triggered, because it only watched for a map change.
    local found, since = false, 0
    for i = 1, 18000 do
        if fighting() then found = true; break end
        local phase = i % 64
        if phase < 28 then joypad.set({ Up = true })
        elseif phase < 32 then joypad.set({})
        elseif phase < 60 then joypad.set({ Down = true })
        else joypad.set({}) end
        emu.frameadvance()
        since = since + 1
        if since >= 120 and not fighting() then
            since = 0
            pcall(savestate.save, PRE)
        end
    end
    joypad.set({})
    if not found then
        shot("stuck")
        finish(false, string.format(
            "no wild encounter in 18000 frames of pacing at tile (%d,%d) — the battery save must "
            .. "be made while STANDING IN TALL GRASS. See patch/build/mkstate_stuck.png.", tx(), ty()))
    end
    log("wild encounter at frame " .. emu.framecount())

    -- Advance the battle intro to the action menu (A-mash, same as the duo scenario).
    local menu = false
    for i = 1, 3600 do
        if at_menu() then menu = true; break end
        if i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
        emu.frameadvance()
    end
    joypad.set({})
    if not menu then shot("stuck"); finish(false, "battle never reached the action menu") end
    frames(30)
    for _, name in ipairs({ "slink_battle.State", "slink_actionmenu.State" }) do
        if not pcall(savestate.save, DIR .. "/" .. name) then
            finish(false, "savestate.save failed: " .. name)
        end
        log("saved " .. name)
    end
    shot("battle")

    joypad.set({ A = true }); emu.frameadvance()      -- FIGHT -> the move list
    joypad.set({}); frames(40)
    if not pcall(savestate.save, DIR .. "/slink_movemenu.State") then
        finish(false, "savestate.save failed: slink_movemenu.State")
    end
    log("saved slink_movemenu.State")
    log("saved slink_prebattle.State (last in-grass position before the encounter)")
    shot("movemenu")
    finish(true, "battle states captured")
end

-- ── kind = "town" ───────────────────────────────────────────────────────────────────────────
-- The save is made standing in front of a Pokémon Center door in a town, which yields three
-- states in one run:
--   slink_overworld.State   the generic walkable state (encounter-free — see the check below)
--   slink_door.State        outside, facing the door (the ghost's warp-transition gate)
--   slink_pokecenter.State  inside PC 1F (the trade-NPC gate)
if KIND == "town" then
    local DIR = assert(os.getenv("SLINK_STATE_DIR"), "SLINK_STATE_DIR unset")
    local DOOR = DIR .. "/slink_door.State"
    os.remove(DOOR)          -- never let a previous run's file survive a failure here
    boot_to_field()
    local g0, n0 = mapg(), mapn()

    -- slink_door.State is captured BEFORE any movement, so it is guaranteed to be outside.
    --
    -- Trying to snapshot "the last frame before the warp" does not work: the door transition is
    -- already in flight several frames before SaveBlock1's map id flips, so a state taken then
    -- reloads INSIDE the building. Two different map sources and an explicit re-check all landed
    -- inside; this is a race you cannot win from Lua.
    --
    -- The only thing the capture position has to satisfy is that test_live_ghostdoor.lua walks in
    -- whatever direction the player FACES, so point them at the door. Set facingDirection directly
    -- rather than tapping Up — a tap can complete a step, and if the player is standing directly
    -- below the door that step IS the warp.
    local FACE_OFF, FACE_NORTH = 0x18, 2
    local fb = memory.read_u8(poe() + FACE_OFF)
    memory.write_u8(poe() + FACE_OFF, (fb & 0xF0) | FACE_NORTH)
    frames(10)
    local face = memory.read_u8(poe() + FACE_OFF) & 0x0F
    if face ~= FACE_NORTH then
        finish(false, string.format("could not face the player north for slink_door.State "
            .. "(facing reads %d) — the engine overwrote it", face))
    end
    -- PROVE THE GROUND FIRST, from a scratch file. slink_overworld.State is what every walking
    -- gate and 4 of the 5 duo scenarios start from, so it must be somewhere the player can walk
    -- without being jumped — captured in tall grass it makes them randomly flaky (the ghost duo
    -- failed with "ghost barely moved" because player A walked into a wild battle halfway
    -- through its loop). Checking BEFORE committing matters: an earlier version wrote both real
    -- states and only then paced, so pointing it at a grass save destroyed two good states on
    -- its way to failing.
    local SCRATCH = DIR .. "/slink_mkstate_scratch.State"
    if not pcall(savestate.save, SCRATCH) then finish(false, "could not write the scratch state") end
    local PACE = 1800
    for i = 1, PACE do
        if fighting() then
            joypad.set({}); shot("stuck")
            os.remove(SCRATCH)
            finish(false, string.format(
                "a wild encounter fired %d frames into a walk test at tile (%d,%d) — this save "
                .. "is in tall grass. The town states need encounter-free ground; grass is what "
                .. "the `battle` kind wants. Nothing was overwritten.", i, tx(), ty()))
        end
        local phase = i % 64
        if phase < 28 then joypad.set({ Up = true })
        elseif phase < 32 then joypad.set({})
        elseif phase < 60 then joypad.set({ Down = true })
        else joypad.set({}) end
        emu.frameadvance()
    end
    joypad.set({})
    log(string.format("walked %d frames with no wild encounter — safe for the walking scenarios", PACE))
    if not pcall(savestate.load, SCRATCH) then finish(false, "could not reload the scratch state") end
    os.remove(SCRATCH)
    frames(30)

    -- Ground is good: commit the two outside states. Same position, so one capture serves both.
    save_verified(DOOR, "slink_door.State", true)
    if mapg() ~= g0 or mapn() ~= n0 then
        finish(false, "slink_door.State is not on the outside map")
    end
    local OW = DIR .. "/slink_overworld.State"
    save_verified(OW, "slink_overworld.State", true)
    log(string.format("slink_door.State / slink_overworld.State: map=(%d,%d) tile=(%d,%d) "
        .. "facing=%d (north)", mapg(), mapn(), tx(), ty(), face))
    shot("door")

    -- Now walk in. Sweep sideways when northward progress stalls: the doorway is one specific
    -- column, and pressing Up against the building wall gets you nothing.
    local function warped() return mapg() ~= g0 or mapn() ~= n0 end
    local left, amp, entered = true, 1, false
    for _ = 1, 20 do
        local y0 = ty()
        if hold("Up", 100, warped) then entered = true; break end
        if ty() >= y0 then
            if hold(left and "Left" or "Right", 26 * amp, warped) then entered = true; break end
            left = not left
            amp = amp + 1
        end
    end
    joypad.set({})
    if not entered then
        shot("stuck")
        finish(false, string.format(
            "never entered a building from map (%d,%d) tile (%d,%d) — the battery save must be "
            .. "made STANDING IN FRONT OF A POKéMON CENTER DOOR. See mkstate_stuck.png.",
            g0, n0, tx(), ty()))
    end

    -- Wait out the warp fade, then confirm we are somewhere the patch recognises as a Pokémon
    -- Center: ask it to spawn the trade NPC and see whether one appears. That is the same
    -- condition test_live_pcnpc.lua asserts, so a state that passes here is usable there.
    local settled = false
    for _ = 1, 600 do
        emu.frameadvance()
        if in_field() then settled = true; break end
    end
    if not settled then shot("stuck"); finish(false, "warp never settled back into the field") end
    log(string.format("entered map=(%d,%d) tile=(%d,%d)",
        mapg(), mapn(), tx(), ty()))
    shot("pokecenter")

    if MB.present() then
        MB.set_pc_npc(true)
        frames(120)
        local npc = 16
        for i = 0, 15 do
            if (memory.read_u8(0x02036E38 + i*0x24) & 1) == 1
               and memory.read_u8(0x02036E38 + i*0x24 + 0x08) == 0xF1 then npc = i; break end
        end
        if npc >= 16 then
            shot("stuck")
            finish(false, string.format(
                "the patch did not spawn its trade NPC on map (%d,%d) — either this is not a "
                .. "Pokémon Center 1F, or that map id is missing from kPokecenter1F in "
                .. "patch/src/handlers.c. See mkstate_pokecenter.png.", mapg(), mapn()))
        end
        log(string.format("patch spawned the trade NPC at oe=%d tile=(%d,%d) — map (%d,%d) is a "
            .. "recognised Pokémon Center", npc,
            memory.read_s16_le(0x02036E38 + npc*0x24 + 0x10),
            memory.read_s16_le(0x02036E38 + npc*0x24 + 0x12), mapg(), mapn()))
        MB.set_pc_npc(false)
        frames(60)
    end

    save_verified(DIR .. "/slink_pokecenter.State", "slink_pokecenter.State", true)
    finish(true, "overworld + door + pokecenter states captured")
end

finish(false, string.format(
    "unknown kind %q — expected one of: town, battle. The standalone `overworld` kind was "
    .. "folded into `town`: the generic state has to come from encounter-free ground, and that "
    .. "is the same save that produces slink_door and slink_pokecenter.", KIND))
