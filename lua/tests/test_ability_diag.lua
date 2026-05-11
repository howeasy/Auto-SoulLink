-- test_ability_diag.lua — Quick ability diagnostic for any profile
-- Load in BizHawk Lua Console. Prints ability data for party slot 0.
-- Tests whether gBaseStats address is correct for this ROM.

local mem_r8  = memory.read_u8
local mem_r16 = memory.read_u16_le
local mem_r32 = memory.read_u32_le

-- ── ROM detection ──
local function readGameCode()
    local b = {}
    for i = 0, 3 do b[i+1] = string.char(mem_r8(0x080000AC + i, "System Bus")) end
    return table.concat(b)
end

local code = readGameCode()
print("Game code: " .. code)

-- ── Profile addresses ──
local PROFILES = {
    vanilla = {
        PARTY_COUNT = 0x02024029, PARTY_BASE = 0x02024284,
        BASESTATS   = 0x08254784, ENTRY_SIZE = 28,
        CFRU = false, ENCRYPTED = true,
    },
    ap = {
        PARTY_COUNT = 0x0202403D, PARTY_BASE = 0x02024298,
        BASESTATS   = 0x08254784, ENTRY_SIZE = 28,
        CFRU = false, ENCRYPTED = true,
    },
    rr = {
        PARTY_COUNT = 0x020244E8, PARTY_BASE = 0x020244EC,
        BASESTATS   = nil, -- resolved via pointer
        ENTRY_SIZE  = 28,
        CFRU = true, ENCRYPTED = false,
        BASESTATS_PTR = 0x080001BC,
    },
}

-- Detect profile — test ALL three and let user see results
local prof

-- Check AP vs vanilla via IWRAM pointer difference (definitive)
local v_sb1_ptr = mem_r32(0x03005008)  -- vanilla SB1 pointer
local a_sb1_ptr = mem_r32(0x03004F58)  -- AP SB1 pointer
local v_valid = (v_sb1_ptr >= 0x02000000 and v_sb1_ptr < 0x02040000)
local a_valid = (a_sb1_ptr >= 0x02000000 and a_sb1_ptr < 0x02040000)

-- Check CFRU pointer
local cfru_ptr = mem_r32(0x080001BC, "System Bus")
local cfru_valid = (cfru_ptr > 0x08000000 and cfru_ptr < 0x0A000000)

print(string.format("  Vanilla SB1 ptr @ 0x03005008 = 0x%08X (%s)",
    v_sb1_ptr, v_valid and "VALID" or "invalid"))
print(string.format("  AP SB1 ptr      @ 0x03004F58 = 0x%08X (%s)",
    a_sb1_ptr, a_valid and "VALID" or "invalid"))
print(string.format("  CFRU BaseStats  @ 0x080001BC = 0x%08X (%s)",
    cfru_ptr, cfru_valid and "VALID ptr" or "not a ptr"))

-- Party count at each address
local v_count = mem_r8(0x02024029)
local a_count = mem_r8(0x0202403D)
local r_count = mem_r8(0x020244E8)
print(string.format("  Party count: vanilla=%d  AP=%d  RR=%d", v_count, a_count, r_count))

if code == "BPRE" or code == "BPGE" then
    if a_valid and not v_valid then
        prof = PROFILES.ap
        print("→ Profile: AP (AP SB1 pointer valid, vanilla not)")
    elseif cfru_valid and r_count >= 1 and r_count <= 6 then
        prof = PROFILES.rr
        prof.BASESTATS = cfru_ptr
        print("→ Profile: RR/CFRU (gBaseStats ptr → " .. string.format("0x%08X", cfru_ptr) .. ")")
    elseif v_valid then
        prof = PROFILES.vanilla
        print("→ Profile: Vanilla")
    elseif a_valid then
        prof = PROFILES.ap
        print("→ Profile: AP")
    else
        print("→ UNABLE TO DETECT — testing ALL profiles below")
        prof = PROFILES.vanilla  -- default
    end
else
    print("ERROR: Unknown game code: " .. code)
    return
end

-- Test gBaseStats at BOTH vanilla and AP-candidate addresses
print("\n=== Testing gBaseStats at multiple addresses ===")
local test_addrs = {
    {0x08254784, "vanilla hardcoded"},
}
if cfru_valid then
    table.insert(test_addrs, {cfru_ptr, "CFRU pointer"})
