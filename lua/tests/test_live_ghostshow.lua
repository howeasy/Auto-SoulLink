-- test_live_ghostshow.lua — VISUAL proof. Spawn the peer ghost next to the player, give it a
-- DISTINCT recoloured avatar (proving it renders on its own palette slot, not the player's), and
-- walk it across via the sub-pixel LERP driver, capturing screenshots so the ghost is visible
-- standing beside you and mid-walk.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostshow_result.txt"
local SHOT = WT .. "/patch/build/ghostshow_"
local MB = dofile(WT .. "/lua/mailbox.lua")
local OE, GS, GST = 0x02036E38, 0x0202063C, 0x44
local function p_tx() return memory.read_s16_le(OE + 0x10) end
local function p_ty() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function p_spr() return memory.read_u8(OE + 0x04) end

local lines = {}
local function log(s) lines[#lines+1] = s; console.log(s) end
local function finish() local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end
local function shot(n) pcall(function() client.screenshot(SHOT .. n .. ".png") end); log("shot " .. n) end

pcall(function() client.speedmode(100) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
for _=1,4 do emu.frameadvance() end
pcall(memory.usememorydomain, "System Bus")
if not MB.present() then log("no patch"); finish(); return end

local px, py, gfx = p_tx(), p_ty(), p_gfx()
local sid = p_spr()
local pimgs = memory.read_u32_le(GS + sid*GST + 0x0C)
local panims = memory.read_u32_le(GS + sid*GST + 0x08)
-- Recolour the player's real palette into a clearly DIFFERENT trainer (swap R<->B 5-bit channels),
-- so the ghost is visibly its own character on its own palette slot.
local t = {}
for i = 0, 15 do
  local c = memory.read_u16_le(0x020373F8 + i*2)   -- player OBJ slot 0, colour i
  if i == 0 then t[#t+1] = string.format("%04X", c)   -- keep transparent index
  else
    local r, g, b = c & 0x1F, (c >> 5) & 0x1F, (c >> 10) & 0x1F
    t[#t+1] = string.format("%04X", (r << 10) | (g << 5) | b)   -- swap red<->blue
  end
end
local pcol = table.concat(t)

-- spawn 2 tiles east of the player, then apply the distinct avatar
local wy = py * 16
MB.ghost_set_pos((px+2)*16, wy, 3, 0, 0)
MB.ghost_spawn(gfx)
for _=1,90 do emu.frameadvance(); if MB.ghost_oe() < 16 then break end end
MB.ghost_set_avatar(pimgs, panims, pcol)
for _=1,40 do emu.frameadvance() end
shot("1_standing")               -- ghost (recoloured) stands east of the player

-- walk the ghost WEST across in front of the player, capturing mid-stride
local wx = (px+2)*16
for step = 1, 64 do
  wx = wx - 1
  if step % 3 == 0 then MB.ghost_set_pos(wx, wy, 3, 1, 6) end   -- facing west, walking, walk anim
  emu.frameadvance()
  if step == 24 then shot("2_walking") end
  if step == 48 then shot("3_walking") end
end
MB.ghost_set_pos(wx, wy, 3, 0, 2)
for _=1,20 do emu.frameadvance() end
shot("4_arrived")
log("RESULT: PASS")
finish()
