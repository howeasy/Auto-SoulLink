-- gen3_emerald_boot_check.lua — Emerald (BPEE) cold boot -> CONTINUE -> in-game SAVE -> flush.
--
-- The Emerald twin of gen3_boot_check.lua (card E1-FIX, EF-10). Launched by
-- `tools/gen3_fixtures.py boot-check --title emerald` and `make-emerald`; the Python side
-- re-imports the flushed battery and judges it (counter +1, party unchanged, and for
-- make-emerald the tile and the cleared continue-game warp).
--
-- Why a twin and not gen3_boot_check.lua itself: that driver's START-menu witnesses are FR/LG's
-- task-based menu (sStartMenuWindowId, Task_StartMenuHandleInput) and its section sizes are
-- FR/LG's SaveBlocks. Emerald's menu is gMenuCallback-driven (pret pokeemerald src/start_menu.c
-- :560-633), so every witness below is Emerald's own. The generic pieces (result file, logging,
-- frame budget, flash domain, save counter) are reused from gen3_boot_check.lua by dofile.
--
-- Every address is read from data/gen3/pret/pokeemerald.sym at start-up (no hardcoded address).
-- Phase transitions are logged; nothing logs per frame.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via tools/gen3_fixtures.py")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")

local NAMES = {
    "gMain", "CB2_Overworld", "sLockFieldControls", "gMenuCallback", "gTasks",
    "Task_ShowStartMenu", "HandleStartMenuInput", "StartMenuSaveCallback", "SaveStartCallback",
    "SaveCallback", "sStartMenuCursorPos", "sNumStartMenuActions", "sCurrentStartMenuActions",
    "gSaveBlock1Ptr", "gSaveFileStatus",
}

local function load_syms()
    local want, out = {}, {}
    for _, n in ipairs(NAMES) do want[n] = true end
    for line in io.lines(WT .. "/data/gen3/pret/pokeemerald.sym") do
        local addr, name = line:match("^(%x+) %a+ %x+ (%S+)$")
        if addr and want[name] then out[name] = tonumber(addr, 16) end
    end
    for _, n in ipairs(NAMES) do assert(out[n], "symbol " .. n .. " missing from pokeemerald.sym") end
    return out
end
local S = load_syms()

-- struct Main.callback2 at +4 (include/main.h:11); struct Task {func, isActive, ...} is 40 bytes,
-- 16 tasks (include/task.h:8-22); MENU_ACTION_SAVE is 5 (start_menu.c:51-58);
-- SAVE_STATUS_OK is 1 (include/save.h:35).
local CB2_OFF, TASK_COUNT, TASK_SIZE, MENU_ACTION_SAVE, SAVE_STATUS_OK = 4, 16, 40, 5, 1
local function thumb(a) return a | 1 end
local function cb2() return memory.read_u32_le(S.gMain + CB2_OFF) end
local function locked() return memory.read_u8(S.sLockFieldControls) ~= 0 end
local function menu_cb() return memory.read_u32_le(S.gMenuCallback) end
local function task_live(fn)
    for i = 0, TASK_COUNT - 1 do
        local base = S.gTasks + i * TASK_SIZE
        if memory.read_u8(base + 4) ~= 0 and memory.read_u32_le(base) == thumb(fn) then return true end
    end
    return false
end
-- input ready: the draw task handed over to Task_ShowStartMenu, which set gMenuCallback (:560-575)
local function menu_ready()
    return task_live(S.Task_ShowStartMenu) and menu_cb() == thumb(S.HandleStartMenuInput)
end
local function save_dialog()
    local c = menu_cb()
    return c == thumb(S.StartMenuSaveCallback) or c == thumb(S.SaveStartCallback)
        or c == thumb(S.SaveCallback)
end
local function where()
    local sb1 = memory.read_u32_le(S.gSaveBlock1Ptr)
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return "sb1=unset" end
    return string.format("map=%d.%d pos=(%d,%d)", memory.read_s8(sb1 + 4), memory.read_s8(sb1 + 5),
                         memory.read_s16_le(sb1), memory.read_s16_le(sb1 + 2))
end
local function pulse(btn, i) joypad.set(i % 16 == 8 and { [btn] = true } or {}) end

