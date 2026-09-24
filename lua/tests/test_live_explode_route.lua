-- test_live_explode_route.lua — LIVE validation of the native Explode-Mode route on a patched ROM,
-- against the C5-FMS-FIX handlers.c (15a274ec + 21df5314):
--   1. write MOVE_EXPLOSION into gBattleMons[battler].moves[0] (+ pp[0]=5; a 0-PP slot is refused),
--   2. post OP_FORCE_MOVE_SLOT {battler, target=1, move_pos=0} to arm the controller swap,
--   3. the driver fires from the parked action/move menu, reads moves[0], commits Explosion, hands the
--      controller back (PlayerBufferExecCompleted) and acks ST_OK.
-- PASS = the ack is ST_OK, slot 0 holds Explosion AND its PP drops (the engine ran the turn through
-- the handed-back controller — this gate never clears the exec flags, which is what used to mask the
-- missing hand-back), with the mailbox still alive. The self-faint (hp->0) is logged as information.
-- Production RR explode uses the Lua battle_commit path; FORCE_MOVE_SLOT is gate-only, so it goes
-- through lua/tests/gen3_gatelib.lua's test-only raw poster (card C5-4b). Battle savestate.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("exploderoute")

local MOVE_EXPLOSION = 153
local gBM, gComm = 0x02023BE4, 0x02023E82
local gBattlerControllerFuncs = 0x03004FE0
local ACTION_CTRL_A, ACTION_CTRL_CFRU, MOVE_CTRL_THUNK = 0x0802E439, 0x090A9EA1, 0x0802EA11
local function move(b,i) return memory.read_u16_le(gBM + b*0x58 + 0x0C + i*2) end
local function pp(b,i)   return memory.read_u8   (gBM + b*0x58 + 0x24 + i)     end
local function hp(b)     return memory.read_u16_le(gBM + b*0x58 + 0x28)        end
local function parked(b)
    local c, f = memory.read_u8(gComm + b), memory.read_u32_le(gBattlerControllerFuncs + b * 4)
    return (c == 1 and (f == ACTION_CTRL_A or f == ACTION_CTRL_CFRU)) or (c == 2 and f == MOVE_CTRL_THUNK)
end
-- A advances battle text only while the menu is not parked (A there would race the driver).
local function drive(i) return (not parked(0) and i % 2 == 0) and { A = true } or nil end

t.boot({ state = "slink_battle.State", native = false })
local B, POS, TARGET = 0, 0, 1
t.log(string.format("before: moves[0]=%d pp[0]=%d hp=%d", move(B,POS), pp(B,POS), hp(B)))

-- Step 1: stamp Explosion into slot 0 (+PP) — the battle state the route commits (instrumentation).
memory.write_u16_le(gBM + B*0x58 + 0x0C + POS*2, MOVE_EXPLOSION)
memory.write_u8   (gBM + B*0x58 + 0x24 + POS,    5)
local pp0 = pp(B,POS)
-- Step 2: arm the driver.  args [0]=battler [1]=target [2]=move_pos
local job = t.raw("OP_FORCE_MOVE_SLOT", { B, TARGET, POS })
t.check("FORCE_MOVE_SLOT posted", t.wait_posted(job))
t.log(string.format("armed: moves[0]=%d (expect %d) pp[0]=%d", move(B,POS), MOVE_EXPLOSION, pp0))

-- Phase 1: let the battle reach the parked menu and the driver fire; then the turn must run.
local r = t.wait(job, 900, drive)
t.check("driver acked ST_OK", t.acked_ok(r), t.receipt_str(r))
local committed = false
for i = 1, 900 do
    if pp(B,POS) < pp0 then committed = true; break end
    t.step(drive(i))
end

-- Phase 2 (informational only): advance a while in case the turn resolves the self-faint.
local self_fainted = (hp(B) == 0)
if committed then
    for i = 1, 600 do
        t.step(drive(i))
        if hp(B) == 0 then self_fainted = true; break end
    end
end

local explosion_selected = (move(B,POS) == MOVE_EXPLOSION)
t.log(string.format("after: moves[0]=%d pp[0]=%d (was %d) hp=%d committed=%s self_fainted=%s(info)",
    move(B,POS), pp(B,POS), pp0, hp(B), tostring(committed), tostring(self_fainted)))
t.check("Explosion committed and fired (slot-0 PP dropped)", committed)
t.check("slot 0 still holds Explosion", explosion_selected, "moves[0]=" .. move(B,POS))
t.check("beacon still present (no crash)", t.present())
t.finish()
