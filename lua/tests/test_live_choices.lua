-- test_live_choices.lua — SPIKE + validation for OP_SHOW_CHOICES (the PROPER multichoice list menu).
-- Stages a custom option list {"TRADE","WAVE"} and opens a native vertical multichoice (replicated
-- DrawVerticalMultichoiceMenu in C + the engine's input task). Confirms the menu opens and the chosen
-- index round-trips into the mailbox result. Needs the overworld savestate (a field menu).
-- Load with the PATCHED ROM:  EmuHawk.exe --lua=<this> patch/build/slink_RR.gba
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
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

-- MALFORMED STAGES MUST BE REJECTED AT THE OPCODE, NOT INSIDE THE CALLNATIVE.
-- show_choices_entry runs from a lockall'd field script whose `waitstate` is resolved ONLY by the
-- input task it creates, so any early return from it strands the player in a locked overworld with
-- no window and no way out — a reset-only softlock. The guards therefore live in OP_SHOW_CHOICES,
-- before lockall, and the entry clamps and repairs instead of bailing. Each case below asserts BOTH
-- halves: a clean ST_FAIL, and the field left unlocked. (Modelled on test_live_infoscreen steps 1-2,
-- which is where this class of bug was first caught.)
local function poll_for(sq, frames)
    for _ = 1, (frames or 180) do
        emu.frameadvance()
        local s = MB.poll(sq); if s then return s end
    end
    return nil
end
local function reject_case(name, stage)
    -- Re-load so each case starts from a known-good, unlocked overworld.
    pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
    emu.frameadvance()
    for _ = 1, 240 do emu.frameadvance(); if MB.present() then break end end
    stage()
    local sq = MB.send(MB.OP_SHOW_CHOICES, { 0 })
    local s = poll_for(sq)
    check(name .. ": ST_FAIL", s == MB.ST_FAIL, "status=" .. tostring(s))
    check(name .. ": field not locked", (memory.read_u8(SC2) or 0) == 0)
end

reject_case("count 0", function() memory.write_u8(MB.MENU_BUF, 0) end)
reject_case("count 9 (over the 8 the window can hold)", function()
    memory.write_u8(MB.MENU_BUF, 9)
    for i = 1, 40 do memory.write_u8(MB.MENU_BUF + i, 0xFF) end
end)
reject_case("option with no terminator", function()
    memory.write_u8(MB.MENU_BUF, 1)
    -- fill the whole buffer with a printable glyph so no 0xFF appears anywhere after the count
    for i = 1, 111 do memory.write_u8(MB.MENU_BUF + i, 0xBB) end
end)

-- ...and a well-formed stage must still work after all that, so the guards cannot have been
-- "fixed" by simply rejecting everything.
local sq2 = MB.show_choices({ "TRADE", "WAVE" })
local st2 = nil
for i = 1, 300 do
    if i > 30 and i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
    emu.frameadvance()
    st2 = MB.poll(sq2); if st2 then break end
end
check("a valid list still opens and acks after the rejections", st2 == MB.ST_OK,
      "status=" .. tostring(st2))
check("field released again", (memory.read_u8(SC2) or 0) == 0)
finish()
