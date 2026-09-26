-- test_live_peerinteract.lua — talk-to-ghost with the engine-driven ghost. The patch spawns the
-- ghost (OP_GHOST_SPAWN) and AUTO-ARMS interaction on it; we walk it to the tile in front of the
-- player, press A facing it, and assert pi_count bumps. The patch does NOT open its own box on
-- interact (the SERVER drives the talk-to-partner menu via OP_SHOW_MENU; a local box would set
-- sScriptContext2Enabled and make that menu bounce) — so we also assert no box auto-opened.
-- DEFERRED (peer ghost is post-RC): opt-in via SLINK_GATES_DEFERRED=1. Ghost ops and the staged
-- partner line go through lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c).
-- Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("peerinteract")
t.boot({ state = "slink_overworld.State", native = false })

local OE, OST = t.P.OBJECT_EVENTS_BASE, 0x24
local function p_tx() return memory.read_s16_le(OE + 0x10) end
local function p_ty() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function oe_cx(i) return memory.read_s16_le(OE + i*OST + 0x10) end
local function oe_cy(i) return memory.read_s16_le(OE + i*OST + 0x12) end
local function face_right() local v = memory.read_u8(OE + 0x18); memory.write_u8(OE + 0x18, (v & 0xF0) | 4) end

local px, py = p_tx(), p_ty()
t.check("partner line staged in TEXT_BUF", t.raw_stage({ t.message_stage("Hi from your partner!") }),
        t.last_service)
t.ghost_set_pos((px + 1) * 16, py * 16, 3, 0, 0)   -- 1 tile EAST (world px); collision tile pinned there
t.check("OP_GHOST_SPAWN acked OK", t.acked_ok(t.ghost_spawn(p_gfx())))
local oe = 16
for _ = 1, 150 do
    oe = t.ghost_oe()
    if oe < 16 and oe_cx(oe) == px+1 and oe_cy(oe) == py then break end
    t.step(nil)
end
t.check("ghost spawned + walked to the front tile", oe < 16 and oe_cx(oe) == px+1 and oe_cy(oe) == py,
        string.format("oe=%d at (%d,%d) want (%d,%d)", oe, oe < 16 and oe_cx(oe) or -1,
                      oe < 16 and oe_cy(oe) or -1, px+1, py))
if oe >= 16 then t.finish() end

local c0 = t.peer_interact_count()
t.step({}); face_right()
t.step({ A = true })                              -- A newly pressed, facing the ghost
t.idle(20)
t.check("peer-interact counter incremented", t.peer_interact_count() > c0,
        string.format("%d -> %d", c0, t.peer_interact_count()))
-- The patch must NOT open its own box (server drives the menu): sScriptContext2Enabled stays 0.
t.check("no local box auto-opened (server drives the menu)", memory.read_u8(0x03000F9C) == 0,
        "sScriptContext2Enabled=" .. memory.read_u8(0x03000F9C))
t.check("game still running (no softlock)", t.present())
t.ghost_clear()
t.finish()
