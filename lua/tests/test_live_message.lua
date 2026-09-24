-- test_live_message.lua — Phase-4 native UI: SHOW_MESSAGE (native field message box) + PLAY_FANFARE.
-- SHOW_MESSAGE runs the DISMISSABLE sign-msgbox field script (run_sign_msgbox: loadword TEXT_BUF /
-- callstd MSGBOX_SIGN), so it reads SLINK_TEXT_BUF directly. We confirm: the opcode acks "shown", a
-- box is actually up (an immediate second call reports "busy"), the FR text was staged in TEXT_BUF,
-- and PLAY_FANFARE acks without crashing.
-- DEFERRED (native text is off for the RC; PLAY_FANFARE rides with it): opt-in via
-- SLINK_GATES_DEFERRED=1. Posted through lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c).
-- Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("message")
t.boot({ state = "slink_overworld.State", native = false })

-- SHOW_MESSAGE (text staged in TEXT_BUF with the post)
local TEXT = "SLink linked Pikachu"
local stage = t.message_stage(TEXT)
local r = t.raw_wait("OP_SHOW_MESSAGE", {}, { stage }, 30)
t.check("SHOW_MESSAGE acked", r ~= nil, t.receipt_str(r))
t.check("ShowFieldMessage returned shown (1)", r ~= nil and r.result == 1, t.receipt_str(r))

-- immediate second call: a box is up -> returns busy (0)
local r2 = t.raw_wait("OP_SHOW_MESSAGE", {}, nil, 30)
t.check("second SHOW reports box busy (0)", r2 ~= nil and r2.result == 0, t.receipt_str(r2))

-- The FR-encoded text was staged in the patch's TEXT_BUF (what run_sign_msgbox's field script reads).
local match, firstbad = true, nil
for i, b in ipairs(stage[2]) do
    if memory.read_u8(t.P.TEXT_BUF + (i-1)) ~= b then match = false; firstbad = i; break end
end
t.check("FR text staged in TEXT_BUF for the field script", match,
        firstbad and ("first mismatch at " .. firstbad) or nil)

-- let the box's task run a while; the game must keep running (no crash/freeze)
t.idle(120)
t.check("game still running after message (beacon stable)", t.present())

-- PLAY_FANFARE (song 1 = a fanfare): args [0..1] = songId; validate it acks + doesn't crash
local r3 = t.raw_wait("OP_PLAY_FANFARE", { 1, 0 }, nil, 30)
t.check("PLAY_FANFARE acked", r3 ~= nil, t.receipt_str(r3))
t.idle(30)
t.check("game still running after fanfare", t.present())
t.finish()
