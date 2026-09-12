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
    -- Retained so generic code can ASK the game module for help it may or may
    -- not offer (see the stat rebuild in retrieveBoxMon). Nothing here branches
    -- on which game it is -- the question is always "does this module provide
    -- the function", which keeps memory_gb generic.
    M._game = game_module
    M.gb_variant = variant
    -- Copy key addresses to module level for fast access
    M.PARTY_COUNT_ADDR    = prof.PARTY_COUNT_ADDR
    M.PARTY_SPECIES_ADDR  = prof.PARTY_SPECIES_ADDR
    M.PARTY_BASE_ADDR     = prof.PARTY_BASE_ADDR
    M.PARTY_OT_NAMES_ADDR = prof.PARTY_OT_NAMES_ADDR
    M.PARTY_NICKS_ADDR    = prof.PARTY_NICKS_ADDR
    M.PARTY_STRUCT_SIZE   = prof.party_struct_size or 44  -- Gen 1 default
    M.BOX_COUNT_ADDR      = prof.BOX_COUNT_ADDR
    M.BOX_SPECIES_ADDR    = prof.BOX_SPECIES_ADDR
    M.BOX_BASE_ADDR       = prof.BOX_BASE_ADDR
    M.BOX_OT_NAMES_ADDR   = prof.BOX_OT_NAMES_ADDR
    M.BOX_NICKS_ADDR      = prof.BOX_NICKS_ADDR
    M.BOX_STRUCT_SIZE     = prof.box_struct_size or 33  -- Gen 1 default
    M.BOX_MAX_MONS        = prof.box_max_mons or 20
    M.BAG_COUNT_ADDR      = prof.BAG_COUNT_ADDR
    M.BAG_ITEMS_ADDR      = prof.BAG_ITEMS_ADDR
    M.BAG_MAX_ITEMS       = prof.bag_max_items or 20
    M.BATTLE_FLAG_ADDR    = prof.BATTLE_FLAG_ADDR
    -- Optional safe-state predicates; nil on profiles that haven't opted in (see
    -- M.isInOverworld).
    M.JOY_IGNORE_ADDR     = prof.JOY_IGNORE_ADDR
    M.FONT_LOADED_ADDR    = prof.FONT_LOADED_ADDR
    M.CURRENT_BOX_NUM_ADDR = prof.CURRENT_BOX_NUM_ADDR
    -- Start of the computed stat block in the party struct (Atk/Def/Spd/Spc), which the
    -- box struct does not carry. See M.readPartyStats.
    M.STATS_OFFSET        = prof.stats_offset
    -- Gen 1 has ONE Special stat, so its Sp.Def IS its Sp.Atk and the default alias is
    -- correct. Gen 2 SPLIT them (party_struct: SpclAtk +0x2C, SpclDef +0x2E), so it declares
    -- a real spdef_offset. Without one, applyPartyStats wrote Sp.Atk over both and every
    -- withdrawal quietly corrupted Sp.Def.
    M.SPDEF_OFFSET        = prof.spdef_offset
                            or (prof.stats_offset and prof.stats_offset + 6)
    -- Rival Team Swap / Explode Mode (Gen 1: pure RAM, no ROM patch needed).
    M.CUR_OPPONENT_ADDR   = prof.CUR_OPPONENT_ADDR
    M.ENEMY_OT_NAMES_ADDR = prof.ENEMY_OT_NAMES_ADDR
    M.ENEMY_NICKS_ADDR    = prof.ENEMY_NICKS_ADDR
    M.PLAYER_SELECTED_MOVE_ADDR   = prof.PLAYER_SELECTED_MOVE_ADDR
    M.PLAYER_MOVE_LIST_INDEX_ADDR = prof.PLAYER_MOVE_LIST_INDEX_ADDR
    M.PLAYER_MON_NUMBER_ADDR = prof.PLAYER_MON_NUMBER_ADDR
    M.BATTLE_MON_MOVES_ADDR = prof.BATTLE_MON_MOVES_ADDR
    M.BATTLE_MON_PP_ADDR    = prof.BATTLE_MON_PP_ADDR
    -- Gen 1 only so far. `false` (the AP disposition) collapses to nil here so
    -- every consumer's `if M.BATTLE_MON_HP_ADDR then` guard behaves identically.
    M.BATTLE_MON_HP_ADDR    = prof.BATTLE_MON_HP_ADDR or nil
    M.MAP_ID_ADDR         = prof.MAP_ID_ADDR
    M.PLAYER_NAME_ADDR    = prof.PLAYER_NAME_ADDR
    M.PLAYER_ID_ADDR      = prof.PLAYER_ID_ADDR
    M.BALL_ITEM_IDS       = prof.ball_item_ids or {0x01, 0x02, 0x03, 0x04}
    -- Enemy party
    M.ENEMY_COUNT_ADDR    = prof.ENEMY_COUNT_ADDR
    M.ENEMY_BASE_ADDR     = prof.ENEMY_BASE_ADDR
    M.ENEMY_SPECIES_LIST_ADDR = prof.ENEMY_SPECIES_LIST_ADDR
    -- Active battle enemy mon addresses
    M.ENEMY_MON_SPECIES_ADDR = prof.ENEMY_MON_SPECIES_ADDR
    M.ENEMY_MON_HP_ADDR      = prof.ENEMY_MON_HP_ADDR
    M.ENEMY_MON_LEVEL_ADDR   = prof.ENEMY_MON_LEVEL_ADDR
    M.ENEMY_MON_MAXHP_ADDR   = prof.ENEMY_MON_MAXHP_ADDR
    -- Badges
    M.BADGES_ADDR            = prof.BADGES_ADDR
    M.KANTO_BADGES_ADDR      = prof.KANTO_BADGES_ADDR  -- Gen 2 only (nil for Gen 1)
    -- Gen 2: 2-byte map addressing (mapGroup + mapNumber)
    M.MAP_GROUP_ADDR         = prof.MAP_GROUP_ADDR     -- nil for Gen 1
    M.MAP_NUMBER_ADDR        = prof.MAP_NUMBER_ADDR    -- nil for Gen 1
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
    -- Level WITHIN THE BOX STRUCT, which is not always the party level offset.
    -- Gen 2's box struct keeps level at the same +0x1F as the party struct, so the two
    -- coincide; Gen 1 stores BoxLevel at +0x03 while the party level lives at +0x21 —
    -- past the end of the 33-byte box struct, i.e. inside the NEXT box slot.
    -- Defaults to LEVEL_OFFSET so a profile that does not set it behaves exactly as before.
    M.BOX_LEVEL_OFFSET    = prof.box_level_offset or M.LEVEL_OFFSET
    -- Status condition offset within party struct (u8)
    M.STATUS_OFFSET       = prof.status_offset or 0x04
    -- Status condition offset within active enemy battle struct (u8)
    M.ENEMY_MON_STATUS_OFFSET = prof.enemy_status_offset or 0x04
    -- Box in SRAM flag: if true, box addresses are in CartRAM domain (Gen 1/2 GBC)
    M.BOX_IN_SRAM         = prof.box_in_sram or false
    M.SRAM_BANK           = prof.sram_bank or 0
    -- Stat-stage addresses + layout (Phase 2). Nil-safe — clients only call helpers when set.
    M.PLAYER_STAT_STAGES_ADDR = prof.PLAYER_STAT_STAGES_ADDR
    M.ENEMY_STAT_STAGES_ADDR  = prof.ENEMY_STAT_STAGES_ADDR
    M.STAT_STAGES_COUNT       = prof.stat_stages_count or 0
    M.STAT_STAGES_LAYOUT      = prof.stat_stages_layout or "gen1"
    -- Moves + PP within party struct (Phase 3). pp_encoding="raw" (Gen 1, simple
    -- byte) or "ppup_packed" (Gen 2, top 2 bits = PP-Up count, bottom 6 = current PP).
    M.MOVES_OFFSET            = prof.moves_offset
    M.PP_OFFSET               = prof.pp_offset
    M.PP_ENCODING             = prof.pp_encoding or "raw"
    -- Enemy battle struct moves + PP (Phase 4). Different from party struct in Gen 2.
    M.ENEMY_BATTLE_MOVES_ADDR = prof.ENEMY_BATTLE_MOVES_ADDR
    M.ENEMY_BATTLE_PP_ADDR    = prof.ENEMY_BATTLE_PP_ADDR
    M.ENEMY_BATTLE_PP_ENCODING = prof.enemy_battle_pp_encoding or "raw"
    -- Trainer class / index in trainer battles (Phase 5).
    M.TRAINER_CLASS_ADDR      = prof.TRAINER_CLASS_ADDR
    M.TRAINER_ID_ADDR         = prof.TRAINER_ID_ADDR
    -- Sound dispatch (Phase 7). Disabled by default (addr=nil) — when a profile
    -- declares SFX_DISPATCH_ADDR, M.playSfx(id) writes id to that address.
    -- The profile also provides a sfx_ids table mapping semantic events
    -- ("capture", "faint", "whiteout", "gift") to ROM SFX constants.
    -- Without confirmed addresses, leave disabled to avoid corrupting game state.
    M.TILE_MAP_ADDR           = prof.TILE_MAP_ADDR
    M.GRASS_TILE_ADDR         = prof.GRASS_TILE_ADDR
    M.GRASS_RATE_ADDR         = prof.GRASS_RATE_ADDR
    M.STATUS_FLAGS_4_ADDR     = prof.STATUS_FLAGS_4_ADDR
    M.MOVEMENT_FLAGS_ADDR     = prof.MOVEMENT_FLAGS_ADDR
    M.SFX_DISPATCH_ADDR       = prof.SFX_DISPATCH_ADDR
    M.SFX_IDS                 = prof.sfx_ids or {}
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

