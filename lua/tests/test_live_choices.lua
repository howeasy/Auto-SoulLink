-- test_live_choices.lua — SPIKE + validation for OP_SHOW_CHOICES (the PROPER multichoice list menu).
-- Stages a custom option list {"TRADE","WAVE"} and opens a native vertical multichoice (replicated
-- DrawVerticalMultichoiceMenu in C + the engine's input task). Confirms the menu opens and the chosen
-- index round-trips into the mailbox result. Needs the overworld savestate (a field menu).
-- Load with the PATCHED ROM:  EmuHawk.exe --lua=<this> patch/build/slink_RR.gba
local WT  = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/choices_result.txt"
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

local seq = MB.show_choices({ "TRADE", "WAVE" })
check("MB.show_choices returned a seq", seq ~= nil, "seq=" .. tostring(seq))
if not seq then finish(); return end

-- Drive: let the menu open, then press A (cursor defaults to index 0 = TRADE). Poll the seq.
local saw_menu, acked, st = false, false, nil
for i = 1, 300 do
    if (memory.read_u8(SC2) or 0) ~= 0 then saw_menu = true end
    if i > 30 and i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
    emu.frameadvance()
    st = MB.poll(seq); if st then acked = true; break end
end
check("native multichoice opened (field script locked)", saw_menu)
check("choices acked", acked, "status=" .. tostring(st))
check("ack is ST_OK", st == MB.ST_OK)
local idx = MB.menu_result()
check("chose index 0 (TRADE, default cursor + A)", idx == 0, "index=" .. tostring(idx))
check("dialogue closed (no stuck menu)", (memory.read_u8(SC2) or 0) == 0)
check("beacon still present (no crash)", MB.present())
finish()
