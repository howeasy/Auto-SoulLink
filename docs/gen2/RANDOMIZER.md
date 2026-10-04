# Gen 2 randomizer: does UPR write into the SLink overlay? (R0)

Card R0, 2026-10-04, branch `claude/gen2-randomizer` off master 020073c6. Evidence:
`F:/slink-work/evidence/g2-rand-r0/` (per-run JSON + UPR logs, `summary.json`,
`differential*.json`, the `.rnqs` files under `settings/`, the private probe sources under
`probe/`, `write_domain_tables.md`). Tool: `tools/upr_gen2_write_domain.py`.

## Verdict

**No collision on any title, any run or any tweak.** With the pinned fork, randomizing an
SLink Gen 2 companion-overlay ROM never changed an overlay byte, never wrote inside an
`SLink ...` ROM section and never touched the cartridge header. With a fixed seed the two
orders give the same bytes: `randomize(overlay)` equals `randomize(clean)` everywhere outside
the overlay hunks, and keeps the overlay's own bytes inside them. "Apply the UPS overlay,
then randomize" is safe for this jar and these settings.

| Title | Runs | Overlay hunk hits | SLink section hits | Header writes | Same-seed differential (4 seeds) |
|---|---|---|---|---|---|
| Crystal | 21 | 0 | 0 | 0 | 0 bytes differ outside hunks, 0 hunk bytes written |
| Gold | 21 | 0 | 0 | 0 | 0 / 0 |
| Silver | 21 | 0 | 0 | 0 | 0 / 0 |

Each misc tweak was run alone over the overlay with every category off. All five were then
run together with the max settings in the seed-44 differential.

| Tweak | Crystal | Gold | Silver | What it writes beyond the all-off baseline |
|---|---|---|---|---|
| BW_EXP_PATCH | safe | safe | safe | 1,214 bytes: free space 0F:7F00-7F4D (76) and 5A:6B00-7058 (1,119), 9 in Battle Core, 10 in `_BoostedExpPointsText` |
| FASTEST_TEXT | safe | safe | safe | 1 byte: `PrintLetterDelay` (Crystal 00:313D, G/S 00:31E2) |
| LOWER_CASE_POKEMON_NAMES | safe | safe | safe | 1,572 bytes: `PokemonNames` (Crystal bank 14, G/S bank 6C) |
| RANDOMIZE_CATCHING_TUTORIAL | safe | safe | safe | 3 bytes: the catching-tutorial species (Crystal bank 68, G/S bank 4A) |
| BAN_LUCKY_EGG | safe | safe | safe | nothing on its own: it only limits item randomization (the effective settings string does carry the bit) |

The closest any UPR write gets to an overlay byte is 151 bytes, on Crystal: `ContestMons` at
25:7D88 against an overlay byte at 25:7CF1. On Gold and Silver it is 152 bytes at the same place.

## Inputs

- Jar: `.cache/slink-upr/PokeRandoZX.jar`, sha256
  `db4bc65c3a0c1761ffc70db6a5c0f495635ab3e0e3c8a99640f34fbb1fb833ac` (data/upr_jars.json:
  "stamp v0.3.0 2026-10-03 (patches 0001-0015)"). It reports UPR 4.6.1 and runs on the
  Java 8 JRE on PATH. `Gen2RomHandler` picks the same entries for the overlay ROMs as for the
  clean dumps (`Crystal (U)`, `Gold (U)`, `Silver (U)`): the game code, version and region
  bytes are unchanged.
- Clean dumps, sha1-checked against data/gen2_sources.lock.json: Crystal `f4cd194b...` (from
  `.cache/gen2-audit-e2yagroz/crystal.gbc`), Gold `d8b8a360...` and Silver `49b163f7...`
  (from `.cache/gen2-build/pokegold/`).
- Overlays rebuilt with `patch/tools/make_ups.py` `ups_apply` from `patch/dist/SLink-*.ups`.
  All three match the sha1 and md5 in data/gen2/overlay_provenance.json (Crystal
  `d5f342db...`, Gold `51b076ac...`, Silver `209e0b46...`).
