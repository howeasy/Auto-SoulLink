-- test_live_ghostbattle.lua — the ghost must SUSPEND during battle (patch must not touch gSprites,
-- which the battle engine reuses -> the reported rival-battle corruption/crash). Load an in-battle
-- savestate, request a ghost, advance frames, and assert it does NOT spawn / drive while in battle.
-- DEFERRED (peer ghost is post-RC): opt-in via SLINK_GATES_DEFERRED=1. Ghost ops go through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c). Battle savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("ghostbattle")
local GBATTLEMONS, GBATTLEOUTCOME = 0x02023BE4, 0x02023E8A
t.boot({ state = "slink_battle.State", native = false })

local maxhp = memory.read_u16_le(GBATTLEMONS + 0x2C)
local outcome = memory.read_u8(GBATTLEOUTCOME)
t.log(string.format("battle state: gBattleMons[0].maxHP=%d gBattleOutcome=%d", maxhp, outcome))
t.check("savestate is in-battle (maxHP>0 && outcome==0)", maxhp > 0 and outcome == 0)

-- request a ghost + post a target; the patch must REFUSE to spawn/drive while in battle.
t.ghost_set_pos(160, 160, 1, 0, 0, false)
t.ghost_spawn(0)
local spawned = false
for _ = 1, 120 do t.step(nil); if t.ghost_oe() < 16 then spawned = true; break end end
t.check("ghost did NOT spawn while in battle (suspended)", not spawned, "oeId=" .. t.ghost_oe())
t.ghost_clear()
t.finish()
