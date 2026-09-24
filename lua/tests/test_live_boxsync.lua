-- test_live_boxsync.lua — LIVE validation of the native PC box<->party storage opcodes on a patched ROM:
--   OP_DEPOSIT_MON  (24): party[slot] -> PC box (CFRU CreateCompressedMonFromBoxMon @0x090B6B78)
--   OP_WITHDRAW_MON (25): PC box -> party[slot] (CFRU CompressedMonToMon @0x090B6A24)
-- CFRU's own compressed-box conversion does the write, so a withdrawn mon comes back fully formed
-- (the engine recomputes level/stats/PP). The addresses were RE'd via the sPokemonBoxPtrs table
-- @0x09148930 (patch/src/ADDRESSES.md "PC storage / box migration reference").
--
-- The gate takes the save's REAL lead party mon, deposits it into a known-empty box slot, withdraws
-- it back, and asserts personality/OT/species survive the round trip. The client moves boxes through
-- lua/gen3/boxes.lua, never these opcodes, so they are posted through lua/tests/gen3_gatelib.lua's
-- test-only raw poster (card C5-4b). Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("boxsync")
t.boot({ state = "slink_overworld.State", native = false })

local MON          = 100
local PARTY        = t.ram.PARTY_BASE
local PARTY_COUNT  = t.ram.PARTY_COUNT_ADDR
-- CFRU box 24 (last box) base from CFRU_BOX_BASES; slot 29 (last slot) = base + 29*0x3A. Almost
-- certainly empty on any save; we also zero it first to guarantee an empty deposit target.
local BOX_ID, BOX_POS = 24, 29
local COMP_SIZE    = 0x3A
local box24_base   = 0x02024638
local comp_addr    = box24_base + BOX_POS * COMP_SIZE

local function u8(a)  return memory.read_u8(a)  end
local function u16(a) return memory.read_u16_le(a) end
local function u32(a) return memory.read_u32_le(a) end
local function party(slot) return PARTY + slot * MON end
-- CFRU party Pokemon (unencrypted, fixed order): personality@0, otId@4, species@0x20, level@0x54.
local function snap(slot)
    local b = party(slot)
    return { pers = u32(b), otid = u32(b + 4), species = u16(b + 0x20), level = u8(b + 0x54) }
end
local function send_wait(op, args, label)
    local r = t.raw_wait(op, args, nil, 120)
    t.check(label .. " acked ST_OK", t.acked_ok(r), t.receipt_str(r))
    return r
end

local count0 = u8(PARTY_COUNT)
t.check("party has a lead mon to test", count0 >= 1, "count=" .. count0)
if count0 < 1 then t.finish() end

local orig = snap(0)
t.log(string.format("lead mon: pers=%08X otid=%08X species=%d level=%d", orig.pers, orig.otid, orig.species, orig.level))
t.check("lead species is sane (1..1200)", orig.species >= 1 and orig.species <= 1200, "species=" .. orig.species)

-- Guarantee an empty deposit target (PC storage, not a native arena: instrumentation).
for i = 0, COMP_SIZE - 1 do memory.write_u8(comp_addr + i, 0) end

-- DEPOSIT party[0] -> box24/slot29.  args [0]=partySlot [1]=boxId [2]=boxPos
send_wait("OP_DEPOSIT_MON", { 0, BOX_ID, BOX_POS }, "OP_DEPOSIT_MON")
t.check("party count decremented after deposit", u8(PARTY_COUNT) == count0 - 1,
        "count " .. count0 .. " -> " .. u8(PARTY_COUNT))
local comp_nonzero = false
for i = 0, COMP_SIZE - 1 do if u8(comp_addr + i) ~= 0 then comp_nonzero = true; break end end
t.check("box slot now holds compressed data", comp_nonzero)

-- WITHDRAW box24/slot29 -> party[end].  args [0]=boxId [1]=boxPos [2]=partySlot
local dst_slot = count0 - 1
send_wait("OP_WITHDRAW_MON", { BOX_ID, BOX_POS, dst_slot }, "OP_WITHDRAW_MON")
t.check("party count restored after withdraw", u8(PARTY_COUNT) == count0, "count=" .. u8(PARTY_COUNT))

local back = snap(dst_slot)
t.log(string.format("withdrawn: pers=%08X otid=%08X species=%d level=%d", back.pers, back.otid, back.species, back.level))
t.check("personality preserved round-trip", back.pers == orig.pers, string.format("%08X vs %08X", back.pers, orig.pers))
t.check("OT id preserved round-trip", back.otid == orig.otid)
t.check("species preserved round-trip", back.species == orig.species, back.species .. " vs " .. orig.species)
t.check("level recomputed sane (>0)", back.level > 0, "level=" .. back.level)

local box_zeroed = true
for i = 0, COMP_SIZE - 1 do if u8(comp_addr + i) ~= 0 then box_zeroed = false; break end end
t.check("box slot freed (zeroed) after withdraw", box_zeroed)
t.check("beacon still present (no corruption)", t.present())
t.finish()
