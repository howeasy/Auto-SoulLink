--[[
  lua/games/gen2_crystal.lua — Game module for Gen 2: Pokémon Crystal (US English).

  Provides detection, memory profiles, gift area definitions, and area resolution
  for the shared memory_gb.lua module and the gen2_crystal_client.lua client.

  Source: pret/pokecrystal wram.asm, data/maps/, constants/pokemon_data_constants.asm
  Crystal species IDs are sequential NatDex 1-251 (no index table needed).
--]]

local M = {}
M.game_id = "gen2_crystal"
M.display_name = "Crystal"
M.implemented = true
M.generation = 2
M.detect_priority = 15  -- higher than Gen 1 (10) to detect Crystal before RBY

-- ═══ Species → NatDex ═══
-- Gen 2 species IDs are sequential NatDex 1-251; no conversion needed.
function M.toNatDex(species_id)
    if species_id >= 1 and species_id <= 251 then
        return species_id
    end
    return 0
end

-- ═══ Memory Profiles ═══
-- Crystal US (CGB-BYTE-0). Addresses from pret/pokecrystal wram.asm.
-- Crystal has no variants — one profile covers all US ROMs.

M.PROFILES = {
    crystal = {
        -- Party (source: wram.asm wPartyCount / wPartyMons / wPartyMon1)
        party_count_addr     = 0xDCD7,
        party_species_addr   = 0xDCD8,  -- 6 bytes + 0xFF terminator
        party_base_addr      = 0xDCDF,  -- 6 × 48 bytes
        party_ot_names_addr  = 0xDDFF,  -- 6 × 11 bytes
        party_nicks_addr     = 0xDE41,  -- 6 × 11 bytes
        party_struct_size    = 48,

        -- Enemy party (wOTPartyCount / wOTPartyMons)
        enemy_count_addr     = 0xD280,  -- TODO: verify in BizHawk
        enemy_base_addr      = 0xD288,  -- TODO: verify in BizHawk

        -- Current active box in SRAM (wBoxCount / wBoxMons)
        -- These addresses are System Bus view (0xA000+offset). Accessed via CartRAM domain.
        -- Layout: count(1) + species(21) + mons(20*32=640) + OT_names(20*11=220) + nicks(20*11=220)
        box_count_addr       = 0xAD10,
        box_species_addr     = 0xAD11,                  -- ends at 0xAD25
        box_base_addr        = 0xAD26,                  -- ends at 0xAFA5 (20*32=640 bytes)
        box_ot_names_addr    = 0xAFA6,                  -- ends at 0xB081 (20*11=220 bytes)
        box_nicks_addr       = 0xB082,                  -- ends at 0xB15D (20*11=220 bytes)
        box_struct_size      = 32,
        box_max_mons         = 20,
        box_in_sram          = true,  -- access via CartRAM domain (not System Bus)
        sram_bank            = 1,    -- active box is in SRAM bank 1

        -- Ball pocket (wBallsCount / wBalls in wram.asm)
        -- Crystal has a dedicated ball pocket like Gen 3.
        bag_count_addr       = 0xD8D7,
        bag_items_addr       = 0xD8D8,  -- each entry = 2 bytes (ID + quantity)
        bag_max_items        = 12,      -- ball pocket max size

        -- Battle (wBattleMode: 0=overworld, 1=wild, 2=trainer)
        battle_flag_addr     = 0xD22D,  -- TODO: verify in BizHawk

        -- Active enemy battle mon (wEnemyMon / wBattleMon structure)
        -- Source: DataCrystal RAM map — battle struct is NOT the same as party struct
        enemy_mon_species_addr = 0xD206,
        enemy_mon_hp_addr      = 0xD216,  -- current HP (2 bytes BE)
        enemy_mon_level_addr   = 0xD213,
        enemy_mon_maxhp_addr   = 0xD218,  -- max HP (2 bytes BE)

        -- Enemy species list
        enemy_species_list_addr = 0xD281, -- TODO: verify in BizHawk

        -- Map (2-byte group:number addressing)
        map_group_addr       = 0xDCB5,   -- wMapGroup
        map_number_addr      = 0xDCB6,   -- wMapNumber

        -- Player (wPlayerID, wPlayerName)
        player_id_addr       = 0xD47B,   -- 2 bytes big-endian
        player_name_addr     = 0xD47D,

        -- Badges
        badges_addr          = 0xD857,   -- wJohtoBadges (bitfield, 8 badges)
        kanto_badges_addr    = 0xD858,   -- wKantoBadges (bitfield, 8 badges)

        -- Party struct offsets (48 bytes, pret/pokecrystal macros/wram.asm)
        species_offset       = 0x00,    -- species ID (sequential NatDex)
        held_item_offset     = 0x01,    -- held item (new in Gen 2)
        otid_offset          = 0x06,    -- 2 bytes big-endian OT ID
        dv_offset_1          = 0x15,    -- Atk/Def DVs
        dv_offset_2          = 0x16,    -- Spd/Spc DVs
        level_offset         = 0x1F,    -- actual level (party-calculated)
        hp_offset            = 0x22,    -- current HP (2 bytes big-endian)
        maxhp_offset         = 0x24,    -- max HP (2 bytes big-endian)
        status_offset        = 0x20,    -- non-volatile status (u8: bits 0-2 SLP, 3 PSN, 4 BRN, 5 FRZ, 6 PAR, 7 TOX)
        enemy_status_offset  = 0x20,    -- same offset in active enemy battle struct (mirrors party struct)

        -- Box struct offsets (32 bytes — truncated party struct, no stats)
        box_species_offset   = 0x00,
        box_held_item_offset = 0x01,
        box_otid_offset      = 0x06,
        box_dv_offset_1      = 0x15,
        box_dv_offset_2      = 0x16,
        box_level_offset     = 0x1F,    -- box level (level at time of deposit)

        -- Ball item IDs (Crystal)
        -- Source: pret/pokecrystal constants/item_constants.asm
        ball_item_ids        = {
            0x01,   -- Master Ball
            0x02,   -- Ultra Ball
            0x04,   -- Great Ball
            0x05,   -- Poké Ball
            -- Apricorn balls (0xA9-0xAF)
            0xA9,   -- Fast Ball
            0xAA,   -- Level Ball
            0xAB,   -- Lure Ball
            0xAC,   -- Heavy Ball
            0xAD,   -- Love Ball
            0xAE,   -- Friend Ball
            0xAF,   -- Moon Ball
            0xB2,   -- Park Ball (Bug Catching Contest)
        },

        -- Gen 2 uses same text encoding as Gen 1
        generation = 2,

        -- Crystal uses 2-byte map addressing (group + number)
        uses_map_group = true,

        -- Egg species sentinel: pret/pokecrystal constants/pokemon_constants.asm defines EGG = $FD.
        -- A party / box slot with species == 0xFD is an egg (no separate flag byte in Gen 2).
        is_egg_species = 0xFD,

        -- Stat stages (Phase 2 — pret/pokecrystal ram/wram.asm "Miscellaneous" UNION section:
        -- wPlayerStatLevels expands to {wPlayerAtkLevel, ...DefLevel, ...SpdLevel,
        -- ...SAtkLevel, ...SDefLevel, ...AccLevel, ...EvaLevel} (7 bytes).
        -- wEnemyStatLevels has the same layout immediately after. Raw range 1..13
        -- (BASE_STAT_LEVEL EQU 7 per constants/battle_constants.asm). Client normalizes to 0..12.
        -- Working hypothesis: 0xC68A / 0xC691 (TODO Phase 9 live verification).
        player_stat_stages_addr = 0xC68A,
        enemy_stat_stages_addr  = 0xC691,
        stat_stages_count       = 7,
        stat_stages_layout      = "gen2",  -- {atk, def, spd, satk, sdef, acc, eva}
    },
}

-- Lowercase alias for game_detect.lua compatibility
M.profiles = M.PROFILES

-- ═══ Gift Areas ═══

M.GIFT_AREAS = {
    new_bark_town  = true,   -- Starter from Professor Elm
    goldenrod_city = true,   -- Eevee from Bill
    olivine_city   = true,   -- Shuckle (Kirk)
    dragons_den    = true,   -- Dratini from Elder
    route_34       = true,   -- Odd Egg from Day Care
    goldenrod_game_corner = true,  -- Game Corner prizes
    celadon_game_corner   = true,  -- Kanto Game Corner prizes
    gift           = true,   -- Fallback
}

function M.is_gift_area(area_id)
    if M.GIFT_AREAS[area_id] then return true end
    if area_id and area_id:sub(1, 5) == "gift_" then return true end
    return false
end

-- ═══ ROM Detection ═══

function M.detect()
    -- Crystal is GBC-only (0x0143 = 0xC0)
    local ok, sysId = pcall(function() return emu.getsystemid() end)
    if not ok or (sysId ~= "GBC" and sysId ~= "GB") then
        return false
    end
    local title = M._readRomTitle()
    if not title then return false end
    -- ROM title: "PM_CRYSTAL" (Crystal US) or contains "CRYSTAL"
    return title == "PM_CRYSTAL" or title:find("CRYSTAL") ~= nil
end

function M.detect_variant()
    -- Crystal has only one variant (US English)
    return "crystal"
end

function M._readRomTitle()
    local ok, bytes = pcall(function()
        local chars = {}
        for i = 0, 15 do
            local b = memory.read_u8(0x0134 + i, "System Bus")
            if b == 0 then break end
            chars[#chars + 1] = string.char(b)
        end
        return table.concat(chars)
    end)
    if ok then return bytes end
    return nil
end

function M.rom_type_for_variant(variant)
    return "Crystal"
end

-- ═══ Area Resolution ═══
-- Crystal uses 2-byte map addressing: mapGroup * 256 + mapNumber → area_id
-- Loaded from gen2_crystal_areas.lua at runtime (generated from area_map.json).

M._area_lookup = nil

function M.resolve_area(mapGroup, mapNumber)
    if not M._area_lookup then
        local ok, areas = pcall(require, "gen2_crystal_areas")
        if ok and areas then
            M._area_lookup = areas
            local count = 0
            for _ in pairs(areas) do count = count + 1 end
            console.log("[SLink-Crystal] Area table loaded: " .. count .. " entries")
        else
            M._area_lookup = {}
            console.log("[SLink-Crystal] WARNING: gen2_crystal_areas.lua failed to load: " .. tostring(areas))
        end
    end
    local composite = mapGroup * 256 + mapNumber
    return M._area_lookup[composite] or ""
end

return M
