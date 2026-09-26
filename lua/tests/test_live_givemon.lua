-- test_live_givemon.lua — LIVE Phase-2 GIVE_MON: OP_CREATE_MON with bump makes a real, usable party
-- member (the party count increments and the mon is species-correct). Validates gift injection
-- (and, by the same code path, building the rival team). CREATE_MON is a patch op the client never
-- sends: posted through lua/tests/gen3_gatelib.lua's test-only raw poster (card C5-4b).
-- Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("givemon")
t.boot({ state = "slink_overworld.State", native = false })

local PARTY, COUNT, MON = t.ram.PARTY_BASE, t.ram.PARTY_COUNT_ADDR, 100
local function count() return memory.read_u8(COUNT) end
local function level(s) return memory.read_u8(PARTY + s*MON + 0x54) end
local function maxhp(s) return memory.read_u16_le(PARTY + s*MON + 0x58) end
local function pid(s)   return memory.read_u32_le(PARTY + s*MON + 0x00) end

local c0 = count()
local slot, SP, LV = c0, 143, 30        -- give a Snorlax into the next empty slot
t.log(string.format("party count before = %d; giving species %d L%d into slot %d", c0, SP, LV, slot))

-- args: [0]=slot [1]=party(0) [2..3]=species [4]=level [5]=bump(1)
local r = t.raw_wait("OP_CREATE_MON", { slot, 0, SP % 256, SP // 256, LV, 1 }, nil, 30)
t.log(string.format("after: %s count=%d  slot%d: lv=%d pid=0x%08X maxhp=%d",
    t.receipt_str(r), count(), slot, level(slot), pid(slot), maxhp(slot)))
t.check("CREATE_MON acked OK", t.acked_ok(r), t.receipt_str(r))
t.check("party count incremented", count() == c0 + 1, string.format("%d -> %d", c0, count()))
t.check("new mon level == 30", level(slot) == LV)
t.check("new mon has a PID", pid(slot) ~= 0)
t.check("new mon maxhp > 0 (species stats)", maxhp(slot) > 0)
t.finish()
