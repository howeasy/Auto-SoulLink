-- test_live_battlemsg.lua — native IN-BATTLE notification text (OP_SHOW_BATTLE_MESSAGE / op23).
--
-- The patch's drive_battle_notif re-asserts FR-encoded text (SLINK_TEXT_BUF) via BattlePutTextOnWindow
-- into a chosen window id each frame. On the in-battle savestate this gate:
--   1. asserts the automatable contract: the notification goes active, its timer runs out and clears
--      it, and the game keeps running (beacon + still in battle);
--   2. sweeps window ids 0..15, one screenshot each (patch/build/battlemsg_winNN.png), to decide
--      which window the notification should draw into (inspected by eye; not an oracle).
-- DEFERRED (native text is off for the RC): opt-in via SLINK_GATES_DEFERRED=1. Posted through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c). Battle savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("battlemsg")
local DIR = t.ROOT .. "/patch/build"
local STATE = "slink_battle.State"
local BN_ACTIVE, BN_FRAMES = t.P.BATTLE_NOTIF + 0, t.P.BATTLE_NOTIF + 4
local gBM, gOutcome = 0x02023BE4, 0x02023E8A
local function in_battle() return memory.read_u16_le(gBM + 0x2C) > 0 and memory.read_u8(gOutcome) == 0 end
local function shot(name) pcall(function() client.screenshot(DIR .. "/" .. name) end) end
-- args: [0..1] = duration frames, [2] = window id (0 -> 0xD), [3] = 0; text (+ colour) in TEXT_BUF
local function show_battle_message(text, frames, win, color)
    return t.raw_wait("OP_SHOW_BATTLE_MESSAGE", { frames % 256, (frames // 256) % 256, win or 0, 0 },
                      { t.message_stage(text, color) }, 30)
end

t.boot({ state = STATE, native = false })
if not in_battle() then t.fail("savestate is in battle") end

-- baseline (no notification) for comparison
t.idle(4)
shot("battlemsg_baseline.png")
t.log("baseline captured")

-- ── automatable contract: timer decrements + clears on timeout, no freeze ──
local r = show_battle_message("SLink TEST", 90, 0, 0x00)   -- colour 0, message window
t.check("SHOW_BATTLE_MESSAGE acked OK", t.acked_ok(r), t.receipt_str(r))
t.idle(2)
local active0 = memory.read_u8(BN_ACTIVE)
local frames0 = memory.read_u16_le(BN_FRAMES)
local beacon_a = t.present()
local cleared = false
for _ = 1, 150 do t.step(nil); if memory.read_u8(BN_ACTIVE) == 0 then cleared = true; break end end
local beacon_b = t.present() and in_battle()
t.log(string.format("sanity: active=%d frames=%d -> cleared=%s beacon=%s/%s",
    active0, frames0, tostring(cleared), tostring(beacon_a), tostring(beacon_b)))
t.check("notification went active", active0 == 1)
t.check("timer ran out and cleared it", cleared)
t.check("game kept running (beacon + still in battle)", beacon_a and beacon_b)

-- ── placement sweep: render into each window id, screenshot (information only) ──
local MAXWIN = 15
for win = 0, MAXWIN do
    t.boot({ state = STATE, native = false })             -- reload to a clean frame per id
    show_battle_message(string.format("WIN %02d", win), 600, win, 0x00)
    t.idle(10)                                            -- let drive_battle_notif re-assert + render
    shot(string.format("battlemsg_win%02d.png", win))
    t.log(string.format("win %02d: shot taken (active=%d in_battle=%s)",
        win, memory.read_u8(BN_ACTIVE), tostring(in_battle())))
end
t.log("sweep complete: " .. (MAXWIN + 1) .. " window ids")
t.finish()