- What counts as the overlay, per title:
  - The overlay hunks decoded from the UPS: Crystal 336 hunks / **9,839** bytes, Gold
    335 / 8,944, Silver 333 / 8,947. Crystal's last hunk runs to EOF at 7F:7FFF with no
    terminating zero XOR. That makes it 9,839 bytes, one more than the 9,838 on the card.
  - Every ROM section whose name starts with `SLink` in `data/gen2/<title>_slink.map`. That is
    20 per title: the four bank 0 bridges, plus Crystal banks 24/64/75 or G/S banks 13/24/5C.
    They total 4,333 bytes on Crystal and 4,241 on G/S. The `SLink Mailbox` section is in WRAM
    ($CFD8), where UPR cannot write.
  - For information only, the vanilla sections that contain an overlay byte (Home, bank1-5,
    bankB, bank14, bank24, Events, Title, the Stadium 2 checksums and others). UPR writes into
    some of them: Home, bank1, bank4, bank14, bank24, Events, Crystal Map Scripts 17 and G/S
    Map Scripts 26. Every one of those writes stays away from the overlay bytes. For example,
    UPR's only bank 4 write is `TMHMMoves` at 04:567A, well clear of the relocated StartMenu
    at 04:6721-7B98.

## Method

1. Run `python tools/upr_gen2_write_domain.py --jar <pinned jar> --clean crystal=...
   --clean gold=... --clean silver=...`. For each title the tool makes 21 runs of the fork
   CLI. Each run uses the same argv as `server/upr_pipeline.randomize()`
   (`java -jar <jar> cli -s <rnqs> -i <in> -o <out> -l`), after the same trusted-jar check:
   - `off`: every category off and no tweaks (the baseline);
   - `max1..max5`: wild, trainers, starters, statics, in-game trades, TMs and TM compat, move
     tutors and tutor compat, and field items. The wild mode rotates through random, area 1:1
     and global 1:1;
   - `cat_*`: each category alone (wild in all three modes, trainers, starters, statics,
     trades, tms, tutors, field_items);
   - `tweak_*`: each misc tweak alone.
   The tool diffs every output against the overlay input and intersects the changed bytes
   with the overlay set above.
2. Same-seed differential. The fork's CLI cannot take a seed, so this uses a private probe:
   `tools/upr_probe/SlinkProbe.java` with `Gen1RomHandler` replaced by `Gen2RomHandler`,
   compiled against the jar with the pinned JDK 17. It lives under `F:/slink-work/tmp`, with a
   copy in the evidence `probe/` folder. Four seeds were used: 11, 22 and 33 (max settings, one
   per wild mode) and 44 (max settings plus all five tweaks). For each seed, the clean dump and
   the overlay dump randomized with that seed must match on every byte outside the overlay
   hunks. Inside the hunks, the overlay output must equal the overlay input. **All 12 pairs
   pass, with 0 bytes off on either check.**
3. Known-positive controls. `--self-check` (run for each title) flips three bytes: one in an
   overlay hunk, one in an SLink section and one in a vanilla table. The audit must flag the
   first two and report the third only as an ordinary write region. The self-check also
   requires the decoded hunks to match the clean-vs-overlay diff exactly, which is how the EOF
   hunk byte was found. For the differential, the overlay randomized with seed 45 must differ
   from the seed-44 output outside the hunks. It does: 8,437 bytes on Crystal, 7,724 on Gold,
   7,727 on Silver.

### Settings

Every `.rnqs` is built with `server.upr_settings.build()`: UPR's own defaults plus the flags
below. The rom name is `Pokemon Crystal (U)`, `Pokemon Gold (U)` or `Pokemon Silver (U)`. Base
stats, types, abilities, evolutions, movesets and move data stay UNCHANGED in every run.

| Category | Flags set (the matching `*_UNCHANGED` bit is cleared) |
|---|---|
| wild | `wild_RANDOM` / `wild_AREA_MAPPING` / `wild_GLOBAL_MAPPING`, restriction NONE, wild legendaries blocked (the default) |
| trainers | `trainers_RANDOM` |
| starters | `starters_COMPLETELY_RANDOM` |
| statics | `static_COMPLETELY_RANDOM` |
| trades | `trades_RANDOMIZE_GIVEN_AND_REQUESTED` + items, IVs, nicknames, OTs |
| tms | `tms_RANDOM` + `tmCompat_COMPLETELY_RANDOM` |
| tutors | `tutors_RANDOM` + `tutorCompat_COMPLETELY_RANDOM` (Crystal only; G/S have no tutors, so their run matches the baseline) |
| field_items | `fieldItems_RANDOM` |
| tweaks | `MISC_TWEAKS` bits BW_EXP_PATCH, FASTEST_TEXT, LOWER_CASE_POKEMON_NAMES, RANDOMIZE_CATCHING_TUTORIAL, BAN_LUCKY_EGG |

Each log's effective settings string was decoded again with `parse_settings_string`. Every
tweak run carries exactly its own tweak bit.

