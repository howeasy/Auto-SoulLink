--- memory_gb.lua — Shared Game Boy / Game Boy Color memory module for SLink
--- Platform I/O, character encoding, and profile-driven party/box reading.
--- Used by Gen 1 (RBY) and Gen 2 (GSC) game clients.

local M = {}

-- ═══ Platform I/O (100% reusable Gen 1 and Gen 2) ═══

local mem_r8  = memory.read_u8
local mem_w8  = memory.write_u8
local mem_r16 = memory.read_u16_le
local mem_w16 = memory.write_u16_le

-- Auto-detect memory domain: prefer "System Bus", fall back to others
local MEM_DOMAIN = "System Bus"
do
    local domains = memory.getmemorydomainlist()
    local found = false
    for _, d in ipairs(domains) do
        if d == "System Bus" then found = true; break end
    end
    if not found then
        -- Gambatte core may use different domain names
        for _, d in ipairs(domains) do
            if d == "Main RAM" or d == "CartRAM" or d == "WRAM" then
                MEM_DOMAIN = d
                break
            end
        end
    end
    print("[memory_gb] Using memory domain: " .. MEM_DOMAIN)
    print("[memory_gb] Available domains: " .. table.concat(domains, ", "))
end

function M.read_u8(addr)
    return mem_r8(addr, MEM_DOMAIN)
end

function M.write_u8(addr, val)
    mem_w8(addr, val, MEM_DOMAIN)
end

function M.read_u16_be(addr)
    return M.read_u8(addr) * 256 + M.read_u8(addr + 1)
end

function M.write_u16_be(addr, val)
    M.write_u8(addr, math.floor(val / 256) % 256)
    M.write_u8(addr + 1, val % 256)
end

-- ═══ SRAM / CartRAM Access (for PC box data in Gen 1/2) ═══
-- On GB/GBC, SRAM (A000-BFFF on System Bus) is exposed as "CartRAM" domain.
-- CartRAM is a flat address space: bank0 at 0x0000, bank1 at 0x2000, etc.
-- Box addresses in profiles use System Bus addressing (0xA000+offset_in_bank).
-- To convert: CartRAM offset = sram_bank * 0x2000 + (system_bus_addr - 0xA000)

local SRAM_DOMAIN = "CartRAM"
local SRAM_BASE = 0xA000       -- System Bus base for SRAM window
local SRAM_BANK_SIZE = 0x2000  -- 8KB per SRAM bank
M.SRAM_BANK = 0               -- Set by profile (Crystal active box = bank 1)

function M.sram_read_u8(addr)
    local offset = M.SRAM_BANK * SRAM_BANK_SIZE + (addr - SRAM_BASE)
    return mem_r8(offset, SRAM_DOMAIN)
end

function M.sram_write_u8(addr, val)
    local offset = M.SRAM_BANK * SRAM_BANK_SIZE + (addr - SRAM_BASE)
    mem_w8(offset, val, SRAM_DOMAIN)
end

function M.sram_read_u16_be(addr)
    return M.sram_read_u8(addr) * 256 + M.sram_read_u8(addr + 1)
end

function M.sram_write_u16_be(addr, val)
    M.sram_write_u8(addr, math.floor(val / 256) % 256)
    M.sram_write_u8(addr + 1, val % 256)
end

-- ═══ Character Encoding (shared Gen 1/2) ═══

M._CHARSET = {
    [0x50] = "",   -- string terminator
    [0x7F] = " ",  -- space
    -- uppercase A-Z: 0x80-0x99
    [0x80] = "A", [0x81] = "B", [0x82] = "C", [0x83] = "D", [0x84] = "E",
    [0x85] = "F", [0x86] = "G", [0x87] = "H", [0x88] = "I", [0x89] = "J",
    [0x8A] = "K", [0x8B] = "L", [0x8C] = "M", [0x8D] = "N", [0x8E] = "O",
    [0x8F] = "P", [0x90] = "Q", [0x91] = "R", [0x92] = "S", [0x93] = "T",
    [0x94] = "U", [0x95] = "V", [0x96] = "W", [0x97] = "X", [0x98] = "Y",
    [0x99] = "Z",
    -- lowercase a-z: 0xA0-0xB9
    [0xA0] = "a", [0xA1] = "b", [0xA2] = "c", [0xA3] = "d", [0xA4] = "e",
    [0xA5] = "f", [0xA6] = "g", [0xA7] = "h", [0xA8] = "i", [0xA9] = "j",
    [0xAA] = "k", [0xAB] = "l", [0xAC] = "m", [0xAD] = "n", [0xAE] = "o",
    [0xAF] = "p", [0xB0] = "q", [0xB1] = "r", [0xB2] = "s", [0xB3] = "t",
    [0xB4] = "u", [0xB5] = "v", [0xB6] = "w", [0xB7] = "x", [0xB8] = "y",
    [0xB9] = "z",
    -- special chars
    [0xE0] = "'",  -- apostrophe
    [0xE1] = "P",  -- PK (part of "POKé")
    [0xE2] = "M",  -- MN
    [0xE3] = "-",  -- dash
    [0xE6] = "?",
    [0xE7] = "!",
    [0xE8] = ".",  -- period
    [0xEF] = "♂",
    [0xF5] = "♀",
    -- digits 0-9: 0xF6-0xFF
    [0xF6] = "0", [0xF7] = "1", [0xF8] = "2", [0xF9] = "3", [0xFA] = "4",
    [0xFB] = "5", [0xFC] = "6", [0xFD] = "7", [0xFE] = "8", [0xFF] = "9",
}

