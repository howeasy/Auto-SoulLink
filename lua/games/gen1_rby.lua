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
        -- The game's own wild-encounter preconditions; see M.isInGrass().
        -- wTileMap is NOT shifted in Yellow (both 0xC3A0); the rest are.
        TILE_MAP_ADDR      = 0xC3A0,
        GRASS_TILE_ADDR    = 0xD535,
        GRASS_RATE_ADDR    = 0xD887,
        MOVEMENT_FLAGS_ADDR = 0xD736,
        -- wStatusFlags4. BIT_NO_BATTLES (bit 4) is checked by NewBattle
        -- (home/overworld.asm:362-373), which gates BOTH wild and trainer battles. The
        -- engine only ever clears it in ChooseFlyDestination, the Fly submenu and two
        -- scripts, so a walk cannot clear it -- which is what makes it usable as a
        -- suppression window. Address from data/pret_syms.json, not derived.
        STATUS_FLAGS_4_ADDR = 0xD72E,
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
        -- The twelve STORED boxes, in CartRAM. pokered/ram/sram.asm puts sBox1-sBox6 in
        -- SRAM bank 2 and sBox7-sBox12 in bank 3, each box being
        -- wBoxDataEnd - wBoxDataStart = 1 + 21 + 20*33 + 20*11 + 20*11 = 1122 bytes.
        -- BizHawk's CartRAM domain is flat, so bank n starts at n * 0x2000.
        -- Cross-check: sBox12 = 0x6000 + 5*1122 = 0x75EA, which is exactly the memorial
        -- box offset this file already used -- the memorial box IS Box 12.
        stored_boxes = {count = 12, stride = 1122, per_bank = 6, banks = {0x4000, 0x6000}},
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
        -- The battle struct copies PP straight from the party struct, and the engine
        -- masks it with PP_MASK everywhere it reads it (core.asm:2649, 2729, 3947+),
        -- so the PP-Up bits are present here too.
        enemy_battle_pp_encoding = "ppup_packed",
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
        -- wBattleMonHP. THE PARTY STRUCT IS NOT THE SOURCE OF TRUTH IN BATTLE.
        -- MainInBattleLoop opens every turn with `call ReadPlayerMonCurHPAndStatus`,
        -- which copies wBattleMonHP *into* the party struct ("so it stays after battle
        -- or switching"), and the faint check on the next line reads wBattleMonHP —
        -- engine/battle/core.asm:280-284 and :1798-1809. So a force_faint that writes
        -- only the party struct is overwritten at the top of the next turn and never
        -- observed: the partner's linked mon kept fighting at full HP.
        BATTLE_MON_HP_ADDR      = 0xD015,
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
        -- The game's own wild-encounter preconditions; see M.isInGrass().
        -- wTileMap is NOT shifted in Yellow (both 0xC3A0); the rest are.
        TILE_MAP_ADDR      = 0xC3A0,
        GRASS_TILE_ADDR    = 0xD534,
        GRASS_RATE_ADDR    = 0xD886,
        MOVEMENT_FLAGS_ADDR = 0xD735,
        STATUS_FLAGS_4_ADDR = 0xD72D,   -- Yellow's -1 shift; pret_syms.json
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
        -- The twelve STORED boxes, in CartRAM. pokered/ram/sram.asm puts sBox1-sBox6 in
        -- SRAM bank 2 and sBox7-sBox12 in bank 3, each box being
        -- wBoxDataEnd - wBoxDataStart = 1 + 21 + 20*33 + 20*11 + 20*11 = 1122 bytes.
        -- BizHawk's CartRAM domain is flat, so bank n starts at n * 0x2000.
        -- Cross-check: sBox12 = 0x6000 + 5*1122 = 0x75EA, which is exactly the memorial
        -- box offset this file already used -- the memorial box IS Box 12.
        stored_boxes = {count = 12, stride = 1122, per_bank = 6, banks = {0x4000, 0x6000}},
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
        -- The battle struct copies PP straight from the party struct, and the engine
        -- masks it with PP_MASK everywhere it reads it (core.asm:2649, 2729, 3947+),
        -- so the PP-Up bits are present here too.
        enemy_battle_pp_encoding = "ppup_packed",
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
        BATTLE_MON_HP_ADDR      = 0xD014,   -- wBattleMonHP; see the red block
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
        -- The game's own wild-encounter preconditions; see M.isInGrass().
        -- wTileMap is NOT shifted in Yellow (both 0xC3A0); the rest are.
        TILE_MAP_ADDR      = 0xC3A0,
        GRASS_TILE_ADDR    = 0xD58D,
        GRASS_RATE_ADDR    = 0xD875,
        -- -18, with the rest of that block. This was nil because the fork predates pret's
        -- symbol rename and has no `wMovementFlags` — it still calls the byte `wd736`, so
        -- looking the vanilla NAME up in the AP symbol table found nothing and the field
        -- was left unset, which reads as "this build has no movement flags". It does:
        -- bank 0 references 0xD724 eleven times, exactly as vanilla references 0xD736.
        -- Careful — alchav ALSO has a symbol literally called `wd730` (0xD71E), and that
        -- one is pret's wStatusFlags5, not this.
        MOVEMENT_FLAGS_ADDR = 0xD724,
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
-- INHERITANCE IS A HAZARD, NOT JUST A CONVENIENCE. Every address added to `red`
-- from now on is silently inherited by red_ap/blue_ap, where the Alchav fork has
-- relocated 861 of the 2171 shared symbols — so a field that is merely *new* is
-- also, for AP, *wrong*, with no error anywhere. AP is deferred, so the safe
-- disposition is to disown the fields rather than guess their AP addresses:
-- `false` is a real value, so `__index` never reaches `red`, and every consumer
-- already guards on the field being falsy.
local AP_UNVERIFIED = {
    -- Added for the in-battle force_faint fix. wBattleMonHP sits in the 0xD0xx
    -- block, which the AP fork moves; do not inherit Red's 0xD015.
    "BATTLE_MON_HP_ADDR",
    -- wStatusFlags4 has NO symbol at all in the Alchav fork (checked against
    -- data/pret_syms.json: alchav_pokered has no wStatusFlags4 entry), so there is
    -- nothing to inherit and Red's 0xD72E would be a guess.
    "STATUS_FLAGS_4_ADDR",
}
for _, field in ipairs(AP_UNVERIFIED) do
    M.PROFILES.red_ap[field] = false
end

setmetatable(M.PROFILES.red_ap, {__index = M.PROFILES.red})
-- Blue's AP build shares Red's layout, exactly as vanilla Blue shares vanilla Red's.
M.PROFILES.blue_ap = setmetatable({variant_label = "Blue (AP)"},
                                  {__index = M.PROFILES.red_ap})

-- Lowercase alias for game_detect.lua compatibility
M.profiles = M.PROFILES

-- ═══ Gift Areas ═══
-- MUST MATCH server/adapters/gen1_rby.py's _GIFT_AREAS, name for name.
-- The two halves do different jobs on the same set: Python decides dead-zoning, the ball
-- gate and the three clauses; this one decides whether the client emits `no_catch` at all
-- (and suppresses the new-encounter banner and the area HUD). They drifted, and the drift
-- was silent -- `route_4` was dropped from the Python set as a real grass route, but left
-- here, so Route 4 kept suppressing the only event that can dead-zone it and stayed
-- re-attemptable forever. `tests/unit/test_gen1_gift_areas.py` now reads both files and
-- requires them equal.
M.GIFT_AREAS = {
    pallet_town = true,
    oaks_lab = true,
    celadon_city = true,
    saffron_city = true,
    silph_co = true,
    cinnabar_island = true,
    mt_moon_pokecenter = true,    -- Magikarp salesman
    celadon_mansion_roof = true,  -- Eevee
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
-- ── Reading the cartridge's own encounter tables ─────────────────────────────────────────
-- A run may be played on a ROM randomized with UPR ZX, where the wild tables bear no
-- relation to the ones SLink ships from the decomps. Showing the decomp data beside such a
-- ROM does not merely look stale -- it tells a player Route 1 holds Pidgey when it holds
-- Koffing. So the client reads the tables out of the ROM it is actually running and sends
-- them at hello.
--
-- FLAT ROM OFFSETS, NOT BUS ADDRESSES. Everything below indexes BizHawk's "ROM" domain.
-- On the System Bus 0x4000-0x7FFF is a window onto whichever bank happens to be mapped,
-- which is how an earlier version of detect_archipelago() ended up reading HRAM scratch.
--
-- These offsets are cross-checked two ways: they are what data/pret_rom_syms.json resolves
-- to (WildDataPointers, GoodRodMons, SuperRodData / SuperRodFishingSlots, and the
-- `ld bc, level, species` immediate inside ItemUseOldRod), and they are the same values
-- UPR ZX's own config/gen1_offsets.ini uses to find these tables. Two readers, two
-- sources, same answers.
--
-- Bank 3 holds the wild data and the R/B super-rod groups; the 2-byte pointers stored there
-- are bank-local (0x4000-0x7FFF) and resolve to flat = bank*0x4000 + (ptr - 0x4000).
M.ROM_TABLES = {
    red = {
        wild_ptr = 0x0CEEB, wild_bank = 3,
        old_rod  = 0x0E252,          -- the 0x01 `ld bc,nn` opcode; species +1, level +2
        good_rod = 0x0E27F,          -- 2 x (level, species)
        super_rod = 0x0E919, super_bank = 3, super_format = "rb",
    },
    yellow = {
        wild_ptr = 0x0CB95, wild_bank = 3,
        old_rod  = 0x0E0FF,
        good_rod = 0x0E12C,
        -- Yellow shares no code with R/B here: flat 9-byte records of
        -- map, (species, level) x 4 -- SPECIES FIRST, the opposite order from every other
        -- Gen 1 table. Read the other way the values stay in plausible ranges.
        super_rod = 0xF5EDA, super_format = "yellow",
    },
}
M.ROM_TABLES.blue = M.ROM_TABLES.red

local function _has_rom_domain()
    for _, d in ipairs(memory.getmemorydomainlist()) do
        if d == "ROM" then return true end
    end
    return false
end

--- Read `n` bytes from the flat ROM domain as an uppercase hex string, or nil on failure.
--- Raw bytes rather than parsed values: the SERVER owns the interpretation, so there is one
--- parser for both a ROM file and a client payload instead of two that can disagree.
local function _rom_hex(offset, n)
    local out = {}
    for i = 0, n - 1 do
        local ok, b = pcall(memory.read_u8, offset + i, "ROM")
        if not ok or type(b) ~= "number" then return nil end
        out[#out + 1] = string.format("%02X", b)
    end
    return table.concat(out)
end

local function _rom_u8(offset)
    local ok, b = pcall(memory.read_u8, offset, "ROM")
    if ok and type(b) == "number" then return b end
    return nil
end

--- The wild-encounter records this cartridge actually holds: { [map_id] = hex }.
---
--- Only maps that HAVE encounters are returned. The pointer table is terminated by 0xFFFF
--- (pret writes `dw -1 ; end` after `assert_table_length NUM_MAPS`), and a block of ten
--- slots is present only when its rate byte is non-zero, so an empty map is two zero bytes.
local function _read_wild(spec)
    local out, count = {}, 0
    for map_id = 0, 255 do
        local lo = _rom_u8(spec.wild_ptr + 2 * map_id)
        local hi = _rom_u8(spec.wild_ptr + 2 * map_id + 1)
        if not lo or not hi then return nil end
        local ptr = lo + hi * 256
        if ptr == 0xFFFF then break end
        if ptr < 0x4000 or ptr > 0x7FFF then return nil end
        local rec = spec.wild_bank * 0x4000 + (ptr - 0x4000)
        -- Measure the record before reading it, so the hex we ship is exactly as long as
        -- the data and a truncated read cannot masquerade as an empty method.
        local len, cur = 0, rec
        for _ = 1, 2 do
            local rate = _rom_u8(cur)
            if not rate then return nil end
            len = len + 1
            cur = cur + 1
            if rate ~= 0 then len = len + 20 cur = cur + 20 end
        end
        if len > 2 then
            local hex = _rom_hex(rec, len)
            if not hex then return nil end
            out[tostring(map_id)] = hex
            count = count + 1
        end
    end
    if count == 0 then return nil end
    return out
end

local function _read_super_rod(spec)
    local out = {}
    if spec.super_format == "yellow" then
        local cur = spec.super_rod
        while true do
            local map_id = _rom_u8(cur)
            if not map_id or map_id == 0xFF then break end
            local hex = _rom_hex(cur + 1, 8)      -- 4 x (species, level)
            if not hex then return nil end
            out[tostring(map_id)] = hex
            cur = cur + 9
        end
    else
        local cur = spec.super_rod
        while true do
            local map_id = _rom_u8(cur)
            if not map_id or map_id == 0xFF then break end
            local lo, hi = _rom_u8(cur + 1), _rom_u8(cur + 2)
            if not lo or not hi then return nil end
            local ptr = lo + hi * 256
            if ptr < 0x4000 or ptr > 0x7FFF then return nil end
            local grp = spec.super_bank * 0x4000 + (ptr - 0x4000)
            local n = _rom_u8(grp)
            if not n or n < 1 or n > 10 then return nil end
            local hex = _rom_hex(grp, 1 + 2 * n)  -- count, then n x (level, species)
            if not hex then return nil end
            out[tostring(map_id)] = hex
            cur = cur + 3
        end
    end
    return out
end

--- Everything the server needs to render this ROM's encounters, or nil if it cannot be read.
--- Returning nil is a real answer: the server must then say the encounter data is
--- unavailable rather than fall back to the decomp tables, because vanilla species shown
--- beside a randomized cartridge is precisely the misinformation this exists to remove.
function M.readRomContent(variant)
    if not _has_rom_domain() then return nil end
    local spec = M.ROM_TABLES[variant]
    if not spec then return nil end
    local wild = _read_wild(spec)
    if not wild then return nil end
    local super = _read_super_rod(spec)
    if not super then return nil end
    return {
        variant = variant,
        wild = wild,
        old_rod = _rom_hex(spec.old_rod + 1, 2),    -- species, level
        good_rod = _rom_hex(spec.good_rod, 4),      -- 2 x (level, species)
        super_rod = super,
    }
end


-- ── Rebuilding a boxed mon's stats from the ROM ──────────────────────────────────────────
-- Gen 1's box struct is 33 bytes and stores no computed stats: Attack/Defence/Speed/Special
-- live only in the party's 11-byte tail. Withdrawing therefore has to RECREATE them, and
-- when the deposit-time cache is missing (a client restarted between deposit and withdraw)
-- retrieveBoxMon used to refuse, because rebuilding "would also need a base-stat table we
-- don't ship". We read the ROM now, so it does not need shipping.
--
-- Everything the formula needs is already in the box struct, which is why this is exact
-- rather than an approximation: DVs at +0x1B and the five stat-exp words at
-- +0x11/13/15/17/19 (macros/ram.asm box_struct), plus the level at +0x03 and the base
-- stats from ROM.
--
-- CalcStat, home/move_mon.asm:
--     stat = ((base + IV) * 2 + floor(ceil(sqrt(statexp)) / 4)) * level / 100
--     non-HP:  + 5
--     HP:      + level + 10
--     capped at 999 (MAX_STAT_VALUE)
-- Where the stat inputs live inside a box/party struct (macros/ram.asm box_struct).
-- Declared here rather than in memory_gb because they are Gen 1's layout: the party struct
-- is the box struct plus an 11-byte tail, so the same offsets serve both.
M.BOX_STAT_OFFSETS = {
    hp = 0x11, attack = 0x13, defense = 0x15, speed = 0x17, special = 0x19,
    dvs = 0x1B,
}

M.ROM_BASE_STATS = {
    -- Flat ROM offsets. 28-byte records ordered by POKEDEX number, so record i describes
    -- dex i+1. Identical in all three titles; the difference is Mew.
    red    = {base = 0x383DE, mew = 0x0425B},
    yellow = {base = 0x383DE, mew = nil},   -- Yellow keeps Mew IN the table, at record 150
}
M.ROM_BASE_STATS.blue = M.ROM_BASE_STATS.red
M.BASE_STATS_RECORD = 28

--- ceil(sqrt(n)) the way the engine computes it: the smallest b >= 1 with b*b >= n, capped
--- at 255. Integer arithmetic on purpose -- a float sqrt of a large perfect square can land
--- a whole unit out, and this feeds a division whose result is a stored stat.
local function _ceil_sqrt(n)
    if n <= 0 then return 1 end
    local b = math.floor(math.sqrt(n))
    if b < 1 then b = 1 end
    while b * b < n do b = b + 1 end
    while b > 1 and (b - 1) * (b - 1) >= n do b = b - 1 end
    if b > 255 then b = 255 end
    return b
end

--- The five base stats for a national dex number, read from the cartridge.
function M.readBaseStats(variant, dex)
    local spec = M.ROM_BASE_STATS[variant]
    if not spec or type(dex) ~= "number" or dex < 1 or dex > 151 then return nil end
    local off
    if dex == 151 and spec.mew then
        off = spec.mew
    else
        off = spec.base + M.BASE_STATS_RECORD * (dex - 1)
    end
    local out, ok, b = {}, nil, nil
    for i, field in ipairs({"hp", "attack", "defense", "speed", "special"}) do
        ok, b = pcall(memory.read_u8, off + i, "ROM")
        if not ok or type(b) ~= "number" then return nil end
        out[field] = b
    end
    -- The record leads with its own dex number, so a wrong offset or a relocated table is
    -- caught here instead of producing believable stats for the wrong species.
    ok, b = pcall(memory.read_u8, off, "ROM")
    if not ok or b ~= dex then return nil end
    return out
end

--- Split Gen 1's packed DV word into the five IVs.
--- byte0 = (Atk << 4) | Def, byte1 = (Spd << 4) | Spc, and HP is assembled from the low bit
--- of each of the other four (CalcStat's .getHPIV path) rather than stored.
function M.splitDVs(dv_word)
    local hi, lo = math.floor(dv_word / 256) % 256, dv_word % 256
    local atk, def = math.floor(hi / 16), hi % 16
    local spd, spc = math.floor(lo / 16), lo % 16
    local hp = (atk % 2) * 8 + (def % 2) * 4 + (spd % 2) * 2 + (spc % 2)
    return {hp = hp, attack = atk, defense = def, speed = spd, special = spc}
end

--- Recompute the five party stats. `stat_exp` maps the same field names to 0..65535.
function M.calcStats(base, level, dv_word, stat_exp)
    if not base or type(level) ~= "number" or level < 1 or level > 100 then return nil end
    local ivs = M.splitDVs(dv_word)
    local out = {}
    for _, field in ipairs({"hp", "attack", "defense", "speed", "special"}) do
        local exp = (stat_exp and stat_exp[field]) or 0
        local core = ((base[field] + ivs[field]) * 2
                      + math.floor(_ceil_sqrt(exp) / 4)) * level
        local stat = math.floor(core / 100)
        if field == "hp" then
            stat = stat + level + 10
        else
            stat = stat + 5
        end
        if stat > 999 then stat = 999 end          -- MAX_STAT_VALUE
        out[field] = stat
    end
    return out
end

--- Everything retrieveBoxMon needs, straight from a box slot's own bytes.
--- Returns nil rather than guessing when the ROM cannot be read or the species is unknown,
--- so the caller keeps its refusal instead of writing stats it cannot justify.
function M.rebuildBoxStats(variant, species_index, level, dv_word, stat_exp)
    local dex = M.toNatDex and M.toNatDex(species_index) or nil
    if not dex or dex < 1 or dex > 151 then return nil end
    local base = M.readBaseStats(variant, dex)
    if not base then return nil end
    return M.calcStats(base, level, dv_word, stat_exp)
end

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