--- Title screen -> CONTINUE -> the field, controls free for 60 frames. A only (never Start: in the
--- field Start would open the menu this driver has to open itself).
local function boot_to_field(frames)
    local held, seen = 0, false
    for i = 1, frames do
        if cb2() == thumb(S.CB2_Overworld) then
            if not seen then seen = true; G.phase("overworld-cb2", where()) end
            joypad.set({})
            held = locked() and 0 or held + 1
            if held >= 60 then return true end
        else
            held = 0
            pulse("A", i)
        end
        G.advance()
    end
    return false
end

local function wait(frames, pred)
    for _ = 1, frames do
        if pred() then return true end
        G.advance()
    end
    return pred()
end

local function save_via_menu(domain)
    local before = G.save_counter(domain)
    G.phase("save-menu", "counter=" .. before)
    local opened = false
    for _ = 1, 5 do
        if not wait(300, function() return not locked() end) then
            return false, before, "field controls never freed"
        end
        G.tap("Start", 3, 0)
        if wait(120, menu_ready) then opened = true; break end
    end
    if not opened then return false, before, "the START menu never took input" end

    local n, row = memory.read_u8(S.sNumStartMenuActions), nil
    for i = 0, n - 1 do
        if memory.read_u8(S.sCurrentStartMenuActions + i) == MENU_ACTION_SAVE then row = i; break end
    end
    if not row then return false, before, "no SAVE row among " .. n .. " START items" end
    for _ = 1, n + 8 do
        if memory.read_u8(S.sStartMenuCursorPos) == row then break end
        if not menu_ready() then return false, before, "the START menu closed during the row walk" end
        G.tap("Down", 3, 13)
    end
    if memory.read_u8(S.sStartMenuCursorPos) ~= row then
        return false, before, "cursor never reached the SAVE row " .. row
    end
    G.tap("A", 3, 0)
    if not wait(120, save_dialog) then return false, before, "the save dialog never opened" end
    G.phase("save-dialog", "row=" .. row .. "/" .. n)

    -- YES is the default on the save prompt; the counter, not the presses, is the verdict
    local after, i = before, 0
    local moved = wait(4800, function()
        i = i + 1
        pulse("A", i)
        if i % 16 ~= 0 then return false end
        after = G.save_counter(domain)
        return after > before
    end)
    if not moved then return false, before, "the save counter never advanced" end
    G.phase("saved", string.format("counter=%d->%d", before, after))
    -- SaveCallback's SAVE_SUCCESS is the only exit that unlocks field controls (:828-834)
    i = 0
    if not wait(600, function() i = i + 1; pulse("A", i); return not locked() end) then
        return false, before, "the save dialog never closed"
    end
    joypad.set({})
    local ok, err = pcall(client.saveram)
    if not ok then return false, before, "SaveRAM flush failed: " .. tostring(err) end
    return true, before, string.format("counter %d -> %d", before, after)
end

G.open("gen3_emerald_boot_check")      -- patch/build/gen3_emerald_boot_check_result.txt
pcall(client.speedmode, 6399)
G.phase("start", "title=emerald")
local domain, seen = G.flash_domain()
if not domain then G.finish(false, "no 0x20000 flash domain; domains: " .. tostring(seen)) end
local seeded = G.save_counter(domain)
if seeded < 0 then G.finish(false, "the battery is erased at boot — the seed was not found") end
G.phase("seeded", "domain=" .. domain .. " counter=" .. seeded)

if not boot_to_field(9000) then
    G.shot("stuck")
    G.finish(false, string.format("never reached a free field in 9000 frames (callback2=%08X "
                                  .. "saveFileStatus=%d)", cb2(), memory.read_u16_le(S.gSaveFileStatus)))
end
local status = memory.read_u16_le(S.gSaveFileStatus)
G.phase("field", where() .. " saveFileStatus=" .. status)
if status ~= SAVE_STATUS_OK then G.finish(false, "gSaveFileStatus " .. status .. " is not OK") end

local ok, _, msg = save_via_menu(domain)
if not ok then G.shot("stuck"); G.finish(false, "the in-game save failed: " .. msg) end
G.idle(60)
G.phase("flushed", where())
G.finish(true, msg .. " " .. where())
