-- test_live_ghostdrive.lua — the engine-driven peer ghost. The PATCH (drive_ghost) spawns a real
-- object-event and WALKS it toward the target tile Lua posts into GhostState, using the engine's
-- native held-movement API. We post a target, advance frames, and assert the ghost's object-event
-- currentCoords advance toward it on their own (Lua writes NOTHING to the sprite/OE), with no
-- player-sprite corruption. Load with the PATCHED ROM + overworld savestate.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostdrive_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local OE, OST, GS, GST = 0x02036E38, 0x24, 0x0202063C, 0x44
local function p_sx() return memory.read_s16_le(OE + 0x10) end
local function p_sy() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function p_spr() return memory.read_u8(OE + 0x04) end
local function oe_cx(i) return memory.read_s16_le(OE + i*OST + 0x10) end
local function oe_cy(i) return memory.read_s16_le(OE + i*OST + 0x12) end
local function oe_localid(i) return memory.read_u8(OE + i*OST + 0x08) end
local function spr_attr2(s) return memory.read_u16_le(GS + s*GST + 0x04) end
local function spr_palnum(s) return (memory.read_u16_le(GS + s*GST + 0x04) >> 12) & 0x0F end

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
local player_attr2 = spr_attr2(p_spr())
log(string.format("player tile=(%d,%d) gfx=%d sprite#%d attr2=0x%04X", px, py, pgfx, p_spr(), player_attr2))

-- Post a target 3 tiles east, then request the engine-driven ghost. The patch spawns + walks it.
MB.ghost_set_target(px + 3, py, 4, 0, pgfx)
MB.ghost_spawn(pgfx)
local oe
for _=1,120 do emu.frameadvance(); oe = MB.ghost_oe(); if oe < 16 then break end end
check("ghost spawned (engine object-event)", oe < 16, "GH.oeId=" .. oe)
if oe >= 16 then finish(); return end
check("spawned slot is ours (localId 0xF0)", oe_localid(oe) == 0xF0, string.format("0x%02X", oe_localid(oe)))
log(string.format("ghost oe=%d at (%d,%d), ghost palNum=%d player palNum=%d",
    oe, oe_cx(oe), oe_cy(oe), spr_palnum(memory.read_u8(OE+oe*OST+0x04)), spr_palnum(p_spr())))

-- Let the patch walk it toward the target. currentCoords must advance EAST on their own.
local gx0 = oe_cx(oe)
for _=1,180 do emu.frameadvance() end
local gx1, gy1 = oe_cx(oe), oe_cy(oe)
check("ghost walked toward target (engine-driven, Lua wrote nothing)", gx1 > gx0, string.format("%d -> %d (target %d)", gx0, gx1, px+3))
check("ghost reached target x", math.abs(gx1 - (px+3)) <= 1, "gx="..gx1.." want "..(px+3))

-- Move the target back west; the ghost should turn around and follow.
MB.ghost_set_target(px, py, 3, 0, pgfx)
for _=1,200 do emu.frameadvance() end
check("ghost followed target back west", oe_cx(oe) < gx1, "now "..oe_cx(oe))

-- No corruption of the player sprite throughout.
check("player sprite oam.attr2 unchanged", spr_attr2(p_spr()) == player_attr2,
      string.format("0x%04X -> 0x%04X", player_attr2, spr_attr2(p_spr())))

MB.ghost_clear()
finish()
