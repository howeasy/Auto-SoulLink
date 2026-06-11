-- test_live_boxsync.lua — LIVE validation of the native PC box⇄party storage opcodes on a patched ROM:
--   OP_DEPOSIT_MON  (24): party[slot] -> PC box (CFRU CreateCompressedMonFromBoxMon @0x090B6B78)
--   OP_WITHDRAW_MON (25): PC box -> party[slot] (CFRU CompressedMonToMon @0x090B6A24)
-- These retire the fragile Lua depositPartyMon/retrieveBoxMon RAM-pokes by letting CFRU's own
-- compressed-box conversion do the write (so a withdrawn mon comes back fully formed — the engine
-- recomputes level/stats/PP). The addresses were RE'd via the sPokemonBoxPtrs table @0x09148930
-- (see patch/src/ADDRESSES.md "PC storage / box migration reference").
--
-- The test takes the save's REAL lead party mon (a genuine RR mon with real moves/IVs/EVs), deposits
-- it into a known-empty box slot, withdraws it back, and asserts personality/OT/species survive the
-- round trip — the faithfulness proof a hand-rolled poke can get subtly wrong. Run on the PATCHED ROM
-- with the overworld savestate:
--   EmuHawk.exe --lua=lua/tests/test_live_boxsync.lua patch/build/slink_RR.gba
-- (launch from the worktree cwd with RELATIVE paths — the "Google Drive" space splits absolute args.)

local WT  = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/boxsync_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_overworld.State"
local MB  = dofile(WT .. "/lua/mailbox.lua")

local MON          = 100
local gPlayerParty = 0x02024284
local gPartyCount  = 0x02024029
-- CFRU box 24 (last box) base from CFRU_BOX_BASES; slot 29 (last slot) = base + 29*0x3A. Almost
-- certainly empty on any save; we also zero it first to guarantee an empty deposit target.
local BOX_ID, BOX_POS = 24, 29
local COMP_SIZE    = 0x3A
local box24_base   = 0x02024638
local comp_addr    = box24_base + BOX_POS * COMP_SIZE

local function u8(a)  return memory.read_u8(a)  end
local function u16(a) return memory.read_u16_le(a) end
local function u32(a) return memory.read_u32_le(a) end
local function party(slot) return gPlayerParty + slot * MON end
-- CFRU party Pokemon (unencrypted, fixed order): personality@0, otId@4, species@0x20, level@0x54.
local function snap(slot)
    local b = party(slot)
    return { pers = u32(b), otid = u32(b + 4), species = u16(b + 0x20), level = u8(b + 0x54) }
end

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end
local function send_wait(seq, label)
    if not seq then check(label .. " sent", false, "seq=nil"); return nil end
    local st
    for _ = 1, 120 do emu.frameadvance(); st = MB.poll(seq); if st then break end end
    check(label .. " acked ST_OK", st == MB.ST_OK, "status=" .. tostring(st))
    return st
end

pcall(function() client.speedmode(400) end)
pcall(memory.usememorydomain, "System Bus")
local ok_ss = pcall(savestate.load, STATE)
for _ = 1, 30 do emu.frameadvance() end
if not MB.present() then log("FAIL: beacon never appeared (unpatched ROM?)  ss_loaded=" .. tostring(ok_ss)); finish(); return end
log("beacon up; savestate loaded=" .. tostring(ok_ss))

local count0 = u8(gPartyCount)
check("party has a lead mon to test", count0 >= 1, "count=" .. count0)
if count0 < 1 then finish(); return end

local orig = snap(0)
log(string.format("lead mon: pers=%08X otid=%08X species=%d level=%d", orig.pers, orig.otid, orig.species, orig.level))
check("lead species is sane (1..1200)", orig.species >= 1 and orig.species <= 1200, "species=" .. orig.species)

-- Guarantee an empty deposit target.
for i = 0, COMP_SIZE - 1 do memory.write_u8(comp_addr + i, 0) end

-- DEPOSIT party[0] -> box24/slot29.
send_wait(MB.deposit_mon(0, BOX_ID, BOX_POS), "OP_DEPOSIT_MON")
check("party count decremented after deposit", u8(gPartyCount) == count0 - 1,
      "count " .. count0 .. " -> " .. u8(gPartyCount))
local comp_nonzero = false
for i = 0, COMP_SIZE - 1 do if u8(comp_addr + i) ~= 0 then comp_nonzero = true; break end end
check("box slot now holds compressed data", comp_nonzero)

-- WITHDRAW box24/slot29 -> party[end].
local dst_slot = count0 - 1
send_wait(MB.withdraw_mon(BOX_ID, BOX_POS, dst_slot), "OP_WITHDRAW_MON")
check("party count restored after withdraw", u8(gPartyCount) == count0,
      "count=" .. u8(gPartyCount))

local back = snap(dst_slot)
log(string.format("withdrawn: pers=%08X otid=%08X species=%d level=%d", back.pers, back.otid, back.species, back.level))
check("personality preserved round-trip", back.pers == orig.pers,
      string.format("%08X vs %08X", back.pers, orig.pers))
check("OT id preserved round-trip", back.otid == orig.otid)
check("species preserved round-trip", back.species == orig.species,
      back.species .. " vs " .. orig.species)
check("level recomputed sane (>0)", back.level > 0, "level=" .. back.level)

local box_zeroed = true
for i = 0, COMP_SIZE - 1 do if u8(comp_addr + i) ~= 0 then box_zeroed = false; break end end
check("box slot freed (zeroed) after withdraw", box_zeroed)
check("beacon still present (no corruption)", MB.present())
finish()