function M.decodeString(addr, maxLen)
    local chars = {}
    for i = 0, maxLen - 1 do
        local b = M.read_u8(addr + i)
        if b == 0x50 then break end
        local ch = M._CHARSET[b]
        if ch then
            chars[#chars + 1] = ch
        else
            chars[#chars + 1] = "?"
        end
    end
    return table.concat(chars)
end

-- ═══ Profile System ═══
-- The game module provides a PROFILES table. M.initProfile() applies it.

M.profile = nil

function M.initProfile(game_module, variant)
    local prof = game_module.PROFILES[variant]
    if not prof then
        error("No profile for variant: " .. tostring(variant))
    end
    M.profile = prof
    -- Copy key addresses to module level for fast access
    M.PARTY_COUNT_ADDR    = prof.party_count_addr
    M.PARTY_SPECIES_ADDR  = prof.party_species_addr
    M.PARTY_BASE_ADDR     = prof.party_base_addr
    M.PARTY_OT_NAMES_ADDR = prof.party_ot_names_addr
    M.PARTY_NICKS_ADDR    = prof.party_nicks_addr
    M.PARTY_STRUCT_SIZE   = prof.party_struct_size or 44  -- Gen 1 default
    M.BOX_COUNT_ADDR      = prof.box_count_addr
    M.BOX_SPECIES_ADDR    = prof.box_species_addr
    M.BOX_BASE_ADDR       = prof.box_base_addr
    M.BOX_OT_NAMES_ADDR   = prof.box_ot_names_addr
    M.BOX_NICKS_ADDR      = prof.box_nicks_addr
    M.BOX_STRUCT_SIZE     = prof.box_struct_size or 33  -- Gen 1 default
    M.BOX_MAX_MONS        = prof.box_max_mons or 20
    M.BAG_COUNT_ADDR      = prof.bag_count_addr
    M.BAG_ITEMS_ADDR      = prof.bag_items_addr
    M.BAG_MAX_ITEMS       = prof.bag_max_items or 20
    M.BATTLE_FLAG_ADDR    = prof.battle_flag_addr
    M.MAP_ID_ADDR         = prof.map_id_addr
    M.PLAYER_NAME_ADDR    = prof.player_name_addr
    M.PLAYER_ID_ADDR      = prof.player_id_addr
    M.BALL_ITEM_IDS       = prof.ball_item_ids or {0x01, 0x02, 0x03, 0x04}
    -- Enemy party
    M.ENEMY_COUNT_ADDR    = prof.enemy_count_addr
    M.ENEMY_BASE_ADDR     = prof.enemy_base_addr
    M.ENEMY_SPECIES_LIST_ADDR = prof.enemy_species_list_addr
    -- Active battle enemy mon addresses
    M.ENEMY_MON_SPECIES_ADDR = prof.enemy_mon_species_addr
    M.ENEMY_MON_HP_ADDR      = prof.enemy_mon_hp_addr
    M.ENEMY_MON_LEVEL_ADDR   = prof.enemy_mon_level_addr
    M.ENEMY_MON_MAXHP_ADDR   = prof.enemy_mon_maxhp_addr
    -- Badges
    M.BADGES_ADDR            = prof.badges_addr
    M.KANTO_BADGES_ADDR      = prof.kanto_badges_addr  -- Gen 2 only (nil for Gen 1)
    -- Gen 2: 2-byte map addressing (mapGroup + mapNumber)
    M.MAP_GROUP_ADDR         = prof.map_group_addr     -- nil for Gen 1
    M.MAP_NUMBER_ADDR        = prof.map_number_addr    -- nil for Gen 1
    M.USES_MAP_GROUP         = prof.uses_map_group or false
    -- Gen 2: held item offset (nil for Gen 1)
    M.HELD_ITEM_OFFSET       = prof.held_item_offset
    -- Gen 2: species ID that marks a party slot as an egg (0xFD in pokecrystal). Nil for Gen 1.
    M.IS_EGG_SPECIES         = prof.is_egg_species
    -- Generation tag for conditional logic
    M.GENERATION             = prof.generation or 1
    -- DV offsets within party struct
    M.DV_OFFSET_1         = prof.dv_offset_1 or 0x1B  -- Atk/Def DVs
    M.DV_OFFSET_2         = prof.dv_offset_2 or 0x1C  -- Spd/Spc DVs
    -- OT ID offset within party struct
    M.OTID_OFFSET         = prof.otid_offset or 0x0C
    -- Species offset in party struct
    M.SPECIES_OFFSET      = prof.species_offset or 0x00
    -- HP offsets
    M.HP_OFFSET           = prof.hp_offset or 0x01      -- current HP (2 bytes BE)
    M.MAXHP_OFFSET        = prof.maxhp_offset or 0x22   -- max HP (2 bytes BE)
    M.LEVEL_OFFSET        = prof.level_offset or 0x21   -- actual level
    -- Status condition offset within party struct (u8)
    M.STATUS_OFFSET       = prof.status_offset or 0x04
    -- Status condition offset within active enemy battle struct (u8)
    M.ENEMY_MON_STATUS_OFFSET = prof.enemy_status_offset or 0x04
    -- Box in SRAM flag: if true, box addresses are in CartRAM domain (Gen 1/2 GBC)
    M.BOX_IN_SRAM         = prof.box_in_sram or false
    M.SRAM_BANK           = prof.sram_bank or 0
    -- Stat-stage addresses + layout (Phase 2). Nil-safe — clients only call helpers when set.
    M.PLAYER_STAT_STAGES_ADDR = prof.player_stat_stages_addr
    M.ENEMY_STAT_STAGES_ADDR  = prof.enemy_stat_stages_addr
    M.STAT_STAGES_COUNT       = prof.stat_stages_count or 0
    M.STAT_STAGES_LAYOUT      = prof.stat_stages_layout or "gen1"
    -- Moves + PP within party struct (Phase 3). pp_encoding="raw" (Gen 1, simple
    -- byte) or "ppup_packed" (Gen 2, top 2 bits = PP-Up count, bottom 6 = current PP).
    M.MOVES_OFFSET            = prof.moves_offset
    M.PP_OFFSET               = prof.pp_offset
    M.PP_ENCODING             = prof.pp_encoding or "raw"
    -- Enemy battle struct moves + PP (Phase 4). Different from party struct in Gen 2.
    M.ENEMY_BATTLE_MOVES_ADDR = prof.enemy_battle_moves_addr
    M.ENEMY_BATTLE_PP_ADDR    = prof.enemy_battle_pp_addr
    M.ENEMY_BATTLE_PP_ENCODING = prof.enemy_battle_pp_encoding or "raw"
    -- Trainer class / index in trainer battles (Phase 5).
    M.TRAINER_CLASS_ADDR      = prof.trainer_class_addr
    M.TRAINER_ID_ADDR         = prof.trainer_id_addr
end

-- ═══ Box Memory Helpers (routes to SRAM when BOX_IN_SRAM is set) ═══

function M.box_read_u8(addr)
    if M.BOX_IN_SRAM then return M.sram_read_u8(addr) end
    return M.read_u8(addr)
end

function M.box_write_u8(addr, val)
    if M.BOX_IN_SRAM then M.sram_write_u8(addr, val) return end
    M.write_u8(addr, val)
end

function M.box_read_u16_be(addr)
    if M.BOX_IN_SRAM then return M.sram_read_u16_be(addr) end
    return M.read_u16_be(addr)
end

function M.box_write_u16_be(addr, val)
    if M.BOX_IN_SRAM then M.sram_write_u16_be(addr, val) return end
    M.write_u16_be(addr, val)
end

-- ═══ Party Reading ═══

function M.getPartyCount()
    return M.read_u8(M.PARTY_COUNT_ADDR)
end

function M.monKey(base)
    -- Gen 1 key format: DDDD:TTTT:II
    -- DDDD = 2 DV bytes as 4 hex chars
    -- TTTT = 2-byte OT ID (big-endian) as 4 hex chars
    -- II = internal species index as 2 hex chars
    local dv1 = M.read_u8(base + M.DV_OFFSET_1)
    local dv2 = M.read_u8(base + M.DV_OFFSET_2)
    local otid = M.read_u16_be(base + M.OTID_OFFSET)
    local species = M.read_u8(base + M.SPECIES_OFFSET)
    return string.format("%02X%02X:%04X:%02X", dv1, dv2, otid, species)
end

-- Cache for monKey to avoid redundant string.format calls
M._mk_cache = {}  -- slot -> {dv1, dv2, otid, species, key_str}

function M.monKeyCached(slot, base)
    local dv1 = M.read_u8(base + M.DV_OFFSET_1)
    local dv2 = M.read_u8(base + M.DV_OFFSET_2)
    local otid = M.read_u16_be(base + M.OTID_OFFSET)
    local species = M.read_u8(base + M.SPECIES_OFFSET)
    local c = M._mk_cache[slot]
    if c and c.dv1 == dv1 and c.dv2 == dv2 and c.otid == otid and c.species == species then
        return c.key_str
    end
    local key = string.format("%02X%02X:%04X:%02X", dv1, dv2, otid, species)
    M._mk_cache[slot] = { dv1 = dv1, dv2 = dv2, otid = otid, species = species, key_str = key }
    return key
end

function M.readPartySlot(slot)
    local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local species_idx = M.read_u8(base + M.SPECIES_OFFSET)
    if species_idx == 0 or species_idx == 0xFF then
        return nil
    end
    local hp = M.read_u16_be(base + M.HP_OFFSET)
    local maxHP = M.read_u16_be(base + M.MAXHP_OFFSET)
    local level = M.read_u8(base + M.LEVEL_OFFSET)
    local key = M.monKeyCached(slot, base)

    local result = {
        key = key,
        hp = hp,
        maxHP = maxHP,
        level = level,
        species_index = species_idx,
        slot = slot,
        status_cond = M.read_u8(base + M.STATUS_OFFSET),
    }
    -- Gen 2: include held item
    if M.HELD_ITEM_OFFSET then
        result.held_item = M.read_u8(base + M.HELD_ITEM_OFFSET)
    end
    -- Gen 2: flag eggs (species == 0xFD per pret/pokecrystal constants/pokemon_constants.asm)
    if M.IS_EGG_SPECIES and species_idx == M.IS_EGG_SPECIES then
        result.is_egg = true
    end
    return result
end

function M.readPartyNickname(slot)
    return M.decodeString(M.PARTY_NICKS_ADDR + slot * 11, 11)
end

function M.readPartyOTName(slot)
    return M.decodeString(M.PARTY_OT_NAMES_ADDR + slot * 11, 11)
end

-- ═══ Box Mon Reading ═══

function M.readBoxSlot(slot)
    local base = M.BOX_BASE_ADDR + slot * M.BOX_STRUCT_SIZE
    local species_idx = M.box_read_u8(base + M.SPECIES_OFFSET)
    if species_idx == 0 or species_idx == 0xFF then
        return nil
    end
    -- Build monKey from box data using box_read helpers
    local dv1 = M.box_read_u8(base + M.DV_OFFSET_1)
    local dv2 = M.box_read_u8(base + M.DV_OFFSET_2)
    local otid = M.box_read_u8(base + M.OTID_OFFSET) * 256 + M.box_read_u8(base + M.OTID_OFFSET + 1)
    local key = string.format("%02X%02X:%04X:%02X", dv1, dv2, otid, species_idx)
    local result = {
        key = key,
        species_index = species_idx,
        slot = slot,
    }
    -- Gen 2: include held item from box struct
    if M.HELD_ITEM_OFFSET then
        local held_offset = M.profile and M.profile.box_held_item_offset or M.HELD_ITEM_OFFSET
        result.held_item = M.box_read_u8(base + held_offset)
    end
    -- Gen 2: flag eggs in boxes (eggs can be moved to PC like normal mons)
    if M.IS_EGG_SPECIES and species_idx == M.IS_EGG_SPECIES then
        result.is_egg = true
    end
    return result
end

function M.getBoxCount()
    return M.box_read_u8(M.BOX_COUNT_ADDR)
end

function M.readBoxNickname(slot)
    if M.BOX_IN_SRAM then
        -- Decode string from SRAM domain
        local addr = M.BOX_NICKS_ADDR + slot * 11
        local chars = {}
        for i = 0, 10 do
            local b = M.sram_read_u8(addr + i)
            if b == 0x50 then break end
            local ch = M._CHARSET[b]
            chars[#chars + 1] = ch or "?"
        end
        return table.concat(chars)
    end
    return M.decodeString(M.BOX_NICKS_ADDR + slot * 11, 11)
end

-- ═══ Enemy Party Reading ═══

function M.getEnemyCount()
    return M.read_u8(M.ENEMY_COUNT_ADDR)
end

function M.readEnemySlot(slot)
    local base = M.ENEMY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local species_idx = M.read_u8(base + M.SPECIES_OFFSET)
    if species_idx == 0 or species_idx == 0xFF then
        return nil
    end
    local hp = M.read_u16_be(base + M.HP_OFFSET)
    local maxHP = M.read_u16_be(base + M.MAXHP_OFFSET)
    local level = M.read_u8(base + M.LEVEL_OFFSET)
    return {
        hp = hp,
        maxHP = maxHP,
        level = level,
        species_index = species_idx,
        slot = slot,
    }
end

--- Read the ACTIVE enemy battle mon (wEnemyMon).
-- This is populated for both wild and trainer battles (the currently active foe).
-- For trainer battles, use the enemy species list for full team info.
-- party_pos (offset +0x03 in battle_struct) indicates which enemy team slot is active.
function M.readActiveBattleMon()
    local species_idx = M.read_u8(M.ENEMY_MON_SPECIES_ADDR)
    if species_idx == 0 or species_idx == 0xFF then
        return nil
    end
    local hp    = M.read_u16_be(M.ENEMY_MON_HP_ADDR)
    local maxHP = M.read_u16_be(M.ENEMY_MON_MAXHP_ADDR)
    local level = M.read_u8(M.ENEMY_MON_LEVEL_ADDR)
    -- PartyPos at battle_struct offset +0x03 (0-indexed slot within trainer's team)
    local party_pos = M.read_u8(M.ENEMY_MON_SPECIES_ADDR + 0x03)
    local status_cond = M.read_u8(M.ENEMY_MON_SPECIES_ADDR + M.ENEMY_MON_STATUS_OFFSET)
    return {
        hp = hp,
        maxHP = maxHP,
        level = level,
        species_index = species_idx,
        party_pos = party_pos,
        slot = 0,
        status_cond = status_cond,
    }
end

--- Read enemy team species from the species list (populated for trainer battles).
-- Returns array of internal species indices (up to enemy count).
function M.getEnemySpeciesList()
    local count = M.getEnemyCount()
    if count < 1 or count > 6 then return {} end
    local list = {}
    for i = 0, count - 1 do
        list[i + 1] = M.read_u8(M.ENEMY_SPECIES_LIST_ADDR + i)
    end
    return list
end

-- ═══ Bag / Pokéball Detection ═══

function M.hasPokeballs()
    local count = M.read_u8(M.BAG_COUNT_ADDR)
    if count > M.BAG_MAX_ITEMS then return false end  -- garbage protection
    for i = 0, count - 1 do
        local itemId = M.read_u8(M.BAG_ITEMS_ADDR + i * 2)
        local qty = M.read_u8(M.BAG_ITEMS_ADDR + i * 2 + 1)
        if qty > 0 and qty <= 99 then
            for _, ballId in ipairs(M.BALL_ITEM_IDS) do
                if itemId == ballId then return true end
            end
        end
    end
    return false
end

function M.countPokeballs()
    local total = 0
    local count = M.read_u8(M.BAG_COUNT_ADDR)
    if count > M.BAG_MAX_ITEMS then return 0 end  -- garbage protection
    for i = 0, count - 1 do
        local itemId = M.read_u8(M.BAG_ITEMS_ADDR + i * 2)
        local qty = M.read_u8(M.BAG_ITEMS_ADDR + i * 2 + 1)
        if qty > 0 and qty <= 99 then
            for _, ballId in ipairs(M.BALL_ITEM_IDS) do
                if itemId == ballId then total = total + qty end
            end
        end
    end
    return total
end

-- ═══ Battle State ═══

function M.isInBattle()
    return M.read_u8(M.BATTLE_FLAG_ADDR) ~= 0
end

function M.isWildBattle()
    return M.read_u8(M.BATTLE_FLAG_ADDR) == 1
end

function M.isTrainerBattle()
    return M.read_u8(M.BATTLE_FLAG_ADDR) == 2
end

-- ═══ Map ═══

function M.getCurrentMap()
    if M.USES_MAP_GROUP then
        -- Gen 2: return composite mapGroup * 256 + mapNumber
        return M.read_u8(M.MAP_GROUP_ADDR) * 256 + M.read_u8(M.MAP_NUMBER_ADDR)
    end
    return M.read_u8(M.MAP_ID_ADDR)
end

--- Read 2-byte map address as separate group and number (Gen 2 only).
-- Returns mapGroup, mapNumber. For Gen 1, returns 0, mapId.
function M.getMapGroupAndNumber()
    if M.USES_MAP_GROUP then
        return M.read_u8(M.MAP_GROUP_ADDR), M.read_u8(M.MAP_NUMBER_ADDR)
    end
    return 0, M.read_u8(M.MAP_ID_ADDR)
end

-- ═══ Player Info ═══

function M.readPlayerName()
    return M.decodeString(M.PLAYER_NAME_ADDR, 11)
end

function M.readPlayerId()
    return M.read_u16_be(M.PLAYER_ID_ADDR)
end

--- Read obtained badges as a count (0-8 for Gen 1, 0-16 for Gen 2).
function M.readBadgeCount()
    if not M.BADGES_ADDR then return 0 end
    local bitfield = M.read_u8(M.BADGES_ADDR)
    local count = 0
    for i = 0, 7 do
        if (bitfield & (1 << i)) ~= 0 then
            count = count + 1
        end
    end
    -- Gen 2: add Kanto badges
    if M.KANTO_BADGES_ADDR then
        local kanto = M.read_u8(M.KANTO_BADGES_ADDR)
        for i = 0, 7 do
            if (kanto & (1 << i)) ~= 0 then
                count = count + 1
            end
        end
    end
    return count
end

--- Read the primary badge bitmask (Johto for Gen 2, all 8 for Gen 1).
function M.readJohtoBadges()
    if not M.BADGES_ADDR then return 0 end
    return M.read_u8(M.BADGES_ADDR)
end

--- Read the Kanto badge bitmask (Gen 2 only; returns 0 for Gen 1).
function M.readKantoBadges()
    if not M.KANTO_BADGES_ADDR then return 0 end
    return M.read_u8(M.KANTO_BADGES_ADDR)
end

-- ═══ HP Writing (Force Faint) ═══

function M.forceFaint(slot)
    local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    M.write_u16_be(base + M.HP_OFFSET, 0)
end

-- ═══ ROM Validation ═══

function M.validateROM()
    local partyCount = M.getPartyCount()
    if partyCount > 6 then
        return false, "Party count > 6: " .. partyCount
    end
    -- NOTE: Battle mode check removed — 0xD22D is unreliable for Crystal
    -- (reads as 2 during intro, may read > 2 during gameplay transitions).
    -- The mapGroup + playerID checks are sufficient for Gen 2 intro gating.
    if M.USES_MAP_GROUP then
        -- Gen 2: validate mapGroup is in reasonable range
        -- Crystal map groups are 1-26; group 0 is never valid in-game.
        -- During intro/title, mapGroup reads as 0 (uninitialized).
        local g, n = M.getMapGroupAndNumber()
        if g == 0 or g > 26 then
            return false, "Map group out of range: " .. g
        end

        -- Gen 2: verify player ID is assigned (0 = pre-game state)
        if M.PLAYER_ID_ADDR then
            local pid = M.read_u16_be(M.PLAYER_ID_ADDR)
            if pid == 0 then
                return false, "Player ID is 0 (pre-game)"
            end
        end
    else
        -- Gen 1: single-byte map ID
        local mapId = M.getCurrentMap()
        if mapId > 0xF7 and mapId ~= 0xFF then
            return false, "Map ID out of range: " .. mapId
        end
    end
    if partyCount > 0 and M.PARTY_SPECIES_ADDR then
        local firstSpecies = M.read_u8(M.PARTY_SPECIES_ADDR)
        if firstSpecies == 0 then
            return false, "First party species is 0 with count > 0"
        end
    end
    return true, "OK"
end

-- ═══ Invariant Key (DVs + OTID, for evolution matching) ═══

function M.invariantKey(base)
    -- Returns DVs:OTID portion for evolution matching (species changes on evolve)
    local dv1 = M.read_u8(base + M.DV_OFFSET_1)
    local dv2 = M.read_u8(base + M.DV_OFFSET_2)
    local otid = M.read_u16_be(base + M.OTID_OFFSET)
    return string.format("%02X%02X:%04X", dv1, dv2, otid)
end

-- ═══ Box Scanning ═══

--- Find a mon by key across all slots in the current box.
-- Returns box_slot (0-based) or nil.
function M.scanBoxForKey(key)
    local count = M.getBoxCount()
    for i = 0, math.min(count, M.BOX_MAX_MONS) - 1 do
        local base = M.BOX_BASE_ADDR + i * M.BOX_STRUCT_SIZE
        local sp = M.box_read_u8(base + M.SPECIES_OFFSET)
        if sp ~= 0 and sp ~= 0xFF then
            -- Build monKey using box domain reads
            local dv1 = M.box_read_u8(base + M.DV_OFFSET_1)
            local dv2 = M.box_read_u8(base + M.DV_OFFSET_2)
            local otid = M.box_read_u8(base + M.OTID_OFFSET) * 256 + M.box_read_u8(base + M.OTID_OFFSET + 1)
            local k = string.format("%02X%02X:%04X:%02X", dv1, dv2, otid, sp)
            if k == key then return i end
        end
    end
    return nil
end

-- ═══ Party/Box Transfer (Quarantine & Sync) ═══

--- Copy n bytes from src to dst in WRAM.
local function memcpy(dst, src, n)
    for i = 0, n - 1 do
        M.write_u8(dst + i, M.read_u8(src + i))
    end
end

--- Zero n bytes starting at addr.
local function memzero(addr, n)
    for i = 0, n - 1 do
        M.write_u8(addr + i, 0)
    end
end

--- Copy n bytes from party (WRAM) to box (SRAM or WRAM depending on BOX_IN_SRAM).
local function memcpy_party_to_box(box_dst, party_src, n)
    for i = 0, n - 1 do
        M.box_write_u8(box_dst + i, M.read_u8(party_src + i))
    end
end

--- Copy n bytes from box (SRAM) to party (WRAM).
local function memcpy_box_to_party(party_dst, box_src, n)
    for i = 0, n - 1 do
        M.write_u8(party_dst + i, M.box_read_u8(box_src + i))
    end
end

--- Copy n bytes within box (SRAM to SRAM).
local function memcpy_box(dst, src, n)
    for i = 0, n - 1 do
        M.box_write_u8(dst + i, M.box_read_u8(src + i))
    end
end

--- Zero n bytes in box.
local function memzero_box(addr, n)
    for i = 0, n - 1 do
        M.box_write_u8(addr + i, 0)
    end
end

--- Deposit party slot to the current PC box.
-- Returns true on success, false + error string on failure.
function M.depositPartyMon(slot)
    local pcount = M.getPartyCount()
    if pcount <= 1 then
        return false, "last mon in party"
    end
    if slot < 0 or slot >= pcount then
        return false, "invalid slot"
    end
    local bcount = M.getBoxCount()
    if bcount >= M.BOX_MAX_MONS then
        return false, "box full"
    end

    local party_base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local species = M.read_u8(party_base + M.SPECIES_OFFSET)

    -- 1. Write mon into box slot (box struct = first BOX_STRUCT_SIZE bytes of party struct)
    local box_dst = M.BOX_BASE_ADDR + bcount * M.BOX_STRUCT_SIZE
    memcpy_party_to_box(box_dst, party_base, M.BOX_STRUCT_SIZE)

    -- 2. Copy OT name (11 bytes) from party (WRAM) to box (SRAM)
    local party_ot = M.PARTY_OT_NAMES_ADDR + slot * 11
    local box_ot = M.BOX_OT_NAMES_ADDR + bcount * 11
    memcpy_party_to_box(box_ot, party_ot, 11)

    -- 3. Copy nickname (11 bytes) from party (WRAM) to box (SRAM)
    local party_nick = M.PARTY_NICKS_ADDR + slot * 11
    local box_nick = M.BOX_NICKS_ADDR + bcount * 11
    memcpy_party_to_box(box_nick, party_nick, 11)

    -- 4. Update box species list and count
    M.box_write_u8(M.BOX_SPECIES_ADDR + bcount, species)
    M.box_write_u8(M.BOX_SPECIES_ADDR + bcount + 1, 0xFF)  -- terminator
    M.box_write_u8(M.BOX_COUNT_ADDR, bcount + 1)

    -- 5. Remove from party: shift remaining mons left
    local new_pcount = pcount - 1
    for i = slot, new_pcount - 1 do
        -- Shift struct
        memcpy(M.PARTY_BASE_ADDR + i * M.PARTY_STRUCT_SIZE,
               M.PARTY_BASE_ADDR + (i + 1) * M.PARTY_STRUCT_SIZE,
               M.PARTY_STRUCT_SIZE)
        -- Shift OT name
        memcpy(M.PARTY_OT_NAMES_ADDR + i * 11,
               M.PARTY_OT_NAMES_ADDR + (i + 1) * 11, 11)
        -- Shift nickname
        memcpy(M.PARTY_NICKS_ADDR + i * 11,
               M.PARTY_NICKS_ADDR + (i + 1) * 11, 11)
    end

    -- Zero the vacated last slot
    memzero(M.PARTY_BASE_ADDR + new_pcount * M.PARTY_STRUCT_SIZE, M.PARTY_STRUCT_SIZE)
    memzero(M.PARTY_OT_NAMES_ADDR + new_pcount * 11, 11)
    memzero(M.PARTY_NICKS_ADDR + new_pcount * 11, 11)

    -- 6. Rebuild party species list
    for i = 0, new_pcount - 1 do
        local sp = M.read_u8(M.PARTY_BASE_ADDR + i * M.PARTY_STRUCT_SIZE + M.SPECIES_OFFSET)
        M.write_u8(M.PARTY_SPECIES_ADDR + i, sp)
    end
    M.write_u8(M.PARTY_SPECIES_ADDR + new_pcount, 0xFF)  -- terminator

    -- 7. Update party count
    M.write_u8(M.PARTY_COUNT_ADDR, new_pcount)

    return true
end

--- Retrieve a mon from the current box by key and add to party.
-- Returns true on success, false + error string on failure.
function M.retrieveBoxMon(key)
    local pcount = M.getPartyCount()
    if pcount >= 6 then
        return false, "party full"
    end
    -- Find the mon in the box
    local box_slot = M.scanBoxForKey(key)
    if not box_slot then
        return false, "not found in box"
    end

    local bcount = M.getBoxCount()
    local box_base = M.BOX_BASE_ADDR + box_slot * M.BOX_STRUCT_SIZE
    local species = M.box_read_u8(box_base + M.SPECIES_OFFSET)

    -- 1. Copy box struct into party slot (first BOX_STRUCT_SIZE bytes of party struct)
    local party_dst = M.PARTY_BASE_ADDR + pcount * M.PARTY_STRUCT_SIZE
    memzero(party_dst, M.PARTY_STRUCT_SIZE)  -- zero full party struct first
    memcpy_box_to_party(party_dst, box_base, M.BOX_STRUCT_SIZE)

    -- 2. Recalculate party-only stats (level + stats at end of struct)
    -- Read level from box struct
    local box_level = M.box_read_u8(box_base + M.LEVEL_OFFSET)
    M.write_u8(party_dst + M.LEVEL_OFFSET, box_level)
    -- For HP: set current HP = max HP (full heal on retrieve)
    local hp = M.box_read_u16_be(box_base + M.HP_OFFSET)
    M.write_u16_be(party_dst + M.HP_OFFSET, hp)
    M.write_u16_be(party_dst + M.MAXHP_OFFSET, hp)

    -- 3. Copy OT name from box (SRAM) to party (WRAM)
    local box_ot = M.BOX_OT_NAMES_ADDR + box_slot * 11
    local party_ot = M.PARTY_OT_NAMES_ADDR + pcount * 11
    memcpy_box_to_party(party_ot, box_ot, 11)

    -- 4. Copy nickname from box (SRAM) to party (WRAM)
    local box_nick = M.BOX_NICKS_ADDR + box_slot * 11
    local party_nick = M.PARTY_NICKS_ADDR + pcount * 11
    memcpy_box_to_party(party_nick, box_nick, 11)

    -- 5. Update party species list and count
    M.write_u8(M.PARTY_SPECIES_ADDR + pcount, species)
    M.write_u8(M.PARTY_SPECIES_ADDR + pcount + 1, 0xFF)
    M.write_u8(M.PARTY_COUNT_ADDR, pcount + 1)

    -- 6. Remove from box: shift remaining box mons left
    local new_bcount = bcount - 1
    for i = box_slot, new_bcount - 1 do
        memcpy_box(M.BOX_BASE_ADDR + i * M.BOX_STRUCT_SIZE,
               M.BOX_BASE_ADDR + (i + 1) * M.BOX_STRUCT_SIZE,
               M.BOX_STRUCT_SIZE)
        memcpy_box(M.BOX_OT_NAMES_ADDR + i * 11,
               M.BOX_OT_NAMES_ADDR + (i + 1) * 11, 11)
        memcpy_box(M.BOX_NICKS_ADDR + i * 11,
               M.BOX_NICKS_ADDR + (i + 1) * 11, 11)
    end

    -- Zero the vacated last box slot
    memzero_box(M.BOX_BASE_ADDR + new_bcount * M.BOX_STRUCT_SIZE, M.BOX_STRUCT_SIZE)
    memzero_box(M.BOX_OT_NAMES_ADDR + new_bcount * 11, 11)
    memzero_box(M.BOX_NICKS_ADDR + new_bcount * 11, 11)

    -- 7. Rebuild box species list
    for i = 0, new_bcount - 1 do
        local sp = M.box_read_u8(M.BOX_BASE_ADDR + i * M.BOX_STRUCT_SIZE + M.SPECIES_OFFSET)
        M.box_write_u8(M.BOX_SPECIES_ADDR + i, sp)
    end
    M.box_write_u8(M.BOX_SPECIES_ADDR + new_bcount, 0xFF)

    -- 8. Update box count
    M.box_write_u8(M.BOX_COUNT_ADDR, new_bcount)

    return true
end

-- ═══ Stat Stages (Phase 2) ═══════════════════════════════════════════════
-- Read in-battle stat-stage bytes and normalize from Gen 1/2's 1..13 (neutral=7)
-- to the Gen 3 convention 0..12 (neutral=6), so the existing server-side
-- _stat_stages_html renderer Just Works.
--
-- Returns a 7-element table {atk, def, spd, satk, sdef, acc, eva}:
--   - Gen 2: 7 raw bytes read directly.
--   - Gen 1: 6 raw bytes (atk, def, spd, spc, acc, eva); the unified Special
--     stat is mirrored into both satk and sdef slots so the renderer shows
--     it consistently for both special stats.
-- Returns nil if the profile doesn't declare stat-stage addresses.

local function _read_stat_stages(base_addr)
    if not base_addr or M.STAT_STAGES_COUNT == 0 then return nil end
    if M.STAT_STAGES_LAYOUT == "gen1" then
        -- 6 raw bytes: atk, def, spd, spc, acc, eva
        local atk = M.read_u8(base_addr + 0)
        local def = M.read_u8(base_addr + 1)
        local spd = M.read_u8(base_addr + 2)
        local spc = M.read_u8(base_addr + 3)
        local acc = M.read_u8(base_addr + 4)
        local eva = M.read_u8(base_addr + 5)
        -- Sanity: refuse to emit if any value is outside 1..13 (uninitialised RAM
        -- or wrong address). Returning nil prevents the renderer from showing
        -- garbage badges.
        for _, v in ipairs({atk, def, spd, spc, acc, eva}) do
            if v < 1 or v > 13 then return nil end
        end
        -- Convert 1..13 (neutral 7) → 0..12 (neutral 6) and mirror Spc into SpA/SpD.
        return {atk - 1, def - 1, spd - 1, spc - 1, spc - 1, acc - 1, eva - 1}
    end
    -- Gen 2 layout: 7 raw bytes
    local stages = {}
    for i = 0, 6 do
        local v = M.read_u8(base_addr + i)
        if v < 1 or v > 13 then return nil end
        stages[i + 1] = v - 1
    end
    return stages
end

function M.readPlayerStatStages()
    return _read_stat_stages(M.PLAYER_STAT_STAGES_ADDR)
end

function M.readEnemyStatStages()
    return _read_stat_stages(M.ENEMY_STAT_STAGES_ADDR)
end

-- ═══ Moves + PP (Phase 3) ═════════════════════════════════════════════════
-- Read 4 move IDs and 4 PP bytes from a party/box struct at the given base
-- address. Returns {moves=[id1..id4], pp=[pp1..pp4], pp_ups=[u1..u4], max_pp=[m1..m4]}
-- or nil if the profile doesn't declare offsets.
--   - Gen 1: pp_encoding="raw", current_pp = byte, pp_ups always 0.
--   - Gen 2: pp_encoding="ppup_packed": current_pp = byte & 0x3F, pp_ups = byte >> 6.
-- max_pp is computed from base PP (provided by caller via base_pp_table) + PP-Up bonus:
--   max_pp = base_pp + (base_pp * pp_ups // 5)
-- Caller passes nil base_pp_table if not available; max_pp will then be nil.

function M.readMovesAndPP(struct_base, base_pp_table)
    if not M.MOVES_OFFSET or not M.PP_OFFSET then return nil end
    local result = {moves = {}, pp = {}, pp_ups = {}, max_pp = {}}
    for i = 0, 3 do
        local move_id = M.read_u8(struct_base + M.MOVES_OFFSET + i)
        local pp_byte = M.read_u8(struct_base + M.PP_OFFSET + i)
        result.moves[i + 1] = move_id
        if M.PP_ENCODING == "ppup_packed" then
            local cur_pp = pp_byte % 64  -- pp_byte & 0x3F
            local pp_ups = math.floor(pp_byte / 64)  -- (pp_byte >> 6) & 0x03
            result.pp[i + 1] = cur_pp
            result.pp_ups[i + 1] = pp_ups
            if base_pp_table and base_pp_table[move_id] then
                local base = base_pp_table[move_id]
                result.max_pp[i + 1] = base + math.floor(base * pp_ups / 5)
            end
        else
            result.pp[i + 1] = pp_byte
            result.pp_ups[i + 1] = 0
            if base_pp_table and base_pp_table[move_id] then
                result.max_pp[i + 1] = base_pp_table[move_id]
            end
        end
    end
    return result
end

-- Read the active enemy battler's 4 moves + 4 PP bytes. Returns
-- {moves=[id1..4], pp=[cur1..4]}, or nil if the profile doesn't declare
-- enemy_battle_moves_addr. Used by build_enemy_snapshot in battle. Enemy PP
-- is treated as raw (no PP-Up encoding) regardless of party-struct encoding —
-- the active battler's PP byte holds the live current PP and PP-Up doesn't
-- need to be displayed for display-only enemy info.
function M.readEnemyBattleMovesAndPP()
    if not M.ENEMY_BATTLE_MOVES_ADDR or not M.ENEMY_BATTLE_PP_ADDR then return nil end
    local moves, pp = {}, {}
    for i = 0, 3 do
        moves[i + 1] = M.read_u8(M.ENEMY_BATTLE_MOVES_ADDR + i)
        local b = M.read_u8(M.ENEMY_BATTLE_PP_ADDR + i)
        if M.ENEMY_BATTLE_PP_ENCODING == "ppup_packed" then
            pp[i + 1] = b % 64  -- unpack current PP
        else
            pp[i + 1] = b
        end
    end
    return {moves = moves, pp = pp, pp_bonuses = 0}
end

--- Deposit party slot directly to the dedicated memorial box (last box).
-- Gen 1: Box 12 (SRAM bank 3, CartRAM offset 0x75EA)
-- Gen 2: Box 14 (SRAM bank 3, CartRAM offset 0x79E0)
-- If no dedicated memorial box is available, falls back to depositPartyMon.
-- Returns true on success, false + error string on failure.
function M.depositMemorialMon(slot)
    local mem_off = M.profile and M.profile.memorial_box_cartram_offset
    if not mem_off then
        if M.GENERATION == 1 then
            mem_off = 0x75EA
        elseif M.GENERATION == 2 then
            mem_off = 0x79E0
        end
    end
    if not mem_off then
        return M.depositPartyMon(slot)
    end

    local pcount = M.getPartyCount()
    if pcount <= 1 then
        return false, "last mon in party"
    end
    if slot < 0 or slot >= pcount then
        return false, "invalid slot"
    end

    local mbox_count = mem_r8(mem_off, SRAM_DOMAIN)
    if mbox_count > M.BOX_MAX_MONS then
        mbox_count = 0
    end
    if mbox_count >= M.BOX_MAX_MONS then
        return M.depositPartyMon(slot)
    end

    local species_off = mem_off + 1
    local structs_off = mem_off + 1 + (M.BOX_MAX_MONS + 1)
    local ots_off     = structs_off + M.BOX_MAX_MONS * M.BOX_STRUCT_SIZE
    local nicks_off   = ots_off + M.BOX_MAX_MONS * 11

    local party_base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local species = M.read_u8(party_base + M.SPECIES_OFFSET)

    local struct_dst = structs_off + mbox_count * M.BOX_STRUCT_SIZE
    for i = 0, M.BOX_STRUCT_SIZE - 1 do
        mem_w8(struct_dst + i, M.read_u8(party_base + i), SRAM_DOMAIN)
    end

    local ot_dst   = ots_off + mbox_count * 11
    local party_ot = M.PARTY_OT_NAMES_ADDR + slot * 11
    for i = 0, 10 do
        mem_w8(ot_dst + i, M.read_u8(party_ot + i), SRAM_DOMAIN)
    end

    local nick_dst   = nicks_off + mbox_count * 11
    local party_nick = M.PARTY_NICKS_ADDR + slot * 11
    for i = 0, 10 do
        mem_w8(nick_dst + i, M.read_u8(party_nick + i), SRAM_DOMAIN)
    end

    mem_w8(species_off + mbox_count, species, SRAM_DOMAIN)
    mem_w8(species_off + mbox_count + 1, 0xFF, SRAM_DOMAIN)
    mem_w8(mem_off, mbox_count + 1, SRAM_DOMAIN)

    local new_pcount = pcount - 1
    for i = slot, new_pcount - 1 do
        memcpy(M.PARTY_BASE_ADDR + i * M.PARTY_STRUCT_SIZE,
               M.PARTY_BASE_ADDR + (i + 1) * M.PARTY_STRUCT_SIZE, M.PARTY_STRUCT_SIZE)
        memcpy(M.PARTY_OT_NAMES_ADDR + i * 11,
               M.PARTY_OT_NAMES_ADDR + (i + 1) * 11, 11)
        memcpy(M.PARTY_NICKS_ADDR + i * 11,
               M.PARTY_NICKS_ADDR + (i + 1) * 11, 11)
    end
    memzero(M.PARTY_BASE_ADDR + new_pcount * M.PARTY_STRUCT_SIZE, M.PARTY_STRUCT_SIZE)
    memzero(M.PARTY_OT_NAMES_ADDR + new_pcount * 11, 11)
    memzero(M.PARTY_NICKS_ADDR + new_pcount * 11, 11)

    for i = 0, new_pcount - 1 do
        local sp = M.read_u8(M.PARTY_BASE_ADDR + i * M.PARTY_STRUCT_SIZE + M.SPECIES_OFFSET)
        M.write_u8(M.PARTY_SPECIES_ADDR + i, sp)
    end
    M.write_u8(M.PARTY_SPECIES_ADDR + new_pcount, 0xFF)
    M.write_u8(M.PARTY_COUNT_ADDR, new_pcount)

    return true
end

return M
