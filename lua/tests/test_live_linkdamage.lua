-- test_live_linkdamage.lua — Phase-5 linked battle rules: APPLY_DAMAGE (linked HP / chip)
-- and CURE_STATUS (link-cured status). Confirms chip damage reduces the battler's HP by the
-- amount (clamped to 0 = faint), and CURE_STATUS clears the non-volatile status. Load with
-- the PATCHED ROM + in-battle savestate.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/linkdamage_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local gBM = 0x02023BE4
local function hp(b)     return memory.read_u16_le(gBM + b*0x58 + 0x28) end
local function set_hp(b,v) memory.write_u16_le(gBM + b*0x58 + 0x28, v) end
local function status1(b) return memory.read_u32_le(gBM + b*0x58 + 0x4C) end
local function set_st(b,v) memory.write_u32_le(gBM + b*0x58 + 0x4C, v) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end
local function send_wait(op,args) local s=MB.send(op,args); for _=1,30 do emu.frameadvance(); if MB.poll(s) then return true end end; return false end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_battle.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end

local B = 0
-- chip damage: set a known HP, then apply 5
set_hp(B, 30)
check("APPLY_DAMAGE acked", send_wait(MB.OP_APPLY_DAMAGE, MB.apply_damage_args(B, 5)))
check("hp 30 -> 25 (chip 5)", hp(B) == 25, "hp="..hp(B))
check("result[0..1] == new hp 25", (MB.read_result_u8(0) | (MB.read_result_u8(1) << 8)) == 25)

-- another chip
send_wait(MB.OP_APPLY_DAMAGE, MB.apply_damage_args(B, 10))
check("hp 25 -> 15 (chip 10)", hp(B) == 15, "hp="..hp(B))

-- lethal chip clamps to 0 (a partner-faint linked KO)
send_wait(MB.OP_APPLY_DAMAGE, MB.apply_damage_args(B, 9999))
check("lethal chip clamps to 0 (linked KO)", hp(B) == 0, "hp="..hp(B))
check("result[0..1] == 0", (MB.read_result_u8(0) | (MB.read_result_u8(1) << 8)) == 0)

-- link-cured status: set poison, then cure
set_st(B, 0x08)   -- STATUS1_POISON
check("status set to poison", status1(B) == 0x08)
check("CURE_STATUS acked", send_wait(MB.OP_CURE_STATUS, {B}))
check("status cleared (link-cured)", status1(B) == 0, "status="..status1(B))

check("game still running", MB.present())
finish()
