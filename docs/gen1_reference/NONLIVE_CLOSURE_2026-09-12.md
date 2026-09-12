# Non-emulator closure lane, 2026-09-12 (branch `claude/gen1-nonlive-closure`, base `gen1/rc` aca99ef)

Delegated by Codex (task cx-08fdd4f7): close `protocol.dom`, `canonical.rom-layout` and
`canonical.generated-data` with source-pinned checks, no emulator. Same rule as batch 1: a proof is
registered only where a test or validator asserts the row's description clause by clause; every new
check has a negative control proving it bites. 218 registered / 170 missing of 388 after this lane.

## `protocol.dom` (closed)

| Clause | Proof | What is asserted |
| --- | --- | --- |
| stream active-run pins | `tests/unit/test_manager_stream_pin.py` (7 tests, new) | Through the app `manager.main` builds, two registry runs alive (liveness stubbed, each backed by a real aiohttp overlay stub): newest-running is the default target; `POST /api/stream/pin` routes `/stream/{name}`, its `/fragment` poll and the query string to the pinned run's port while the other run receives nothing; unknown id is 404 and a stopped or dead run is 409, both keeping the previous pin (a dead run used to be accepted with a 200 that echoed a pin `_active_stream_run` had already dropped); an accepted pin reports the stored pin; invalid JSON is 400; `null` unpins; a dead pinned run falls back and the registry records it stopped with pid null; no running run gives the friendly 404 and the empty status payload |
| capability-gated controls | same file, `test_the_ability_column_follows_the_adapter_capability[gen1_rby, gen3_rr]`, `test_the_patcher_offers_the_start_panel_only_where_the_target_has_one[rb-red, rb-blue, yellow]` | The real dashboard renders the party table without the Ability header for `Gen1Adapter` (`supports_abilities()` False) and with it for Gen 3; `/patcher` lists the START-panel feature for rb-red and rb-blue and not for yellow, following `capabilities.panel` |
| Gen 1 accurate UI | `test_routes_smoke.py` (gen1_rby parametrizations), `test_gen1_presentation.py` | Every route renders for a Gen 1 server with real Gen 1 keys, the pair reaches the dashboard and memorial, sprite class, status tokens, badge mask, active box |
| safe JSON | `test_manager_xss.py`, `test_http_server_security.py::test_dashboard_escapes_client_text_in_both_views_and_encounter_rows` | No payload closes the script element, round trip unchanged, client text escaped in both views and encounter rows, cross-origin mutation blocked |
| variant labels | `test_rom_type_routing.py::test_every_variant_has_a_display_label[gen1_rby]`, `test_gen1_archipelago.py` | Every variant the Lua module can emit has a label; red_ap/blue_ap labels; a label is never a rom_type |

## `canonical.rom-layout` (closed)

`tools/verify_gen1_rom_layout.py` gains one row per title, **"UPR pointer roots match pret symbols and
clean-ROM bytes"** (`verify_upr_roots`): every int or list key of the title's `upr_layout.json` profile is
either pinned or listed as metadata, otherwise the row fails naming it. Each root must equal its pret
symbol (through `sym_to_offset`, never a flat offset) plus a displacement read off the asm, and the clean
ROM bytes there must decode as pret says. 41 roots on Red and Blue, 43 on Yellow. Examples:

