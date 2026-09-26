# Acquisition paths and data sources (HGSS)

Source: pokeheartgold @ad7a3afa. OMP card G4-R4 `cx-0d075ef7` (30 accepted, 0 rejected, 2 open).

The coordinator re-checked:
- `ROAMER_MAX 4` (Raikou, Entei, Latias, Latios)
- `gs_enc_data.json` and `trainers.json` present
- 21 `WildBattle` sites
- 13 `GiveMon` lines vs the card's 12 (the generator counts exactly)

## Generator inputs (SOURCE)

| Data | Source | Format |
|---|---|---|
| Wild encounters (land, surf, rock smash, 3 rods, swarms, day/night, radio) | `files/fielddata/encountdata/gs_enc_data.json` (+ `.json.txt`); HG/SS split per entry `{"HEARTGOLD":…,"SOULSILVER":…}` or `#ifdef ENC_SOULSILVER` | JSON; struct `include/wild_encounter.h:34-56` |
| Headbutt | `files/arc/headbutt.json` (HG/SS narcs) | JSON |
| Safari Zone | `files/arc/safari_enc.json` (per **area**; `src/field/encounter_check.c:930-975`) | JSON |
| Pal Park | `files/arc/ppark.json` | JSON |
| Trainers | `files/poketool/trainer/trainers.json` (+ `trdata`/`trpoke` templates); names `trname.json` → msg 0729 | JSON |
| Map id → header | `src/data/map_headers.h` (`[MAP_*]`, `.wildEncounterBank`, `.mapsec`, `.regionNo`); ids `include/constants/maps.h` | C |
| Area names | **msg 0279** indexed by mapsec (`src/field/draw_map_name.c:110,138`); `mapname.bin` is unused | gmm |
| Species / move / item / ability names | msg 0237 / 0750 / 0222 / 0720 | gmm |
| NPC trades | **binary NARC** `files/a/1/1/2` (`NPCTrade` 0x54 B, `include/npc_trade.h:10-32`); OT names msg 0200 | NARC (parse the ROM) |

HG/SS script differences are **runtime** branches (`GetGameVersion`, cmd 494 → 7/8). There is one shared `scr_seq` build (`files/fielddata/script/scr_seq.mk:3-11`). Compile-time splits exist only in the encounter/headbutt JSON templates.

## Acquisition manifest

The generator should grep this fixed command set over `files/fielddata/script/scr_seq`:

```
^\s*(GiveMon|GiveEgg|GiveTogepiEgg|GiveSpikyEarPichu|GiveLoanMon|CreateRoamer|WildBattle|LoadNPCTrade|ChooseStarter)\b
```

Add the C `Party_AddMon` sites:
- `src/choose_starter.c:81` (Elm starter)
- `src/get_egg.c:640` (daycare / hatch)
- `src/npc_trade.c:70`
- `src/scrcmd_mystery_gift.c:305`
- `src/battle/battle_command.c:7003` (capture)
- `src/field/scrcmd_pokemon_misc.c:1071, :1139`

| Kind | Examples (site) |
|---|---|
| Starters | Elm via `ChooseStarter` (cmd 167, C, `src/choose_starter.c:45-81`); Kanto starters from Oak `scr_seq_0740_T01R0301.s:629` |
| Script gifts (`GiveMon`) | Tyrogue L10 `scr_seq_0098`; Dratini L15 `scr_seq_0112`; Eevee L5 (Bill) `scr_seq_0892`; Tentacool L15 `scr_seq_0878`; fossils L20 `scr_seq_0755`; Game Corner prizes `scr_seq_0804/0906/0910`; Hoenn starters (Steven) `scr_seq_0837`; Sinjoh Dialga/Palkia/Giratina (event) `scr_seq_0131` |
| Eggs | `GiveEgg` Mareep/Wooper/Slugma (Primo, Violet PC) `scr_seq_0860`; **Togepi egg** via `GiveTogepiEgg` cmd 776 in Violet City `scr_seq_0858_T22FS0101.s:53` (C `src/field/scrcmd_pokemon_misc.c:1029-1076`). The key item `ITEM_MYSTERY_EGG` (484) is a separate, earlier hand-off. |
| Special gifts | Spiky-eared Pichu L30 form 1, cmd 778, Ilex Forest (`scrcmd_pokemon_misc.c:1121-1123`) |
| Loans | Shuckle `GiveLoanMon 6,20,75` (Cianwood); Kenya's Spearow `GiveLoanMon 7,20,101` (Route 35) |
| Statics (`WildBattle` cmd 589, 21 sites) | Mewtwo, Articuno, Zapdos, Moltres, Suicune ×2, Lapras, Electrode ×3, Snorlax ×2, Sudowoodo ×2, Red Gyarados (shiny, L30), Groudon/Kyogre/Rayquaza, Lugia/Ho-Oh (Lugia L70 in HG, L45 in SS, `scr_seq_0104_D40R0107.s:70-80`) |
| Roamers | Raikou, Entei, Latias, Latios only (`include/constants/roamer.h:4-8`); save array 21 `RoamerSaveData` (`include/roamer.h:19-40`); created by `CreateRoamer` (cmd 361); triggered by step-count checks (`src/field/encounter_check.c:255-263, 429-436, 1205-1213`, `BATTLE_TYPE_ROAMER`). Lugia/Ho-Oh are **not** roamers. |
| NPC trades | 13 (Onix, Machop, Voltorb, Dodrio, Rapidash, Steelix, Shuckle, Spearow, Magneton, Xatu, Pikachu, Rhyhorn, Beldum), `include/constants/npc_trade.h:4-19`. Species come from the NARC. |
| Pokéwalker | **no mon-giving code** (`src/pokewalker.c`) |
| Mystery Gift | `src/scrcmd_mystery_gift.c` (incl. Manaphy egg); external distribution, not observable |

## Special catch modes (SOURCE)

- **Bug-Catching Contest** (`BATTLE_TYPE_BUG_CONTEST`):
  - `BattleSetup_New_BugContest` copies the held bug (`src/battle/battle_setup.c:93-97`).
  - A catch prompts a **swap** (`src/encounter.c:505-507` → `src/unk_0206D494.c:404-436`).
  - The winning bug is added at `src/overlay_bug_contest.c:229`, so a Soul Link catch happens at the result, not at the in-contest catch.
- **Safari Zone:** `BATTLE_TYPE_SAFARI`; 30 balls (`src/scrcmd_c.c:3403`); counter in `LocalFieldData` (`src/save_local_field_data.c:26`); encounters per area.
- **Pal Park:** present in HGSS (`MAP_PAL_PARK`, `src/catching_show.c`). It only accepts migrated mons, so it is out of scope.
- **Balls** (`include/constants/items.h`):

  | Ball | Item id |
  |---|---|
  | Master … Cherish | 1-16 (Safari 5) |
  | Level / Lure / Heavy / Love / Friend / Moon | 493 / 494 / 495 / 496 / 497 / 498 |
  | Sport | 499 |
  | Park | 500 |
  | Apricorns (Kurt makes them the next day) | 485-491 |

  The legacy table's "0x1F4 = Sport Ball" is wrong: 0x1F4 = 500 = Park Ball.

## Open

- Raw numeric species literals at the Game Corner, Silph and fossil sites: resolve them against `include/constants/species.h` in the generator.
- NPC trade NARC contents.
