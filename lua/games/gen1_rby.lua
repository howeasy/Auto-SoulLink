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
        -- Safe-state predicates. `not in_battle` alone is also true in the PC box UI, the
        -- party menu and the naming screen — all windows where writing party/box memory
        -- corrupts what the open UI is about to write back.
        JOY_IGNORE_ADDR    = 0xCD6B,  -- wJoyIgnore: nonzero while a script owns input
        FONT_LOADED_ADDR   = 0xCFC4,  -- wFontLoaded: bit 0 set while a text box is up
        CURRENT_BOX_NUM_ADDR = 0xD5A0,  -- wCurrentBoxNum (low 7 bits = active box index)

        -- pokered's ChangeBox wipes every SRAM box the first time the player opens the box
        -- menu (engine/menus/save.asm:366). Box 12 is our memorial, so the client claims the
        -- banks first via M.protectSramBoxes(). Geometry from pret: NUM_BOXES 12, 6 per bank
        -- in banks 2/3, wBoxDataEnd-wBoxDataStart = 1122, checksum block at sBank2/3AllBoxes-
        -- Checksum (0xBA4C) = bank base + 0x1A4C. BIT_HAS_CHANGED_BOXES = 7.
        sram_box_layout = {
            box_len = 1122, boxes_per_bank = 6, banks = {2, 3},
            checksum_offset = 0x1A4C,
            changed_boxes_addr = 0xD5A0, changed_boxes_bit = 0x80,
        },
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
        level_offset       = 0x21,    -- actual level (pret wPartyMon1Level, party+0x21)
        -- Computed stats: Atk/Def/Spd/Spc, 2 bytes each, big-endian (wPartyMon1Attack).
        -- Past the 33-byte box struct, so they are lost on deposit — see readPartyStats.
        stats_offset       = 0x24,
        -- pret wBoxMon1BoxLevel is box+0x03. The party level at +0x21 is PAST the end of
        -- the 33-byte box struct, so reading it from a box base lands in the next slot.
        box_level_offset   = 0x03,
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
        -- pret/pokered constants/pokemon_data_constants.asm:101-102 define
        --   PP_UP_MASK EQU %11000000   PP_MASK EQU %00111111
        -- so Gen 1 packs PP-Ups in the top two bits exactly like Gen 2. This said "raw",
        -- which reported a move with PP Ups applied as having up to 3x its real PP.
        pp_encoding             = "ppup_packed",
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
        -- wCurOpponent = trainer class + OPP_ID_OFFSET(200). This is the id the trainer
        -- tables and rival_trainer_ids() are keyed by.
        CUR_OPPONENT_ADDR       = 0xD059,
        -- Enemy party name arrays, needed to write a partner's team faithfully: Gen 1
        -- keeps OT names and nicknames OUTSIDE the mon struct, in parallel arrays.
        ENEMY_OT_NAMES_ADDR     = 0xD9AC,  -- wEnemyMonOT,    6 x 11
        ENEMY_NICKS_ADDR        = 0xD9EE,  -- wEnemyMonNicks, 6 x 11
        -- Explode Mode. The engine reads the player's chosen move from
        -- wPlayerSelectedMove and the slot index from wPlayerMoveListIndex; the active
        -- battler's moves/PP live in wBattleMonMoves/wBattleMonPP.
        PLAYER_SELECTED_MOVE_ADDR = 0xCCDC,
        PLAYER_MOVE_LIST_INDEX_ADDR = 0xCC2E,
        -- Which PARTY slot is currently out. Gen 1 does have this — do not assume slot 0.
        PLAYER_MON_NUMBER_ADDR  = 0xCC2F,
        BATTLE_MON_MOVES_ADDR   = 0xD01C,
        BATTLE_MON_PP_ADDR      = 0xD02D,
        -- Sound-effect dispatch. DISABLED pending live validation.
        -- 0xD35B is wMapMusicSoundID (pret/pokered) — the STORED MAP MUSIC ID, not a
        -- sound hook. Writing SFX ids there corrupted the map's background music on
        -- every capture, gift, faint and whiteout. The real hook is wNewSoundID at
        -- 0xC0EE (same address in Yellow — audio WRAM at 0xC000 is not shifted), but
        -- Gen 1 has NO RAM-writable sound trigger. wNewSoundID (0xC0EE) looks like one and
        -- is not: PlaySound takes the id in register `a` and only uses that address as
        -- internal scratch (pokered home/audio.asm:140), and nothing polls it. So this stays
        -- nil for an unpatched cartridge and playSfx is a no-op. The client raises it to the
        -- companion patch's mailbox byte at runtime when it detects the 'SLNK' beacon —
        -- see M.detectCompanionPatch(). Yellow can never have it (no free WRAM to patch).
        SFX_DISPATCH_ADDR       = nil,  -- set at runtime on patched Red/Blue only
        companion_patch_mailbox = 0xDEE2,  -- 'SLNK' beacon; see patch/gen1/README.md
        -- ROM offset of ChangeBox's `bit BIT_HAS_CHANGED_BOXES, [hl]` (CB 7E), followed by
        -- `call z, EmptyAllSRAMBoxes`. Unique in the dump. The writes gate reads these bytes
        -- so it verifies the game behaviour the memorial guard defends against, rather than
        -- trusting a source read.
        change_box_bit_test_rom_addr = 0x738B2,
        sfx_ids                 = {
            -- Ids are BANK-RELATIVE in Gen 1: the same number is a different sound depending
            -- on which audio bank is loaded (overworld=Audio1, battle=Audio2). Every id below
            -- is one of the 64 that resolve identically in ALL THREE banks, so a capture or a
            -- faint fired mid-battle cannot play the wrong sound. Derived from the SFX header
            -- label offsets in data/pret_rom_syms.json: id = (SFX_X - SFX_Headers_N) / 3.
            -- The expressive Audio1-only alternatives (Denied 0xA5, Collision 0xB4,
            -- Get_Key_Item 0x94) are correct ONLY in the overworld — don't use them here.
            capture   = 0x89,   -- SFX_GET_ITEM_2
            gift      = 0x89,   -- SFX_GET_ITEM_2
            faint     = 0x8C,   -- SFX_TINK
            whiteout  = 0x8C,   -- SFX_TINK
            no_catch  = 0x8C,   -- SFX_TINK
            success   = 0x8D,   -- SFX_HEAL_HP
            failure   = 0x8C,   -- SFX_TINK
            boo       = 0x8C,   -- SFX_TINK
            shiny     = 0x89,   -- SFX_GET_ITEM_2 (Gen 1 has no dedicated shiny SE)
        },
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
        JOY_IGNORE_ADDR    = 0xCD6B,  -- not shifted (0xCDxx block is shared)
        FONT_LOADED_ADDR   = 0xCFC3,
        CURRENT_BOX_NUM_ADDR = 0xD59F,

        -- pokered's ChangeBox wipes every SRAM box the first time the player opens the box
        -- menu (engine/menus/save.asm:366). Box 12 is our memorial, so the client claims the
        -- banks first via M.protectSramBoxes(). Geometry from pret: NUM_BOXES 12, 6 per bank
        -- in banks 2/3, wBoxDataEnd-wBoxDataStart = 1122, checksum block at sBank2/3AllBoxes-
        -- Checksum (0xBA4C) = bank base + 0x1A4C. BIT_HAS_CHANGED_BOXES = 7.
        sram_box_layout = {
            box_len = 1122, boxes_per_bank = 6, banks = {2, 3},
            checksum_offset = 0x1A4C,
            changed_boxes_addr = 0xD59F, changed_boxes_bit = 0x80,
        },
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
        stats_offset       = 0x24,
        box_level_offset   = 0x03,    -- pret wBoxMon1BoxLevel; see the red block
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
        pp_encoding             = "ppup_packed",   -- see the red block
        -- Yellow's wEnemyMon is shifted -1 like other battle addresses.
        ENEMY_BATTLE_MOVES_ADDR = 0xCFEC,
        ENEMY_BATTLE_PP_ADDR    = 0xCFFD,
        enemy_battle_pp_encoding = "raw",
        -- Yellow shift -1
        TRAINER_CLASS_ADDR      = 0xD030,
        TRAINER_ID_ADDR         = 0xD05C,
        CUR_OPPONENT_ADDR       = 0xD058,
        ENEMY_OT_NAMES_ADDR     = 0xD9AB,
        ENEMY_NICKS_ADDR        = 0xD9ED,
        -- 0xCCxx/0xCC2E are NOT shifted in Yellow (only the 0xD0xx+ block is).
        PLAYER_SELECTED_MOVE_ADDR = 0xCCDC,
        PLAYER_MOVE_LIST_INDEX_ADDR = 0xCC2E,
        PLAYER_MON_NUMBER_ADDR  = 0xCC2F,   -- not shifted in Yellow
        BATTLE_MON_MOVES_ADDR   = 0xD01B,
        BATTLE_MON_PP_ADDR      = 0xD02C,
        -- SFX dispatch DISABLED — see the red block. 0xD35A is Yellow's
        -- wMapMusicSoundID, not a sound hook. Note wNewSoundID is 0xC0EE in BOTH games:
        -- the -1 shift applies to the 0xD3xx block, not to audio WRAM at 0xC000.
        -- Yellow can never have SFX: 0xC0EE (wNewSoundID) is PlaySound's scratch, not a
        -- polled mailbox, and Yellow has zero free WRAM for the companion patch that provides
        -- a real one (pret map: WRAM0 TOTAL EMPTY $0000). No companion_patch_mailbox here.
        SFX_DISPATCH_ADDR       = nil,
        change_box_bit_test_rom_addr = 0x73BFB,  -- see the red block
        sfx_ids                 = {
            -- Ids are BANK-RELATIVE in Gen 1: the same number is a different sound depending
            -- on which audio bank is loaded (overworld=Audio1, battle=Audio2). Every id below
            -- is one of the 64 that resolve identically in ALL THREE banks, so a capture or a
            -- faint fired mid-battle cannot play the wrong sound. Derived from the SFX header
            -- label offsets in data/pret_rom_syms.json: id = (SFX_X - SFX_Headers_N) / 3.
            -- The expressive Audio1-only alternatives (Denied 0xA5, Collision 0xB4,
            -- Get_Key_Item 0x94) are correct ONLY in the overworld — don't use them here.
            capture   = 0x89,   -- SFX_GET_ITEM_2
            gift      = 0x89,   -- SFX_GET_ITEM_2
            faint     = 0x8C,   -- SFX_TINK
            whiteout  = 0x8C,   -- SFX_TINK
            no_catch  = 0x8C,   -- SFX_TINK
            success   = 0x8D,   -- SFX_HEAL_HP
            failure   = 0x8C,   -- SFX_TINK
            boo       = 0x8C,   -- SFX_TINK
            shiny     = 0x89,   -- SFX_GET_ITEM_2 (Gen 1 has no dedicated shiny SE)
        },
    },

    -- Archipelago Red/Blue is built from Alchav's FORK of pokered, not from pret, and the
    -- fork adds ~121 lines of WRAM for AP item/event/dexsanity tracking. That relocates
    -- real addresses: 861 of the 2171 WRAM symbols shared with vanilla move.
    --
    -- This profile used to inherit EVERY vanilla address and override only the label, so
    -- an AP run read the wrong byte for its current map, badges, trainer ID, PC box and
    -- enemy party. Listed below are exactly the fields whose pret symbol moved, taken from
    -- `alchav_pokered` in data/pret_syms.json; the ~19 unchanged fields are inherited from
    -- red via the metatable attached just after this table.
    --
    -- Independently corroborated: AP's own client.py reads CurrentMap at WRAM offset
    -- 0x1436, i.e. bus 0xD436 — matching MAP_ID_ADDR here.
    red_ap = {
        -- The AP fork rebuilds the ROM, so vanilla ROM offsets do not carry over.
        change_box_bit_test_rom_addr = false,
        
        variant_label           = "Red (AP)",
        -- +216: AP's tracking block sits ahead of the player-data area.
        MAP_ID_ADDR             = 0xD436,   -- wCurMap
        PLAYER_ID_ADDR          = 0xD431,   -- wPlayerID
        BADGES_ADDR             = 0xD42E,   -- wObtainedBadges
        -- -18: the enemy party block moves DOWN, not up.
        ENEMY_COUNT_ADDR        = 0xD88A,   -- wEnemyPartyCount
        ENEMY_SPECIES_LIST_ADDR = 0xD88B,   -- wEnemyPartySpecies
        ENEMY_BASE_ADDR         = 0xD892,   -- wEnemyMons
        -- +11: the PC box block.
        BOX_COUNT_ADDR          = 0xDA8B,   -- wBoxCount
        BOX_SPECIES_ADDR        = 0xDA8C,   -- wBoxSpecies
        BOX_BASE_ADDR           = 0xDAA1,   -- wBoxMon1
        BOX_OT_NAMES_ADDR       = 0xDD35,   -- wBoxMonOT
        BOX_NICKS_ADDR          = 0xDE11,   -- wBoxMonNicks
        -- +116: wCurrentBoxNum moves further than the rest of the box block.
        CURRENT_BOX_NUM_ADDR    = 0xD614,   -- wCurrentBoxNum

        -- pokered's ChangeBox wipes every SRAM box the first time the player opens the box
        -- menu (engine/menus/save.asm:366). Box 12 is our memorial, so the client claims the
        -- banks first via M.protectSramBoxes(). Geometry from pret: NUM_BOXES 12, 6 per bank
        -- in banks 2/3, wBoxDataEnd-wBoxDataStart = 1122, checksum block at sBank2/3AllBoxes-
        -- Checksum (0xBA4C) = bank base + 0x1A4C. BIT_HAS_CHANGED_BOXES = 7.
        sram_box_layout = {
            box_len = 1122, boxes_per_bank = 6, banks = {2, 3},
            checksum_offset = 0x1A4C,
            changed_boxes_addr = 0xD614, changed_boxes_bit = 0x80,
        },
        -- -18, with the rest of the enemy party block.
        ENEMY_OT_NAMES_ADDR     = 0xD99A,   -- wEnemyMonOT
        ENEMY_NICKS_ADDR        = 0xD9DC,   -- wEnemyMonNicks
        -- JOY_IGNORE_ADDR / FONT_LOADED_ADDR are unmoved (0xCDxx / 0xCFxx), inherited.
    },
}

