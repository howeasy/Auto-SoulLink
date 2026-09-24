-- test_live_explode_route.lua — LIVE validation of the native Explode-Mode route on a patched ROM,
-- against the C5-FMS-FIX handlers.c (15a274ec + 21df5314):
--   1. write MOVE_EXPLOSION into gBattleMons[battler].moves[POS] (+ pp[POS]=5; a 0-PP slot is refused),
--   2. post OP_FORCE_MOVE_SLOT {battler, target=1, move_pos=POS} to arm the controller swap,
--   3. the driver fires from the parked action/move menu, reads moves[POS], commits Explosion, hands the
--      controller back (PlayerBufferExecCompleted) and acks ST_OK.
-- POS is slot 2, NOT the default cursor slot 0, so "the PP that dropped is POS's" can only come from
-- the forced pick (R2 L9). PASS = the ack is ST_OK, the controller is PlayerBufferRunCommand on the ack
-- frame (the hand-back forcemove also checks), slot POS still holds Explosion AND is the slot whose PP
-- dropped (the engine ran the turn through the handed-back controller; this gate never clears the exec
-- flags), with the mailbox alive. The self-faint (hp->0) is logged as information.
-- Production RR explode uses the Lua battle_commit path; FORCE_MOVE_SLOT is gate-only, so it goes
-- through lua/tests/gen3_gatelib.lua's test-only raw poster (card C5-4b). Battle savestate.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("exploderoute")

local MOVE_EXPLOSION = 153
local gBM, gComm = 0x02023BE4, 0x02023E82
local gBattlerControllerFuncs = 0x03004FE0
local ACTION_CTRL_A, ACTION_CTRL_CFRU, MOVE_CTRL_THUNK = 0x0802E439, 0x090A9EA1, 0x0802EA11
-- PlayerBufferExecCompleted stores PlayerBufferRunCommand, or CFRU 0x090ACD8D in its bit-24 mode
local RUN_COMMAND = { [0x0802E3B5] = true, [0x090ACD8D] = true }
local function move(b,i) return memory.read_u16_le(gBM + b*0x58 + 0x0C + i*2) end
local function pp(b,i)   return memory.read_u8   (gBM + b*0x58 + 0x24 + i)     end
local function hp(b)     return memory.read_u16_le(gBM + b*0x58 + 0x28)        end
local function ctrl(b)   return memory.read_u32_le(gBattlerControllerFuncs + b * 4) end
local function parked(b)
    local c, f = memory.read_u8(gComm + b), ctrl(b)
    return (c == 1 and (f == ACTION_CTRL_A or f == ACTION_CTRL_CFRU)) or (c == 2 and f == MOVE_CTRL_THUNK)
end
-- A advances battle text only while the menu is not parked (A there would race the driver).
local function drive(i) return (not parked(0) and i % 2 == 0) and { A = true } or nil end

t.boot({ state = "slink_battle.State", native = false })
local B, POS, TARGET = 0, 2, 1
t.log(string.format("before: moves[%d]=%d pp[%d]=%d hp=%d", POS, move(B,POS), POS, pp(B,POS), hp(B)))

-- Step 1: stamp Explosion into slot POS (+PP) — the battle state the route commits (instrumentation).
memory.write_u16_le(gBM + B*0x58 + 0x0C + POS*2, MOVE_EXPLOSION)
memory.write_u8   (gBM + B*0x58 + 0x24 + POS,    5)
local pp0 = { [0] = pp(B,0), [1] = pp(B,1), [2] = pp(B,2), [3] = pp(B,3) }
-- Step 2: arm the driver.  args [0]=battler [1]=target [2]=move_pos
local job = t.raw("OP_FORCE_MOVE_SLOT", { B, TARGET, POS })
t.check("FORCE_MOVE_SLOT posted", t.wait_posted(job))
t.log(string.format("armed: moves[%d]=%d (expect %d) pp[%d]=%d", POS, move(B,POS), MOVE_EXPLOSION, POS, pp0[POS]))

-- Phase 1: let the battle reach the parked menu and the driver fire; then the turn must run.
local r = t.wait(job, 900, drive)
local ctrl_at_ack = ctrl(B)
t.check("driver acked ST_OK", t.acked_ok(r), t.receipt_str(r))
t.check("controller handed back to PlayerBufferRunCommand on the fire frame",
        RUN_COMMAND[ctrl_at_ack] == true, string.format("ctrl=%08X", ctrl_at_ack))
local fired = nil
for i = 1, 900 do
    for s = 0, 3 do if pp(B, s) < pp0[s] then fired = s; break end end
    if fired then break end
    t.step(drive(i))
end

-- Phase 2 (informational only): advance a while in case the turn resolves the self-faint.
local self_fainted = (hp(B) == 0)
if fired then
    for i = 1, 600 do
        t.step(drive(i))
        if hp(B) == 0 then self_fainted = true; break end
    end
end

t.log(string.format("after: moves[%d]=%d pp=%d/%d/%d/%d fired_slot=%s hp=%d self_fainted=%s(info)",
    POS, move(B,POS), pp(B,0), pp(B,1), pp(B,2), pp(B,3), tostring(fired), hp(B), tostring(self_fainted)))
t.check("Explosion committed and fired from the forced slot (its PP dropped)", fired == POS,
        "fired_slot=" .. tostring(fired))
t.check("slot " .. POS .. " still holds Explosion", move(B,POS) == MOVE_EXPLOSION, "move=" .. move(B,POS))
t.check("beacon still present (no crash)", t.present())
t.finish()
