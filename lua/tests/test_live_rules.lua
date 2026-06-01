-- test_live_rules.lua — Phase-5 ROM-enforced settings: SET_RULES persistently keeps the
-- battle style on SET (the classic nuzlocke "no free switch after a KO" rule) so the player
-- can't change it back in the options menu. Load with the PATCHED ROM + overworld savestate.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/rules_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local STYLE = 0x0200  -- optionsBattleStyle bit (1 = SET)

local function sb2() return memory.read_u32_le(0x0300500C) end
local function opts() return memory.read_u16_le(sb2() + 0x14) end
local function set_style_shift() local o = opts(); memory.write_u16_le(sb2() + 0x14, o & (~STYLE & 0xFFFF)) end
local function style_is_set() return (opts() & STYLE) ~= 0 end

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
log(string.format("SaveBlock2 @ 0x%08X  options=0x%04X", sb2(), opts()))

-- start from SHIFT, enable enforcement -> becomes SET and STAYS set
set_style_shift()
check("battle style starts SHIFT", not style_is_set())
check("SET_RULES(enforce) acked", send_wait(MB.OP_SET_RULES, {1}))
for _=1,5 do emu.frameadvance() end
check("battle style now SET (enforced)", style_is_set())

-- player tries to change it back -> patch re-enforces it
set_style_shift()
for _=1,5 do emu.frameadvance() end
check("re-enforced to SET after a change attempt", style_is_set())

-- disable enforcement -> a change now sticks
check("SET_RULES(off) acked", send_wait(MB.OP_SET_RULES, {0}))
set_style_shift()
for _=1,5 do emu.frameadvance() end
check("SHIFT sticks once enforcement is off", not style_is_set())
check("game still running", MB.present())
finish()
