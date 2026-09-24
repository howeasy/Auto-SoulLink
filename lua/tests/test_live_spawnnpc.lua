-- test_live_spawnnpc.lua — LIVE Phase-3 SPAWN_PEER_NPC: spawn a real engine object-event next to the
-- player via SpawnSpecialObjectEventParameterized. Confirms the engine created a proper object-event
-- + sprite (so the engine owns rendering), then DESPAWN removes it cleanly.
-- DEFERRED (the ghost's engine NPC; peer ghost is post-RC): opt-in via SLINK_GATES_DEFERRED=1.
-- Posted through lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c). Overworld savestate.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("spawnnpc")
t.boot({ state = "slink_overworld.State", native = false })

local OE, STRIDE = t.P.OBJECT_EVENTS_BASE, 0x24   -- gObjectEvents
local GS, GSTRIDE = t.P.SPRITES_BASE, 0x44        -- gSprites
local function oe_flags(i)  return memory.read_u8 (OE + i*STRIDE + 0x00) end
local function oe_sprite(i) return memory.read_u8 (OE + i*STRIDE + 0x04) end
local function oe_gfx(i)    return memory.read_u8 (OE + i*STRIDE + 0x05) end
local function oe_local(i)  return memory.read_u8 (OE + i*STRIDE + 0x08) end
local function oe_x(i)      return memory.read_u16_le(OE + i*STRIDE + 0x10) end
local function oe_y(i)      return memory.read_u16_le(OE + i*STRIDE + 0x12) end
local function spr_inuse(s) return (memory.read_u8(GS + s*GSTRIDE + 0x3E) & 1) end

-- player object-event (slot 0): use its graphicsId (guaranteed valid) + spawn one tile east
local pgfx, px, py = oe_gfx(0), oe_x(0), oe_y(0)
local LOCALID = t.P.LOCALID
t.log(string.format("player oe[0]: gfx=%d coords=(%d,%d); spawning localId=0x%X gfx=%d at (%d,%d)",
    pgfx, px, py, LOCALID, pgfx, px+1, py))

-- args: [0]=gfxId [1]=localId [2..3]=x [4..5]=y [6]=movement
local x, y = px + 1, py
local r = t.raw_wait("OP_SPAWN_PEER_NPC", { pgfx, LOCALID, x % 256, (x // 256) % 256, y % 256, (y // 256) % 256, 0 },
                     nil, 30)
local oeId = r and r.result or 0xFF
t.log(string.format("%s -> object-event id = %d", t.receipt_str(r), oeId))
t.check("spawn acked", r ~= nil, t.receipt_str(r))
t.check("spawn returned a valid object-event id (<16)", oeId < 16, "id=" .. oeId)
if oeId < 16 then
    t.log(string.format("oe[%d]: flags=0x%02X spriteId=%d gfx=%d localId=0x%X coords=(%d,%d)",
        oeId, oe_flags(oeId), oe_sprite(oeId), oe_gfx(oeId), oe_local(oeId), oe_x(oeId), oe_y(oeId)))
    t.check("object-event is active (flags bit0)", (oe_flags(oeId) & 1) == 1)
    t.check("localId matches", oe_local(oeId) == LOCALID)
    t.check("graphicsId matches", oe_gfx(oeId) == pgfx)
    t.check("spawned adjacent to player (x = px+1)", oe_x(oeId) == px+1, string.format("got %d want %d", oe_x(oeId), px+1))
    local sid = oe_sprite(oeId)
    t.check("a sprite was allocated + in use", spr_inuse(sid) == 1, "spriteId=" .. sid)

    -- DESPAWN: clean removal — object-event inactive + sprite freed.  args [0]=objectEventId
    t.raw_wait("OP_DESPAWN_PEER_NPC", { oeId }, nil, 30)
    t.log(string.format("after despawn: oe[%d].flags=0x%02X  sprite[%d].inUse=%d",
        oeId, oe_flags(oeId), sid, spr_inuse(sid)))
    t.check("object-event cleared (inactive)", (oe_flags(oeId) & 1) == 0)
    t.check("sprite freed", spr_inuse(sid) == 0)
end
t.finish()