### Seeds (CLI runs, drawn by UPR)

| Run | Crystal | Gold | Silver |
|---|---|---|---|
| max1 (random) | 120467846379053 | 19919166501434 | 125227498147140 |
| max2 (area) | 112043814412766 | 99875019693094 | 130827835661658 |
| max3 (global) | 172528382551388 | 232031008290641 | 221755789696370 |
| max4 (random) | 20926159872051 | 151639059095350 | 76718382511412 |
| max5 (area) | 157569365772573 | 130522538717435 | 249078009839705 |

Differential seeds (probe): 11, 22, 33 and 44, plus 45 as the control.

## UPR accepts the overlay ROM

Every run exited 0 and printed `Randomized successfully!`, with empty stderr. The logs mention
the CRC only once, as information: `Original ROM CRC32: CBE21A7B` (Crystal), `4A5BDF5E` (Gold),
`3D687F98` (Silver). These are the overlay CRC32s, which differ from the INI `CRC32=` values,
and the CLI prints no warning about the mismatch. UPR never writes the header (0x134-0x14F), so
it does not recompute the global checksum. A randomized overlay therefore keeps the overlay's
header bytes, and its global checksum no longer matches the contents. A randomized clean ROM
ends up the same way, and GBC hardware and emulators do not check that checksum.

## Findings worth knowing

- **UPR is not lossless on Gen 2.** The all-off run still changes 5,411 bytes on Crystal and
  5,398 on G/S. It always repacks `EvosAttacks` in bank 10 (5,409 / 5,396 bytes); the pointers
  move even when nothing else changes. It also always re-rolls the intro Pokemon, writing the
  `OakSpeech` sprite and cry bytes (01:5FD2 and 01:6050 on Crystal). A future audit has to
  compare evolutions and level-up moves as a graph, as the Gen 1 `_check_content` does, not
  byte by byte.
- **Three writes go into free space** that the clean map leaves unallocated (the gaps in
  `data/gen2/linker_slack.json`):
  - BW_EXP_PATCH writes 0F:7F00-7F4D (76 bytes) on all three titles;
  - BW_EXP_PATCH writes 5A:6B00-7058 (1,119 bytes) on all three titles;
  - on Crystal, the tutor menu goes to `MoveTutorMenuNewSpace` at 66:7B00. Up to 45 bytes were
    seen; the size depends on the move names chosen.

  The overlay uses none of these ranges today. **If the overlay grows, it must stay out of
  them** (or SLink must refuse the BW EXP tweak and tutor randomization). Otherwise the
  same-seed result above stops holding.
- The Stadium 2 checksum block in bank 7F is part of the overlay hunks. UPR does not update it,
  whether the input is clean or overlay. Nothing in SLink reads it.

## Gen 2 write domain (input for a future audit module)

The tables below are the union over all 21 runs for each title. Bytes are grouped by the
section of the overlay map they fall in. The label is the first symbol at or before the start
of the range. "ALWAYS" means the all-off run writes there too. The full byte lists are in
`summary.json` (`write_domain`) and in the per-run JSONs.

#### Crystal