| Root | pret label + delta | Byte expectation |
| --- | --- | --- |
| PokedexOrder / PokemonNamesOffset / PokemonStatsOffset | PokedexOrder, MonsterNames, BaseStats +0 | DEX_RHYDON; "RHYDON" through the UPR text table; DEX_BULBASAUR 45,49,49,45,65 |
| OldRodOffset / GoodRodOffset / SuperRodTableOffset | ItemUseOldRod+6 (`call`+`jp c`), GoodRodMons+0, SuperRodData+0 (R/B) or SuperRodFishingSlots+0 (Y) | `01 MAGIKARP 05`; `10 GOLDEEN 10 POLIWAG`; PALLET_TOWN then a 1..4 group / STARYU 10 TENTACOOL 10 |
| MoveDataOffset / MoveNamesOffset / TypeEffectivenessOffset / TMMovesOffset | Moves, MoveNames, TypeEffects, TechnicalMachines +0 | POUND 00 40 NORMAL 255 35; "POUND"; WATER FIRE 20; first add_tm |
| StarterOffsets1/2/3 (R/B: 28 sites), StarterOffsets1/2 (Y) | OaksLab, CeruleanCity, ReadTrainer, Route22, SilphCo7F, PokemonTower2F, SSAnne2F, ChampionsRoom labels; Yellow PalletTownPikachuBattleScript, OaksLabPlayerReceivedMonText, Rival1Data+1 | `3E STARTERx` / `FE STARTERx` / Route22 `.StarterTable`; `3E STARTER_PIKACHU`; `05 EEVEE 00` |
| TrainerDataTableOffset / TrainerClassNamesOffsets / ExtraTrainerMovesTableOffset / GymLeaderMovesTableOffset | TrainerDataPointers+0; TrainerNamePointers+0x5E and TrainerNames+0; TeamMoves (R/B) / SpecialTrainerMoves (Y); LoneMoves+1 | first dw -> YoungsterData; "YOUNGSTER"; LORELEI BLIZZARD; 01 BIDE |
| MapBanks / MapAddresses / MapNameTableOffset / SpecialMapList / SpecialMapPointerTable / HiddenItemRoutine | MapHeaderBanks, MapHeaderPointers, ExternalMapEntries, HiddenEventMaps, HiddenEventPointers, HiddenItems +0 | BANK(PalletTown_h); dw PalletTown_h; `dn 11,2`; REDS_HOUSE_2F; `21 HiddenItemCoords` |
| IntroPokemonOffset / IntroCryOffset / PCPotionOffset / CatchingTutorialMonOffset / TextDelayFunctionOffset | OakSpeech+0x58 (R/B) +0x56 (Y); TextCommandSounds+0xF; OakSpeech+0x1F/+0x1D; ViridianCityOldManStartCatchTrainingScript+0x23/+0x20; PrintLetterDelay+0 | `3E NIDORINO`/`3E PIKACHU`; `14 NIDORINA`/`14 PIKACHU`; `3E POTION`; `3E WEEDLE`/`3E RATTATA`; `FA wStatusFlags5` |
| PokemonMovesetsExtraSpaceOffset / StarterPokedexBranchOffset | EffectCallBattleCore+5 (last routine of bank $0E); no label (UPR free tail of StarterDex's bank) | zeros to bank end; in-bank, past every symbol, zeros |
| PikachuHappinessCheckOffset / PikachuEvoJumpOffset (Y) | CeruleanMelanieHouseMelanieText+0x18; ItemUseEvoStone+0x39 | `FE 93 38` (cp 147; jr c); `CD .. .. 30` |

The seven values Yellow inherits from Red through `CopyFrom=Red (U)` (StarterOffsets3, StarterTextOffsets,
StarterPokedexOn/Off/Branch, SpecialMapList, PokedexRamOffset) are what UPR's own Java copies and are read by
none of the Yellow scan paths; they are pinned to Red's numbers and named in the row detail. Registered on
the `rom-layout` validator and `tests/unit/test_gen1_upr_roots.py` (row ok per title; a shifted
PokemonStatsOffset is named).

## `canonical.generated-data` (closed)

| Clause | Check | Source parsed at check time |
| --- | --- | --- |
| maps/subareas | `tools/gen_gen1_area_map.py --check` | `constants/map_constants.asm` (both decomps), `data/wild/grass_water.asm`, `data/wild/super_rod.asm`; every fishable map has an area; Yellow-only ids stated; the Lua tables equal a render of the JSON |
| every encounter method | `tools/gen_gen1_encounters.py --check` + the clean-ROM scanner control (`test_gen1_rom_content.py`, now every method) | grass/water per map with the version conditionals, `good_rod.asm`, `super_rod.asm` (R/B pointer groups and the Yellow flat format), `ItemUseOldRod`; Old/Good/Super Rod shipped for 28 areas per title; rates are the title's own pick: R/B uniform (`ReadSuperRodData` rejection-samples a 2-bit number), Yellow 102/76/51/27 of 256 (`GenerateRandomFishingEncounter` compares one byte to `$66/$B2/$E5`, parsed from `engine/items/super_rod.asm` and asserted equal to the scanner pin `YELLOW_SUPER_ROD_THRESHOLDS`); every fishing map in a multi-map area keeps its own labelled Super Rod row (wild floor, else the map constant's tail: `Super Rod Dock`, `Super Rod Gym`, `Super Rod 1F/B1F`), published in `floor_labels.json` and applied identically by `build_encounter_tables`, which also emits Old and Good Rod so production ROM ingestion cannot drop a method |
| types | `test_gen1_canonical_moves_trainers_types.py::test_types_match_pret[red/blue, yellow]` | `constants/type_constants.asm` and all 151 `data/pokemon/base_stats/*.asm` equal `_TYPE_IDS` and `_SPECIES_TYPES` (BIRD, carried by nothing, is the documented omission) |
| moves | `tools/gen_moves_data.py --check` | `data/moves/moves.asm` and `names.asm` of both decomps: 165 in id order, name, type, power, accuracy, pp, split |
| trainers | `tools/gen_gen1_trainers.py --check` | `constants/trainer_constants.asm` (OPP_ID_OFFSET parsed), `data/trainers/names.asm`, `data/trainers/parties.asm` per title; party counts equal the UPR pin `TrainerDataClassCounts` |
| items, gifts, statics, evolution families | already proven: `test_gen1_items.py`, the `acquisition-source-census` validator, `test_gen1_static_receipt.py`, `test_gen1_gift_areas.py`, the ROM-vs-asm evolution graph control in `test_gen1_rom_scan.py` | registered on this row for the first time |

