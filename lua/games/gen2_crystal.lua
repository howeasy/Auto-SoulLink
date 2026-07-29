--[[
  lua/games/gen2_crystal.lua — Game module for Gen 2: Pokémon Crystal (US English).

  Provides detection, memory profiles, gift area definitions, and area resolution
  for the shared memory_gb.lua module and the gen2_crystal_client.lua client.

  Source: pret/pokecrystal wram.asm, data/maps/, constants/pokemon_data_constants.asm
  Crystal species IDs are sequential NatDex 1-251 (no index table needed).
--]]

local M = {}
M.game_id = "gen2_crystal"
M.display_name = "Crystal / Gold / Silver"
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

-- ═══ Ball item IDs ═══
-- DERIVED, not transcribed: these are exactly the items pret files in the BALL pocket
-- (data/items/attributes.asm, whose row N is item N+1 — the table starts at MASTER_BALL).
-- Identical in pokecrystal and pokegold, so all three profiles share one list.
--
-- The previous list had the Apricorn balls at 0xA9-0xAF, which are really SUN_STONE,
-- POLKADOT_BOW, UP_GRADE, BERRY, GOLD_BERRY and SQUIRTBOTTLE, and Park Ball at 0xB2
-- instead of 0xB1. Since the Balls pocket can only ever hold real balls, that produced no
-- false positives — it produced SILENCE: a player carrying only Kurt's Apricorn balls read
-- as having none, so the Nuzlocke gate never opened and no rule was enforced all run.
--
-- LIGHT_BALL (0xA3) is deliberately absent. It is Pikachu's held item, not a ball, and it
-- is filed in the ITEM pocket — the one entry that name-matching would get wrong.
local BALL_ITEM_IDS = {
    0x01,   -- MASTER_BALL
    0x02,   -- ULTRA_BALL
    0x04,   -- GREAT_BALL
    0x05,   -- POKE_BALL
    0x9D,   -- HEAVY_BALL
    0x9F,   -- LEVEL_BALL
    0xA0,   -- LURE_BALL
    0xA1,   -- FAST_BALL
    0xA4,   -- FRIEND_BALL
    0xA5,   -- MOON_BALL
    0xA6,   -- LOVE_BALL
    0xB1,   -- PARK_BALL (unobtainable in Gold/Silver, but in their pocket table too)
}

-- ═══ Memory Profiles ═══
-- Crystal US (CGB-BYTE-0). Addresses from pret/pokecrystal wram.asm.
-- Crystal has no variants — one profile covers all US ROMs.

