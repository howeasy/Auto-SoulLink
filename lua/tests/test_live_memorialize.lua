-- test_live_memorialize.lua — LIVE validation of the native memorialize opcode on a patched ROM:
--   OP_MEMORIALIZE (26): party[slot] -> memorial box (compress), then ZERO + SWAP-WITH-LAST removal.
-- Unlike OP_DEPOSIT_MON's shift-compact, survivors must KEEP their slot indices (CFRU's deferred
-- battle writes target slots).
--
-- The gate takes the save's REAL party: memorializes slot 0, then asserts (1) the compressed mon
-- landed in the box slot (personality survives), (2) party count dropped by one, (3) the FORMER LAST
-- party mon now occupies slot 0 (swap, not shift), (4) the vacated last slot is zeroed, and that bad
-- bounds are refused. The client memorializes through lua/gen3/boxes.lua, so OP_MEMORIALIZE (and the
-- OP_CREATE_MON filler) go through lua/tests/gen3_gatelib.lua's test-only raw poster (card C5-4b).
-- Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("memorialize")
t.boot({ state = "slink_overworld.State", native = false })

local MON          = 100
local PARTY        = t.ram.PARTY_BASE
local PARTY_COUNT  = t.ram.PARTY_COUNT_ADDR
-- CFRU box 24 (the memorial box on RR: BOXES_PER_STORE-1), slot 28 — distinct from boxsync's slot 29.
local BOX_ID, BOX_POS = 24, 28
local COMP_SIZE    = 0x3A
local box24_base   = 0x02024638
local comp_addr    = box24_base + BOX_POS * COMP_SIZE

local function u8(a)  return memory.read_u8(a)  end
local function u16(a) return memory.read_u16_le(a) end
local function u32(a) return memory.read_u32_le(a) end
local function party(slot) return PARTY + slot * MON end
local function snap(slot)
    local b = party(slot)
    return { pers = u32(b), otid = u32(b + 4), species = u16(b + 0x20) }
end

local count0 = u8(PARTY_COUNT)
t.log(string.format("party count=%d", count0))
if count0 < 2 then
    -- The overworld save has a 1-mon party: natively add a filler (OP_CREATE_MON, bump count) so
    -- the swap-with-last semantics have something to swap. Species 1 (Bulbasaur line) lv 5.
    local r = t.raw_wait("OP_CREATE_MON", { count0, 0, 1, 0, 5, 1 }, nil, 120)
    if not t.acked_ok(r) then t.fail("OP_CREATE_MON filler acked OK", t.receipt_str(r)) end
    count0 = u8(PARTY_COUNT)
    t.log(string.format("filler added -> party count=%d", count0))
    if count0 < 2 then t.fail("party >= 2 after the filler", "count=" .. count0) end
end

-- Zero the target box slot so the deposit target is guaranteed empty (instrumentation).
for i = 0, COMP_SIZE - 1 do memory.write_u8(comp_addr + i, 0) end

local victim = snap(0)
local last   = snap(count0 - 1)
t.log(string.format("victim slot0: pers=%08X species=%d | last slot%d: pers=%08X species=%d",
    victim.pers, victim.species, count0 - 1, last.pers, last.species))

-- OP_MEMORIALIZE: party[0] -> box24[28].  args [0]=partySlot [1]=boxId [2]=boxPos
local r = t.raw_wait("OP_MEMORIALIZE", { 0, BOX_ID, BOX_POS }, nil, 120)
t.check("OP_MEMORIALIZE acked ST_OK", t.acked_ok(r), t.receipt_str(r))

-- (1) compressed mon landed: CFRU compressed box mon keeps personality at +0.
t.check("box slot holds the victim (personality)", u32(comp_addr) == victim.pers,
        string.format("box=%08X want=%08X", u32(comp_addr), victim.pers))
-- (2) party count dropped.
t.check("party count decremented", u8(PARTY_COUNT) == count0 - 1,
        string.format("count=%d want=%d", u8(PARTY_COUNT), count0 - 1))
-- (3) SWAP semantics: the former LAST mon now sits in slot 0.
local s0 = snap(0)
t.check("former last mon swapped into slot 0", s0.pers == last.pers and s0.species == last.species,
        string.format("slot0 pers=%08X want=%08X", s0.pers, last.pers))
-- (4) the vacated last slot is zeroed.
local lz = true
for i = 0, MON - 1 do if u8(party(count0 - 1) + i) ~= 0 then lz = false; break end end
t.check("vacated last slot zeroed", lz)

-- Bounds rejection: bad slot / box both ack ST_FAIL.
local function refused(rr) return rr ~= nil and rr.why == "native refused" end
local r2 = t.raw_wait("OP_MEMORIALIZE", { 6, BOX_ID, BOX_POS }, nil, 120)
t.check("partySlot 6 rejected", refused(r2), t.receipt_str(r2))
local r3 = t.raw_wait("OP_MEMORIALIZE", { 0, 25, BOX_POS }, nil, 120)
t.check("box 25 rejected", refused(r3), t.receipt_str(r3))
t.finish()
