-- test_live_ghostmove.lua — Phase-3 capstone: spawn a real engine NPC, then DRIVE its
-- sprite position from Lua over many frames (the peer-ghost tracking model) and confirm it
-- moves cleanly WITHOUT corrupting the player's sprite — the exact failure of the old
-- hand-cloned ghost. Load with the PATCHED ROM + overworld savestate.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostmove_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_overworld.State"
local MB = dofile(WT .. "/lua/mailbox.lua")

local OE, OST = 0x02036E38, 0x24
local GS, GST = 0x0202063C, 0x44
local function oe_gfx(i)  return memory.read_u8(OE + i*OST + 0x05) end
local function oe_x(i)    return memory.read_u16_le(OE + i*OST + 0x10) end
local function oe_y(i)    return memory.read_u16_le(OE + i*OST + 0x12) end
local function oe_spr(i)  return memory.read_u8(OE + i*OST + 0x04) end
local function spr_attr2(s) return memory.read_u16_le(GS + s*GST + 0x04) end  -- tileNum+palette
local function spr_inuse(s) return memory.read_u8(GS + s*GST + 0x3E) & 1 end
local function spr_posx(s)  return memory.read_u16_le(GS + s*GST + 0x20) end
local function set_posx(s,v) memory.write_u16_le(GS + s*GST + 0x20, v & 0xFFFF) end
local function set_anim(s,n) memory.write_u8(GS + s*GST + 0x2A, n) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE); emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end

-- record the PLAYER's sprite identity (slot 0) up front — must be untouched by the ghost
local p_spr = oe_spr(0)
local p_attr2_before = spr_attr2(p_spr)
log(string.format("player sprite #%d oam.attr2=0x%04X (tileNum+palette)", p_spr, p_attr2_before))

-- spawn the ghost (use the player's gfx so it shares a palette slot — the worst case for the
-- old clone, which corrupted the shared player palette)
local st = MB.send(MB.OP_SPAWN_PEER_NPC, MB.spawn_npc_args(oe_gfx(0), 0xF0, oe_x(0)+1, oe_y(0), 0))
for _=1,30 do emu.frameadvance(); if MB.poll(st) then break end end
local oeId = MB.read_result_u8(0)
if oeId >= 16 then log("FAIL: spawn failed"); finish(); return end
local g_spr = oe_spr(oeId)
log(string.format("ghost oe=%d sprite=#%d", oeId, g_spr))

-- DRIVE the ghost sprite's position over 90 frames (slide it east) + cycle facing anims
local base = spr_posx(g_spr)
local moved = false
for f = 1, 90 do
    set_posx(g_spr, base + (f // 2))       -- slide horizontally
    set_anim(g_spr, (f // 8) % 4)          -- cycle idle-facing anims
    emu.frameadvance()
    if spr_posx(g_spr) ~= base then moved = true end
end
log(string.format("after 90 frames driving: ghost sprite #%d inUse=%d posx=%d (base %d)",
    g_spr, spr_inuse(g_spr), spr_posx(g_spr), base))

check("ghost sprite still in use after driving", spr_inuse(g_spr) == 1)
check("ghost sprite position was driven (moved)", moved)
check("PLAYER sprite still in use (not freed)", spr_inuse(p_spr) == 1)
check("PLAYER sprite oam.attr2 UNCHANGED (no tile/palette corruption)",
      spr_attr2(p_spr) == p_attr2_before, string.format("0x%04X -> 0x%04X", p_attr2_before, spr_attr2(p_spr)))

MB.send(MB.OP_DESPAWN_PEER_NPC, {oeId})
for _=1,20 do emu.frameadvance() end
check("ghost despawned cleanly", spr_inuse(g_spr) == 0)
finish()