| Section (overlay map) | Range | Sub-ranges | Bytes (union) | Written by |
|---|---|---|---|---|
| Home (`PrintLetterDelay`) | 00:313D-00:313D | 1 | 1 | FASTEST_TEXT |
| bank1 (`OakSpeech`) | 01:5FD2-01:730A | 3 | 3 | ALWAYS (all-off run too), statics |
| bank4 (`TMHMMoves`) | 04:567A-04:56AB | 1 | 50 | tms |
| bankA (`InitRoamMons`) | 0A:62A1-0A:792D | 2 | 2252 | statics, wild |
| Enemy Trainers (`Trainers`) | 0E:5A29-0E:7A65 | 1 | 2653 | trainers |
| Battle Core (`SometimesFleeMons`) | 0F:459A-0F:70E6 | 4 | 13 | BW_EXP_PATCH, statics, wild |
| (free space, bank 0F) (`BattleCommandPointers`) | 0F:7F00-0F:7F4D | 1 | 76 | BW_EXP_PATCH |
| Evolutions and Attacks (`EvosAttacksPointers`) | 10:65B5-10:7C5A | 2 | 5409 | ALWAYS (all-off run too) |
| Crystal Features 1 (`MoveTutor.GetMoveTutorMove`) | 12:52B1-12:66FD | 2 | 6 | statics, tutors |
| bank14 (`BaseData`) | 14:543C-14:7D4D | 251 | 3580 | LOWER_CASE_POKEMON_NAMES, tms, tutors |
| Map Scripts 1 (`WhitneyAttractText`) | 15:4307-15:6DE2 | 6 | 95 | statics, tms |
| Map Scripts 2 (`RuinsOfAlphHoOhItemRoomGoldBerry`) | 16:5918-16:7279 | 11 | 29 | field_items, statics |
| Map Scripts 3 (`NationalParkParlyzHeal`) | 17:41CC-17:6841 | 3 | 34 | field_items, tms |
| Map Scripts 4 (`RadioTower5FUltraBall`) | 18:40FE-18:6E1E | 4 | 42 | field_items, tms |
| Map Scripts 5 (`Route11HiddenRevive`) | 1A:4059-1A:5D65 | 4 | 17 | field_items, statics, tms |
| Map Scripts 6 (`VoltorbExplodingTrap`) | 1B:4A38-1B:6E20 | 8 | 30 | field_items, statics |
| Map Scripts 7 (`RedGyarados`) | 1C:406A-1C:6D54 | 9 | 156 | field_items, statics, tms |
| Map Scripts 8 (`DiglettsCaveHiddenMaxRevive`) | 1D:4007-1D:7256 | 9 | 23 | field_items, statics |
| Map Scripts 9 (`Route34Nugget`) | 1E:432B-1E:74EE | 11 | 125 | field_items, starters, tms |
| Map Scripts 10 (`GoldenrodUndergroundHiddenParlyzHeal`) | 1F:430D-1F:666F | 14 | 49 | field_items, statics |
| bank24 (`FishGroups.Shore_Old`) | 24:64E4-24:666D | 1 | 155 | wild |
| Events (`ContestMons`) | 25:7D88-25:7DAC | 1 | 10 | wild |
| Map Scripts 11 (`MortyText_ShadowBallSpeech`) | 26:60F1-26:611A | 1 | 42 | tms |
| Map Scripts 12 (`Jasmine_IronTailSpeech`) | 27:43A7-27:58EF | 3 | 70 | tms |
| bank2E (`TreeMonSet_None`) | 2E:42FB-2E:43E2 | 1 | 74 | wild |
| bank3F (`NPCTrades`) | 3F:4E59-3F:4F31 | 1 | 149 | trades |
| (free space, bank 5A) (`UnownRBackpic`) | 5A:6B00-5A:7058 | 1 | 1119 | BW_EXP_PATCH |
| Map Scripts 14 (`CeruleanCityHiddenBerserkGene`) | 61:40BB-61:6231 | 18 | 31 | field_items, statics |
| Map Scripts 15 (`PowerPlantManagerTM07IsZapCannonText`) | 62:5409-62:67E3 | 3 | 71 | field_items, tms |
| Map Scripts 16 (`WhirlIslandNEUltraBall`) | 63:4396-63:6F35 | 15 | 146 | field_items, statics, tms |
| Map Scripts 17 (`Route32GreatBall`) | 64:4773-64:51A7 | 2 | 17 | field_items, tms |
| Map Scripts 18 (`WateredWeirdTreeScript`) | 65:4068-65:6043 | 4 | 155 | statics, tms |
| Map Scripts 19 (`AzaleaTownHiddenFullHeal`) | 66:4133-66:6601 | 4 | 74 | field_items, tms, tutors |
| (free space, bank 66) (`OaksLab_MapEvents`) | 66:7B00-66:7B2C | 1 | 45 | tutors |
| Map Scripts 20 (`Route35TMRollout`) | 67:4A7C-67:6FE7 | 5 | 13 | field_items |
| Map Scripts 21 (`CianwoodCityHiddenRevive`) | 68:40D6-68:64A1 | 8 | 11 | RANDOMIZE_CATCHING_TUTORIAL, field_items |
| Map Scripts 22 (`EcruteakCityHiddenHyperPotion`) | 69:4057-69:7011 | 9 | 75 | field_items, tms |
| Map Scripts 23 (`VioletCityPPUp`) | 6A:4421-6A:6FA4 | 10 | 34 | field_items, statics, tms |
| Map Scripts 24 (`Route2DireHit`) | 6B:42FE-6B:6213 | 4 | 13 | field_items |
| Map Scripts 25 (`SilverCaveOutsideHiddenFullRestore`) | 6C:6053-6C:6053 | 1 | 1 | field_items |
| Text 2 (`_BoostedExpPointsText`) | 70:42B7-70:42D6 | 1 | 10 | BW_EXP_PATCH |
| Crystal Events (`OddEggs`) | 7E:756E-7E:7887 | 28 | 124 | statics |

