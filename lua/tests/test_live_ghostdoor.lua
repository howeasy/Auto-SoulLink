-- test_live_ghostdoor.lua — reproduce the "ghost reverts to MY sprite after a door" bug headlessly.
-- Drive the REAL receiver (so the end-of-frame avatar re-assert runs), spawn the ghost as the OTHER
-- character, then walk the player THROUGH the door (scripted input) and verify the ghost is STILL the
-- other character after the warp (sprite->images + the displayed VRAM tiles), not the local stand-in.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT  = WT .. "/patch/build/ghostdoor_result.txt"
local SHOT = WT .. "/patch/build/ghostdoor_"
package.path = WT .. "/lua/?.lua;" .. package.path
local PG = require("peer_ghost_npc")
local OE, GS, GST = 0x02036E38, 0x0202063C, 0x44
local OVRAM = 0x06010000
local OTHER_IMGS, OTHER_DATA = 0x08EB3A78, 0x08EBF02C   -- the non-savestate character + frame0 data
local RED_DATA = 0x08EB8810
local function poe() return MB and 0 end
local MB = dofile(WT .. "/lua/mailbox.lua")
local function p_mg() return memory.read_u8(MB.player_oe() + 0x0A) end
local function p_mn() return memory.read_u8(MB.player_oe() + 0x09) end
local function p_tx() return memory.read_s16_le(MB.player_oe() + 0x10) end
local function p_ty() return memory.read_s16_le(MB.player_oe() + 0x12) end
local function p_face() return memory.read_u8(MB.player_oe() + 0x18) & 0x0F end
local function p_gfx() return memory.read_u8(MB.player_oe() + 0x05) end
local function ghost_sid() local o=MB.ghost_oe(); if o>=16 then return nil end
  local s=memory.read_u8(OE+o*0x24+0x04); return (s<64) and s or nil end
local function ghost_imgs() local s=ghost_sid(); return s and memory.read_u32_le(GS+s*GST+0x0C) or 0 end
local function ghost_tilenum() local s=ghost_sid(); return s and (memory.read_u16_le(GS+s*GST+0x04)&0x3FF) or 0 end
local function rd(a,n) local t={}; for i=0,n-1 do t[#t+1]=string.format("%02X",memory.read_u8(a+i)) end; return table.concat(t) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end
local function shot(n) pcall(function() client.screenshot(SHOT..n..".png") end) end
local FACEKEY = {[1]="Down",[2]="Up",[3]="Left",[4]="Right"}

pcall(function() client.speedmode(100) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_door.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
check("patch present", PG.present()); if not PG.present() then finish(); return end

-- partner = the OTHER character, always reported on the player's CURRENT map (so it persists across
-- the warp) a couple tiles away. Feed every 3rd frame at 20 Hz, like the real client.
-- use a REAL palette (the local player's actual slot-0 colours) so the render is representative,
-- not the garbage of a synthetic palette. The ghost shows the OTHER shape with these colours.
local function real_pcol()
  local lsid = memory.read_u8(MB.player_oe() + 0x04)
  local slot = (lsid<64) and ((memory.read_u16_le(GS + lsid*GST + 0x04) >> 12) & 0x0F) or 0
  local t = {}
  for i=0,15 do t[#t+1] = string.format("%04X", memory.read_u16_le(0x020373F8 + slot*0x20 + i*2)) end
  return table.concat(t)
end
local function feed()
  PG.on_ghost_pos({ mg=p_mg(), mn=p_mn(), x=(p_tx()+1)*16, y=p_ty()*16, f=1, mv=0, an=0, run=0,
                    gfx=p_gfx(), imgs=OTHER_IMGS, anim=0x083A3470, pcol=real_pcol() })
end
local mg0, mn0, face = p_mg(), p_mn(), p_face()
log(string.format("door state: map(%d,%d) tile(%d,%d) facing=%d gfx=%d", mg0, mn0, p_tx(), p_ty(), face, p_gfx()))
feed()
for k=1,150 do if k%3==0 then feed() end; PG.on_frame(); emu.frameadvance(); if MB.ghost_oe()<16 then break end end
check("ghost spawned before the door", MB.ghost_oe()<16)
for k=1,30 do if k%3==0 then feed() end; PG.on_frame(); emu.frameadvance() end  -- let the re-assert apply
log(string.format("BEFORE door: ghost images=0x%08X (want 0x%08X)", ghost_imgs(), OTHER_IMGS))
check("ghost shows the OTHER character BEFORE the door", ghost_imgs()==OTHER_IMGS)
shot("1_before")

-- walk THROUGH the door: hold the facing direction until the map changes, feeding the partner on the
-- new map each frame so the ghost persists.
local key = FACEKEY[face] or "Up"
local warped, fc = false, 0
for k=1,240 do
  joypad.set({ [key]=true })
  if k%3==0 then feed() end
  PG.on_frame(); emu.frameadvance(); fc=fc+1
  if (p_mg()~=mg0 or p_mn()~=mn0) and not warped then warped=true; log(string.format("WARPED to map(%d,%d) at frame %d",p_mg(),p_mn(),fc)) end
end
joypad.set({})
-- settle on the new map
for k=1,120 do if k%3==0 then feed() end; PG.on_frame(); emu.frameadvance() end

check("player actually warped through the door", warped, "still map("..p_mg()..","..p_mn()..")")
local gi = ghost_imgs()
log(string.format("AFTER door: map(%d,%d) ghost images=0x%08X (want 0x%08X)", p_mg(), p_mn(), gi, OTHER_IMGS))
local sid = ghost_sid()
if sid then
  local v = rd(OVRAM + ghost_tilenum()*32 + 0xC0, 16)
  log("AFTER door VRAM[0xC0]="..v)
  log("  OTHER frame0="..rd(OTHER_DATA+0xC0,16))
  log("  RED   frame0="..rd(RED_DATA+0xC0,16))
end
shot("2_after")
check("ghost STILL shows the OTHER character after the door (not my stand-in)", gi==OTHER_IMGS,
      string.format("0x%08X", gi))
finish()