Data defects the checks found and fixed:

- `trainers.json` and `lua/games/gen1_rby_trainers.lua` listed five Champion (class 243) parties; `Rival3Data`
  has three, one per starter, in every title and the UPR pin agrees.
- The shipped tables had no fishing at all while the ROM scanner already read all three rods; the scanner
  weighted a Super Rod group with the grass slot rates (a two-fish group showed 54/46) while its docstring
  claimed uniformity.
- Six fishable maps had no rule area (Viridian, Cerulean, Vermilion and Fuchsia city maps, Cerulean Gym,
  Vermilion Dock): the cities are areas now, the gym and dock fold into their cities as the Fighting Dojo
  folds into Saffron. **Mapping them exposed the Route 4 defect with a rod:** `pallet_town`, `celadon_city`
  and `cinnabar_island` were gift areas (never dead-zone, no clauses, no ball gate) while every title lets
  you fish there. They leave `_GIFT_AREAS` and the Lua mirror; no grant is delivered under those ids at
  runtime (the starter settles in `oaks_lab`, other grants arrive namespaced through `gift_link_area`).
- The dashboard looked encounter icons up on the first word of the method, so no rod or Rock Smash method
  in any generation ever had its icon.

Persisted state across the gift-area reclassification: everything a run saved under `pallet_town`,
`celadon_city` or `cinnabar_island` was gift-classified (that was the defect), so `SoulLinkState.load` passes
every persisted area id through the adapter's `persisted_area` hook and Gen 1 moves those three into the gift
namespace (`gift_cinnabar_island` keeps the fossil pair a gift pair; a pending fossil cannot pair with a rod
catch; the town is a real encounter area from then on). Shared code calls the hook only; identity elsewhere.
`tools/gen_gen1_area_map.py --check` fails on any fishable map without an area (no note path). The Super Rod
labels are derived, not hand-typed: a per-title test asserts that every area holds exactly one labelled row per
fishing map, each label the wild floor or the map constant's tail, so a future map or decomp change cannot
silently collapse rows. Ruff on the lane's files is clean under the default ruleset; the six findings left in
`server/manager.py:756-787` predate the lane (Codex's launcher hunk) and were not touched.

Review corrections (Codex, same day): the first cut modelled Yellow's Super Rod as uniform and let the
lowest map id win a shared area, hiding Yellow's Vermilion Dock and Cerulean Cave 1F rows, and the scanner
did not emit Old/Good Rod so a ROM-ingested table lost them. All three are fixed above; the `Super Rod`
key count per title is 26 because Cerulean Cave carries only labelled rows.

## Re-pins

`tools/repin_gen1_release_hashes.py --write` re-pinned 1,500 entries over 77 rows: Codex's commits after
ffcc118 (`server/gen1_launcher.py`, `lua/gen1_client_entry.lua`, `lua/gen1_held_faint.lua`,
`server/gen1_observation_runtime.py`, `server/manager.py`, `lua/slink.lua` and their tests; the gate on
`gen1/rc` was already red on that drift) plus this lane's `server/server.py`,
`server/adapters/gen1_rom_scan.py`, `server/adapters/gen1_rby.py`, `lua/games/gen1_rby.lua`, the area map
and the two tools. The gate run is the review.

## Verification

- `python tools/verify_gen1_rom_layout.py`: 40 ok / 0 fail / 0 missing.
- `python tools/gen_gen1_area_map.py --check`, `gen_gen1_encounters.py --check`, `gen_moves_data.py --check`,
  `gen_gen1_trainers.py --check`: all exit 0.
- `python -m pytest tests/unit -k "gen1 or gift or no_catch or semantic or routes_smoke or manager or rom_scan or rom_content or adapter or engine_bridge or starter or acquisition"`: 5100 passed (before the review corrections; the affected suites, 447 tests, rerun green after them).
- `python tools/repin_gen1_release_hashes.py`: 0 stale, 0 missing. `verify_gen1_release.py --list`: 218 / 170.
- `verify_gen1_release.py --quick` and the inventory refresh: recorded in the closing commit.
