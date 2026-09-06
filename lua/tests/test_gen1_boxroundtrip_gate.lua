-- Retrieval integration: canonical recomputation ignores complete stale cache data;
-- malformed supplied data NACKs without changing the cartridge, then permits retry.
-- The independent cartridge CalcLevel/CalcStats oracle is test_gen1_storage_differential.
-- This gate compares the SAME boxed inputs across cache modes, never the fixture's
-- cached party tail: existing fixtures can legitimately carry level 5 with experience 0.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
local G = dofile(ROOT .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_boxroundtrip_gate")
local M, fmt = t.M, string.format
local STRUCT, BOXLEN, NAME = M.PARTY_STRUCT_SIZE, M.BOX_STRUCT_SIZE, 11

local function bytes(addr, count, reader)
    local out = {}
    for i = 0, count - 1 do out[#out + 1] = string.char(reader(addr + i)) end
    return table.concat(out)
end
local function mon(party, slot)
    local size = party and STRUCT or BOXLEN
    local read = party and M.read_u8 or M.box_read_u8
    local base = party and M.PARTY_BASE_ADDR or M.BOX_BASE_ADDR
    local ot = party and M.PARTY_OT_NAMES_ADDR or M.BOX_OT_NAMES_ADDR
    local nick = party and M.PARTY_NICKS_ADDR or M.BOX_NICKS_ADDR
    return bytes(base + slot * size, size, read)
        .. bytes(ot + slot * NAME, NAME, read) .. bytes(nick + slot * NAME, NAME, read)
end
local function put(addr, blob)
    for i = 1, #blob do M.write_u8(addr + i - 1, blob:byte(i)) end
end
local function party_slot(key)
    for slot = 0, M.getPartyCount() - 1 do
        if M.monKey(M.PARTY_BASE_ADDR + slot * STRUCT) == key then return slot end
    end
end
local function cartridge_snapshot()
    -- Include the unused landing slot: a NACK may neither clear it nor partly fill it.
    local ram = bytes(0xC000, 0x2000, M.read_u8)
    local hram = bytes(0xFF80, 0x7F, M.read_u8)
    local sram = bytes(0, memory.getmemorydomainsize("CartRAM"), function(addr)
        return memory.read_u8(addr, "CartRAM")
    end)
    return ram .. hram .. sram .. tostring(emu.getregister("SRAM BANK"))
end

if not t.check("fixture has one party mon, an empty current box and a valid box number",
        M.getPartyCount() == 1 and M.getBoxCount() == 0 and M.getCurrentBoxNum() ~= nil) then
    t.finish("fixture prerequisites failed")
end
local original = mon(true, 0)
local keys = {}
-- Keep the real starter in slot 0. Different OTIDs make the three test mons distinct
-- and avoid accidentally testing Yellow's separate starter-Pikachu PC policy here.
local original_ot = M.read_u16_be(M.PARTY_BASE_ADDR + M.OTID_OFFSET)
for slot = 1, 3 do
    local base = M.PARTY_BASE_ADDR + slot * STRUCT
    put(base, original:sub(1, STRUCT))
    put(M.PARTY_OT_NAMES_ADDR + slot * NAME, original:sub(STRUCT + 1, STRUCT + NAME))
    put(M.PARTY_NICKS_ADDR + slot * NAME, original:sub(STRUCT + NAME + 1))
    M.write_u16_be(base + M.OTID_OFFSET, (original_ot + slot) % 65536)
    M.write_u8(M.PARTY_OT_NAMES_ADDR + slot * NAME, 0x80 + slot)
    M.write_u8(M.PARTY_NICKS_ADDR + slot * NAME, 0x90 + slot)
    M.write_u8(M.PARTY_SPECIES_ADDR + slot, original:byte(1))
    keys[slot] = M.monKey(base)
end
M.write_u8(M.PARTY_COUNT_ADDR, 4)
M.write_u8(M.PARTY_SPECIES_ADDR + 4, 0xFF)
local target = M.PARTY_BASE_ADDR + 2 * STRUCT
M.write_u8(target + M.LEVEL_OFFSET, 99) -- deliberately disagrees with preserved experience
M.write_u16_be(target + M.HP_OFFSET, 9)
M.write_u8(target + M.STATUS_OFFSET, 0x08)
for move = 0, 3 do
    if M.read_u8(target + 8 + move) ~= 0 then
        M.write_u8(target + 29 + move, (move + 1) % 4 * 64 + 1)
    end
end
for index = 1, 3 do
    local before = mon(true, 1)
    local level = before:byte(M.LEVEL_OFFSET + 1)
    local ok, err = M.depositPartyMon(1)
    if not t.check("deposit test mon " .. index, ok, err) then t.finish("deposit failed") end
    local expected = before:sub(1, 3) .. string.char(level) .. before:sub(5, BOXLEN)
        .. before:sub(STRUCT + 1)
    t.check("deposit preserves struct, OT and nickname " .. index,
        mon(false, index - 1) == expected and M.scanBoxForKey(keys[index]) == index - 1)
end
local boxed = {mon(false, 0), mon(false, 1), mon(false, 2)}
local key = keys[2]
-- Poison the unused destination BEFORE cloning; failed attempts must leave it intact.
put(M.PARTY_BASE_ADDR + STRUCT, string.rep(string.char(0xA5), STRUCT))
put(M.PARTY_OT_NAMES_ADDR + NAME, string.rep(string.char(0xA5), NAME))
put(M.PARTY_NICKS_ADDR + NAME, string.rep(string.char(0xA5), NAME))
local checkpoint = memorysavestate.savecorestate()
local function restore(cache)
    memorysavestate.loadcorestate(checkpoint)
    M._party_tail_cache = cache or {}
end
local function stale_stats()
    return {level = 80, maxHP = 901, attack = 902, defense = 903,
            speed = 904, spAtk = 905, spDef = 905}
end

restore()
local ok, err = M.retrieveBoxMon(key)
if not t.check("no-cache retrieval recomputes and appends", ok, err) then
    t.finish("no-cache retrieval failed")
end
local baseline = mon(true, 1)
t.check("received mon appended behind the untouched original", party_slot(key) == 1
    and M.getPartyCount() == 2 and mon(true, 0) == original)
t.check("all 33 boxed bytes including HP/status/PP-Up survive", baseline:sub(1, BOXLEN) == boxed[2]:sub(1, BOXLEN))
t.check("all 22 OT/nickname bytes survive", baseline:sub(STRUCT + 1) == boxed[2]:sub(BOXLEN + 1))
local level = baseline:byte(M.LEVEL_OFFSET + 1)
t.check("level is recomputed instead of replaying stale BoxLevel", level >= 1 and level <= 100 and level ~= 99,
    fmt("BoxLevel=99, experience=%d, received level=%d",
        boxed[2]:byte(15) * 65536 + boxed[2]:byte(16) * 256 + boxed[2]:byte(17), level))
for offset = 0x22, 0x2A, 2 do
    local value = baseline:byte(offset + 1) * 256 + baseline:byte(offset + 2)
    t.check(fmt("recomputed stat at +%02X is legal", offset), value >= 1 and value <= 999)
end
t.check("middle-box removal compacts both records and parallel names", M.getBoxCount() == 2
    and mon(false, 0) == boxed[1] and mon(false, 1) == boxed[3] and M.scanBoxForKey(key) == nil)
t.check("both species lists remain terminated", M.read_u8(M.PARTY_SPECIES_ADDR + 2) == 0xFF
    and M.box_read_u8(M.BOX_SPECIES_ADDR + 2) == 0xFF)

for _, mode in ipairs({"server", "local"}) do
    local stale = stale_stats()
    restore(mode == "local" and {[key] = stale} or nil)
    local supplied = mode == "server" and stale or nil
    local accepted, reason = M.retrieveBoxMon(key, supplied)
    t.check(mode .. " complete stale cache produces the identical 66-byte result",
        accepted and mon(true, 1) == baseline, reason)
end

local invalid = {
    {"partial", {level = 5, maxHP = 20}},
    {"out-of-range level", stale_stats()},
    {"fractional stat", stale_stats()},
    {"zero maxHP", stale_stats()},
    {"inconsistent Special", stale_stats()},
}
invalid[2][2].level = 101
invalid[3][2].attack = 1.5
invalid[4][2].maxHP = 0
invalid[5][2].spDef = 906
for _, case in ipairs(invalid) do
    restore()
    local before = cartridge_snapshot()
    local called, result, reason = pcall(M.retrieveBoxMon, key, case[2])
    t.check(case[1] .. " returns a retryable NACK without throwing",
        called and result == false and type(reason) == "string" and #reason > 0, reason)
    t.check(case[1] .. " changes no WRAM, HRAM, SRAM or SRAM-bank selection",
        cartridge_snapshot() == before)
    local retried, retry_reason = M.retrieveBoxMon(key)
    t.check(case[1] .. " permits a valid retry with identical output",
        retried and mon(true, 1) == baseline, retry_reason)
end

-- A failed canonical lookup cannot fall back to a plausible-looking server cache.
restore()
local before, rebuild = cartridge_snapshot(), M._game.rebuildBoxStats
M._game.rebuildBoxStats = function() return nil end
local called, result = pcall(M.retrieveBoxMon, key, stale_stats())
M._game.rebuildBoxStats = rebuild
t.check("unavailable canonical evidence NACKs without writes", called and result == false
    and cartridge_snapshot() == before)
t.check("restored canonical evidence permits retry", M.retrieveBoxMon(key)
    and mon(true, 1) == baseline)

local x, y = M.MAP_ID_ADDR + 4, M.MAP_ID_ADDR + 3
local x0, y0 = M.read_u8(x), M.read_u8(y)
for attempt = 1, 8 do
    t.hold(attempt % 2 == 1 and "Right" or "Left", 24, function()
        return M.read_u8(x) ~= x0 or M.read_u8(y) ~= y0
    end)
    if M.read_u8(x) ~= x0 or M.read_u8(y) ~= y0 then break end
end
t.check("the cartridge still walks with the recomputed party",
    M.read_u8(x) ~= x0 or M.read_u8(y) ~= y0)
t.check("party and received identity survive actual engine frames", M.getPartyCount() == 2 and party_slot(key) == 1)
t.finish(fmt("variant=%s; cache independence, full byte fidelity, zero-mutation NACK/retry", t.variant))
