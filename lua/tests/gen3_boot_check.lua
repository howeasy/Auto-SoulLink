-- gen3_boot_check.lua — cold boot -> CONTINUE -> in-game SAVE -> flush, for a Gen 3 fixture.
--
-- PLAN §5.5: `qualify` proves the bytes model a save; USABILITY is signed only by a real
-- cold boot -> CONTINUE -> re-save -> reload. This is the emulator half of that; the Python
-- half (`tools/gen3_fixtures.py boot-check`) re-imports the flushed SaveRAM and requires the
-- counter to have advanced by exactly 1 with the party unchanged.
--
--   python tools/gen3_fixtures.py boot-check --rom <gba> --fixture tests/fixtures/gen3/rr_town.sav --rr
--
-- Environment (set by the Python side; SLINK_ROOT is run_gate.py's):
--   SLINK_ROOT              repo root
--   SLINK_GEN3_CHECKPOINT   absolute path to data/games/gen3_{frlg,rr}/write_checkpoint.json
--   SLINK_GEN3_TITLE        title key inside it (optional when the file has exactly one)
--
-- TWO ROLES. Run as the top-level `--lua=` script it performs the boot check and exits; a
-- `dofile()` from a sibling driver gets the helpers and nothing runs. BizHawk reports
-- `source == "main"` for a `--lua=` script and the real path for a dofile'd chunk
-- (reference_bizhawk_lua_selflocate), which is what the guard at the bottom reads. The
-- sibling is lua/tests/gen3_fr_newgame_inputs.lua, which needs the same SAVE driver.
--
-- NO GUESSED MENU GEOMETRY. FR's and RR's START menus differ in row order and RR's row count
-- moves with the companion patch, so `save_via_menu` never presses "Down N times" blind: it
-- reads the engine's own sStartMenuOrder to find the SAVE row, walks the cursor there (every
-- press gated on the menu window actually being open, card C4-F2), and asks the ENGINE whether
-- the save dialog opened (`sSaveDialogCB` from the checkpoint profile). Nothing here is a
-- †UNVERIFIED input sequence.
--
-- The save itself is proven by the SaveRAM-backed sector counter advancing in the flash
-- memory domain, never by assuming the button press worked.

local M = {}

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via tools/gen3_fixtures.py")
local JSON = dofile(WT .. "/lua/json_codec.lua")

-- Flash geometry, the same constants server/adapters/gen3_codec.py carries (pret
-- pokefirered include/save.h:63-71 struct SaveSector: data[3968], unused, then the footer
-- u16 id @0xFF4, u16 checksum @0xFF6, u32 signature @0xFF8, u32 counter @0xFFC; 32
-- physical sectors = 0x20000, two slots of 14 at sectors 0-13 and 14-27).
local SECTOR_SIZE, SECTORS = 0x1000, 32
local SECTORS_PER_SLOT = 14
local OFF_ID, OFF_CHECKSUM = 0x0FF4, 0x0FF6
local OFF_SIGNATURE, OFF_COUNTER = 0x0FF8, 0x0FFC
local SIGNATURE = 0x08012025

-- ── START menu witnesses (pret pokefirered src/start_menu.c) ────────────────────────────────
-- WRAM globals, not code: identical addresses in pokefirered.sym AND pokeleafgreen.sym (grepped
-- both directly, card C4-F2), and already relied on at these same addresses for Radical Red by
-- lua/tests/test_live_startmenu.lua's own live probe -- so no per-title table (gen3_title_syms,
-- which exists for .text addresses that DO shift per title) is needed for these four.
local START_MENU_CURSOR_ADDR    = 0x020370F4   -- sStartMenuCursorPos (u8): highlighted row
local START_MENU_COUNT_ADDR     = 0x020370F5   -- sNumStartMenuItems (u8): rows built this open
local START_MENU_ORDER_ADDR     = 0x020370F6   -- sStartMenuOrder (u8[9]): action id per row
local START_MENU_WINDOW_ID_ADDR = 0x0203ABE0   -- sStartMenuWindowId (u8): WINDOW_NONE (0xFF)
                                                -- until ShowStartMenu creates the list window
