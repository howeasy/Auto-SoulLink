--[[
  lua/tests/test_gen1_memory_gate.lua — headless: does the Gen 1 profile read a REAL game?

  The automated counterpart to test_gen1_memory.lua, which prints to the Lua console and
  waits for a human to press F-keys. Every address here is already checked against pret by
  tools/verify_profile_addresses.py; what that CANNOT check is whether the numbers mean
  anything on a running cartridge — a correct address read through the wrong domain, or a
  struct offset applied to the wrong base, still produces plausible-looking bytes.

  Runs against tests/fixtures/gen1/<rom>_town.SaveRAM, whose contents are known exactly
  because tools/gen1_playthrough.py wrote them: one level-5 Squirtle (internal species 177)
  with 20/20 HP, and 5 Poke Balls in the bag.

  Result file: patch/build/test_gen1_memory_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_memory_gate")
local M = t.M
local fmt = string.format

-- ── Party ────────────────────────────────────────────────────────────────────
local count = M.getPartyCount()
t.check("party count is 1", count == 1, fmt("got %d", count))

local mon = M.readPartySlot(0)
t.check("slot 0 decodes", mon ~= nil)
if mon then
    -- The fixture's mon, written byte by byte by gen1_playthrough.lua.
    t.check("species is Squirtle (internal 177)", mon.species_index == 177,
            fmt("got %s", tostring(mon.species_index)))
    t.check("level is 5", mon.level == 5, fmt("got %d", mon.level))
    t.check("HP is 20/20", mon.hp == 20 and mon.maxHP == 20,
            fmt("got %d/%d", mon.hp, mon.maxHP))
    -- A key is DVs:OTID:species — the identity every Soul Link rule hangs off.
    t.check("mon key has the DDDD:TTTT:II shape", mon.key and #mon.key == 12,
            fmt("got %q", tostring(mon.key)))
    t.check("internal index maps to a NatDex number", t.G.toNatDex(mon.species_index) == 7,
            fmt("got %s", tostring(t.G.toNatDex(mon.species_index))))
end

-- ── Moves + PP ───────────────────────────────────────────────────────────────
local base = M.PARTY_BASE_ADDR
local mp = M.readMovesAndPP(base, nil)
t.check("moves decode", mp ~= nil)
if mp then
    t.check("move 1 is Tackle (33)", mp.moves[1] == 33, fmt("got %s", tostring(mp.moves[1])))
    -- PP is PP-Up PACKED in Gen 1 (PP_MASK %00111111), not raw — the profile said "raw"
    -- until this was corrected, which over-reported PP for any mon with PP Ups applied.
    t.check("move 1 PP is 35 after masking", mp.pp[1] == 35, fmt("got %s", tostring(mp.pp[1])))
end

-- ── Nuzlocke gate ────────────────────────────────────────────────────────────
-- hasPokeballs reads the real bag pocket; the whole rule set stays inactive until it is
-- true, so a wrong bag address silently disables the nuzlocke rather than erroring.
t.check("hasPokeballs() sees the fixture's 5 balls", M.hasPokeballs() == true)
t.check("countPokeballs() == 5", M.countPokeballs() == 5,
        fmt("got %s", tostring(M.countPokeballs())))

-- ── Player / world ───────────────────────────────────────────────────────────
local ot = M.readPlayerId()
t.check("player OT id is readable and nonzero", ot and ot > 0, fmt("got %s", tostring(ot)))
t.check("badge count is 0 on a fresh save", M.readBadgeCount() == 0,
        fmt("got %s", tostring(M.readBadgeCount())))
t.check("not in battle in the town fixture", M.isInBattle() == false)
t.check("overworld gate agrees", M.isInOverworld() == true)

-- ── Box ──────────────────────────────────────────────────────────────────────
local box = M.getBoxCount()
t.check("box count is sane (0..20)", box >= 0 and box <= 20, fmt("got %s", tostring(box)))
local active_box = M.getCurrentBoxNum()
t.check("active box index is sane (0..11)", active_box and active_box >= 0 and active_box <= 11,
        fmt("got %s", tostring(active_box)))

t.finish(fmt("variant=%s", t.variant))
