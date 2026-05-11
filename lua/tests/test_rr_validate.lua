-- test_rr_validate.lua — Validates RR addresses for PSP, SB2, PC boxes, and trainer name.
-- Load in BizHawk Lua Console with an active RR 4.1 save.
-- Results are written to rr_validate_results.txt alongside this script.
--
-- Controls:
--   F1 = Run full validation (must have at least 1 mon in a PC box)
--   F3 = Dump first 3 PC box slots raw hex (for debugging garbage data)

local memory = memory or {}  -- BizHawk globals

-- ═══════════════════════════════════════════════════════════════════════════
-- Confirmed addresses from discovery
-- ═══════════════════════════════════════════════════════════════════════════

local SB1_PTR_ADDR = 0x03003840
local SB2_PTR_ADDR = 0x03003838

-- CFRU Compressed Box Storage (from pokemon_storage_system.c)
local POKEMON_STORAGE_BASE = 0x02029314  -- PokemonStorage struct; currentBox at +0x00
local COMPRESSED_MON_SIZE  = 58          -- CompressedPokemon = 58 bytes (packed)
local BOXES_PER_STORE = 25
local MONS_PER_BOX    = 30
local BOX_NAME_SIZE   = 9
-- Box bases: 25 non-contiguous EWRAM regions
local CFRU_BOX_BASES = {
    [0]  = 0x02029318,                    -- box  0
    [1]  = 0x02029318 + 1740,             -- box  1
    [2]  = 0x02029318 + 1740 * 2,         -- box  2
    [3]  = 0x02029318 + 1740 * 3,
    [4]  = 0x02029318 + 1740 * 4,
    [5]  = 0x02029318 + 1740 * 5,
    [6]  = 0x02029318 + 1740 * 6,
    [7]  = 0x02029318 + 1740 * 7,
    [8]  = 0x02029318 + 1740 * 8,
    [9]  = 0x02029318 + 1740 * 9,
    [10] = 0x02029318 + 1740 * 10,
    [11] = 0x02029318 + 1740 * 11,
    [12] = 0x02029318 + 1740 * 12,
    [13] = 0x02029318 + 1740 * 13,
    [14] = 0x02029318 + 1740 * 14,
    [15] = 0x02029318 + 1740 * 15,
    [16] = 0x02029318 + 1740 * 16,
    [17] = 0x02029318 + 1740 * 17,
    [18] = 0x02029318 + 1740 * 18,
    [19] = 0x0203CB44,                    -- box 19
    [20] = 0x0203CB44 + 1740,             -- box 20
    [21] = 0x0203CB44 + 1740 * 2,         -- box 21
    [22] = 0x02027434,                    -- box 22
    [23] = 0x02027434 + 1740,             -- box 23
    [24] = 0x02024638,                    -- box 24
}
local CFRU_BOX_NAME_BASE = 0x02031658    -- ORIGINAL_BOX_NAME_RAM

local MON_SIZE         = 100   -- struct Pokemon (party)
local OFF_PERSONALITY  = 0x00
local OFF_OTID         = 0x04
local OFF_NICKNAME     = 0x08
local OFF_HP           = 0x56
local OFF_MAX_HP       = 0x58
local OFF_LEVEL        = 0x54
local OFF_SUBSTRUCT    = 0x20

-- FRLG character table for decoding nicknames/trainer names
local CHARSET = {
  [0xBB]="A", [0xBC]="B", [0xBD]="C", [0xBE]="D", [0xBF]="E",
  [0xC0]="F", [0xC1]="G", [0xC2]="H", [0xC3]="I", [0xC4]="J",
  [0xC5]="K", [0xC6]="L", [0xC7]="M", [0xC8]="N", [0xC9]="O",
  [0xCA]="P", [0xCB]="Q", [0xCC]="R", [0xCD]="S", [0xCE]="T",
  [0xCF]="U", [0xD0]="V", [0xD1]="W", [0xD2]="X", [0xD3]="Y",
  [0xD4]="Z", [0xD5]="a", [0xD6]="b", [0xD7]="c", [0xD8]="d",
  [0xD9]="e", [0xDA]="f", [0xDB]="g", [0xDC]="h", [0xDD]="i",
  [0xDE]="j", [0xDF]="k", [0xE0]="l", [0xE1]="m", [0xE2]="n",
  [0xE3]="o", [0xE4]="p", [0xE5]="q", [0xE6]="r", [0xE7]="s",
  [0xE8]="t", [0xE9]="u", [0xEA]="v", [0xEB]="w", [0xEC]="x",
  [0xED]="y", [0xEE]="z", [0xA1]="0", [0xA2]="1", [0xA3]="2",
  [0xA4]="3", [0xA5]="4", [0xA6]="5", [0xA7]="6", [0xA8]="7",
  [0xA9]="8", [0xAA]="9", [0x00]=" ", [0xAD]="-", [0xAC]="!",
  [0xAE]=".", [0xB4]="'", [0xFF]="",
}

