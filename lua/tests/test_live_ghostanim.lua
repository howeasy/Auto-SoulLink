-- test_live_ghostanim.lua — does the engine ANIMATE the ghost's held-movement walk? Spawn, walk it
-- a few tiles, and sample the ghost sprite's animNum (0x2A) + displayed tile (OAM attr2 low bits)
-- every frame. A real walk => animNum in the GO range (4-7) AND the tile cycles between frames.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostanim_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local OST, GST = 0x24, 0x44
local function poe() return MB.player_oe() end
local function p_sx() return memory.read_s16_le(poe() + 0x10) end
local function p_sy() return memory.read_s16_le(poe() + 0x12) end
local function p_gfx() return memory.read_u8(poe() + 0x05) end
local function oe_spr(i) return memory.read_u8(0x02036E38 + i*OST + 0x04) end
local function oe_cx(i) return memory.read_s16_le(0x02036E38 + i*OST + 0x10) end
local function spr_anim(s) return memory.read_u8(0x0202063C + s*GST + 0x2A) end
local function spr_tile(s) return memory.read_u16_le(0x0202063C + s*GST + 0x04) & 0x03FF end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
check("patch present", MB.present()); if not MB.present() then finish(); return end

local px, py, pgfx = p_sx(), p_sy(), p_gfx()
MB.ghost_set_target(px + 4, py, 4, 0, pgfx)
MB.ghost_spawn(pgfx)
local oe = 16
for _=1,120 do emu.frameadvance(); oe = MB.ghost_oe(); if oe < 16 then break end end
check("ghost spawned", oe < 16, "oe=" .. oe); if oe >= 16 then finish(); return end
local sid = oe_spr(oe)
log("ghost oe=" .. oe .. " sprite=" .. sid .. " gfx=" .. pgfx)

-- OW sprites keep a FIXED tile and DMA the current frame's IMAGE into it. So check whether the VRAM
-- image at the ghost's tile actually changes while walking (= animation playing), plus the animNum.
local function spr_animcmd(s) return memory.read_u8(0x0202063C + s*GST + 0x2B) end
local function spr_animpaused(s) return (memory.read_u8(0x0202063C + s*GST + 0x2C) & 0x40) ~= 0 end
local tilenum = spr_tile(sid)
local vram = 0x06010000 + tilenum * 0x20   -- OBJ VRAM for this 16x32 sprite (8 tiles)
-- signature over the WHOLE sprite (8 tiles = 256 bytes); the top tile is transparent so the legs
-- live in the lower tiles. Sample a few words spread across the 8 tiles.
local function sprite_sig()
  return string.format("%08X%08X%08X%08X%08X",
    memory.read_u32_le(vram + 4*0x20 + 16), memory.read_u32_le(vram + 5*0x20 + 8),
    memory.read_u32_le(vram + 6*0x20 + 16), memory.read_u32_le(vram + 7*0x20 + 8),
    memory.read_u32_le(vram + 5*0x20 + 16))
end
local anims, sigs, cmds, moved, paused_seen = {}, {}, {}, false, false
local last_cx = oe_cx(oe)
for step = 1, 60 do
  MB.ghost_set_target(px + 4, py, 4, 0, pgfx)
  emu.frameadvance()
  anims[spr_anim(sid)] = true
  cmds[spr_animcmd(sid)] = true
  if spr_animpaused(sid) then paused_seen = true end
  sigs[sprite_sig()] = true
  if oe_cx(oe) ~= last_cx then moved = true; last_cx = oe_cx(oe) end
end
local cmd_list = {}; for c,_ in pairs(cmds) do cmd_list[#cmd_list+1] = c end; table.sort(cmd_list)
log("animCmdIndex values seen: " .. table.concat(cmd_list, ",") .. "  animPaused-ever=" .. tostring(paused_seen))
local anim_list = {}; for a,_ in pairs(anims) do anim_list[#anim_list+1] = a end; table.sort(anim_list)
local nsig = 0; for _ in pairs(sigs) do nsig = nsig + 1 end
log("animNums seen while walking: " .. table.concat(anim_list, ","))
log("ghost tile=" .. tilenum .. " vram=0x" .. string.format("%08X", vram) .. " distinct frame images: " .. nsig)

check("position actually moved (held movement, not stuck)", moved)
local walk = false
for _,a in ipairs(anim_list) do if a >= 4 and a <= 11 then walk = true end end
check("a walk/run animNum was used", walk)
check("the frame IMAGE in VRAM cycled (animation playing)", nsig >= 2, "#images=" .. nsig)
MB.ghost_clear()
finish()
