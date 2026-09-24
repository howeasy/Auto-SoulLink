-- test_live_forcemove.lua — LIVE validation of OP_FORCE_MOVE_SLOT (the controller-swap driver),
-- against the C5-FMS-FIX handlers.c (15a274ec + 21df5314). Battle savestate, PATCHED ROM.
--
-- The driver, per patch/src/handlers.c drive_force_move / slink_force_controller:
--   * it swaps battler b's controller only while the player's menu is PARKED, with pret's 0-based
--     gBattleCommunication enum: comm 1 + HandleInputChooseAction (0x0802E439, or CFRU's second
--     spelling 0x090A9EA1) or comm 2 + HandleInputChooseMove (0x0802EA11); never in a link battle;
--   * the swapped routine writes the chosen move, sets comm 3 (CONFIRMED_STANDBY), and hands the slot
--     back with PlayerBufferExecCompleted (slot = PlayerBufferRunCommand 0x0802E3B5, or CFRU's
--     0x090ACD8D), then acks ST_OK;
--   * a slot with 0 PP is refused at the gate: disarm, ST_FAIL, reason 11, the menu stays with the
--     player.
-- The old gate cleared the battle exec flags every frame, which masked the missing hand-back (the
-- first message/animation for battler b hung). This gate never touches the exec flags: the forced
-- move's PP can only drop if the engine really ran the turn through the handed-back controller.
--
-- Part 1 forces SLOT 1 (Growl: NOT the default slot 0, NOT a Z-move) and needs it to execute. Part 2
-- reloads, empties slot 1's PP and needs the reason-11 refusal with the menu left alone.
-- FORCE_MOVE_SLOT is gate-only (production uses the Lua commit), so it goes through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (card C5-4b).
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("forcemove")

local gBM, gComm = 0x02023BE4, 0x02023E82
local gBattlerControllerFuncs = 0x03004FE0                -- u32[4] (handlers.c)
local ACTION_CTRL_A, ACTION_CTRL_CFRU = 0x0802E439, 0x090A9EA1
local MOVE_CTRL_THUNK = 0x0802EA11
-- PlayerBufferExecCompleted stores PlayerBufferRunCommand, or CFRU 0x090ACD8D in its bit-24 mode
-- (patch/src/ADDRESSES.md, the detour 0x0802E34A -> 0x0904459A).
local RUN_COMMAND = { [0x0802E3B5] = true, [0x090ACD8D] = true }
local function pp(b, i) return memory.read_u8(gBM + b*0x58 + 0x24 + i) end
local function comm(b) return memory.read_u8(gComm + b) end
local function ctrl(b) return memory.read_u32_le(gBattlerControllerFuncs + b * 4) end
local function parked(b)
    local c, f = comm(b), ctrl(b)
    return (c == 1 and (f == ACTION_CTRL_A or f == ACTION_CTRL_CFRU)) or (c == 2 and f == MOVE_CTRL_THUNK)
end
-- Advance battle text with A while the menu is NOT parked; never press while it is, or A would pick
-- a menu row itself and race the driver.
local function drive(i) return (not parked(0) and i % 2 == 0) and { A = true } or nil end

local B, POS, TARGET = 0, 1, 1     -- force slot 1 (Growl): NOT default slot 0, NOT a Z-move

-- ── part 1: the forced slot executes and the controller is handed back ──────────────────────
t.boot({ state = "slink_battle.State", native = false })
local pp0 = { [0] = pp(B,0), [1] = pp(B,1), [2] = pp(B,2), [3] = pp(B,3) }
t.log(string.format("pp_before=%d/%d/%d/%d  forcing slot %d", pp0[0], pp0[1], pp0[2], pp0[3], POS))
t.check("forced slot has PP to spend", pp0[POS] > 0, "pp=" .. pp0[POS])

-- args [0]=battler [1]=target [2]=move_pos; the patch acks when the move is committed
local job = t.raw("OP_FORCE_MOVE_SLOT", { B, TARGET, POS })
t.check("FORCE_MOVE_SLOT posted", t.wait_posted(job))
local r = t.wait(job, 900, drive)
local ctrl_at_ack = ctrl(B)
t.log(string.format("ack: %s comm=%d ctrl=%08X", t.receipt_str(r), comm(B), ctrl_at_ack))
t.check("driver acked ST_OK (fired from a parked menu)", t.acked_ok(r), t.receipt_str(r))
t.check("controller handed back to PlayerBufferRunCommand on the fire frame",
        RUN_COMMAND[ctrl_at_ack] == true, string.format("ctrl=%08X", ctrl_at_ack))

local fired = nil
for i = 1, 900 do
    for s = 0, 3 do if pp(B, s) < pp0[s] then fired = s; break end end
    if fired then break end
    t.step(drive(i))
end
t.log(string.format("pp_after=%d/%d/%d/%d  fired_slot=%s (forced %d)",
    pp(B,0), pp(B,1), pp(B,2), pp(B,3), tostring(fired), POS))
t.check("the forced slot executed (its PP dropped, no exec-flag clearing)", fired == POS,
        "fired_slot=" .. tostring(fired))
t.check("beacon still present (no crash)", t.present())

-- ── part 2: a 0-PP slot is refused with reason 11 and the menu stays with the player ─────────
t.boot({ state = "slink_battle.State", native = false })
memory.write_u8(gBM + B*0x58 + 0x24 + POS, 0)            -- pp[POS] = 0 (instrumentation)
local job2 = t.raw("OP_FORCE_MOVE_SLOT", { B, TARGET, POS })
t.check("0-PP FORCE_MOVE_SLOT posted", t.wait_posted(job2))
local r2 = t.wait(job2, 900, drive)
t.check("0-PP slot refused: ST_FAIL reason 11", r2 ~= nil and r2.why == "native refused" and r2.reason == 11,
        t.receipt_str(r2))
t.check("the menu stays with the player (still parked, not swapped)", parked(B),
        string.format("comm=%d ctrl=%08X", comm(B), ctrl(B)))
t.check("beacon still present (no crash)", t.present())
t.finish()
