-- test_live_menu.lua — LIVE validation of OP_SHOW_MENU (the talk-to-partner menuing FOUNDATION).
-- Sends a native YES/NO menu over the FR-text buffer, drives the box to a selection, and asserts the
-- choice round-trips back into the mailbox result (gSpecialVar_Result). Proves the whole pipe:
--   Lua write_message -> OP_SHOW_MENU -> field script (lockall/msgbox YESNO/releaseall) -> player
--   picks -> patch publishes gSpecialVar_Result -> Lua MB.menu_result().
-- Also re-confirms gSpecialVar_Result @ 0x020370D0 on this RR build (YES default cursor + A => 1).
-- Needs the overworld savestate (a field script only runs in the overworld). Load with the PATCHED
-- ROM:  EmuHawk.exe --lua=<this> patch/build/slink_RR.gba
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/menu_result.txt"
local MB  = dofile(WT .. "/lua/mailbox.lua")
local SC2 = 0x03000F9C   -- sScriptContext2Enabled (non-zero while the field script is up)

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

local seq = MB.show_menu("Trade with your partner?")
check("MB.show_menu returned a seq", seq ~= nil, "seq=" .. tostring(seq))
if not seq then finish(); return end

-- Drive the box: alternate A (GBA reads button EDGES) to advance the message then select YES (the
-- default cursor). Poll the seq every frame; the patch acks ST_OK once the field script ends.
local saw_box, acked, st = false, false, nil
for i = 1, 300 do
    if (memory.read_u8(SC2) or 0) ~= 0 then saw_box = true end
    if i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
    emu.frameadvance()
    st = MB.poll(seq); if st then acked = true; break end
end
check("native field menu actually opened (sScriptContext2Enabled set)", saw_box)
check("menu acked", acked, "status=" .. tostring(st))
check("ack is ST_OK", st == MB.ST_OK)
local res = MB.menu_result()
check("choice round-tripped (result is 0=NO or 1=YES)", res == 0 or res == 1, "result=" .. tostring(res))
check("selected YES (default cursor + A)", res == 1, "result=" .. tostring(res))
check("dialogue closed (no stuck box / softlock)", (memory.read_u8(SC2) or 0) == 0)
check("beacon still present (no crash)", MB.present())
finish()