M.PROFILES = {
    crystal = {
        -- Party (source: wram.asm wPartyCount / wPartyMons / wPartyMon1)
        PARTY_COUNT_ADDR     = 0xDCD7,
        PARTY_SPECIES_ADDR   = 0xDCD8,  -- 6 bytes + 0xFF terminator
        PARTY_BASE_ADDR      = 0xDCDF,  -- 6 × 48 bytes
        PARTY_OT_NAMES_ADDR  = 0xDDFF,  -- 6 × 11 bytes
        PARTY_NICKS_ADDR     = 0xDE41,  -- 6 × 11 bytes
        party_struct_size    = 48,

        -- Enemy party (wOTPartyCount / wOTPartyMons)
        ENEMY_COUNT_ADDR     = 0xD280,  -- verified vs pret by tools/verify_profile_addresses.py
        ENEMY_BASE_ADDR      = 0xD288,  -- verified vs pret by tools/verify_profile_addresses.py

        -- Current active box in SRAM (wBoxCount / wBoxMons)
        -- These addresses are System Bus view (0xA000+offset). Accessed via CartRAM domain.
        -- Layout: count(1) + species(21) + mons(20*32=640) + OT_names(20*11=220) + nicks(20*11=220)
        BOX_COUNT_ADDR       = 0xAD10,
        -- wCurBox: the active PC box, 0-based. Gen 1 packs a "changed boxes"
        -- flag into bit 7 of its equivalent; Gen 2's is a plain index, and the
        -- shared mask is harmless on 0..13.
        CURRENT_BOX_NUM_ADDR = 0xDB72,
        -- The safe-state predicate: nonzero while a script or a full-screen menu owns the
        -- game. Named JOY_IGNORE_ADDR because that is the shared key memory_gb's
        -- isInOverworld() reads; Gen 1's equivalent really is wJoyIgnore.
        --
        -- MEASURED, not chosen by name (lua/tests/probe_gen2_safestate.lua on real Crystal):
        --   wScriptRunning  00 overworld -> FF with the START menu open -> 00 closed   USABLE
        --   wJoypadDisable  00 in BOTH — the obvious Gen 1 analogue, and it does not fire
        --   wTextboxFlags   01 in both — it is text-SPEED config, not "a box is open"
        --   wMapEventStatus differs but does not return to its overworld value
        -- Gating writes on `not in_battle` alone is what this replaces: that is also true in
        -- the PC box UI, the party menu and the naming screen, where the open UI holds its
        -- own copy of the data and writes it back over ours.
        JOY_IGNORE_ADDR      = 0xD438,
        BOX_SPECIES_ADDR     = 0xAD11,                  -- ends at 0xAD25
        BOX_BASE_ADDR        = 0xAD26,                  -- ends at 0xAFA5 (20*32=640 bytes)
        BOX_OT_NAMES_ADDR    = 0xAFA6,                  -- ends at 0xB081 (20*11=220 bytes)
        BOX_NICKS_ADDR       = 0xB082,                  -- ends at 0xB15D (20*11=220 bytes)
        box_struct_size      = 32,
        box_max_mons         = 20,
        box_in_sram          = true,  -- access via CartRAM domain (not System Bus)
        sram_bank            = 1,    -- active box is in SRAM bank 1

        -- Ball pocket (wBallsCount / wBalls in wram.asm)
        -- Crystal has a dedicated ball pocket like Gen 3.
        BAG_COUNT_ADDR       = 0xD8D7,
        BAG_ITEMS_ADDR       = 0xD8D8,  -- each entry = 2 bytes (ID + quantity)
        bag_max_items        = 12,      -- ball pocket max size

        -- Battle (wBattleMode: 0=overworld, 1=wild, 2=trainer)
        BATTLE_FLAG_ADDR     = 0xD22D,  -- verified vs pret by tools/verify_profile_addresses.py

        -- Active enemy battle mon (wEnemyMon / wBattleMon structure)
        -- Source: DataCrystal RAM map — battle struct is NOT the same as party struct
        ENEMY_MON_SPECIES_ADDR = 0xD206,
        ENEMY_MON_HP_ADDR      = 0xD216,  -- current HP (2 bytes BE)
        ENEMY_MON_LEVEL_ADDR   = 0xD213,
        ENEMY_MON_MAXHP_ADDR   = 0xD218,  -- max HP (2 bytes BE)

        -- Enemy species list
        ENEMY_SPECIES_LIST_ADDR = 0xD281, -- verified vs pret by tools/verify_profile_addresses.py

        -- Map (2-byte group:number addressing)
        MAP_GROUP_ADDR       = 0xDCB5,   -- wMapGroup
        MAP_NUMBER_ADDR      = 0xDCB6,   -- wMapNumber

        -- Player (wPlayerID, wPlayerName)
        PLAYER_ID_ADDR       = 0xD47B,   -- 2 bytes big-endian
        PLAYER_NAME_ADDR     = 0xD47D,

        -- Badges
        BADGES_ADDR          = 0xD857,   -- wJohtoBadges (bitfield, 8 badges)
        KANTO_BADGES_ADDR    = 0xD858,   -- wKantoBadges (bitfield, 8 badges)

        -- Party struct offsets (48 bytes, pret/pokecrystal macros/wram.asm)
        species_offset       = 0x00,    -- species ID (sequential NatDex)
        held_item_offset     = 0x01,    -- held item (new in Gen 2)
        otid_offset          = 0x06,    -- 2 bytes big-endian OT ID
        dv_offset_1          = 0x15,    -- Atk/Def DVs
        dv_offset_2          = 0x16,    -- Spd/Spc DVs
        level_offset         = 0x1F,    -- actual level (party-calculated)
        hp_offset            = 0x22,    -- current HP (2 bytes big-endian)
        maxhp_offset         = 0x24,    -- max HP (2 bytes big-endian)
        status_offset        = 0x20,
        -- party_struct tail (pret macros/ram.asm): Atk +0x26, Def +0x28, Spd +0x2A,
        -- SpclAtk +0x2C, SpclDef +0x2E. Gen 2 SPLIT Special, so spdef_offset is a
        -- real address here rather than the alias of spAtk it is in Gen 1.
        stats_offset         = 0x26,
        spdef_offset         = 0x2E,    -- non-volatile status (u8: bits 0-2 SLP, 3 PSN, 4 BRN, 5 FRZ, 6 PAR, 7 TOX)
        -- wEnemyMon is a battle_struct (NOT party_struct). Offsets confirmed by the
        -- profile's other battle-struct addresses: ENEMY_MON_LEVEL_ADDR-SPECIES = 0x0D,
        -- ENEMY_MON_HP_ADDR-SPECIES = 0x10, MaxHP at 0x12 → Status sits at 0x0E.
        enemy_status_offset  = 0x0E,    -- battle_struct status offset (was wrongly 0x20)

        -- Box struct offsets (32 bytes — truncated party struct, no stats)
        box_species_offset   = 0x00,
        box_held_item_offset = 0x01,
        box_otid_offset      = 0x06,
        box_dv_offset_1      = 0x15,
        box_dv_offset_2      = 0x16,
        box_level_offset     = 0x1F,    -- box level (level at time of deposit)

        ball_item_ids        = BALL_ITEM_IDS,

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
        -- Phase 10: pret-authoritative wPlayerStatLevels=0xC6CC, wEnemyStatLevels=0xC6D4
        -- (was 0xC68A/0xC691 working hypothesis from SECTION analysis — corrected).
        PLAYER_STAT_STAGES_ADDR = 0xC6CC,
        ENEMY_STAT_STAGES_ADDR  = 0xC6D4,
        stat_stages_count       = 7,
        stat_stages_layout      = "gen2",  -- {atk, def, spd, satk, sdef, acc, eva}

        -- Moves + PP within party struct (Phase 3 — pret/pokecrystal macros).
        -- Moves at +0x02..0x05 (4 bytes), PP at +0x17..0x1A (4 bytes).
        -- Gen 2 PP byte format: bits 0-5 = current PP (0..63), bits 6-7 = PP-Up
        -- count (0..3). Constants PP_MASK=0x3F, PP_UP_MASK=0xC0 per
        -- pret/pokecrystal engine/items/item_effects.asm.
        moves_offset            = 0x02,
        pp_offset               = 0x17,
        pp_encoding             = "ppup_packed",

        -- Enemy battle struct moves + PP (Phase 4 — wEnemyMon battle struct
        -- has its own layout, NOT party_struct). Per DataCrystal Crystal RAM
        -- map: wEnemyMon @ 0xD206 (species); moves @ 0xD208 (+0x02); PP @ 0xD20E (+0x08).
        -- Enemy battle PP is raw (no PP-Up encoding — display only, not bred).
        ENEMY_BATTLE_MOVES_ADDR = 0xD208,
        ENEMY_BATTLE_PP_ADDR    = 0xD20E,
        enemy_battle_pp_encoding = "raw",

        -- Trainer class + index (Phase 5 — wOtherTrainerClass / wOtherTrainerID
        -- per pret/pokecrystal). Phase 10: pret-authoritative wOtherTrainerClass=0xD22F,
        -- wOtherTrainerID=0xD231 (Phase 5 hypothesis was 0xD233/0xD234 — corrected).
        -- Class is 1-based per pret constants (FALKNER=1, BUGSY=3, BROCK=17, etc.),
        -- trainer_id is 1-based within class.
        TRAINER_CLASS_ADDR      = 0xD22F,
        TRAINER_ID_ADDR         = 0xD231,
        -- Phase 7: Sound-effect dispatch. wMusicID at 0xC2BD per pret/pokecrystal.
        -- The audio engine consumes the byte on the next audio frame.
        -- SFX IDs from constants/sfx_constants.asm.
        -- wMusicID. This said 0xC2BD, which is wCryTracks — the comment named the right
        -- symbol and the value was a different one, exactly the shape of the Gen 1 SFX bug
        -- (that one pointed at wMapMusicSoundID and corrupted the map's BGM on every capture
        -- and faint). UNVERIFIED ON HARDWARE: Gen 1 also taught that the right-looking symbol
        -- need not be a trigger at all — wNewSoundID turned out to be PlaySound's internal
        -- scratch, so no address would have worked. Treat sound as unproven until a probe
        -- shows wChannelSoundIDs actually changing.
        SFX_DISPATCH_ADDR       = 0xC29D,
        sfx_ids                 = {
            capture   = 0x44,   -- SFX_CAUGHT_MON
            gift      = 0x44,   -- SFX_CAUGHT_MON
            faint     = 0x46,   -- SFX_FAINT
            whiteout  = 0x46,   -- SFX_FAINT
            no_catch  = 0x39,   -- SFX_NO
            success   = 0x4A,   -- SFX_GET_BADGE (link formed, nuzlocke start)
            failure   = 0x39,   -- SFX_NO
            boo       = 0x39,   -- SFX_NO
            shiny     = 0xB5,   -- SFX_SHINY
        },
    },

    -- ═══ Pokémon Gold (Phase 11 — Gold/Silver Phase 10-style addresses) ═══
    -- pret/pokegold + pret/pokegold's _GOLD build. Gold/Silver share the same
    -- WRAM/SRAM layout (the _GOLD vs _SILVER ASM flag affects trainer-party
    -- data only, not memory layout). All addresses below were verified via
    -- tools/verify_profile_addresses.py against pret/pokegold/master .sym.
    --
    -- WRAM layout differs substantially from Crystal because Crystal added
    -- the Mobile Adapter, Phone, and Time Capsule sections which shifted
    -- everything in WRAMX bank 1. Roughly: Gold/Silver addresses are
    -- 690 bytes EARLIER in WRAMX than the equivalent Crystal addresses.
    gold = {
        -- Party (pret/pokegold wPartyCount / wPartyMon1)
        PARTY_COUNT_ADDR     = 0xDA22,
        PARTY_SPECIES_ADDR   = 0xDA23,  -- 6 bytes + 0xFF terminator
        PARTY_BASE_ADDR      = 0xDA2A,  -- 6 × 48 bytes
        PARTY_OT_NAMES_ADDR  = 0xDB4A,
        PARTY_NICKS_ADDR     = 0xDB8C,
        party_struct_size    = 48,

        -- Enemy party (pret/pokegold wOTPartyCount / wOTPartyMons)
        ENEMY_COUNT_ADDR     = 0xDD55,
        ENEMY_SPECIES_LIST_ADDR = 0xDD56,
        ENEMY_BASE_ADDR      = 0xDD5D,

        -- Current active box (SRAM bank 1)
        BOX_COUNT_ADDR       = 0xAD6C,  -- sBoxCount
        -- wCurBox: the active PC box, 0-based. Gen 1 packs a "changed boxes"
        -- flag into bit 7 of its equivalent; Gen 2's is a plain index, and the
        -- shared mask is harmless on 0..13.
        CURRENT_BOX_NUM_ADDR = 0xD8BC,
        -- The safe-state predicate: nonzero while a script or a full-screen menu owns the
        -- game. Named JOY_IGNORE_ADDR because that is the shared key memory_gb's
        -- isInOverworld() reads; Gen 1's equivalent really is wJoyIgnore.
        --
        -- MEASURED, not chosen by name (lua/tests/probe_gen2_safestate.lua on real Crystal):
        --   wScriptRunning  00 overworld -> FF with the START menu open -> 00 closed   USABLE
        --   wJoypadDisable  00 in BOTH — the obvious Gen 1 analogue, and it does not fire
        --   wTextboxFlags   01 in both — it is text-SPEED config, not "a box is open"
        --   wMapEventStatus differs but does not return to its overworld value
        -- Gating writes on `not in_battle` alone is what this replaces: that is also true in
        -- the PC box UI, the party menu and the naming screen, where the open UI holds its
        -- own copy of the data and writes it back over ours.
        JOY_IGNORE_ADDR      = 0xD15F,
        BOX_SPECIES_ADDR     = 0xAD6D,  -- sBoxSpecies
        BOX_BASE_ADDR        = 0xAD82,  -- sBoxMons (20 × 32 bytes)
        BOX_OT_NAMES_ADDR    = 0xB002,  -- sBoxMonOTs
        BOX_NICKS_ADDR       = 0xB0DE,  -- sBoxMonNicknames
        box_struct_size      = 32,
        box_max_mons         = 20,
        box_in_sram          = true,
        sram_bank            = 1,

        -- Ball pocket (wNumBalls / wBalls)
        BAG_COUNT_ADDR       = 0xD5FC,
        BAG_ITEMS_ADDR       = 0xD5FD,
        bag_max_items        = 12,

        -- Battle (wBattleMode: 0=overworld, 1=wild, 2=trainer)
        BATTLE_FLAG_ADDR     = 0xD116,

        -- Active enemy battle struct (wEnemyMon @ 0xD0EF — different offsets
        -- than Crystal's 0xD206 because the Mobile-related sections aren't here)
        ENEMY_MON_SPECIES_ADDR = 0xD0EF,
        ENEMY_MON_HP_ADDR      = 0xD0FF,
        ENEMY_MON_LEVEL_ADDR   = 0xD0FC,
        ENEMY_MON_MAXHP_ADDR   = 0xD101,

        -- Map (2-byte group:number addressing, same as Crystal)
        MAP_GROUP_ADDR       = 0xDA00,
        MAP_NUMBER_ADDR      = 0xDA01,

        -- Player
        PLAYER_ID_ADDR       = 0xD1A1,
        PLAYER_NAME_ADDR     = 0xD1A3,

        -- Badges
        BADGES_ADDR          = 0xD57C,  -- wJohtoBadges
        KANTO_BADGES_ADDR    = 0xD57D,  -- wKantoBadges

        -- Party struct offsets (identical to Crystal — 48-byte party_struct
        -- macro is shared across pokegold/pokecrystal)
        species_offset       = 0x00,
        held_item_offset     = 0x01,
        otid_offset          = 0x06,
        dv_offset_1          = 0x15,
        dv_offset_2          = 0x16,
        level_offset         = 0x1F,
        hp_offset            = 0x22,
        maxhp_offset         = 0x24,
        status_offset        = 0x20,
        -- party_struct tail (pret macros/ram.asm): Atk +0x26, Def +0x28, Spd +0x2A,
        -- SpclAtk +0x2C, SpclDef +0x2E. Gen 2 SPLIT Special, so spdef_offset is a
        -- real address here rather than the alias of spAtk it is in Gen 1.
        stats_offset         = 0x26,
        spdef_offset         = 0x2E,
        -- battle_struct, not party_struct: wEnemyMonStatus(0xD0FD) - wEnemyMon(0xD0EF) = 0x0E.
        -- Was 0x20 (the party_struct offset). Crystal was fixed and these two were missed.
        enemy_status_offset  = 0x0E,

        -- Box struct offsets (32-byte truncated party_struct)
        box_species_offset   = 0x00,
        box_held_item_offset = 0x01,
        box_otid_offset      = 0x06,
        box_dv_offset_1      = 0x15,
        box_dv_offset_2      = 0x16,
        box_level_offset     = 0x1F,

        ball_item_ids        = BALL_ITEM_IDS,

        generation     = 2,
        uses_map_group = true,
        is_egg_species = 0xFD,

        -- Stat stages (pret/pokegold wPlayerStatLevels / wEnemyStatLevels)
        PLAYER_STAT_STAGES_ADDR = 0xCBAA,
        ENEMY_STAT_STAGES_ADDR  = 0xCBB2,
        stat_stages_count       = 7,
        stat_stages_layout      = "gen2",

        -- Moves + PP — Gen 2 party_struct layout is identical to Crystal
        moves_offset            = 0x02,
        pp_offset               = 0x17,
        pp_encoding             = "ppup_packed",

        -- Enemy battle moves + PP (wEnemyMonMoves / wEnemyMonPP)
        ENEMY_BATTLE_MOVES_ADDR = 0xD0F1,
        ENEMY_BATTLE_PP_ADDR    = 0xD0F7,
        enemy_battle_pp_encoding = "raw",

        -- Trainer class / id (wOtherTrainerClass / wOtherTrainerID)
        TRAINER_CLASS_ADDR      = 0xD118,
        TRAINER_ID_ADDR         = 0xD11B,
    },

    -- Silver shares Gold's WRAM/SRAM layout (the _GOLD vs _SILVER pret build
    -- flag only differs in trainer party data, not memory layout). Profile
    -- duplicated explicitly so verify_profile_addresses.py validates each
    -- address against pokegold.sym independently.
    silver = {
        PARTY_COUNT_ADDR     = 0xDA22,
        PARTY_SPECIES_ADDR   = 0xDA23,
        PARTY_BASE_ADDR      = 0xDA2A,
        PARTY_OT_NAMES_ADDR  = 0xDB4A,
        PARTY_NICKS_ADDR     = 0xDB8C,
        party_struct_size    = 48,
        ENEMY_COUNT_ADDR     = 0xDD55,
        ENEMY_SPECIES_LIST_ADDR = 0xDD56,
        ENEMY_BASE_ADDR      = 0xDD5D,
        BOX_COUNT_ADDR       = 0xAD6C,
        -- wCurBox: the active PC box, 0-based. Gen 1 packs a "changed boxes"
        -- flag into bit 7 of its equivalent; Gen 2's is a plain index, and the
        -- shared mask is harmless on 0..13.
        CURRENT_BOX_NUM_ADDR = 0xD8BC,
        -- The safe-state predicate: nonzero while a script or a full-screen menu owns the
        -- game. Named JOY_IGNORE_ADDR because that is the shared key memory_gb's
        -- isInOverworld() reads; Gen 1's equivalent really is wJoyIgnore.
        --
        -- MEASURED, not chosen by name (lua/tests/probe_gen2_safestate.lua on real Crystal):
        --   wScriptRunning  00 overworld -> FF with the START menu open -> 00 closed   USABLE
        --   wJoypadDisable  00 in BOTH — the obvious Gen 1 analogue, and it does not fire
        --   wTextboxFlags   01 in both — it is text-SPEED config, not "a box is open"
        --   wMapEventStatus differs but does not return to its overworld value
        -- Gating writes on `not in_battle` alone is what this replaces: that is also true in
        -- the PC box UI, the party menu and the naming screen, where the open UI holds its
        -- own copy of the data and writes it back over ours.
        JOY_IGNORE_ADDR      = 0xD15F,
        BOX_SPECIES_ADDR     = 0xAD6D,
        BOX_BASE_ADDR        = 0xAD82,
        BOX_OT_NAMES_ADDR    = 0xB002,
        BOX_NICKS_ADDR       = 0xB0DE,
        box_struct_size      = 32,
        box_max_mons         = 20,
        box_in_sram          = true,
        sram_bank            = 1,
        BAG_COUNT_ADDR       = 0xD5FC,
        BAG_ITEMS_ADDR       = 0xD5FD,
        bag_max_items        = 12,
        BATTLE_FLAG_ADDR     = 0xD116,
        ENEMY_MON_SPECIES_ADDR = 0xD0EF,
        ENEMY_MON_HP_ADDR      = 0xD0FF,
        ENEMY_MON_LEVEL_ADDR   = 0xD0FC,
        ENEMY_MON_MAXHP_ADDR   = 0xD101,
        MAP_GROUP_ADDR       = 0xDA00,
        MAP_NUMBER_ADDR      = 0xDA01,
        PLAYER_ID_ADDR       = 0xD1A1,
        PLAYER_NAME_ADDR     = 0xD1A3,
        BADGES_ADDR          = 0xD57C,
        KANTO_BADGES_ADDR    = 0xD57D,
        species_offset       = 0x00,
        held_item_offset     = 0x01,
        otid_offset          = 0x06,
        dv_offset_1          = 0x15,
        dv_offset_2          = 0x16,
        level_offset         = 0x1F,
        hp_offset            = 0x22,
        maxhp_offset         = 0x24,
        status_offset        = 0x20,
        -- party_struct tail (pret macros/ram.asm): Atk +0x26, Def +0x28, Spd +0x2A,
        -- SpclAtk +0x2C, SpclDef +0x2E. Gen 2 SPLIT Special, so spdef_offset is a
        -- real address here rather than the alias of spAtk it is in Gen 1.
        stats_offset         = 0x26,
        spdef_offset         = 0x2E,
        -- battle_struct, not party_struct: wEnemyMonStatus(0xD0FD) - wEnemyMon(0xD0EF) = 0x0E.
        -- Was 0x20 (the party_struct offset). Crystal was fixed and these two were missed.
        enemy_status_offset  = 0x0E,
        box_species_offset   = 0x00,
        box_held_item_offset = 0x01,
        box_otid_offset      = 0x06,
        box_dv_offset_1      = 0x15,
        box_dv_offset_2      = 0x16,
        box_level_offset     = 0x1F,
        ball_item_ids        = BALL_ITEM_IDS,
        generation     = 2,
        uses_map_group = true,
        is_egg_species = 0xFD,
        PLAYER_STAT_STAGES_ADDR = 0xCBAA,
        ENEMY_STAT_STAGES_ADDR  = 0xCBB2,
        stat_stages_count       = 7,
        stat_stages_layout      = "gen2",
        moves_offset            = 0x02,
        pp_offset               = 0x17,
        pp_encoding             = "ppup_packed",
        ENEMY_BATTLE_MOVES_ADDR = 0xD0F1,
        ENEMY_BATTLE_PP_ADDR    = 0xD0F7,
        enemy_battle_pp_encoding = "raw",
        TRAINER_CLASS_ADDR      = 0xD118,
        TRAINER_ID_ADDR         = 0xD11B,
    },
}