local WINDOW_NONE = 0xFF
-- start_menu.c's action-id enum (POKEDEX=0, POKEMON=1, BAG=2, PLAYER=3, SAVE=4, OPTION=5,
-- EXIT=6, RETIRE_SAFARI=7, PLAYER_LINK=8 -- id 8 is the "dead" row reference_rr_startmenu_hijack
-- names). Title-invariant: same source, same enum: confirmed against both .sym files' callback
-- order (StartMenuPokedexCallback, ...PokemonCallback, ...BagCallback, ...PlayerCallback,
-- ...SaveCallback is the 5th, i.e. index 4) and against RR's own observed order in
-- test_live_startmenu.lua (whose [1 2 3 4 5 6] is this same enum with id 0 not yet unlocked).
local MENU_ACTION_SAVE = 4

local function start_menu_open()
    return memory.read_u8(START_MENU_WINDOW_ID_ADDR) ~= WINDOW_NONE
end

-- Per-id section sizes: the SAVEBLOCK_CHUNK macro (pret src/save.c:43-72), mirrored from
-- gen3_codec.slot_layout: size = min(sizeof(object) - chunk*CHUNK, CHUNK). CHUNK is 0xF80
-- for vanilla FR/LG and CFRU's 0xFF0 for Radical Red (gen3_codec CHUNK_SIZE_CFRU).
local function section_sizes(chunk)
    local sizes = {}
    for _, o in ipairs({ { 0x0F24, 0, 0 }, { 0x3D68, 1, 4 }, { 0x83D0, 5, 13 } }) do
        for id = o[2], o[3] do
            local off = (id - o[2]) * chunk
            sizes[id] = math.max(0, math.min(o[1] - off, chunk))
        end
    end
    return sizes
end
local SIZES = { vanilla = section_sizes(0x0F80), cfru = section_sizes(0x0FF0) }

-- ── logging: phase transitions only, never per frame ────────────────────────────────────────
-- (reference_bizhawk_gate_drivers: a console.log per frame starves the emulator.)
local out, lines = nil, {}

function M.open(name)
    out = io.open(WT .. "/patch/build/" .. name .. "_result.txt", "w")
end

