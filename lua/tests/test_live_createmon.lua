-- test_live_createmon.lua — LIVE Phase-2 validation: OP_CREATE_MON calls the engine's CreateMon
-- natively. Creates two very different species at the same level in empty party slots and confirms
-- each has the requested level, a real PID, and species-specific maxHP (Snorlax >> Bulbasaur) —
-- proving correct per-species base stats (the "wrong base stats" bug a pure-RAM clone would have).
-- CREATE_MON is a patch op the client never sends: posted through lua/tests/gen3_gatelib.lua's
-- test-only raw poster (card C5-4b). Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("createmon")
t.boot({ state = "slink_overworld.State", native = false })

local PARTY, MON = t.ram.PARTY_BASE, 100
local function pid(s)   return memory.read_u32_le(PARTY + s*MON + 0x00) end
local function level(s) return memory.read_u8 (PARTY + s*MON + 0x54) end
local function maxhp(s) return memory.read_u16_le(PARTY + s*MON + 0x58) end
-- args: [0]=slot [1]=party(0=player,1=enemy) [2..3]=species [4]=level [5]=bump (handlers.c OP_CREATE_MON)
local function create_args(slot, species, lv) return { slot, 0, species % 256, species // 256, lv, 0 } end
t.log("party count=" .. memory.read_u8(t.ram.PARTY_COUNT_ADDR))

local LV = 50
local SPECIES = { { slot = 4, name = "Bulbasaur", id = 1 }, { slot = 5, name = "Snorlax", id = 143 } }
for _, s in ipairs(SPECIES) do
    t.log(string.format("slot %d before: pid=0x%08X lv=%d maxhp=%d", s.slot, pid(s.slot), level(s.slot), maxhp(s.slot)))
    local r = t.raw_wait("OP_CREATE_MON", create_args(s.slot, s.id, LV), nil, 30)
    s.pid, s.lv, s.hp = pid(s.slot), level(s.slot), maxhp(s.slot)
    t.log(string.format("  %s (id=%d) -> %s lv=%d pid=0x%08X maxhp=%d", s.name, s.id, t.receipt_str(r),
                        s.lv, s.pid, s.hp))
    t.check(s.name .. " CREATE_MON acked OK", t.acked_ok(r), t.receipt_str(r))
    t.check(s.name .. " level==50", s.lv == LV)
    t.check(s.name .. " pid!=0", s.pid ~= 0)
    t.check(s.name .. " maxhp>0", s.hp > 0)
end
-- species-specific base stats: Snorlax (bulky) must out-HP Bulbasaur at the same level
t.check("Snorlax maxhp > Bulbasaur maxhp (per-species base stats)", SPECIES[2].hp > SPECIES[1].hp,
        string.format("snorlax=%d bulba=%d", SPECIES[2].hp, SPECIES[1].hp))
t.finish()
