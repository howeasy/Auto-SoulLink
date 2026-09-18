# pureRGB driver-facts derivation (P3b-e)

Companion to `lua/tests/gen1_pure_facts.lua`, regenerated from both facts files: every fact the two
tables carry, with the VANILLA value, the pureRGB value, a status and the citation behind the
status. The vanilla column is `lua/tests/gen1_rb_facts.lua` (the drivers' own literals), the
pureRGB column is the pure file.

- **SAME** — the two foundations agree (the pure file's source check established it).
- **DELTA** — they disagree; the pureRGB column is what a pureRGB lane must use.
- **UNVERIFIED** — no source line could be opened for it (reason given on the row).

Sources: the pinned pureRGB checkout (commit `7e7a4653`) and the packs under `data/games/gen1_purergb/`; `data/games/gen1_rby/engine_signals.json` and `data/pret/pokered.sym` /
`data/purergb/pokered.sym` for the vanilla column, which no earlier revision of this table had.

Counts: **250 rows** — SAME 176, DELTA 49, UNVERIFIED 25.

## Table

| key | vanilla | pureRGB | status | citation |
|---|---|---|---|---|
| `MAP.PALLET_TOWN` | `0` | `0` | SAME | SAME: constants/map_constants.asm:19 "map_const PALLET_TOWN, 10, 9 ; $00" |
| `MAP.VIRIDIAN_CITY` | `1` | `1` | SAME | SAME: constants/map_constants.asm:20 "; $01" |
| `MAP.CINNABAR_ISLAND` | `9` | `9` | SAME | SAME: constants/map_constants.asm:28 "; $09" (Sea Routes table) |
| `MAP.ROUTE_1` | `12` | `12` | SAME | SAME: constants/map_constants.asm:33 "map_const ROUTE_1, 10, 18 ; $0C" (D2 left this UNVERIFIED) |
| `MAP.ROUTE_2` | `13` | `13` | SAME | SAME: constants/map_constants.asm:34 "map_const ROUTE_2, 10, 36 ; $0D" (D2 left this UNVERIFIED) |
| `MAP.ROUTE_20` | `31` | `31` | SAME | SAME: constants/map_constants.asm:52 "; $1F" (Sea Routes table) |
| `MAP.ROUTE_22` | `33` | `33` | SAME | SAME: constants/map_constants.asm:54 "; $21" |
| `MAP.REDS_HOUSE_1F` | `37` | `37` | SAME | SAME: constants/map_constants.asm:59 "map_const REDS_HOUSE_1F, 4, 4 ; $25" |
| `MAP.REDS_HOUSE_2F` | `38` | `38` | SAME | SAME: constants/map_constants.asm:60 "map_const REDS_HOUSE_2F, 4, 4 ; $26" (boot/park map) |
| `MAP.OAKS_LAB` | `40` | `40` | SAME | SAME: constants/map_constants.asm:62 "; $28" |
| `MAP.VIRIDIAN_POKECENTER` | `41` | `41` | SAME | SAME: constants/map_constants.asm:63 "; $29" |
| `MAP.VIRIDIAN_MART` | `42` | `42` | SAME | SAME: constants/map_constants.asm:64 "; $2A" |
| `MAP.VIRIDIAN_FOREST_SOUTH_GATE` | `50` | `50` | SAME | SAME: constants/map_constants.asm:72 "; $32" |
| `MAP.VIRIDIAN_FOREST` | `51` | `51` | SAME | SAME: constants/map_constants.asm:73 "map_const VIRIDIAN_FOREST, 17, 24 ; $33" |
| `SPECIES.BULBASAUR` | `153` | `153` | SAME | SAME: data/games/gen1_purergb/species_index.json (internal 153) |
| `SPECIES.CHARMANDER` | `176` | `176` | SAME | SAME: species_index.json (internal 176 = 0xB0) |
| `SPECIES.SQUIRTLE` | `177` | `177` | SAME | SAME: species_index.json (internal 177 = 0xB1) |
| `SPECIES.WEEDLE` | `112` | `112` | SAME | SAME: species_index.json (internal 112 = 0x70); the forest poison hunt target |
| `SPECIES.MISSINGNO` | `181` | `181` | SAME | SAME: species_index.json (internal 181 = 0xB5, dex 0, classification "missingno") |
| `ITEM.POKE_BALL` | `4` | `4` | SAME | SAME: constants/item_constants.asm:13 "const POKE_BALL ; $04" (the parcel driver's purchase check) |
| `ITEM.ANTIDOTE` | `11` | `11` | SAME | SAME: constants/item_constants.asm:20 |
| `ITEM.BURN_HEAL` | `12` | `12` | SAME | SAME: constants/item_constants.asm:21 |
| `ITEM.PARLYZ_HEAL` | `15` | `15` | SAME | SAME: constants/item_constants.asm:24 |
| `ITEM.OAKS_PARCEL` | `70` | `70` | SAME | SAME: constants/item_constants.asm:79 |
| `ITEM.BALL_IDS` | `[1, 2, 3, 4]` | `[1, 2, 3, 4, 5, 8]` | DELTA | DELTA: data/games/gen1_purergb/items.json ball_items == the ItemUseBall dispatch set at engine/items/item_effects.asm:23-30 (vanilla 1..4 misses HYPER_BALL $05) |
| `MOVE.GROWL` | `45` | `45` | SAME | SAME: constants/move_constants.asm:53 "const GROWL ; 2d" |
| `MOVE.GROWL_SLOT` | `2` | `2` | SAME | SAME: data/pokemon/base_stats/charmander.asm:13 (level-1 moves SCRATCH, GROWL) |
| `EVENT.GOT_POKEDEX` | `37` | `37` | SAME | SAME: constants/event_constants.asm:37 "const EVENT_GOT_POKEDEX" |
| `EVENT.GOT_OAKS_PARCEL` | `57` | `57` | SAME | SAME: constants/event_constants.asm:51 "const EVENT_GOT_OAKS_PARCEL" |
| `EVENT.OAK_GOT_PARCEL` | `56` | `37` | DELTA | DELTA: bit 56 no longer exists (constants/event_constants.asm:50 "used to be EVENT_OAK_GOT_PARCEL but it's no different from EVENT_GOT_POKEDEX") — read GOT_POKEDEX instead |
| `EVENT.OAK_GOT_PARCEL_EXISTS` | `true` | `false` | DELTA | DELTA: constants/event_constants.asm:50 (bare const_skip) |
| `EVENT.OAK_GOT_PARCEL_SUBSTITUTE` | `false` | `"GOT_POKEDEX"` | DELTA | DELTA: constants/event_constants.asm:37 |
| `TRAINER.OPP_ID_OFFSET` | `200` | `197` | DELTA | DELTA: docs/purergb/PLAN.md A12 "OPP_ID_OFFSET = 197" (was 200); data/games/gen1_purergb/trainers.json opp_id_offset |
| `TRAINER.OPP_RIVAL1` | `225` | `221` | DELTA | DELTA: data/games/gen1_purergb/trainers.json rival_ids[0] == 221 (class 221 is RIVAL1); PLAN A12 "rivals 221 / 237 / 238" — the id the lab and Route 22 drivers must assert (vanilla 225) |
| `SCRIPT.OAKSLAB.DEFAULT` | `0` | `0` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.OAK_ENTERS_LAB` | `1` | `1` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.TOGGLE_OAKS` | `2` | `2` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.PLAYER_ENTERS_LAB` | `3` | `3` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.FOLLOWED_OAK` | `4` | `4` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.OAK_CHOOSE_MON_SPEECH` | `5` | `5` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.PLAYER_DONT_GO_AWAY` | `6` | `6` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.PLAYER_FORCED_TO_WALK_BACK` | `7` | `7` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.CHOSE_STARTER` | `8` | `8` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.RIVAL_CHOOSES_STARTER` | `9` | `9` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.RIVAL_CHALLENGES_PLAYER` | `10` | `10` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.RIVAL_START_BATTLE` | `11` | `11` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.RIVAL_END_BATTLE` | `12` | `12` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.RIVAL_STARTS_EXIT` | `13` | `13` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.PLAYER_WATCH_RIVAL_EXIT` | `14` | `14` | SAME | SAME: scripts/OaksLab.asm:8-26 (same script names, same order as vanilla) |
| `SCRIPT.OAKSLAB.RIVAL_ARRIVES_AT_OAKS_REQUEST` | `15` | `15` | SAME | SAME: scripts/OaksLab.asm:23 (delivery[1]) |
| `SCRIPT.OAKSLAB.OAK_GIVES_POKEDEX` | `16` | `16` | SAME | SAME: scripts/OaksLab.asm:24 (delivery[2]; SetEvent EVENT_GOT_POKEDEX fires inside this script) |
| `SCRIPT.OAKSLAB.RIVAL_LEAVES_WITH_POKEDEX` | `17` | `17` | SAME | SAME: scripts/OaksLab.asm:25 (delivery[3]) |
| `SCRIPT.OAKSLAB.NOOP` | `18` | `18` | SAME | SAME: scripts/OaksLab.asm:26 "dw_const DoRet, SCRIPT_OAKSLAB_NOOP" |
| `SCRIPT.PALLETTOWN.DEFAULT` | `0` | `0` | SAME | SAME: scripts/PalletTown.asm:9-15 (driver reads 0-4) |
| `SCRIPT.PALLETTOWN.OAK_HEY_WAIT` | `1` | `1` | SAME | SAME: scripts/PalletTown.asm:9-15 (driver reads 0-4) |
| `SCRIPT.PALLETTOWN.OAK_WALKS_TO_PLAYER` | `2` | `2` | SAME | SAME: scripts/PalletTown.asm:9-15 (driver reads 0-4) |
| `SCRIPT.PALLETTOWN.OAK_NOT_SAFE_COME_WITH_ME` | `3` | `3` | SAME | SAME: scripts/PalletTown.asm:9-15 (driver reads 0-4) |
| `SCRIPT.PALLETTOWN.PLAYER_FOLLOWS_OAK` | `4` | `4` | SAME | SAME: scripts/PalletTown.asm:9-15 (driver reads 0-4) |
| `SCRIPT.PALLETTOWN.DAISY` | `5` | `5` | SAME | SAME: scripts/PalletTown.asm:9-15 (driver reads 0-4) |
| `SCRIPT.PALLETTOWN.NOOP` | `6` | `6` | SAME | SAME: scripts/PalletTown.asm:9-15 (driver reads 0-4) |
| `SCRIPT.VIRIDIANMART.DEFAULT` | `0` | `0` | SAME | SAME: scripts/ViridianMart.asm:6-10 (the parcel driver's `mart_script == 2` check) |
| `SCRIPT.VIRIDIANMART.OAKS_PARCEL` | `1` | `1` | SAME | SAME: scripts/ViridianMart.asm:6-10 (the parcel driver's `mart_script == 2` check) |
| `SCRIPT.VIRIDIANMART.NOOP` | `2` | `2` | SAME | SAME: scripts/ViridianMart.asm:6-10 (the parcel driver's `mart_script == 2` check) |
| `SCRIPT.LAB_DELIVERY.delivery` | `[15, 16, 17]` | `[15, 16, 17]` | SAME |  |
| `SCRIPT.LAB_DELIVERY.noop` | `18` | `18` | SAME |  |
| `MART.VIRIDIAN_STOCK` | `[4, 11, 15, 12]` | `[4, 11, 15, 12]` | SAME | SAME: data/items/marts/viridian.asm:2-7 "script_mart POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL" |
| `MART.VIRIDIAN_BALL_ROW` | `0` | `0` | SAME | SAME: data/items/marts/viridian.asm:4 (POKE_BALL is the first row; the parcel driver buys at menu_item 0) |
| `MART.LIST_SIGNATURE.list_menu_id` | `2` | `2` | UNVERIFIED | UNVERIFIED: see note above (no single source line states the Mart path's values) |
| `MART.LIST_SIGNATURE.text_box` | `14` | `14` | UNVERIFIED | UNVERIFIED: see note above |
| `MART.LIST_SIGNATURE.menu_y` | `1` | `1` | UNVERIFIED | UNVERIFIED: see note above |
| `MART.LIST_SIGNATURE.menu_x` | `1` | `1` | UNVERIFIED | UNVERIFIED: see note above |
| `MART.LIST_SIGNATURE.menu_max` | `2` | `2` | UNVERIFIED | UNVERIFIED: see note above |
| `STARTER_MOVES_LV5.BULBASAUR` | `['TACKLE', 'GROWL']` | `['TACKLE', 'GROWL']` | SAME | SAME: data/pokemon/base_stats/*.asm:13 + evos_moves.asm (no move changes before level 7) |
| `STARTER_MOVES_LV5.CHARMANDER` | `['SCRATCH', 'GROWL']` | `['SCRATCH', 'GROWL']` | SAME | SAME: data/pokemon/base_stats/*.asm:13 + evos_moves.asm (no move changes before level 7) |
| `STARTER_MOVES_LV5.SQUIRTLE` | `['TACKLE', 'TAIL_WHIP']` | `['TACKLE', 'TAIL_WHIP']` | SAME | SAME: data/pokemon/base_stats/*.asm:13 + evos_moves.asm (no move changes before level 7) |
| `MENU.START.menu_y` | `2` | `2` | SAME | SAME: engine/menus/draw_start_menu.asm:9-10 |
| `MENU.START.menu_x` | `11` | `11` | SAME | SAME: engine/menus/draw_start_menu.asm:9-10 |
| `MENU.START.save_index_without_pokedex` | `3` | `3` | SAME | SAME: engine/menus/draw_start_menu.asm:64-76 (SAVE is row 3 of 6 without the dex) |
| `MENU.START.save_index_with_pokedex` | `4` | `4` | SAME | SAME: engine/menus/draw_start_menu.asm:64-76 (the dex is a prepended row) |
| `MENU.START.max_minus_save` | `3` | `2` | DELTA | DELTA: engine/menus/draw_start_menu.asm:26-34 stores the LAST 0-based row index (5/6), not the row COUNT (6/7) — use menu_max == save_index + 2 |
| `MENU.SAVE_PROMPT.text_box` | `20` | `20` | SAME | SAME: engine/menus/save.asm:150-153,178 + home/yes_no.asm:6 |
| `MENU.SAVE_PROMPT.menu_y` | `8` | `8` | SAME | SAME: engine/menus/save.asm:150-153,178 + home/yes_no.asm:6 |
| `MENU.SAVE_PROMPT.menu_x` | `1` | `1` | SAME | SAME: engine/menus/save.asm:150-153,178 + home/yes_no.asm:6 |
| `MENU.SAVE_PROMPT.menu_max` | `1` | `1` | SAME | SAME: engine/menus/save.asm:150-153,178 + home/yes_no.asm:6 |
| `MENU.SAVE_PROMPT.yes_index` | `0` | `0` | SAME | SAME: engine/menus/save.asm:150-153,178 + home/yes_no.asm:6 |
| `MENU.BATTLE.menu_y` | `14` | `14` | SAME | SAME: engine/battle/core.asm:2298-2306 (left column) and the .rightColumn block |
| `MENU.BATTLE.left_x` | `9` | `9` | SAME | SAME: engine/battle/core.asm:2298-2306 (left column) and the .rightColumn block |
| `MENU.BATTLE.right_x` | `15` | `15` | SAME | SAME: engine/battle/core.asm:2298-2306 (left column) and the .rightColumn block |
| `MENU.BATTLE.menu_max` | `1` | `1` | SAME | SAME: engine/battle/core.asm:2298-2306 (left column) and the .rightColumn block |
| `MENU.BATTLE.left_watched` | `17` | `17` | SAME | PAD_RIGHT \| PAD_A |
| `MENU.BATTLE.right_watched` | `33` | `33` | SAME | PAD_LEFT \| PAD_A |
| `MENU.BATTLE.template` | `11` | `11` | SAME | constants/menu_constants.asm BATTLE_MENU_TEMPLATE $0b |
| `MENU.MOVE.menu_x` | `5` | `5` | SAME |  |
| `MENU.MOVE.menu_y` | `12` | `12` | SAME |  |
| `MENU.PARTY.menu_x` | `0` | `0` | SAME |  |
| `MENU.PARTY.menu_y` | `1` | `1` | SAME |  |
| `MENU.PARTY.watched` | `3` | `3` | SAME |  |
| `MENU.SWITCH_BOX.menu_max` | `2` | `2` | SAME |  |
| `MENU.SWITCH_BOX.menu_x` | `12` | `12` | SAME |  |
| `MENU.SWITCH_BOX.menu_y` | `12` | `12` | SAME |  |
| `MENU.SWITCH_BOX.watched` | `3` | `3` | SAME |  |
| `MENU.NAMING.menu_max` | `3` | `3` | SAME |  |
| `MENU.NAMING.menu_x` | `1` | `1` | SAME |  |
| `MENU.NAMING.menu_y` | `2` | `2` | SAME |  |
| `MENU.NAMING.watched` | `1` | `1` | SAME |  |
| `MENU.PC.menu_y` | `2` | `2` | SAME | SAME: engine/pokemon/bills_pc.asm:77-79 |
| `MENU.PC.menu_x` | `1` | `1` | SAME | SAME: engine/pokemon/bills_pc.asm:77-79 |
| `MENU.PC.main` | `42` | `42` | SAME | SAME: the PC MAIN menu's first row (SOMEONE's/BILL's PC) -- vanilla engine/pokemon/bills_pc.asm:33, pure :32 (DisplayPCMainMenu, hlcoord 2,2 = 42) |
| `MENU.PC.withdraw` | `42` | `42` | SAME | SAME: BILL's PC menu's first row -- vanilla engine/pokemon/bills_pc.asm:126 + BillsPCMenuText :341-347, pure :119 + :426-432 |
| `MENU.PC.deposit` | `82` | `82` | SAME | SAME: row 2 of BillsPCMenuText (vanilla :341-347, pure :426-432; `next` moves two tile rows) |
| `MENU.PC.release` | `122` | `122` | SAME | SAME: row 3 of BillsPCMenuText (same lines) |
| `MENU.PC.changebox` | `162` | `162` | SAME | SAME: row 4 of BillsPCMenuText (same lines) |
| `MENU.PC.seeya` | `202` | `202` | SAME | SAME: row 5 of BillsPCMenuText (same lines) |
| `MENU.PC.sub_action` | `251` | `251` | SAME | SAME: vanilla engine/pokemon/bills_pc.asm:393, pure :474 (hlcoord 11,12 = 251) |
| `MENU.PC.sub_cancel` | `331` | `331` | SAME | SAME: vanilla engine/pokemon/bills_pc.asm:395, pure :476-478 (hlcoord 11,14 / 11,16 = 291 / 331) |
| `MENU.PC.list` | `86` | `86` | SAME | SAME: vanilla home/list_menu.asm:364, pure :411 (hlcoord 6,4 = 86) |
| `MENU.PC.list_step` | `40` | `40` | SAME | SAME: list entries are two tile rows apart (same regions) |
| `MENU.PC.text1` | `281` | `281` | SAME | SAME: the message box's first line -- vanilla home/text.asm:242, pure :182 (hlcoord 1,14 = 281) + data/text_boxes.asm MESSAGE_BOX `0,12,19,17` (identical in both) |
| `MENU.PC.text2` | `321` | `321` | SAME | SAME: the box's second line, two rows below the first (same lines); pureRGB's live PC receipt read the release hint's first line at 281 |
| `MENU.PC.release_confirm.menu_y` | `8` | `8` | SAME | SAME: vanilla home/yes_no.asm:18 "lb bc, 8, 15"; pure engine/menus/multi_choice_menu.asm:73-74 |
| `MENU.PC.release_confirm.menu_x` | `15` | `14` | DELTA | vanilla home/yes_no.asm:18; pure multi_choice_menu.asm:75-76 (TwoOptionSmallMenu sits one column left) |
| `MENU.PC.release_confirm.yes` | `176` | `175` | DELTA | vanilla home/yes_no.asm:17 + engine/menus/text_box.asm:278-279 (strings one row below the corner); pure multi_choice_menu.asm:82 (hlcoord 15,8 = 175) |
| `MENU.PC.release_confirm.no` | `216` | `215` | DELTA | the second entry, two tile rows down (same lines as above) |
| `MENU.PC.release_confirm.menu_max` | `1` | `1` | SAME | SAME: vanilla engine/menus/text_box.asm:219-220; pure multi_choice_menu.asm:69-71 |
| `MENU.PC.release_confirm.confirm` | `A` | `A_THEN_START` | DELTA | vanilla engine/pokemon/bills_pc.asm:304-311 (OnceReleasedText -> YesNoChoice, A on YES releases); pure :372-383 -- A prints "Press START to / confirm release." (data/text/text_2.asm:1650-1652) and arms PAD_START, and START is what releases (:384-388) |
| `MENU.PC.changebox_prompt.menu_y` | `8` | `6` | DELTA | vanilla engine/menus/save.asm:361 (YesNoChoice); pure multi_choice_menu.asm:113 (ThreeOptionMenuSmall) |
| `MENU.PC.changebox_prompt.menu_x` | `15` | `12` | DELTA | vanilla engine/menus/save.asm:361; pure multi_choice_menu.asm:107-108 |
| `MENU.PC.changebox_prompt.menu_max` | `1` | `2` | DELTA | pure has THREE entries: multi_choice_menu.asm:104-106 "ld a, 2 / ld [wMaxMenuItem], a" |
| `MENU.PC.changebox_prompt.yes` | `176` | `133` | DELTA | pure multi_choice_menu.asm:118 (hlcoord 13,6 = 133) |
| `MENU.PC.changebox_prompt.no` | `216` | `173` | DELTA | the second entry, two tile rows down |
| `MENU.PC.changebox_prompt.hide` | `false` | `213` | DELTA | pure adds HIDE (multi_choice_menu.asm:118 + YesNoHide :285-289, passed at engine/menus/save.asm:355); HIDE sets EVENT_HIDE_CHANGE_BOX_SAVE_MSG (save.asm:375-376) |
| `MENU.PC.box_menu.menu_y` | `1` | `1` | SAME | SAME: vanilla engine/menus/save.asm:444-445; pure engine/menus/change_box_menu.asm:25-26 |
| `MENU.PC.box_menu.menu_x` | `12` | `7` | DELTA | vanilla engine/menus/save.asm:446-447; pure change_box_menu.asm:27-28 |
| `MENU.PC.box_menu.menu_max` | `11` | `11` | SAME | SAME: vanilla save.asm:442-443; pure change_box_menu.asm:23-24 |
| `MENU.PC.box_menu.name` | `33` | `28` | DELTA | vanilla save.asm:467 (hlcoord 13,1 = 33, BoxNames single-spaced); pure change_box_menu.asm:66 (hlcoord 8,1 = 28) |
| `MENU.PC.box_menu.name_step` | `20` | `20` | SAME | SAME: one box per tile row; vanilla 33 + 11*20 = 253, pure 28 + 11*20 = 248 |
| `MENU.PC.box_menu.count_col` | `false` | `13` | DELTA | pure change_box_menu.asm:96 (hlcoord 13,1 -- the column vanilla keeps the NAMES in, now the box counts). Not probed: an empty box leaves it blank |
| `BLACKOUT.default.map` | `0` | `0` | SAME | SAME: the new-game blackout point is Pallet Town -- scripts/RedsHouse1F.asm:3 `call SetOnlyLastBlackoutMap` with wLastMap = PALLET_TOWN (engine/overworld/special_warps.asm:28) |
| `BLACKOUT.default.x` | `5` | `5` | SAME | SAME: FlyWarpDataPtr `fly_warp PALLET_TOWN, 5, 6` (data/maps/special_warps.asm:97) |
| `BLACKOUT.default.y` | `6` | `6` | SAME | SAME: same line |
| `BLACKOUT.after_center.map` | `0` | `1` | DELTA | vanilla engine/events/pokecenter.asm:17 sets wLastBlackoutMap only when the nurse HEALS; pureRGB moved the call to Pokemon-Center ENTRY (scripts/ViridianPokecenter.asm:2 -> home/overworld.asm:2394/2401), so the lane's Center-PC visit leaves VIRIDIAN_CITY |
| `BLACKOUT.after_center.x` | `5` | `23` | DELTA | pure: FlyWarpDataPtr `fly_warp VIRIDIAN_CITY, 23, 26` (data/maps/special_warps.asm:98) |
| `BLACKOUT.after_center.y` | `6` | `26` | DELTA | same line |
| `POISON.psn_mask` | `8` | `8` | SAME | SAME: engine/events/poison.asm:16 "and 1 << PSN" + constants/battle_constants.asm:65 "const PSN ; 3" |
| `POISON.hp_per_tick` | `1` | `1` | SAME | SAME: engine/events/poison.asm:25 ("subtract 1 from HP") |
| `POISON.steps_per_tick` | `4` | `4` | SAME | SAME: engine/events/poison.asm:8-10 (wStepCounter & $3 -> damage every fourth step) |
| `POISON.status_bit_shift` | `3` | `3` | SAME | SAME: engine/events/poison.asm:16 (the driver's floor(status/8)%%2 test) |
| `CATCH.maxhp_factor` | `255` | `255` | SAME | SAME: engine/items/item_effects.asm:108 (ItemUseBall); W = floor(floor(maxhp*255/12) / max(floor(hp/4),1)) |
| `CATCH.maxhp_divisor` | `12` | `12` | SAME | SAME: engine/items/item_effects.asm:108 region |
| `CATCH.hp_divisor` | `4` | `4` | SAME | SAME: engine/items/item_effects.asm:108 region |
| `CATCH.sure_catch_w` | `255` | `255` | SAME | SAME: engine/items/item_effects.asm:108 region (W >= 255 is a certain catch) |
| `CATCH.first_rand_max` | `255` | `255` | SAME | SAME: engine/items/item_effects.asm:193-199 "; Poke Ball: [0, 255]" |
| `CATCH.great_rand_max` | `200` | `200` | SAME | SAME: engine/items/item_effects.asm:194 "; Great Ball/Safari: [0, 200]" |
| `CATCH.ultra_rand_max` | `150` | `150` | SAME | SAME: engine/items/item_effects.asm:195 "; Ultra Ball: [0, 150]" |
| `CATCH.hunt_ball_min` | `1` | `1` | SAME | SAME: engine/items/item_effects.asm:23-26 (MASTER/ULTRA/GREAT/POKE Ball all dispatch to ItemUseBall) |
| `CATCH.hunt_ball_max` | `4` | `5` | DELTA | DELTA: pureRGB adds HYPER_BALL $05 (engine/items/item_effects.asm:28); the vanilla scan stops at 4 — prefer ITEM.BALL_IDS |
| `BANKS.display_battle_menu` | `15` | `15` | SAME | data/pret/pokered.sym DisplayBattleMenu is bank $0F / data/purergb/pokered.sym DisplayBattleMenu is bank $0F |
| `BANKS.execute_enemy_move` | `15` | `15` | SAME | data/pret/pokered.sym ExecuteEnemyMove is bank $0F / data/purergb/pokered.sym ExecuteEnemyMove is bank $0F |
| `BANKS.execute_player_move` | `15` | `15` | SAME | data/pret/pokered.sym ExecutePlayerMove is bank $0F / data/purergb/pokered.sym ExecutePlayerMove is bank $0F |
| `BANKS.move_selection_menu` | `15` | `15` | SAME | data/pret/pokered.sym MoveSelectionMenu is bank $0F / data/purergb/pokered.sym MoveSelectionMenu is bank $0F |
| `BANKS.select_enemy_move` | `15` | `15` | SAME | data/pret/pokered.sym SelectEnemyMove is bank $0F / data/purergb/pokered.sym SelectEnemyMove is bank $0F |
| `BANKS.add_party_mon` | `0` | `0` | SAME | data/games/gen1_rby/engine_signals.json sites.add_party_mon.bank = 0 / data/games/gen1_purergb/engine_signals.json sites.add_party_mon.bank = 0 |
| `BANKS.apex_commit` | `false` | `3` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.apex_commit.bank = 3 |
| `BANKS.apex_preflight` | `false` | `3` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.apex_preflight.bank = 3 |
| `BANKS.apex_recalc_call` | `false` | `3` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.apex_recalc_call.bank = 3 |
| `BANKS.bag_received` | `3` | `3` | SAME | data/games/gen1_rby/engine_signals.json sites.bag_received.bank = 3 / data/games/gen1_purergb/engine_signals.json sites.bag_received.bank = 3 |
| `BANKS.battle_begin` | `15` | `15` | SAME | data/games/gen1_rby/engine_signals.json sites.battle_begin.bank = 15 / data/games/gen1_purergb/engine_signals.json sites.battle_begin.bank = 15 |
| `BANKS.battle_end` | `4` | `58` | DELTA | data/games/gen1_rby/engine_signals.json sites.battle_end.bank = 4 / data/games/gen1_purergb/engine_signals.json sites.battle_end.bank = 58 |
| `BANKS.battle_faint` | `15` | `15` | SAME | data/games/gen1_rby/engine_signals.json sites.battle_faint.bank = 15 / data/games/gen1_purergb/engine_signals.json sites.battle_faint.bank = 15 |
| `BANKS.battle_loop_head` | `15` | `15` | SAME | data/games/gen1_rby/engine_signals.json sites.battle_loop_head.bank = 15 / data/games/gen1_purergb/engine_signals.json sites.battle_loop_head.bank = 15 |
| `BANKS.blackout` | `1` | `1` | SAME | data/games/gen1_rby/engine_signals.json sites.blackout.bank = 1 / data/games/gen1_purergb/engine_signals.json sites.blackout.bank = 1 |
| `BANKS.cable_partial_save` | `false` | `1` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.cable_partial_save.bank = 1 |
| `BANKS.cable_trade_add` | `false` | `1` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.cable_trade_add.bank = 1 |
| `BANKS.cable_trade_remove` | `false` | `1` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.cable_trade_remove.bank = 1 |
| `BANKS.capture_box` | `3` | `3` | SAME | data/games/gen1_rby/engine_signals.json sites.capture_box.bank = 3 / data/games/gen1_purergb/engine_signals.json sites.capture_box.bank = 3 |
| `BANKS.capture_box_begin` | `false` | `3` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.capture_box_begin.bank = 3 |
| `BANKS.capture_box_end` | `false` | `3` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.capture_box_end.bank = 3 |
| `BANKS.capture_party_begin` | `false` | `3` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.capture_party_begin.bank = 3 |
| `BANKS.capture_party_end` | `false` | `3` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.capture_party_end.bank = 3 |
| `BANKS.changebox_full_save` | `false` | `28` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.changebox_full_save.bank = 28 |
| `BANKS.daycare_withdraw` | `false` | `21` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.daycare_withdraw.bank = 21 |
| `BANKS.evolve` | `14` | `44` | DELTA | data/games/gen1_rby/engine_signals.json sites.evolve.bank = 14 / data/games/gen1_purergb/engine_signals.json sites.evolve.bank = 44 |
| `BANKS.evolve_species_store` | `false` | `44` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.evolve_species_store.bank = 44 |
| `BANKS.move_mon` | `0` | `0` | SAME | data/games/gen1_rby/engine_signals.json sites.move_mon.bank = 0 / data/games/gen1_purergb/engine_signals.json sites.move_mon.bank = 0 |
| `BANKS.npc_trade` | `28` | `28` | SAME | data/games/gen1_rby/engine_signals.json sites.npc_trade.bank = 28 / data/games/gen1_purergb/engine_signals.json sites.npc_trade.bank = 28 |
| `BANKS.npc_trade_add` | `false` | `28` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.npc_trade_add.bank = 28 |
| `BANKS.npc_trade_done` | `false` | `28` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.npc_trade_done.bank = 28 |
| `BANKS.npc_trade_remove` | `false` | `28` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.npc_trade_remove.bank = 28 |
| `BANKS.pc_deposit` | `false` | `51` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.pc_deposit.bank = 51 |
| `BANKS.pc_release` | `false` | `51` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.pc_release.bank = 51 |
| `BANKS.pc_withdraw` | `false` | `51` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.pc_withdraw.bank = 51 |
| `BANKS.poison_faint` | `3` | `3` | SAME | data/games/gen1_rby/engine_signals.json sites.poison_faint.bank = 3 / data/games/gen1_purergb/engine_signals.json sites.poison_faint.bank = 3 |
| `BANKS.remove_pokemon` | `0` | `0` | SAME | data/games/gen1_rby/engine_signals.json sites.remove_pokemon.bank = 0 / data/games/gen1_purergb/engine_signals.json sites.remove_pokemon.bank = 0 |
| `BANKS.save_witness` | `28` | `28` | SAME | data/games/gen1_rby/engine_signals.json sites.save_witness.bank = 28 / data/games/gen1_purergb/engine_signals.json sites.save_witness.bank = 28 |
| `BANKS.starter_begin` | `7` | `7` | SAME | data/games/gen1_rby/engine_signals.json sites.starter_begin.bank = 7 / data/games/gen1_purergb/engine_signals.json sites.starter_begin.bank = 7 |
| `BANKS.starter_end` | `7` | `7` | SAME | data/games/gen1_rby/engine_signals.json sites.starter_end.bank = 7 / data/games/gen1_purergb/engine_signals.json sites.starter_end.bank = 7 |
| `BANKS.trainer_staging` | `false` | `15` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.trainer_staging.bank = 15 |
| `BANKS.transform` | `false` | `53` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.transform.bank = 53 |
| `BANKS.transform_hp_hi` | `false` | `53` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.transform_hp_hi.bank = 53 |
| `BANKS.transform_hp_lo` | `false` | `53` | DELTA | no such site on a vanilla cartridge (data/games/gen1_rby/engine_signals.json lists 17); data/games/gen1_purergb/engine_signals.json sites.transform_hp_lo.bank = 53 |
| `BANKS.wild_begin` | `15` | `15` | SAME | data/games/gen1_rby/engine_signals.json sites.wild_begin.bank = 15 / data/games/gen1_purergb/engine_signals.json sites.wild_begin.bank = 15 |
| `TUNING.input_cadence` | `16` | `16` | SAME | SAME: lua/tests/gen1_inputs_common.lua:42 |
| `TUNING.run_repress` | `120` | `120` | SAME | SAME: lua/tests/gen1_battle_driver.lua:58 |
| `TUNING.stall_bound` | `1800` | `1800` | SAME | SAME: lua/tests/gen1_rb_forest_inputs.lua:164 / gen1_rb_route22_inputs.lua:112 |
| `TUNING.stall_nudge` | `48` | `48` | SAME | SAME: lua/tests/gen1_rb_forest_inputs.lua:165 |
| `TUNING.detour_frames` | `32` | `32` | SAME | SAME: lua/tests/gen1_rb_forest_inputs.lua:166 |
| `TUNING.detour_bound` | `4` | `4` | SAME | SAME: lua/tests/gen1_rb_forest_inputs.lua:167 (added by 94f0058) |
| `TUNING.detour_backoffs` | `3` | `3` | SAME | SAME: lua/tests/gen1_rb_forest_inputs.lua:168 |
| `TUNING.battle_bound` | `60000` | `60000` | SAME | SAME: lua/tests/gen1_rb_route22_inputs.lua:117 |
| `TUNING.trigger_grace` | `600` | `600` | SAME | SAME: lua/tests/gen1_rb_route22_inputs.lua:118 |
| `TUNING.max_encounters_hunt` | `6` | `6` | SAME | SAME: lua/tests/gen1_rb_hunt_inputs.lua:25 |
| `TUNING.max_encounters_forest` | `60` | `60` | SAME | SAME: lua/tests/gen1_rb_forest_inputs.lua:161 |
| `TUNING.max_grass_steps` | `2000` | `2000` | SAME | SAME: lua/tests/gen1_rb_forest_inputs.lua:162 |
| `TUNING.max_growl_turns` | `20` | `20` | SAME | SAME: lua/tests/gen1_rb_forest_inputs.lua:163 |
| `TUNING.wild_run_attempt_bound` | `8` | `8` | SAME | SAME: lua/tests/gen1_rb_route1_inputs.lua:39 |
| `CLIENT.speedmode` | `6399` | `6399` | SAME | SAME: lua/tests/gen1_gate.lua:55 (BizHawk-level, not a ROM fact) |
| `CLIENT.tick_frames` | `30` | `30` | SAME | SAME: lua/gen1/client.lua:18 (TICK_INTERVAL) |
| `WAYPOINTS.PARCEL.lab_exit` | `[[5, 11]]` | `[[5, 11]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_parcel_inputs.lua:27-34; PLAN §11.2 Live 3 walked this route |
| `WAYPOINTS.PARCEL.pallet_north` | `[[12, 11], [9, 11], [9, 2], [10, 2], [10, -1]]` | `[[12, 11], [9, 11], [9, 2], [10, 2], [10, -1]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_parcel_inputs.lua:27-34; PLAN §11.2 Live 3 walked this route |
| `WAYPOINTS.PARCEL.route_north` | `[[10, 31], [8, 31], [8, 24], [12, 24], [12, 22], [9, 22], [9, 14], [14, 14], [14, 4], [11, 4], [11, -1]]` | `[[10, 31], [8, 31], [8, 24], [12, 24], [12, 22], [9, 22], [9, 14], [14, 14], [14, 4], [11, 4], [11, -1]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_parcel_inputs.lua:27-34; PLAN §11.2 Live 3 walked this route |
| `WAYPOINTS.PARCEL.viridian_mart` | `[[20, 35], [20, 30], [19, 30], [19, 20], [29, 20], [29, 19]]` | `[[20, 35], [20, 30], [19, 30], [19, 20], [29, 20], [29, 19]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_parcel_inputs.lua:27-34; PLAN §11.2 Live 3 walked this route |
| `WAYPOINTS.PARCEL.viridian_south` | `[[29, 20], [19, 20], [19, 30], [20, 30], [20, 36]]` | `[[29, 20], [19, 20], [19, 30], [20, 30], [20, 36]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_parcel_inputs.lua:27-34; PLAN §11.2 Live 3 walked this route |
| `WAYPOINTS.PARCEL.route_south` | `[[10, 4], [14, 4], [14, 14], [9, 14], [9, 22], [12, 22], [12, 24], [8, 24], [8, 31], [10, 31], [10, 36]]` | `[[10, 4], [14, 4], [14, 14], [9, 14], [9, 22], [12, 22], [12, 24], [8, 24], [8, 31], [10, 31], [10, 36]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_parcel_inputs.lua:27-34; PLAN §11.2 Live 3 walked this route |
| `WAYPOINTS.PARCEL.pallet_lab` | `[[10, 2], [9, 2], [9, 12], [12, 12], [12, 11]]` | `[[10, 2], [9, 2], [9, 12], [12, 12], [12, 11]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_parcel_inputs.lua:27-34; PLAN §11.2 Live 3 walked this route |
| `WAYPOINTS.PARCEL.lab_oak` | `[[5, 11], [5, 3]]` | `[[5, 11], [5, 3]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_parcel_inputs.lua:27-34; PLAN §11.2 Live 3 walked this route |
| `WAYPOINTS.PARCEL.park` | `[10, 35]` | `[10, 35]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_parcel_inputs.lua:27-34; PLAN §11.2 Live 3 walked this route |
| `WAYPOINTS.ROUTE1.mart_exit` | `[[3, 7]]` | `[[3, 7]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_route1_inputs.lua:13-18 |
| `WAYPOINTS.ROUTE1.viridian_south` | `[[29, 20], [19, 20], [19, 30], [20, 30], [20, 36]]` | `[[29, 20], [19, 20], [19, 30], [20, 30], [20, 36]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_route1_inputs.lua:13-18 |
| `WAYPOINTS.ROUTE1.route_south` | `[[10, 4], [14, 4], [14, 14], [9, 14], [9, 22], [12, 22], [12, 24], [8, 24], [8, 31], [10, 31], [10, 35]]` | `[[10, 4], [14, 4], [14, 14], [9, 14], [9, 22], [12, 22], [12, 24], [8, 24], [8, 31], [10, 31], [10, 35]]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_route1_inputs.lua:13-18 |
| `WAYPOINTS.ROUTE1.park` | `[10, 35]` | `[10, 35]` | SAME | SAME (live-proven on pureRGB): lua/tests/gen1_rb_route1_inputs.lua:13-18 |
| `WAYPOINTS.HUNT.park` | `[10, 35]` | `[10, 35]` | UNVERIFIED | UNVERIFIED: tile coordinates, vanilla-only so far |
| `WAYPOINTS.HUNT.grass` | `[[10, 33], [10, 35]]` | `[[10, 33], [10, 35]]` | UNVERIFIED | UNVERIFIED: tile coordinates, vanilla-only so far |
| `WAYPOINTS.CENTER.lab_exit.map` | `40` | `40` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.lab_exit.next` | `0` | `0` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.lab_exit.waypoints` | `[[5, 11]]` | `[[5, 11]]` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.pallet_north.map` | `0` | `0` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.pallet_north.next` | `12` | `12` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.pallet_north.waypoints` | `[[12, 11], [9, 11], [9, 2], [10, 2], [10, -1]]` | `[[12, 11], [9, 11], [9, 2], [10, 2], [10, -1]]` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.route_one_north.map` | `12` | `12` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.route_one_north.next` | `1` | `1` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.route_one_north.waypoints` | `[[10, 31], [8, 31], [8, 24], [12, 24], [12, 22], [9, 22], [9, 14], [14, 14], [14, 4], [11, 4], [11, -1]]` | `[[10, 31], [8, 31], [8, 24], [12, 24], [12, 22], [9, 22], [9, 14], [14, 14], [14, 4], [11, 4], [11, -1]]` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.viridian_center.map` | `1` | `1` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.viridian_center.next` | `41` | `41` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.viridian_center.waypoints` | `[[20, 30], [19, 30], [19, 26], [23, 26], [23, 25]]` | `[[20, 30], [19, 30], [19, 26], [23, 26], [23, 25]]` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.center_recept.map` | `41` | `41` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.CENTER.center_recept.waypoints` | `[[3, 4], [11, 4], [11, 3]]` | `[[3, 4], [11, 4], [11, 3]]` | UNVERIFIED | UNVERIFIED: vanilla-only so far; lua/tests/gen1_rb_center_inputs.lua:6-17 |
| `WAYPOINTS.FOREST.park` | `[18, 41]` | `[18, 41]` | UNVERIFIED | UNVERIFIED: tile coordinates, vanilla-only so far |
| `WAYPOINTS.FOREST.pace` | `[[18, 41], [18, 40]]` | `[[18, 41], [18, 40]]` | UNVERIFIED | UNVERIFIED: tile coordinates, vanilla-only so far |
| `WAYPOINTS.FOREST.shuttle` | `[[18, 43], [18, 44]]` | `[[18, 43], [18, 44]]` | UNVERIFIED | UNVERIFIED: tile coordinates, vanilla-only so far |
| `WAYPOINTS.ROUTE22.trigger` | `[[29, 5], [29, 4]]` | `[[29, 5], [29, 4]]` | UNVERIFIED | UNVERIFIED: tile coordinates, vanilla-only so far |

## What differs, and why

The scalar facts, each at its definition and at its consumers:

1. **`TRAINER.OPP_RIVAL1` (+ `OPP_ID_OFFSET`)** — `wCurOpponent` is `OPP_ID_OFFSET + class`: 200 +
   `RIVAL1` `$19` = **225** on vanilla, 197 + `RIVAL1` `$18` = **221** on pureRGB
   (`docs/purergb/PLAN.md` A12; `data/games/gen1_purergb/trainers.json` `rival_ids`). The lab and
   Route 22 drivers assert this id, so a vanilla literal there refuses the pure lane's first battle.
2. **`EVENT.OAK_GOT_PARCEL`** — vanilla bit 56 (`constants/event_constants.asm:29`), and the flag
   the parcel gate polls. pureRGB deleted the event (`:50` is a bare `const_skip`), so bit 56 reads
   0 forever and the Mart never opens; the lane reads `EVENT_GOT_POKEDEX` (37) instead.
3. **`MENU.START.max_minus_save`** — pureRGB stores the last 0-based row INDEX (5/6), not the row
   COUNT (6/7, `engine/menus/draw_start_menu.asm:26-34`), so the SAVE-row arithmetic is
   `save_index + 2` there and `+ 3` on vanilla (the companion SLINK row adds 1 either way).
4. **`ITEM.BALL_IDS` / `CATCH.hunt_ball_max`** — pureRGB adds `HYPER_BALL` `$05`
   (`constants/item_constants.asm:14`, replacing TOWN MAP) with its own `ItemUseBall` dispatch, so
   the vanilla scan `{1,2,3,4}` misses a ball the player can throw: `{1,2,3,4,5,8}`.
5. **`MENU.PC.{release_confirm,changebox_prompt,box_menu}`** — pureRGB routes the RELEASE
   confirmation and the CHANGE BOX prompt through `DisplayMultiChoiceMenu`
   (`engine/menus/multi_choice_menu.asm:8`) instead of `YesNoChoice`: the small variants sit one
   column left (`wTopMenuItemX` 15 → 14, YES 176 → 175), CHANGE BOX gains a third HIDE entry
   (`:285-289` + `ThreeOptionMenuSmall` `:112-119`) that sets `EVENT_HIDE_CHANGE_BOX_SAVE_MSG`
   (`engine/menus/save.asm:375-376`) and silences the prompt for the rest of the save, and RELEASE
   needs A (the "Press START to / confirm release." hint, `engine/pokemon/bills_pc.asm:378-383`)
   before START releases. Its box list moved the NAMES off column 13 (`wTopMenuItemX` 12 → 7, names
   at `hlcoord 8,1` = 28) and gave column 13 to the box counts. `MENU.PC.yes` / `.no` / `.box` /
   `.box_last` are superseded by these three groups (the old `.box`/`.box_last` cited pureRGB's
   count column as if it were the names).

And the `BANKS` group, which is not a scalar fact but a per-foundation SITE INVENTORY:

- pureRGB moved `EndOfBattle` (`$04` → `$3A`) and `TryEvolvingMon` (`$0E` → `$2C`);
- 23 of its 40 hooks (`apex_*`, `cable_*`, `pc_*`, `npc_trade_add/done/remove`, `capture_*_begin/end`,
  `transform*`, `daycare_withdraw`, `changebox_full_save`, `trainer_staging`) have no vanilla site
  at all — the twin carries `false` for those, and a driver reading one finds the battle-core bank;
- the five battle-menu hooks the live battle driver filters on are bank `$0F` in BOTH `.sym` sets.

## The 25 UNVERIFIED facts

- **`MART.LIST_SIGNATURE.*`** (5) — a runtime list-menu signature the mart driver matches; the
  generic list menu sets these from its own state (`home/list_menu.asm:44-53`) and the Mart path was
  not traced. The purchase ran live on pureRGB (PLAN §11.2 Live 3).
- **`WAYPOINTS.{CENTER,FOREST,ROUTE22,HUNT}`** (20) — tile coordinates: map layout, not ROM
  constants. `WAYPOINTS.PARCEL` and `WAYPOINTS.ROUTE1` are SAME because the live pureRGB run walked
  those tiles; these four groups have only been walked on vanilla R/B.

(`MENU.PC.text1` / `MENU.PC.text2` left this list: the message box's two text lines are
`hlcoord 1,14` / two rows down in both foundations -- vanilla `home/text.asm:242`, pureRGB
`home/text.asm:182`, over an identical `MESSAGE_BOX 0,12,19,17` -- and the pure lane's own PC
receipt read the release hint's first line at 281.)

## Two citation traps when porting the drivers

- The driver's naming-screen predicate (`wMaxMenuItem==3`, `wTopMenuItemY==2`, `wTopMenuItemX==1`)
  is `DisplayIntroNameTextBox` (`engine/movie/oak_speech/oak_speech2.asm:172-182`) and is SAME; the
  comment that named `engine/menus/naming_screen.asm` pointed at the alphabet grid (Y3/X1/max7).
- Two pureRGB line-number shifts: the PC mon-list position is `home/list_menu.asm:411` (the vanilla
  driver cites `:364-365`), and the Mart stock is `data/items/marts/viridian.asm:2-7` with POKE_BALL
  at `:4` (the vanilla citation says 1-5 / 2).