#### Gold

| Section (overlay map) | Range | Sub-ranges | Bytes (union) | Written by |
|---|---|---|---|---|
| Home (`PrintLetterDelay`) | 00:31E2-00:31E2 | 1 | 1 | FASTEST_TEXT |
| bank1 (`OakSpeech`) | 01:5FDE-01:73E6 | 3 | 3 | ALWAYS (all-off run too), statics |
| bank4 (`TMHMMoves`) | 04:5A66-04:5A97 | 1 | 50 | tms |
| bankA (`InitRoamMons`) | 0A:67D8-0A:7EE1 | 2 | 2296 | statics, wild |
| Enemy Trainers (`Trainers`) | 0E:59CC-0E:7683 | 1 | 2229 | trainers |
| Battle Core (`SometimesFleeMons`) | 0F:4551-0F:6F0F | 4 | 14 | BW_EXP_PATCH, statics, wild |
| (free space, bank 0F) (`BattleCommandPointers`) | 0F:7F00-0F:7F4D | 1 | 76 | BW_EXP_PATCH |
| Evolutions and Attacks (`EvosAttacksPointers`) | 10:67C1-10:7E56 | 2 | 5396 | ALWAYS (all-off run too) |
| bank14 (`BaseData`) | 14:5B23-14:7A6A | 251 | 2003 | tms |
| bank24 (`FishGroups.Shore_Old`) | 24:6A53-24:6BDC | 1 | 155 | wild |
| Events (`ContestMons`) | 25:7BB9-25:7BDD | 1 | 10 | wild |
| bank2E (`TreeMonSet_Unused`) | 2E:647D-2E:64EC | 1 | 36 | wild |
| bank3F (`NPCTrades`) | 3F:4C25-3F:4CDD | 1 | 124 | trades |
| Map Scripts 1 (`SproutTower1FParlyzHeal`) | 42:4022-42:5A60 | 16 | 45 | field_items, statics |
| Map Scripts 2 (`NationalParkParlyzHeal`) | 43:418F-43:5EDE | 3 | 33 | field_items, tms |
| Map Scripts 3 (`UnionCave1FGreatBall`) | 44:5051-44:6DA2 | 9 | 18 | field_items, statics |
| Map Scripts 4 (`VoltorbExplodingTrap`) | 45:46F3-45:6982 | 8 | 26 | field_items, statics |
| Map Scripts 5 (`GoldenrodUndergroundHiddenParlyzHeal`) | 46:42D5-46:6329 | 14 | 40 | field_items, statics |
| Map Scripts 6 (`WhirlIslandNEUltraBall`) | 47:401E-47:4A22 | 13 | 94 | field_items, statics, tms |
| Map Scripts 7 (`VioletCityPPUp`) | 48:4CD7-48:5935 | 3 | 6 | field_items |
| Map Scripts 8 (`EcruteakCityHiddenHyperPotion`) | 49:4556-49:5F26 | 4 | 9 | field_items, statics |
| Map Scripts 9 (`Route26MaxElixer`) | 4A:4173-4A:5E02 | 10 | 75 | RANDOMIZE_CATCHING_TUTORIAL, field_items, tms |
| Map Scripts 10 (`Route32GreatBall`) | 4B:4288-4B:64B3 | 6 | 77 | field_items, statics, tms |
| Map Scripts 11 (`Route37HiddenEther`) | 4C:4092-4C:5C15 | 5 | 7 | field_items |
| Map Scripts 12 (`Route43MaxEther`) | 4D:418C-4D:5C19 | 5 | 18 | field_items |
| Map Scripts 13 (`ViridianCityDreamEaterFisherGotDreamEaterText`) | 4E:4352-4E:5B39 | 4 | 24 | field_items, tms |
| Map Scripts 14 (`Route15PPUp`) | 4F:407D-4F:60AF | 7 | 10 | field_items, statics |
| Map Scripts 15 (`Route9HiddenEther`) | 50:407F-50:51D4 | 3 | 5 | field_items |
| Map Scripts 16 (`Jasmine_IronTailSpeech`) | 51:4388-51:5707 | 3 | 112 | tms |
| Map Scripts 17 (`MortyText_ShadowBallSpeech`) | 52:53DB-52:5404 | 1 | 42 | tms |
| Map Scripts 18 (`BlackthornGymClairText_DescribeTM24`) | 53:44B6-53:55D6 | 2 | 77 | tms |
| Map Scripts 19 (`PowerPlantManagerTM07IsZapCannonText`) | 54:535A-54:5380 | 1 | 39 | tms |
| Map Scripts 20 (`BugsyText_FuryCutterSpeech`) | 55:506F-55:509B | 1 | 45 | tms |
| Map Scripts 21 (`FalknerTMMudSlapText`) | 56:442D-56:59FC | 3 | 16 | statics, tms |
| Map Scripts 22 (`WhitneyAttractText`) | 57:430C-57:707F | 7 | 131 | statics, tms |
| (free space, bank 5A) (`HallOfFame_MapEvents`) | 5A:6B00-5A:7058 | 1 | 1119 | BW_EXP_PATCH |
| Map Scripts 25 (`OlivinePortHiddenProtein`) | 5B:418D-5B:6929 | 4 | 5 | field_items, statics |
| Map Scripts 26 (`JanineText_ToxicSpeech`) | 5C:433D-5C:435D | 1 | 33 | tms |
| Map Scripts 27 (`ChuckExplainTMText`) | 5D:55D7-5D:55E4 | 1 | 14 | tms |
| Map Scripts 28 (`CeladonMansionRoofHousePharmacistCurseText`) | 5E:5341-5E:60F4 | 6 | 144 | statics, tms |
| Map Scripts 30 (`CyndaquilPokeBallScript`) | 60:40D2-60:64AB | 10 | 119 | starters, tms |
| Map Scripts 31 (`FightingDojoFocusBand`) | 61:400B-61:4B7E | 2 | 34 | field_items, tms |
| Text 1 (`_BoostedExpPointsText`) | 64:5E29-64:5E48 | 1 | 10 | BW_EXP_PATCH |
| Names (`PokemonNames`) | 6C:4B75-6C:553D | 1 | 1572 | LOWER_CASE_POKEMON_NAMES |

