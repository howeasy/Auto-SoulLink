-- test_live_memorialize.lua — LIVE validation of the native memorialize opcode on a patched ROM:
--   OP_MEMORIALIZE (26): party[slot] -> memorial box (compress), then ZERO + SWAP-WITH-LAST removal.
-- Unlike OP_DEPOSIT_MON's shift-compact, survivors must KEEP their slot indices (CFRU's deferred
-- battle writes target slots — the same reason Lua M.memorializeMon swaps instead of shifting).
--
-- The test takes the save's REAL party: memorializes slot 0, then asserts (1) the compressed mon
-- landed in the box slot (personality survives), (2) party count dropped by one, (3) the FORMER LAST
-- party mon now occupies slot 0 (swap, not shift), (4) the vacated last slot is zeroed. Run on the
-- PATCHED ROM with the overworld savestate:
--   EmuHawk.exe --lua=lua/tests/test_live_memorialize.lua patch/build/slink_RR.gba
-- (launch from the worktree cwd with RELATIVE paths — the "Google Drive" space splits absolute args.)

local WT  = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/memorialize_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_overworld.State"
local MB  = dofile(WT .. "/lua/mailbox.lua")

local MON          = 100
local gPlayerParty = 0x02024284
local gPartyCount  = 0x02024029
-- CFRU box 24 (the memorial box on RR: BOXES_PER_STORE-1), slot 28 — distinct from boxsync's slot 29.
local BOX_ID, BOX_POS = 24, 28
local COMP_SIZE    = 0x3A
local box24_base   = 0x02024638
local comp_addr    = box24_base + BOX_POS * COMP_SIZE

local function u8(a)  return memory.read_u8(a)  end
local function u16(a) return memory.read_u16_le(a) end
local function u32(a) return memory.read_u32_le(a) end
local function party(slot) return gPlayerParty + slot * MON end
local function snap(slot)
    local b = party(slot)
    return { pers = u32(b), otid = u32(b + 4), species = u16(b + 0x20) }
end

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end
local function abort(why) fails = fails + 1; log("ABORT: " .. why); finish() end

pcall(function() client.speedmode(400) end)
pcall(memory.usememorydomain, "System Bus")
local ok_ss = pcall(savestate.load, STATE)
for _ = 1, 30 do emu.frameadvance() end
if not MB.present() then abort("beacon never appeared (unpatched ROM?)  ss_loaded=" .. tostring(ok_ss)); return end

local count0 = u8(gPartyCount)
log(string.format("party count=%d", count0))
if count0 < 2 then
    -- The overworld save has a 1-mon party: natively add a slot-1 mon (OP_CREATE_MON, bump count)
    -- so the swap-with-last semantics have something to swap. Species 1 (Bulbasaur line) lv 5.
    local cs = MB.send(MB.OP_CREATE_MON, MB.create_mon_args(count0, 1, 5, 0, 1))
    local cst
    for _ = 1, 120 do emu.frameadvance(); cst = MB.poll(cs); if cst then break end end
    if cst ~= MB.ST_OK then abort("OP_CREATE_MON filler failed: " .. tostring(cst)); return end
    count0 = u8(gPartyCount)
    log(string.format("filler added -> party count=%d", count0))
    if count0 < 2 then abort("party still < 2 after filler"); return end
end

-- Zero the target box slot so the deposit target is guaranteed empty.
for i = 0, COMP_SIZE - 1 do memory.write_u8(comp_addr + i, 0) end

local victim = snap(0)
local last   = snap(count0 - 1)
log(string.format("victim slot0: pers=%08X species=%d | last slot%d: pers=%08X species=%d",
    victim.pers, victim.species, count0 - 1, last.pers, last.species))

-- OP_MEMORIALIZE: party[0] -> box24[28]
local seq = MB.memorialize_mon(0, BOX_ID, BOX_POS)
local st
for _ = 1, 120 do emu.frameadvance(); st = MB.poll(seq); if st then break end end
check("OP_MEMORIALIZE acked ST_OK", st == MB.ST_OK, "status=" .. tostring(st))

-- (1) compressed mon landed: CFRU compressed box mon keeps personality at +0.
check("box slot holds the victim (personality)", u32(comp_addr) == victim.pers,
      string.format("box=%08X want=%08X", u32(comp_addr), victim.pers))
-- (2) party count dropped.
check("party count decremented", u8(gPartyCount) == count0 - 1,
      string.format("count=%d want=%d", u8(gPartyCount), count0 - 1))
-- (3) SWAP semantics: the former LAST mon now sits in slot 0.
local s0 = snap(0)
check("former last mon swapped into slot 0", s0.pers == last.pers and s0.species == last.species,
      string.format("slot0 pers=%08X want=%08X", s0.pers, last.pers))
-- (4) the vacated last slot is zeroed.
local lz = true
for i = 0, MON - 1 do if u8(party(count0 - 1) + i) ~= 0 then lz = false; break end end
check("vacated last slot zeroed", lz)

-- Bounds rejection: bad slot / box / pos all ack ST_FAIL.
local s2 = MB.memorialize_mon(6, BOX_ID, BOX_POS)
for _ = 1, 120 do emu.frameadvance(); st = MB.poll(s2); if st then break end end
check("partySlot 6 rejected", st == MB.ST_FAIL, "status=" .. tostring(st))
local s3 = MB.memorialize_mon(0, 25, BOX_POS)
for _ = 1, 120 do emu.frameadvance(); st = MB.poll(s3); if st then break end end
check("box 25 rejected", st == MB.ST_FAIL, "status=" .. tostring(st))

finish()
