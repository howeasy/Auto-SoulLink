-- test_live_ghostreceiver.lua — drive the REAL receiver (peer_ghost_npc) the way the client does:
-- require it, feed on_ghost_pos a partner on the SAME map a couple tiles away, call on_frame each
-- frame, and assert it spawns + walks the engine ghost. Isolates the receiver from the network path.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostreceiver_result.txt"
package.path = WT .. "/lua/?.lua;" .. package.path
local PG = require("peer_ghost_npc")
local OE, OST = 0x02036E38, 0x24
local function p_grp() return memory.read_u8(OE + 0x0A) end
local function p_num() return memory.read_u8(OE + 0x09) end
local function p_tx() return memory.read_s16_le(OE + 0x10) end
local function p_ty() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function oe_cx(i) return memory.read_s16_le(OE + i*OST + 0x10) end
local function oe_localid(i) return memory.read_u8(OE + i*OST + 0x08) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
check("receiver reports patch present", PG.present()); if not PG.present() then finish(); return end

-- Partner on the SAME map (mg/mn = local player's map bytes), 2 tiles east, facing west.
local grp, num, px, py = p_grp(), p_num(), p_tx(), p_ty()
log(string.format("local map=(grp%d,num%d) tile=(%d,%d) gfx=%d", grp, num, px, py, p_gfx()))
PG.on_ghost_pos({ mg = grp, mn = num, x = px + 2, y = py, f = 3, mv = 1, run = 0, gfx = p_gfx() })

local oe
for _=1,150 do PG.on_frame(); emu.frameadvance(); oe = PG.debug().oeId; if oe and oe < 16 then break end end
check("receiver spawned the ghost", oe and oe < 16, "oeId=" .. tostring(oe))
if not (oe and oe < 16) then finish(); return end
check("spawned slot is ours (localId 0xF0)", oe_localid(oe) == 0xF0)

-- keep posting the same target; the patch should walk the ghost to (px+2, py)
for _=1,150 do PG.on_frame(); emu.frameadvance()
  PG.on_ghost_pos({ mg = grp, mn = num, x = px + 2, y = py, f = 3, mv = 0, run = 0, gfx = p_gfx() }) end
check("ghost reached the partner tile", math.abs(oe_cx(oe) - (px+2)) <= 1, "gx=" .. oe_cx(oe) .. " want " .. (px+2))

-- partner leaves to a different map -> receiver clears it
PG.on_ghost_pos({ mg = (grp+1) % 256, mn = num, x = px, y = py, f = 1, mv = 0, run = 0, gfx = p_gfx() })
for _=1,8 do PG.on_frame(); emu.frameadvance() end
local gone = true
for i=0,15 do if (memory.read_u8(OE+i*OST) & 1)==1 and oe_localid(i)==0xF0 then gone=false end end
check("receiver cleared the ghost on partner map change", gone)
finish()
