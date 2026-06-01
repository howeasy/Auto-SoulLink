-- test_live_ghostowner.lua — the slot-ownership guard (Oak's-lab corruption fix). If the engine
-- reassigns our object-event slot to a real NPC (warp/cull), the receiver must DROP it, NOT keep
-- driving it (which would write the partner's sprite onto that NPC). Simulate reassignment by
-- changing the ghost OE's localId out from under us and verify the receiver lets go without
-- clobbering the slot's sprite pointers.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostowner_result.txt"
package.path = WT .. "/lua/?.lua;" .. package.path
local PG = require("peer_ghost_npc")
local OE, GS, OST, GST = 0x02036E38, 0x0202063C, 0x24, 0x44
local function p_m9() return memory.read_u8(OE + 0x09) end
local function p_mA() return memory.read_u8(OE + 0x0A) end
local function p_tx() return memory.read_u16_le(OE + 0x10) end
local function p_ty() return memory.read_u16_le(OE + 0x12) end
local function oe_localid(i) return memory.read_u8(OE + i*OST + 0x08) end
local function spr_imgs(s) return memory.read_u32_le(GS + s*GST + 0x0C) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end
local function run(n,t) for _=1,n do PG.on_frame(); emu.frameadvance(); if t then PG.on_ghost_pos(t) end end end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
check("patch present", PG.present()); if not PG.present() then finish(); return end

local m9, mA, px, py = p_m9(), p_mA(), p_tx(), p_ty()
local TEST_IMGS = 0x083A3470
local pos = { mg=m9, mn=mA, x=(px+2)*16, y=py*16, f=1, mv=0, imgs=TEST_IMGS, anm=TEST_IMGS }
PG.on_ghost_pos(pos)
run(40, pos)
local d = PG.debug()
check("ghost spawned + owns slot (localId 0xF0)", d.oeId ~= nil and oe_localid(d.oeId) == 0xF0,
      "oeId="..tostring(d.oeId).." localId="..(d.oeId and string.format("0x%02X",oe_localid(d.oeId)) or "?"))
if not d.oeId then finish(); return end

-- Simulate the engine handing our slot to a different NPC: change its localId + a sentinel images.
local victim_oe, victim_spr = d.oeId, d.sprId
local NPC_IMGS = 0x08000000
memory.write_u8(OE + victim_oe*OST + 0x08, 0x05)            -- not our LOCALID (0xF0)
memory.write_u32_le(GS + victim_spr*GST + 0x0C, NPC_IMGS)  -- pretend it's a real NPC's sprite
PG.on_frame(); emu.frameadvance()                          -- one frame: receiver should let go

check("receiver dropped the reassigned slot", PG.debug().oeId ~= victim_oe or PG.debug().oeId == nil)
check("did NOT overwrite the reassigned NPC's sprite", spr_imgs(victim_spr) == NPC_IMGS,
      string.format("%08X (should stay %08X)", spr_imgs(victim_spr), NPC_IMGS))
PG.on_ghost_clear()
finish()
