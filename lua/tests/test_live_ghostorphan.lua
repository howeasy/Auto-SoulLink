-- test_live_ghostorphan.lua — hunt the "extra invisible collision left behind after connect".
-- Drive the real receiver through a connect, move the partner, then scan ALL object-events for our
-- ghost sentinel (localId 0xF0). There must be EXACTLY ONE (the live ghost) — any extra = an orphan
-- OE left behind (a permanent invisible wall). Also exercise a re-init (reconnect) + clear/respawn.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostorphan_result.txt"
package.path = WT .. "/lua/?.lua;" .. package.path
local PG = require("peer_ghost_npc")
local OE, OST = 0x02036E38, 0x24
local function p_grp() return memory.read_u8(MB_PO() + 0x0A) end
local MB = dofile(WT .. "/lua/mailbox.lua")
function MB_PO() return MB.player_oe() end
local function pmg() return memory.read_u8(MB.player_oe()+0x0A) end
local function pmn() return memory.read_u8(MB.player_oe()+0x09) end
local function ptx() return memory.read_s16_le(MB.player_oe()+0x10) end
local function pty() return memory.read_s16_le(MB.player_oe()+0x12) end
local function pgfx() return memory.read_u8(MB.player_oe()+0x05) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

-- scan for all active OEs with our sentinel localId 0xF0; report count + (tile, elevation) of each
local function scan_ghosts()
  local out, n = {}, 0
  for i=0,15 do
    local b = OE + i*OST
    if (memory.read_u8(b) & 1) == 1 and memory.read_u8(b+0x08) == 0xF0 then
      n = n + 1
      out[#out+1] = string.format("slot%d@(%d,%d)elev0x%02X", i,
        memory.read_s16_le(b+0x10), memory.read_s16_le(b+0x12), memory.read_u8(b+0x0B))
    end
  end
  return n, table.concat(out, " ")
end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
check("patch present", PG.present()); if not PG.present() then finish(); return end

local grp, num, gfx = pmg(), pmn(), pgfx()
local bx, by = ptx(), pty()
local function feed(dx, dy) PG.on_ghost_pos({ mg=grp, mn=num, x=(bx+dx)*16, y=(by+dy)*16, f=4, mv=1, an=6, run=0, gfx=gfx,
                                              imgs=0x08EB3A78, anim=0x083A3470, pcol=("0421"):rep(16) }) end

-- CONNECT: partner appears a few tiles east, ghost spawns + tracks.
feed(3, 0)
for _=1,150 do PG.on_frame(); emu.frameadvance(); if PG.debug().oeId and PG.debug().oeId<16 then break end end
local n0,d0 = scan_ghosts(); log("after connect+spawn: "..n0.." ghost OE(s)  "..d0)
check("exactly one ghost OE after connect", n0 == 1, d0)

-- partner walks around for a while (the ghost should track, no leftovers)
for k=1,120 do feed(3 - (k//20)%4, (k//40)%3); PG.on_frame(); emu.frameadvance() end
local n1,d1 = scan_ghosts(); log("after partner walked: "..n1.." ghost OE(s)  "..d1)
check("still exactly one ghost OE after movement", n1 == 1, d1)

-- RECONNECT path: re-init the receiver (as a client reload/reconnect would) while the patch ghost
-- still exists, then connect again. A leftover here = the orphan the user sees.
PG.init()
feed(3, 0)
for k=1,150 do PG.on_frame(); emu.frameadvance(); if PG.debug().oeId and PG.debug().oeId<16 then break end end
for k=1,60 do feed(3,0); PG.on_frame(); emu.frameadvance() end
local n2,d2 = scan_ghosts(); log("after re-init + reconnect: "..n2.." ghost OE(s)  "..d2)
check("exactly one ghost OE after a reconnect (no orphan)", n2 == 1, d2)

local function ghs() return memory.read_u8(0x0203F850), memory.read_u8(0x0203F851) end
-- dump the live ghost OE + GhostState BEFORE clearing, to see why ghost_remove's guard may skip
do local b = OE + 4*OST
   log(string.format("PRE-CLEAR slot4: flags=0x%02X localId=0x%02X | GH.oeId=%d GH.localId=0x%02X",
       memory.read_u8(b), memory.read_u8(b+0x08), memory.read_u8(0x0203F851), memory.read_u8(0x0203F854))) end
PG.on_ghost_clear()
for _=1,8 do PG.on_frame(); emu.frameadvance() end
local a1,o1 = ghs(); log(string.format("after PG.on_ghost_clear: GH.active=%d GH.oeId=%d", a1, o1))
local n3,d3 = scan_ghosts(); log("after clear: "..n3.." ghost OE(s)  "..d3)
-- direct patch clear, to isolate Lua vs patch
MB.ghost_clear()
for _=1,8 do emu.frameadvance() end
local a2,o2 = ghs(); log(string.format("after direct MB.ghost_clear: GH.active=%d GH.oeId=%d", a2, o2))
local n4,d4 = scan_ghosts(); log("after direct clear: "..n4.." ghost OE(s)  "..d4)
-- battle-check sanity on the overworld save (stale gBattleMons would suspend drive_ghost forever)
log(string.format("gBattleMons[0].maxHP=%d gBattleOutcome=%d",
    memory.read_u16_le(0x02023BE4 + 0x2C), memory.read_u8(0x02023E8A)))
check("no ghost OE after clear", n4 == 0, d4)
finish()
