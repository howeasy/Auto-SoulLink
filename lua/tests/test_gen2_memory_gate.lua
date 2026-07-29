--[[
  lua/tests/test_gen2_memory_gate.lua — headless: does the Gen 2 profile read a REAL game?

  The automated counterpart to test_gen2_memory.lua, which prints to the Lua console and
  waits for a human to press F-keys. Every address here is already checked against pret by
  tools/verify_profile_addresses.py; what that CANNOT check is whether the numbers mean
  anything on a running cartridge — a correct address read through the wrong domain, or a
  struct offset applied to the wrong base, still produces plausible-looking bytes. That gap
  is where every bug Gen 1's live bring-up found was hiding.

  Runs against tests/fixtures/gen2/crystal_town.SaveRAM, whose contents are known exactly
  because tools/gen2_playthrough.py wrote them:

      one level-5 Totodile (species 158), 20/20 HP, no held item, healthy
      moves Scratch (0x0A) / Leer (0x2B), PP 35 / 30
      Atk 11, Def 11, Spd 10, SpAtk 10, SpDef 10
      10 Poke Balls in the BALLS pocket
      standing in PLAYERS_HOUSE_2F, map group 24 map 7

  ASSERTIONS ARE CHOSEN TO BE GEN 2-SPECIFIC where a Gen 1-shaped read would still look
  plausible — the held-item byte Gen 1 does not have, the map GROUP Gen 1 does not have, the
  Sp.Atk / Sp.Def split Gen 1 does not have, and 14 boxes rather than 12.

  Result file: patch/build/test_gen2_memory_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gatelib.lua")
local t = G.start("test_gen2_memory_gate", {game = "gen2_crystal"})
local M = t.M
local fmt = string.format

-- ── Party ────────────────────────────────────────────────────────────────────
local count = M.getPartyCount()
t.check("party count is 1", count == 1, fmt("got %d", count))

local mon = M.readPartySlot(0)
t.check("slot 0 decodes", mon ~= nil)
if mon then
    -- Gen 2 species ids ARE NatDex, unlike Gen 1's internal indices. 158 is Totodile in
    -- both, so also assert toNatDex is an identity rather than an index table.
    t.check("species is Totodile (158)", mon.species_index == 158,
            fmt("got %s", tostring(mon.species_index)))
    t.check("Gen 2 species ids need no NatDex conversion", t.G.toNatDex(158) == 158,
            fmt("got %s", tostring(t.G.toNatDex(158))))
    t.check("level is 5", mon.level == 5, fmt("got %d", mon.level))
    t.check("HP is 20/20", mon.hp == 20 and mon.maxHP == 20,
            fmt("got %d/%d", mon.hp, mon.maxHP))
    t.check("status is healthy", mon.status_cond == 0, fmt("got %s", tostring(mon.status_cond)))
    -- The held-item byte exists only from Gen 2. If HELD_ITEM_OFFSET were wrong it would
    -- read a move id or a DV byte, i.e. something nonzero — so "is exactly 0" is a real
    -- check here, on a fixture written with no held item.
    t.check("held item reads as none", mon.held_item == 0,
            fmt("got %s", tostring(mon.held_item)))
    -- A key is DVs:OTID:species — the identity every Soul Link rule hangs off.
    t.check("mon key has the DDDD:TTTT:SS shape", mon.key and #mon.key == 12,
            fmt("got %q", tostring(mon.key)))
    t.check("mon key ends in the species byte", mon.key and mon.key:sub(-2) == "9E",
            fmt("got %q", tostring(mon.key)))
end

t.check("nickname decodes as TOTODILE", M.readPartyNickname(0) == "TOTODILE",
        fmt("got %q", tostring(M.readPartyNickname(0))))

-- ── Stats: the Sp.Atk / Sp.Def split ─────────────────────────────────────────
-- Gen 1 has ONE Special. Gen 2 split it (party_struct: SpclAtk +0x2C, SpclDef +0x2E), and
-- no Gen 2 profile declared stats_offset at all — so readPartyStats returned nil, the
-- deposit-time cache stored nil, and Status/HP/MaxHP and all five stats were dropped on
-- deposit and never restored. Same class as the Gen 1 retrieveBoxMon corruption.
local st = M.readPartyStats(0)
t.check("readPartyStats returns a block", st ~= nil,
        "nil means the profile has no stats_offset and every box deposit loses the stats")
if st then
    t.check("Attack is 11", st.attack == 11, fmt("got %s", tostring(st.attack)))
    t.check("Defense is 11", st.defense == 11, fmt("got %s", tostring(st.defense)))
    t.check("Speed is 10", st.speed == 10, fmt("got %s", tostring(st.speed)))
    t.check("Sp.Atk is 10", st.spAtk == 10, fmt("got %s", tostring(st.spAtk)))
    t.check("Sp.Def is 10", st.spDef == 10, fmt("got %s", tostring(st.spDef)))
    t.check("maxHP agrees with the party read", st.maxHP == 20, fmt("got %s", tostring(st.maxHP)))
end

-- The values above are all equal in the fixture, so they cannot tell an aliased Sp.Def from
-- a real one. Prove the two stats are DIFFERENT ADDRESSES by writing one and re-reading:
-- with the Gen 1 alias in place, spDef would follow spAtk and this fails.
if st then
    local base = M.PARTY_BASE_ADDR
    M.write_u16_be(base + 0x2C, 77)          -- SpclAtk
    local probe = M.readPartyStats(0)
    t.check("Sp.Def is read from its own address, not aliased onto Sp.Atk",
            probe and probe.spAtk == 77 and probe.spDef == 10,
            fmt("after writing SpclAtk=77: spAtk=%s spDef=%s",
                tostring(probe and probe.spAtk), tostring(probe and probe.spDef)))
    M.write_u16_be(base + 0x2C, 10)          -- put it back
end

-- ── Moves + PP ───────────────────────────────────────────────────────────────
-- Gen 2 moves live at +0x02 and PP at +0x17, both different from Gen 1.
local mp = M.readMovesAndPP(M.PARTY_BASE_ADDR, nil)
t.check("moves decode", mp ~= nil)
if mp then
    t.check("move 1 is Scratch (0x0A)", mp.moves[1] == 0x0A,
            fmt("got %s", tostring(mp.moves[1])))
    t.check("move 2 is Leer (0x2B)", mp.moves[2] == 0x2B,
            fmt("got %s", tostring(mp.moves[2])))
    t.check("move 3 is empty", mp.moves[3] == 0, fmt("got %s", tostring(mp.moves[3])))
    -- PP is PP-Up PACKED (PP_MASK %00111111), not raw — reporting it raw over-states PP for
    -- any mon with PP Ups applied, which is what Gen 1's profile did until it was corrected.
    t.check("move 1 PP is 35 after masking", mp.pp[1] == 35, fmt("got %s", tostring(mp.pp[1])))
    t.check("move 2 PP is 30 after masking", mp.pp[2] == 30, fmt("got %s", tostring(mp.pp[2])))
end

-- ── Nuzlocke gate ────────────────────────────────────────────────────────────
-- hasPokeballs reads the real BALLS POCKET (Crystal keeps balls separate from items), and
-- the whole rule set stays inactive until it is true — so a wrong pocket address or a wrong
-- ball id silently disables the nuzlocke rather than erroring. Both were wrong here: the
-- profiles listed the Apricorn balls at 0xA9-0xAF, which are SUN_STONE, POLKADOT_BOW,
-- UP_GRADE, BERRY, GOLD_BERRY and SQUIRTBOTTLE.
t.check("hasPokeballs() sees the fixture's balls", M.hasPokeballs() == true)
t.check("countPokeballs() == 10", M.countPokeballs() == 10,
        fmt("got %s", tostring(M.countPokeballs())))

-- ── Player / world ───────────────────────────────────────────────────────────
local ot = M.readPlayerId()
t.check("player OT id is readable and nonzero", ot and ot > 0, fmt("got %s", tostring(ot)))
t.check("badge count is 0 on a fresh save", M.readBadgeCount() == 0,
        fmt("got %s", tostring(M.readBadgeCount())))
t.check("Johto and Kanto badges are separate bitfields, both empty",
        M.readJohtoBadges() == 0 and M.readKantoBadges() == 0,
        fmt("got johto=%s kanto=%s",
            tostring(M.readJohtoBadges()), tostring(M.readKantoBadges())))
t.check("not in battle in the town fixture", M.isInBattle() == false)
t.check("overworld gate agrees", M.isInOverworld() == true)

-- Gen 2 addresses a map by GROUP and NUMBER; Gen 1 has a single id. Reading only one of the
-- pair is the mistake that resolves every map in a group to the same area.
local group, number = M.getMapGroupAndNumber()
t.check("map is PLAYERS_HOUSE_2F (group 24, number 7)", group == 24 and number == 7,
        fmt("got group=%s number=%s", tostring(group), tostring(number)))

-- ── Box ──────────────────────────────────────────────────────────────────────
-- The active box lives in SRAM in Gen 2, reached through the CartRAM domain rather than the
-- System Bus — a correct address read through the wrong domain returns plausible bytes.
local box = M.getBoxCount()
t.check("box count is 0 on a fresh save", box == 0, fmt("got %s", tostring(box)))
local active_box = M.getCurrentBoxNum()
t.check("active box index is sane for 14 boxes (0..13)",
        active_box and active_box >= 0 and active_box <= 13,
        fmt("got %s", tostring(active_box)))
-- Box 14 (index 13) is where memorialized pairs are buried. An unreadable or garbage count
-- there means depositMemorialMon would append past the end of the box.
local mem = M.getMemorialBoxCount()
t.check("memorial box count is 0 on a fresh save", mem == 0, fmt("got %s", tostring(mem)))

t.finish(fmt("variant=%s", t.variant))
