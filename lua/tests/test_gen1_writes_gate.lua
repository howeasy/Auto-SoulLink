--[[
  lua/tests/test_gen1_writes_gate.lua — headless: do the Gen 1 WRITE paths actually work?

  Reads are covered by test_gen1_memory_gate. This gate exercises the code that MUTATES the
  cartridge, which is where Gen 1 was most broken and least verified:

    * force_faint      — the whole faint-propagation rule depends on it
    * box deposit      — party -> PC, and the level/stat round-trip that came back with a
                         garbage level because the box level was read from party+0x21,
                         past the end of the 33-byte box struct and into the NEXT slot
    * writeEnemyParty  — the Rival Team Swap's 404-byte contiguous write
    * forceExplode     — Explode Mode's move injection
    * safe-state gate  — isInOverworld must refuse while a menu/script owns the screen

  None of this had ever run against a real game: the unit tests exercise the Python adapter
  and never load the Lua, and the Lua syntax check cannot catch a wrong address.

  Runs on tests/fixtures/gen1/<rom>_town.SaveRAM (one level-5 Squirtle, 20/20 HP).
  Result file: patch/build/test_gen1_writes_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_writes_gate")
local M = t.M
local fmt = string.format

-- ── Safe-state gate ──────────────────────────────────────────────────────────
-- Only the POSITIVE case is asserted live. Opening the START menu from a freshly loaded
-- battery save proved unreliable to stage here (wFontLoaded stayed 0x00 through a dozen
-- held Start presses, with and without walking first), and a gate that cannot reliably set
-- up its precondition tests the harness rather than the code.
--
-- The negative cases are not skipped, just tested somewhere better: tests/unit/
-- test_gen1_safe_state.py executes THIS SAME Lua under lupa and drives wJoyIgnore /
-- wFontLoaded / wIsInBattle directly, covering the menu, the text box, a script holding
-- the joypad, and the IN_BATTLE_LOST sentinel — every combination, deterministically.
t.check("isInOverworld true while the player is walking around",
        M.isInOverworld() == true)


t.check("starting from a healthy mon", (M.readPartySlot(0) or {}).hp == 20)

-- ── force_faint ──────────────────────────────────────────────────────────────
M.forceFaint(0)
local mon = M.readPartySlot(0)
t.check("forceFaint zeroes current HP", mon and mon.hp == 0,
        fmt("hp=%s", tostring(mon and mon.hp)))
t.check("forceFaint leaves maxHP intact", mon and mon.maxHP == 20,
        fmt("maxHP=%s", tostring(mon and mon.maxHP)))
t.check("the mon key survives a faint", mon and mon.key and #mon.key == 12,
        "identity must not change, or the pair unlinks")

-- Heal it back so the later checks start from a known state.
M.write_u16_be(M.PARTY_BASE_ADDR + M.HP_OFFSET, 20)
t.check("healed back to 20", (M.readPartySlot(0) or {}).hp == 20)

-- ── Box round-trip ───────────────────────────────────────────────────────────
-- depositPartyMon refuses to box the last party mon (it would soft-lock the save), so give
-- the party a second mon first by cloning slot 0.
local struct = M.PARTY_STRUCT_SIZE
for i = 0, struct - 1 do
    M.write_u8(M.PARTY_BASE_ADDR + struct + i, M.read_u8(M.PARTY_BASE_ADDR + i))
end
M.write_u8(M.PARTY_SPECIES_ADDR + 1, M.read_u8(M.PARTY_SPECIES_ADDR))
M.write_u8(M.PARTY_SPECIES_ADDR + 2, 0xFF)
M.write_u8(M.PARTY_COUNT_ADDR, 2)
-- Make the two distinguishable: slot 1 is level 9 with different DVs, so a wrong box
-- offset shows up as the WRONG mon rather than silently passing.
M.write_u8(M.PARTY_BASE_ADDR + struct + M.LEVEL_OFFSET, 9)
M.write_u8(M.PARTY_BASE_ADDR + struct + 0x1B, 0x77)
t.check("party is 2 for the deposit test", M.getPartyCount() == 2)

local before_box = M.getBoxCount()
local ok, err = M.depositPartyMon(1)
t.check("depositPartyMon(1) succeeds", ok, tostring(err))
t.check("box count went up", M.getBoxCount() == before_box + 1,
        fmt("%d -> %d", before_box, M.getBoxCount()))
t.check("party count went down", M.getPartyCount() == 1, fmt("got %d", M.getPartyCount()))

-- The client's party_to_box detection only fires once it can FIND the mon in the box by
-- key (it refuses to report a deposit it cannot corroborate). So readBoxSlot must produce
-- the same DVs:OTID:species key the party read produced — if it does not, a deposit is
-- silently never reported and the partner is never told to box their half.
local deposited_key = nil
do
    local bc = M.getBoxCount()
    local found = nil
    for i = 0, bc - 1 do
        local b = M.readBoxSlot(i)
        if b then deposited_key = b.key; if b.key then found = i end end
    end
    t.check("readBoxSlot decodes the mon just deposited", found ~= nil,
            fmt("boxCount=%d firstKey=%s", bc, tostring(deposited_key)))
    t.check("box key has the same DDDD:TTTT:II shape as a party key",
            deposited_key and #deposited_key == 12,
            fmt("got %q — a mismatch here means party_to_box never fires", tostring(deposited_key)))
end

-- THE PHASE 0 BUG: box level lives at box+0x03 (wBoxMon1BoxLevel). Reading it at the
-- party's +0x21 lands past the 33-byte box struct, inside the next slot.
local box_base = M.BOX_BASE_ADDR + (M.getBoxCount() - 1) * M.BOX_STRUCT_SIZE
local box_level = M.box_read_u8(box_base + M.BOX_LEVEL_OFFSET)
t.check("boxed mon kept its level (box+0x03, not party+0x21)", box_level == 9,
        fmt("got %d, expected 9", box_level))

-- ── Rival Team Swap ──────────────────────────────────────────────────────────
-- 404 contiguous bytes: count, species list, 6x44 structs, 6x11 OT, 6x11 nicknames.
local blob = M.readPartyBlob(0)
t.check("readPartyBlob returns 66 bytes (44 struct + 11 OT + 11 nick)",
        blob and #blob == 66, fmt("got %s", blob and #blob or "nil"))
if blob then
    local wrote, n = M.writeEnemyParty({blob, blob})
    t.check("writeEnemyParty succeeds", wrote, tostring(n))
    t.check("enemy party count is 2", M.read_u8(M.ENEMY_COUNT_ADDR) == 2,
            fmt("got %d", M.read_u8(M.ENEMY_COUNT_ADDR)))
    t.check("enemy species list is terminated", M.read_u8(M.ENEMY_SPECIES_LIST_ADDR + 2) == 0xFF)
    t.check("enemy mon 0 species matches the blob",
            M.read_u8(M.ENEMY_BASE_ADDR) == blob[1],
            fmt("got 0x%02X want 0x%02X", M.read_u8(M.ENEMY_BASE_ADDR), blob[1]))
    -- Level at +0x21 is what send-out copies into wCurEnemyLevel.
    t.check("enemy mon 1 level landed at +0x21",
            M.read_u8(M.ENEMY_BASE_ADDR + M.PARTY_STRUCT_SIZE + 0x21) == blob[0x21 + 1],
            "a wrong stride here fights you with the wrong team")
    t.check("enemy OT name array was written", M.read_u8(M.ENEMY_OT_NAMES_ADDR) == blob[45])
end

-- ── Explode Mode ─────────────────────────────────────────────────────────────
-- Out of battle it must REFUSE, so the caller falls back to a plain force_faint rather
-- than silently doing nothing and leaving a linked mon alive.
local ex_ok, ex_err = M.forceExplode(0)
t.check("forceExplode refuses outside battle", ex_ok == false, tostring(ex_err))

-- ── Memorial box vs the game's one-time SRAM wipe ────────────────────────────
-- pokered's ChangeBox opens with
--     bit BIT_HAS_CHANGED_BOXES, [hl]   ; hl = wCurrentBoxNum, bit 7
--     call z, EmptyAllSRAMBoxes         ; if so, empty ALL boxes in SRAM
-- so the first time a player ever picks "CHANGE BOX", the game marks every SRAM box empty —
-- including box 12, our memorial. A run that buried a pair before the player first opened the
-- box menu would lose it silently.
--
-- Driving that menu needs a Pokémon Center, which no gate can reach. So instead we prove the
-- two halves that compose into the guarantee:
--   (a) the ROM really does branch on that bit — read the actual instruction bytes, so this
--       gate verifies the behaviour it defends against instead of trusting a source read;
--   (b) after a memorial write the bit is SET, so `call z` is not taken.
local CHANGE_BOX_HOOK = M.profile and M.profile.change_box_bit_test_rom_addr
if CHANGE_BOX_HOOK then
    -- `bit 7, [hl]` = CB 7E ; `call z, nn` = CC nn nn
    local b0 = memory.read_u8(CHANGE_BOX_HOOK, "ROM")
    local b1 = memory.read_u8(CHANGE_BOX_HOOK + 1, "ROM")
    local b2 = memory.read_u8(CHANGE_BOX_HOOK + 2, "ROM")
    t.check("ChangeBox really tests bit 7 of wCurrentBoxNum then conditionally calls",
            b0 == 0xCB and b1 == 0x7E and b2 == 0xCC,
            fmt("bytes %02X %02X %02X at ROM %#07x (want CB 7E CC)",
                b0, b1, b2, CHANGE_BOX_HOOK))
end

local before_flag = M.read_u8(M.CURRENT_BOX_NUM_ADDR)
t.check("fixture starts with BIT_HAS_CHANGED_BOXES clear (the dangerous state)",
        before_flag < 0x80,
        fmt("wCurrentBoxNum = %#04x — if this is already >=0x80 the guard is untested here",
            before_flag))

-- The box test above deposited slot 1, so the party is back down to one mon and
-- depositMemorialMon would (correctly) refuse. Give it a second mon again.
for i = 0, struct - 1 do
    M.write_u8(M.PARTY_BASE_ADDR + struct + i, M.read_u8(M.PARTY_BASE_ADDR + i))
end
M.write_u8(M.PARTY_SPECIES_ADDR + 1, M.read_u8(M.PARTY_SPECIES_ADDR))
M.write_u8(M.PARTY_SPECIES_ADDR + 2, 0xFF)
M.write_u8(M.PARTY_COUNT_ADDR, 2)
t.check("party topped back up to 2 for the memorial test", M.getPartyCount() == 2)

local mem_before = M.getMemorialBoxCount()
local mem_ok, mem_err = M.depositMemorialMon(0)
t.check("depositMemorialMon succeeds", mem_ok, tostring(mem_err))

if mem_ok then
    t.check("memorial box gained a mon",
            M.getMemorialBoxCount() == mem_before + 1,
            fmt("%d -> %d", mem_before, M.getMemorialBoxCount()))

    local slot = M.readMemorialBoxSlot(mem_before)
    t.check("the buried mon reads back with a well-formed key",
            slot ~= nil and type(slot.key) == "string" and #slot.key == 12,
            fmt("got %s", slot and slot.key or "nil"))

    -- THE ASSERTION THIS SECTION EXISTS FOR.
    local after_flag = M.read_u8(M.CURRENT_BOX_NUM_ADDR)
    t.check("BIT_HAS_CHANGED_BOXES is now set, so ChangeBox will NOT wipe the memorial",
            after_flag >= 0x80,
            fmt("wCurrentBoxNum %#04x -> %#04x", before_flag, after_flag))
    t.check("the active box index was not disturbed by the guard",
            after_flag % 0x80 == before_flag % 0x80,
            fmt("index %d -> %d", before_flag % 0x80, after_flag % 0x80))

    -- The other 11 boxes must be left in the game's own "empty" shape (count 0, 0xFF
    -- terminator), not uninitialised SRAM garbage that the box menu would render as counts.
    local BOX_LEN, PER_BANK = 1122, 6
    local bad = nil
    for box = 1, 12 do
        if box ~= 12 then
            local off = (box <= PER_BANK and 2 or 3) * 0x2000
                        + ((box - 1) % PER_BANK) * BOX_LEN
            local cnt = memory.read_u8(off, "CartRAM")
            local term = memory.read_u8(off + 1, "CartRAM")
            if cnt ~= 0 or term ~= 0xFF then
                bad = fmt("box %d: count=%d term=%#04x", box, cnt, term)
                break
            end
        end
    end
    t.check("the other 11 SRAM boxes were initialised to the game's empty shape",
            bad == nil, bad or "all count=0 / 0xFF")

    -- Idempotence on real hardware: a second memorial must not re-run the wipe.
    local ok2 = M.depositMemorialMon(0)
    if ok2 then
        t.check("a second memorial does not erase the first",
                M.getMemorialBoxCount() == mem_before + 2,
                fmt("count is %d, expected %d", M.getMemorialBoxCount(), mem_before + 2))
    end
end

t.finish(fmt("variant=%s", t.variant))
