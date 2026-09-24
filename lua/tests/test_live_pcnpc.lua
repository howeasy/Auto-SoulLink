-- test_live_pcnpc.lua — LIVE Pokémon-Center trade NPC (presence-OFF path) through lua/gen3/native.lua.
-- native:config({pc_trade_npc = true}) sets TN_ENABLE the way the server's config command does; the
-- companion patch's drive_trade_npc then spawns a real engine NPC (localId 0xF1) on every Pokémon
-- Center 1F, auto-arms talk on it (SlinkState pi_oe / pi_armed), and despawns it when disabled. We
-- enable it, confirm the NPC spawned + talk is armed, place the player one tile south facing it,
-- press A, and assert pi_count bumps with NO local box (the SERVER drives the Trade/Say hey menu) and
-- that native:service turned the bump into exactly one trade_request event. Then we disable through
-- config and confirm clean removal.
--
-- Needs a savestate STANDING IN A POKÉMON CENTER 1F (front room). PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("pcnpc")
t.boot({ state = "slink_pokecenter.State" })

local P = t.P
local OE, OST  = P.OBJECT_EVENTS_BASE, 0x24   -- gObjectEvents
local GS, GST  = P.SPRITES_BASE, 0x44         -- gSprites
local PI_COUNT = P.PI_COUNT                   -- SlinkState: _rsvd0, pi_armed, pi_oe, pi_count
local PI_ARMED, PI_OE = PI_COUNT - 2, PI_COUNT - 1
local TN_LOCALID = 0xF1

local function oe_active(i) return (memory.read_u8(OE + i*OST + 0x00) & 1) == 1 end
local function oe_local(i)  return memory.read_u8 (OE + i*OST + 0x08) end
local function oe_sprite(i) return memory.read_u8 (OE + i*OST + 0x04) end
local function oe_cx(i)     return memory.read_s16_le(OE + i*OST + 0x10) end
local function oe_cy(i)     return memory.read_s16_le(OE + i*OST + 0x12) end
local function spr_inuse(s) return (memory.read_u8(GS + s*GST + 0x3E) & 1) end
local function find_npc()   for i=0,15 do if oe_active(i) and oe_local(i) == TN_LOCALID then return i end end return 16 end
-- The player is not always object-event slot 0: its slot is gPlayerAvatar.objectEventId (+0x05).
local function player_oe()
    local id = memory.read_u8(P.GPLAYER_AVATAR + 0x05)
    if id >= 16 then id = 0 end
    return OE + id * OST
end

local poe = player_oe()
t.log(string.format("player map = (%d,%d)  [confirm this is a Pokémon Center 1F in kPokecenter1F]",
                    memory.read_u8(poe + 0x0A), memory.read_u8(poe + 0x09)))

-- 1) Enable the patch's PC-NPC driver through native config; it should spawn + arm within a few frames.
t.native:config({ pc_trade_npc = true })
local npc = 16
for _ = 1, 120 do t.step(nil); npc = find_npc(); if npc < 16 then break end end
t.check("TN_ENABLE set through native config", memory.read_u8(P.TN_ENABLE) == 1)
t.check("trade NPC spawned (active OE, localId 0xF1)", npc < 16, "oe=" .. npc)
if npc >= 16 then
    t.log("  (no NPC — is the savestate inside a PC 1F? is this map in kPokecenter1F? is PCNPC_TILE valid?)")
    t.finish()
end
local nx, ny, sid = oe_cx(npc), oe_cy(npc), oe_sprite(npc)
t.log(string.format("  NPC oe=%d gfx=%d tile=(%d,%d) sprite=%d", npc, memory.read_u8(OE+npc*OST+0x05), nx, ny, sid))
t.check("NPC sprite allocated + in use", sid < 64 and spr_inuse(sid) == 1, "sprite=" .. sid)
t.check("talk armed on the NPC (SS->pi_oe + pi_armed)",
        memory.read_u8(PI_OE) == npc and memory.read_u8(PI_ARMED) == 1,
        string.format("pi_oe=%d pi_armed=%d", memory.read_u8(PI_OE), memory.read_u8(PI_ARMED)))

-- 2) Talk: put the player one tile SOUTH of the NPC, idle + facing NORTH, then press A.
--    check_peer_interact reads only the player's currentCoords/facing/idle + the armed OE's tile, so
--    repositioning the player struct is sufficient to simulate standing in front of the NPC.
memory.write_s16_le(poe + 0x10, nx)        -- player currentCoords X = NPC X
memory.write_s16_le(poe + 0x12, ny + 1)    -- player currentCoords Y = NPC Y + 1 (one tile south)
local face = memory.read_u8(poe + 0x18)
memory.write_u8(poe + 0x18, (face & 0xF0) | 2)        -- facing NORTH (toward the NPC)
memory.write_u8(poe + 0x00, memory.read_u8(poe) | 0x80)  -- heldMovementFinished (idle)

local c0 = memory.read_u8(PI_COUNT)
local sent0 = #t.sent_of("trade_request")
t.step({})
t.step({ A = true })                        -- A newly pressed, facing the NPC
t.idle(20)
t.check("peer-interact counter incremented", memory.read_u8(PI_COUNT) > c0,
        string.format("%d -> %d", c0, memory.read_u8(PI_COUNT)))
t.check("native:service sent exactly one trade_request", #t.sent_of("trade_request") == sent0 + 1,
        (#t.sent_of("trade_request") - sent0) .. " new trade_request events")
t.check("no local box auto-opened (server drives the menu)", memory.read_u8(0x03000F9C) == 0,
        "sScriptContext2Enabled=" .. memory.read_u8(0x03000F9C))

-- 3) Disable through native config: the patch must remove the NPC cleanly + disarm talk.
t.native:config({ pc_trade_npc = false })
for _ = 1, 60 do t.step(nil); if find_npc() >= 16 then break end end
t.check("TN_ENABLE cleared through native config", memory.read_u8(P.TN_ENABLE) == 0)
t.check("NPC removed when disabled", find_npc() >= 16)
t.check("sprite freed", sid >= 64 or spr_inuse(sid) == 0, "sprite=" .. sid)
t.check("talk disarmed", memory.read_u8(PI_ARMED) == 0, "pi_armed=" .. memory.read_u8(PI_ARMED))
t.check("game still running (no softlock)", t.present())
t.finish()
