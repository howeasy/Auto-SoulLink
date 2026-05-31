-- test_mailbox_battle.lua — runtime LOGIC validation of the Phase-1 battle opcodes.
--
-- Live-engine validation (the move actually executing) needs an in-battle RR savestate,
-- which we don't have. This test instead proves the dispatcher computes addresses and
-- writes the engine globals CORRECTLY: it injects a controlled fake battle state into the
-- real RR RAM, fires FORCE_FAINT / FORCE_MOVE via the mailbox, and reads the globals back.
-- Combined with SLink's production Variant-3 (which proves those writes drive the engine),
-- this validates the native port's correctness. Load with the PATCHED ROM.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/battle_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

-- validated battle globals (see patch/src/ADDRESSES.md)
local gBattleMons, gAction, gMoves, gComm, gBS =
      0x02023BE4, 0x02023D7C, 0x02023DC4, 0x02023E82, 0x02023FE8
local BS_SCRATCH = 0x0203F900          -- our controlled BattleStruct (free EWRAM, past mailbox)

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local fails = 0
local function check(name, cond, extra)
    if not cond then fails = fails + 1 end
    log(string.format("  [%s] %s%s", cond and "PASS" or "FAIL", name, extra and ("  " .. extra) or ""))
end
local function finish()
    log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit()
end

pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(800) end)

-- wait for beacon
local ok = false
for _ = 1, 2000 do emu.frameadvance(); if MB.present() then ok = true; break end end
if not ok then log("FAIL: no beacon"); finish(); return end
log("beacon up")

local function send_wait(op, args)
    local s = MB.send(op, args)
    for _ = 1, 20 do emu.frameadvance(); local st = MB.poll(s); if st then return st end end
    return nil
end

-- ---- FORCE_FAINT: set battler 2's gBattleMons hp nonzero, then force-faint it ----
local B = 2
memory.write_u16_le(gBattleMons + B * 0x58 + 0x28, 0x015E)   -- hp = 350
check("precondition hp set", memory.read_u16_le(gBattleMons + B * 0x58 + 0x28) == 0x015E)
local st = send_wait(MB.OP_FORCE_FAINT, {B})
check("FORCE_FAINT acked ok", st == MB.ST_OK, "st=" .. tostring(st))
check("FORCE_FAINT zeroed hp", memory.read_u16_le(gBattleMons + B * 0x58 + 0x28) == 0,
      string.format("hp=0x%04X", memory.read_u16_le(gBattleMons + B * 0x58 + 0x28)))

-- ---- FORCE_MOVE: point gBattleStruct at our scratch, fire, verify all 5 writes ----
local Bm, target, move_pos, move_id = 1, 0, 2, 153   -- 153 = Explosion
memory.write_u32_le(gBS, BS_SCRATCH)                          -- bs ptr -> scratch
memory.write_u8(gAction + Bm, 0xFF)                          -- dirty, expect ->0
memory.write_u16_le(gMoves + Bm * 2, 0xFFFF)                 -- dirty, expect ->153
memory.write_u8(gComm + Bm, 0xFF)                            -- dirty, expect ->3
memory.write_u8(BS_SCRATCH + 0x80 + Bm, 0xFF)               -- dirty, expect ->2
memory.write_u8(BS_SCRATCH + 0x0C + Bm, 0xFF)               -- dirty, expect ->0
st = send_wait(MB.OP_FORCE_MOVE, MB.force_move_args(Bm, target, move_pos, move_id))
check("FORCE_MOVE acked ok", st == MB.ST_OK, "st=" .. tostring(st))
check("action[b]=USE_MOVE(0)", memory.read_u8(gAction + Bm) == 0)
check("move[b]=153", memory.read_u16_le(gMoves + Bm * 2) == 153)
check("comm[b]=3", memory.read_u8(gComm + Bm) == 3)
check("bs.chosenMovePos[b]=2", memory.read_u8(BS_SCRATCH + 0x80 + Bm) == move_pos)
check("bs.moveTarget[b]=0", memory.read_u8(BS_SCRATCH + 0x0C + Bm) == target)

-- ---- unknown opcode -> fail status (negative) ----
st = send_wait(99, {})
check("unknown opcode -> FAIL", st == MB.ST_FAIL, "st=" .. tostring(st))

finish()
