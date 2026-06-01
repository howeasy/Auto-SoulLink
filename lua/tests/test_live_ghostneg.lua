-- test_live_ghostneg.lua — regression for the s16 wrap that hid the ghost on-screen. The player
-- sprite's pos1 goes NEGATIVE near a map's origin; reading it unsigned wrapped -40 -> 65496 and
-- threw the ghost's computed screen pos to ~65000 ("off-screen"). Force a negative player pos1 and
-- assert the ghost (sitting right on the player) stays VISIBLE and at a sane position.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostneg_result.txt"
package.path = WT .. "/lua/?.lua;" .. package.path
local PG = require("peer_ghost_npc")
local OE, GS, OST, GST = 0x02036E38, 0x0202063C, 0x24, 0x44
local function p_sid() return memory.read_u8(OE + 0x04) end
local function p_m9() return memory.read_u8(OE + 0x09) end
local function p_mA() return memory.read_u8(OE + 0x0A) end
local function p_tx() return memory.read_s16_le(OE + 0x10) end
local function p_ty() return memory.read_s16_le(OE + 0x12) end
local function spr_x(s) return memory.read_s16_le(GS + s*GST + 0x20) end
local function spr_invis(s) return (memory.read_u8(GS + s*GST + 0x3E) & 0x04) ~= 0 end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
check("patch present", PG.present()); if not PG.present() then finish(); return end

-- spawn the ghost on the player's tile (broadcast a valid avatar so it can show)
local pos = { mg=p_m9(), mn=p_mA(), x=p_tx()*16, y=p_ty()*16, f=1, mv=0, imgs=0x083A3470, anm=0x083A3470 }
PG.on_ghost_pos(pos)
for _=1,40 do PG.on_frame(); emu.frameadvance() end
local d = PG.debug()
check("ghost spawned + visible normally", d.oeId ~= nil and not spr_invis(d.sprId)); if not d.oeId then finish(); return end
local psid = p_sid()

-- Force the PLAYER sprite pos1.x negative (as happens near a map origin) and re-drive THIS frame
-- (no frameadvance, so the engine doesn't restore it before we read). Keep the ghost on the player.
memory.write_u16_le(GS + psid*GST + 0x20, (-40) & 0xFFFF)   -- pos1.x = -40 (s16)
PG.on_ghost_pos({ mg=p_m9(), mn=p_mA(), x=p_tx()*16, y=p_ty()*16, f=1, mv=0, imgs=0x083A3470, anm=0x083A3470 })
PG.on_frame()   -- reads the negative player pos1; with the u16 bug this hides the ghost
local gx = spr_x(d.sprId)
check("ghost still VISIBLE with negative player pos1 (no s16 wrap)", not spr_invis(d.sprId))
check("ghost pos1.x is sane, not a 16-bit-wrapped 65xxx", gx > -512 and gx < 512, "gx="..gx)
PG.on_ghost_clear()
finish()