-- Blue uses same addresses as Red
M.PROFILES.blue = M.PROFILES.red

-- ═══ Archipelago variants ═════════════════════════════════════════════════
-- red_ap is declared INSIDE M.PROFILES above so tools/verify_profile_addresses.py can see
-- it — that parser only walks literal blocks within M.PROFILES. Inheritance of the ~19
-- unchanged fields is attached here, after the table exists.
setmetatable(M.PROFILES.red_ap, {__index = M.PROFILES.red})
-- Blue's AP build shares Red's layout, exactly as vanilla Blue shares vanilla Red's.
M.PROFILES.blue_ap = setmetatable({variant_label = "Blue (AP)"},
                                  {__index = M.PROFILES.red_ap})

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

-- Archipelago writes the multiworld seed name as 20 bytes of Gen 1 charset text to ROM
-- offset 0x5F22 (`Title_Seed`), and the slot name to 0x5F42 — confirmed against the AP
-- world's rom.py and the shipped basepatch, whose unrandomized placeholder decodes to
-- "(NOT RANDOMIZED)".
M.AP_SEED_ROM_OFFSET = 0x5F22
M.AP_SEED_LEN = 16

-- Bytes that can appear in an encoded Gen 1 string: terminator, space, A-Z + punctuation,
-- a-z, and the digit block. Deliberately NOT a full charmap — this only has to separate
-- "looks like text" from "looks like code".
local function _is_text_byte(b)
    return b == 0x50            -- "@" terminator
        or b == 0x7F            -- space
        or (b >= 0x80 and b <= 0x9F)   -- A-Z ( ) : ; [ ]
        or (b >= 0xA0 and b <= 0xB9)   -- a-z
        or (b >= 0xF6 and b <= 0xFF)   -- 0-9