-- ═══ Archipelago variant ═════════════════════════════════════════════════
-- THE "SAME LAYOUT AS VANILLA" ASSUMPTION IS FALSE, and it is falsifiable without a ROM.
--
-- The shipped pokemon_crystal.apworld carries its own `ram_addresses` table
-- (pokemon_crystal/data/data.json, WRAM-domain offsets that add 0xC000). Diffed against
-- data/pret_syms.json's vanilla pokecrystal, the fork moves things by FOUR different amounts
-- and in both directions:
--
--     wMapEventStatus  0xD433 -> 0xD437   +4
--     wMapGroup        0xDCB5 -> 0xDCC0  +11
--     wMapNumber       0xDCB6 -> 0xDCC1  +11
--     wEventFlags      0xDA72 -> 0xDA8F  +29
--     wStatusFlags     0xD84C -> 0xD827  -37
--
-- So a blanket `setmetatable(..., {__index = crystal})` served WRONG addresses for anything
-- past an insertion point. Gen 1's red_ap had exactly this bug (+88 / -18 / +216).
--
-- WHAT IS AND IS NOT KNOWN. Only those five vanilla symbols appear in the apworld's table,
-- and there is no public fork repo to build a full symbol set from (the URL the docs used to
-- name is gone), so tools/build_pret_syms.py cannot do for AP Crystal what it does for
-- alchav_pokered. The five below are overridden because they are PROVEN wrong. Every other
-- address is still inherited and is therefore UNVERIFIED — it may well be right, and there is
-- no evidence either way.
--
-- Consequently AP Crystal is NOT claimed as supported. Treat this profile as "vanilla plus
-- the five corrections we can prove" until a live gate on a generated AP ROM says otherwise.
-- tests/unit/test_gen2_ap_addresses.py pins these five against the apworld's own data so the
-- profile cannot silently drift from what AP itself declares.
M.PROFILES.crystal_ap = setmetatable({
    variant_label  = "Crystal (AP)",
    -- Proven from the apworld's ram_addresses (see above).
    MAP_GROUP_ADDR  = 0xDCC0,   -- wMapGroup,  vanilla 0xDCB5 (+11)
    MAP_NUMBER_ADDR = 0xDCC1,   -- wMapNumber, vanilla 0xDCB6 (+11)
    -- Recorded for the address checker and for whoever builds the live gate. The profile has
    -- no key for these today; they are the only other fork addresses we can prove.
    ap_known_addresses = {
        wMapEventStatus = 0xD437,
        wStatusFlags    = 0xD827,
        wEventFlags     = 0xDA8F,
    },
    -- Everything else is inherited from vanilla Crystal and NOT verified.
    ap_addresses_unverified = true,
}, {__index = M.PROFILES.crystal})

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
    -- Crystal is GBC-only; Gold/Silver run on both GB and GBC.
    local ok, sysId = pcall(function() return emu.getsystemid() end)
    if not ok or (sysId ~= "GBC" and sysId ~= "GB") then
        return false
    end
    local title = M._readRomTitle()
    if not title then return false end
    -- ROM titles per pret/pokecrystal + pret/pokegold Makefiles:
    --   "PM_CRYSTAL" — vanilla Crystal
    --   "AP_CRYSTAL" — gerbiljames Archipelago-Crystal fork
    --   "POKEMON_GLD" — vanilla Gold
    --   "POKEMON_SLV" — vanilla Silver
    return title == "PM_CRYSTAL" or title == "AP_CRYSTAL"
        or title == "POKEMON_GLD" or title == "POKEMON_SLV"
        or title:find("CRYSTAL") ~= nil
end

function M.detect_variant()
    -- Phase 8: distinguish AP-patched ROM from vanilla.
    -- Phase 11: also detect Gold / Silver.
    local title = M._readRomTitle()
    if title == "AP_CRYSTAL"  then return "crystal_ap" end
    if title == "POKEMON_GLD" then return "gold" end
    if title == "POKEMON_SLV" then return "silver" end
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
    if variant == "crystal_ap" then return "Crystal (AP)" end
    if variant == "gold"       then return "Gold" end
    if variant == "silver"     then return "Silver" end
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
