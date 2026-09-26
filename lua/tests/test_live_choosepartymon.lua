-- test_live_choosepartymon.lua — OP_CHOOSE_PARTY_MON (the pick-the-pair menu) through
-- lua/gen3/native.lua. native:choose_mon opens the native "Choose a POKeMON" party menu (FireRed
-- `special ChoosePartyMon`, idx 170) via a field script; the chosen slot must round-trip from the
-- mailbox result (Var8004) into native's mon_chosen event. Needs the overworld savestate (has a
-- party). PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local SC2 = 0x03000F9C
local V8004 = 0x020370C0
local CTX_STATUS = 0x03000EA8   -- sGlobalScriptContextStatus (write_checkpoint script_context_status; 2 = shutdown)
local t = G.open("choosepartymon")
t.boot({ state = "slink_overworld.State" })

local CB2 = t.P.GMAIN_CB2_PTR   -- gMain.callback2
local cb_before = memory.read_u32_le(CB2)
local job = t.watch(t.native:choose_mon({ token = 9 }))
t.check("native:choose_mon queued the op", job ~= nil)
if not job then t.finish() end
t.check("op posted to the mailbox (dispatch receipt)", t.wait_posted(job))

-- Drive: let the party menu fade in, then press A (cursor defaults to slot 0 -> CHOOSE_AND_CLOSE
-- picks it). Alternate A (GBA reads edges). The patch acks once Var8004 leaves the 0xFF sentinel.
local cb_changed = false
local r = t.wait(job, 600, function(i)
    if memory.read_u32_le(CB2) ~= cb_before then cb_changed = true end
    if i % 60 == 0 then
        t.log(string.format("  .f%d cb2=%08X v8004=%d", i, memory.read_u32_le(CB2), memory.read_u16_le(V8004)))
    end
    return (i > 30 and i % 2 == 0) and { A = true } or nil
end)
t.log(string.format("cb2 before=%08X after=%08X changed=%s v8004=%d", cb_before, memory.read_u32_le(CB2),
    tostring(cb_changed), memory.read_u16_le(V8004)))
t.check("party menu opened (gMain.callback2 changed)", cb_changed)
t.check("chooser acked", r ~= nil, t.receipt_str(r))
t.check("ack is ST_OK", r ~= nil and r.why == nil, t.receipt_str(r))
local slot = r and r.result
t.check("a valid slot came back (0-5 chosen, or 7=cancel)", slot ~= nil and slot <= 7, "slot=" .. tostring(slot))
t.check("selected a party mon (slot 0-5, not the 0xFF sentinel)", slot ~= nil and slot <= 5,
        "slot=" .. tostring(slot))
local sent = t.sent_of("mon_chosen")
t.check("native sent mon_chosen{token=9, slot}", #sent == 1 and sent[1].token == 9 and sent[1].slot == slot,
        #sent == 1 and ("slot=" .. tostring(sent[1].slot)) or (#sent .. " mon_chosen events"))

-- After the pick the field must be released: the script's waitstate resumes and hits `end`
-- (context status 2), and field controls unlock. The client's overworld checkpoint refuses every
-- write until then (RR duo trade_gen3: A never got the native scene, 1800 frames of
-- "script_context_status"). FR's own ChoosePartyMon returns through gFieldCallback2 =
-- CB2_FadeFromPartyMenu -> Task_PartyMenuWaitForFade -> EnableBothScriptContexts.
local released
for i = 1, 600 do
    if memory.read_u8(CTX_STATUS) == 2 and memory.read_u8(SC2) == 0 then released = i; break end
    t.step(nil)
end
t.log(string.format("after the pick: ctx_status=%d sc2=%d cb2=%08X released_after=%s",
    memory.read_u8(CTX_STATUS), memory.read_u8(SC2), memory.read_u32_le(CB2), tostring(released)))
t.check("the field script ended after the pick (context status 2 within 600 frames)",
        memory.read_u8(CTX_STATUS) == 2, "status=" .. memory.read_u8(CTX_STATUS))
t.check("beacon still present (no crash)", t.present())
t.finish()