end

-- True when the seed slot holds text rather than the executable code vanilla has there.
-- Measured on the real ROMs: vanilla scores 1/16 text-range bytes, an AP build 16/16, so
-- a 3/4 threshold separates them with enormous margin.
function M.detect_archipelago()
    -- Read the FLAT ROM domain, not the System Bus: 0x5F22 lives in bank 1, and on the
    -- bus 0x4000-0x7FFF is a window onto whatever bank is mapped right now. Self-contained
    -- (BizHawk's `memory` global) because the game module is loaded before initProfile.
    local has_rom = false
    for _, d in ipairs(memory.getmemorydomainlist()) do
        if d == "ROM" then has_rom = true; break end
    end
    if not has_rom then return false end
    local textish = 0
    for i = 0, M.AP_SEED_LEN - 1 do
        local ok, b = pcall(memory.read_u8, M.AP_SEED_ROM_OFFSET + i, "ROM")
        if not ok then return false end
        if _is_text_byte(b) then textish = textish + 1 end
    end
    return textish >= math.floor(M.AP_SEED_LEN * 3 / 4)
end

function M.detect_variant()
    local title = M._readRomTitle()
    local base
    if title == "POKEMON RED" then base = "red"
    elseif title == "POKEMON BLUE" then base = "blue"
    elseif title == "POKEMON YELLOW" then base = "yellow"
    else return nil end
    -- Yellow has no upstream AP world.
    if base == "yellow" then return base end
    -- This used to read CPU 0xFFDB on the System Bus, which is HRAM — runtime scratch,
    -- nonzero during normal play — so every vanilla cart eventually self-identified as
    -- AP. The seed lives in ROM bank 1 and must be read from the flat ROM domain.
    local ok, is_ap = pcall(M.detect_archipelago)
    if ok and is_ap then return base .. "_ap" end
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

-- rom_type is a KEY, not a label: the server maps it through _ROM_TYPE_TO_GAME_ID to pick
-- an adapter, and renders the pretty name from its own _VARIANT_LABEL table. This used to
-- return "Red (AP)", which is in neither table, so an AP run resolved to game_id=None and
-- the hello never bound an adapter. Gen 3 already uses the lowercase-snake form
-- (firered_ap); Gen 1 now matches it.
function M.rom_type_for_variant(variant)
    local names = {
        red = "Red", blue = "Blue", yellow = "Yellow",
        red_ap = "red_ap", blue_ap = "blue_ap",
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
