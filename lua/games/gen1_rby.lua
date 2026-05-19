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
        PARTY_COUNT_ADDR   = 0xD163,
        PARTY_SPECIES_ADDR = 0xD164,  -- 6 bytes + 0xFF terminator
        PARTY_BASE_ADDR    = 0xD16B,  -- 6 × 44 bytes
        PARTY_OT_NAMES_ADDR = 0xD273, -- 6 × 11 bytes
        PARTY_NICKS_ADDR   = 0xD2B5,  -- 6 × 11 bytes
        party_struct_size  = 44,
        -- Enemy party
        ENEMY_COUNT_ADDR   = 0xD89C,
        ENEMY_BASE_ADDR    = 0xD8A4,
        -- Current box
        BOX_COUNT_ADDR     = 0xDA80,
        BOX_SPECIES_ADDR   = 0xDA81,  -- 20 bytes + 0xFF terminator
        BOX_BASE_ADDR      = 0xDA96,  -- 20 × 33 bytes
        BOX_OT_NAMES_ADDR  = 0xDD2A,  -- 20 × 11 bytes
        BOX_NICKS_ADDR     = 0xDE06,  -- 20 × 11 bytes (pret wBoxMonNicks; Phase 10 fix from 0xDEB8)
        box_struct_size    = 33,
        box_max_mons       = 20,
        -- Bag
        BAG_COUNT_ADDR     = 0xD31D,
        BAG_ITEMS_ADDR     = 0xD31E,  -- each item = 2 bytes (ID + quantity)
        bag_max_items      = 20,
        -- Battle
        BATTLE_FLAG_ADDR   = 0xD057,  -- 0=overworld, 1=wild, 2=trainer
        -- Active enemy battle mon (wEnemyMon at CFE5, battle_struct layout)
        ENEMY_MON_SPECIES_ADDR = 0xCFE5,  -- internal species index (+0x00)
        ENEMY_MON_HP_ADDR      = 0xCFE6,  -- 2 bytes big-endian (+0x01)
        ENEMY_MON_LEVEL_ADDR   = 0xCFF3,  -- actual level (+0x0E)
        ENEMY_MON_MAXHP_ADDR   = 0xCFF4,  -- 2 bytes big-endian (+0x0F)
        -- Enemy species list (between count and struct): count+1 through count+6
        ENEMY_SPECIES_LIST_ADDR = 0xD89D, -- 6 bytes, each = internal species index
        -- Map
        MAP_ID_ADDR        = 0xD35E,
        -- Player
        PLAYER_NAME_ADDR   = 0xD158,
        PLAYER_ID_ADDR     = 0xD359,  -- 2 bytes, big-endian
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
        BADGES_ADDR        = 0xD356,  -- wObtainedBadges (bitfield, 8 badges)
        -- Stat stages (Phase 2 — DataCrystal RBY RAM map, pret/pokered wram.asm
        -- wPlayerMonAttackMod..wPlayerMonEvasionMod = CD1A..CD1F (6 bytes).
        -- wEnemyMonAttackMod..wEnemyMonEvasionMod   = CD2E..CD33.
        -- Raw range 1..13 (BASE_STAT_LEVEL=7 per pret); client normalizes to 0..12/6.
        -- Gen 1 has 6 stat stages — Special is unified (split into SpA/SpD only in Gen 2).
        PLAYER_STAT_STAGES_ADDR = 0xCD1A,
        ENEMY_STAT_STAGES_ADDR  = 0xCD2E,
        stat_stages_count       = 6,
        stat_stages_layout      = "gen1",  -- {atk, def, spd, spc, acc, eva}
        -- Moves + PP within party struct (Phase 3 — pret/pokered macros, 4 bytes each).
        moves_offset            = 0x08,    -- 4 move IDs at +0x08..0x0B
        pp_offset               = 0x1D,    -- 4 PP bytes at +0x1D..0x20 (simple counters, no PP-Up encoding in Gen 1)
        pp_encoding             = "raw",   -- Gen 1 PP is raw 0..40, no top-bits PP-Up
        -- Enemy battle struct moves + PP (Phase 4 — wEnemyMon is a battle_struct with the
        -- same layout as party_struct in Gen 1). wEnemyMon @ 0xCFE5; moves at +0x08 = 0xCFED;
        -- PP at +0x19 = 0xCFFE (DataCrystal RBY map). PP is raw (no PP-Ups).
        ENEMY_BATTLE_MOVES_ADDR = 0xCFED,
        ENEMY_BATTLE_PP_ADDR    = 0xCFFE,
        enemy_battle_pp_encoding = "raw",
        -- Trainer class + index (Phase 5 — wTrainerClass holds OPP_ID_OFFSET (200)
        -- + const_id per pret/pokered. wTrainerNo is 1-based index within the class.
        -- Working hypothesis 0xD031/0xD05D; Phase 9 diagnostic confirms.
        TRAINER_CLASS_ADDR      = 0xD031,
        TRAINER_ID_ADDR         = 0xD05D,
    },

    -- Yellow has shifted WRAM addresses
    yellow = {
        PARTY_COUNT_ADDR   = 0xD162,
        PARTY_SPECIES_ADDR = 0xD163,
        PARTY_BASE_ADDR    = 0xD16A,
        PARTY_OT_NAMES_ADDR = 0xD272,
        PARTY_NICKS_ADDR   = 0xD2B4,
        party_struct_size  = 44,
        ENEMY_COUNT_ADDR   = 0xD89B,
        ENEMY_BASE_ADDR    = 0xD8A3,
        BOX_COUNT_ADDR     = 0xDA7F,
        BOX_SPECIES_ADDR   = 0xDA80,
        BOX_BASE_ADDR      = 0xDA95,
        BOX_OT_NAMES_ADDR  = 0xDD29,
        BOX_NICKS_ADDR     = 0xDE05,  -- pret wBoxMonNicks; Phase 10 fix from 0xDEB7
        box_struct_size    = 33,
        box_max_mons       = 20,
        BAG_COUNT_ADDR     = 0xD31C,
        BAG_ITEMS_ADDR     = 0xD31D,
        bag_max_items      = 20,
        BATTLE_FLAG_ADDR   = 0xD056,
        ENEMY_MON_SPECIES_ADDR = 0xCFE4,
        ENEMY_MON_HP_ADDR      = 0xCFE5,
        ENEMY_MON_LEVEL_ADDR   = 0xCFF2,
        ENEMY_MON_MAXHP_ADDR   = 0xCFF3,
        ENEMY_SPECIES_LIST_ADDR = 0xD89C,
        MAP_ID_ADDR        = 0xD35D,
        PLAYER_NAME_ADDR   = 0xD157,
        PLAYER_ID_ADDR     = 0xD358,
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
        BADGES_ADDR        = 0xD355,  -- wObtainedBadges (Yellow, shifted -1)
        -- Stat stages (Phase 2, tentative -1 shift from R/B; Phase 9 diagnostic confirms)
        -- Phase 10 fix: Yellow does NOT shift these -1 from R/B (the "Main Data"
        -- section origin is fixed; the Yellow audio adds bytes earlier in WRAM
        -- but doesn't push this region). pret/pokeyellow wPlayerMonAttackMod=0xCD1A.
        PLAYER_STAT_STAGES_ADDR = 0xCD1A,
        ENEMY_STAT_STAGES_ADDR  = 0xCD2E,
        stat_stages_count       = 6,
        stat_stages_layout      = "gen1",
        -- Moves + PP: same struct offsets as Red/Blue (no -1 shift inside the struct).
        moves_offset            = 0x08,
        pp_offset               = 0x1D,
        pp_encoding             = "raw",
        -- Yellow's wEnemyMon is shifted -1 like other battle addresses.
        ENEMY_BATTLE_MOVES_ADDR = 0xCFEC,
        ENEMY_BATTLE_PP_ADDR    = 0xCFFD,
        enemy_battle_pp_encoding = "raw",
        -- Yellow shift -1
        TRAINER_CLASS_ADDR      = 0xD030,
        TRAINER_ID_ADDR         = 0xD05C,
    },
}

-- Blue uses same addresses as Red
M.PROFILES.blue = M.PROFILES.red

-- ═══ Archipelago variants (Phase 8) ═══════════════════════════════════════
-- Pokemon Red/Blue Archipelago (Alchav, official ArchipelagoMW/Archipelago)
-- preserves the vanilla WRAM layout — no address relocation. ROM title at
-- 0x134 is unchanged ("POKEMON RED" / "POKEMON BLUE"); the seed name written
-- to 0xFFDB by the AP patcher distinguishes it from a vanilla cart. Profiles
-- clone vanilla addresses with a variant_label override.
M.PROFILES.red_ap  = setmetatable({variant_label = "Red (AP)"},  {__index = M.PROFILES.red})
M.PROFILES.blue_ap = setmetatable({variant_label = "Blue (AP)"}, {__index = M.PROFILES.blue})

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
    local base
    if title == "POKEMON RED" then base = "red"
    elseif title == "POKEMON BLUE" then base = "blue"
    elseif title == "POKEMON YELLOW" then base = "yellow"
    else return nil end
    -- Phase 8: detect Archipelago patch via seed name at 0xFFDB (21 bytes).
    -- Vanilla ROMs have zeros there; AP-patched ROMs write a seed identifier.
    -- Yellow has no upstream AP world yet — skip the check.
    if base == "yellow" then return base end
    local ok, ap_marker = pcall(function()
        local non_zero = false
        for i = 0, 5 do
            local b = memory.read_u8(0xFFDB + i, "System Bus")
            if b ~= 0 and b ~= 0xFF then non_zero = true; break end
        end
        return non_zero
    end)
    if ok and ap_marker then return base .. "_ap" end
    return base
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
    local names = {
        red = "Red", blue = "Blue", yellow = "Yellow",
        red_ap = "Red (AP)", blue_ap = "Blue (AP)",
    }
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
