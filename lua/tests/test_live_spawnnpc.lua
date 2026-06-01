-- test_live_spawnnpc.lua — LIVE Phase-3 SPAWN_PEER_NPC: spawn a real engine object-event
-- next to the player via SpawnSpecialObjectEventParameterized. Confirms the engine created
-- a proper object-event + sprite (so the engine owns rendering — retiring the Lua peer-ghost
-- saga). Load with the PATCHED ROM + overworld savestate.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/spawnnpc_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_overworld.State"
local MB = dofile(WT .. "/lua/mailbox.lua")

local OE, STRIDE = 0x02036E38, 0x24   -- gObjectEvents; peer-ghost confirmed
local GS, GSTRIDE = 0x0202063C, 0x44  -- gSprites
local function oe_flags(i)  return memory.read_u8 (OE + i*STRIDE + 0x00) end
local function oe_sprite(i) return memory.read_u8 (OE + i*STRIDE + 0x04) end
local function oe_gfx(i)    return memory.read_u8 (OE + i*STRIDE + 0x05) end
local function oe_local(i)  return memory.read_u8 (OE + i*STRIDE + 0x08) end
local function oe_x(i)      return memory.read_u16_le(OE + i*STRIDE + 0x10) end
local function oe_y(i)      return memory.read_u16_le(OE + i*STRIDE + 0x12) end
local function spr_inuse(s) return (memory.read_u8(GS + s*GSTRIDE + 0x3E) & 1) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE); emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end

-- player object-event (slot 0): use its graphicsId (guaranteed valid) + spawn one tile east
local pgfx, px, py = oe_gfx(0), oe_x(0), oe_y(0)
local LOCALID = 0xF0
log(string.format("player oe[0]: gfx=%d coords=(%d,%d); spawning localId=0x%X gfx=%d at (%d,%d)",
    pgfx, px, py, LOCALID, pgfx, px+1, py))

local st = MB.send(MB.OP_SPAWN_PEER_NPC, MB.spawn_npc_args(pgfx, LOCALID, px+1, py, 0))
local ok=false; for _=1,30 do emu.frameadvance(); if MB.poll(st) then ok=true; break end end
local oeId = MB.read_result_u8(0)
log(string.format("acked=%s -> object-event id = %d", tostring(ok), oeId))

check("spawn returned a valid object-event id (<16)", oeId < 16, "id="..oeId)
if oeId < 16 then
    log(string.format("oe[%d]: flags=0x%02X spriteId=%d gfx=%d localId=0x%X coords=(%d,%d)",
        oeId, oe_flags(oeId), oe_sprite(oeId), oe_gfx(oeId), oe_local(oeId), oe_x(oeId), oe_y(oeId)))
    check("object-event is active (flags bit0)", (oe_flags(oeId) & 1) == 1)
    check("localId matches", oe_local(oeId) == LOCALID)
    check("graphicsId matches", oe_gfx(oeId) == pgfx)
    check("spawned adjacent to player (x = px+1)", oe_x(oeId) == px+1, string.format("got %d want %d", oe_x(oeId), px+1))
    local sid = oe_sprite(oeId)
    check("a sprite was allocated + in use", spr_inuse(sid) == 1, "spriteId="..sid)

    -- DESPAWN: clean removal — object-event inactive + sprite freed
    local st2 = MB.send(MB.OP_DESPAWN_PEER_NPC, {oeId})
    for _=1,30 do emu.frameadvance(); if MB.poll(st2) then break end end
    log(string.format("after despawn: oe[%d].flags=0x%02X  sprite[%d].inUse=%d",
        oeId, oe_flags(oeId), sid, spr_inuse(sid)))
    check("object-event cleared (inactive)", (oe_flags(oeId) & 1) == 0)
    check("sprite freed", spr_inuse(sid) == 0)
end
finish()