function M.log(s)
    lines[#lines + 1] = tostring(s)
    console.log("[gen3] " .. tostring(s))
    if out then out:write(tostring(s) .. "\n"); out:flush() end
end

function M.phase(name, detail)
    M.log(string.format("phase %s frame=%d%s", name, emu.framecount(),
                        detail and (" " .. detail) or ""))
end

function M.finish(ok, msg)
    joypad.set({})
    M.log("RESULT: " .. (ok and "PASS" or "FAIL") .. (msg and (" " .. msg) or ""))
    if out then out:close() end
    if client.exitCode then pcall(client.exitCode, ok and 0 or 1) end
    client.exit()      -- no argument: client.exit(n) does NOT exit in 2.11.1
end

function M.shot(name)
    pcall(client.screenshot, WT .. "/patch/build/gen3_" .. name .. ".png")
end

-- ── the profile ─────────────────────────────────────────────────────────────────────────────

local function int(x) return math.floor(x) end

--- The per-title block of data/games/gen3_*/write_checkpoint.json.
function M.checkpoint()
    local path = assert(os.getenv("SLINK_GEN3_CHECKPOINT"), "SLINK_GEN3_CHECKPOINT unset")
    local f = assert(io.open(path, "rb"), "cannot read " .. path)
    local raw = f:read("a")
    f:close()
    local doc = assert(JSON.decode(raw), "malformed checkpoint JSON: " .. path)
    local want = os.getenv("SLINK_GEN3_TITLE")
    if want and want ~= "" then
        M.title = want
        return assert(doc[want], "no title " .. want .. " in " .. path), want
    end
    local only, key
    for k, v in pairs(doc) do
        assert(only == nil, "several titles in " .. path .. " — set SLINK_GEN3_TITLE")
        only, key = v, k
    end
    M.title = key
    return assert(only, "empty checkpoint " .. path), key
end

local function read_width(addr, width)
    if width == 4 then return memory.read_u32_le(addr) end
    if width == 2 then return memory.read_u16_le(addr) end
    return memory.read_u8(addr)
end

--- (value, expected) for a named checkpoint predicate, mask applied.
function M.pred(cp, name)
    local p = assert(cp.predicates and cp.predicates[name], "no predicate " .. name)
    local v = read_width(int(p.address) + int(p.offset or 0), int(p.width or 1))
    if p.mask then v = v & int(p.mask) end
    return v, int(p.expect)
end

function M.pred_ok(cp, name)
    local v, want = M.pred(cp, name)
    return v == want
end

--- The SaveBlock1-derived (mapGroup, mapNum), the pointer chain lua/memory_gba.lua:1109-1114
--- reads (+0x04 / +0x05). -1,-1 while the pointer is not yet a sane EWRAM address.
function M.map(cp)
    local ptr = assert(cp.pointers and cp.pointers.gSaveBlock1Ptr, "no gSaveBlock1Ptr")
    local sb1 = memory.read_u32_le(int(ptr.address))
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return -1, -1 end
    return memory.read_u8(sb1 + 0x04), memory.read_u8(sb1 + 0x05)
end

--- The player's map coordinates: SaveBlock1 begins with `struct Coords16 pos` (pret
--- pokefirered c75f352 include/global.h:761). -1,-1 while the pointer is not sane.
function M.pos(cp)
    local ptr = assert(cp.pointers and cp.pointers.gSaveBlock1Ptr, "no gSaveBlock1Ptr")
    local sb1 = memory.read_u32_le(int(ptr.address))
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return -1, -1 end
    return memory.read_s16_le(sb1 + 0x00), memory.read_s16_le(sb1 + 0x02)
end

-- ── the flash domain and its save counter ───────────────────────────────────────────────────

