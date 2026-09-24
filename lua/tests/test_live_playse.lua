-- test_live_playse.lua — LIVE validation of OP_PLAY_SE (native sound) through lua/gen3/native.lua.
-- The client routes the server's play_sound to native:play_sound (PlaySE in the patch) instead of the
-- m4a SE1 poke. Headless can't assert audio, so this proves the opcode posts, runs and acks cleanly
-- (no crash) for a real SE id. PATCHED ROM, cold boot.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("playse")
t.boot()

local job = t.watch(t.native:play_sound(25))   -- SE_SUCCESS (a real FRLG sound-effect id)
t.check("native:play_sound queued the op", job ~= nil)
t.check("op posted to the mailbox (dispatch receipt)", t.wait_posted(job))
local r = t.wait(job, 60)
t.check("opcode acked", r ~= nil, t.receipt_str(r))
t.check("ack is ST_OK", r ~= nil and r.why == nil, t.receipt_str(r))
t.check("beacon still present (no crash)", t.present())
t.finish()
