-- test_live_choosepartymon.lua — SPIKE + validation for OP_CHOOSE_PARTY_MON (the pick-the-pair menu).
-- Opens the native "Choose a POKeMON" party menu (FireRed `special ChoosePartyMon`, idx 170) via a
-- field script and confirms the chosen slot round-trips into the mailbox result (Var8004 @ 0x020370C0).
-- Validates the FR special index works on the RR build. Needs the overworld savestate (has a party).
-- Load with the PATCHED ROM:  EmuHawk.exe --lua=<this> patch/build/slink_RR.gba
local WT  = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/choosepartymon_result.txt"
local MB  = dofile(WT .. "/lua/mailbox.lua")
local SC2 = 0x03000F9C

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
if not MB.present() then log("FAIL: beacon absent (unpatched ROM?)"); finish(); return end
log("beacon up")

local CB2 = 0x030030F4
local V8004 = 0x020370C0
local cb_before = memory.read_u32_le(CB2)
local seq = MB.choose_party_mon()
check("MB.choose_party_mon returned a seq", seq ~= nil, "seq=" .. tostring(seq))
if not seq then finish(); return end

-- Drive: let the party menu fade in, then press A (cursor defaults to slot 0 → CHOOSE_AND_CLOSE picks
-- it). Alternate A (GBA reads edges). Poll the seq; the patch acks once Var8004 leaves the 0xFF sentinel.
local saw_menu, acked, st = false, false, nil
local cb_changed = false
for i = 1, 600 do
    local cbnow = memory.read_u32_le(CB2)
    if cbnow ~= cb_before then cb_changed = true; saw_menu = true end
    if (memory.read_u8(SC2) or 0) ~= 0 then saw_menu = true end
    if i > 30 and i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
    emu.frameadvance()
    if i % 60 == 0 then log(string.format("  .f%d cb2=%08X v8004=%d", i, memory.read_u32_le(CB2), memory.read_u16_le(V8004))) end
    st = MB.poll(seq); if st then acked = true; break end
end
log(string.format("cb2 before=%08X after=%08X changed=%s v8004=%d", cb_before, memory.read_u32_le(CB2),
    tostring(cb_changed), memory.read_u16_le(V8004)))
check("party menu opened (gMain.callback2 changed)", cb_changed)
check("chooser acked", acked, "status=" .. tostring(st))
check("ack is ST_OK", st == MB.ST_OK)
local slot = MB.choose_result()
check("a valid slot came back (0-5 chosen, or 7=cancel)", slot ~= nil and slot <= 7,
      "slot=" .. tostring(slot))
check("selected a party mon (slot 0-5, not the 0xFF sentinel)", slot ~= nil and slot <= 5,
      "slot=" .. tostring(slot))
check("beacon still present (no crash)", MB.present())
finish()