end
for _, t in ipairs(test_addrs) do
    local addr, label = t[1], t[2]
    local entry = addr + 1 * 28  -- Bulbasaur
    local hp  = mem_r8(entry + 0, "System Bus")
    local atk = mem_r8(entry + 1, "System Bus")
    local def = mem_r8(entry + 2, "System Bus")
    local type1 = mem_r8(entry + 6, "System Bus")
    local type2 = mem_r8(entry + 7, "System Bus")
    local ok = (hp == 45 and atk == 49 and type1 == 12 and type2 == 3)
    print(string.format("  0x%08X (%s): HP=%d Atk=%d Def=%d T1=%d T2=%d → %s",
        addr, label, hp, atk, def, type1, type2, ok and "VALID" or "WRONG"))
end

-- ── Substruct permutation table ──
local SUBSTRUCT_ORDER = {
    {0,1,2,3},{0,1,3,2},{0,2,1,3},{0,2,3,1},{0,3,1,2},{0,3,2,1},
    {1,0,2,3},{1,0,3,2},{2,0,1,3},{3,0,1,2},{2,0,3,1},{3,0,2,1},
    {1,2,0,3},{1,3,0,2},{2,1,0,3},{3,1,0,2},{2,3,0,1},{3,2,0,1},
    {1,2,3,0},{1,3,2,0},{2,1,3,0},{3,1,2,0},{2,3,1,0},{3,2,1,0},
}

-- ── Decrypt species ──
local function decryptSpecies(base)
    local personality = mem_r32(base)
    local otId = mem_r32(base + 4)
    if prof.ENCRYPTED then
        local key = personality ~ otId
        local perm = SUBSTRUCT_ORDER[(personality % 24) + 1]
        local growth_pos = perm[1]  -- 1st element = Growth substruct position
        local raw = mem_r32(base + 0x20 + growth_pos * 12)
        return (raw ~ key) & 0xFFFF
    else
        -- CFRU: unencrypted, growth at position 0
        return mem_r16(base + 0x20)
    end
end

-- ── Read ability ──
local function getAbility(base)
    local personality = mem_r32(base)
    local otId = mem_r32(base + 4)
    local species = decryptSpecies(base)

    -- Get IVs dword for abilityBit
    local ivs_dword
    if not prof.ENCRYPTED then
        -- CFRU: fixed order, Misc at position 3
        ivs_dword = mem_r32(base + 0x20 + 3 * 12 + 4)
    else
        local key = personality ~ otId
        local perm = SUBSTRUCT_ORDER[(personality % 24) + 1]
        local misc_pos = perm[4]
        ivs_dword = mem_r32(base + 0x20 + misc_pos * 12 + 4) ~ key
    end
    local ability_bit = (ivs_dword >> 31) & 1

    -- Look up in gBaseStats
    local entry = prof.BASESTATS + species * prof.ENTRY_SIZE
    local a1 = mem_r8(entry + 0x16, "System Bus")
    local a2 = mem_r8(entry + 0x17, "System Bus")

    local slot = prof.CFRU and (personality % 2) or ability_bit
    local aid = mem_r8(entry + 0x16 + slot, "System Bus")
    if aid == 0 and slot == 1 then aid = a1 end

    return species, ability_bit, a1, a2, aid, entry
end

-- ── Validate gBaseStats ──
-- Check if the address looks sane by reading a known species (Bulbasaur = 1)
local function validateBaseStats()
    if not prof.BASESTATS then return false, "no address" end
    local entry = prof.BASESTATS + 1 * prof.ENTRY_SIZE  -- Bulbasaur
    local hp  = mem_r8(entry + 0, "System Bus")
    local atk = mem_r8(entry + 1, "System Bus")
    local def = mem_r8(entry + 2, "System Bus")
    local spd = mem_r8(entry + 3, "System Bus")
    local type1 = mem_r8(entry + 6, "System Bus")
    local type2 = mem_r8(entry + 7, "System Bus")
    -- Bulbasaur: HP=45, Atk=49, Def=49, Spd=45, Grass(12)/Poison(3)
    print(string.format("  Bulbasaur check: HP=%d Atk=%d Def=%d Spd=%d Type1=%d Type2=%d",
        hp, atk, def, spd, type1, type2))
    local ok = (hp == 45 and atk == 49 and def == 49 and type1 == 12 and type2 == 3)
    if not ok then
        -- Maybe randomized stats but types should still be sane (0-17)
        if type1 <= 17 and type2 <= 17 and hp > 0 and hp < 255 then
            print("  Stats differ (randomized?) but structure looks valid")
            return true, "randomized"
        end
        return false, string.format("bad data (HP=%d type1=%d)", hp, type1)
    end
    return true, "exact match"
end

