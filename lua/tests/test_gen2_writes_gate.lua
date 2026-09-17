--[[
  lua/tests/test_gen2_writes_gate.lua — headless: do the Gen 2 WRITES do what they claim?

  test_gen2_memory_gate only READS. Everything here mutates a live cartridge: force_faint,
  deposit, withdraw, and the memorial burial. This is the code that can corrupt somebody's
  save, and none of it had ever executed against a running Gen 2 game.

  THREE THINGS GEN 2 DOES DIFFERENTLY FROM GEN 1, each of which is a separate way to be
  quietly wrong:

  1. THE BOX STRUCT HAS NO HP FIELD. Gen 1's box_struct is 33 bytes with current HP at +0x01.
     Gen 2's is 32 bytes and ends at Level +0x1F, while the party keeps HP at +0x22 in the
     party-only tail. retrieveBoxMon read HP at HP_OFFSET off the box base regardless — which
     in Gen 2 is two bytes PAST the end of the slot, i.e. the NEXT boxed mon's move ids read
     as an HP value. This gate plants a recognisable pattern exactly there, so the assertion
     fails loudly if that read ever comes back.

     pret settles what should happen instead: SendGetMonIntoFromBox (move_mon.asm) clears
     MON_STATUS and copies MON_MAXHP into MON_HP on withdrawal. Gen 2 boxes cannot preserve
     HP, so the mon comes back full.

  2. SPECIAL IS SPLIT. SpclAtk +0x2C and SpclDef +0x2E are separate stats. The shared stat
     writer had one Special and aliased it, so a withdrawal would have written Sp.Atk over
     Sp.Def. The fixture is given DIFFERENT values for the two so an alias cannot pass.

  3. THE BOXES ARE NOT CHECKSUMMED. Gen 2 verifies a checksum on load, but it covers
     sGameData..sGameDataEnd only (save.asm SaveChecksum / VerifyChecksum) — the box banks
     are outside it. So the memorial write needs no checksum maintenance, and, unlike Gen 1,
     there is no EmptyAllSRAMBoxes to defend against: ChangeBoxSaveGame only does
     SaveBox/LoadBox, so there is nothing to protect against and this gate proves the
     memorial survives without any SRAM-box maintenance.

  Runs on tests/fixtures/gen2/crystal_town.SaveRAM.
  Result file: patch/build/test_gen2_writes_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gatelib.lua")
local t = G.start("test_gen2_writes_gate", {game = "gen2_crystal"})
local M = t.M
local fmt = string.format

local STRUCT = M.PARTY_STRUCT_SIZE      -- 48
local BOXLEN = M.BOX_STRUCT_SIZE        -- 32

-- ── Safe-state gate ──────────────────────────────────────────────────────────
-- Only the POSITIVE case is asserted live: staging a text box from a freshly booted save is
-- unreliable enough that a gate doing it would be testing the harness, not the code.
t.check("isInOverworld true while the player is walking around", M.isInOverworld() == true)
t.check("starting from a healthy mon", (M.readPartySlot(0) or {}).hp == 20)

-- Give the fixture's mon distinct Sp.Atk and Sp.Def BEFORE anything is cached. Equal values
-- cannot tell an aliased read from a real one, and the fixture writes 10 to both.
M.write_u16_be(M.PARTY_BASE_ADDR + 0x2C, 21)    -- SpclAtk
M.write_u16_be(M.PARTY_BASE_ADDR + 0x2E, 34)    -- SpclDef
local st0 = M.readPartyStats(0)
t.check("Sp.Atk and Sp.Def are independently readable",
        st0 and st0.spAtk == 21 and st0.spDef == 34,
        fmt("got spAtk=%s spDef=%s", tostring(st0 and st0.spAtk), tostring(st0 and st0.spDef)))

-- ── force_faint ──────────────────────────────────────────────────────────────
M.forceFaint(0)
local mon = M.readPartySlot(0)
t.check("forceFaint zeroes current HP", mon and mon.hp == 0,
        fmt("got %s", tostring(mon and mon.hp)))
t.check("forceFaint leaves maxHP intact", mon and mon.maxHP == 20,
        fmt("got %s", tostring(mon and mon.maxHP)))
t.check("the mon key survives a faint", mon and mon.key and #mon.key == 12,
        fmt("got %q", tostring(mon and mon.key)))

M.write_u16_be(M.PARTY_BASE_ADDR + 0x22, 20)    -- heal back to a known state
t.check("healed back to 20", (M.readPartySlot(0) or {}).hp == 20)

-- ── A second mon ─────────────────────────────────────────────────────────────
-- depositPartyMon refuses to box the LAST party mon (it would soft-lock the save), so clone
-- slot 0 and make the copy distinguishable: different DVs and level mean a wrong box offset
-- shows up as the WRONG mon rather than silently passing.
local function clone_slot0_into_slot1()
    for i = 0, STRUCT - 1 do
        M.write_u8(M.PARTY_BASE_ADDR + STRUCT + i, M.read_u8(M.PARTY_BASE_ADDR + i))
    end
    for i = 0, 10 do
        M.write_u8(M.PARTY_OT_NAMES_ADDR + 11 + i, M.read_u8(M.PARTY_OT_NAMES_ADDR + i))
        M.write_u8(M.PARTY_NICKS_ADDR + 11 + i, M.read_u8(M.PARTY_NICKS_ADDR + i))
    end
    local b1 = M.PARTY_BASE_ADDR + STRUCT
    M.write_u8(b1 + M.DV_OFFSET_1, 0xA5)
    M.write_u8(b1 + M.DV_OFFSET_2, 0x5A)
    M.write_u8(b1 + M.LEVEL_OFFSET, 9)
    M.write_u16_be(b1 + 0x2C, 44)               -- distinct Sp.Atk
    M.write_u16_be(b1 + 0x2E, 55)               -- distinct Sp.Def
    M.write_u8(M.PARTY_SPECIES_ADDR + 1, M.read_u8(M.PARTY_SPECIES_ADDR))
    M.write_u8(M.PARTY_SPECIES_ADDR + 2, 0xFF)
    M.write_u8(M.PARTY_COUNT_ADDR, 2)
end
clone_slot0_into_slot1()
t.check("party is 2 for the deposit test", M.getPartyCount() == 2)

local slot1 = M.readPartySlot(1)
local slot1_key = slot1 and slot1.key
local slot1_stats = M.readPartyStats(1)
t.check("the clone has its own key", slot1_key and slot1_key ~= (M.readPartySlot(0) or {}).key,
        fmt("slot0=%q slot1=%q", tostring((M.readPartySlot(0) or {}).key), tostring(slot1_key)))
t.check("the clone's cached stats keep Sp.Atk and Sp.Def apart",
        slot1_stats and slot1_stats.spAtk == 44 and slot1_stats.spDef == 55,
        fmt("got spAtk=%s spDef=%s",
            tostring(slot1_stats and slot1_stats.spAtk),
            tostring(slot1_stats and slot1_stats.spDef)))

-- ── Deposit ──────────────────────────────────────────────────────────────────
local before_box = M.getBoxCount()
local ok, err = M.depositPartyMon(1)
t.check("depositPartyMon(1) succeeds", ok, tostring(err))
t.check("box count went up", M.getBoxCount() == before_box + 1,
        fmt("got %d, was %d", M.getBoxCount(), before_box))
t.check("party count went down", M.getPartyCount() == 1, fmt("got %d", M.getPartyCount()))

-- The client's party_to_box detection only fires once it can FIND the mon in the box by key,
-- so a box read that produces a different key silently disables the whole feature.
local boxed = M.readBoxSlot(before_box)
t.check("the boxed mon reads back with the same key", boxed and boxed.key == slot1_key,
        fmt("box=%q party was %q", tostring(boxed and boxed.key), tostring(slot1_key)))
t.check("scanBoxForKey finds it", M.scanBoxForKey(slot1_key) == before_box,
        fmt("got %s", tostring(M.scanBoxForKey(slot1_key))))
-- No level assertion here: readBoxSlot does not expose one in ANY generation, and reading
-- BOX_LEVEL_OFFSET raw would only read back through the same constant depositPartyMon wrote
-- through. The property that matters is asserted end to end after the withdraw instead.
t.check("the nickname followed it into the box",
        M.readBoxNickname(before_box) == "TOTODILE",
        fmt("got %q", tostring(M.readBoxNickname(before_box))))

-- ── The HP trap ──────────────────────────────────────────────────────────────
-- Plant a recognisable pattern at exactly the address the OLD code read HP from: the box
-- base plus HP_OFFSET (0x22), which for a 32-byte box struct is +0x02 into the NEXT slot.
-- If that read ever comes back, HP is 0xDEAD instead of maxHP and this fails.
local trap_addr = M.BOX_BASE_ADDR + before_box * BOXLEN + M.HP_OFFSET
t.check("HP_OFFSET really does fall outside the Gen 2 box struct",
        M.HP_OFFSET + 2 > BOXLEN,
        fmt("HP_OFFSET=%#x box_struct=%d — if this is false the trap below proves nothing",
            M.HP_OFFSET, BOXLEN))
M.box_write_u16_be(trap_addr, 0xDEAD)

-- ── Withdraw ─────────────────────────────────────────────────────────────────
local ok2, err2 = M.retrieveBoxMon(slot1_key, slot1_stats)
t.check("retrieveBoxMon succeeds with the cached stats", ok2, tostring(err2))
t.check("party count went back up", M.getPartyCount() == 2, fmt("got %d", M.getPartyCount()))
t.check("box count went back down", M.getBoxCount() == before_box,
        fmt("got %d", M.getBoxCount()))

local back = M.readPartySlot(1)
t.check("the withdrawn mon has the original key", back and back.key == slot1_key,
        fmt("got %q", tostring(back and back.key)))
t.check("level survived the round trip", back and back.level == 9,
        fmt("got %s", tostring(back and back.level)))
t.check("HP is maxHP, as pret's SendGetMonIntoFromBox does",
        back and back.hp == back.maxHP and back.maxHP == 20,
        fmt("got %s/%s", tostring(back and back.hp), tostring(back and back.maxHP)))
t.check("HP did NOT come from two bytes into the next box slot",
        back and back.hp ~= 0xDEAD, fmt("got %s", tostring(back and back.hp)))
t.check("status is clear on withdrawal", back and back.status_cond == 0,
        fmt("got %s", tostring(back and back.status_cond)))
t.check("the nickname came back", M.readPartyNickname(1) == "TOTODILE",
        fmt("got %q", tostring(M.readPartyNickname(1))))

local back_stats = M.readPartyStats(1)
t.check("Attack and Defense were restored",
        back_stats and back_stats.attack == 11 and back_stats.defense == 11,
        fmt("got atk=%s def=%s", tostring(back_stats and back_stats.attack),
            tostring(back_stats and back_stats.defense)))
t.check("Sp.Atk came back as 44, not aliased",
        back_stats and back_stats.spAtk == 44, fmt("got %s", tostring(back_stats and back_stats.spAtk)))
t.check("Sp.Def came back as 55, NOT overwritten by Sp.Atk",
        back_stats and back_stats.spDef == 55,
        fmt("got %s — an aliased writer leaves 44 here", tostring(back_stats and back_stats.spDef)))

-- Refusing a withdraw with no cached stats matters more than it sounds: the box carries 32
-- of the 48 bytes, so improvising would hand back a mon with zeroed Attack and Defense.
-- Clear the cache AFTER the deposit, never before: depositPartyMon REPOPULATES it with
-- readPartyStats, so a pre-emptive clear leaves the fallback intact and the withdraw
-- succeeds — which is exactly how this assertion passed vacuously on the first run.
M.depositPartyMon(1)
M._party_tail_cache = {}
local ok3, err3 = M.retrieveBoxMon(slot1_key, nil)
t.check("retrieveBoxMon REFUSES when it has no stats to restore", ok3 == false,
        tostring(err3))
t.check("the refusal leaves the mon in the box", M.getBoxCount() == before_box + 1,
        fmt("got %d", M.getBoxCount()))
t.check("the refusal leaves no half-written mon in the party",
        M.getPartyCount() == 1, fmt("got %d", M.getPartyCount()))
M.retrieveBoxMon(slot1_key, slot1_stats)   -- put it back for the memorial test

-- ── Memorial box ─────────────────────────────────────────────────────────────
-- Box 14 (sBox14, flat CartRAM 0x79E0) is where dead pairs are buried. Verified against
-- pret's `box` macro: count +0, species +1 (21 bytes), mons +22, OTs +662, nicks +882.
t.check("the memorial box starts empty", M.getMemorialBoxCount() == 0,
        fmt("got %d", M.getMemorialBoxCount()))
local mem_key = (M.readPartySlot(1) or {}).key
local ok4, err4 = M.depositMemorialMon(1)
t.check("depositMemorialMon succeeds", ok4, tostring(err4))
t.check("the memorial box now holds one", M.getMemorialBoxCount() == 1,
        fmt("got %d", M.getMemorialBoxCount()))
t.check("it left the party", M.getPartyCount() == 1, fmt("got %d", M.getPartyCount()))
t.check("it did NOT land in the active box", M.getBoxCount() == before_box,
        fmt("got %d — the memorial went to the wrong SRAM offset", M.getBoxCount()))

local buried = M.readMemorialBoxSlot(0)
t.check("the buried mon reads back", buried ~= nil)
t.check("with the same key", buried and buried.key == mem_key,
        fmt("got %q want %q", tostring(buried and buried.key), tostring(mem_key)))
t.check("and its nickname, decoded from SRAM", buried and buried.nickname == "TOTODILE",
        fmt("got %q", tostring(buried and buried.nickname)))

t.finish(fmt("variant=%s", t.variant))
