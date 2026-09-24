-- test_live_menu.lua — LIVE validation of OP_SHOW_MENU (the talk-to-partner menuing FOUNDATION)
-- through lua/gen3/native.lua. native:show_menu stages the prompt in TEXT_BUF and posts the YES/NO
-- menu; we drive the box to a selection and assert the choice round-trips from the mailbox result
-- (gSpecialVar_Result) into native's menu_result event. The whole pipe:
--   native:show_menu -> OP_SHOW_MENU -> field script (lockall/msgbox YESNO/releaseall) -> player
--   picks -> patch publishes gSpecialVar_Result -> native done(result) -> send("menu_result").
-- Needs the overworld savestate (a field script only runs in the overworld). PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local SC2 = 0x03000F9C   -- sScriptContext2Enabled (non-zero while the field script is up)
local t = G.open("menu")
t.boot({ state = "slink_overworld.State" })

local job = t.watch(t.native:show_menu({ token = 7, text = "Trade with your partner?" }))
t.check("native:show_menu queued the op", job ~= nil)
if not job then t.finish() end
t.check("op posted to the mailbox (dispatch receipt)", t.wait_posted(job))

-- Drive the box: alternate A (GBA reads button EDGES) to advance the message then select YES (the
-- default cursor). The patch acks ST_OK once the field script ends.
local saw_box = false
local r = t.wait(job, 300, function(i)
    if memory.read_u8(SC2) ~= 0 then saw_box = true end
    return i % 2 == 0 and { A = true } or nil
end)
t.check("native field menu actually opened (sScriptContext2Enabled set)", saw_box)
t.check("menu acked", r ~= nil, t.receipt_str(r))
t.check("ack is ST_OK", r ~= nil and r.why == nil, t.receipt_str(r))
local res = r and r.result
t.check("choice round-tripped (result is 0=NO or 1=YES)", res == 0 or res == 1, "result=" .. tostring(res))
t.check("selected YES (default cursor + A)", res == 1, "result=" .. tostring(res))
local sent = t.sent_of("menu_result")
t.check("native sent menu_result{token=7, choice=1}",
        #sent == 1 and sent[1].token == 7 and sent[1].choice == 1,
        #sent == 1 and ("choice=" .. tostring(sent[1].choice)) or (#sent .. " menu_result events"))
t.check("dialogue closed (no stuck box / softlock)", memory.read_u8(SC2) == 0)
t.check("beacon still present (no crash)", t.present())
t.finish()
