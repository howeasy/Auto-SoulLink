-- test_live_enemyparty.lua — LIVE Phase-2: OP_CREATE_MON into the ENEMY party (the Rival-Team-Swap
-- fix). Creates a bulky and a frail species into empty gEnemyParty slots on the in-battle save and
-- confirms each is species-accurate. CREATE_MON is a patch op the client never sends: posted through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (card C5-4b). Battle savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("enemyparty")
t.boot({ state = "slink_battle.State", native = false })

local ENEMY, MON = t.ram.ENEMY_BASE, 100
local function pid(s)   return memory.read_u32_le(ENEMY + s*MON + 0x00) end
local function level(s) return memory.read_u8 (ENEMY + s*MON + 0x54) end
local function maxhp(s) return memory.read_u16_le(ENEMY + s*MON + 0x58) end
t.log("enemy slot0 (active) maxhp=" .. maxhp(0))

local LV = 40
local MONS = { { slot = 1, name = "Snorlax", id = 143 }, { slot = 2, name = "Diglett", id = 50 } }
for _, m in ipairs(MONS) do
    -- party=1 (enemy), bump=1 (set gEnemyPartyCount) — the full Rival-Team-Swap build
    local r = t.raw_wait("OP_CREATE_MON", { m.slot, 1, m.id % 256, m.id // 256, LV, 1 }, nil, 30)
    m.lv, m.pid, m.hp = level(m.slot), pid(m.slot), maxhp(m.slot)
    t.log(string.format("  enemy %s (id=%d) -> %s lv=%d pid=0x%08X maxhp=%d", m.name, m.id,
                        t.receipt_str(r), m.lv, m.pid, m.hp))
    t.check(m.name .. " CREATE_MON acked OK", t.acked_ok(r), t.receipt_str(r))
    t.check(m.name .. " level==40", m.lv == LV)
    t.check(m.name .. " pid!=0", m.pid ~= 0)
    t.check(m.name .. " maxhp>0", m.hp > 0)
end
t.check("Snorlax maxhp > Diglett maxhp (species-specific base stats, enemy side)",
        MONS[1].hp > MONS[2].hp, string.format("snorlax=%d diglett=%d", MONS[1].hp, MONS[2].hp))
t.check("gEnemyPartyCount bumped to 3", memory.read_u8(t.ram.ENEMY_COUNT_ADDR) == 3,
        "count=" .. memory.read_u8(t.ram.ENEMY_COUNT_ADDR))
t.finish()