#### Silver

| Section (overlay map) | Range | Sub-ranges | Bytes (union) | Written by |
|---|---|---|---|---|
| Home (`PrintLetterDelay`) | 00:31E2-00:31E2 | 1 | 1 | FASTEST_TEXT |
| bank1 (`OakSpeech`) | 01:5FDE-01:73AC | 3 | 3 | ALWAYS (all-off run too), statics |
| bank4 (`TMHMMoves`) | 04:5A66-04:5A97 | 1 | 50 | tms |
| bankA (`InitRoamMons`) | 0A:67D8-0A:7EE1 | 2 | 2296 | statics, wild |
| Enemy Trainers (`Trainers`) | 0E:59CC-0E:7683 | 1 | 2229 | trainers |
| Battle Core (`SometimesFleeMons`) | 0F:4551-0F:6F0F | 4 | 14 | BW_EXP_PATCH, statics, wild |
| (free space, bank 0F) (`BattleCommandPointers`) | 0F:7F00-0F:7F4D | 1 | 76 | BW_EXP_PATCH |
| Evolutions and Attacks (`EvosAttacksPointers`) | 10:67C1-10:7E56 | 2 | 5396 | ALWAYS (all-off run too) |
| bank14 (`BaseData`) | 14:5B23-14:7A6A | 251 | 2003 | tms |
| bank24 (`FishGroups.Shore_Old`) | 24:6A53-24:6BDC | 1 | 155 | wild |
| Events (`ContestMons`) | 25:7BB9-25:7BDD | 1 | 10 | wild |
| bank2E (`TreeMonSet_Unused`) | 2E:647D-2E:64EC | 1 | 36 | wild |
| bank3F (`NPCTrades`) | 3F:4C25-3F:4CDC | 1 | 127 | trades |
| Map Scripts 1 (`SproutTower1FParlyzHeal`) | 42:4022-42:5A60 | 16 | 45 | field_items, statics |
| Map Scripts 2 (`NationalParkParlyzHeal`) | 43:418F-43:5EE0 | 3 | 35 | field_items, tms |
| Map Scripts 3 (`UnionCave1FGreatBall`) | 44:5051-44:6DA2 | 9 | 18 | field_items, statics |
| Map Scripts 4 (`VoltorbExplodingTrap`) | 45:46F3-45:6982 | 8 | 26 | field_items, statics |
| Map Scripts 5 (`GoldenrodUndergroundHiddenParlyzHeal`) | 46:42D5-46:6329 | 14 | 40 | field_items, statics |
| Map Scripts 6 (`WhirlIslandNEUltraBall`) | 47:401E-47:4A22 | 14 | 94 | field_items, statics, tms |
| Map Scripts 7 (`VioletCityPPUp`) | 48:4CD7-48:5935 | 3 | 6 | field_items |
| Map Scripts 8 (`EcruteakCityHiddenHyperPotion`) | 49:4556-49:5F26 | 4 | 9 | field_items, statics |
| Map Scripts 9 (`Route26MaxElixer`) | 4A:4173-4A:5E02 | 10 | 75 | RANDOMIZE_CATCHING_TUTORIAL, field_items, tms |
| Map Scripts 10 (`Route32GreatBall`) | 4B:4288-4B:64B4 | 6 | 83 | field_items, statics, tms |
| Map Scripts 11 (`Route37HiddenEther`) | 4C:4092-4C:5C15 | 5 | 7 | field_items |
| Map Scripts 12 (`Route43MaxEther`) | 4D:418C-4D:5C19 | 5 | 18 | field_items |
| Map Scripts 13 (`ViridianCityDreamEaterFisherGotDreamEaterText`) | 4E:4352-4E:5B39 | 4 | 24 | field_items, tms |
| Map Scripts 14 (`Route15PPUp`) | 4F:407D-4F:60AF | 7 | 10 | field_items, statics |
| Map Scripts 15 (`Route9HiddenEther`) | 50:407F-50:51D4 | 3 | 5 | field_items |
| Map Scripts 16 (`Jasmine_IronTailSpeech`) | 51:4388-51:5706 | 3 | 111 | tms |
| Map Scripts 17 (`MortyText_ShadowBallSpeech`) | 52:53DB-52:5405 | 1 | 43 | tms |
| Map Scripts 18 (`BlackthornGymClairText_DescribeTM24`) | 53:44B6-53:55D6 | 2 | 77 | tms |
| Map Scripts 19 (`PowerPlantManagerTM07IsZapCannonText`) | 54:535A-54:5381 | 1 | 40 | tms |
| Map Scripts 20 (`BugsyText_FuryCutterSpeech`) | 55:506F-55:509B | 1 | 45 | tms |
| Map Scripts 21 (`FalknerTMMudSlapText`) | 56:442D-56:59FC | 3 | 15 | statics, tms |
| Map Scripts 22 (`WhitneyAttractText`) | 57:430C-57:707E | 7 | 130 | statics, tms |
| (free space, bank 5A) (`HallOfFame_MapEvents`) | 5A:6B00-5A:7058 | 1 | 1119 | BW_EXP_PATCH |
| Map Scripts 25 (`OlivinePortHiddenProtein`) | 5B:418D-5B:6934 | 5 | 5 | field_items, statics |
| Map Scripts 26 (`JanineText_ToxicSpeech`) | 5C:433D-5C:435C | 1 | 32 | tms |
| Map Scripts 27 (`ChuckExplainTMText`) | 5D:55D7-5D:55E5 | 1 | 15 | tms |
| Map Scripts 28 (`CeladonMansionRoofHousePharmacistCurseText`) | 5E:5341-5E:60F5 | 6 | 147 | statics, tms |
| Map Scripts 30 (`CyndaquilPokeBallScript`) | 60:40D2-60:64AC | 10 | 122 | starters, tms |
| Map Scripts 31 (`FightingDojoFocusBand`) | 61:400B-61:4B7D | 2 | 33 | field_items, tms |
| Text 1 (`_BoostedExpPointsText`) | 64:5E29-64:5E48 | 1 | 10 | BW_EXP_PATCH |
| Names (`PokemonNames`) | 6C:4B75-6C:553D | 1 | 1572 | LOWER_CASE_POKEMON_NAMES |

