-- lua/tests/gen1_rb_facts.lua — the VANILLA (Red/Blue) twin of lua/tests/gen1_pure_facts.lua:
-- the same fact groups and leaf names, valued as the R/B harness drivers embed them today
-- (docs/purergb/PLAN.md M2-e / P3b-e). Pure data: no BizWawk API, no side effects, loadable
-- under lupa.
--
-- HOW TO READ THIS FILE
--   * Every fact carries a trailing `-- SAME|DELTA|UNVERIFIED: <citation>` on its own line; a
--     group line carries the tag for the whole group unless a member overrides it. The tags are
--     read from THIS side of the pair:
--     SAME       = gen1_pure_facts.lua carries the same value, and the citation shown is the one
--                  its source check used (that check is what established the two agree). The
--                  value here is the literal the drivers embedded inline before P3b-e.
--     DELTA      = the two foundations disagree; this file carries the vanilla value and the
--                  comment names the pureRGB value.
--     UNVERIFIED = no source line could be opened for it this pass (reason given on the line).
--   * `false` means the thing does not exist in this foundation (no such engine-signal site on a
--     vanilla cartridge).
--   * Citations for SAME rows name pureRGB source or a generated pack under data/games/, exactly
--     as gen1_pure_facts.lua records them; DELTA rows name the vanilla proof (pret source, a
--     vanilla pack file or data/games/gen1_rby/README.md).
--   * Both columns: docs/purergb/research/p3/pure_facts_derivation.md. Key sets and the exact
--     DELTA set are pinned by tests/unit/test_gen1_facts_tables.py.
return {
  MAP = {
    PALLET_TOWN                = 0x00, -- SAME: constants/map_constants.asm:19 "map_const PALLET_TOWN, 10, 9 ; $00"
    VIRIDIAN_CITY              = 0x01, -- SAME: constants/map_constants.asm:20 "; $01"
    CINNABAR_ISLAND            = 0x09, -- SAME: constants/map_constants.asm:28 "; $09" (Sea Routes table)
    ROUTE_1                    = 0x0C, -- SAME: constants/map_constants.asm:33 "map_const ROUTE_1, 10, 18 ; $0C" (D2 left this UNVERIFIED)
    ROUTE_2                    = 0x0D, -- SAME: constants/map_constants.asm:34 "map_const ROUTE_2, 10, 36 ; $0D" (D2 left this UNVERIFIED)
    ROUTE_20                   = 0x1F, -- SAME: constants/map_constants.asm:52 "; $1F" (Sea Routes table)
    ROUTE_22                   = 0x21, -- SAME: constants/map_constants.asm:54 "; $21"
    REDS_HOUSE_1F              = 0x25, -- SAME: constants/map_constants.asm:59 "map_const REDS_HOUSE_1F, 4, 4 ; $25"
    REDS_HOUSE_2F              = 0x26, -- SAME: constants/map_constants.asm:60 "map_const REDS_HOUSE_2F, 4, 4 ; $26" (boot/park map)
    OAKS_LAB                   = 0x28, -- SAME: constants/map_constants.asm:62 "; $28"
    VIRIDIAN_POKECENTER        = 0x29, -- SAME: constants/map_constants.asm:63 "; $29"
    VIRIDIAN_MART              = 0x2A, -- SAME: constants/map_constants.asm:64 "; $2A"
    VIRIDIAN_FOREST_SOUTH_GATE = 0x32, -- SAME: constants/map_constants.asm:72 "; $32"
    VIRIDIAN_FOREST            = 0x33, -- SAME: constants/map_constants.asm:73 "map_const VIRIDIAN_FOREST, 17, 24 ; $33"
  },

  -- ── Species, INTERNAL ids as the wire protocol uses them ───────────────────────────────────
  SPECIES = {
    BULBASAUR  = 153, -- SAME: data/games/gen1_purergb/species_index.json (internal 153)
    CHARMANDER = 176, -- SAME: species_index.json (internal 176 = 0xB0)
    SQUIRTLE   = 177, -- SAME: species_index.json (internal 177 = 0xB1)
    WEEDLE     = 112, -- SAME: species_index.json (internal 112 = 0x70); the forest poison hunt target
    MISSINGNO  = 181, -- SAME: species_index.json (internal 181 = 0xB5, dex 0, classification "missingno")
  },

  -- ── Items ───────────────────────────────────────────────────────────────────────────────────
  ITEM = {
    POKE_BALL   = 0x04, -- SAME: constants/item_constants.asm:13 "const POKE_BALL ; $04" (the parcel driver's purchase check)
    ANTIDOTE    = 0x0B, -- SAME: constants/item_constants.asm:20
    BURN_HEAL   = 0x0C, -- SAME: constants/item_constants.asm:21
    PARLYZ_HEAL = 0x0F, -- SAME: constants/item_constants.asm:24
    OAKS_PARCEL = 0x46, -- SAME: constants/item_constants.asm:79
    BALL_IDS    = {1, 2, 3, 4}, -- DELTA: engine/items/item_effects.asm the ItemUseBall dispatch set MASTER/ULTRA/GREAT/POKE (pureRGB adds HYPER_BALL $05 -> {1,2,3,4,5,8})
  },

  -- ── Moves ───────────────────────────────────────────────────────────────────────────────────
  MOVE = {
    GROWL      = 0x2D, -- SAME: constants/move_constants.asm:53 "const GROWL ; 2d"
    GROWL_SLOT = 2, -- SAME: data/pokemon/base_stats/charmander.asm:13 (level-1 moves SCRATCH, GROWL)
  },

  -- ── Event flags (bit index into wEventFlags) ────────────────────────────────────────────────
  EVENT = {
    GOT_POKEDEX               = 37, -- SAME: constants/event_constants.asm:37 "const EVENT_GOT_POKEDEX"
    GOT_OAKS_PARCEL           = 57, -- SAME: constants/event_constants.asm:51 "const EVENT_GOT_OAKS_PARCEL"
    OAK_GOT_PARCEL            = 56, -- DELTA: .cache/pret/pokered/constants/event_constants.asm:29 (const_next $28 + EVENT_GOT_TM42 + const_skip 14 -> bit 56); pureRGB deleted the event and reads bit 37 (EVENT_GOT_POKEDEX) instead
    OAK_GOT_PARCEL_EXISTS     = true, -- DELTA: the event exists on vanilla (constants/event_constants.asm:29); pureRGB's :50 is a bare const_skip -> false
    OAK_GOT_PARCEL_SUBSTITUTE = false, -- DELTA: no substitute needed - the vanilla flag is read directly; pureRGB reads EVENT_GOT_POKEDEX instead
  },

  -- ── Trainer opponent ids: wCurOpponent = OPP_ID_OFFSET + class ─────────────────────────
  TRAINER = {
    OPP_ID_OFFSET = 200, -- DELTA: data/games/gen1_rby/README.md:96-97 OPP_ID_OFFSET(200) + RIVAL1 $19; pureRGB renumbers (197 + $18)
    OPP_RIVAL1    = 225, -- DELTA: data/games/gen1_rby/README.md:96-97 -> 225, the id the lab and Route 22 drivers assert; pureRGB is 221 (PLAN A12, trainers.json rival_ids)
  },

  -- ── Script-index tables (dw_const row order) ────────────────────────────────────────────────
  SCRIPT = {
    OAKSLAB = {
      DEFAULT                       = 0,
      OAK_ENTERS_LAB                = 1,
      TOGGLE_OAKS                   = 2,
      PLAYER_ENTERS_LAB             = 3,
      FOLLOWED_OAK                  = 4,
      OAK_CHOOSE_MON_SPEECH         = 5,
      PLAYER_DONT_GO_AWAY           = 6,
      PLAYER_FORCED_TO_WALK_BACK    = 7,
      CHOSE_STARTER                 = 8,
      RIVAL_CHOOSES_STARTER         = 9,
      RIVAL_CHALLENGES_PLAYER       = 10,
      RIVAL_START_BATTLE            = 11,
      RIVAL_END_BATTLE              = 12,
      RIVAL_STARTS_EXIT             = 13,
      PLAYER_WATCH_RIVAL_EXIT       = 14,
      RIVAL_ARRIVES_AT_OAKS_REQUEST = 15, -- SAME: scripts/OaksLab.asm:23 (delivery[1])
      OAK_GIVES_POKEDEX             = 16, -- SAME: scripts/OaksLab.asm:24 (delivery[2]; SetEvent EVENT_GOT_POKEDEX fires inside this script)
      RIVAL_LEAVES_WITH_POKEDEX     = 17, -- SAME: scripts/OaksLab.asm:25 (delivery[3])
      NOOP                          = 18, -- SAME: scripts/OaksLab.asm:26 "dw_const DoRet, SCRIPT_OAKSLAB_NOOP"
    },
    PALLETTOWN = {
      DEFAULT                   = 0,
      OAK_HEY_WAIT              = 1,
      OAK_WALKS_TO_PLAYER       = 2,
      OAK_NOT_SAFE_COME_WITH_ME = 3,
      PLAYER_FOLLOWS_OAK        = 4,
      DAISY                     = 5,
      NOOP                      = 6,
    },
    VIRIDIANMART = {
      DEFAULT     = 0,
      OAKS_PARCEL = 1,
      NOOP        = 2,
    },
    LAB_DELIVERY = { delivery = {15, 16, 17}, noop = 18 }, -- SAME: scripts/OaksLab.asm:23-26
  },

  -- ── Viridian Mart ───────────────────────────────────────────────────────────────────────────
  MART = {
    VIRIDIAN_STOCK    = {0x04, 0x0B, 0x0F, 0x0C}, -- SAME: data/items/marts/viridian.asm:2-7 "script_mart POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL"
    VIRIDIAN_BALL_ROW = 0, -- SAME: data/items/marts/viridian.asm:4 (POKE_BALL is the first row; the parcel driver buys at menu_item 0)
    LIST_SIGNATURE = {
      list_menu_id = 2, -- UNVERIFIED: see note above (no single source line states the Mart path's values)
      text_box     = 0x0E, -- UNVERIFIED: see note above
      menu_y       = 1, -- UNVERIFIED: see note above
      menu_x       = 1, -- UNVERIFIED: see note above
      menu_max     = 2, -- UNVERIFIED: see note above
    },
  },

  -- ── Starter movesets: level 1 == level 5 (first new move is level 7+) ───────────────────────
  STARTER_MOVES_LV5 = {
    BULBASAUR  = {"TACKLE", "GROWL"},
    CHARMANDER = {"SCRATCH", "GROWL"},
    SQUIRTLE   = {"TACKLE", "TAIL_WHIP"},
  },

  -- ── Menu geometry ───────────────────────────────────────────────────────────────────────────
  BLACKOUT = { -- where a whiteout puts the player (per SCENARIO: the whiteout lane visits the Viridian Center's PC first)
    default      = { map = 0, x = 5, y = 6 }, -- SAME: new-game blackout point = Pallet Town (RedsHouse1F sets it; poison_new blacks out here on both foundations)
    after_center = { map = 0, x = 5, y = 6 }, -- SAME: pret engine/events/pokecenter.asm:17 sets wLastBlackoutMap only when the nurse HEALS; the whiteout lane uses the Center PC and never heals, so the destination stays the new-game default (Pallet Town)
  },
  LAB_LOSS = { -- the deliberate lab loss (gen1_rb_ball_gate_inputs.lua): Tackle turns before Growl stacking
    tackle_turns = 0, -- SAME: vanilla's rival KOs a Growl-stacked starter in ~15 turns, well inside Growl's 40 PP
    tackle_max_enemy_hp = 0, -- DELTA: vanilla never Tackles in the lab loss (Growl only); pureRGB Tackles while the rival's HP is above its value
  },
  MENU = {
    START = {
      menu_y                     = 2, -- SAME: engine/menus/draw_start_menu.asm:9-10
      menu_x                     = 11, -- SAME: engine/menus/draw_start_menu.asm:9-10
      save_index_without_pokedex = 3, -- SAME: engine/menus/draw_start_menu.asm:64-76 (SAVE is row 3 of 6 without the dex)
      save_index_with_pokedex    = 4, -- SAME: engine/menus/draw_start_menu.asm:64-76 (the dex is a prepended row)
      max_minus_save             = 3, -- DELTA: engine/menus/draw_start_menu.asm stores the row COUNT (6 without the dex, 7 with), so menu_max == save_index + 3; pureRGB stores the last 0-based row index -> +2
    },
    SAVE_PROMPT = {
      text_box  = 0x14,
      menu_y    = 8,
      menu_x    = 1,
      menu_max  = 1,
      yes_index = 0,
    },
    BATTLE = {
      menu_y        = 14,
      left_x        = 9,
      right_x       = 15,
      menu_max      = 1,
      left_watched  = 0x11, -- PAD_RIGHT | PAD_A
      right_watched = 0x21, -- PAD_LEFT | PAD_A
      template      = 0x0B, -- constants/menu_constants.asm BATTLE_MENU_TEMPLATE $0b
    },
    MOVE       = { menu_y = 0x0C, menu_x = 5 }, -- SAME: engine/battle/core.asm:2714 "hlcoord 4, 12" + :2726-2727 "ld b, $5 / ld a, $c"
    PARTY      = { menu_y = 1, menu_x = 0, watched = 0x03 }, -- SAME: home/pokemon.asm:128-131 (Y=1, X=0) + engine/menus/party_menu.asm:301-303 (PAD_A|PAD_B in battle)
    SWITCH_BOX = { menu_y = 0x0C, menu_x = 0x0C, menu_max = 2, watched = 0x03 }, -- SAME: engine/battle/core.asm:2564-2573 ("ld a, $c" twice, "ld a, $2", PAD_B|PAD_A)
    NAMING     = { menu_y = 2, menu_x = 1, menu_max = 3, watched = 0x01 }, -- SAME: engine/movie/oak_speech/oak_speech2.asm:172-182 (X=1, watched=PAD_A, Y=2, max=3); 4 rows = NEW NAME + 3 presets (constants/player_constants.asm:1 NUM_PLAYER_NAMES=3)
    BAG        = { menu_y = 4, menu_x = 5, watched = 0x07 }, -- SAME: pret home/list_menu.asm DisplayListMenuID (Y=4, X=5, PAD_A|PAD_B|PAD_SELECT)
    PC = {
      menu_y     = 2, -- SAME: engine/pokemon/bills_pc.asm:77-79
      menu_x     = 1, -- SAME: engine/pokemon/bills_pc.asm:77-79
      -- `main` is the PC MAIN menu's first row (SOMEONE's/BILL's PC) and `withdraw`..`seeya` are
      -- BILL's PC menu rows: two screens, both placing rows at (2,2),(2,4),... so the offsets
      -- coincide. `next` in a menu string moves two tile rows (BillsPCMenuText below).
      main       = 42, -- SAME: engine/pokemon/bills_pc.asm:33 (DisplayPCMainMenu, hlcoord 2,2 = 42)
      withdraw   = 42, -- SAME: engine/pokemon/bills_pc.asm:126 (BillsPCMenu, hlcoord 2,2) + BillsPCMenuText :341-347
      deposit    = 82, -- SAME: engine/pokemon/bills_pc.asm:341-347 (row 2 of BillsPCMenuText)
      release    = 122, -- SAME: engine/pokemon/bills_pc.asm:341-347 (row 3, RELEASE)
      changebox  = 162, -- SAME: engine/pokemon/bills_pc.asm:341-347 (row 4, CHANGE BOX)
      seeya      = 202, -- SAME: engine/pokemon/bills_pc.asm:341-347 (row 5, SEE YA!)
      sub_action = 251, -- SAME: engine/pokemon/bills_pc.asm:393 (hlcoord 11,12 = 251)
      sub_cancel = 331, -- SAME: engine/pokemon/bills_pc.asm:395 (hlcoord 11,14 / 11,16 = 291 / 331)
      list       = 86, -- SAME: home/list_menu.asm:364 (hlcoord 6,4 = 86)
      list_step  = 40, -- SAME: home/list_menu.asm:364 region (entries two tile rows apart)
      text1      = 281, -- SAME: home/text.asm:242 (hlcoord 1, 14) + data/text_boxes.asm:10 MESSAGE_BOX 0,12,19,17
      text2      = 321, -- SAME: home/text.asm:242 region (the box's second line, two rows below the first)
      -- The two confirmation screens the driver presses through; both are YesNoChoice here
      -- (home/yes_no.asm:3-18 -> the two-option box at hlcoord 14,7 with b=8/c=15).
      release_confirm = {
        menu_y   = 8, -- SAME: home/yes_no.asm:18 "lb bc, 8, 15" (b = the menu Y)
        menu_x   = 15, -- SAME: home/yes_no.asm:18 (c = the menu X)
        yes      = 176, -- SAME: home/yes_no.asm:17 + engine/menus/text_box.asm:278-279 (strings one row below the corner)
        no       = 216, -- SAME: engine/menus/text_box.asm:278-279 (NO one row below YES)
        menu_max = 1, -- SAME: engine/menus/text_box.asm:219-220 "ld a, $1 / ld [wMaxMenuItem], a"
        confirm  = "A", -- SAME: engine/pokemon/bills_pc.asm:304-311 (OnceReleasedText -> YesNoChoice; A on YES releases)
      },
      changebox_prompt = {
        menu_y   = 8, -- SAME: engine/menus/save.asm:361 "call YesNoChoice" (the same box)
        menu_x   = 15, -- SAME: engine/menus/save.asm:361
        menu_max = 1, -- SAME: engine/menus/save.asm:361
        yes      = 176, -- SAME: engine/menus/save.asm:361
        no       = 216, -- SAME: engine/menus/save.asm:361
        hide     = false, -- SAME: a two-option box has no third entry
      },
      box_menu = {
        menu_y    = 1, -- SAME: engine/menus/save.asm:444-445 "ld a, 1 / ld [wTopMenuItemY], a"
        menu_x    = 12, -- SAME: engine/menus/save.asm:446-447 "ld a, 12 / ld [wTopMenuItemX], a"
        menu_max  = 11, -- SAME: engine/menus/save.asm:442-443 "ld a, 11 / ld [wMaxMenuItem], a"
        name      = 33, -- SAME: engine/menus/save.asm:467 (hlcoord 13,1 = 33, BoxNames, single-spaced)
        name_step = 20, -- SAME: one box per tile row; n=12 -> 33 + 11*20 = 253
        count_col = false, -- SAME: vanilla has no count column -- the names themselves are at column 13
      },
    },
  },

  -- ── Poison (engine/events/poison.asm) ───────────────────────────────────────────────────────
  POISON = {
    psn_mask         = 0x08, -- SAME: engine/events/poison.asm:16 "and 1 << PSN" + constants/battle_constants.asm:65 "const PSN ; 3"
    hp_per_tick      = 1, -- SAME: engine/events/poison.asm:25 ("subtract 1 from HP")
    steps_per_tick   = 4, -- SAME: engine/events/poison.asm:8-10 (wStepCounter & $3 -> damage every fourth step)
    status_bit_shift = 3, -- SAME: engine/events/poison.asm:16 (the driver's floor(status/8)%%2 test)
  },

  -- ── Catch odds (engine/items/item_effects.asm ItemUseBall) ──────────────────────────────────
  CATCH = {
    maxhp_factor   = 255, -- SAME: engine/items/item_effects.asm:108 (ItemUseBall); W = floor(floor(maxhp*255/12) / max(floor(hp/4),1))
    maxhp_divisor  = 12, -- SAME: engine/items/item_effects.asm:108 region
    hp_divisor     = 4, -- SAME: engine/items/item_effects.asm:108 region
    sure_catch_w   = 255, -- SAME: engine/items/item_effects.asm:108 region (W >= 255 is a certain catch)
    first_rand_max = 255, -- SAME: engine/items/item_effects.asm:193-199 "; Poke Ball: [0, 255]"
    great_rand_max = 200, -- SAME: engine/items/item_effects.asm:194 "; Great Ball/Safari: [0, 200]"
    ultra_rand_max = 150, -- SAME: engine/items/item_effects.asm:195 "; Ultra Ball: [0, 150]"
    hunt_ball_min  = 1, -- SAME: engine/items/item_effects.asm:23-26 (MASTER/ULTRA/GREAT/POKE Ball all dispatch to ItemUseBall)
    hunt_ball_max  = 4, -- DELTA: the vanilla ball dispatch stops at POKE_BALL $04 (engine/items/item_effects.asm:23-26); pureRGB adds HYPER_BALL $05 -> 5
  },

  -- ── Companion overlay/patch ABI (PLAN M3 B5). The two tables carry the SAME frame counts —
  -- only the addresses that anchor them move, and pureRGB's overlay runs the overworld at 2x
  -- emulator speed (CGB double-speed), which is why speed_multiplier is recorded at all: the
  -- windows below are counted in FRAMES, not wall time, so a 2x core does not scale them. ──────
  COMPANION = {
    playtime_frames_addr   = 0xDA44, -- SAME: pret ram/wram.asm wPlayTimeFrames (test_gen1_patch_gate.lua measured this address directly; pureRGB moves it, see gen1_pure_facts.lua DELTA)
    channel_sound_ids_addr = 0xC026, -- SAME: pret ram/wram.asm wChannelSoundIDs (data/purergb/pokered.sym wChannelSoundIDs agrees)
    speed_multiplier       = 1, -- SAME: the vanilla companion patch runs at native DMG/CGB single speed
    panel_stage_timeout    = 90, -- SAME: patch/gen1/src/slink.asm SLINK_STAGE_TIMEOUT (patch/gen1/purergb/README.md "stage 90" is the same ABI)
    panel_deadline         = 60, -- SAME: lua/gen1/panel.lua DEADLINE (measured from the transition the client observed, tighter than the patch's own poll)
    query_frames           = 30, -- SAME: patch/gen1/purergb/README.md B5 "the same timings (QUERY 30, ...)"
    offer_frames           = 180, -- SAME: patch/gen1/purergb/README.md B5 "OFFER 180"
    settle_frames          = 20, -- SAME: patch/gen1/purergb/README.md B5 "settle 20" (ROM 20-frame button settle)
    apply_frames           = 100, -- SAME: patch/gen1/purergb/README.md B5 "apply 100" (native apply pre-animation delay)
  },

  -- ── Engine-signal banks per hook ────────────────────────────────────────────────────────────

  -- ── ── Engine-signal banks per hook (data/games/gen1_rby/engine_signals.json; the 5 battle-menu hooks gen1_battle_driver.lua hooks are bank $0F) ──
  BANKS = {
    add_party_mon        = 0x0, -- SAME: data/games/gen1_rby/engine_signals.json sites.add_party_mon.bank = 0x0 (pureRGB sites.add_party_mon.bank agrees)
    bag_received         = 0x3, -- SAME: data/games/gen1_rby/engine_signals.json sites.bag_received.bank = 0x3 (pureRGB sites.bag_received.bank agrees)
    battle_begin         = 0xf, -- SAME: data/games/gen1_rby/engine_signals.json sites.battle_begin.bank = 0xf (pureRGB sites.battle_begin.bank agrees)
    battle_end           = 0x4, -- DELTA: data/games/gen1_rby/engine_signals.json sites.battle_end.bank = 0x4 (pureRGB moved it to 0x3a)
    battle_faint         = 0xf, -- SAME: data/games/gen1_rby/engine_signals.json sites.battle_faint.bank = 0xf (pureRGB sites.battle_faint.bank agrees)
    battle_loop_head     = 0xf, -- SAME: data/games/gen1_rby/engine_signals.json sites.battle_loop_head.bank = 0xf (pureRGB sites.battle_loop_head.bank agrees)
    blackout             = 0x1, -- SAME: data/games/gen1_rby/engine_signals.json sites.blackout.bank = 0x1 (pureRGB sites.blackout.bank agrees)
    capture_box          = 0x3, -- SAME: data/games/gen1_rby/engine_signals.json sites.capture_box.bank = 0x3 (pureRGB sites.capture_box.bank agrees)
    evolve               = 0xe, -- DELTA: data/games/gen1_rby/engine_signals.json sites.evolve.bank = 0xe (pureRGB moved it to 0x2c)
    move_mon             = 0x0, -- SAME: data/games/gen1_rby/engine_signals.json sites.move_mon.bank = 0x0 (pureRGB sites.move_mon.bank agrees)
    npc_trade            = 0x1c, -- SAME: data/games/gen1_rby/engine_signals.json sites.npc_trade.bank = 0x1c (pureRGB sites.npc_trade.bank agrees)
    poison_faint         = 0x3, -- SAME: data/games/gen1_rby/engine_signals.json sites.poison_faint.bank = 0x3 (pureRGB sites.poison_faint.bank agrees)
    remove_pokemon       = 0x0, -- SAME: data/games/gen1_rby/engine_signals.json sites.remove_pokemon.bank = 0x0 (pureRGB sites.remove_pokemon.bank agrees)
    save_witness         = 0x1c, -- SAME: data/games/gen1_rby/engine_signals.json sites.save_witness.bank = 0x1c (pureRGB sites.save_witness.bank agrees)
    starter_begin        = 0x7, -- SAME: data/games/gen1_rby/engine_signals.json sites.starter_begin.bank = 0x7 (pureRGB sites.starter_begin.bank agrees)
    starter_end          = 0x7, -- SAME: data/games/gen1_rby/engine_signals.json sites.starter_end.bank = 0x7 (pureRGB sites.starter_end.bank agrees)
    wild_begin           = 0xf, -- SAME: data/games/gen1_rby/engine_signals.json sites.wild_begin.bank = 0xf (pureRGB sites.wild_begin.bank agrees)
    apex_commit          = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    apex_preflight       = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    apex_recalc_call     = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    cable_partial_save   = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    cable_trade_add      = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    cable_trade_remove   = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    capture_box_begin    = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    capture_box_end      = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    capture_party_begin  = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    capture_party_end    = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    changebox_full_save  = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    daycare_withdraw     = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    evolve_species_store = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    npc_trade_add        = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    npc_trade_done       = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    npc_trade_remove     = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    pc_deposit           = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    pc_release           = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    pc_withdraw          = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    trainer_staging      = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    transform            = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    transform_hp_hi      = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    transform_hp_lo      = false, -- DELTA: no such engine-signal site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17; pureRGB has 40)
    display_battle_menu  = 0x0F, -- SAME: data/pret/pokered.sym display_battle_menu is bank $0F, the filter gen1_battle_driver.lua:76 carried inline (data/purergb/pokered.sym agrees)
    move_selection_menu  = 0x0F, -- SAME: data/pret/pokered.sym move_selection_menu is bank $0F, the filter gen1_battle_driver.lua:76 carried inline (data/purergb/pokered.sym agrees)
    select_enemy_move    = 0x0F, -- SAME: data/pret/pokered.sym select_enemy_move is bank $0F, the filter gen1_battle_driver.lua:76 carried inline (data/purergb/pokered.sym agrees)
    execute_player_move  = 0x0F, -- SAME: data/pret/pokered.sym execute_player_move is bank $0F, the filter gen1_battle_driver.lua:76 carried inline (data/purergb/pokered.sym agrees)
    execute_enemy_move   = 0x0F, -- SAME: data/pret/pokered.sym execute_enemy_move is bank $0F, the filter gen1_battle_driver.lua:76 carried inline (data/purergb/pokered.sym agrees)
  },

  -- ── Harness tuning (foundation-independent; kept so both lanes use the same bounds) ─────────
  TUNING = {
    input_cadence          = 16, -- SAME: lua/tests/gen1_inputs_common.lua:42
    run_repress            = 120, -- SAME: lua/tests/gen1_battle_driver.lua:58
    stall_bound            = 1800, -- SAME: lua/tests/gen1_rb_forest_inputs.lua:164 / gen1_rb_route22_inputs.lua:112
    stall_nudge            = 48, -- SAME: lua/tests/gen1_rb_forest_inputs.lua:165
    detour_frames          = 32, -- SAME: lua/tests/gen1_rb_forest_inputs.lua:166
    detour_bound           = 4, -- SAME: lua/tests/gen1_rb_forest_inputs.lua:167 (added by 94f0058)
    detour_backoffs        = 3, -- SAME: lua/tests/gen1_rb_forest_inputs.lua:168
    battle_bound           = 60000, -- SAME: lua/tests/gen1_rb_route22_inputs.lua:117
    trigger_grace          = 600, -- SAME: lua/tests/gen1_rb_route22_inputs.lua:118
    max_encounters_hunt    = 6, -- SAME: lua/tests/gen1_rb_hunt_inputs.lua:25
    max_encounters_forest  = 60, -- SAME: lua/tests/gen1_rb_forest_inputs.lua:161
    max_grass_steps        = 2000, -- SAME: lua/tests/gen1_rb_forest_inputs.lua:162
    max_growl_turns        = 20, -- SAME: lua/tests/gen1_rb_forest_inputs.lua:163
    wild_run_attempt_bound = 8, -- SAME: lua/tests/gen1_rb_route1_inputs.lua:39
  },

  -- ── Client / emulator settings ─────────────────────────────────────────────────────────────
  CLIENT = {
    speedmode   = 6399, -- SAME: lua/tests/gen1_gate.lua:55 (BizHawk-level, not a ROM fact)
    tick_frames = 30, -- SAME: lua/gen1/client.lua:18 (TICK_INTERVAL)
  },

  -- ── Waypoints: tile coordinates, not ROM constants ─────────────────────────────────────────
  WAYPOINTS = {

    -- ── SAME: the tiles lua/tests/gen1_rb_parcel_inputs.lua:27-34 already walks; live-proven on pureRGB too (PLAN §11.2 Live 3)
    PARCEL = {
      lab_exit       = { {5,11} },
      pallet_north   = { {12,11}, {9,11}, {9,2}, {10,2}, {10,-1} },
      route_north    = { {10,31}, {8,31}, {8,24}, {12,24}, {12,22}, {9,22}, {9,14}, {14,14}, {14,4}, {11,4}, {11,-1} },
      viridian_mart  = { {20,35}, {20,30}, {19,30}, {19,20}, {29,20}, {29,19} },
      viridian_south = { {29,20}, {19,20}, {19,30}, {20,30}, {20,36} },
      route_south    = { {10,4}, {14,4}, {14,14}, {9,14}, {9,22}, {12,22}, {12,24}, {8,24}, {8,31}, {10,31}, {10,36} },
      pallet_lab     = { {10,2}, {9,2}, {9,12}, {12,12}, {12,11} },
      lab_oak        = { {5,11}, {5,3} },
      park           = {10, 35},
    },

    -- ── SAME: the tiles lua/tests/gen1_rb_route1_inputs.lua:13-18 already walks; live-proven on pureRGB too
    ROUTE1 = {
      mart_exit      = { {3,7} },
      viridian_south = { {29,20}, {19,20}, {19,30}, {20,30}, {20,36} },
      route_south    = { {10,4}, {14,4}, {14,14}, {9,14}, {9,22}, {12,22}, {12,24}, {8,24}, {8,31}, {10,31}, {10,35} },
      park           = {10, 35},
    },

    -- ── UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_hunt_inputs.lua:20-24
    HUNT = {
      park  = {10, 35}, -- UNVERIFIED: tile coordinates, vanilla-only so far
      grass = { {10, 33}, {10, 35} }, -- UNVERIFIED: tile coordinates, vanilla-only so far
    },

    -- ── UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17
    CENTER = {
      lab_exit        = { map = 0x28, next = 0x00, waypoints = { {5,11} } }, -- UNVERIFIED: tile coordinates, vanilla-only so far
      pallet_north    = { map = 0x00, next = 0x0C, waypoints = { {12,11}, {9,11}, {9,2}, {10,2}, {10,-1} } }, -- UNVERIFIED: tile coordinates, vanilla-only so far
      route_one_north = { map = 0x0C, next = 0x01, waypoints = { {10,31}, {8,31}, {8,24}, {12,24}, {12,22}, {9,22}, {9,14}, {14,14}, {14,4}, {11,4}, {11,-1} } }, -- UNVERIFIED: tile coordinates, vanilla-only so far
      viridian_center = { map = 0x01, next = 0x29, waypoints = { {20,30}, {19,30}, {19,26}, {23,26}, {23,25} } }, -- UNVERIFIED: tile coordinates, vanilla-only so far
      center_recept   = { map = 0x29, waypoints = { {3,4}, {11,4}, {11,3} } }, -- UNVERIFIED: tile coordinates, vanilla-only so far
    },

    -- ── UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_forest_inputs.lua:158-160
    FOREST = {
      park    = {18, 41}, -- UNVERIFIED: tile coordinates, vanilla-only so far
      pace    = { {18, 41}, {18, 40} }, -- UNVERIFIED: tile coordinates, vanilla-only so far
      shuttle = { {18, 43}, {18, 44} }, -- UNVERIFIED: tile coordinates, vanilla-only so far
    },

    -- ── UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_route22_inputs.lua:111
    ROUTE22 = {
      trigger = { {29, 5}, {29, 4} }, -- UNVERIFIED: tile coordinates, vanilla-only so far
    },
  },
}