-- ═══════════════════════════════════════════════════════════════════════════
-- Helpers
-- ═══════════════════════════════════════════════════════════════════════════

local r8  = function(a) return memory.read_u8(a) end
local r16 = function(a) return memory.read_u16_le(a) end
local r32 = function(a) return memory.read_u32_le(a) end

local function decodeString(addr, maxLen)
    local chars = {}
    for i = 0, maxLen - 1 do
        local b = r8(addr + i)
        if b == 0xFF then break end
        chars[#chars + 1] = CHARSET[b] or string.format("[%02X]", b)
    end
    return table.concat(chars)
end

local function hexDump(addr, len)
    local parts = {}
    for i = 0, len - 1 do
        parts[#parts + 1] = string.format("%02X", r8(addr + i))
        if (i + 1) % 16 == 0 then parts[#parts + 1] = "\n    " end
    end
    return table.concat(parts, " ")
end

local function decryptSpecies(base)
    -- CFRU party/BoxPokemon: substructs unencrypted. Species = raw u16 at +0x20.
    return r16(base + OFF_SUBSTRUCT)
end

local function decryptHeldItem(base)
    -- CFRU party/BoxPokemon: held item = raw u16 at +0x22.
    return r16(base + OFF_SUBSTRUCT + 2)
end

-- CompressedPokemon (58 bytes): species at +0x1C, held item at +0x1E
local function compressedSpecies(base)
    return r16(base + 0x1C)
end

local function compressedHeldItem(base)
    return r16(base + 0x1E)
end

local function boxMonAddr(boxIdx, slotIdx)
    local base = CFRU_BOX_BASES[boxIdx]
    if not base then return nil end
    return base + slotIdx * COMPRESSED_MON_SIZE
end

local function boxNameAddr(boxIdx)
    if boxIdx <= 13 then
        return CFRU_BOX_NAME_BASE + boxIdx * BOX_NAME_SIZE
    else
        return CFRU_BOX_NAME_BASE - (boxIdx - 13) * BOX_NAME_SIZE
    end
end

local out_lines = {}
local function log(msg)
    out_lines[#out_lines + 1] = msg
    console.log(msg)
end

local function writeResults()
    local script_dir = debug.getinfo(1, "S").source:match("@?(.*[\\/])")
    if not script_dir then script_dir = "." end
    local path = script_dir .. "rr_validate_results.txt"
    local f = io.open(path, "w")
    if f then
        f:write(table.concat(out_lines, "\n"))
        f:close()
        console.log("[VALIDATE] Results written to: " .. path)
    end
end

-- ═══════════════════════════════════════════════════════════════════════════
-- Validation
-- ═══════════════════════════════════════════════════════════════════════════

local function validate()
    out_lines = {}
    log("═══════════════════════════════════════════════════════════════")
    log("  RR ADDRESS VALIDATION")
    log("═══════════════════════════════════════════════════════════════")

    -- 1. SB1 pointer
    local sb1 = r32(SB1_PTR_ADDR)
    local sb1_ok = sb1 >= 0x02000000 and sb1 < 0x02040000
    log(string.format("\n[SB1] SB1_PTR_ADDR = 0x%08X → 0x%08X  %s",
        SB1_PTR_ADDR, sb1, sb1_ok and "OK (EWRAM)" or "BAD"))

    -- 2. SB2 pointer
    local sb2 = r32(SB2_PTR_ADDR)
    local sb2_ok = sb2 >= 0x02000000 and sb2 < 0x02040000
    log(string.format("\n[SB2] SB2_PTR_ADDR = 0x%08X → 0x%08X  %s",
        SB2_PTR_ADDR, sb2, sb2_ok and "OK (EWRAM)" or "BAD"))

    -- 2b. Trainer name from SB2
    if sb2_ok then
        local tname = decodeString(sb2, 7)
        local raw_bytes = {}
        for i = 0, 7 do
            raw_bytes[#raw_bytes+1] = string.format("%02X", r8(sb2 + i))
        end
        log(string.format("  Trainer name (SB2+0x00): %q  raw=[%s]", tname, table.concat(raw_bytes, " ")))
        local is_blank = tname:match("^%s*$") ~= nil
        if is_blank then
            log("  WARNING: Trainer name is blank — SB2 pointer may be wrong!")
            log("  Scanning IWRAM for SB2 candidates (look for trainer name)...")
            for addr = 0x03003000, 0x03007000, 4 do
                local candidate = r32(addr)
                if candidate >= 0x02000000 and candidate < 0x02040000 then
                    local name = decodeString(candidate, 7)
                    if #name >= 2 and name:match("^[A-Za-z]") then
                        -- Also check encryption key at +0xF20
                        local ek = r32(candidate + 0x0F20)
                        log(string.format("    SB2? 0x%08X → 0x%08X → name=%q encKey=0x%08X",
                            addr, candidate, name, ek))
                    end
                end
            end
        end
    end

    -- 2c. SB2 encryption key
    if sb2_ok then
        local encKey = r32(sb2 + 0x0F20)
        log(string.format("  Encryption key (SB2+0x0F20): 0x%08X  %s",
            encKey, encKey ~= 0 and "OK (non-zero)" or "WARNING: zero"))
    end

    -- 3. CFRU Compressed Box Storage
    log(string.format("\n[BOXES] PokemonStorage base = 0x%08X", POKEMON_STORAGE_BASE))
    local currentBox = r8(POKEMON_STORAGE_BASE)
    log(string.format("  currentBox: %d  %s",
        currentBox, currentBox < BOXES_PER_STORE and "OK" or "BAD (>= 25)"))

    -- 3a. Box names
    log("\n[BOX NAMES]")
    for boxIdx = 0, math.min(BOXES_PER_STORE - 1, 5) do
        local nameAddr = boxNameAddr(boxIdx)
        local name = decodeString(nameAddr, 8)
        log(string.format("  Box %2d name @ 0x%08X: %q", boxIdx, nameAddr, name))
    end
    if BOXES_PER_STORE > 6 then
        log("  ... (showing first 6 only)")
        -- Also show last box (memorial)
        local lastIdx = BOXES_PER_STORE - 1
        local nameAddr = boxNameAddr(lastIdx)
        local name = decodeString(nameAddr, 8)
        log(string.format("  Box %2d name @ 0x%08X: %q  (memorial)", lastIdx, nameAddr, name))
    end

    -- 3b. Scan all boxes with CompressedPokemon format
    log("\n[BOXES] Scanning all 25 boxes (58-byte CompressedPokemon)...")
    local total_mons = 0
    local garbage_count = 0
    local sample_shown = 0
    for boxIdx = 0, BOXES_PER_STORE - 1 do
        local box_mons = 0
        for slot = 0, MONS_PER_BOX - 1 do
            local addr = boxMonAddr(boxIdx, slot)
            if addr then
                local flags = r8(addr + 0x13)  -- sanity byte: bit 1 = hasSpecies
                local pers  = r32(addr + OFF_PERSONALITY)
                if pers ~= 0 and (flags & 0x02) ~= 0 then
                    box_mons = box_mons + 1
                    local species = compressedSpecies(addr)
                    if species == 0 or species > 2000 then
                        garbage_count = garbage_count + 1
                    end
                    -- Show first few detailed entries
                    if sample_shown < 5 then
                        local otId = r32(addr + OFF_OTID)
                        local nick = decodeString(addr + OFF_NICKNAME, 10)
                        local item = compressedHeldItem(addr)
                        local key = string.format("%08X:%08X", pers, otId)
                        log(string.format("  Box %2d Slot %2d @ 0x%08X: %s nick=%q species=%d item=%d",
                            boxIdx, slot, addr, key, nick, species, item))
                        sample_shown = sample_shown + 1
                    end
                end
            end
        end
        if box_mons > 0 then
            total_mons = total_mons + box_mons
            log(string.format("  Box %2d: %d mons  (base=0x%08X)", boxIdx, box_mons, CFRU_BOX_BASES[boxIdx]))
        end
    end
    log(string.format("  Total mons in PC: %d (garbage species: %d)", total_mons, garbage_count))
    if total_mons == 0 then
        log("  No mons found in any box. Deposit a mon to verify addresses.")
    elseif garbage_count > total_mons / 2 then
        log("  WARNING: Most species IDs look like garbage — box addresses may be wrong!")
    else
        log("  ✓ Box data looks valid!")
    end

    -- 4. Party (compare SB1 vs vanilla EWRAM)
    local EWRAM_PARTY_COUNT_ADDR = 0x02024029
    local VANILLA_PARTY_BASE     = 0x02024284
    local ewramCount = r8(EWRAM_PARTY_COUNT_ADDR)
    if sb1_ok then
        local sb1Count  = r8(sb1 + 0x0034)
        local partyBase = sb1 + 0x0038
        log(string.format("\n[PARTY] ewram_count=%d  sb1_count=%d", ewramCount, sb1Count))
        log(string.format("  SB1 base=0x%08X (SB1+0x38)  Vanilla base=0x%08X", partyBase, VANILLA_PARTY_BASE))
        if ewramCount ~= sb1Count then
            log("  WARNING: EWRAM count != SB1 count — SB1 copy is stale!")
        end
        local useCount = math.min(ewramCount, 6)
        for i = 0, useCount - 1 do
            -- Read from SB1
            local base_sb1 = partyBase + i * MON_SIZE
            local pers_sb1 = r32(base_sb1 + OFF_PERSONALITY)
            local hp_sb1   = r16(base_sb1 + OFF_HP)
            local maxHP_sb1 = r16(base_sb1 + OFF_MAX_HP)
            local level_sb1 = r8(base_sb1 + OFF_LEVEL)
            local nick_sb1  = decodeString(base_sb1 + OFF_NICKNAME, 10)
            local ok_s, species_sb1 = pcall(decryptSpecies, base_sb1)
            species_sb1 = ok_s and species_sb1 or -1
            -- Read from vanilla EWRAM
            local base_v = VANILLA_PARTY_BASE + i * MON_SIZE
            local pers_v = r32(base_v + OFF_PERSONALITY)
            local hp_v   = r16(base_v + OFF_HP)
            local maxHP_v = r16(base_v + OFF_MAX_HP)
            local level_v = r8(base_v + OFF_LEVEL)
            local nick_v  = decodeString(base_v + OFF_NICKNAME, 10)
            local ok_s2, species_v = pcall(decryptSpecies, base_v)
            species_v = ok_s2 and species_v or -1
            local key_sb1 = string.format("%08X", pers_sb1)
            local key_v   = string.format("%08X", pers_v)
            local match = (pers_sb1 == pers_v) and "SAME" or "DIFF"
            log(string.format("  Slot %d SB1:  %s lv%d %d/%d HP species=%d nick=%q",
                i, key_sb1, level_sb1, hp_sb1, maxHP_sb1, species_sb1, nick_sb1))
            log(string.format("  Slot %d VAN:  %s lv%d %d/%d HP species=%d nick=%q  [%s]",
                i, key_v, level_v, hp_v, maxHP_v, species_v, nick_v, match))
        end
    end

    -- 4b. gBattleMons (live battle data — only valid during battle)
    local BATTLE_MONS_ADDR = 0x02023BE4
    local BATTLE_MON_SIZE  = 0x58  -- 88 bytes
    local BATTLE_OUTCOME_ADDR = 0x02023E8A
    local BATTLER_PARTY_IDX_ADDR = 0x02023BCE
    local BATTLERS_COUNT_ADDR = 0x02023BCC
    local outcome = r8(BATTLE_OUTCOME_ADDR)
    local bmon0_maxHP = r16(BATTLE_MONS_ADDR + 0x2C)
    local in_battle = (bmon0_maxHP > 0 and outcome == 0)
    log(string.format("\n[BATTLE] outcome=%d  bmon0_maxHP=%d  in_battle=%s",
        outcome, bmon0_maxHP, tostring(in_battle)))
    if in_battle or bmon0_maxHP > 0 then
        local battlerCount = r8(BATTLERS_COUNT_ADDR)
        log(string.format("  battlerCount=%d  partyIdx[0]=%d  partyIdx[2]=%d",
            battlerCount,
            r16(BATTLER_PARTY_IDX_ADDR),
            r16(BATTLER_PARTY_IDX_ADDR + 4)))
        for b = 0, 3 do
            local bbase = BATTLE_MONS_ADDR + b * BATTLE_MON_SIZE
            local sp  = r16(bbase + 0x00)
            local bhp = r16(bbase + 0x28)
            local bmx = r16(bbase + 0x2C)
            local blv = r8(bbase + 0x2A)
            if sp > 0 and bmx > 0 then
                log(string.format("  Battler %d: species=%d lv%d %d/%d HP",
                    b, sp, blv, bhp, bmx))
            end
        end
    else
        log("  (not in battle)")
    end

    -- 4c. Enemy party (vanilla EWRAM globals — likely wrong for CFRU)
    local ENEMY_COUNT_ADDR = 0x0202402A
    local ENEMY_BASE       = 0x0202402C
    local enemyCount = r8(ENEMY_COUNT_ADDR)
    log(string.format("\n[ENEMY] count=%d @ 0x%08X  base=0x%08X", enemyCount, ENEMY_COUNT_ADDR, ENEMY_BASE))
    if enemyCount > 0 and enemyCount <= 6 then
        for i = 0, math.min(enemyCount, 6) - 1 do
            local base = ENEMY_BASE + i * MON_SIZE
            local pers  = r32(base + OFF_PERSONALITY)
            local maxHP = r16(base + OFF_MAX_HP)
            if pers ~= 0 and maxHP > 0 then
                local level = r8(base + OFF_LEVEL)
                local nick  = decodeString(base + OFF_NICKNAME, 10)
                local ok_s, species = pcall(decryptSpecies, base)
                species = ok_s and species or -1
                local key = string.format("%08X:%08X", pers, r32(base + OFF_OTID))
                log(string.format("  Slot %d: %s lv%d %d HP nick=%q species=%d",
                    i, key, level, maxHP, nick, species))
            end
        end
    else
        log("  (no enemy party loaded — enter a battle to test)")
    end

    -- 5. Ball pocket (EWRAM)
    local BALL_POCKET_ADDR = 0x0203C354
    log(string.format("\n[BAG] Ball pocket @ 0x%08X (EWRAM, 50 slots)", BALL_POCKET_ADDR))
    local balls_found = 0
    for i = 0, 49 do
        local itemId = r16(BALL_POCKET_ADDR + i * 4)
        local qty    = r16(BALL_POCKET_ADDR + i * 4 + 2)
        if itemId ~= 0 then
            log(string.format("  Slot %d: itemId=%d qty=%d", i, itemId, qty))
            balls_found = balls_found + 1
        end
    end
    if balls_found == 0 then
        log("  No balls in bag (or wrong address)")
    end

    -- 6. Flags offset sanity check
    if sb1_ok then
        local flagsByte = r8(sb1 + 0x0EE0 + 0x0104)
        local badges = 0
        for bit = 0, 7 do
            if (flagsByte & (1 << bit)) ~= 0 then badges = badges + 1 end
        end
        log(string.format("\n[FLAGS] Badge byte (SB1+0x0EE0+0x104): 0x%02X → %d badges",
            flagsByte, badges))
    end

    log("\n═══════════════════════════════════════════════════════════════")
    log("  VALIDATION COMPLETE")
    log("═══════════════════════════════════════════════════════════════")
    writeResults()
end

local function scanForBoxMon()
    out_lines = {}
    log("═══ CFRU BOX VERIFICATION ═══")
    log("Scanning CFRU box addresses for deposited mon...")

    -- Read the current party slot 0 personality
    local sb1 = r32(SB1_PTR_ADDR)
    local partyBase = sb1 + 0x0038
    local target_pers = r32(partyBase + OFF_PERSONALITY)
    local target_otId = r32(partyBase + OFF_OTID)
    local partyCount = r8(sb1 + 0x0034)

    if partyCount == 0 or target_pers == 0 then
        target_pers = 0xC7083398
        target_otId = 0x0EF92CE1
        log(string.format("  Party empty — using known key: %08X:%08X", target_pers, target_otId))
    else
        log(string.format("  Party slot 0 key: %08X:%08X", target_pers, target_otId))
    end

    -- Scan all 25 CFRU boxes for this mon
    log(string.format("\n  Searching %d boxes for personality 0x%08X...", BOXES_PER_STORE, target_pers))
    local found = false
    for boxIdx = 0, BOXES_PER_STORE - 1 do
        for slot = 0, MONS_PER_BOX - 1 do
            local addr = boxMonAddr(boxIdx, slot)
            if addr then
                local pers = r32(addr + OFF_PERSONALITY)
                if pers == target_pers then
                    local otId = r32(addr + OFF_OTID)
                    local match = (otId == target_otId)
                    local species = compressedSpecies(addr)
                    local item = compressedHeldItem(addr)
                    local nick = decodeString(addr + OFF_NICKNAME, 10)
                    log(string.format("  ✓ Box %d Slot %d @ 0x%08X: otId=%s species=%d item=%d nick=%q",
                        boxIdx, slot, addr,
                        match and "MATCH" or string.format("MISMATCH(0x%08X)", otId),
                        species, item, nick))
                    found = true
                end
            end
        end
    end

    if not found then
        log("  Not found in any box slot. Is it deposited?")
        -- Also do a raw EWRAM scan as fallback
        log("\n  Fallback: scanning EWRAM 0x02000000-0x0203FFFC...")
        for addr = 0x02000000, 0x0203FFFC, 4 do
            if r32(addr) == target_pers and r32(addr + 4) == target_otId then
                local nick = decodeString(addr + 0x08, 10)
                local sp_party = r16(addr + 0x20)  -- party species offset
                local sp_box   = r16(addr + 0x1C)  -- compressed species offset
                log(string.format("  HIT @ 0x%08X: nick=%q species_party_offset=%d species_box_offset=%d",
                    addr, nick, sp_party, sp_box))
            end
        end
    end

    -- Show currentBox and box 0 raw header
    local currentBox = r8(POKEMON_STORAGE_BASE)
    log(string.format("\n  currentBox: %d", currentBox))
    local box0base = CFRU_BOX_BASES[0]
    log(string.format("  Box 0 base = 0x%08X, first 32 bytes:", box0base))
    log("    " .. hexDump(box0base, 32))

    log("\n═══ SCAN COMPLETE ═══")
    writeResults()
end

local function dumpBoxSlots()
    out_lines = {}
    log("═══ RAW HEX DUMP: Box 0, Slots 0-2 (CompressedPokemon, 58 bytes each) ═══")
    for slot = 0, 2 do
        local addr = boxMonAddr(0, slot)
        log(string.format("\nBox 0 Slot %d @ 0x%08X:", slot, addr))
        log("    " .. hexDump(addr, COMPRESSED_MON_SIZE))
        local pers = r32(addr + OFF_PERSONALITY)
        if pers ~= 0 then
            local species = compressedSpecies(addr)
            local item = compressedHeldItem(addr)
            local nick = decodeString(addr + OFF_NICKNAME, 10)
            log(string.format("    → pers=0x%08X species=%d item=%d nick=%q", pers, species, item, nick))
        else
            log("    → (empty slot)")
        end
    end
    writeResults()
end

-- ═══════════════════════════════════════════════════════════════════════════
-- Key handlers
-- ═══════════════════════════════════════════════════════════════════════════

local prev_keys = {}
local function on_frame()
    local keys = input.get()
    if keys["F1"] and not prev_keys["F1"] then
        console.log("[VALIDATE] F1 — Running full validation...")
        validate()
    end
    if keys["F3"] and not prev_keys["F3"] then
        console.log("[VALIDATE] F3 — Dumping box slots...")
        dumpBoxSlots()
    end
    if keys["F5"] and not prev_keys["F5"] then
        console.log("[VALIDATE] F5 — Scanning EWRAM for box mon...")
        scanForBoxMon()
    end
    prev_keys = keys
end

event.onframeend(on_frame)
console.log("[VALIDATE] Ready. Press F1 for full validation, F3 for raw box hex dump, F5 for box mon scan.")
console.log("[VALIDATE] Make sure you have an active save loaded (not title screen).")
