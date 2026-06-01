-- test_live_peerinteract.lua — Phase-5 peer interaction: when the player presses A facing
-- the ghost NPC, the patch shows a native message box and bumps a counter the client polls.
-- Spawns the ghost one tile in front of the player, faces the player at it, presses A.
-- Load with the PATCHED ROM + overworld savestate.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/peerinteract_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local OE, OST, gStringVar4 = 0x02036E38, 0x24, 0x02021D18
local function p_tx() return memory.read_u16_le(OE + 0x10) end
local function p_ty() return memory.read_u16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function face_right() local v = memory.read_u8(OE + 0x18); memory.write_u8(OE + 0x18, (v & 0xF0) | 4) end

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

-- spawn the ghost one tile EAST of the player; face the player right at it
local px, py = p_tx(), p_ty()
send_wait(MB.OP_SPAWN_PEER_NPC, MB.spawn_npc_args(p_gfx(), 0xF0, px+1, py, 0))
local oeId = MB.read_result_u8(0)
check("ghost spawned", oeId < 16, "oeId="..oeId)
if oeId >= 16 then finish(); return end
face_right()

-- pre-write the interaction message + arm detection for this ghost
MB.write_message("Hi from your partner!")
check("ARM_PEER_INTERACT acked", send_wait(MB.OP_ARM_PEER_INTERACT, {oeId, 1}))

local c0 = MB.peer_interact_count()
log(string.format("player tile=(%d,%d) facing-right, ghost at (%d,%d); pi_count before=%d", px, py, px+1, py, c0))

-- press A (one fresh press) while facing the ghost
joypad.set({}); emu.frameadvance()            -- ensure A is not already held
face_right()
joypad.set({A=true}); emu.frameadvance()       -- A newly pressed this frame
joypad.set({}); for _=1,20 do emu.frameadvance() end

check("peer-interact counter incremented", MB.peer_interact_count() > c0,
      string.format("%d -> %d", c0, MB.peer_interact_count()))
-- the patch showed the native message box (text copied to gStringVar4)
local enc = MB.fr_encode("Hi from your partner!")
local match = true
for i=1,#enc do if memory.read_u8(gStringVar4 + (i-1)) ~= enc[i] then match=false; break end end
check("native interaction message shown", match)
check("game still running (no softlock)", MB.present())

MB.send(MB.OP_ARM_PEER_INTERACT, {oeId, 0})
MB.send(MB.OP_DESPAWN_PEER_NPC, {oeId})
finish()