## Reproduce

```
python tools/upr_gen2_write_domain.py --self-check --clean crystal=<clean crystal.gbc>
python tools/upr_gen2_write_domain.py --jar <.cache/slink-upr/PokeRandoZX.jar> \
    --clean crystal=<...> --clean gold=<...> --clean silver=<...> \
    --work F:/slink-work/tmp/g2-rand-r0/work --evidence F:/slink-work/evidence/g2-rand-r0
python <evidence>/probe/differential.py
python <evidence>/probe/diff2.py
```

The two probe scripts need the compiled `SlinkProbeGen2` class in `F:/slink-work/tmp/g2-rand-r0/probe`.

Not covered: wild held items, trainer held items, trainer names and trainer class names, shop
items and time-based encounters. None of these were run, so the write domain above does not
include them.

## Server pipeline (R1+R2, 2026-10-04)

- `server/upr_settings.py` family `gen2_gsc`: Gen 1 parity allowlist plus tutors, trades and BW EXP.
  Base stats, types, evolutions and movesets are refused, as for every family.
- **Lower-case names is OFF for Gen 2.** With random statics, the pinned fork sometimes crashes in
  `Gen2RomHandler.writePaddedPokemonName` (Game Corner prizes). It failed 2 of 40 Crystal and 5 of
  40 Gold runs at max settings, and 0 of 100 with statics alone. It fails closed, but players would
  see random failures. Re-enable after a fork patch.
