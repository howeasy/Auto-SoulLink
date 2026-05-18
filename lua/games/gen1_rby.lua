--[[
  lua/games/gen1_rby.lua — Game module for Gen 1: Pokemon Red, Blue, Yellow (US English).
  
  Provides detection, memory profiles, gift area definitions, and area resolution
  for the shared memory_gb.lua module and the gen1_rby_client.lua client.
--]]

local M = {}
M.game_id = "gen1_rby"
M.display_name = "Red / Blue / Yellow"
M.implemented = true
M.detect_priority = 10  -- lower than Gen 3/4 to avoid false positives

-- ═══ Internal Species Index → NatDex Lookup ═══
-- Source: pret/pokered data/pokemon/dex_order.asm
-- Only valid species (MissingNo entries omitted)
M.INDEX_TO_NATDEX = {
    [1]=112,[2]=115,[3]=32,[4]=35,[5]=21,[6]=100,[7]=34,[8]=80,[9]=2,[10]=103,
    [11]=108,[12]=102,[13]=88,[14]=94,[15]=29,[16]=31,[17]=104,[18]=111,[19]=131,[20]=59,
    [21]=151,[22]=130,[23]=90,[24]=72,[25]=92,[26]=123,[27]=120,[28]=9,[29]=127,[30]=114,
    [33]=58,[34]=95,[35]=22,[36]=16,[37]=79,[38]=64,[39]=75,[40]=113,[41]=67,[42]=122,
    [43]=106,[44]=107,[45]=24,[46]=47,[47]=54,[48]=96,[49]=76,[51]=126,[53]=125,[54]=82,
    [55]=109,[57]=56,[58]=86,[59]=50,[60]=128,[64]=83,[65]=48,[66]=149,[70]=84,[71]=60,
    [72]=124,[73]=146,[74]=144,[75]=145,[76]=132,[77]=52,[78]=98,[82]=37,[83]=38,[84]=25,
    [85]=26,[88]=147,[89]=148,[90]=140,[91]=141,[92]=116,[93]=117,[96]=27,[97]=28,[98]=138,
    [99]=139,[100]=39,[101]=40,[102]=133,[103]=136,[104]=135,[105]=134,[106]=66,[107]=41,
    [108]=23,[109]=46,[110]=61,[111]=62,[112]=13,[113]=14,[114]=15,[116]=85,[117]=57,
    [118]=51,[119]=49,[120]=87,[123]=10,[124]=11,[125]=12,[126]=68,[128]=55,[129]=97,
    [130]=42,[131]=150,[132]=143,[133]=129,[136]=89,[138]=99,[139]=91,[141]=101,[142]=36,
    [143]=110,[144]=53,[145]=105,[147]=93,[148]=63,[149]=65,[150]=17,[151]=18,[152]=121,
    [153]=1,[154]=3,[155]=73,[157]=118,[158]=119,[163]=77,[164]=78,[165]=19,[166]=20,
    [167]=33,[168]=30,[169]=74,[170]=137,[171]=142,[173]=81,[176]=4,[177]=7,[178]=5,
    [179]=8,[180]=6,[185]=43,[186]=44,[187]=45,[188]=69,[189]=70,[190]=71,
}

function M.toNatDex(internalIndex)
    return M.INDEX_TO_NATDEX[internalIndex] or 0
end

-- ═══ Memory Profiles ═══
-- Red and Blue share identical WRAM layouts.
-- Yellow has addresses shifted by approximately -1 byte in many areas.
-- Source: pret/pokered wram.asm, datacrystal RAM map

