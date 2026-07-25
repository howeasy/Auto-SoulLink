-- test_live_msgboxdismiss.lua — OP_SHOW_MESSAGE must now be a DISMISSABLE dialogue (the waved-at
-- player's "Your partner waved at you!" box used to stick open). The patch routes it through the
-- std sign-msgbox script (lockall/message/waitbuttonpress/releaseall). Assert: showing the message
-- enables a field script (sScriptContext2Enabled != 0), and an A-press dismisses it (returns to 0).
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/msgboxdismiss_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local SCRIPT_ACTIVE = 0x03000F9C   -- sScriptContext2Enabled (u8 != 0 while a field script is up)
local function script_up() return memory.read_u8(SCRIPT_ACTIVE) ~= 0 end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
check("patch present", MB.present()); if not MB.present() then finish(); return end
check("no script up initially", not script_up())

-- Show a message via the opcode (text pre-written to the buffer).
MB.write_message("Your partner waved at you!")
MB.send(MB.OP_SHOW_MESSAGE, {})
local up = false
for _=1,30 do emu.frameadvance(); if script_up() then up = true; break end end
check("OP_SHOW_MESSAGE opened a dismissable dialogue (script active)", up)

-- Press A to advance/dismiss; the box should close and release the player.
joypad.set({}); emu.frameadvance()
joypad.set({A=true}); emu.frameadvance()
joypad.set({}); for _=1,40 do emu.frameadvance() end
-- a single A may just print; mash A a couple more times to close any wait-button-press
for _=1,3 do joypad.set({A=true}); emu.frameadvance(); joypad.set({}); for _=1,15 do emu.frameadvance() end end
check("dialogue dismissed by A (script no longer active)", not script_up())
finish()
