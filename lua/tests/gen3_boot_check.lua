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
-- moves with the companion patch, so `save_via_menu` does not press "Down N times": it walks
-- one row per attempt and asks the ENGINE whether the save dialog opened (`sSaveDialogCB`
-- from the checkpoint profile). Nothing here is a †UNVERIFIED input sequence; the only fixed
-- shapes are "Start opens the menu" and "B backs out", which both games share.
--
-- The save itself is proven by the SaveRAM-backed sector counter advancing in the flash
-- memory domain, never by assuming the button press worked.

local M = {}

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via tools/gen3_fixtures.py")
local JSON = dofile(WT .. "/lua/json_codec.lua")

-- Flash geometry, the same constants server/adapters/gen3_codec.py carries
-- (pokefirered include/save.h: SECTOR_SIZE 0x1000, SECTOR_SIGNATURE 0x08012025, the footer's
-- signature at +0xFF8 and the save counter at +0xFFC; 32 physical sectors = 0x20000).
local SECTOR_SIZE, SECTORS = 0x1000, 32
local OFF_SIGNATURE, OFF_COUNTER = 0x0FF8, 0x0FFC
local SIGNATURE = 0x08012025

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
        return assert(doc[want], "no title " .. want .. " in " .. path), want
    end
    local only, key
    for k, v in pairs(doc) do
        assert(only == nil, "several titles in " .. path .. " — set SLINK_GEN3_TITLE")
        only, key = v, k
    end
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

--- The highest save counter over the signature-valid sectors of the flash image. -1 when no
--- sector carries the signature (an erased or unread battery). This is the witness the save
--- actually happened: it is the byte the loader itself uses to pick a slot.
function M.save_counter(domain)
    local best = -1
    for s = 0, SECTORS - 1 do
        local base = s * SECTOR_SIZE
        if memory.read_u32_le(base + OFF_SIGNATURE, domain) == SIGNATURE then
            local c = memory.read_u32_le(base + OFF_COUNTER, domain)
            if c ~= 0xFFFFFFFF and c > best then best = c end
        end
    end
    return best
end

--- How many signature-valid slot sectors (id < 14) carry save counter `ctr`. A finished
--- full save has all 14; the counter appears in the first written sector long before the
--- loop ends (PHYSICAL, RR companion 2026-09-21: ~66 frames per sector under the mGBA flash
--- timing, so a 14-sector save spans ~950 frames after the counter first moves).
function M.sectors_at(domain, ctr)
    local n = 0
    for s = 0, SECTORS - 1 do
        local base = s * SECTOR_SIZE
        if memory.read_u32_le(base + OFF_SIGNATURE, domain) == SIGNATURE
           and memory.read_u32_le(base + OFF_COUNTER, domain) == ctr
           and memory.read_u16_le(base + OFF_SIGNATURE - 8, domain) < 14 then
            n = n + 1
        end
    end
    return n
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

--- Open the START menu, find the SAVE row, confirm, and wait for the save counter to move.
--- Returns (ok, before_counter, after_counter).
---
--- ROW SEARCH, NOT A ROW INDEX. One A press per attempt, then the engine is asked whether
--- `sSaveDialogCB` became non-zero; a wrong row is backed out of with B (until callback2 is
--- CB2_Overworld again, which every submenu — Pokédex, Bag, trainer card — leaves), the menu
--- is reopened and the cursor walks down one row. FRLG keeps the START cursor position
--- between openings, so a relative walk covers every row whatever the cursor started on. 14
--- attempts is more rows than either build's menu has (RR's normal field menu is six,
--- lua/tests/test_live_startmenu.lua:96-104; the companion patch adds one).
function M.save_via_menu(cp, domain, attempts)
    local function field() return M.pred_ok(cp, "callback2") end
    local function dialog() return (M.pred(cp, "save_dialog_cb")) ~= 0 end

    local before = M.save_counter(domain)
    M.phase("save-menu", string.format("counter=%d", before))
    M.tap("Start", 3, 30)
    local opened = false
    for attempt = 1, (attempts or 14) do
        M.tap("A", 3, 60)
        if dialog() then
            M.phase("save-dialog", "attempt=" .. attempt)
            opened = true
            break
        end
        for _ = 1, 12 do
            if field() then break end
            M.tap("B", 3, 20)          -- back out of whatever that row opened
        end
        M.tap("B", 3, 20)              -- close the START menu if it is still up
        M.tap("Start", 3, 30)          -- reopen; the cursor keeps its row
        M.tap("Down", 3, 13)           -- one row further down
    end
    if not opened then
        M.shot("stuck")
        return false, before, before
    end

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
        return false, before, after
    end
    M.phase("saved", string.format("counter=%d->%d", before, after))
    -- The counter moving is NOT completion: wait for every sector of the new slot.
    local done = M.sectors_at(domain, after)
    for _ = 1, 6000 do
        if done >= 14 then break end
        M.advance()
        if M.spent % 16 == 0 then done = M.sectors_at(domain, after) end
    end
    M.phase("slot-complete", string.format("sectors=%d/14", done))
    if done < 14 then
        M.shot("stuck")
        return false, before, after
    end
    for _ = 1, 600 do                  -- let the dialog close before the flush
        if not dialog() then break end
        M.advance()
    end
    return true, before, after
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

    local ok, before, after = M.save_via_menu(cp, domain)
    if not ok then
        M.finish(false, string.format("the in-game save never advanced the sector counter "
                                   .. "(%d -> %d). See patch/build/gen3_stuck.png", before, after))
    end

    pcall(client.saveram)              -- flush the battery file before we exit
    M.idle(60)
    M.phase("flushed")
    M.finish(true, string.format("counter %d -> %d", before, after))
end

-- `source == "main"` ONLY for a top-level `--lua=` script; a dofile'd chunk sees its own path
-- (reference_bizhawk_lua_selflocate). So the sibling driver gets the helpers, not a run.
if (debug.getinfo(1, "S").source or "") == "main" then run() end

return M
