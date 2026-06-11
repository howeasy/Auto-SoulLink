-- test_live_battlemsg.lua — HEADLESS screenshot sweep for native IN-BATTLE notification text
-- (OP_SHOW_BATTLE_MESSAGE / op23). Decides WHICH battle window id our notification should draw into.
--
-- The patch's drive_battle_notif re-asserts FR-encoded text (SLINK_TEXT_BUF) via BattlePutTextOnWindow into
-- a chosen window id each frame. This test, on the in-battle savestate (action-select screen — so BOTH the
-- bottom message window AND the menu windows are present), fires the notification into each window id 0..N,
-- captures a screenshot per id, and writes a result file. The PNGs are then inspected to see where each
-- window draws + whether any id corrupts the battle graphics.
--
-- Run headless:
--   EmuHawk.exe --lua=lua/tests/test_live_battlemsg.lua patch/build/slink_RR.gba   (relative paths, from worktree)
-- Outputs: patch/build/battlemsg_baseline.png, patch/build/battlemsg_winNN.png, patch/build/battlemsg_result.txt

local WT    = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local DIR   = WT .. "/patch/build"
local OUT   = DIR .. "/battlemsg_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_battle.State"
local MB    = dofile(WT .. "/lua/mailbox.lua")

local BN_ACTIVE, BN_FRAMES = MB.BATTLE_NOTIF + 0, MB.BATTLE_NOTIF + 4
local gBM, gOutcome = 0x02023BE4, 0x02023E8A
local function in_battle() return memory.read_u16_le(gBM + 0x2C) > 0 and memory.read_u8(gOutcome) == 0 end

local lines = {}; local function log(s) lines[#lines+1] = s; console.log(s) end
local function writeout(ok)
    lines[#lines+1] = ok and "RESULT: PASS" or "RESULT: FAIL"
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
end
local function shot(name) pcall(function() client.screenshot(DIR .. "/" .. name) end) end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE); emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
if not MB.present() then log("FAIL: beacon absent (unpatched ROM?)"); writeout(false); client.exit(); return end
if not in_battle() then log("FAIL: savestate is not in battle"); writeout(false); client.exit(); return end

-- baseline (no notification) for comparison
for _ = 1, 4 do emu.frameadvance() end
shot("battlemsg_baseline.png")
log("baseline captured")

-- ── automatable contract: timer decrements + clears on timeout, no freeze ──
MB.show_battle_message("SLink TEST", 90, 0, 0x00)   -- clear flag, message window
emu.frameadvance(); emu.frameadvance()
local active0 = memory.read_u8(BN_ACTIVE)
local frames0 = memory.read_u16_le(BN_FRAMES)
local beacon_a = MB.present()
local cleared = false
for _ = 1, 150 do emu.frameadvance(); if memory.read_u8(BN_ACTIVE) == 0 then cleared = true; break end end
local beacon_b = MB.present() and in_battle()
log(string.format("sanity: active=%d frames=%d -> cleared=%s beacon=%s/%s",
    active0, frames0, tostring(cleared), tostring(beacon_a), tostring(beacon_b)))
writeout(active0 == 1 and cleared and beacon_a and beacon_b)

-- ── placement sweep: render into each window id, screenshot ──
-- clear flag (0x00) so each id's text is unambiguous; the text says the id so shots can't be confused.
local MAXWIN = 15
for win = 0, MAXWIN do
    pcall(savestate.load, STATE); emu.frameadvance()   -- reload to a clean frame per id (no residue)
    MB.show_battle_message(string.format("WIN %02d", win), 600, win, 0x00)
    for _ = 1, 10 do emu.frameadvance() end             -- let drive_battle_notif re-assert + engine render
    shot(string.format("battlemsg_win%02d.png", win))
    log(string.format("win %02d: shot taken (active=%d in_battle=%s)",
        win, memory.read_u8(BN_ACTIVE), tostring(in_battle())))
end
log("sweep complete: " .. (MAXWIN + 1) .. " window ids")
client.exit()