-- ═══ Memorial Box Reading (mirrors depositMemorialMon's layout) ═══
-- The memorial box lives at a fixed SRAM CartRAM offset (Gen 1: 0x75EA,
-- Gen 2: 0x79E0). Layout is identical to the active box: count byte, species
-- list (BOX_MAX_MONS + 1 with terminator), mon structs, OT names, nicknames.
-- These reads complement depositMemorialMon so the server can display memorial
-- contents on the status / debug pages.

function M.getMemorialBoxOffset()
    local mem_off = M.profile and M.profile.memorial_box_cartram_offset
    if not mem_off then
        if M.GENERATION == 1 then
            mem_off = 0x75EA
        elseif M.GENERATION == 2 then
            mem_off = 0x79E0
        end
    end
    return mem_off
end

function M.getMemorialBoxCount()
    local mem_off = M.getMemorialBoxOffset()
    if not mem_off then return 0 end
    local count = mem_r8(mem_off, SRAM_DOMAIN)
    if count > M.BOX_MAX_MONS then return 0 end
    return count
end

function M.readMemorialBoxSlot(slot)
    local mem_off = M.getMemorialBoxOffset()
    if not mem_off then return nil end
    if slot < 0 or slot >= M.BOX_MAX_MONS then return nil end

    local structs_off = mem_off + 1 + (M.BOX_MAX_MONS + 1)
    local ots_off     = structs_off + M.BOX_MAX_MONS * M.BOX_STRUCT_SIZE
    local nicks_off   = ots_off + M.BOX_MAX_MONS * 11

    local base = structs_off + slot * M.BOX_STRUCT_SIZE
    local species_idx = mem_r8(base + M.SPECIES_OFFSET, SRAM_DOMAIN)
    if species_idx == 0 or species_idx == 0xFF then
        return nil
    end

    local dv1 = mem_r8(base + M.DV_OFFSET_1, SRAM_DOMAIN)
    local dv2 = mem_r8(base + M.DV_OFFSET_2, SRAM_DOMAIN)
    local otid = mem_r8(base + M.OTID_OFFSET, SRAM_DOMAIN) * 256
               + mem_r8(base + M.OTID_OFFSET + 1, SRAM_DOMAIN)
    local key = string.format("%02X%02X:%04X:%02X", dv1, dv2, otid, species_idx)

    local nick_addr = nicks_off + slot * 11
    local chars = {}
    for i = 0, 10 do
        local b = mem_r8(nick_addr + i, SRAM_DOMAIN)
        if b == 0x50 then break end
        local ch = M._CHARSET[b]
        chars[#chars + 1] = ch or "?"
    end
    local nickname = table.concat(chars)

    local result = {
        key = key,
        species_index = species_idx,
        slot = slot,
        nickname = nickname,
    }
    if M.HELD_ITEM_OFFSET then
        local held_offset = M.profile and M.profile.box_held_item_offset or M.HELD_ITEM_OFFSET
        result.held_item = mem_r8(base + held_offset, SRAM_DOMAIN)
    end
    if M.IS_EGG_SPECIES and species_idx == M.IS_EGG_SPECIES then
        result.is_egg = true
    end
    return result
end

--- Every mon key held in the STORED PC boxes, read straight from SRAM.
---
--- The client seeded `all_known_keys` from the party and the ACTIVE box only, which is a
--- keyset that changes the moment the player switches box in the PC. Reconnect with Box 5
--- open, then switch to a Box 1 holding twenty mons from an earlier session, and the next
--- lost battle made the box scanner emit twenty `capture` events -- each stamped with the
--- route the player happened to be standing on, each forming a link. Box-switching after
--- filling a box is ordinary play, so this was reachable rather than theoretical.
---
--- Layout comes from the profile, not from a generation check: the box count, stride and
--- the SRAM banks they are spread across are that cartridge's business. A profile that
--- does not describe them returns nil, and the caller keeps its old behaviour.
---
--- The current box's SRAM slot is intentionally empty. Read that box from WRAM
--- and the other eleven from SRAM; before first ChangeBox only the current box exists.
function M.storedBoxKeys()
    local sb = M.profile and M.profile.stored_boxes
    if not (sb and sb.count and sb.stride and sb.banks and sb.per_bank) then return nil end
    local current = M.getCurrentBoxNum()
    if current == nil then return nil, "invalid current box" end
    -- Before first ChangeBox, no inactive SRAM box has been initialized.
    local initialized = not M.profile.sram_box_layout or M.read_u8(M.CURRENT_BOX_NUM_ADDR) >= 0x80
    local keys = {}
    for b = 0, sb.count - 1 do
        local active = b == current
        if active or initialized then
        local bank = sb.banks[math.floor(b / sb.per_bank) + 1]
        if not bank then return nil, "missing stored box bank" end
        local box_off = bank + (b % sb.per_bank) * sb.stride
        local read = active and M.box_read_u8 or function(addr) return mem_r8(addr, SRAM_DOMAIN) end
        local count_addr = active and M.BOX_COUNT_ADDR or box_off
        local species_addr = active and M.BOX_SPECIES_ADDR or box_off + 1
        local structs = active and M.BOX_BASE_ADDR or box_off + 1 + M.BOX_MAX_MONS + 1
        local n = read(count_addr)
        if n > M.BOX_MAX_MONS then return nil, "invalid box count" end
        if read(species_addr + n) ~= 0xFF then return nil, "invalid box species terminator" end
        for i = 0, n - 1 do
            local base = structs + i * M.BOX_STRUCT_SIZE
            local sp = read(base + M.SPECIES_OFFSET)
            if sp == 0 or sp == 0xFF or read(species_addr + i) ~= sp then
                return nil, "invalid box species list"
            end
            local key = string.format("%02X%02X:%04X:%02X", read(base + M.DV_OFFSET_1),
                read(base + M.DV_OFFSET_2), read(base + M.OTID_OFFSET) * 256 + read(base + M.OTID_OFFSET + 1), sp)
            if keys[key] then return nil, "duplicate stored Pokemon key" end
            keys[key] = true
        end
        end
    end
    return keys
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

--- Is a given item id in the bag at all? Quantity is not consulted -- key items like the
--- Silph Scope are held as a single entry and some carry a quantity of 0.
function M.hasBagItem(item_id)
    if not (item_id and M.BAG_COUNT_ADDR and M.BAG_ITEMS_ADDR) then return false end
    local count = M.read_u8(M.BAG_COUNT_ADDR)
    if count > M.BAG_MAX_ITEMS then return false end     -- garbage protection
    for i = 0, count - 1 do
        if M.read_u8(M.BAG_ITEMS_ADDR + i * 2) == item_id then return true end
    end
    return false
end

-- ═══ Battle State ═══

function M.isInBattle()
    -- Per pret/pokered & pret/pokecrystal, wIsInBattle has FOUR values:
    --   0 = IN_BATTLE_NONE, 1 = IN_BATTLE_WILD, 2 = IN_BATTLE_TRAINER,
    --   -1 (0xFF) = IN_BATTLE_LOST (set during certain post-battle cleanup paths
    --   and can persist after a successful catch). Only treat 1/2 as in-battle.
    local v = M.read_u8(M.BATTLE_FLAG_ADDR)
    return v == 1 or v == 2
end

function M.isWildBattle()
    return M.read_u8(M.BATTLE_FLAG_ADDR) == 1
end

-- Legacy state flags. These alone do not certify a write: live RBY gates show
-- clear flags on the title/CONTINUE screen and during parts of nickname entry.
-- Kept for observations and existing Gen 2/AP behavior.
function M.isInOverworld()
    if M.isInBattle() then return false end
    if M.JOY_IGNORE_ADDR and M.read_u8(M.JOY_IGNORE_ADDR) ~= 0 then return false end
    if M.FONT_LOADED_ADDR and (M.read_u8(M.FONT_LOADED_ADDR) % 2) == 1 then return false end
    return true
end

-- Active PC box index (0-based). The high bit of wCurrentBoxNum is a "changed box" flag.
function M.getCurrentBoxNum()
    if not M.CURRENT_BOX_NUM_ADDR then return nil end
    local current = M.read_u8(M.CURRENT_BOX_NUM_ADDR) % 0x80
    local count = M.profile and M.profile.stored_boxes and M.profile.stored_boxes.count
    if count and current >= count then return nil end
    return current
end

-- ═══ Rival Team Swap ═══
-- wCurOpponent = trainer class + OPP_ID_OFFSET(200); this is the id the adapter's
-- rival_trainer_ids() is keyed by. nil in a wild battle or on a profile without the address.
function M.readTrainerOpponentId()
    if not M.CUR_OPPONENT_ADDR then return nil end
    local v = M.read_u8(M.CUR_OPPONENT_ADDR)
    if v == 0 then return nil end
    return v
end

-- Overwrite the enemy trainer's whole team with `blobs` (each a 66-byte array from
-- readPartyBlob: 44-byte struct + 11-byte OT + 11-byte nickname).
--
-- No encryption, no checksums, no ASLR — this is the plain byte copy that Gen 3 needed a
-- companion patch for. The engine reads everything it needs for a trainer mon out of these
-- structs on send-out: species (+0x00), current HP (+0x01), status (+0x04), moves (+0x08)
-- and level (+0x21). Stats and DVs are NOT taken from here — LoadEnemyMonData recomputes
-- them from the species header with fixed trainer DVs — so the swapped team fights at the
-- partner's levels with the partner's moves and HP, but with trainer-standard DVs.
local gen1_party_codec
local function load_gen1_party_codec()
    if gen1_party_codec then return gen1_party_codec end
    local ok, module = pcall(require, "gen1_party_codec")
    if not ok then
        local root = rawget(_G, "SLINK_ROOT") or os.getenv("SLINK_ROOT")
        ok, module = pcall(dofile, (root and (root .. "/") or "") .. "lua/gen1_party_codec.lua")
    end
    if not ok or type(module) ~= "table" or module.VERSION ~= "gen1-rby-party-v1" then
        return nil, "verified Gen1 party codec unavailable"
    end
    gen1_party_codec = module
    return module
end

-- Positive CPU checkpoint for vanilla RBY party/box operations. This is only
-- execution safety; admission, operation ownership and payload checks are separate.
local gen1_write_safety
function M.isPartyWriteSafe()
    if M.gb_variant == "red_ap" or M.gb_variant == "blue_ap" then
        -- AP's existing behavior is retained explicitly. No vanilla ROM or stack
        -- address is inherited into these relocated profiles.
        return M.isInOverworld(), "legacy AP state flags"
    end
    if not gen1_write_safety then
        local ok, module = pcall(require, "gen1_write_safety")
        if not ok then return false, "write checkpoint module unavailable" end
        gen1_write_safety = module
    end
    return gen1_write_safety.check(M.profile, {
        domains = memory.getmemorydomainlist,
        read_u8 = mem_r8,
        register = function(name) return emu.getregister(name) end,
    })
end

function M.writeEnemyParty(blobs)
    if not (M.ENEMY_COUNT_ADDR and M.ENEMY_BASE_ADDR and M.ENEMY_SPECIES_LIST_ADDR
            and M.ENEMY_OT_NAMES_ADDR and M.ENEMY_NICKS_ADDR) then
        return false, "profile lacks enemy party addresses"
    end
    if type(blobs) ~= "table" or getmetatable(blobs) ~= nil then return false, "invalid party payload" end
    local n = #blobs
    if n < 1 then return false, "no blobs" end
    if n > 6 then return false, "party count exceeds six; nothing written" end
    local struct = M.PARTY_STRUCT_SIZE

    -- VALIDATE EVERY BLOB BEFORE WRITING ANY OF THEM.
    -- The length check used to sit inside the write loop, so a payload whose third blob was
    -- short returned false with blobs 1 and 2 already copied into wEnemyMons -- and with
    -- neither the 0xFF terminator nor wEnemyPartyCount updated, because both are written
    -- after the loop. The caller reported an error and the cartridge was left mid-battle
    -- with a spliced enemy party: the engine sends out mon 3 from the stale list carrying
    -- mon 1's struct. The payload is server-supplied, so a truncated line is enough.
    local entries = 0
    for key in pairs(blobs) do
        if type(key) ~= "number" or key % 1 ~= 0 or key < 1 or key > n then
            return false, "invalid party index; nothing written"
        end
        entries = entries + 1
    end
    if entries ~= n then return false, "missing party entry; nothing written" end
    local validated = {}
    if M.GENERATION == 1 and (M.gb_variant == "red" or M.gb_variant == "blue" or M.gb_variant == "yellow") then
        local codec, reason = load_gen1_party_codec()
        if not codec then return false, reason end
        local party, error = codec.validateParty(blobs, M.gb_variant)
        if not party then return false, error .. "; nothing written" end
        for i, mon in ipairs(party) do validated[i] = mon.blob end
    else
        -- AP/other GB layouts retain their own semantics. Enforce a complete byte
        -- envelope without guessing vanilla ROM facts for a relocated profile.
        for i = 1, n do
            local blob = blobs[i]
            if type(blob) ~= "table" or getmetatable(blob) ~= nil or #blob ~= struct + 22 then
                return false, "invalid blob length; nothing written"
            end
            local copied, size = {}, 0
            for key, value in pairs(blob) do
                if type(key) ~= "number" or key % 1 ~= 0 or key < 1 or key > struct + 22
                    or type(value) ~= "number" or value % 1 ~= 0 or value < 0 or value > 255 then
                    return false, "invalid blob byte; nothing written"
                end
                copied[key], size = value, size + 1
            end
            if size ~= struct + 22 then return false, "missing blob byte; nothing written" end
            validated[i] = copied
        end
    end

    for i = 1, n do
        local b = validated[i]
        local dst = M.ENEMY_BASE_ADDR + (i - 1) * struct
        for j = 0, struct - 1 do M.write_u8(dst + j, b[j + 1]) end
        for j = 0, 10 do M.write_u8(M.ENEMY_OT_NAMES_ADDR + (i - 1) * 11 + j, b[struct + 1 + j]) end
        for j = 0, 10 do M.write_u8(M.ENEMY_NICKS_ADDR + (i - 1) * 11 + j, b[struct + 12 + j]) end
        -- The species LIST is what the engine iterates to pick the next mon; the copy
        -- inside each struct is not enough on its own.
        M.write_u8(M.ENEMY_SPECIES_LIST_ADDR + (i - 1), b[1])
    end
    M.write_u8(M.ENEMY_SPECIES_LIST_ADDR + n, 0xFF)   -- terminator
    M.write_u8(M.ENEMY_COUNT_ADDR, n)
    return true, n
end

-- ═══ Explode Mode ═══
-- Coerce the active battler into Explosion (move 153). Gen 1 takes the player's choice from
-- wPlayerSelectedMove, so this is a RAM write rather than a patched battle script.
-- Slot 0's move and PP are overwritten because the engine decrements PP by slot index and
-- would otherwise refuse a move the mon does not know.
M.MOVE_EXPLOSION = 153

-- Which party slot is currently on the field (wPlayerMonNumber), or nil if the profile
-- doesn't declare it. Explode Mode only applies to this mon — a benched partner has to
-- fall back to a plain faint.
function M.getActivePartySlot()
    if not M.PLAYER_MON_NUMBER_ADDR then return nil end
    return M.read_u8(M.PLAYER_MON_NUMBER_ADDR)
end

function M.validatePartySlot(slot)
    local count = M.getPartyCount()
    if type(count) ~= "number" or count % 1 ~= 0 or count < 1 or count > 6 then
        return false, "invalid party count"
    end
    if type(slot) ~= "number" or slot % 1 ~= 0 or slot < 0 or slot >= count then
        return false, "invalid party slot"
    end
    return true
end

function M.forceExplode(slot)
    if not (M.BATTLE_MON_MOVES_ADDR and M.PLAYER_SELECTED_MOVE_ADDR and M.PLAYER_MON_NUMBER_ADDR) then
        return false, "profile lacks explode addresses"
    end
    if not M.isInBattle() then return false, "not in battle" end
    local active = M.getActivePartySlot()
    local valid, reason = M.validatePartySlot(slot)
    if not valid then return false, reason end
    if slot ~= active then return false, "not the active battler" end
    local mv = M.MOVE_EXPLOSION
    -- ALL FOUR SLOTS, not just the first. wPlayerSelectedMove is set here, but the
    -- engine RE-DERIVES it from the move the player confirms:
    --     add hl, bc            ; hl = wBattleMonMoves + wCurrentMenuItem
    --     ld a, [hl] / ld [wPlayerSelectedMove], a
    -- (engine/battle/core.asm:2664-2668). Writing only slot 0 therefore left every
    -- other slot holding its real move, so the player escaped the coercion simply by
    -- picking the second, third or fourth one. Filling all four means any choice
    -- explodes. The mon is being deliberately killed, so losing its moveset is moot.
    for i = 0, 3 do
        M.write_u8(M.BATTLE_MON_MOVES_ADDR + i, mv)
        if M.BATTLE_MON_PP_ADDR then M.write_u8(M.BATTLE_MON_PP_ADDR + i, 5) end
    end
    -- Mirror into the party struct so a switch-out/in does not restore the old moves.
    if slot and M.PARTY_BASE_ADDR and M.MOVES_OFFSET then
        local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
        for i = 0, 3 do
            M.write_u8(base + M.MOVES_OFFSET + i, mv)
            if M.PP_OFFSET then M.write_u8(base + M.PP_OFFSET + i, 5) end
        end
    end
    if M.PLAYER_MOVE_LIST_INDEX_ADDR then M.write_u8(M.PLAYER_MOVE_LIST_INDEX_ADDR, 0) end
    M.write_u8(M.PLAYER_SELECTED_MOVE_ADDR, mv)
    return true
end

-- A whole party mon as raw bytes, for handing the partner's team to the server.
--
-- Gen 1 keeps OT names and nicknames in PARALLEL arrays rather than inside the struct, so
-- a faithful copy is three pieces, not one: 44-byte struct + 11-byte OT + 11-byte nick.
-- That composite is what the server caches and what a rival-team swap writes back, which
-- is why Gen 1's blob is 66 bytes where Gen 3's is a flat 100.
-- Returns nil if the slot is empty or the profile lacks the name arrays.
function M.readPartyBlob(slot)
    if not (M.PARTY_OT_NAMES_ADDR and M.PARTY_NICKS_ADDR) then return nil end
    local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    if M.read_u8(base + M.SPECIES_OFFSET) == 0 then return nil end
    local out = {}
    local n = 0
    for i = 0, M.PARTY_STRUCT_SIZE - 1 do n = n + 1; out[n] = M.read_u8(base + i) end
    for i = 0, 10 do n = n + 1; out[n] = M.read_u8(M.PARTY_OT_NAMES_ADDR + slot * 11 + i) end
    for i = 0, 10 do n = n + 1; out[n] = M.read_u8(M.PARTY_NICKS_ADDR + slot * 11 + i) end
    return out
end

function M.bytesToHex(bytes)
    local parts = {}
    for i = 1, #bytes do parts[i] = string.format("%02X", bytes[i]) end
    return table.concat(parts)
end

-- Inverse of bytesToHex. Returns nil for odd-length or non-hex input rather than a partial
-- decode, so a truncated blob is rejected outright instead of writing garbage into RAM.
function M.hexToBytes(s)
    if type(s) ~= "string" or #s == 0 or #s % 2 ~= 0 then return nil end
    local out = {}
    for i = 1, #s, 2 do
        local b = tonumber(s:sub(i, i + 1), 16)
        if not b then return nil end
        out[#out + 1] = b
    end
    return out
end

-- The party-only stats a box struct cannot hold, read BEFORE a deposit.
--
-- Gen 1's box struct is the first 33 bytes of the 44-byte party struct, so level (+0x21),
-- maxHP (+0x22) and the four computed stats (+0x24..+0x2B) are simply lost on deposit.
-- The engine recalculates them from DVs and StatExp when the player withdraws through the
-- PC; SLink writes the party struct directly, so it has to put them back itself. Sending
-- them to the server as `stats_cache` makes that survive a client restart, which an
-- in-memory table cannot.
--
-- Returns nil on profiles that don't declare the stat offsets, so callers can skip.
function M.validatePartyStats(stats)
    if type(stats) ~= "table" or not (stats.maxHP and stats.level and stats.attack
        and stats.defense and stats.speed and (stats.spAtk or stats.spDef)) then
        return false, "incomplete stats block (need level, maxHP and all four stats)"
    end
    for _, name in ipairs({"level", "maxHP", "attack", "defense", "speed", "spAtk", "spDef"}) do
        local value = stats[name]
        local limit = name == "level" and 100 or (M.GENERATION == 1 and 999 or 65535)
        if value ~= nil and (type(value) ~= "number" or value % 1 ~= 0 or value < 1 or value > limit) then
            return false, "out-of-range stats block"
        end
    end
    if M.GENERATION == 1 and stats.spAtk and stats.spDef and stats.spAtk ~= stats.spDef then
        return false, "inconsistent Gen 1 Special stats"
    end
    return true
end

function M.readPartyStats(slot)
    if not (M.STATS_OFFSET and M.MAXHP_OFFSET and M.LEVEL_OFFSET) then return nil end
    local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local s = M.STATS_OFFSET
    return {
        level   = M.read_u8(base + M.LEVEL_OFFSET),
        maxHP   = M.read_u16_be(base + M.MAXHP_OFFSET),
        attack  = M.read_u16_be(base + s),
        defense = M.read_u16_be(base + s + 2),
        speed   = M.read_u16_be(base + s + 4),
        spAtk   = M.read_u16_be(base + s + 6),
        -- Gen 1 has ONE Special stat, and M.SPDEF_OFFSET aliases it back onto spAtk so the
        -- shared renderer and the Gen 3-shaped stats dict need no generation branch. Gen 2
        -- split the stat and points this at its own address.
        spDef   = M.read_u16_be(base + M.SPDEF_OFFSET),
    }
end

-- Write a cached stat block back into a party slot after a retrieve.
function M.applyPartyStats(slot, stats)
    if not (stats and M.STATS_OFFSET) then return false end
    local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local s = M.STATS_OFFSET
    if stats.level  then M.write_u8(base + M.LEVEL_OFFSET, stats.level) end
    if stats.maxHP  then M.write_u16_be(base + M.MAXHP_OFFSET, stats.maxHP) end
    if stats.attack then M.write_u16_be(base + s, stats.attack) end
    if stats.defense then M.write_u16_be(base + s + 2, stats.defense) end
    if stats.speed  then M.write_u16_be(base + s + 4, stats.speed) end
    if stats.spAtk  then M.write_u16_be(base + s + 6, stats.spAtk) end
    -- In Gen 1 this address IS s+6, so the write is a harmless repeat of the line above. In
    -- Gen 2 it is the only thing that restores Sp.Def at all.
    if stats.spDef  then M.write_u16_be(base + M.SPDEF_OFFSET, stats.spDef) end
    return true
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

--- Read the primary badge bitmask: all 8 badges on Gen 1, the Johto 8 on Gen 2.
---
--- This is what every client sends as `badges`, because the server decodes it bit by bit
--- (server.py:3772 dashboard strip, :5627 /stream/badges-*). Do not send a COUNT here --
--- Gen 1 did, and three badges lit Boulder+Cascade while eight lit only Rainbow.
function M.readBadgeMask()
    if not M.BADGES_ADDR then return 0 end
    return M.read_u8(M.BADGES_ADDR)
end

-- Gen 2's call sites name it for Johto; same byte, same meaning.
M.readJohtoBadges = M.readBadgeMask

--- Read the Kanto badge bitmask (Gen 2 only; returns 0 for Gen 1).
function M.readKantoBadges()
    if not M.KANTO_BADGES_ADDR then return 0 end
    return M.read_u8(M.KANTO_BADGES_ADDR)
end

-- ═══ HP Writing (Force Faint) ═══

--- Kill a party mon. Writes the party struct AND, when that mon is the one
--- currently out, the battle struct.
---
--- THE PARTY STRUCT ALONE DOES NOTHING TO THE ACTIVE BATTLER. pokered's
--- MainInBattleLoop opens every single turn with
---
---     call ReadPlayerMonCurHPAndStatus     ; engine/battle/core.asm:280
---     ld hl, wBattleMonHP
---     ld a, [hli] / or [hl] / jp z, HandlePlayerMonFainted
---
--- and ReadPlayerMonCurHPAndStatus (`:1798-1809`) copies wBattleMonHP *into* the
--- party struct — its own comment says "so it stays after battle or switching".
--- So the direction of travel is battle -> party, and a party-only write is
--- overwritten at the top of the next turn without ever being read. Faint
--- propagation simply did not apply to the mon that was out: the partner died,
--- the toast fired, and the linked mon fought on at full HP.
---
--- Writing wBattleMonHP is what the engine actually consumes; the party write
--- stays so a benched mon (and the post-battle copy-back) is still correct.
--- Returns true when the battle struct was also written, for callers that want
--- to assert the in-battle path really ran.
function M.forceFaint(slot)
    local valid, reason = M.validatePartySlot(slot)
    if not valid then return false, reason end
    local in_battle = M.BATTLE_MON_HP_ADDR and M.isInBattle and M.isInBattle()
    local active
    if in_battle then
        active = M.getActivePartySlot and M.getActivePartySlot()
        if not M.validatePartySlot(active) then return false, "invalid active battler" end
    end
    local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    M.write_u16_be(base + M.HP_OFFSET, 0)

    -- Only the active battler has a battle struct, and only in battle. Gen 2
    -- leaves BATTLE_MON_HP_ADDR unset, so this is a no-op there.
    if not in_battle or active ~= slot then return false end
    M.write_u16_be(M.BATTLE_MON_HP_ADDR, 0)
    return true
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
        -- InitPlayerData copies two RNG bytes without excluding 0000. A real
        -- nonempty party may therefore belong to player 0000. The all-zero
        -- title-screen shape still fails; this is a profile sanity check, not
        -- the separate, release-blocking proof of a safe write state.
        if M.PLAYER_ID_ADDR then
            local pid = M.read_u16_be(M.PLAYER_ID_ADDR)
            if pid == 0 and partyCount == 0 then
                return false, "Player ID is 0 and party is empty (pre-game state)"
            end
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
    if M.GENERATION == 1 then
        if count > M.BOX_MAX_MONS then return nil, "invalid box count" end
        if M.box_read_u8(M.BOX_SPECIES_ADDR + count) ~= 0xFF then
            return nil, "invalid box species terminator"
        end
    end
    local found, keys = nil, {}
    for i = 0, math.min(count, M.BOX_MAX_MONS) - 1 do
        local base = M.BOX_BASE_ADDR + i * M.BOX_STRUCT_SIZE
        local sp = M.box_read_u8(base + M.SPECIES_OFFSET)
        if M.GENERATION == 1 and (sp == 0 or sp == 0xFF
            or M.box_read_u8(M.BOX_SPECIES_ADDR + i) ~= sp
            or (M._game and M._game.toNatDex and M._game.toNatDex(sp) == 0)) then
            return nil, "invalid box species list"
        end
        if sp ~= 0 and sp ~= 0xFF then
            local dv1 = M.box_read_u8(base + M.DV_OFFSET_1)
            local dv2 = M.box_read_u8(base + M.DV_OFFSET_2)
            local otid = M.box_read_u16_be(base + M.OTID_OFFSET)
            local k = string.format("%02X%02X:%04X:%02X", dv1, dv2, otid, sp)
            if M.GENERATION == 1 and keys[k] then return nil, "duplicate current-box key" end
            keys[k] = true
            if k == key then found = i end
        end
    end
    return found
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
    if M.GENERATION == 1 and M.getCurrentBoxNum() == nil then return false, "invalid current box" end
    local pcount = M.getPartyCount()
    if pcount <= 1 then
        return false, "last mon in party"
    end
    if pcount > 6 then return false, "invalid party count" end
    if type(slot) ~= "number" or slot % 1 ~= 0 or slot < 0 or slot >= pcount then
        return false, "invalid slot"
    end
    local bcount = M.getBoxCount()
    if bcount >= M.BOX_MAX_MONS then
        return false, "box full"
    end
    local deposit_effect
    if M._game and M._game.prepareDeposit then
        local allowed, effect = M._game.prepareDeposit(M, slot)
        if not allowed then return false, effect end
        deposit_effect = effect
    end

    local party_base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local species = M.read_u8(party_base + M.SPECIES_OFFSET)

    -- 1. Write mon into box slot (box struct = first BOX_STRUCT_SIZE bytes of party struct)
    local box_dst = M.BOX_BASE_ADDR + bcount * M.BOX_STRUCT_SIZE
    if deposit_effect then M._game.applyDepositEffect(M, deposit_effect) end
    memcpy_party_to_box(box_dst, party_base, M.BOX_STRUCT_SIZE)

    -- Refresh the stored box level from the LIVE party level. Gen 1's BoxLevel (+0x03) is
    -- written at catch time and goes stale the moment the mon levels up, so copying the
    -- struct verbatim would box a mon at the level it was caught at.
    M.box_write_u8(box_dst + M.BOX_LEVEL_OFFSET, M.read_u8(party_base + M.LEVEL_OFFSET))

    -- Stash the party-only stats the box struct cannot hold, so a deposit+withdraw within
    -- one session restores correctly even before the server echoes stats_cache back. The
    -- server's copy is the durable one; this is just the same-session fallback.
    M._party_tail_cache = M._party_tail_cache or {}
    M._party_tail_cache[M.monKey(party_base)] = M.readPartyStats(slot)

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
-- `stats` (optional) is validated before writes. Gen 1 rebuilds the party-only
-- tail from ROM/experience/DVs/stat experience even when a complete cache is supplied.
function M.retrieveBoxMon(key, stats)
    if M.GENERATION == 1 and M.getCurrentBoxNum() == nil then return false, "invalid current box" end
    local pcount = M.getPartyCount()
    if pcount >= 6 then return false, "party full" end
    local bcount = M.getBoxCount()
    if bcount > M.BOX_MAX_MONS then return false, "invalid box count" end
    local box_slot, scan_error = M.scanBoxForKey(key)
    if box_slot == nil then return false, scan_error or "not found in box" end
    if M.GENERATION == 1 then
        local known, reason = M.storedBoxKeys()
        if not known then return false, reason or "storage identity unavailable" end
        if M.read_u8(M.PARTY_SPECIES_ADDR + pcount) ~= 0xFF then
            return false, "invalid party species terminator"
        end
        local party_keys = {}
        for i = 0, pcount - 1 do
            local base = M.PARTY_BASE_ADDR + i * M.PARTY_STRUCT_SIZE
            local species = M.read_u8(base + M.SPECIES_OFFSET)
            if M.read_u8(M.PARTY_SPECIES_ADDR + i) ~= species or M._game.toNatDex(species) == 0 then
                return false, "invalid party species list"
            end
            local existing = M.monKey(base)
            if party_keys[existing] or known[existing] then return false, "storage key collision" end
            party_keys[existing] = true
        end
    end
    local box_base = M.BOX_BASE_ADDR + box_slot * M.BOX_STRUCT_SIZE
    local species = M.box_read_u8(box_base + M.SPECIES_OFFSET)
    for i = 0, pcount - 1 do
        if M.monKey(M.PARTY_BASE_ADDR + i * M.PARTY_STRUCT_SIZE) == key then
            return false, "party key collision"
        end
    end

    -- Validate supplied cache data before the first write, even on a cartridge
    -- that can rebuild stats. Partial/out-of-range payloads are retryable NACKs.
    local cached = stats
    if cached == nil then cached = M._party_tail_cache and M._party_tail_cache[key] end
    if cached ~= nil then
        local valid, reason = M.validatePartyStats(cached)
        if not valid then return false, reason .. " for " .. tostring(key) end
    end
    local box_level = M.box_read_u8(box_base + M.BOX_LEVEL_OFFSET)
    if M.GENERATION == 1 and M.gb_variant ~= "red_ap" and M.gb_variant ~= "blue_ap" then
        -- _MoveMon calls CalcLevelFromExperience, then CalcStats. BoxLevel and
        -- cached party tails are not authoritative on withdrawal. Read every
        -- input from the box before writes; absent ROM evidence leaves it intact.
        local game = M._game
        if not (game and game.rebuildBoxStats and game.BOX_STAT_OFFSETS) then
            return false, "no canonical stat rebuild available"
        end
        local off, stat_exp = game.BOX_STAT_OFFSETS, {}
        for _, field in ipairs({"hp", "attack", "defense", "speed", "special"}) do
            stat_exp[field] = M.box_read_u16_be(box_base + off[field])
        end
        local experience = M.box_read_u8(box_base + M.OTID_OFFSET + 2) * 65536
            + M.box_read_u8(box_base + M.OTID_OFFSET + 3) * 256
            + M.box_read_u8(box_base + M.OTID_OFFSET + 4)
        local rebuilt = game.rebuildBoxStats(M.gb_variant, species, box_level,
            M.box_read_u16_be(box_base + off.dvs), stat_exp, experience)
        if not rebuilt then return false, "no cached stats fallback: canonical ROM/stat evidence unavailable for " .. tostring(key) end
        cached = {level = rebuilt.level, maxHP = rebuilt.hp, attack = rebuilt.attack,
            defense = rebuilt.defense, speed = rebuilt.speed, spAtk = rebuilt.special, spDef = rebuilt.special}
    elseif not cached then
        -- AP keeps the established fully validated cache path until its own
        -- base-stat ROM layout is independently verified. Never inherit RBY roots.
        return false, "no cached stats for " .. tostring(key)
    end

    -- All failure paths above are read-only. Preserve Gen 1 HP/status exactly,
    -- including HP above recomputed maxHP: canonical _MoveMon does not clamp it.
    local party_dst = M.PARTY_BASE_ADDR + pcount * M.PARTY_STRUCT_SIZE
    memzero(party_dst, M.PARTY_STRUCT_SIZE)
    memcpy_box_to_party(party_dst, box_base, M.BOX_STRUCT_SIZE)
    M.applyPartyStats(pcount, cached)
    local box_has_hp = (M.HP_OFFSET + 2) <= M.BOX_STRUCT_SIZE
    if not box_has_hp then
        M.write_u16_be(party_dst + M.HP_OFFSET, M.read_u16_be(party_dst + M.MAXHP_OFFSET))
    end
    if M._party_tail_cache then M._party_tail_cache[key] = nil end

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
--   - Gen 1: 6 raw bytes (atk, def, spd, spc, acc, eva); the unified Special stat
--     occupies the satk slot and the sdef slot stays neutral, because RBY has one
--     Special and rendering it twice invents a stat.
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
        -- Convert 1..13 (neutral 7) → 0..12 (neutral 6). Special goes in the SpA slot and
        -- the SpD slot is left NEUTRAL: mirroring it into both rendered one Special drop as
        -- two chips, implying a stat this cartridge does not have. The adapter names the
        -- fourth slot "SPC" and blanks the fifth (GameAdapter.stat_stage_labels).
        return {atk - 1, def - 1, spd - 1, spc - 1, 6, acc - 1, eva - 1}
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
--   - Gen 1: pp_encoding="ppup_packed" (PP_UP_MASK %11000000, PP_MASK %00111111 --
--     pokered/constants/pokemon_data_constants.asm:100).
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

-- ═══ Overworld: the game's own wild-encounter preconditions ══════════════
-- Profile-keyed (Gen 1 only declares these), so Gen 2 inherits a nil no-op.
--
-- These exist because driving the overworld blind does not work. Pacing back and forth to
-- farm encounters drifts: Route 1's ledges are ONE-WAY, so a stray southward step drops the
-- player off the route with no way back, and every later step reports "no encounter" while
-- looking perfectly healthy. Rather than heuristics, ask the game what it asks itself.
--
-- pokered TryDoWildEncounter (engine/battle/wild_encounters.asm:27-32):
--     hlcoord 9, 9        ; bottom-right tile of the half-block we stand in
--     ld c, [hl]
--     ld a, [wGrassTile]
--     cp c                ; equal -> grass -> an encounter can roll
-- hlcoord x,y is wTileMap + y*20 + x, so the probe tile is wTileMap + 189.

--- True when the player is standing on a tile that can roll a wild encounter.
function M.isInGrass()
    if not (M.TILE_MAP_ADDR and M.GRASS_TILE_ADDR) then return nil end
    local tile = M.read_u8(M.TILE_MAP_ADDR + 189)
    return tile == M.read_u8(M.GRASS_TILE_ADDR)
end

--- True when this map has wild Pokémon at all (wGrassRate == 0 means none).
--
-- Zero does NOT mean "a battle ate the table". An earlier version of this file claimed that,
-- on the basis of the UNION at pret/pokered ram/wram.asm:2143-2172, and it was wrong twice:
--
--   * The overlay does not line up the way it looks. The second branch opens with
--     wLinkEnemyTrainerName (11 bytes) + padding + wSerialEnemyDataBlock, so wEnemyPartyCount
--     lands at 0xD89C — in the 8-byte hole AFTER wGrassMons — and wEnemyMons lands on
--     wWaterRate. A battle therefore clobbers the WATER table, never the grass one.
--   * It would not matter anyway: after every battle the game runs
--     .noFaintCheck -> EnterMap -> LoadMapHeader -> LoadWildData
--     (home/overworld.asm:353, :2309, :2253), rebuilding the whole table.
--
-- What actually zeroes it is standing on a map whose wild data is NothingWildMons — Pallet
-- Town and Viridian City among them (data/wild/grass_water.asm:3-4), both of which Route 1
-- connects to with no warp, and both of which HAVE grass tiles. So isInGrass() stays true
-- while the rate is zero, which reads as "walking in grass forever with nothing happening".
-- If you see that, check the map id before blaming the game.
-- ── The native in-game panel ─────────────────────────────────────────────────────────────
-- The companion patch owns the SCREEN: it takes over from the START menu, blanks the
-- display and sets an awaiting handshake meaning "the tile map is yours,
-- paint now". We paint, set it to STAGED, and the patch reveals what we painted. Because
-- the screen is white for the whole of that window, a half-painted page can never be seen.
--
-- WHY THE CLIENT DRAWS AND NOT THE PATCH. Red and Blue have thirty bytes of free WRAM
-- between wBoxDataEnd and the stack; the panel's content is a few hundred. There is nowhere
-- to put it in the ROM's own memory, so the text is written straight into wTileMap and the
-- patch never has to store it.
M.PANEL_MAILBOX = 0xDEE2
M.PANEL_CAPS    = M.PANEL_MAILBOX + 5
M.PANEL_STATE   = M.PANEL_MAILBOX + 15
-- Native request/page and generation controls follow the locked ABI-3 layout.
M.PANEL_PAGE    = M.PANEL_MAILBOX + 16
M.PANEL_PAGES   = M.PANEL_MAILBOX + 17
M.PANEL_GENERATION = M.PANEL_MAILBOX + 18
M.PANEL_ACK = M.PANEL_MAILBOX + 19
M.PANEL_TRANSFERS = M.PANEL_MAILBOX + 20
M.PANEL_LEASE = M.PANEL_MAILBOX + 21
M.PANEL_CANARY = M.PANEL_MAILBOX + 22
M.PANEL_CAP_BIT = 0x02

M.PANEL_CLOSED, M.PANEL_AWAIT, M.PANEL_STAGED, M.PANEL_DISPLAY = 0, 1, 2, 3

M.TILEMAP = 0xC3A0
M.PANEL_COLS, M.PANEL_ROWS = 20, 18

--- ASCII -> Gen 1 tile ids.
---
--- Gen 1 has its own encoding and nothing else in the client needs it: the HUD overlay
--- draws with BizHawk's own font and never touches the ROM's charset. Unmapped characters
--- become spaces rather than guesses -- a wrong tile is a glyph the player cannot read and
--- would have to interpret, and there is no punctuation here worth that risk.
--- Ranges verified against the ROM: "POK<e>DEX@" is 8F 8E 8A BA 83 84 97 50, so 'A' is $80;
--- $7F is the space the menu rows are padded with; digits are the $F6-$FF block.
---
--- The whitelist and the PAYLOAD GENERATOR have to agree. '-' was missing here while
--- server.py emitted dead-zone rows as "-" .. area_name, so every one of them silently
--- lost its leading dash and rendered as an indented name.
local function _tile_for(ch)
    local b = string.byte(ch)
    if b >= 65 and b <= 90  then return 0x80 + (b - 65) end   -- A-Z
    if b >= 97 and b <= 122 then return 0xA0 + (b - 97) end   -- a-z
    if b >= 48 and b <= 57  then return 0xF6 + (b - 48) end   -- 0-9
    if b == 47 then return 0xF3 end                           -- '/'
    if b == 45 then return 0xE3 end                           -- '-' (charmap.asm:163)
    return 0x7F                                               -- space, and anything unknown
end

--- Paint one row of the tile map, padded to the full width so no stale tile survives.
function M.panelWriteRow(row, text)
    if row < 0 or row >= M.PANEL_ROWS then return end
    local base = M.TILEMAP + row * M.PANEL_COLS
    for col = 0, M.PANEL_COLS - 1 do
        local ch = text:sub(col + 1, col + 1)
        M.write_u8(base + col, ch == "" and 0x7F or _tile_for(ch))
    end
end

--- True when the ROM patch is waiting for us to paint.
function M.panelIsAwaitingStage()
    return M.read_u8(M.PANEL_STATE) == M.PANEL_AWAIT
end

--- Does THIS cartridge have the panel? Asked of the capability bits rather than inferred
--- from the ABI number, because a build may ship one feature without the other.
function M.panelSupported()
    local caps = M.read_u8(M.PANEL_CAPS)
    if caps == 0 or caps == 0xFF or (caps & M.PANEL_CAP_BIT) == 0 or M.panelAbi()~=3 then return false end
    local magic={0x53,0x4C,0x4E,0x4B}
    for i,value in ipairs(magic)do if M.read_u8(M.PANEL_MAILBOX+i-1)~=value then return false end end
    for i=0,7 do if M.read_u8(M.PANEL_CANARY+i)~=0xA5 then return false end end
    return true
end

function M.panelAbi()
    return M.read_u8(M.PANEL_MAILBOX + 4)
end

--- Paint `rows` and hand the screen back to the patch.
--- Rows past the bottom are dropped rather than wrapped: the patch reveals whatever is in
--- the tile map, so silently spilling would corrupt the page rather than truncate it.
--- How many screens `rows` needs. Always at least one, so an empty panel still opens.
function M.panelPageCount(rows)
    local n = rows and #rows or 0
    if n <= 0 then return 1 end
    return math.ceil(n / M.PANEL_ROWS)
end

--- Paint the page the patch asked for, and hand the screen back.
---
--- Rows past the bottom of a page are not dropped any more, they are the NEXT page: the
--- patch owns a page number at +16 and we paint the slice it names. Every row is written
--- even when the slice is short, because panelWriteRow pads to the full width -- so nothing
--- of the previous page can survive into this one.
local panel_publisher
local function publisher()
    if not panel_publisher then
        local fields={state=M.PANEL_STATE,page=M.PANEL_PAGE,pages=M.PANEL_PAGES,generation=M.PANEL_GENERATION,
            ack=M.PANEL_ACK,transfers=M.PANEL_TRANSFERS,lease=M.PANEL_LEASE}
        panel_publisher=require("staged_panel").new({page_rows=M.PANEL_ROWS,lease_frames=180,
            read=function(name)return M.read_u8(fields[name])end,
            write=function(name,value)M.write_u8(fields[name],value)end,
            available=M.panelSupported,
            paint=function(rows,page)
                for i=0,M.PANEL_ROWS-1 do M.panelWriteRow(i,rows[page*M.PANEL_ROWS+i+1]or "")end
            end})
    end
    return panel_publisher
end
function M.panelStage(rows)return publisher():stage(rows)end
function M.panelHeartbeat(connected)return publisher():maintain(connected)end

function M.hasWildEncounters()
    if not M.GRASS_RATE_ADDR then return nil end
    return M.read_u8(M.GRASS_RATE_ADDR) ~= 0
end

--- Suppress or re-enable EVERY battle, using the engine's own switch.
---
--- NewBattle (home/overworld.asm:362-373) reads wStatusFlags4 and returns "no battle" when
--- BIT_NO_BATTLES is set, before it can reach InitBattle. That gate covers wild encounters
--- AND trainers, and pokered uses it for exactly this purpose in its own scripts -- Mt. Moon
--- B2F sets it around the fossil choice and Pokemon Tower 5F around the Rocket fight
--- (scripts/MtMoonB2F.asm:14, scripts/PokemonTower5F.asm:32).
---
--- Nothing an ordinary walk does clears it. The only engine clears are ChooseFlyDestination
--- (home/reload_tiles.asm:32-34), the Fly submenu (engine/menus/start_sub_menus.asm:222),
--- one item effect (engine/items/item_effects.asm:1512) and those two scripts -- so a
--- suppression window opened here stays open until it is closed here.
---
--- WHY A TEST WANTS THIS: a fixture parked in tall grass starts an encounter during the
--- boot walk that proves the game is live, which commits a species before the scenario can
--- choose one, and no way of ending that battle leaves the area usable (running and KOing
--- both dead-zone it, catching consumes its only slot). Suppressing battles across the boot
--- makes the grass fixture behave like a town fixture for as long as the window is open.
---
--- Returns false when the profile has no verified address (AP), so callers can say so
--- rather than silently walking into the encounter they meant to prevent.
local BIT_NO_BATTLES = 4            -- constants/ram_constants.asm:98
function M.setNoBattles(on)
    if not M.STATUS_FLAGS_4_ADDR then return false end
    local v = M.read_u8(M.STATUS_FLAGS_4_ADDR)
    M.write_u8(M.STATUS_FLAGS_4_ADDR,
               on and (v | (1 << BIT_NO_BATTLES)) or (v & ~(1 << BIT_NO_BATTLES)))
    -- Read back: this is a WRAM byte the engine also writes, and an assumed write is what
    -- this repo has been burned by before.
    local got = M.read_u8(M.STATUS_FLAGS_4_ADDR)
    local set = (got & (1 << BIT_NO_BATTLES)) ~= 0
    return set == (on and true or false)
end

--- True while the player is mid-ledge-hop, exiting a door, or fishing.
-- TryDoWildEncounter returns early on this, and it is also how we notice a ledge was jumped
-- (the drift that no amount of walking can undo).
function M.isMoveLocked()
    if not M.MOVEMENT_FLAGS_ADDR then return nil end
    return M.read_u8(M.MOVEMENT_FLAGS_ADDR) ~= 0
end

-- ═══ Sound effects (Phase 7) ═════════════════════════════════════════════
-- Trigger an in-game sound effect by writing its ROM SFX ID to the music/SFX
-- dispatch register. Profile-gated: if SFX_DISPATCH_ADDR is nil, this is a
-- no-op (safe default). Use `lua/tests/test_gen{1,2}_sfx.lua` to validate
-- the dispatch address + SFX IDs before enabling in production profiles.
--
-- M.playSfx("capture") looks up profile.sfx_ids.capture and writes it to
-- the dispatch register. Unknown event names are no-ops.

--- Detect the Gen 1 companion patch and, if present, enable SFX through its mailbox.
--
-- No RBY SFX service is qualified. Detect only the current panel ABI and
-- keep audio dispatch disabled; the retired mailbox+7 interface is never used.
function M.detectCompanionPatch()
    M.SFX_DISPATCH_ADDR = nil -- no qualified RBY SFX service is selected
    local mb = M.profile and M.profile.companion_patch_mailbox
    if not mb then return nil end
    local tag = string.char(M.read_u8(mb), M.read_u8(mb + 1),
                            M.read_u8(mb + 2), M.read_u8(mb + 3))
    if tag ~= "SLNK" or not M.panelSupported() then return nil end
    local abi = M.read_u8(mb + 4)
    return abi
end

function M.playSfx(event_name)
    if not M.SFX_DISPATCH_ADDR then return false end
    local sfx_id = M.SFX_IDS[event_name]
    if not sfx_id then return false end
    M.write_u8(M.SFX_DISPATCH_ADDR, sfx_id)
    return true
end

-- Direct write (for diagnostic scripts that want to test arbitrary SFX IDs).
function M.playSfxRaw(sfx_id)
    if not M.SFX_DISPATCH_ADDR then return false end
    M.write_u8(M.SFX_DISPATCH_ADDR, sfx_id)
    return true
end

-- Maps Gen 3 (FRLG/RR) m4a SE_* sound IDs to semantic event names. The server
-- emits play_sound commands with these numeric IDs for cross-gen events
-- (shiny clause, bonus pair formed/rejected). Gen 1/2 profiles bind the
-- semantic name to a ROM-specific SFX ID via the sfx_ids table (Phase 7).
M.GEN3_SE_TO_EVENT = {
    [95] = "shiny",    -- SE_SHINY  (shiny encountered, bonus mon)
    [26] = "failure",  -- SE_FAILURE (rejection, error)
    [25] = "success",  -- SE_SUCCESS (bonus pair formed)
    [22] = "boo",      -- SE_BOO    (partner rejection)
}

function M.playSfxFromGen3Id(sound_id)
    local event_name = M.GEN3_SE_TO_EVENT[sound_id]
    if not event_name then return false end
    return M.playSfx(event_name)
end

-- Read the active enemy battler's 4 moves + 4 PP bytes. Returns
-- {moves=[id1..4], pp=[cur1..4]}, or nil if the profile doesn't declare
-- ENEMY_BATTLE_MOVES_ADDR. Used by build_enemy_snapshot in battle. The encoding is a
-- separate profile key because the battle struct is not always laid out like the party
-- one -- but on Gen 1 it IS: the engine copies PP straight across and masks with PP_MASK
-- everywhere it reads it, so the PP-Up bits are present in both.
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
-- ═══ Gen 1 SRAM box-bank integrity ═══
-- Profile-keyed via `sram_box_layout`, which only the Gen 1 profiles declare — Gen 2's box
-- banks have a different layout and no equivalent one-time wipe, so none of this runs there.
--
-- THE POINT OF THIS, and it is not the checksums. pokered's `ChangeBox` opens with
--     bit BIT_HAS_CHANGED_BOXES, [hl]   ; hl = wCurrentBoxNum, bit 7
--     call z, EmptyAllSRAMBoxes         ; if so, empty ALL boxes in SRAM
-- (engine/menus/save.asm:366, identical in pokeyellow:351 and Alchav's AP fork:354). So the
-- first time the player ever picks "CHANGE BOX", the game marks every SRAM box empty as a
-- one-time init — **including box 12, where we put the memorial**. A run that memorialised
-- before the player first touched the box menu would silently lose every buried mon.
--
-- The fix is to do that init ourselves, once, and then set the bit so the game never does.
-- It is safe: bit 7 clear means the game has never run ChangeBox, which is the only path that
-- writes a real mon to an SRAM box — so there is nothing of the player's to destroy.
local function sram_box_geometry()
    local L = M.profile and M.profile.sram_box_layout
    if not L then return nil end
    -- Defaults match pret/pokered: 12 boxes, 6 per bank, 1122-byte box, banks 2 and 3.
    return {
        box_len   = L.box_len or 1122,
        per_bank  = L.boxes_per_bank or 6,
        banks     = L.banks or {2, 3},
        -- CartRAM offset of each bank's checksum block = bank*0x2000 + (0xBA4C - 0xA000).
        ck_offset = L.checksum_offset or 0x1A4C,
        flag_addr = L.changed_boxes_addr,   -- wCurrentBoxNum
        flag_bit  = L.changed_boxes_bit or 0x80,
        save_start = L.main_save_start,
        save_len = L.main_save_len,
        save_checksum = L.main_checksum_offset,
        saved_flag = L.saved_box_flag_offset,
        save_ranges = L.save_party_dex_ranges,
        player_id = L.player_id_addr,
        saved_player_id = L.saved_player_id_offset,
    }
end

--- Complement of the 8-bit sum, i.e. pokered's `CalcCheckSum` (save.asm:297).
local function sram_sum(off, len)
    local d = 0
    for i = 0, len - 1 do
        d = (d + mem_r8(off + i, SRAM_DOMAIN)) % 256
    end
    return d
end

local function sram_fingerprint(off, len)
    local bytes = {}
    for i = 0, len - 1 do bytes[#bytes + 1] = string.char(mem_r8(off + i, SRAM_DOMAIN)) end
    return table.concat(bytes)
end

--- Recompute one bank's all-boxes checksum and its 6 per-box checksums.
-- One pass: the all-boxes range is exactly the per-box ranges concatenated, so the total is
-- the sum of the parts and we never read a byte twice.
local function recompute_bank_checksums(g, bank)
    local base = bank * SRAM_BANK_SIZE
    local total, per = 0, {}
    for i = 0, g.per_bank - 1 do
        local s = sram_sum(base + i * g.box_len, g.box_len)
        per[i] = (255 - s) % 256
        total = (total + s) % 256
    end
    local ck = base + g.ck_offset
    mem_w8(ck, (255 - total) % 256, SRAM_DOMAIN)
    for i = 0, g.per_bank - 1 do
        mem_w8(ck + 1 + i, per[i], SRAM_DOMAIN)
    end
end

--- Run the game's one-time SRAM box init ourselves, if it has not happened yet.
-- Returns true when it actually did the init (so the caller knows both banks changed).
local function preflight_sram_boxes(g)
    if not (g and g.flag_addr and g.save_start and g.save_len and g.save_checksum and g.saved_flag
        and g.player_id and g.saved_player_id) then
        return false, "missing verified main-save geometry"
    end
    local flag = M.read_u8(g.flag_addr)
    local saved_flag = mem_r8(g.saved_flag, SRAM_DOMAIN)
    local player_id = M.read_u16_be(g.player_id)
    local saved_id = mem_r8(g.saved_player_id, SRAM_DOMAIN) * 256
        + mem_r8(g.saved_player_id + 1, SRAM_DOMAIN)
    -- InitPlayerData stores both RNG bytes verbatim; 0000 is a legal identity.
    if player_id ~= saved_id then
        return false, "saved/live player identity differs; save this game before memorializing"
    end
    -- CheckPreviousSaveFile first requires a nonempty saved player name. The
    -- verified save geometry places sPlayerName exactly at sGameData/save_start.
    if mem_r8(g.save_start, SRAM_DOMAIN) == 0 then
        return false, "no saved player name; save this game before memorializing"
    end
    local count = g.per_bank * #g.banks
    if flag % g.flag_bit >= count or saved_flag % g.flag_bit >= count then
        return false, "invalid current box in memory/save"
    end
    if saved_flag >= g.flag_bit and flag < g.flag_bit then
        return false, "saved/live box initialization conflict"
    end
    if mem_r8(g.save_checksum, SRAM_DOMAIN) ~= (255 - sram_sum(g.save_start, g.save_len)) % 256 then
        return false, "main save checksum invalid; save in game before memorializing"
    end
    return true
end

function M.protectSramBoxes()
    local g = sram_box_geometry()
    if not g or not g.flag_addr then return false end
    local valid, reason = preflight_sram_boxes(g)
    if not valid then return false, reason end
    local flag = M.read_u8(g.flag_addr)
    local initialize = flag % (g.flag_bit * 2) < g.flag_bit
    if initialize then
        -- EmptySRAMBox changes count and list terminator; unused tails are preserved.
        for _, bank in ipairs(g.banks) do
            for i = 0, g.per_bank - 1 do
                local box = bank * SRAM_BANK_SIZE + i * g.box_len
                mem_w8(box, 0, SRAM_DOMAIN)
                mem_w8(box + 1, 0xFF, SRAM_DOMAIN)
            end
            recompute_bank_checksums(g, bank)
        end
    end
    -- Keep the saved current-box index: the save may predate a live box change.
    -- Persist the initialization flag and its covering checksum before any grave data.
    local saved_flag = mem_r8(g.saved_flag, SRAM_DOMAIN)
    if saved_flag % (g.flag_bit * 2) < g.flag_bit then
        mem_w8(g.saved_flag, saved_flag + g.flag_bit, SRAM_DOMAIN)
        mem_w8(g.save_checksum, (255 - sram_sum(g.save_start, g.save_len)) % 256, SRAM_DOMAIN)
    end
    if initialize then M.write_u8(g.flag_addr, flag + g.flag_bit) end
    return initialize
end

--- Refresh the checksums for whichever banks we touched.
-- ponytail: vanilla pokered never READS these — every reference is a write (verified by
-- grepping the whole decomp), and ChangeBox recomputes them from SRAM anyway. We write them
-- so SRAM stays self-consistent for forks that might check. If this ever costs a visible
-- frame hitch, drop it; correctness does not depend on it.
function M.refreshSramBoxChecksums(all_banks)
    local g = sram_box_geometry()
    if not g then return end
    if all_banks then
        for _, bank in ipairs(g.banks) do recompute_bank_checksums(g, bank) end
    else
        recompute_bank_checksums(g, g.banks[#g.banks])   -- memorial box lives in the last bank
    end
end

-- Read-only proof for a Gen 1 memorial ACK. Absence from the party alone says
-- nothing about where a Pokemon went. Verify its exact dead key in the actual
-- memorial box, then require uniqueness across the party and all twelve boxes.
-- The current box is authoritative in WRAM, including when Box 12 is active.
function M.verifyMemorialKey(key)
    if M.GENERATION ~= 1 then return false, "memorial proof unsupported for this generation" end
    if type(key) ~= "string" or not key:match("^%x%x%x%x:%x%x%x%x:%x%x$") then
        return false, "invalid memorial key"
    end
    local geometry = sram_box_geometry()
    local valid, save_error = preflight_sram_boxes(geometry)
    if not valid then return false, save_error end
    local p = M.profile
    local boxes = p and p.stored_boxes
    local layout = p and p.sram_box_layout
    local offset = M.getMemorialBoxOffset()
    if not (boxes and boxes.banks and boxes.count and boxes.stride and boxes.per_bank
        and layout and layout.changed_boxes_addr and layout.changed_boxes_bit and offset) then
        return false, "missing verified memorial geometry"
    end
    local memorial_index
    for index = 0, boxes.count - 1 do
        local bank = boxes.banks[math.floor(index / boxes.per_bank) + 1]
        if bank and bank + (index % boxes.per_bank) * boxes.stride == offset then
            if memorial_index ~= nil then return false, "ambiguous memorial geometry" end
            memorial_index = index
        end
    end
    if memorial_index == nil then return false, "memorial offset is not a verified box" end
    local current = M.getCurrentBoxNum()
    if current == nil then return false, "invalid current box" end
    local active = current == memorial_index
    local saved_flag = mem_r8(geometry.saved_flag, SRAM_DOMAIN)
    if M.read_u8(layout.changed_boxes_addr) < layout.changed_boxes_bit
        or saved_flag < layout.changed_boxes_bit then
        return false, "memorial initialization is not persisted"
    end
    if saved_flag % layout.changed_boxes_bit ~= current then
        return false, "saved/live current box differs; memorial save proof unavailable"
    end
    local read = active and M.box_read_u8 or function(address) return mem_r8(address, SRAM_DOMAIN) end
    local count_addr = active and M.BOX_COUNT_ADDR or offset
    local species_addr = active and M.BOX_SPECIES_ADDR or offset + 1
    local structs = active and M.BOX_BASE_ADDR or offset + 1 + M.BOX_MAX_MONS + 1
    local count = read(count_addr)
    if count > M.BOX_MAX_MONS then return false, "invalid memorial count" end
    if read(species_addr + count) ~= 0xFF then return false, "invalid memorial species terminator" end
    local found, seen = false, {}
    for slot = 0, count - 1 do
        local base = structs + slot * M.BOX_STRUCT_SIZE
        local species = read(base + M.SPECIES_OFFSET)
        if not M._game or not M._game.toNatDex or M._game.toNatDex(species) == 0
            or read(species_addr + slot) ~= species then
            return false, "invalid memorial species list"
        end
        local identity = string.format("%02X%02X:%04X:%02X", read(base + M.DV_OFFSET_1),
            read(base + M.DV_OFFSET_2), read(base + M.OTID_OFFSET) * 256
                + read(base + M.OTID_OFFSET + 1), species)
        if seen[identity] then return false, "duplicate memorial key" end
        seen[identity] = true
        if read(base + M.HP_OFFSET) * 256 + read(base + M.HP_OFFSET + 1) ~= 0 then
            return false, "memorial contains a live Pokemon"
        end
        if identity == key then found = true end
    end
    if not found then return false, "exact key not present in memorial" end

    local party_count = M.getPartyCount()
    if party_count > 6 then return false, "invalid party count" end
    if M.read_u8(M.PARTY_SPECIES_ADDR + party_count) ~= 0xFF then
        return false, "invalid party species terminator"
    end
    for slot = 0, party_count - 1 do
        local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
        local species = M.read_u8(base + M.SPECIES_OFFSET)
        if M._game.toNatDex(species) == 0 or M.read_u8(M.PARTY_SPECIES_ADDR + slot) ~= species then
            return false, "invalid party species list"
        end
        if M.monKey(base) == key then return false, "memorial key also exists in party" end
    end
    -- storedBoxKeys validates the actual active WRAM box and all other SRAM
    -- boxes, rejecting duplicate identities and malformed count/species lists.
    local stored, reason = M.storedBoxKeys()
    if not stored then return false, reason or "storage identity unavailable" end
    if not stored[key] then return false, "memorial identity missing from verified storage" end

    -- A complete-looking grave is insufficient if resetting loads its old copy
    -- from sPartyData, or if the saved ordinary current box duplicates the key.
    -- Read only the exact SaveCurrentBoxData/SavePartyAndDexData profile ranges.
    local function saved_keys(count_source, species_source, struct_source, stride, capacity, dead_only)
        local range
        for _, candidate in ipairs(geometry.save_ranges or {}) do
            if candidate.src == count_source then
                if range then return nil, "ambiguous saved storage range" end
                range = candidate
            end
        end
        if not range or not range.len or not range.dst or range.dst < geometry.save_start
            or range.dst + range.len > geometry.save_start + geometry.save_len
            or struct_source - count_source + capacity * stride > range.len then
            return nil, "missing verified saved storage range"
        end
        local n = mem_r8(range.dst, SRAM_DOMAIN)
        if n > capacity then return nil, "invalid saved storage count" end
        local list = range.dst + species_source - count_source
        local base = range.dst + struct_source - count_source
        if mem_r8(list + n, SRAM_DOMAIN) ~= 0xFF then return nil, "invalid saved species terminator" end
        local keys = {}
        for slot = 0, n - 1 do
            local mon = base + slot * stride
            local sp = mem_r8(mon + M.SPECIES_OFFSET, SRAM_DOMAIN)
            if M._game.toNatDex(sp) == 0 or mem_r8(list + slot, SRAM_DOMAIN) ~= sp then
                return nil, "invalid saved species list"
            end
            local identity = string.format("%02X%02X:%04X:%02X",
                mem_r8(mon + M.DV_OFFSET_1, SRAM_DOMAIN), mem_r8(mon + M.DV_OFFSET_2, SRAM_DOMAIN),
                mem_r8(mon + M.OTID_OFFSET, SRAM_DOMAIN) * 256
                    + mem_r8(mon + M.OTID_OFFSET + 1, SRAM_DOMAIN), sp)
            if keys[identity] then return nil, "duplicate saved storage key" end
            if dead_only and mem_r8(mon + M.HP_OFFSET, SRAM_DOMAIN) * 256
                + mem_r8(mon + M.HP_OFFSET + 1, SRAM_DOMAIN) ~= 0 then
                return nil, "saved memorial contains a live Pokemon"
            end
            keys[identity] = true
        end
        return keys
    end
    local saved_party, party_error = saved_keys(M.PARTY_COUNT_ADDR, M.PARTY_SPECIES_ADDR,
        M.PARTY_BASE_ADDR, M.PARTY_STRUCT_SIZE, 6, false)
    if not saved_party then return false, party_error end
    if saved_party[key] then return false, "saved party still contains memorial key" end
    local saved_box, box_error = saved_keys(M.BOX_COUNT_ADDR, M.BOX_SPECIES_ADDR,
        M.BOX_BASE_ADDR, M.BOX_STRUCT_SIZE, M.BOX_MAX_MONS, active)
    if not saved_box then return false, box_error end
    if active and not saved_box[key] then return false, "active memorial key is not saved" end
    if not active and saved_box[key] then return false, "saved ordinary box duplicates memorial key" end
    return true
end

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
    if pcount > 6 then return false, "invalid party count" end
    if type(slot) ~= "number" or slot % 1 ~= 0 or slot < 0 or slot >= pcount then
        return false, "invalid slot"
    end
    local deposit_effect
    local selected_base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local selected_level = M.read_u8(selected_base + M.LEVEL_OFFSET)
    if selected_level < 1 or selected_level > 100 then return false, "invalid memorial selection level" end
    if M.read_u16_be(selected_base + M.HP_OFFSET) ~= 0 then
        return false, "memorial selection is still alive"
    end
    if M._game and M._game.prepareDeposit then
        local allowed, effect = M._game.prepareDeposit(M, slot)
        if not allowed then return false, effect end
        deposit_effect = effect
    end
    local geometry = sram_box_geometry()
    local initializing = false
    if geometry then
        local _, box_error = M.scanBoxForKey("")
        if box_error then return false, box_error end
        if M.read_u8(M.PARTY_SPECIES_ADDR + pcount) ~= 0xFF then
            return false, "invalid party species terminator"
        end
        for i = 0, pcount - 1 do
            local sp = M.read_u8(M.PARTY_BASE_ADDR + i * M.PARTY_STRUCT_SIZE + M.SPECIES_OFFSET)
            if M._game.toNatDex(sp) == 0 or M.read_u8(M.PARTY_SPECIES_ADDR + i) ~= sp then
                return false, "invalid party species list"
            end
        end
        -- A replay after a partial save/rewind must not append a second grave.
        -- Refuse before initialization or writes; exact prepared-poststate
        -- recovery belongs to the durable executor, not a key-only success.
        if M.GENERATION == 1 then
            local stored, storage_error = M.storedBoxKeys()
            if not stored then return false, storage_error or "storage identity unavailable" end
            local party_keys = {}
            for i = 0, pcount - 1 do
                local key = M.monKey(M.PARTY_BASE_ADDR + i * M.PARTY_STRUCT_SIZE)
                if party_keys[key] or stored[key] then return false, "storage key collision" end
                party_keys[key] = true
            end
        end
        local valid, reason = preflight_sram_boxes(geometry)
        if not valid then return false, reason end
        if not geometry.save_ranges then return false, "missing verified party/dex save ranges" end
        for _, range in ipairs(geometry.save_ranges) do
            if not (range.src and range.dst and range.len and range.len > 0
                and range.src >= 0xC000 and range.src + range.len <= 0xE000
                and range.dst >= geometry.save_start
                and range.dst + range.len <= geometry.save_start + geometry.save_len) then
                return false, "invalid party/dex save range"
            end
        end
        local current = M.getCurrentBoxNum()
        if current == nil then return false, "invalid current box" end
        if current ~= mem_r8(geometry.saved_flag, SRAM_DOMAIN) % geometry.flag_bit then
            return false, "saved/live box index differs; save in game before memorializing"
        end
        if current == geometry.per_bank * #geometry.banks - 1 then
            return false, "memorial box is active; change to another box first"
        end
        initializing = M.read_u8(geometry.flag_addr) % (geometry.flag_bit * 2) < geometry.flag_bit
    end
    local mbox_count = mem_r8(mem_off, SRAM_DOMAIN)
    if initializing then mbox_count = 0 end
    if mbox_count > M.BOX_MAX_MONS then return false, "invalid memorial box count" end
    if mbox_count >= M.BOX_MAX_MONS then
        -- FULL MEMORIAL: FAIL, do not fall back to depositPartyMon.
        -- That fallback wrote into whatever box the player happened to have OPEN, and then
        -- reported success -- so the corpse landed in a regular box, the server acked the
        -- memorialize, and its very next pc_boxes scan saw a dead mon in a regular box and
        -- re-queued the memorialize. Round and round, with a body in the player's storage.
        -- Failing is honest: the caller NACKs, the pair still reaches MEMORIAL status via
        -- _handle_memorialize_failed, and the mon stays where it was.
        return false, "memorial box full"
    end

    local species_off = mem_off + 1
    local structs_off = mem_off + 1 + (M.BOX_MAX_MONS + 1)
    local ots_off     = structs_off + M.BOX_MAX_MONS * M.BOX_STRUCT_SIZE
    local nicks_off   = ots_off + M.BOX_MAX_MONS * 11

    local reservation_key
    if geometry then
        M._memorial_reservations = M._memorial_reservations or {}
        reservation_key = tostring(M.readPlayerId()) .. ":" .. tostring(mem_off)
        local previous = M._memorial_reservations[reservation_key]
        if previous ~= nil and previous ~= sram_fingerprint(mem_off, geometry.box_len) then
            return false, "memorial contents changed since verified reservation"
        end
        if previous == nil then
            if mbox_count ~= 0 then return false, "memorial box not empty; reservation unverified" end
        end
        if not initializing then
            if mem_r8(species_off + mbox_count, SRAM_DOMAIN) ~= 0xFF then
                return false, "invalid memorial species terminator"
            end
            -- Reservation is not permission to overwrite arbitrary later contents.
            -- Revalidate every use, including hidden live records outside the count.
            for i = 0, M.BOX_MAX_MONS - 1 do
                local base = structs_off + i * M.BOX_STRUCT_SIZE
                local sp = mem_r8(base + M.SPECIES_OFFSET, SRAM_DOMAIN)
                local hp = mem_r8(base + M.HP_OFFSET, SRAM_DOMAIN) * 256
                    + mem_r8(base + M.HP_OFFSET + 1, SRAM_DOMAIN)
                if sp ~= 0 and sp ~= 0xFF and hp > 0 then
                    return false, "memorial box contains a live Pokemon"
                end
                if i < mbox_count and (sp == 0 or sp == 0xFF
                    or mem_r8(species_off + i, SRAM_DOMAIN) ~= sp
                    or M._game.toNatDex(sp) == 0) then
                    return false, "invalid memorial species list"
                end
            end
        end
        local did_init, reason = M.protectSramBoxes()
        if reason then return false, reason end
        initializing = did_init
    end

    local party_base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local species = M.read_u8(party_base + M.SPECIES_OFFSET)

    local struct_dst = structs_off + mbox_count * M.BOX_STRUCT_SIZE
    if deposit_effect then M._game.applyDepositEffect(M, deposit_effect) end
    for i = 0, M.BOX_STRUCT_SIZE - 1 do
        mem_w8(struct_dst + i, M.read_u8(party_base + i), SRAM_DOMAIN)
    end
    mem_w8(struct_dst + M.BOX_LEVEL_OFFSET, selected_level, SRAM_DOMAIN)

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

    M.refreshSramBoxChecksums(initializing)
    if geometry then
        -- Match SaveCurrentBoxData then SavePartyAndDexData copy ranges, including
        -- Yellow happiness/mood. Party and active box must be persisted together:
        -- saving a party after an ordinary unsaved deposit would otherwise lose
        -- that boxed mon on reset. Preflight requires the saved/live box indices
        -- to agree, so sCurBoxData cannot be attributed to a different box.
        for _, range in ipairs(geometry.save_ranges) do
            for i = 0, range.len - 1 do
                mem_w8(range.dst + i, M.read_u8(range.src + i), SRAM_DOMAIN)
            end
        end
        mem_w8(geometry.save_checksum,
            (255 - sram_sum(geometry.save_start, geometry.save_len)) % 256, SRAM_DOMAIN)
        M._memorial_reservations[reservation_key] = sram_fingerprint(mem_off, geometry.box_len)
    end
    return true
end

return M
