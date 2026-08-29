--[[
  lua/tests/test_gen1_stat_rebuild.lua — recompute the party's stats and check the GAME agrees.

  Gen 1's box struct is 33 bytes and stores no computed stats, so withdrawing a boxed mon
  has to recreate Attack/Defence/Speed/Special. When the deposit-time cache is missing,
  retrieveBoxMon used to refuse rather than improvise -- correctly, because the alternative
  it replaced left those four at zero and produced a mon that could not fight, which is
  silent permanent save corruption.

  Rebuilding them is only safe if the formula is EXACTLY the engine's. This gate is the
  proof, and it needs no fixture of its own: every mon in the party already carries both the
  inputs (level, DVs, stat exp) and the answer the game itself computed. Recompute from the
  inputs, compare against the stored stats, and a formula that is even one off anywhere
  fails.

  That makes it a genuine known-positive control rather than a self-consistency check --
  nothing here reads the stored stats before computing them.

      python tools/run_gb_gate.py lua/tests/test_gen1_stat_rebuild.lua --rom red --target battle
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_stat_rebuild")
local M, Game = t.M, t.G
local fmt = string.format

-- Box-struct offsets, macros/ram.asm box_struct. The party struct is the box struct plus an
-- 11-byte tail, so these apply to a party slot unchanged.
local DVS_OFF        = 0x1B
local STAT_EXP_OFF   = {hp = 0x11, attack = 0x13, defense = 0x15, speed = 0x17, special = 0x19}
-- The party-only tail.
local LEVEL_OFF      = 0x21
local STAT_OFF       = {hp = 0x22, attack = 0x24, defense = 0x26, speed = 0x28, special = 0x2A}

local FIELDS = {"hp", "attack", "defense", "speed", "special"}

t.check("the game module exposes the rebuild", type(Game.rebuildBoxStats) == "function")
t.check("the profile knows this variant's base-stat table",
        Game.ROM_BASE_STATS[t.variant] ~= nil, "variant=" .. tostring(t.variant))

-- Sanity-check the ROM read itself before trusting anything built on it. Bulbasaur's line
-- is 45/49/49/45/65 (data/pokemon/base_stats/bulbasaur.asm) in all three titles.
local bulb = Game.readBaseStats(t.variant, 1)
t.check("Bulbasaur's base stats read out of the ROM", bulb ~= nil, "readBaseStats returned nil")
if bulb then
    t.check("they are 45/49/49/45/65",
            bulb.hp == 45 and bulb.attack == 49 and bulb.defense == 49
            and bulb.speed == 45 and bulb.special == 65,
            fmt("got %d/%d/%d/%d/%d", bulb.hp, bulb.attack, bulb.defense,
                bulb.speed, bulb.special))
end
-- A wrong dex must fail rather than return a neighbouring species' line.
t.check("an out-of-range dex is refused", Game.readBaseStats(t.variant, 400) == nil)

-- ── the real comparison ──────────────────────────────────────────────────────
local count = M.getPartyCount()
t.check("the fixture has a party to check", count >= 1, fmt("party count is %d", count))

local checked, mismatches, nonzero_exp = 0, {}, 0
for slot = 0, count - 1 do
    local base_addr = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local species = M.read_u8(base_addr)
    local level = M.read_u8(base_addr + LEVEL_OFF)
    local dv = M.read_u16_be(base_addr + DVS_OFF)
    local stat_exp = {}
    for _, f in ipairs(FIELDS) do
        stat_exp[f] = M.read_u16_be(base_addr + STAT_EXP_OFF[f])
    end

    local got = Game.rebuildBoxStats(t.variant, species, level, dv, stat_exp)
    if got then
        checked = checked + 1
        for _, f in ipairs(FIELDS) do
            local stored = M.read_u16_be(base_addr + STAT_OFF[f])
            if got[f] ~= stored then
                mismatches[#mismatches + 1] = fmt(
                    "slot %d (species 0x%02X lv%d) %s: computed %d, the game stored %d",
                    slot, species, level, f, got[f], stored)
            end
        end
        -- Report the stat exp too: a party of freshly caught mons carries zeros, and with
        -- zeros the ceil(sqrt(statexp)) branch contributes nothing, so a pass would say
        -- less than it appears to. This makes the sample's real coverage visible.
        local exp_total = 0
        for _, f in ipairs(FIELDS) do exp_total = exp_total + stat_exp[f] end
        if exp_total > 0 then nonzero_exp = nonzero_exp + 1 end
        t.log(fmt("[stats] slot %d species=0x%02X lv%-3d dv=0x%04X statexp=%d -> "
                  .. "hp=%d atk=%d def=%d spd=%d spc=%d",
                  slot, species, level, dv, exp_total, got.hp, got.attack, got.defense,
                  got.speed, got.special))
    else
        t.log(fmt("[stats] slot %d species=0x%02X — no rebuild (unknown species?)",
                  slot, species))
    end
end

for _, m in ipairs(mismatches) do t.log("[stats] MISMATCH " .. m) end
t.check("every party mon was rebuildable", checked == count,
        fmt("rebuilt %d of %d", checked, count))
t.check("every recomputed stat matches what the game itself stored",
        #mismatches == 0,
        fmt("%d mismatch(es) — the formula is not the engine's", #mismatches))

-- Guard the refusal path: a species the table cannot describe must yield nil, so
-- retrieveBoxMon keeps refusing rather than writing stats it cannot justify.
t.check("an unmapped species index rebuilds to nil",
        Game.rebuildBoxStats(t.variant, 0x1F, 5, 0, {}) == nil,
        "0x1F is one of Gen 1's MissingNo holes and has no dex number")

t.log(fmt("[stats] coverage: %d mons, %d of them with non-zero stat exp", checked, nonzero_exp))
t.finish(fmt("%d party mons x %d stats, all matching (%d with stat exp)",
             checked, #FIELDS, nonzero_exp))
