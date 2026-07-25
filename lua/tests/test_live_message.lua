-- test_live_message.lua — Phase-4 native UI: SHOW_MESSAGE (native field message box) +
-- PLAY_FANFARE. SHOW_MESSAGE runs the DISMISSABLE sign-msgbox field script (run_sign_msgbox:
-- loadword TEXT_BUF / callstd MSGBOX_SIGN), so it reads SLINK_TEXT_BUF directly — it does NOT
-- copy into gStringVar4 the way the old bare ShowFieldMessage did. We confirm: the opcode acks
-- "shown", a box is actually up (an immediate second call reports "busy"), the FR text was staged
-- in TEXT_BUF, and PLAY_FANFARE acks without crashing. Load with the PATCHED ROM + overworld save.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/message_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local gStringVar4 = 0x02021D18

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end
local function send_wait(op,args) local s=MB.send(op,args); for _=1,30 do emu.frameadvance(); if MB.poll(s) then return true end end; return false end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end

-- SHOW_MESSAGE
local TEXT = "SLink linked Pikachu"
MB.write_message(TEXT)
check("SHOW_MESSAGE acked", send_wait(MB.OP_SHOW_MESSAGE, {}))
check("ShowFieldMessage returned shown (1)", MB.read_result_u8(0) == 1, "result="..MB.read_result_u8(0))

-- immediate second call: a box is up -> returns busy (0)
local busy = send_wait(MB.OP_SHOW_MESSAGE, {})
check("second SHOW reports box busy (0)", MB.read_result_u8(0) == 0, "result="..MB.read_result_u8(0))

-- The FR-encoded text was staged in the patch's TEXT_BUF (what run_sign_msgbox's field script reads).
-- (The dismissable sign-msgbox reads TEXT_BUF directly; it does NOT route through gStringVar4.)
local enc = MB.fr_encode(TEXT)
local match, firstbad = true, nil
for i = 1, #enc do
    if memory.read_u8(MB.TEXT_BUF + (i-1)) ~= enc[i] then match = false; firstbad = i; break end
end
check("FR text staged in TEXT_BUF for the field script", match,
      firstbad and ("first mismatch at "..firstbad) or nil)

-- let the box's task run a while; the game must keep running (no crash/freeze)
for _=1,120 do emu.frameadvance() end
check("game still running after message (beacon stable)", MB.present())

-- PLAY_FANFARE (song 1 = a fanfare); validate it acks + doesn't crash
check("PLAY_FANFARE acked", send_wait(MB.OP_PLAY_FANFARE, MB.fanfare_args(1)))
for _=1,30 do emu.frameadvance() end
check("game still running after fanfare", MB.present())
finish()
