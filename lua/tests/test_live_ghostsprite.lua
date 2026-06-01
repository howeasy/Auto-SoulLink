-- test_live_ghostsprite.lua — verify the engine-NPC ghost adopts the PARTNER's broadcast
-- sprite images/anims ROM pointers (so it shows their avatar, not gfx 0 = the local player).
-- Feeds on_ghost_pos a distinct (valid) images/anims pair and checks the ghost sprite took them.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostsprite_result.txt"
package.path = WT .. "/lua/?.lua;" .. package.path
local PG = require("peer_ghost_npc")
local OE, GS, OST, GST = 0x02036E38, 0x0202063C, 0x24, 0x44
local function p_m9() return memory.read_u8(OE + 0x09) end
local function p_mA() return memory.read_u8(OE + 0x0A) end
local function p_tx() return memory.read_u16_le(OE + 0x10) end
local function p_ty() return memory.read_u16_le(OE + 0x12) end
local function spr_imgs(s) return memory.read_u32_le(GS + s*GST + 0x0C) end
local function spr_anms(s) return memory.read_u32_le(GS + s*GST + 0x08) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end
local function run(n) for _=1,n do PG.on_frame(); emu.frameadvance() end end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
check("patch present", PG.present()); if not PG.present() then finish(); return end

local m9, mA, px, py = p_m9(), p_mA(), p_tx(), p_ty()
-- A distinct but valid OW sprite-template images/anims pair (Prof. Oak gfx pointers differ from
-- the player's). We don't care WHICH sprite — only that the ghost adopts the broadcast pointers.
local TEST_IMGS, TEST_ANMS = 0x083A3470, 0x083A3470   -- valid ROM addrs (player anim table; in-ROM)
PG.on_ghost_pos({ mg=m9, mn=mA, x=(px+2)*16, y=py*16, f=1, mv=0, imgs=TEST_IMGS, anm=TEST_ANMS })
run(40)
local d = PG.debug()
check("ghost spawned", d.oeId ~= nil, "oeId="..tostring(d.oeId)); if not d.oeId then finish(); return end
check("ghost adopted broadcast images", spr_imgs(d.sprId) == TEST_IMGS,
      string.format("%08X (want %08X)", spr_imgs(d.sprId), TEST_IMGS))
check("ghost adopted broadcast anims", spr_anms(d.sprId) == TEST_ANMS,
      string.format("%08X (want %08X)", spr_anms(d.sprId), TEST_ANMS))

local function invis(s) return (memory.read_u8(GS + s*GST + 0x3E) & 0x04) ~= 0 end
-- On-screen (2 tiles east): visible.
check("on-screen ghost visible (invisible bit clear)", not invis(d.sprId))
-- Far off-screen (30 tiles east): culled (invisible) so its OAM coord can't wrap to garbage.
PG.on_ghost_pos({ mg=m9, mn=mA, x=(px+30)*16, y=py*16, f=4, mv=0, imgs=TEST_IMGS, anm=TEST_ANMS })
run(10)
check("off-screen ghost culled (invisible bit set)", invis(d.sprId))
-- Back on-screen: visible again.
PG.on_ghost_pos({ mg=m9, mn=mA, x=(px+2)*16, y=py*16, f=4, mv=0, imgs=TEST_IMGS, anm=TEST_ANMS })
run(10)
check("on-screen again -> visible", not invis(d.sprId))
PG.on_ghost_clear()
finish()
