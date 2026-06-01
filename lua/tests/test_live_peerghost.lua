-- test_live_peerghost.lua — full lifecycle test of the engine-NPC peer ghost receiver
-- (peer_ghost_npc.lua) on one instance with simulated partner positions: async spawn,
-- position tracking, facing, map-change despawn, clear despawn, and no player-sprite
-- corruption. Load with the PATCHED ROM + overworld savestate.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/peerghost_result.txt"
package.path = WT .. "/lua/?.lua;" .. package.path   -- so peer_ghost_npc can require("mailbox")
local PG = require("peer_ghost_npc")

local OE, GS, OST, GST = 0x02036E38, 0x0202063C, 0x24, 0x44
local function p_spr()    return memory.read_u8(OE + 0x04) end
local function p_tx()     return memory.read_u16_le(OE + 0x10) end
local function p_ty()     return memory.read_u16_le(OE + 0x12) end
local function p_m9()     return memory.read_u8(OE + 0x09) end
local function p_mA()     return memory.read_u8(OE + 0x0A) end
local function spr_x(s)   return memory.read_u16_le(GS + s*GST + 0x20) end
local function spr_anim(s)return memory.read_u8(GS + s*GST + 0x2A) end
local function spr_inuse(s) return memory.read_u8(GS + s*GST + 0x3E) & 1 end
local function pl_attr2() return memory.read_u16_le(GS + p_spr()*GST + 0x04) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end
local function run(n, fn) for _=1,n do PG.on_frame(); emu.frameadvance(); if fn then fn() end end end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE or WT) ; pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
check("patch present", PG.present())
if not PG.present() then finish(); return end

local attr2_0 = pl_attr2()
local m9, mA, px, py = p_m9(), p_mA(), p_tx(), p_ty()
log(string.format("player map=(%d,%d) tile=(%d,%d) sprite#%d attr2=0x%04X", m9, mA, px, py, p_spr(), attr2_0))

-- 1. SPAWN: partner 3 tiles east (world-pixel = tile*16), facing west(3)
PG.on_ghost_pos({mg=m9, mn=mA, x=(px+3)*16, y=py*16, f=3})
run(50)
local d = PG.debug()
check("ghost spawned (object-event id)", d.oeId ~= nil, "oeId="..tostring(d.oeId))
if not d.oeId then finish(); return end
check("ghost sprite in use", spr_inuse(d.sprId) == 1)
local diff = spr_x(d.sprId) - spr_x(p_spr())
check("ghost ~3 tiles east of player (pos1 dx≈48)", math.abs(diff - 48) <= 2, "dx="..diff)
check("facing anim = west (2)", spr_anim(d.sprId) == 2, "anim="..spr_anim(d.sprId))

-- 2. TRACK: partner moves to 1 tile east -> sprite follows
PG.on_ghost_pos({mg=m9, mn=mA, x=(px+1)*16, y=py*16, f=4})
run(50)
diff = spr_x(d.sprId) - spr_x(p_spr())
check("ghost tracked to 1 tile east (pos1 dx≈16)", math.abs(diff - 16) <= 2, "dx="..diff)
check("facing anim updated to east (3)", spr_anim(d.sprId) == 3, "anim="..spr_anim(d.sprId))

-- 3. MAP CHANGE: partner on a different map -> despawn
local freed_sprite = d.sprId
PG.on_ghost_pos({mg=(m9+1)%256, mn=mA, x=(px+1)*16, y=py*16, f=4})
run(10)
check("despawned on map mismatch", PG.debug().oeId == nil and spr_inuse(freed_sprite) == 0)

-- 4. RESPAWN then CLEAR
PG.on_ghost_pos({mg=m9, mn=mA, x=(px+2)*16, y=py*16, f=1})
run(50)
local d2 = PG.debug()
check("respawned after returning to same map", d2.oeId ~= nil)
PG.on_ghost_clear()
run(12)
check("despawned on ghost_clear", PG.debug().oeId == nil and (d2.sprId and spr_inuse(d2.sprId) == 0))

-- 5. NO corruption of the player sprite throughout
check("player sprite still in use", spr_inuse(p_spr()) == 1)
check("player sprite oam.attr2 unchanged", pl_attr2() == attr2_0, string.format("0x%04X->0x%04X", attr2_0, pl_attr2()))
finish()
