-- test_live_choosepartymon.lua — OP_CHOOSE_PARTY_MON (the pick-the-pair menu) through
-- lua/gen3/native.lua. native:choose_mon opens the native "Choose a POKeMON" party menu (FireRed
-- `special ChoosePartyMon`, idx 170) via a field script; the chosen slot must round-trip from the
-- mailbox result (Var8004) into native's mon_chosen event. Needs the overworld savestate (has a
-- party). PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local SC2 = 0x03000F9C
local V8004 = 0x020370C0
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
t.check("beacon still present (no crash)", t.present())
t.finish()