--- The memory domain BizHawk backs the battery file with, or nil. Bound at run time from
--- memory.getmemorydomainlist() rather than hardcoded (PLAN §5.5 binds it in P1).
function M.flash_domain()
    local list = memory.getmemorydomainlist()
    local names = {}
    for _, n in pairs(list) do names[#names + 1] = tostring(n) end
    for _, want in ipairs({ "SRAM", "Flash", "FLASH", "Save RAM" }) do
        for _, n in ipairs(names) do
            if n == want then
                local ok, size = pcall(memory.getmemorydomainsize, n)
                if ok and size and size >= SECTOR_SIZE * SECTORS then return n end
            end
        end
    end
    return nil, table.concat(names, ", ")
end

--- The highest save counter over the signature-valid SLOT sectors (0-27) of the flash image.
--- -1 when none carries the signature (an erased or unread battery). This is the witness the
--- save actually happened: it is the word the loader itself uses to pick a slot. Sectors 28-31
--- (Hall of Fame / trainer tower, CFRU-repurposed on RR) are not slot sectors.
function M.save_counter(domain)
    local best = -1
    for s = 0, 2 * SECTORS_PER_SLOT - 1 do
        local base = s * SECTOR_SIZE
        if memory.read_u32_le(base + OFF_SIGNATURE, domain) == SIGNATURE then
            local c = memory.read_u32_le(base + OFF_COUNTER, domain)
            if c ~= 0xFFFFFFFF and c > best then best = c end
        end
    end
    return best
end

--- pret src/save.c CalculateChecksum: wrapping u32 sum of size/4 LE words, folded to u16.
local function sector_checksum(domain, base, size)
    local sum = 0
    for i = 0, size // 4 - 1 do
        sum = (sum + memory.read_u32_le(base + i * 4, domain)) & 0xFFFFFFFF
    end
    return ((sum >> 16) + sum) & 0xFFFF
end

--- The save written at counter `ctr`, judged the way gen3_codec.qualify_flash judges a slot:
--- returns (n, why) where n is how many of the 14 logical ids 0..13 appear EXACTLY ONCE in
--- the ONE physical slot the game writes that counter to (pret save.c HandleWriteSector:
--- slot = gSaveCounter % 2, sectors 14*slot .. 14*slot+13), each carrying the signature and
--- `ctr`. n == 14 additionally requires every section checksum (over that id's chunk size)
--- to match; `why` names the first defect when n < 14. The checksum pass runs only once the
--- structure is whole (the counter word is the last one a sector write programs), so the
--- per-poll cost while the save is in flight stays at 3 reads per sector.
--- The chunk table follows the checkpoint title (M.title, set by M.checkpoint): radical_red
--- is CFRU, anything else vanilla; `cfru` overrides.
function M.sectors_at(domain, ctr, cfru)
    if cfru == nil then cfru = M.title == "radical_red" end
    local sizes = cfru and SIZES.cfru or SIZES.vanilla
    local first = SECTORS_PER_SLOT * (ctr % 2)
    local where, n, why = {}, 0, nil
    for s = first, first + SECTORS_PER_SLOT - 1 do
        local base = s * SECTOR_SIZE
        local id = memory.read_u16_le(base + OFF_ID, domain)
        if memory.read_u32_le(base + OFF_SIGNATURE, domain) ~= SIGNATURE then
            why = why or string.format("sector %d: no signature", s)
        elseif memory.read_u32_le(base + OFF_COUNTER, domain) ~= ctr then
            why = why or string.format("sector %d: counter is not %d", s, ctr)
        elseif id >= SECTORS_PER_SLOT then
            why = why or string.format("sector %d: out-of-range id %d", s, id)
        elseif where[id] then
            why = why or string.format("sector %d: duplicate id %d (also sector %d)", s, id, where[id])
        else
            where[id], n = s, n + 1
        end
    end
    if n < SECTORS_PER_SLOT then return n, why end
    for id = 0, SECTORS_PER_SLOT - 1 do
        local base = where[id] * SECTOR_SIZE
        if sector_checksum(domain, base, sizes[id]) ~= memory.read_u16_le(base + OFF_CHECKSUM, domain) then
            return n - 1, string.format("sector %d (id %d): bad checksum", where[id], id)
        end
    end
    return n, nil
end

-- ── input, on a frame budget ────────────────────────────────────────────────────────────────

M.spent, M.budget = 0, 200000

function M.advance()
    M.spent = M.spent + 1
    if M.spent > M.budget then
        M.shot("stuck")
        M.finish(false, string.format("frame budget %d exhausted — see patch/build/gen3_stuck.png",
                                      M.budget))
    end
    emu.frameadvance()
end

function M.idle(n)
    joypad.set({})
    for _ = 1, n do M.advance() end
end

--- One button press on the 16-frame cadence native menus need
--- (reference_bizhawk_gate_drivers: re-pulse native menus on the 16-frame cadence).
function M.tap(btn, hold, gap)
    for _ = 1, (hold or 3) do joypad.set({ [btn] = true }); M.advance() end
    M.idle(gap or 13)
end

--- Mash A (and Start every 4th beat) for up to `frames`, stopping as soon as `stop()` is true.
function M.mash(frames, stop)
    local beat = 0
    for _ = 1, frames do
        if stop and stop() then joypad.set({}); return true end
        beat = beat + 1
        local phase = beat % 16
        if phase == 0 then joypad.set({ Start = true })
        elseif phase == 8 then joypad.set({ A = true })
        else joypad.set({}) end
        M.advance()
    end
    joypad.set({})
    return stop and stop() or false
end

-- ── the two drives ──────────────────────────────────────────────────────────────────────────

--- Cold boot through the title screen and CONTINUE into the walkable field.
---
--- The overworld signal is the profile's own `callback2` predicate (gMain.callback2 ==
--- CB2_Overworld), NOT a populated party: RR loads the save into RAM during the intro so the
--- main menu can show CONTINUE stats, so gPlayerParty is live while the splash is still up
--- (lua/tests/mkstate.lua:38-46). Held for HOLD frames so a one-frame flicker cannot pass.
function M.boot_to_field(cp, frames)
    local HOLD = 60
    local held = 0
    for _ = 1, (frames or 9000) do
        if M.pred_ok(cp, "callback2") and M.pred_ok(cp, "palette_fade_active") then
            held = held + 1
            joypad.set({})              -- stop mashing the moment the field is up
            if held >= HOLD then
                M.phase("field", string.format("map=(%d,%d)", M.map(cp)))
                return true
            end
            M.advance()
        else
            held = 0
            local phase = M.spent % 16
            if phase == 0 then joypad.set({ A = true })
            elseif phase == 8 then joypad.set({ Start = true })
            else joypad.set({}) end
            M.advance()
        end
    end
    joypad.set({})
    return false
end

--- Open the START menu, walk straight to the SAVE row, confirm, wait for the new slot to be
--- complete and valid (M.sectors_at), wait for the dialog to close, then flush the battery
--- file. Returns (ok, before_counter, after_counter, why): ok is true ONLY when all of that
--- held; otherwise `why` names the step that failed (menu, counter, slot, dialog, flush).
---
--- WITNESSED, NOT COUNTED. PHYSICAL 2026-09-23 (gen3-P4-C4-F/C4-F2): the previous "one A per
--- attempt, back out with B, reopen, one Down further" row SEARCH could press Down right after
--- re-tapping Start but before the menu actually had the window up -- field control locks the
--- instant Start registers (pret start_menu.c ShowStartMenu -> LockPlayerFieldControls), but
--- the list WINDOW (sStartMenuWindowId) is created a few frames later, and a Down sent in that
--- gap could still land on a submenu the wrong row opened, walking the player across a map
--- connection mid-save. Fixed at the root: every navigation press is gated on
--- `start_menu_open()` (the window existing -- field control is already locked by then, so
--- nothing typed from here on can ever reach the free-moving field), and the SAVE row is read
--- directly from the engine's own sStartMenuOrder/sNumStartMenuItems rather than hunted for by
--- counting presses, so there is no wrong row to back out of at all.
function M.save_via_menu(cp, domain, attempts)
    -- OPEN = sSaveDialogCB changed since before the menu: pret never clears it (start_menu.c
    -- :608-842), so after an earlier save this boot it still holds SaveDialogCB_ReturnSuccess
    -- and a bare ~= 0 would "open" on the first A of any row.
    local cb0 = M.pred(cp, "save_dialog_cb")
    local function dialog() return (M.pred(cp, "save_dialog_cb")) ~= cb0 end

    local before = M.save_counter(domain)
    M.phase("save-menu", string.format("counter=%d", before))

    -- Wait for field control to be free before ever touching Start. PHYSICAL 2026-09-23: right
    -- after control returns to the player (a fresh CONTINUE, this driver's own boot_to_field),
    -- sLockFieldControls can hold LOCKED for 100+ frames with no input at all -- a settle
    -- period, observed on a tall-grass spawn -- and a Start press sent during it is silently
    -- swallowed. The pre-fix row search only ever "worked" by accident: its own retry loop
    -- re-pressed Start every cycle until one happened to land after the window closed, which
    -- is what its "several attempts before the dialog opened" logs actually were.
    -- `field_controls_locked`'s pred_ok is TRUE when sLockFieldControls == 0, i.e. FREE.
    -- Retried, not one-shot: a fresh CONTINUE's settle lock is the one PHYSICAL cause pinned so
    -- far, but a Start press can still land in some other transient un-witnessed gap (observed
    -- right after fleeing a battle back to the field) and be swallowed the same way. Retrying
    -- the wait-then-press cycle is safe here -- unlike Down/A, a Start sent while the menu is
    -- ALREADY open just toggles it shut, which is exactly why this only re-presses after
    -- confirming (via the very next check) that it is still closed.
    local function controls_free() return M.pred_ok(cp, "field_controls_locked") end
    local opened = false
    for _ = 1, 5 do
        local freed = false
        for _ = 1, 300 do
            if controls_free() then freed = true; break end
            M.advance()
        end
        if not freed then
            M.shot("stuck")
            return false, before, before, "field controls never freed before the save attempt"
        end
        M.tap("Start", 3, 0)
        for _ = 1, 120 do
            if start_menu_open() then opened = true; break end
            M.advance()
        end
        if opened then break end
    end
    if not opened then
        M.shot("stuck")
        return false, before, before, "the start menu window never opened"
    end

    local n = memory.read_u8(START_MENU_COUNT_ADDR)
    local save_row = nil
    for i = 0, n - 1 do
        if memory.read_u8(START_MENU_ORDER_ADDR + i) == MENU_ACTION_SAVE then save_row = i; break end
    end
    if not save_row then
        M.shot("stuck")
        return false, before, before, string.format(
            "no SAVE row in sStartMenuOrder (%d items, no action id %d)", n, MENU_ACTION_SAVE)
    end

    -- Forward-only, no wrap assumed: a fresh boot's cursor starts at row 0 (bss-cleared), at or
    -- before save_row; a repeat save later in the same boot leaves the cursor sitting exactly
    -- on save_row from the last confirm (FRLG keeps the position between openings), so every
    -- real caller of save_via_menu starts at-or-before the target and Down alone always
    -- reaches it. Budget past `n` rows for presses wasted while the witness above was still
    -- settling; `attempts` overrides for a caller with a known-larger menu.
    local reached = false
    for _ = 1, (attempts or (n + 8)) do
        if memory.read_u8(START_MENU_CURSOR_ADDR) == save_row then reached = true; break end
        if not start_menu_open() then
            M.shot("stuck")
            return false, before, before, "the start menu closed unexpectedly during the row walk"
        end
        M.tap("Down", 3, 13)
    end
    if not reached then
        M.shot("stuck")
        return false, before, before, string.format(
            "cursor never reached the SAVE row (row %d, at %d)", save_row,
            memory.read_u8(START_MENU_CURSOR_ADDR))
    end

    M.tap("A", 3, 60)
    if not dialog() then
        M.shot("stuck")
        return false, before, before, "the save dialog never opened"
    end
    M.phase("save-dialog", "row=" .. save_row)

    -- Confirm (YES is the default on both the save prompt and the overwrite prompt) and keep
    -- tapping A through "SAVING… DON'T TURN OFF THE POWER" and the "saved the game" box.
    -- The verdict is the COUNTER, not the presses.
    local after, tick = before, 0
    local moved = M.mash(4800, function()
        tick = tick + 1
        if tick % 16 ~= 0 then return false end   -- 32 sector reads: not every frame
        after = M.save_counter(domain)
        return after > before
    end)
    if not moved then
        M.shot("stuck")
        return false, before, after, "the save counter never advanced"
    end
    M.phase("saved", string.format("counter=%d->%d", before, after))
    -- The counter moving is NOT completion: wait for every sector of the new slot.
    local done, why = M.sectors_at(domain, after)
    for _ = 1, 6000 do
        if done >= SECTORS_PER_SLOT then break end
        M.advance()
        if M.spent % 16 == 0 then done, why = M.sectors_at(domain, after) end
    end
    M.phase("slot-complete", string.format("sectors=%d/14%s", done, why and (" " .. why) or ""))
    if done < SECTORS_PER_SLOT then
        M.shot("stuck")
        return false, before, after, "the new slot is not a valid save: " .. tostring(why)
    end
    -- `dialog()` (sSaveDialogCB ~= 0) is right for detecting the dialog OPEN above -- this
    -- boot's cold start zeroes it (bss) and StartMenu_PrepareForSave (pret start_menu.c:608)
    -- is the first thing to touch it -- but it is the WRONG signal for closed: pret never
    -- resets sSaveDialogCB to NULL on any exit path (:608-842 is every assignment there is),
    -- so once this save has opened the dialog once, `dialog()` reads non-zero for the rest of
    -- the boot, saved or not. The real "control is back" signal is the field-controls lock
    -- ShowStartMenu took out for the whole menu (:405 LockPlayerFieldControls, the moment
    -- Start was first pressed above) and only StartCB_Save2's OKAY/ERROR exits release
    -- (:586, :598) -- `field_controls_locked` already tracks that.
    --
    -- SaveDialogCB_ReturnSuccess (:827-835) itself gates on !IsSEPlaying() and then
    -- SaveDialog_Wait60FramesOrAButtonHeld (:671-687): JOY_HELD(A_BUTTON) (not JOY_NEW, so a
    -- re-pulse lands whether or not a prior press was still down) returns TRUE immediately, a
    -- 60-frame timeout returns TRUE with no press at all -- B is never read there. A press is
    -- not strictly required, only faster than the timeout; re-pulse it every 16 frames anyway
    -- so a slow SE/printer never leaves the timeout as the only path.
    local function unlocked() return M.pred_ok(cp, "field_controls_locked") end
    local closed = false
    for i = 1, 600 do                  -- let the dialog close before the flush
        if unlocked() then closed = true; break end
        if i % 16 == 1 then joypad.set({ A = true }) else joypad.set({}) end
        M.advance()
    end
    joypad.set({})
    if not closed then
        M.shot("stuck")
        return false, before, after, "the save dialog never closed in 600 frames"
    end
    local fok, ferr = pcall(client.saveram)
    if not fok then
        return false, before, after, "SaveRAM flush failed: " .. tostring(ferr)
    end
    return true, before, after, nil
end

-- ── run as a gate ───────────────────────────────────────────────────────────────────────────

local function run()
    M.open("gen3_boot_check")          -- patch/build/gen3_boot_check_result.txt
    pcall(client.speedmode, 6399)
    local cp, title = M.checkpoint()
    M.phase("start", "title=" .. tostring(title))

    local domain, seen = M.flash_domain()
    if not domain then
        M.finish(false, "no flash memory domain of 0x20000 bytes; domains: " .. tostring(seen))
    end
    M.phase("domain", domain)

    local seeded = M.save_counter(domain)
    if seeded < 0 then
        M.finish(false, "the battery is erased at boot — the fixture was not seeded into the "
                     .. "per-run SaveRAM directory BizHawk was configured with")
    end
    M.phase("seeded", "counter=" .. seeded)

    if not M.boot_to_field(cp, 9000) then
        M.shot("stuck")
        local cb2 = M.pred(cp, "callback2")
        M.finish(false, string.format("never reached the field in 9000 frames (callback2=%08X) "
                                   .. "— the title screen did not offer a usable CONTINUE. See "
                                   .. "patch/build/gen3_stuck.png", cb2))
    end

    local ok, before, after, why = M.save_via_menu(cp, domain)   -- flushes on success
    if not ok then
        M.finish(false, string.format("the in-game save failed (%d -> %d): %s. See "
                                   .. "patch/build/gen3_stuck.png", before, after, why))
    end
    M.idle(60)
    M.phase("flushed")
    M.finish(true, string.format("counter %d -> %d", before, after))
end

-- `source == "main"` ONLY for a top-level `--lua=` script; a dofile'd chunk sees its own path
-- (reference_bizhawk_lua_selflocate). So the sibling driver gets the helpers, not a run.
if (debug.getinfo(1, "S").source or "") == "main" then run() end

return M