- **Tutors on a Crystal + Gold/Silver pair** are refused by the existing "same applied settings"
  rule, because UPR drops tutors on G/S. Use tutors only for Crystal + Crystal pairs.
- `cartridges.py` follows the pureRGB order: apply the UPS (md5 verified), then randomize. Then
  `_check_content_gen2` (base stats, types, evolution graph and learnsets unchanged) and
  `upr_gen2_write_domain.check_output` (no write in UPS hunks, `SLink*` sections or the header).
- End-to-end runs through `cartridges.provision` succeeded for a Crystal pair and a Gold + Silver
  pair (evidence in F:/slink-work/tmp/g2r1). One-byte mutants of base stats, types, evolution,
  learnset, hunk, SLink section and header are all refused.
## Runtime admission (R3, 2026-10-04)

- `lua/gen2/entry.lua` admits an unknown sha1 only as `rand_overlay`. The title's overlay row must
  pass its G4, binding and receipt checks, its anchors must hold, and the companion hook bytes must
  be present: `Entry.COMPANION_PINS`, the DelayFrame and MainMenuJoypadLoop substitutions from the
  binding. A randomized clean cart is refused with the companion message.
- The server binds a Gen 2 hello to the contract's per-player `rom_sha1`
  (`rom_contract_by_sha1`). A `rand_overlay` hello in a run with no contract is refused: only the
  Manager makes randomized Gen 2 cartridges.
## ROM-derived data (R4, 2026-10-04)

- On a `rand_overlay` cart, `lua/gen2/signals.lua` keeps the vanilla site identity (map + script position) and reads the species (and level, and item for `givepoke`) from the ROM bytes at that site; the opcode and trailing bytes must still match the pack, else that one site is unselected. Roamers read the immediate of `ld a,xx; ld [wRoamMon<i>Species],a` in InitRoamMons. Clean/overlay behaviour is unchanged (the ROM is never read).
- The server decodes each player's provisioned ROM (`_contracted_rom`, bytes whose sha1 equals the contract pin; a client's JSON is never trusted) with `gen2_rom_scan` unpinned, and adopts it per player like Gen 3. Wild, tree, fishing, contest and static tables come from the ROM; until adopted, a randomized cart shows no encounter table.
- Checked against the UPR logs on real randomized ROMs: starters 4/4, statics/gifts 24/24, 24/24, 21/21, 21/21, roamers all match.
- Known limits: the legend area's display name still shows the slot's vanilla name (e.g. "Raikou"); `gift_link_area(acquisition="roamer")` still checks the vanilla species (nothing calls it).

### Overlay beacon: the Lua gate checks every overlay byte (was: known limit, review F-1)

Adversarial review cx-63dc558a (2026-10-04) showed that a clean cartridge with only the 7 bytes of the two companion hook pins patched was admitted as `rand_overlay`: the overlay changes 9839 bytes over 336 runs on Crystal (8944/335 Gold, 8947/333 Silver), and the anchors and pins covered 7 of them. R6 closes it. `tools/gen_gen2_beacon.py` writes `data/games/gen2_<title>/overlay/beacon.json`: the UPS hunks of `patch/dist/SLink-<Title>.ups` (cross-checked against a clean/overlay byte diff) and the sha256 of the overlay's bytes in those spans, pinned to the binding's `rom_sha1`, `base_sha1` and `ups_sha256` (`--check` goes red on drift). `lua/gen2/entry.lua` re-hashes those spans from the executing ROM with `Admission.sha256` and refuses on mismatch, or when the beacon does not name the overlay row's sha1; the hook pins stay as anchors. Because R0 proved UPR's write domain never touches an overlay-changed byte, a randomized companion cartridge keeps every beacon byte, so the Lua gate now proves overlay integrity on its own, not only that two hooks are wired in (proved on real UPR outputs for all three titles; the hash costs about 4 ms in lupa, against about 450 ms for the full-ROM sha1 the composition already takes). The server side is unchanged: the Manager's `upr_gen2_write_domain.check_output` and the contract `rom_sha1` still bind the hello. A rebuilt or restamped overlay needs its beacon regenerated with its binding. The ROM size floor (review F-2) and the additive sha1 pin (review F-4) are fixed.
