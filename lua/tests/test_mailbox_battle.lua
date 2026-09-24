-- test_mailbox_battle.lua — runtime LOGIC validation of the Phase-1 battle opcodes.
--
-- Proves the dispatcher computes addresses and writes the engine globals CORRECTLY: it injects a
-- controlled fake battle state into the real RR RAM, fires FORCE_FAINT / FORCE_MOVE via the mailbox,
-- and reads the globals back, then checks an unknown opcode is refused. Both ops are patch-only (the
-- client never sends them), so they go through lua/tests/gen3_gatelib.lua's test-only raw poster
-- (card C5-4b). Cold boot, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("battle")

-- validated battle globals (see patch/src/ADDRESSES.md)
local gBattleMons, gAction, gMoves, gComm, gBS =
      0x02023BE4, 0x02023D7C, 0x02023DC4, 0x02023E82, 0x02023FE8

t.boot({ native = false, beacon = 2000, speed = 800 })
-- COLD BOOT (G5-GATES-LIVE 2026-09-24): the beacon is up by frame ~12, before the game has set its save
-- pointers, and writes:arm refuses until they are live ("safety.lua: invalid pointer: gPokemonStoragePtr").
-- The client never arms that early (it waits for the server hello), so step until an arm would succeed.
-- Idle alone never gets there (3000 frames, run 2); RR sets them when the main menu loads the save
-- (lua/tests/mkstate.lua:38-46), so pulse Start through the intro/title (probe: armable ~8 frames
-- after the first Start at the title). The field is never entered: no A, no CONTINUE.
do
    local never = function() return false end
    local ready = false
    for _ = 1, 3000 do
        ready = pcall(function() t.writes:arm("native", never) end)
        t.writes:disarm()
        if ready then break end
        t.step((_ % 32 == 0) and { Start = true } or nil)
    end
    if not ready then t.fail("save pointers live (native arm possible)", "frame " .. t.frame) end
    t.log(string.format("native arm possible at frame %d", t.frame))
end
-- Our controlled BattleStruct: the patch text buffer (a native arena, so the dirty bytes are staged
-- through the raw poster's window; nothing else uses it in this gate).
local BS_SCRATCH = t.P.TEXT_BUF

local function send_wait(op, args) return t.raw_wait(op, args, nil, 20) end

-- ---- FORCE_FAINT: set battler 2's gBattleMons hp nonzero, then force-faint it ----
local B = 2
memory.write_u16_le(gBattleMons + B * 0x58 + 0x28, 0x015E)   -- hp = 350 (instrumentation)
t.check("precondition hp set", memory.read_u16_le(gBattleMons + B * 0x58 + 0x28) == 0x015E)
local r = send_wait("OP_FORCE_FAINT", { B })
t.check("FORCE_FAINT acked ok", t.acked_ok(r), t.receipt_str(r))
t.check("FORCE_FAINT zeroed hp", memory.read_u16_le(gBattleMons + B * 0x58 + 0x28) == 0,
        string.format("hp=0x%04X", memory.read_u16_le(gBattleMons + B * 0x58 + 0x28)))

-- ---- FORCE_MOVE: point gBattleStruct at our scratch, fire, verify all 5 writes ----
local Bm, target, move_pos, move_id = 1, 0, 2, 153   -- 153 = Explosion
memory.write_u32_le(gBS, BS_SCRATCH)                  -- bs ptr -> scratch
memory.write_u8(gAction + Bm, 0xFF)                  -- dirty, expect ->0
memory.write_u16_le(gMoves + Bm * 2, 0xFFFF)         -- dirty, expect ->153
memory.write_u8(gComm + Bm, 0xFF)                    -- dirty, expect ->3
t.check("scratch BattleStruct dirtied",            -- expect ->2 and ->0
        t.raw_stage({ { BS_SCRATCH + 0x80 + Bm, { 0xFF } }, { BS_SCRATCH + 0x0C + Bm, { 0xFF } } }),
        t.last_service)
-- args {battler, target, move_pos, 0, move_lo, move_hi}
r = send_wait("OP_FORCE_MOVE", { Bm, target, move_pos, 0, move_id % 256, move_id // 256 })
t.check("FORCE_MOVE acked ok", t.acked_ok(r), t.receipt_str(r))
t.check("action[b]=USE_MOVE(0)", memory.read_u8(gAction + Bm) == 0)
t.check("move[b]=153", memory.read_u16_le(gMoves + Bm * 2) == 153)
t.check("comm[b]=3", memory.read_u8(gComm + Bm) == 3)
t.check("bs.chosenMovePos[b]=2", memory.read_u8(BS_SCRATCH + 0x80 + Bm) == move_pos)
t.check("bs.moveTarget[b]=0", memory.read_u8(BS_SCRATCH + 0x0C + Bm) == target)

-- ---- unknown opcode -> fail status (negative) ----
r = send_wait(99, {})
t.check("unknown opcode -> FAIL", r ~= nil and r.why == "native refused", t.receipt_str(r))
t.finish()
