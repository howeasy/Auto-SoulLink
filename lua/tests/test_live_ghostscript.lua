-- test_live_ghostscript.lua — reproduce "invisible collision after dialogue/scripted events".
-- A sign dialogue does lockall -> FreezeObjectEvents (freezes every active OE, incl. our ghost) and
-- releaseall -> UnfreezeObjectEvents on dismiss. We spawn the ghost on-screen (solid), move the
-- partner, raise a real sign box, move the partner DURING the freeze, dismiss it, then assert: still
-- exactly ONE ghost OE, and its collision tile == its drawn tile, its elevation matches the player
-- (no stale/leftover solid tile).
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/ghostscript_result.txt"
package.path = WT .. "/lua/?.lua;" .. package.path
local PG = require("peer_ghost_npc")
local MB = dofile(WT .. "/lua/mailbox.lua")
local OE, OST, GS, GST = 0x02036E38, 0x24, 0x0202063C, 0x44
local SCTX = 0x03000F9C
local function pmg() return memory.read_u8(MB.player_oe()+0x0A) end
local function pmn() return memory.read_u8(MB.player_oe()+0x09) end
local function ptx() return memory.read_s16_le(MB.player_oe()+0x10) end
local function pty() return memory.read_s16_le(MB.player_oe()+0x12) end
local function gsid() local o=MB.ghost_oe(); if o>=16 then return nil,o end
  local s=memory.read_u8(OE+o*OST+0x04); return (s<64) and s or nil, o end
local function gtile() local _,o=gsid(); if o>=16 then return nil end
  return memory.read_s16_le(OE+o*OST+0x10), memory.read_s16_le(OE+o*OST+0x12), memory.read_u8(OE+o*OST+0x0B) end
local function gdrawtile() local s=gsid(); if not s then return nil end
  local cx=memory.read_s16_le(0x0203F850+36); local cy=memory.read_s16_le(0x0203F850+38)
  -- ghost world-px = pos1 - C ; drawn tile = round(worldpx/16)
  local wx=memory.read_s16_le(GS+s*GST+0x20)-cx; local wy=memory.read_s16_le(GS+s*GST+0x22)-cy
  return (wx+8)>>4, (wy+8)>>4 end
local function count_ghosts() local n=0; for i=0,15 do local b=OE+i*OST
  if (memory.read_u8(b)&1)==1 and memory.read_u8(b+0x08)==0xF0 then n=n+1 end end; return n end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(200) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
check("patch present", PG.present()); if not PG.present() then finish(); return end

local grp, num = pmg(), pmn()
local bx, by = ptx(), pty()
local wxp, wyp = 2, 0
local function feed() PG.on_ghost_pos({ mg=grp, mn=num, x=(bx+wxp)*16, y=(by+wyp)*16, f=4, mv=1, an=6, run=0,
  gfx=memory.read_u8(MB.player_oe()+0x05), imgs=0x08EB3A78, anim=0x083A3470, pcol=("0421"):rep(16) }) end
feed()
for _=1,150 do PG.on_frame(); emu.frameadvance(); if MB.ghost_oe()<16 then break end end
for _=1,40 do feed(); PG.on_frame(); emu.frameadvance() end  -- settle on-screen
check("ghost spawned + on screen", count_ghosts()==1, "n="..count_ghosts())
local gx0,gy0,ge0 = gtile(); log(string.format("before script: ghost tile=(%d,%d) elev=0x%02X  n=%d", gx0,gy0,ge0,count_ghosts()))

-- raise a real lockall sign box (freezes object events)
MB.write_message("Hello there partner")
MB.send(8, {})  -- OP_SHOW_MESSAGE -> run_sign_msgbox (lockall/.../releaseall)
for _=1,20 do PG.on_frame(); emu.frameadvance() end
log(string.format("during script: sScriptCtx2=%d  ghost tile=(%s,%s)  n=%d",
    memory.read_u8(SCTX), tostring(({gtile()})[1]), tostring(({gtile()})[2]), count_ghosts()))
-- move the partner WHILE frozen, then dismiss with A
wxp = 4
for k=1,40 do if k%3==0 then feed() end; PG.on_frame(); emu.frameadvance() end
joypad.set({A=true}); emu.frameadvance(); joypad.set({})
for _=1,40 do feed(); PG.on_frame(); emu.frameadvance() end   -- script ends, partner still moving

local n2 = count_ghosts()
local gx,gy,ge = gtile()
local dx,dy = gdrawtile()
log(string.format("after script: sScriptCtx2=%d  ghost collisionTile=(%s,%s) elev=0x%02X  drawnTile=(%s,%s)  n=%d",
    memory.read_u8(SCTX), tostring(gx),tostring(gy),ge or 0, tostring(dx),tostring(dy), n2))
check("exactly one ghost OE after the dialogue", n2==1, "n="..n2)
check("ghost collision tile == its drawn tile (no stale leftover)", gx==dx and gy==dy,
      string.format("collision=(%s,%s) drawn=(%s,%s)", tostring(gx),tostring(gy),tostring(dx),tostring(dy)))
finish()
