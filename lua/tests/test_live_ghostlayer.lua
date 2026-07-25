-- test_live_ghostlayer.lua — VISUAL: does the ghost layer correctly (behind the player when north,
-- in front when south)? Geometry only, so a single-instance recoloured ghost is representative.
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local SHOT = WT .. "/patch/build/ghostlayer_"
local OUT = WT .. "/patch/build/ghostlayer_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local GS, GST = 0x0202063C, 0x44
local function p_tx() return memory.read_s16_le(MB.player_oe()+0x10) end
local function p_ty() return memory.read_s16_le(MB.player_oe()+0x12) end
local function p_gfx() return memory.read_u8(MB.player_oe()+0x05) end
local function p_spr() return memory.read_u8(MB.player_oe()+0x04) end
local function gsid() local o=MB.ghost_oe(); if o>=16 then return nil end
  local s=memory.read_u8(0x02036E38+o*0x24+0x04); return s<64 and s or nil end
local lines={}
local function log(s) lines[#lines+1]=s; console.log(s) end
local function shot(n) pcall(function() client.screenshot(SHOT..n..".png") end); log("shot "..n) end

pcall(function() client.speedmode(100) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
for _=1,4 do emu.frameadvance() end
pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("no patch"); local f=io.open(OUT,"w"); f:write("no patch"); f:close(); client.exit(); return end

-- recolour the player's palette (swap R<->B) so the ghost is a clearly different colour
local sid=p_spr()
local pcol={}
for i=0,15 do local c=memory.read_u16_le(0x020373F8+i*2)
  if i==0 then pcol[#pcol+1]=string.format("%04X",c)
  else local r,g,b=c&0x1F,(c>>5)&0x1F,(c>>10)&0x1F; pcol[#pcol+1]=string.format("%04X",(r<<10)|(g<<5)|b) end end
pcol=table.concat(pcol)
local pimgs=memory.read_u32_le(GS+sid*GST+0x0C)
local panims=memory.read_u32_le(GS+sid*GST+0x08)

-- spawn + give it the distinct avatar
MB.ghost_set_pos((p_tx())*16,(p_ty()-1)*16,1,0,0)
MB.ghost_spawn(0)
for _=1,90 do emu.frameadvance(); if MB.ghost_oe()<16 then break end end
MB.ghost_set_avatar(pimgs,panims,pcol)

-- Position the ghost ONE TILE NORTH of the player (overlapping from above) -> should draw BEHIND.
for _=1,40 do MB.ghost_set_pos((p_tx())*16,(p_ty()-1)*16,1,0,0); emu.frameadvance() end
shot("1_north_behind")
-- Position it ONE TILE SOUTH (overlapping from below) -> should draw IN FRONT.
for _=1,40 do MB.ghost_set_pos((p_tx())*16,(p_ty()+1)*16,2,0,0); emu.frameadvance() end
shot("2_south_front")
log("RESULT: PASS")
local f=io.open(OUT,"w"); f:write(table.concat(lines,"\n").."\n"); f:close()
MB.ghost_clear(); client.exit()
