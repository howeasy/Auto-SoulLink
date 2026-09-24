-- test_live_ghostwarp.lua — the ghost must never be ORPHANED: OP_GHOST_CLEAR removes it cleanly
-- (the same RemoveEventObject path a warp uses), and a map change never leaves a second localId-0xF0
-- object event behind.
-- DEFERRED (peer ghost is post-RC): opt-in via SLINK_GATES_DEFERRED=1. Ghost ops go through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c). Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("ghostwarp")
t.boot({ state = "slink_overworld.State", native = false })

local OE, OST = t.P.OBJECT_EVENTS_BASE, 0x24
local function p_sx() return memory.read_s16_le(OE + 0x10) end
local function p_sy() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function oe_active(i) return (memory.read_u8(OE + i*OST) & 1) == 1 end
local function oe_localid(i) return memory.read_u8(OE + i*OST + 0x08) end
local function ghost_oe_count()
    local n = 0
    for i = 0, 15 do if oe_active(i) and oe_localid(i) == t.P.LOCALID then n = n + 1 end end
    return n
end

local function spawn()
    t.ghost_set_pos(p_sx() * 16, p_sy() * 16, 1, 0, 0); t.ghost_spawn(p_gfx())
    for _ = 1, 120 do if t.ghost_oe() < 16 then return t.ghost_oe() end; t.step(nil) end
    return 16
end

-- (1) clean removal via OP_GHOST_CLEAR (same RemoveEventObject path the warp uses)
local oe = spawn()
t.check("ghost spawned", oe < 16, "oe=" .. oe); if oe >= 16 then t.finish() end
t.check("exactly one ghost OE", ghost_oe_count() == 1)
t.ghost_clear()
t.idle(6)
t.check("ghost fully removed after clear (no localId-0xF0 OE)", ghost_oe_count() == 0)
t.check("old slot freed (not active+ours)", not (oe_active(oe) and oe_localid(oe) == t.P.LOCALID))

-- (2) simulated map change must not leave an orphan
oe = spawn()
t.check("re-spawned ghost", oe < 16); if oe >= 16 then t.finish() end
local real_mn = memory.read_u8(OE + 0x09)
memory.write_u8(OE + 0x09, (real_mn + 1) % 256)   -- pretend the player warped (instrumentation)
t.idle(6)
t.check("no ORPHAN ghost after map change (<=1 localId-0xF0 OE)", ghost_oe_count() <= 1,
        "count=" .. ghost_oe_count())
memory.write_u8(OE + 0x09, real_mn)
t.idle(6)
t.check("still <=1 ghost after map restore", ghost_oe_count() <= 1, "count=" .. ghost_oe_count())
t.ghost_clear()
t.finish()
