# pureRGB driver-facts derivation (P3b-e)

Companion to `lua/tests/gen1_pure_facts.lua`: every fact that file carries, with its vanilla value,
its pureRGB value, a status and the citation behind the status.

- **SAME** — pureRGB equals the vanilla literal the R/B driver embeds, verified against the pureRGB
  source at commit `7e7a4653` or a generated pack file under `data/games/gen1_purergb/`.
- **DELTA** — pureRGB differs; the pureRGB column is what a pureRGB lane must use.
- **UNVERIFIED** — no source line could be opened this pass; the reason is on the row.

Sources opened: the pinned pureRGB checkout (`…/scratchpad/purergb`, the plan's `P:` tree),
`data/games/gen1_purergb/{species_index,items,engine_signals}.json`, and the vanilla drivers' literals
via `docs/purergb/research/p3/harness_literals_bbcd037.md` table 2.

Counts: **223 facts** — SAME 192, DELTA 6, UNVERIFIED 25.

## Table

| key | vanilla | pureRGB | status | citation |
|---|---|---|---|---|
| `CLIENT.speedmode` | `6399` | `6399` | SAME | lua/tests/gen1_gate.lua:55 (BizHawk-level, not a ROM fact) |
| `CLIENT.tick_frames` | `30` | `30` | SAME | lua/gen1/client.lua:18 (TICK_INTERVAL) |
| `EVENT.GOT_POKEDEX` | `37` | `37` | SAME | constants/event_constants.asm:37 "const EVENT_GOT_POKEDEX" |
| `EVENT.OAK_GOT_PARCEL_SUBSTITUTE` | `(none — read bit 56 directly)` | `"GOT_POKEDEX"` | DELTA | constants/event_constants.asm:37 |
| `EVENT.GOT_OAKS_PARCEL` | `57` | `57` | SAME | constants/event_constants.asm:51 "const EVENT_GOT_OAKS_PARCEL" |
| `EVENT.OAK_GOT_PARCEL` | `56` | `37` | DELTA | bit 56 no longer exists (constants/event_constants.asm:50 "used to be EVENT_OAK_GOT_PARCEL but it's no different from EVENT_GOT_POKEDEX") — read GOT_POKEDEX instead |
| `EVENT.OAK_GOT_PARCEL_EXISTS` | `true` | `false` | DELTA | constants/event_constants.asm:50 (bare const_skip) |
| `CATCH.maxhp_factor` | `255` | `255` | SAME | engine/items/item_effects.asm:108 (ItemUseBall); W = floor(floor(maxhp*255/12) / max(floor(hp/4),1)) |
| `CATCH.first_rand_max` | `255` | `255` | SAME | engine/items/item_effects.asm:193-199 "; Poke Ball: [0, 255]" |
| `CATCH.hunt_ball_max` | `4` | `5` | DELTA | pureRGB adds HYPER_BALL $05 (engine/items/item_effects.asm:28); the vanilla scan stops at 4 — prefer ITEM.BALL_IDS |
| `CATCH.hp_divisor` | `4` | `4` | SAME | engine/items/item_effects.asm:108 region |
| `CATCH.maxhp_divisor` | `12` | `12` | SAME | engine/items/item_effects.asm:108 region |
| `CATCH.ultra_rand_max` | `150` | `150` | SAME | engine/items/item_effects.asm:195 "; Ultra Ball: [0, 150]" |
| `CATCH.great_rand_max` | `200` | `200` | SAME | engine/items/item_effects.asm:194 "; Great Ball/Safari: [0, 200]" |
| `CATCH.hunt_ball_min` | `1` | `1` | SAME | engine/items/item_effects.asm:23-26 (MASTER/ULTRA/GREAT/POKE Ball all dispatch to ItemUseBall) |
| `CATCH.sure_catch_w` | `255` | `255` | SAME | engine/items/item_effects.asm:108 region (W >= 255 is a certain catch) |
| `ITEM.PARLYZ_HEAL` | `15` | `15` | SAME | constants/item_constants.asm:24 |
| `ITEM.OAKS_PARCEL` | `70` | `70` | SAME | constants/item_constants.asm:79 |
| `ITEM.BALL_IDS` | `{1, 2, 3, 4}` | `{1, 2, 3, 4, 5, 8}` | DELTA | data/games/gen1_purergb/items.json ball_items == the ItemUseBall dispatch set at engine/items/item_effects.asm:23-30 (vanilla 1..4 misses HYPER_BALL $05) |
| `ITEM.ANTIDOTE` | `11` | `11` | SAME | constants/item_constants.asm:20 |
| `ITEM.BURN_HEAL` | `12` | `12` | SAME | constants/item_constants.asm:21 |
| `ITEM.POKE_BALL` | `4` | `4` | SAME | constants/item_constants.asm:13 "const POKE_BALL ; $04" (the parcel driver's purchase check) |
| `MART.VIRIDIAN_BALL_ROW` | `0` | `0` | SAME | data/items/marts/viridian.asm:4 (POKE_BALL is the first row; the parcel driver buys at menu_item 0) |
| `MART.VIRIDIAN_STOCK` | `{4, 11, 15, 12}` | `{4, 11, 15, 12}` | SAME | data/items/marts/viridian.asm:2-7 "script_mart POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL" |
| `MART.LIST_SIGNATURE.menu_y` | `1` | `1` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MART.LIST_SIGNATURE.menu_max` | `2` | `2` | UNVERIFIED | see note above |
| `MART.LIST_SIGNATURE.menu_x` | `1` | `1` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MART.LIST_SIGNATURE.text_box` | `14` | `14` | UNVERIFIED | see note above |
| `MART.LIST_SIGNATURE.list_menu_id` | `2` | `2` | UNVERIFIED | see note above (no single source line states the Mart path's values) |
| `SPECIES.SQUIRTLE` | `177` | `177` | SAME | species_index.json (internal 177 = 0xB1) |
| `SPECIES.BULBASAUR` | `153` | `153` | SAME | data/games/gen1_purergb/species_index.json (internal 153) |
| `SPECIES.CHARMANDER` | `176` | `176` | SAME | species_index.json (internal 176 = 0xB0) |
| `SPECIES.MISSINGNO` | `181` | `181` | SAME | species_index.json (internal 181 = 0xB5, dex 0, classification "missingno") |
| `SPECIES.WEEDLE` | `112` | `112` | SAME | species_index.json (internal 112 = 0x70); the forest poison hunt target |
| `STARTER_MOVES_LV5.CHARMANDER` | `{"SCRATCH", "GROWL"}` | `{"SCRATCH", "GROWL"}` | SAME | species_index.json (internal 176 = 0xB0) |
| `STARTER_MOVES_LV5.SQUIRTLE` | `{"TACKLE", "TAIL_WHIP"}` | `{"TACKLE", "TAIL_WHIP"}` | SAME | species_index.json (internal 177 = 0xB1) |
| `STARTER_MOVES_LV5.BULBASAUR` | `{"TACKLE", "GROWL"}` | `{"TACKLE", "GROWL"}` | SAME | data/games/gen1_purergb/species_index.json (internal 153) |
| `WAYPOINTS.PARCEL.lab_exit` | `{{5, 11}}` | `{{5, 11}}` | SAME | tile coordinates, vanilla-only so far |
| `WAYPOINTS.PARCEL.pallet_lab` | `{{10, 2}, {9, 2}, {9, 12}, {12, 12}, {12, 11}}` | `{{10, 2}, {9, 2}, {9, 12}, {12, 12}, {12, 11}}` | SAME |  |
| `WAYPOINTS.PARCEL.park` | `{10, 35}` | `{10, 35}` | SAME | tile coordinates, vanilla-only so far |
| `WAYPOINTS.PARCEL.route_north` | `{{10, 31}, {8, 31}, {8, 24}, {12, 24}, {12, 22}, {9, 22}, {9, 14}, {14, 14}, {14, 4}, {11, 4}, {11, -1}}` | `{{10, 31}, {8, 31}, {8, 24}, {12, 24}, {12, 22}, {9, 22}, {9, 14}, {14, 14}, {14, 4}, {11, 4}, {11, -1}}` | SAME |  |
| `WAYPOINTS.PARCEL.viridian_mart` | `{{20, 35}, {20, 30}, {19, 30}, {19, 20}, {29, 20}, {29, 19}}` | `{{20, 35}, {20, 30}, {19, 30}, {19, 20}, {29, 20}, {29, 19}}` | SAME |  |
| `WAYPOINTS.PARCEL.route_south` | `{{10, 4}, {14, 4}, {14, 14}, {9, 14}, {9, 22}, {12, 22}, {12, 24}, {8, 24}, {8, 31}, {10, 31}, {10, 36}}` | `{{10, 4}, {14, 4}, {14, 14}, {9, 14}, {9, 22}, {12, 22}, {12, 24}, {8, 24}, {8, 31}, {10, 31}, {10, 36}}` | SAME |  |
| `WAYPOINTS.PARCEL.lab_oak` | `{{5, 11}, {5, 3}}` | `{{5, 11}, {5, 3}}` | SAME |  |
| `WAYPOINTS.PARCEL.pallet_north` | `{{12, 11}, {9, 11}, {9, 2}, {10, 2}, {10, -1}}` | `{{12, 11}, {9, 11}, {9, 2}, {10, 2}, {10, -1}}` | SAME | tile coordinates, vanilla-only so far |
| `WAYPOINTS.PARCEL.viridian_south` | `{{29, 20}, {19, 20}, {19, 30}, {20, 30}, {20, 36}}` | `{{29, 20}, {19, 20}, {19, 30}, {20, 30}, {20, 36}}` | SAME |  |
| `WAYPOINTS.ROUTE22.trigger` | `{{29, 5}, {29, 4}}` | `{{29, 5}, {29, 4}}` | UNVERIFIED | tile coordinates, vanilla-only so far |
| `WAYPOINTS.FOREST.park` | `{18, 41}` | `{18, 41}` | UNVERIFIED | tile coordinates, vanilla-only so far |
| `WAYPOINTS.FOREST.shuttle` | `{{18, 43}, {18, 44}}` | `{{18, 43}, {18, 44}}` | UNVERIFIED | tile coordinates, vanilla-only so far |
| `WAYPOINTS.FOREST.pace` | `{{18, 41}, {18, 40}}` | `{{18, 41}, {18, 40}}` | UNVERIFIED | tile coordinates, vanilla-only so far |
| `WAYPOINTS.CENTER.lab_exit.waypoints` | `{{5, 11}}` | `{{5, 11}}` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.lab_exit.next` | `0` | `0` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.lab_exit.map` | `40` | `40` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.route_one_north.waypoints` | `{{10, 31}, {8, 31}, {8, 24}, {12, 24}, {12, 22}, {9, 22}, {9, 14}, {14, 14}, {14, 4}, {11, 4}, {11, -1}}` | `{{10, 31}, {8, 31}, {8, 24}, {12, 24}, {12, 22}, {9, 22}, {9, 14}, {14, 14}, {14, 4}, {11, 4}, {11, -1}}` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.route_one_north.next` | `1` | `1` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.route_one_north.map` | `12` | `12` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.center_recept.waypoints` | `{{3, 4}, {11, 4}, {11, 3}}` | `{{3, 4}, {11, 4}, {11, 3}}` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.center_recept.map` | `41` | `41` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.pallet_north.waypoints` | `{{12, 11}, {9, 11}, {9, 2}, {10, 2}, {10, -1}}` | `{{12, 11}, {9, 11}, {9, 2}, {10, 2}, {10, -1}}` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.pallet_north.next` | `12` | `12` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.pallet_north.map` | `0` | `0` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.viridian_center.waypoints` | `{{20, 30}, {19, 30}, {19, 26}, {23, 26}, {23, 25}}` | `{{20, 30}, {19, 30}, {19, 26}, {23, 26}, {23, 25}}` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.viridian_center.next` | `41` | `41` | UNVERIFIED |  |
| `WAYPOINTS.CENTER.viridian_center.map` | `1` | `1` | UNVERIFIED |  |
| `WAYPOINTS.ROUTE1.park` | `{10, 35}` | `{10, 35}` | SAME | tile coordinates, vanilla-only so far |
| `WAYPOINTS.ROUTE1.route_south` | `{{10, 4}, {14, 4}, {14, 14}, {9, 14}, {9, 22}, {12, 22}, {12, 24}, {8, 24}, {8, 31}, {10, 31}, {10, 35}}` | `{{10, 4}, {14, 4}, {14, 14}, {9, 14}, {9, 22}, {12, 22}, {12, 24}, {8, 24}, {8, 31}, {10, 31}, {10, 35}}` | SAME |  |
| `WAYPOINTS.ROUTE1.viridian_south` | `{{29, 20}, {19, 20}, {19, 30}, {20, 30}, {20, 36}}` | `{{29, 20}, {19, 20}, {19, 30}, {20, 30}, {20, 36}}` | SAME |  |
| `WAYPOINTS.ROUTE1.mart_exit` | `{{3, 7}}` | `{{3, 7}}` | SAME |  |
| `WAYPOINTS.HUNT.grass` | `{{10, 33}, {10, 35}}` | `{{10, 33}, {10, 35}}` | UNVERIFIED | tile coordinates, vanilla-only so far |
| `WAYPOINTS.HUNT.park` | `{10, 35}` | `{10, 35}` | UNVERIFIED | tile coordinates, vanilla-only so far |
| `MAP.ROUTE_2` | `13` | `13` | SAME | constants/map_constants.asm:34 "map_const ROUTE_2, 10, 36 ; $0D" (D2 left this UNVERIFIED) |
| `MAP.ROUTE_22` | `33` | `33` | SAME | constants/map_constants.asm:54 "; $21" |
| `MAP.CINNABAR_ISLAND` | `9` | `9` | SAME | constants/map_constants.asm:28 "; $09" (Sea Routes table) |
| `MAP.VIRIDIAN_FOREST` | `51` | `51` | SAME | constants/map_constants.asm:73 "map_const VIRIDIAN_FOREST, 17, 24 ; $33" |
| `MAP.REDS_HOUSE_1F` | `37` | `37` | SAME | constants/map_constants.asm:59 "map_const REDS_HOUSE_1F, 4, 4 ; $25" |
| `MAP.ROUTE_20` | `31` | `31` | SAME | constants/map_constants.asm:52 "; $1F" (Sea Routes table) |
| `MAP.VIRIDIAN_MART` | `42` | `42` | SAME | constants/map_constants.asm:64 "; $2A" |
| `MAP.VIRIDIAN_POKECENTER` | `41` | `41` | SAME | constants/map_constants.asm:63 "; $29" |
| `MAP.ROUTE_1` | `12` | `12` | SAME | constants/map_constants.asm:33 "map_const ROUTE_1, 10, 18 ; $0C" (D2 left this UNVERIFIED) |
| `MAP.PALLET_TOWN` | `0` | `0` | SAME | constants/map_constants.asm:19 "map_const PALLET_TOWN, 10, 9 ; $00" |
| `MAP.VIRIDIAN_CITY` | `1` | `1` | SAME | constants/map_constants.asm:20 "; $01" |
| `MAP.VIRIDIAN_FOREST_SOUTH_GATE` | `50` | `50` | SAME | constants/map_constants.asm:72 "; $32" |
| `MAP.REDS_HOUSE_2F` | `38` | `38` | SAME | constants/map_constants.asm:60 "map_const REDS_HOUSE_2F, 4, 4 ; $26" (boot/park map) |
| `MAP.OAKS_LAB` | `40` | `40` | SAME | constants/map_constants.asm:62 "; $28" |
| `TUNING.input_cadence` | `16` | `16` | SAME | lua/tests/gen1_inputs_common.lua:42 |
| `TUNING.stall_bound` | `1800` | `1800` | SAME | lua/tests/gen1_rb_forest_inputs.lua:164 / gen1_rb_route22_inputs.lua:112 |
| `TUNING.trigger_grace` | `600` | `600` | SAME | lua/tests/gen1_rb_route22_inputs.lua:118 |
| `TUNING.max_encounters_hunt` | `6` | `6` | SAME | lua/tests/gen1_rb_hunt_inputs.lua:25 |
| `TUNING.wild_run_attempt_bound` | `8` | `8` | SAME | lua/tests/gen1_rb_route1_inputs.lua:39 |
| `TUNING.battle_bound` | `60000` | `60000` | SAME | lua/tests/gen1_rb_route22_inputs.lua:117 |
| `TUNING.max_grass_steps` | `2000` | `2000` | SAME | lua/tests/gen1_rb_forest_inputs.lua:162 |
| `TUNING.max_encounters_forest` | `60` | `60` | SAME | lua/tests/gen1_rb_forest_inputs.lua:161 |
| `TUNING.detour_backoffs` | `3` | `3` | SAME | lua/tests/gen1_rb_forest_inputs.lua:168 |
| `TUNING.detour_bound` | `4` | `4` | SAME | lua/tests/gen1_rb_forest_inputs.lua:167 (added by 94f0058) |
| `TUNING.max_growl_turns` | `20` | `20` | SAME | lua/tests/gen1_rb_forest_inputs.lua:163 |
| `TUNING.detour_frames` | `32` | `32` | SAME | lua/tests/gen1_rb_forest_inputs.lua:166 |
| `TUNING.stall_nudge` | `48` | `48` | SAME | lua/tests/gen1_rb_forest_inputs.lua:165 |
| `TUNING.run_repress` | `120` | `120` | SAME | lua/tests/gen1_battle_driver.lua:58 |
| `SCRIPT.OAKSLAB.OAK_GIVES_POKEDEX` | `16` | `16` | SAME | scripts/OaksLab.asm:24 (delivery[2]; SetEvent EVENT_GOT_POKEDEX fires inside this script) |
| `SCRIPT.OAKSLAB.CHOSE_STARTER` | `8` | `8` | SAME |  |
| `SCRIPT.OAKSLAB.RIVAL_CHALLENGES_PLAYER` | `10` | `10` | SAME |  |
| `SCRIPT.OAKSLAB.PLAYER_DONT_GO_AWAY` | `6` | `6` | SAME |  |
| `SCRIPT.OAKSLAB.RIVAL_CHOOSES_STARTER` | `9` | `9` | SAME |  |
| `SCRIPT.OAKSLAB.RIVAL_END_BATTLE` | `12` | `12` | SAME |  |
| `SCRIPT.OAKSLAB.TOGGLE_OAKS` | `2` | `2` | SAME |  |
| `SCRIPT.OAKSLAB.RIVAL_ARRIVES_AT_OAKS_REQUEST` | `15` | `15` | SAME | scripts/OaksLab.asm:23 (delivery[1]) |
| `SCRIPT.OAKSLAB.PLAYER_WATCH_RIVAL_EXIT` | `14` | `14` | SAME |  |
| `SCRIPT.OAKSLAB.PLAYER_ENTERS_LAB` | `3` | `3` | SAME |  |
| `SCRIPT.OAKSLAB.DEFAULT` | `0` | `0` | SAME |  |
| `SCRIPT.OAKSLAB.OAK_ENTERS_LAB` | `1` | `1` | SAME |  |
| `SCRIPT.OAKSLAB.PLAYER_FORCED_TO_WALK_BACK` | `7` | `7` | SAME |  |
| `SCRIPT.OAKSLAB.FOLLOWED_OAK` | `4` | `4` | SAME |  |
| `SCRIPT.OAKSLAB.NOOP` | `18` | `18` | SAME | scripts/OaksLab.asm:26 "dw_const DoRet, SCRIPT_OAKSLAB_NOOP" |
| `SCRIPT.OAKSLAB.OAK_CHOOSE_MON_SPEECH` | `5` | `5` | SAME |  |
| `SCRIPT.OAKSLAB.RIVAL_STARTS_EXIT` | `13` | `13` | SAME |  |
| `SCRIPT.OAKSLAB.RIVAL_START_BATTLE` | `11` | `11` | SAME |  |
| `SCRIPT.OAKSLAB.RIVAL_LEAVES_WITH_POKEDEX` | `17` | `17` | SAME | scripts/OaksLab.asm:25 (delivery[3]) |
| `SCRIPT.LAB_DELIVERY.delivery` | `{15, 16, 17}` | `{15, 16, 17}` | SAME |  |
| `SCRIPT.LAB_DELIVERY.noop` | `18` | `18` | SAME |  |
| `SCRIPT.PALLETTOWN.OAK_HEY_WAIT` | `1` | `1` | SAME |  |
| `SCRIPT.PALLETTOWN.OAK_WALKS_TO_PLAYER` | `2` | `2` | SAME |  |
| `SCRIPT.PALLETTOWN.NOOP` | `6` | `6` | SAME | scripts/OaksLab.asm:26 "dw_const DoRet, SCRIPT_OAKSLAB_NOOP" |
| `SCRIPT.PALLETTOWN.OAK_NOT_SAFE_COME_WITH_ME` | `3` | `3` | SAME |  |
| `SCRIPT.PALLETTOWN.DEFAULT` | `0` | `0` | SAME |  |
| `SCRIPT.PALLETTOWN.PLAYER_FOLLOWS_OAK` | `4` | `4` | SAME |  |
| `SCRIPT.PALLETTOWN.DAISY` | `5` | `5` | SAME |  |
| `SCRIPT.VIRIDIANMART.DEFAULT` | `0` | `0` | SAME |  |
| `SCRIPT.VIRIDIANMART.OAKS_PARCEL` | `1` | `1` | SAME | constants/item_constants.asm:79 |
| `SCRIPT.VIRIDIANMART.NOOP` | `2` | `2` | SAME | scripts/OaksLab.asm:26 "dw_const DoRet, SCRIPT_OAKSLAB_NOOP" |
| `BANKS.starter_begin` | `7` | `7` | SAME |  |
| `BANKS.battle_end` | `58` | `58` | SAME |  |
| `BANKS.apex_recalc_call` | `3` | `3` | SAME |  |
| `BANKS.npc_trade_add` | `28` | `28` | SAME |  |
| `BANKS.move_mon` | `0` | `0` | SAME |  |
| `BANKS.capture_party_begin` | `3` | `3` | SAME |  |
| `BANKS.capture_box_end` | `3` | `3` | SAME |  |
| `BANKS.bag_received` | `3` | `3` | SAME |  |
| `BANKS.trainer_staging` | `15` | `15` | SAME |  |
| `BANKS.battle_begin` | `15` | `15` | SAME |  |
| `BANKS.poison_faint` | `3` | `3` | SAME |  |
| `BANKS.apex_preflight` | `3` | `3` | SAME |  |
| `BANKS.changebox_full_save` | `28` | `28` | SAME |  |
| `BANKS.apex_commit` | `3` | `3` | SAME |  |
| `BANKS.blackout` | `1` | `1` | SAME |  |
| `BANKS.add_party_mon` | `0` | `0` | SAME |  |
| `BANKS.wild_begin` | `15` | `15` | SAME |  |
| `BANKS.capture_box_begin` | `3` | `3` | SAME |  |
| `BANKS.transform_hp_hi` | `53` | `53` | SAME |  |
| `BANKS.evolve` | `44` | `44` | SAME |  |
| `BANKS.battle_faint` | `15` | `15` | SAME |  |
| `BANKS.evolve_species_store` | `44` | `44` | SAME |  |
| `BANKS.npc_trade_remove` | `28` | `28` | SAME |  |
| `BANKS.pc_release` | `51` | `51` | SAME |  |
| `BANKS.save_witness` | `28` | `28` | SAME |  |
| `BANKS.pc_withdraw` | `51` | `51` | SAME |  |
| `BANKS.cable_partial_save` | `1` | `1` | SAME |  |
| `BANKS.pc_deposit` | `51` | `51` | SAME |  |
| `BANKS.remove_pokemon` | `0` | `0` | SAME |  |
| `BANKS.capture_party_end` | `3` | `3` | SAME |  |
| `BANKS.npc_trade` | `28` | `28` | SAME |  |
| `BANKS.transform_hp_lo` | `53` | `53` | SAME |  |
| `BANKS.transform` | `53` | `53` | SAME |  |
| `BANKS.npc_trade_done` | `28` | `28` | SAME |  |
| `BANKS.capture_box` | `3` | `3` | SAME |  |
| `BANKS.starter_end` | `7` | `7` | SAME |  |
| `BANKS.cable_trade_remove` | `1` | `1` | SAME |  |
| `BANKS.daycare_withdraw` | `21` | `21` | SAME |  |
| `BANKS.cable_trade_add` | `1` | `1` | SAME |  |
| `BANKS.battle_loop_head` | `15` | `15` | SAME |  |
| `MENU.PC.box` | `33` | `33` | SAME | engine/menus/change_box_menu.asm:96 (hlcoord 13,1 = 33) |
| `MENU.PC.withdraw` | `42` | `42` | SAME | engine/pokemon/bills_pc.asm:36 (hlcoord 2,2 = 42) |
| `MENU.PC.sub_cancel` | `331` | `331` | SAME | engine/pokemon/bills_pc.asm:476-478 (hlcoord 11,14 / 11,16 = 291 / 331) |
| `MENU.PC.deposit` | `82` | `82` | SAME | engine/pokemon/bills_pc.asm:40 (hlcoord 2,4 = 82) |
| `MENU.PC.menu_x` | `1` | `1` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.PC.release` | `122` | `122` | SAME | engine/pokemon/bills_pc.asm:49 (hlcoord 2,6 = 122) |
| `MENU.PC.main` | `42` | `42` | SAME | engine/pokemon/bills_pc.asm:32 (hlcoord 2,2 = 42) |
| `MENU.PC.box_last` | `253` | `253` | SAME | engine/menus/change_box_menu.asm:96 region (one box per tile row; n=12 -> 253) |
| `MENU.PC.text1` | `281` | `281` | UNVERIFIED | vanilla driver offset 14*20+1; I did not open the line that places this text on pureRGB |
| `MENU.PC.text2` | `321` | `321` | UNVERIFIED | vanilla driver offset 16*20+1; same reason |
| `MENU.PC.menu_y` | `2` | `2` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.PC.list_step` | `40` | `40` | SAME | home/list_menu.asm:411 region (entries two tile rows apart) |
| `MENU.PC.list` | `86` | `86` | SAME | home/list_menu.asm:411 (hlcoord 6,4 = 86); the vanilla driver cites home/list_menu.asm:364-365, whose lines shifted in pureRGB |
| `MENU.PC.changebox` | `162` | `162` | SAME | engine/pokemon/bills_pc.asm:57 (hlcoord 2,8 = 162) |
| `MENU.PC.no` | `216` | `216` | SAME | home/yes_no.asm:6 (NO one row below YES) |
| `MENU.PC.yes` | `176` | `176` | SAME | home/yes_no.asm:6 (hlcoord 14,7 box; YES one row below) |
| `MENU.PC.sub_action` | `251` | `251` | SAME | engine/pokemon/bills_pc.asm:474 (hlcoord 11,12 = 251) |
| `MENU.PC.seeya` | `202` | `202` | SAME | engine/pokemon/bills_pc.asm:60 (hlcoord 2,10 = 202) |
| `MENU.MOVE.menu_y` | `12` | `12` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.MOVE.menu_x` | `5` | `5` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.BATTLE.menu_y` | `14` | `14` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.BATTLE.menu_max` | `1` | `1` | SAME | see note above |
| `MENU.BATTLE.left_watched` | `17` | `17` | SAME |  |
| `MENU.BATTLE.right_x` | `15` | `15` | SAME |  |
| `MENU.BATTLE.left_x` | `9` | `9` | SAME |  |
| `MENU.BATTLE.right_watched` | `33` | `33` | SAME |  |
| `MENU.BATTLE.template` | `11` | `11` | SAME |  |
| `MENU.PARTY.menu_y` | `1` | `1` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.PARTY.watched` | `3` | `3` | SAME |  |
| `MENU.PARTY.menu_x` | `0` | `0` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.START.menu_y` | `2` | `2` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.START.save_index_without_pokedex` | `3` | `3` | SAME | engine/menus/draw_start_menu.asm:64-76 (SAVE is row 3 of 6 without the dex) |
| `MENU.START.menu_x` | `11` | `11` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.START.max_minus_save` | `3 (vanilla row COUNT convention; 4 with the companion SLINK row)` | `2` | DELTA | engine/menus/draw_start_menu.asm:26-34 stores the LAST 0-based row index (5/6), not the row COUNT (6/7) — use menu_max == save_index + 2 |
| `MENU.START.save_index_with_pokedex` | `4` | `4` | SAME | engine/menus/draw_start_menu.asm:64-76 (the dex is a prepended row) |
| `MENU.SWITCH_BOX.menu_y` | `12` | `12` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.SWITCH_BOX.menu_max` | `2` | `2` | SAME | see note above |
| `MENU.SWITCH_BOX.watched` | `3` | `3` | SAME |  |
| `MENU.SWITCH_BOX.menu_x` | `12` | `12` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.SAVE_PROMPT.menu_y` | `8` | `8` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.SAVE_PROMPT.menu_max` | `1` | `1` | SAME | see note above |
| `MENU.SAVE_PROMPT.menu_x` | `1` | `1` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.SAVE_PROMPT.yes_index` | `0` | `0` | SAME |  |
| `MENU.SAVE_PROMPT.text_box` | `20` | `20` | SAME | see note above |
| `MENU.NAMING.menu_y` | `2` | `2` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MENU.NAMING.menu_max` | `3` | `3` | SAME | see note above |
| `MENU.NAMING.watched` | `1` | `1` | SAME |  |
| `MENU.NAMING.menu_x` | `1` | `1` | SAME | engine/pokemon/bills_pc.asm:77-79 |
| `MOVE.GROWL_SLOT` | `2` | `2` | SAME | data/pokemon/base_stats/charmander.asm:13 (level-1 moves SCRATCH, GROWL) |
| `MOVE.GROWL` | `45` | `45` | SAME | constants/move_constants.asm:53 "const GROWL ; 2d" |
| `POISON.status_bit_shift` | `3` | `3` | SAME | engine/events/poison.asm:16 (the driver's floor(status/8)%%2 test) |
| `POISON.steps_per_tick` | `4` | `4` | SAME | engine/events/poison.asm:8-10 (wStepCounter & $3 -> damage every fourth step) |
| `POISON.hp_per_tick` | `1` | `1` | SAME | engine/events/poison.asm:25 ("subtract 1 from HP") |
| `POISON.psn_mask` | `8` | `8` | SAME | engine/events/poison.asm:16 "and 1 << PSN" + constants/battle_constants.asm:65 "const PSN ; 3" |

## The six DELTA facts

1. **`EVENT.OAK_GOT_PARCEL`** (+ `OAK_GOT_PARCEL_EXISTS`, `OAK_GOT_PARCEL_SUBSTITUTE`) — vanilla bit 56,
   the flag the parcel driver polls as `oak_got_parcel`. pureRGB deleted the event:
   `constants/event_constants.asm:50` is a bare `const_skip` commented "used to be
   EVENT_OAK_GOT_PARCEL but it's no different from EVENT_GOT_POKEDEX", and nothing in `scripts/`
   or `data/` sets or checks it — reading bit 56 always yields 0, which is the live failure D2
   diagnosed. Substitute: `EVENT.GOT_POKEDEX` (bit 37, `event_constants.asm:37`), set inside
   `OaksLabOakGivesPokedexScript` (script 16) before the counter reaches 17 then NOOP(18).
2. **`MENU.START.max_minus_save`** — vanilla stores the row COUNT in `wMaxMenuItem` (6/7), so the
   driver's formula was `menu_max == save_index + 3` (+4 with the companion SLINK row). pureRGB
   stores the LAST 0-based row index (5/6): `engine/menus/draw_start_menu.asm:26-34` (`ld a, 5` …
   `inc a` … `ld [wMaxMenuItem], a`), so the formula is `save_index + 2`. The SAVE row index is
   unchanged (3/4).
3. **`ITEM.BALL_IDS` / `CATCH.hunt_ball_max`** — pureRGB adds `HYPER_BALL` `$05`
   (`constants/item_constants.asm:14`, replacing TOWN MAP) with its own `ItemUseBall` dispatch
   (`engine/items/item_effects.asm:28`). The vanilla ball scans (`{1,2,3,4}`, the hunt driver's
   `id >= 1 and id <= 4`) miss a ball the player can throw; the pure set is `{1,2,3,4,5,8}`.

## The 25 UNVERIFIED facts

- **`MART.LIST_SIGNATURE.*`** (5) — a runtime list-menu signature the mart driver matches; the
  generic list menu sets these from its own state (`home/list_menu.asm:44-53`) and I did not trace
  the Mart path. The purchase ran live on pureRGB (PLAN §11.2 Live 3).
- **`WAYPOINTS.{CENTER,FOREST,ROUTE22,HUNT}`** (18) — tile coordinates: map layout, not ROM
  constants, so no source line states them. `WAYPOINTS.PARCEL` and `WAYPOINTS.ROUTE1` are SAME
  because the live pureRGB run walked those tiles; these four groups have only been walked on
  vanilla R/B and need one pure run (or a tile-level map read).
- **`MENU.PC.text1` / `MENU.PC.text2`** (2) — tilemap offsets (14×20+1, 16×20+1) the vanilla PC
  driver carries; I did not open the lines that place that text on pureRGB.

## What this adds over D2's module, and two citation traps

- D2's two UNVERIFIED map ids are now source-verified: `ROUTE_1 = 0x0C` (`map_constants.asm:33`),
  `ROUTE_2 = 0x0D` (`:34`).
- The driver's naming-screen predicate (`gen1_scripted_play.lua:68`: `wMaxMenuItem==3`,
  `wTopMenuItemY==2`, `wTopMenuItemX==1`) IS a real menu and IS unchanged on pureRGB: it is
  `DisplayIntroNameTextBox` (`engine/movie/oak_speech/oak_speech2.asm:172-182`), the Oak-speech
  preset-name list (NEW NAME + `NUM_PLAYER_NAMES` 3 → `wMaxMenuItem = 3`). The driver's comment cites
  `engine/menus/naming_screen.asm`, which is the alphabet grid (Y=3/X=1/max=7) — the comment is stale,
  the predicate is right, and the pure value is SAME.
- `gen1_battle_driver.lua:76`'s bank filter (`hLoadedROMBank == 0x0F`) becomes a 40-entry table:
  `battle_end` is bank `$3A`, `add_party_mon`/`move_mon`/`remove_pokemon` are `$00`, the capture and
  APEX hooks `$03`, the PC hooks `$33`, the cable hooks `$01`.
- Two line-number shifts to know when porting: the PC mon-list position is `home/list_menu.asm:411`
  on pureRGB (the vanilla driver cites `:364-365`), and the Mart stock is at
  `data/items/marts/viridian.asm:2-7` with POKE_BALL at `:4`.
