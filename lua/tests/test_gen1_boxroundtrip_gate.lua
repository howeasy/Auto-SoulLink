--[[
  lua/tests/test_gen1_boxroundtrip_gate.lua — headless: does M.retrieveBoxMon give the mon back?

  THE UNTESTED PATH. test_gen1_writes_gate covers the DEPOSIT half (party -> box) and stops
  there. The WITHDRAW half has never executed on a cartridge, and it is the riskiest code in
  the Gen 1 client: it rebuilds a 44-byte party struct out of a 33-byte box struct plus a
  stat block the SERVER hands back, and writes those integers into WRAM unvalidated. If it
  is wrong, a Soul Link party-sync silently returns a bricked mon.

  WHAT THE GAME DOES, so this gate asserts the same invariants
  ------------------------------------------------------------
  pokered's PC withdraw is BillsPCWithdraw -> MoveMon(BOX_TO_PARTY) -> RemovePokemon:

    .cache/pret/pokered/engine/pokemon/bills_pc.asm:253-289   BillsPCWithdraw
    .cache/pret/pokered/engine/pokemon/add_mon.asm:341-505    _MoveMon
    .cache/pret/pokered/engine/pokemon/remove_mon.asm:1-100   _RemovePokemon
    .cache/pret/pokered/home/move_mon.asm:33-47               CalcStats
    .cache/pret/pokered/macros/ram.asm:7-36                   box_struct / party_struct

  _MoveMon copies BOXMON_STRUCT_LENGTH (33) bytes verbatim (add_mon.asm:409-412), copies the
  OT name and the nickname out of the parallel 11-byte arrays (add_mon.asm:426-486), and then
  — for BOX_TO_PARTY only — recomputes the party tail (add_mon.asm:487-504):

      Level  = CalcLevelFromExperience(Exp)        ; NOT the stored BoxLevel
      MaxHP/Attack/Defense/Speed/Special = CalcStats(DVs, StatExp, Level)

  Nothing else is touched: current HP, Status, Type1/2, CatchRate, Moves, OTID, Exp, StatExp,
  DVs and PP all ride along inside the 33 bytes.

  So a game deposit -> withdraw is byte-for-byte IDENTITY on the 44-byte party struct, with
  exactly one exception: BoxLevel (+0x03) is refreshed from the live Level on the way IN
  (add_mon.asm:420-426), so a mon that levelled up since it was caught comes back with
  +0x03 == Level rather than its stale catch-time value.

  Level and the stats survive the game's round trip because Exp, DVs and StatExp are all
  unchanged while boxed — CalcLevelFromExperience and CalcStats are pure functions of bytes
  the box preserves. SLink replays the cached values instead of reimplementing RBY's stat
  formula (which would also need a base-stat table it does not ship); that is the SAME
  ANSWER, so byte identity is the correct expectation for SLink too. This gate asserts it.

  WHY A SINGLE-INSTANCE GATE. retrieveBoxMon is pure RAM manipulation with no server round
  trip inside it. The deferred-command plumbing that reaches it (pending_sync_cmds, the
  safe-state gate) is the SAME queue already driven end-to-end by the two-instance
  scenario_gen1_boxsync — which exercises box_mon and stops before party_mon. Nothing here
  needs a partner, so this stays cheap.

  Runs on tests/fixtures/gen1/<rom>_town.SaveRAM.
  Result file: patch/build/test_gen1_boxroundtrip_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_boxroundtrip_gate")
local M = t.M
local fmt = string.format

local STRUCT = M.PARTY_STRUCT_SIZE   -- 44
local BOXLEN = M.BOX_STRUCT_SIZE     -- 33
local NAME   = 11
local POISON = 0xA5

-- pret party_struct field names, so a failure says "Speed.lo" and not "byte 41".
-- macros/ram.asm:7-36.
local FIELD = {
    [0x00] = "Species",    [0x01] = "HP.hi",      [0x02] = "HP.lo",     [0x03] = "BoxLevel",
    [0x04] = "Status",     [0x05] = "Type1",      [0x06] = "Type2",     [0x07] = "CatchRate",
    [0x08] = "Move1",      [0x09] = "Move2",      [0x0A] = "Move3",     [0x0B] = "Move4",
    [0x0C] = "OTID.hi",    [0x0D] = "OTID.lo",
    [0x0E] = "Exp.0",      [0x0F] = "Exp.1",      [0x10] = "Exp.2",
    [0x11] = "HPExp.hi",   [0x12] = "HPExp.lo",   [0x13] = "AtkExp.hi", [0x14] = "AtkExp.lo",
    [0x15] = "DefExp.hi",  [0x16] = "DefExp.lo",  [0x17] = "SpdExp.hi", [0x18] = "SpdExp.lo",
    [0x19] = "SpcExp.hi",  [0x1A] = "SpcExp.lo",
    [0x1B] = "DVs.AtkDef", [0x1C] = "DVs.SpdSpc",
    [0x1D] = "PP1",        [0x1E] = "PP2",        [0x1F] = "PP3",       [0x20] = "PP4",
    [0x21] = "Level",      [0x22] = "MaxHP.hi",   [0x23] = "MaxHP.lo",
    [0x24] = "Attack.hi",  [0x25] = "Attack.lo",  [0x26] = "Defense.hi",[0x27] = "Defense.lo",
    [0x28] = "Speed.hi",   [0x29] = "Speed.lo",   [0x2A] = "Special.hi",[0x2B] = "Special.lo",
}

-- ── snapshot / compare helpers ───────────────────────────────────────────────

local function snap_party(slot)
    local base = M.PARTY_BASE_ADDR + slot * STRUCT
    local s = {struct = {}, ot = {}, nick = {}, slot = slot}
    for i = 0, STRUCT - 1 do s.struct[i] = M.read_u8(base + i) end
    for i = 0, NAME - 1 do
        s.ot[i]   = M.read_u8(M.PARTY_OT_NAMES_ADDR + slot * NAME + i)
        s.nick[i] = M.read_u8(M.PARTY_NICKS_ADDR   + slot * NAME + i)
    end
    s.key = M.monKey(base)
    s.level = s.struct[0x21]
    return s
end

local function snap_box(slot)
    local base = M.BOX_BASE_ADDR + slot * BOXLEN
    local s = {struct = {}, ot = {}, nick = {}, slot = slot}
    for i = 0, BOXLEN - 1 do s.struct[i] = M.box_read_u8(base + i) end
    for i = 0, NAME - 1 do
        s.ot[i]   = M.box_read_u8(M.BOX_OT_NAMES_ADDR + slot * NAME + i)
        s.nick[i] = M.box_read_u8(M.BOX_NICKS_ADDR   + slot * NAME + i)
    end
    s.key = string.format("%02X%02X:%04X:%02X",
                          s.struct[M.DV_OFFSET_1], s.struct[M.DV_OFFSET_2],
                          s.struct[M.OTID_OFFSET] * 256 + s.struct[M.OTID_OFFSET + 1],
                          s.struct[M.SPECIES_OFFSET])
    return s
end

-- Returns nil when every byte matches, else a string naming EVERY mismatch.
-- `expect` overrides individual struct offsets (used for BoxLevel, see the header).
-- `upto` limits the struct compare (33 for a box snapshot, 44 for a party one).
local function diff(want, got, expect, upto)
    upto = upto or STRUCT
    local bad = {}
    for i = 0, upto - 1 do
        local w = (expect and expect[i]) or want.struct[i]
        if got.struct[i] ~= w then
            bad[#bad + 1] = fmt("%s(+0x%02X) %02X->%02X", FIELD[i] or "?", i, w, got.struct[i])
        end
    end
    for i = 0, NAME - 1 do
        if got.ot[i] ~= want.ot[i] then
            bad[#bad + 1] = fmt("OT[%d] %02X->%02X", i, want.ot[i], got.ot[i])
        end
        if got.nick[i] ~= want.nick[i] then
            bad[#bad + 1] = fmt("Nick[%d] %02X->%02X", i, want.nick[i], got.nick[i])
        end
    end
    if #bad == 0 then return nil end
    return table.concat(bad, ", ")
end

local function find_party_slot(key)
    for s = 0, M.getPartyCount() - 1 do
        local mon = M.readPartySlot(s)
        if mon and mon.key == key then return s end
    end
    return nil
end

-- Fill the slot retrieveBoxMon is about to land in with a byte that cannot be mistaken for
-- real data, so a field it FAILS to write shows up as 0xA5 instead of leftover-correct
-- bytes from an earlier phase. Without this the whole gate could pass on stale WRAM.
local function poison_party_slot(slot)
    local base = M.PARTY_BASE_ADDR + slot * STRUCT
    for i = 0, STRUCT - 1 do M.write_u8(base + i, POISON) end
    for i = 0, NAME - 1 do
        M.write_u8(M.PARTY_OT_NAMES_ADDR + slot * NAME + i, POISON)
        M.write_u8(M.PARTY_NICKS_ADDR   + slot * NAME + i, POISON)
    end
end

-- ── the comparator's own known-positive control ──────────────────────────────
-- "Verify the probe first": a diff() that always returns nil would make every check below
-- green. Prove it can see a single flipped byte before trusting it.
do
    local a = snap_party(0)
    local b = snap_party(0)
    t.check("diff() reports nothing when two identical snapshots are compared",
            diff(a, b) == nil)
    b.struct[0x29] = (b.struct[0x29] + 1) % 256   -- Speed.lo
    local d = diff(a, b)
    t.check("diff() catches a one-byte change (comparator is not blind)",
            d ~= nil and d:find("Speed.lo") ~= nil, tostring(d))
    b = snap_party(0)
    b.nick[3] = (b.nick[3] + 1) % 256
    t.check("diff() catches a nickname byte too", diff(a, b) ~= nil)
end

local box0 = M.getBoxCount()
t.check("the fixture's box count is sane before we touch anything",
        box0 >= 0 and box0 <= M.BOX_MAX_MONS, fmt("wBoxCount = %d", box0))
t.check("the fixture has exactly one mon to start from", M.getPartyCount() == 1,
        fmt("party = %d", M.getPartyCount()))

-- ── setup: two fillers ───────────────────────────────────────────────────────
-- depositPartyMon refuses to box the LAST party mon, and phase 3 needs two mons in the box
-- at once, so clone slot 0 twice. The clones get different DVs and levels — otherwise all
-- three share one monKey and scanBoxForKey could match the wrong struct and still "pass".
-- Slot 0 stays PRISTINE: phase 1 has to round-trip bytes the GAME wrote, not bytes we did.
do
    for n = 1, 2 do
        for i = 0, STRUCT - 1 do
            M.write_u8(M.PARTY_BASE_ADDR + n * STRUCT + i, M.read_u8(M.PARTY_BASE_ADDR + i))
        end
        for i = 0, NAME - 1 do
            M.write_u8(M.PARTY_OT_NAMES_ADDR + n * NAME + i,
                       M.read_u8(M.PARTY_OT_NAMES_ADDR + i))
            M.write_u8(M.PARTY_NICKS_ADDR + n * NAME + i,
                       M.read_u8(M.PARTY_NICKS_ADDR + i))
        end
        M.write_u8(M.PARTY_SPECIES_ADDR + n, M.read_u8(M.PARTY_SPECIES_ADDR))
    end
    local a, b = M.PARTY_BASE_ADDR + STRUCT, M.PARTY_BASE_ADDR + 2 * STRUCT
    M.write_u8(a + 0x1B, 0x77); M.write_u8(a + 0x1C, 0x11); M.write_u8(a + 0x21, 9)
    M.write_u8(b + 0x1B, 0x33); M.write_u8(b + 0x1C, 0x44); M.write_u8(b + 0x21, 12)
    M.write_u8(M.PARTY_SPECIES_ADDR + 3, 0xFF)
    M.write_u8(M.PARTY_COUNT_ADDR, 3)
end
t.check("party topped up to 3 (real + two fillers)", M.getPartyCount() == 3,
        fmt("got %d", M.getPartyCount()))

local real_key   = snap_party(0).key
local fillerA_key = snap_party(1).key
local fillerB_key = snap_party(2).key
t.check("the three mons have three distinct keys",
        real_key ~= fillerA_key and real_key ~= fillerB_key and fillerA_key ~= fillerB_key,
        fmt("%s / %s / %s", real_key, fillerA_key, fillerB_key))

-- ═════════════════════════════════════════════════════════════════════════════
-- PHASE 1 — pristine mon, in-process cache
-- The bytes under test are the ones the GAME wrote into the battery save. If the
-- round trip mangles a real starter, everything after this is moot.
-- ═════════════════════════════════════════════════════════════════════════════
t.log("── phase 1: pristine round trip (deposit-time cache) ──")
do
    local before = snap_party(0)
    local ok, err = M.depositPartyMon(0)
    t.check("depositPartyMon(0) succeeds", ok, tostring(err))
    t.check("the mon really left the party", find_party_slot(real_key) == nil,
            "if it is still there, the withdraw below proves nothing")
    t.check("the box holds it", M.getBoxCount() == box0 + 1, fmt("box = %d", M.getBoxCount()))
    t.check("the box copy carries the same key", snap_box(box0).key == real_key,
            fmt("box key %s vs party key %s", snap_box(box0).key, real_key))

    poison_party_slot(M.getPartyCount())
    local rok, rerr = M.retrieveBoxMon(real_key)      -- stats=nil -> _party_tail_cache
    t.check("retrieveBoxMon succeeds with the deposit-time cache", rok, tostring(rerr))

    local slot = find_party_slot(real_key)
    t.check("the mon is back in the party and still keyed the same", slot ~= nil,
            "a changed key unlinks the Soul Link pair permanently")
    t.check("party count went back up", M.getPartyCount() == 3, fmt("got %d", M.getPartyCount()))
    t.check("the box gave it up", M.getBoxCount() == box0, fmt("box = %d", M.getBoxCount()))

    if slot then
        local after = snap_party(slot)
        -- +0x03 is the ONE byte pokered does not preserve: _MoveMon refreshes BoxLevel from
        -- the live Level on the way in (add_mon.asm:420-426), so it comes back as Level.
        local d = diff(before, after, {[0x03] = before.level})
        t.check("all 44 struct bytes + OT + nickname survived the round trip", d == nil,
                tostring(d))
        t.check("no poison byte survived anywhere in the slot",
                (function()
                    for i = 0, STRUCT - 1 do
                        if after.struct[i] == POISON and before.struct[i] ~= POISON then
                            return false
                        end
                    end
                    return true
                end)(), "a 0xA5 means retrieveBoxMon never wrote that field")
        t.log(fmt("   nick=%q OT=%q level=%d maxHP=%d",
                  M.readPartyNickname(slot), M.readPartyOTName(slot),
                  after.struct[0x21], after.struct[0x22] * 256 + after.struct[0x23]))
    end
end

-- ═════════════════════════════════════════════════════════════════════════════
-- PHASE 2 — every field distinct, and the SERVER-supplied stat block
-- The fixture starter's Atk/Def/Spd/Spc are all within a couple of points of each other at
-- L5, so a bug that wrote Speed into Defense would sail through phase 1. Stamp values that
-- are pairwise distinct, then feed the stats through the production path: the `stats`
-- ARGUMENT (server mon_stats echoed in the party_mon command), with the in-process cache
-- deliberately emptied so it cannot silently cover for a broken argument path.
-- ═════════════════════════════════════════════════════════════════════════════
t.log("── phase 2: distinct fields + server-supplied stats ──")
do
    local slot = find_party_slot(real_key)
    if not slot then t.check("phase 2 needs the mon from phase 1", false); t.finish("aborted") end
    local base = M.PARTY_BASE_ADDR + slot * STRUCT

    -- Species / OTID / DVs are left alone: they ARE the key.
    M.write_u8(base + 0x03, 0x63)                       -- deliberately stale BoxLevel (99)
    M.write_u8(base + 0x04, 0x08)                       -- Status: poisoned (PSN, bit 3)
    M.write_u8(base + 0x05, 0x15); M.write_u8(base + 0x06, 0x16)   -- Type1 / Type2
    M.write_u8(base + 0x07, 0x2D)                       -- CatchRate
    for i = 0, 3 do M.write_u8(base + 0x08 + i, 0x21 + i) end       -- Moves 33..36
    M.write_u8(base + 0x0E, 0x00); M.write_u8(base + 0x0F, 0x12)
    M.write_u8(base + 0x10, 0x34)                                   -- Exp
    for i = 0, 9 do M.write_u8(base + 0x11 + i, 0x11 + i) end       -- StatExp, 10 distinct
    for i = 0, 3 do M.write_u8(base + 0x1D + i, 0x05 + 5 * i) end   -- PP 5/10/15/20
    M.write_u16_be(base + 0x01, 42)                                 -- current HP
    M.write_u8(base + 0x21, 23)                                     -- Level
    M.write_u16_be(base + 0x22, 89)                                 -- MaxHP
    M.write_u16_be(base + 0x24, 31)                                 -- Attack
    M.write_u16_be(base + 0x26, 41)                                 -- Defense
    M.write_u16_be(base + 0x28, 51)                                 -- Speed
    M.write_u16_be(base + 0x2A, 61)                                 -- Special
    for i = 0, 4 do                                                 -- nick "ABCDE@"
        M.write_u8(M.PARTY_NICKS_ADDR + slot * NAME + i, 0x80 + i)
        M.write_u8(M.PARTY_OT_NAMES_ADDR + slot * NAME + i, 0x85 + i)
    end
    M.write_u8(M.PARTY_NICKS_ADDR + slot * NAME + 5, 0x50)
    M.write_u8(M.PARTY_OT_NAMES_ADDR + slot * NAME + 5, 0x50)

    local before = snap_party(slot)
    -- What the client sends the server as `stats_cache` at deposit time and what the server
    -- echoes back in party_mon. Captured through the production reader, not hand-built.
    local server_stats = M.readPartyStats(slot)
    t.check("readPartyStats captured the tail the box cannot hold",
            server_stats ~= nil and server_stats.level == 23 and server_stats.maxHP == 89
            and server_stats.attack == 31 and server_stats.defense == 41
            and server_stats.speed == 51 and server_stats.spAtk == 61,
            server_stats and fmt("lv=%d hp=%d a=%d d=%d s=%d sp=%d", server_stats.level,
                                 server_stats.maxHP, server_stats.attack, server_stats.defense,
                                 server_stats.speed, server_stats.spAtk) or "nil")

    local ok, err = M.depositPartyMon(slot)
    t.check("deposit of the stamped mon succeeds", ok, tostring(err))

    -- The box struct stops at 33 bytes, so the stamped tail is gone. Prove it, or the
    -- "stats restored" check below is measuring nothing.
    local boxed = snap_box(M.getBoxCount() - 1)
    t.check("the box really dropped the party tail (level/maxHP/stats are not in the box)",
            boxed.struct[0x21] == nil,
            "box struct is 33 bytes; +0x21 onward does not exist, so the tail MUST be "
            .. "restored from the cache and cannot be smuggled through")
    t.check("deposit refreshed BoxLevel from the live Level (add_mon.asm:420-426)",
            boxed.struct[0x03] == 23, fmt("box +0x03 = %d, want 23", boxed.struct[0x03]))

    M._party_tail_cache = {}       -- force the `stats` ARGUMENT path
    poison_party_slot(M.getPartyCount())
    local rok, rerr = M.retrieveBoxMon(real_key, server_stats)
    t.check("retrieveBoxMon succeeds with a server-supplied stat block", rok, tostring(rerr))

    local back = find_party_slot(real_key)
    t.check("the stamped mon is back", back ~= nil)
    if back then
        local after = snap_party(back)
        local d = diff(before, after, {[0x03] = 23})
        t.check("every distinct field came back in its own place", d == nil, tostring(d))
        -- Spelled out separately so a failure names the concept, not just an offset.
        t.check("Level restored from the server block", after.struct[0x21] == 23)
        t.check("MaxHP restored (not clobbered with current HP)",
                after.struct[0x22] * 256 + after.struct[0x23] == 89,
                fmt("got %d, current HP is %d",
                    after.struct[0x22] * 256 + after.struct[0x23],
                    after.struct[0x01] * 256 + after.struct[0x02]))
        t.check("Attack/Defense/Speed/Special are not swapped",
                after.struct[0x25] == 31 and after.struct[0x27] == 41
                and after.struct[0x29] == 51 and after.struct[0x2B] == 61,
                fmt("%d/%d/%d/%d", after.struct[0x25], after.struct[0x27],
                    after.struct[0x29], after.struct[0x2B]))
        t.check("current HP rode along inside the box struct",
                after.struct[0x01] * 256 + after.struct[0x02] == 42)
        t.check("Status survived (a poisoned mon must still be poisoned)",
                after.struct[0x04] == 0x08, fmt("got %#04x", after.struct[0x04]))
        t.check("all four moves survived",
                after.struct[0x08] == 0x21 and after.struct[0x09] == 0x22
                and after.struct[0x0A] == 0x23 and after.struct[0x0B] == 0x24)
        t.check("all four PP counters survived",
                after.struct[0x1D] == 5 and after.struct[0x1E] == 10
                and after.struct[0x1F] == 15 and after.struct[0x20] == 20,
                fmt("%d/%d/%d/%d", after.struct[0x1D], after.struct[0x1E],
                    after.struct[0x1F], after.struct[0x20]))
        t.check("Exp survived — pokered derives Level from it (add_mon.asm:497-500), so a "
                .. "lost Exp means the next level-up snaps the mon back",
                after.struct[0x0E] == 0x00 and after.struct[0x0F] == 0x12
                and after.struct[0x10] == 0x34)
        t.check("StatExp survived — CalcStats reads it (home/move_mon.asm:49-90)",
                (function()
                    for i = 0, 9 do
                        if after.struct[0x11 + i] ~= 0x11 + i then return false end
                    end
                    return true
                end)())
        t.check("nickname decoded back to ABCDE", M.readPartyNickname(back) == "ABCDE",
                fmt("got %q", M.readPartyNickname(back)))
        t.check("OT name survived", M.readPartyOTName(back) == "FGHIJ",
                fmt("got %q", M.readPartyOTName(back)))
    end
end

-- ═════════════════════════════════════════════════════════════════════════════
-- PHASE 3 — the box shift, with TWO mons in the box
-- Step 6 of retrieveBoxMon slides every box slot after the withdrawn one down by 33 bytes
-- and rebuilds the species list. Phases 1-2 always withdrew the only mon in the box, so the
-- loop never ran. This is where an off-by-one duplicates or eats the survivor.
-- ═════════════════════════════════════════════════════════════════════════════
t.log("── phase 3: withdrawing from the middle shifts the rest ──")
do
    local sA = find_party_slot(fillerA_key)
    t.check("filler A is in the party", sA ~= nil)
    if sA then t.check("deposit filler A", M.depositPartyMon(sA)) end
    local sB = find_party_slot(fillerB_key)
    t.check("filler B is in the party", sB ~= nil)
    if sB then t.check("deposit filler B", M.depositPartyMon(sB)) end
    t.check("the box now holds two mons", M.getBoxCount() == box0 + 2,
            fmt("box = %d", M.getBoxCount()))

    local slotA, slotB
    for i = 0, M.getBoxCount() - 1 do
        local k = snap_box(i).key
        if k == fillerA_key then slotA = i elseif k == fillerB_key then slotB = i end
    end
    t.check("both fillers are findable in the box by key", slotA ~= nil and slotB ~= nil,
            fmt("A=%s B=%s", tostring(slotA), tostring(slotB)))
    t.check("filler A is the EARLIER box slot, so the shift loop will actually run",
            slotA ~= nil and slotB ~= nil and slotA < slotB,
            fmt("A=%s B=%s", tostring(slotA), tostring(slotB)))

    local survivor = slotB and snap_box(slotB)
    poison_party_slot(M.getPartyCount())
    local ok, err = M.retrieveBoxMon(fillerA_key)
    t.check("retrieveBoxMon pulls the FIRST of two boxed mons", ok, tostring(err))
    t.check("filler A is in the party", find_party_slot(fillerA_key) ~= nil)
    t.check("the box is down to one", M.getBoxCount() == box0 + 1,
            fmt("box = %d", M.getBoxCount()))

    if survivor then
        local moved = snap_box(box0)
        t.check("the survivor shifted down into the vacated slot, intact",
                diff(survivor, moved, nil, BOXLEN) == nil,
                tostring(diff(survivor, moved, nil, BOXLEN)))
        t.check("the survivor kept its own key (not filler A's)", moved.key == fillerB_key,
                fmt("got %s, want %s", moved.key, fillerB_key))
        t.check("the box species list was rebuilt and terminated",
                M.box_read_u8(M.BOX_SPECIES_ADDR + box0) == moved.struct[0x00]
                and M.box_read_u8(M.BOX_SPECIES_ADDR + box0 + 1) == 0xFF,
                fmt("species[%d]=%02X term=%02X", box0,
                    M.box_read_u8(M.BOX_SPECIES_ADDR + box0),
                    M.box_read_u8(M.BOX_SPECIES_ADDR + box0 + 1)))
        local tail_base = M.BOX_BASE_ADDR + (box0 + 1) * BOXLEN
        local zeroed = true
        for i = 0, BOXLEN - 1 do
            if M.box_read_u8(tail_base + i) ~= 0 then zeroed = false break end
        end
        t.check("the vacated tail slot was zeroed, leaving no ghost copy", zeroed,
                "a leftover struct there reads back as a duplicate mon")
    end
end

-- ═════════════════════════════════════════════════════════════════════════════
-- PHASE 4 — no cache: REFUSE, do not improvise
-- This phase pinned the opposite behaviour when it was written, and it was right to: the old
-- code returned a mon with maxHP = current HP and Atk/Def/Spd/Spc left at ZERO, because step 1
-- zeroes all 44 bytes and the box only carries 33 of them. A player who restarted the client
-- and withdrew got a Pokemon that could not fight — silently, permanently, and with nothing
-- left in the box to restore from.
--
-- retrieveBoxMon now refuses instead. The client turns `false` into sync_retrieve_failed, so
-- the server learns the withdraw did not happen and the pair stays consistent.
--
-- The last check is the known-positive control: supplying stats must make the SAME withdraw
-- succeed. Without it this phase would also pass if retrieveBoxMon were broken outright.
-- ═════════════════════════════════════════════════════════════════════════════
t.log("── phase 4: no cache -> refuse rather than corrupt ──")
do
    local slot = find_party_slot(real_key)
    t.check("the real mon is available for the fallback test", slot ~= nil)
    if slot then
        local before = snap_party(slot)
        -- Capture the real stat block BEFORE depositing: snap_party carries raw struct bytes,
        -- not a stats table, and the control below needs something retrieveBoxMon will accept.
        local real_stats = M.readPartyStats(slot)
        t.check("captured a stat block for the control", real_stats ~= nil)
        t.check("deposit for the fallback test", M.depositPartyMon(slot))
        local box_after_deposit = M.getBoxCount()
        local party_after_deposit = M.getPartyCount()
        M._party_tail_cache = {}                 -- nothing cached anywhere
        poison_party_slot(party_after_deposit)

        local ok, err = M.retrieveBoxMon(real_key, nil)
        t.check("retrieveBoxMon REFUSES when it has no stats", ok == false,
                fmt("returned %s (%s)", tostring(ok), tostring(err)))
        t.check("...and says why", type(err) == "string" and #err > 0, tostring(err))

        -- Nothing may have moved. A refusal that half-completes is worse than one that
        -- corrupts, because the count is bumped over a poisoned struct.
        t.check("the party count did not change", M.getPartyCount() == party_after_deposit,
                fmt("%d -> %d", party_after_deposit, M.getPartyCount()))
        t.check("the mon is NOT in the party", find_party_slot(real_key) == nil)
        t.check("the mon is still safe in the box", M.getBoxCount() == box_after_deposit,
                fmt("box %d -> %d", box_after_deposit, M.getBoxCount()))

        -- No half-written mon left behind: the refusal zeroes the slot it was building in,
        -- so the poison bytes must be gone rather than partially overwritten.
        local landing = M.PARTY_BASE_ADDR + party_after_deposit * M.PARTY_STRUCT_SIZE
        local nonzero = 0
        for i = 0, M.PARTY_STRUCT_SIZE - 1 do
            if M.read_u8(landing + i) ~= 0 then nonzero = nonzero + 1 end
        end
        t.check("the landing slot was left clean, not half-written", nonzero == 0,
                fmt("%d of %d bytes non-zero", nonzero, M.PARTY_STRUCT_SIZE))

        -- KNOWN-POSITIVE CONTROL: the same withdraw, with stats, must work.
        local rok, rerr = M.retrieveBoxMon(real_key, real_stats)
        t.check("the SAME withdraw succeeds once stats are supplied", rok, tostring(rerr))
        local back = find_party_slot(real_key)
        t.check("and the mon comes back intact", back ~= nil
                and diff(before, snap_party(back), nil, BOXLEN) == nil,
                back and tostring(diff(before, snap_party(back), nil, BOXLEN)) or "not found")
    end
end

-- ═════════════════════════════════════════════════════════════════════════════
-- PHASE 5 — hostile server integers
-- applyPartyStats writes stats.level with an unmasked write_u8 and the rest through
-- write_u16_be. The server is the only source of that table, but "the server is trusted"
-- is not the same as "the client survives a bad one". The bar here is deliberately low and
-- absolute: no Lua error may escape into the client's frame callback, and the party must
-- still be coherent afterwards. A thrown error would abort retrieveBoxMon mid-rebuild and
-- leave a half-written party struct with the count already bumped.
-- ═════════════════════════════════════════════════════════════════════════════
t.log("── phase 5: garbage stat block must not corrupt the party ──")
do
    local slot = find_party_slot(real_key)
    if slot then
        t.check("deposit for the hostile-input test", M.depositPartyMon(slot))
        M._party_tail_cache = {}
        local landing = M.getPartyCount()
        poison_party_slot(landing)
        -- Every value here is reachable from JSON the server could plausibly emit: an
        -- out-of-u8 level, an out-of-u16 maxHP, a negative, a huge one, and a FLOAT (Python
        -- serialises 89.0, and Lua keeps it a float — mem_w8 wants an integer).
        local ok, res = pcall(M.retrieveBoxMon, real_key,
                              {level = 999, maxHP = 70000, attack = -1,
                               defense = 2 ^ 20, speed = 89.0})
        t.check("retrieveBoxMon does not throw on an out-of-range stat block", ok,
                tostring(res) .. " — an uncaught error here kills the client's frame handler")
        local pc = M.getPartyCount()
        t.check("party count stayed in range", pc >= 1 and pc <= 6, fmt("got %d", pc))
        t.check("the party species list is still terminated",
                M.read_u8(M.PARTY_SPECIES_ADDR + pc) == 0xFF,
                fmt("species[%d] = %#04x", pc, M.read_u8(M.PARTY_SPECIES_ADDR + pc)))
        t.check("the mon is still identifiable by key (identity is not derived from stats)",
                find_party_slot(real_key) ~= nil)
        -- Repair before the liveness walk: a level-231 mon with a 0-byte maxHP is not
        -- something to hand back to the engine.
        local back = find_party_slot(real_key)
        if back then
            local b = M.PARTY_BASE_ADDR + back * STRUCT
            M.write_u8(b + 0x21, 23)
            M.write_u16_be(b + 0x22, 89)
            M.write_u16_be(b + 0x01, 42)
        end
    end
end

-- ═════════════════════════════════════════════════════════════════════════════
-- PHASE 6 — the engine is still running
-- Everything above reads back SLink's own writes. That proves self-consistency, not that
-- the cartridge accepts the result. Walking is the one liveness probe that cannot be faked
-- (gen1_gatelib leans on the same fact at boot): if the coordinates move, the overworld
-- loop is still executing over the party we just rewrote.
-- ═════════════════════════════════════════════════════════════════════════════
t.log("── phase 6: the game still runs on the rebuilt party ──")
do
    local x_addr, y_addr = M.MAP_ID_ADDR + 4, M.MAP_ID_ADDR + 3
    local x0, y0 = M.read_u8(x_addr), M.read_u8(y_addr)
    local before_count = M.getPartyCount()
    local moved = false
    for i = 1, 8 do
        t.hold(({"Right", "Left"})[(i % 2) + 1], 24, function()
            return M.read_u8(x_addr) ~= x0 or M.read_u8(y_addr) ~= y0
        end)
        if M.read_u8(x_addr) ~= x0 or M.read_u8(y_addr) ~= y0 then moved = true break end
    end
    t.check("the player still walks after the party was rebuilt from the box", moved,
            fmt("at %d,%d (was %d,%d) — a corrupt party struct can hang the overworld loop",
                M.read_u8(x_addr), M.read_u8(y_addr), x0, y0))
    t.check("the party count did not drift while the game ran",
            M.getPartyCount() == before_count,
            fmt("%d -> %d", before_count, M.getPartyCount()))
    t.check("the withdrawn mon is still there after the game ran",
            find_party_slot(real_key) ~= nil)
end

t.finish(fmt("variant=%s", t.variant))