-- ── Search for gBaseStats if current address fails ──
local function searchBaseStats()
    print("\n=== Searching for gBaseStats in ROM ===")
    -- Bulbasaur (species 1) signature: HP=45,Atk=49,Def=49,SpAtk=65,SpDef=65,Spd=45
    -- Types: Grass(12),Poison(3), CatchRate=45, ExpYield=64
    -- Search ROM for this byte pattern
    local sig = {45, 49, 49, 65, 65, 45, 12, 3, 45, 64}
    local ROM_START = 0x08000000
    local ROM_END   = 0x09FFFFFF
    local STEP = 4  -- aligned search
    local found = {}

    print("Searching for Bulbasaur stat signature in ROM...")
    print("(This may take a moment)")

    -- Search in likely ranges first (0x0824xxxx - 0x0828xxxx for vanilla-like,
    -- 0x086xxxxx - 0x087xxxxx for AP-shifted)
    local ranges = {
        {0x08200000, 0x08300000},  -- vanilla range
        {0x08600000, 0x08800000},  -- AP shifted range
        {0x08400000, 0x08600000},  -- other possible ranges
        {0x08100000, 0x08200000},
    }

    for _, range in ipairs(ranges) do
        for addr = range[1], range[2], STEP do
            local match = true
            for j, byte in ipairs(sig) do
                if mem_r8(addr + j - 1, "System Bus") ~= byte then
                    match = false
                    break
                end
            end
            if match then
                -- This would be Bulbasaur's entry; gBaseStats = addr - 28 (entry_size)
                local base = addr - prof.ENTRY_SIZE
                print(string.format("  FOUND Bulbasaur stats at 0x%08X → gBaseStats = 0x%08X", addr, base))
                table.insert(found, base)
            end
        end
    end

    if #found == 0 then
        print("  No matches in priority ranges. Try full ROM scan? (slow)")
    end
    return found
end

-- ── Main diagnostics ──
print("\n=== gBaseStats Validation ===")
print(string.format("  Address: 0x%08X", prof.BASESTATS or 0))
local valid, reason = validateBaseStats()
print("  Valid: " .. tostring(valid) .. " (" .. reason .. ")")

if not valid then
    local candidates = searchBaseStats()
    if #candidates > 0 then
        print("\nRetesting with first candidate:")
        prof.BASESTATS = candidates[1]
        valid, reason = validateBaseStats()
        print("  Valid: " .. tostring(valid) .. " (" .. reason .. ")")
    end
end

print("\n=== Party Ability Scan ===")
local count = mem_r8(prof.PARTY_COUNT)
print("Party count: " .. count)

if count >= 1 and count <= 6 then
    for i = 0, count - 1 do
        local base = prof.PARTY_BASE + i * 100
        local personality = mem_r32(base)
        local otId = mem_r32(base + 4)
        local hp = mem_r16(base + 0x56)
        local maxHP = mem_r16(base + 0x58)
        local key = string.format("%08X:%08X", personality, otId)

        if maxHP > 0 then
            local ok, species, abit, a1, a2, aid, entry = pcall(getAbility, base)
            if ok then
                print(string.format(
                    "  Slot %d: key=%s HP=%d/%d species=%d abilityBit=%d a1=%d a2=%d → aid=%d entry@0x%08X",
                    i, key, hp, maxHP, species, abit, a1, a2, aid, entry))
            else
                print(string.format("  Slot %d: key=%s HP=%d/%d ERROR: %s", i, key, hp, maxHP, tostring(species)))
            end
        else
            print(string.format("  Slot %d: key=%s (empty/fainted)", i, key))
        end
    end
else
    print("  Invalid party count!")
end

-- Also check gBattleMons if in battle (ability at +0x20 is resolved by the engine)
print("\n=== gBattleMons Active Foe ===")
local BMON_ADDRS = {
    vanilla = 0x02023BE4,
    ap      = 0x02023BF8,
    rr      = 0x02023A14,
}
local profile_name = prof.CFRU and "rr" or (prof == PROFILES.ap and "ap" or "vanilla")
local bmon_base = BMON_ADDRS[profile_name]
if bmon_base then
    local bmon_size = prof.CFRU and 0x60 or 0x58
    -- Battler 0 = player active
    local b0_species = mem_r16(bmon_base)
    local b0_ability = mem_r8(bmon_base + 0x20)
    local b0_hp      = mem_r16(bmon_base + 0x28)
    print(string.format("  Battler 0 (player): species=%d ability=%d hp=%d", b0_species, b0_ability, b0_hp))
    -- Battler 1 = enemy active
    local b1 = bmon_base + bmon_size
    local b1_species = mem_r16(b1)
    local b1_ability = mem_r8(b1 + 0x20)
    local b1_hp      = mem_r16(b1 + 0x28)
    print(string.format("  Battler 1 (enemy):  species=%d ability=%d hp=%d", b1_species, b1_ability, b1_hp))
else
    print("  (unknown profile)")
end

print("\n=== Done ===")
print("If gBaseStats is wrong, update PROFILES.ap.BASESTATS_ADDR in memory.lua")