M.PROFILES = {
    red = {
        -- Party
        party_count_addr   = 0xD163,
        party_species_addr = 0xD164,  -- 6 bytes + 0xFF terminator
        party_base_addr    = 0xD16B,  -- 6 × 44 bytes
        party_ot_names_addr = 0xD273, -- 6 × 11 bytes
        party_nicks_addr   = 0xD2B5,  -- 6 × 11 bytes
        party_struct_size  = 44,
        -- Enemy party
        enemy_count_addr   = 0xD89C,
        enemy_base_addr    = 0xD8A4,
        -- Current box
        box_count_addr     = 0xDA80,
        box_species_addr   = 0xDA81,  -- 20 bytes + 0xFF terminator
        box_base_addr      = 0xDA96,  -- 20 × 33 bytes
        box_ot_names_addr  = 0xDD2A,  -- 20 × 11 bytes
        box_nicks_addr     = 0xDEB8,  -- 20 × 11 bytes
        box_struct_size    = 33,
        box_max_mons       = 20,
        -- Bag
        bag_count_addr     = 0xD31D,
        bag_items_addr     = 0xD31E,  -- each item = 2 bytes (ID + quantity)
        bag_max_items      = 20,
        -- Battle
        battle_flag_addr   = 0xD057,  -- 0=overworld, 1=wild, 2=trainer
        -- Active enemy battle mon (wEnemyMon at CFE5, battle_struct layout)
        enemy_mon_species_addr = 0xCFE5,  -- internal species index (+0x00)
        enemy_mon_hp_addr      = 0xCFE6,  -- 2 bytes big-endian (+0x01)
        enemy_mon_level_addr   = 0xCFF3,  -- actual level (+0x0E)
        enemy_mon_maxhp_addr   = 0xCFF4,  -- 2 bytes big-endian (+0x0F)
        -- Enemy species list (between count and struct): count+1 through count+6
        enemy_species_list_addr = 0xD89D, -- 6 bytes, each = internal species index
        -- Map
        map_id_addr        = 0xD35E,
        -- Player
        player_name_addr   = 0xD158,
        player_id_addr     = 0xD359,  -- 2 bytes, big-endian
        -- DV offsets within party struct
        dv_offset_1        = 0x1B,    -- Attack/Defense DVs
        dv_offset_2        = 0x1C,    -- Speed/Special DVs
        -- Other offsets within party struct
        otid_offset        = 0x0C,
        species_offset     = 0x00,
        hp_offset          = 0x01,    -- current HP (2 bytes BE)
        maxhp_offset       = 0x22,    -- max HP (2 bytes BE)
        level_offset       = 0x21,    -- actual level
        status_offset      = 0x04,    -- non-volatile status (u8: bits 0-2 SLP, 3 PSN, 4 BRN, 5 FRZ, 6 PAR)
        enemy_status_offset = 0x04,   -- same offset in active enemy battle struct (mirrors party struct)
        -- Ball item IDs
        ball_item_ids      = {0x01, 0x02, 0x03, 0x04},  -- Master, Ultra, Great, Poke
        -- Badges
        badges_addr        = 0xD356,  -- wObtainedBadges (bitfield, 8 badges)
        -- Stat stages (Phase 2 — DataCrystal RBY RAM map, pret/pokered wram.asm
        -- wPlayerMonAttackMod..wPlayerMonEvasionMod = CD1A..CD1F (6 bytes).
        -- wEnemyMonAttackMod..wEnemyMonEvasionMod   = CD2E..CD33.
        -- Raw range 1..13 (BASE_STAT_LEVEL=7 per pret); client normalizes to 0..12/6.
        -- Gen 1 has 6 stat stages — Special is unified (split into SpA/SpD only in Gen 2).
        player_stat_stages_addr = 0xCD1A,
        enemy_stat_stages_addr  = 0xCD2E,
        stat_stages_count       = 6,
        stat_stages_layout      = "gen1",  -- {atk, def, spd, spc, acc, eva}
    },

    -- Yellow has shifted WRAM addresses
    yellow = {
        party_count_addr   = 0xD162,
        party_species_addr = 0xD163,
        party_base_addr    = 0xD16A,
        party_ot_names_addr = 0xD272,
        party_nicks_addr   = 0xD2B4,
        party_struct_size  = 44,
        enemy_count_addr   = 0xD89B,
        enemy_base_addr    = 0xD8A3,
        box_count_addr     = 0xDA7F,
        box_species_addr   = 0xDA80,
        box_base_addr      = 0xDA95,
        box_ot_names_addr  = 0xDD29,
        box_nicks_addr     = 0xDEB7,
        box_struct_size    = 33,
        box_max_mons       = 20,
        bag_count_addr     = 0xD31C,
        bag_items_addr     = 0xD31D,
        bag_max_items      = 20,
        battle_flag_addr   = 0xD056,
        enemy_mon_species_addr = 0xCFE4,
        enemy_mon_hp_addr      = 0xCFE5,
        enemy_mon_level_addr   = 0xCFF2,
        enemy_mon_maxhp_addr   = 0xCFF3,
        enemy_species_list_addr = 0xD89C,
        map_id_addr        = 0xD35D,
        player_name_addr   = 0xD157,
        player_id_addr     = 0xD358,
        dv_offset_1        = 0x1B,
        dv_offset_2        = 0x1C,
        otid_offset        = 0x0C,
        species_offset     = 0x00,
        hp_offset          = 0x01,
        maxhp_offset       = 0x22,
        level_offset       = 0x21,
        status_offset      = 0x04,    -- non-volatile status (u8)
        enemy_status_offset = 0x04,   -- same offset in active enemy battle struct
        ball_item_ids      = {0x01, 0x02, 0x03, 0x04},
        badges_addr        = 0xD355,  -- wObtainedBadges (Yellow, shifted -1)
        -- Stat stages (Phase 2, tentative -1 shift from R/B; Phase 9 diagnostic confirms)
        player_stat_stages_addr = 0xCD19,
        enemy_stat_stages_addr  = 0xCD2D,
        stat_stages_count       = 6,
        stat_stages_layout      = "gen1",
    },
}

-- Blue uses same addresses as Red
M.PROFILES.blue = M.PROFILES.red

-- Lowercase alias for game_detect.lua compatibility
M.profiles = M.PROFILES

-- ═══ Gift Areas ═══
M.GIFT_AREAS = {
    pallet_town = true,
    oaks_lab = true,
    celadon_city = true,
    saffron_city = true,
    silph_co = true,
    cinnabar_island = true,
    route_4 = true,
    celadon_game_corner = true,
    gift = true,
}

function M.is_gift_area(area_id)
    if M.GIFT_AREAS[area_id] then return true end
    if area_id and area_id:sub(1, 5) == "gift_" then return true end
    return false
end

-- ═══ ROM Detection ═══

function M.detect()
    -- Check if running on Game Boy
    local ok, sysId = pcall(function() return emu.getsystemid() end)
    if not ok or (sysId ~= "GB" and sysId ~= "GBC") then
        return false
    end
    -- Read ROM title at 0x0134-0x0143 (16 bytes, ASCII)
    local title = M._readRomTitle()
    if not title then return false end
    return title == "POKEMON RED" or title == "POKEMON BLUE" or title == "POKEMON YELLOW"
end

function M.detect_variant()
    local title = M._readRomTitle()
    if title == "POKEMON RED" then return "red" end
    if title == "POKEMON BLUE" then return "blue" end
    if title == "POKEMON YELLOW" then return "yellow" end
    return nil
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
    local names = { red = "Red", blue = "Blue", yellow = "Yellow" }
    return names[variant] or variant
end

-- ═══ Area Resolution ═══
-- Loaded from gen1_rby_areas.lua at runtime

M._area_lookup = nil

function M.resolve_area(mapId)
    if not M._area_lookup then
        local ok, areas = pcall(require, "gen1_rby_areas")
        if ok and areas then
            M._area_lookup = areas
        else
            M._area_lookup = {}
        end
    end
    return M._area_lookup[mapId] or ""
end

return M
