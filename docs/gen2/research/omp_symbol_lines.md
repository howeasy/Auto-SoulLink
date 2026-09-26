# gen2-A2 — JSON-only Gen 2 symbols pinned to source lines

Mechanical lookup only. Nothing here decides anything; the coordinator reads the lines.

**Clones (read-only).**
- pokecrystal `7a7881d0d62e0ddbd82dcf10e7116807487ac651` — `C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-gen2-planning-kickoff-a18801\17c55ba3-97ae-4ed8-ba47-396926dd84c9\scratchpad\pret_head\pokecrystal`
- pokegold   `656583c939d30f920a316177311a502dd222b57c` — `C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-gen2-planning-kickoff-a18801\17c55ba3-97ae-4ed8-ba47-396926dd84c9\scratchpad\pret_head\pokegold`
- `data/pret_syms.json` (worktree) keys `pokecrystal`, `pokegold`; both clones clean
  (`git status --porcelain` empty).

**Method.** `^<symbol>::` line-start match in `ram/wram.asm` and `ram/sram.asm` (RGBDS
`.sym` files are not consulted; the clones contain no such file for these repos). On a
miss, a repo-wide word-boundary scan of every `*.asm` was run and its result is stated.
SECTION = the nearest preceding `SECTION "..."` line. pret_syms.json values are the
committed JSON, not the source.

## Symbol declaration lines

| symbol | pokecrystal | pokegold | PC SECTION | PG SECTION | json PC | json PG |
|---|---|---|---|---|---|---|
| `wNumBalls` | ram/wram.asm:3117 | ram/wram.asm:2515 | Enemy Party | Game Data | 0xD8D7 | 0xD5FC |
| `wBalls` | ram/wram.asm:3118 | ram/wram.asm:2516 | Enemy Party | Game Data | 0xD8D8 | 0xD5FD |
| `wNumItems` | ram/wram.asm:3111 | ram/wram.asm:2509 | Enemy Party | Game Data | 0xD892 | 0xD5B7 |
| `wItems` | ram/wram.asm:3112 | ram/wram.asm:2510 | Enemy Party | Game Data | 0xD893 | 0xD5B8 |
| `wNumKeyItems` | ram/wram.asm:3114 | ram/wram.asm:2512 | Enemy Party | Game Data | 0xD8BC | 0xD5E1 |
| `wKeyItems` | ram/wram.asm:3115 | ram/wram.asm:2513 | Enemy Party | Game Data | 0xD8BD | 0xD5E2 |
| `wTMsHMs` | ram/wram.asm:3109 | ram/wram.asm:2507 | Enemy Party | Game Data | 0xD859 | 0xD57E |
| `wPlayerID` | ram/wram.asm:2994 | ram/wram.asm:2399 | Enemy Party | Game Data | 0xD47B | 0xD1A1 |
| `wPlayerName` | ram/wram.asm:2996 | ram/wram.asm:2401 | Enemy Party | Game Data | 0xD47D | 0xD1A3 |
| `wJohtoBadges` | ram/wram.asm:3106 | ram/wram.asm:2504 | Enemy Party | Game Data | 0xD857 | 0xD57C |
| `wKantoBadges` | ram/wram.asm:3107 | ram/wram.asm:2505 | Enemy Party | Game Data | 0xD858 | 0xD57D |
| `wStatusFlags` | ram/wram.asm:3071 | ram/wram.asm:2487 | Enemy Party | Game Data | 0xD84C | 0xD571 |
| `wStatusFlags2` | ram/wram.asm:3082 | ram/wram.asm:2489 | Enemy Party | Game Data | 0xD84D | 0xD572 |
| `wScriptRunning` | ram/wram.asm:2924 | ram/wram.asm:2311 | Enemy Party | WRAM 1 | 0xD438 | 0xD15F |
| `wScriptFlags` | ram/wram.asm:2910 | ram/wram.asm:2297 | Enemy Party | WRAM 1 | 0xD434 | 0xD15B |
| `wScriptMode` | ram/wram.asm:2923 | ram/wram.asm:2310 | Enemy Party | WRAM 1 | 0xD437 | 0xD15E |
| `wMapEventStatus` | ram/wram.asm:2908 | ram/wram.asm:2295 | Enemy Party | WRAM 1 | 0xD433 | 0xD15A |
| `wJoypadDisable` | ram/wram.asm:1839 | ram/wram.asm:2619 | Video | Game Data | 0xCFBE | 0xD8BA |
| `wGameTimerPause` | NOT FOUND | NOT FOUND | - | - | - | - |
| `wOtherTrainerClass` | ram/wram.asm:2728 | ram/wram.asm:2194 | More WRAM 1 | WRAM 1 | 0xD22F | 0xD118 |
| `wOtherTrainerID` | ram/wram.asm:2736 | ram/wram.asm:2204 | More WRAM 1 | WRAM 1 | 0xD231 | 0xD11B |
| `wBattleMode` | ram/wram.asm:2720 | ram/wram.asm:2186 | More WRAM 1 | WRAM 1 | 0xD22D | 0xD116 |
| `wBattleType` | ram/wram.asm:2734 | ram/wram.asm:2200 | More WRAM 1 | WRAM 1 | 0xD230 | 0xD119 |
| `wBattleResult` | ram/wram.asm:2394 | ram/wram.asm:1875 | More WRAM 1 | Video | 0xD0EE | 0xCFE9 |
| `wEnemyMon` | ram/wram.asm:2713 | ram/wram.asm:2179 | More WRAM 1 | WRAM 1 | 0xD206 | 0xD0EF |
| `wEnemyMonSpecies` | macro-emitted: macros/ram.asm:79 (MACRO battle_struct) <- ram/wram.asm:2713 | macro-emitted: macros/ram.asm:76 (MACRO battle_struct) <- ram/wram.asm:2179 | More WRAM 1 | WRAM 1 | 0xD206 | 0xD0EF |
| `wCurPartyMon` | ram/wram.asm:2431 | ram/wram.asm:1917 | More WRAM 1 | WRAM 1 | 0xD109 | 0xD005 |
| `wCurBattleMon` | ram/wram.asm:2343 | ram/wram.asm:1818 | More WRAM 1 | Video | 0xD0D4 | 0xCFC6 |
| `wSavedAtLeastOnce` | ram/wram.asm:3002 | ram/wram.asm:2407 | Enemy Party | Game Data | 0xD4B4 | 0xD1DA |
| `wMapGroup` | ram/wram.asm:3400 | ram/wram.asm:2744 | Enemy Party | Game Data | 0xDCB5 | 0xDA00 |
| `wMapNumber` | ram/wram.asm:3401 | ram/wram.asm:2745 | Enemy Party | Game Data | 0xDCB6 | 0xDA01 |
| `wPlayerStatLevels` | ram/wram.asm:454 | ram/wram.asm:942 | Tilemap | Unused Map Buffer | 0xC6CC | 0xCBAA |
| `wEnemyStatLevels` | ram/wram.asm:464 | ram/wram.asm:952 | Tilemap | Unused Map Buffer | 0xC6D4 | 0xCBB2 |
| `wMusicID` | ram/wram.asm:51 | ram/wram.asm:43 | Audio RAM | Audio RAM | 0xC29D | 0xC19D |
| `wMapMusic` | ram/wram.asm:107 | ram/wram.asm:99 | Audio RAM | Audio RAM | 0xC2C0 | 0xC1C0 |
| `wCryTracks` | ram/wram.asm:95 | ram/wram.asm:87 | Audio RAM | Audio RAM | 0xC2BD | 0xC1BD |
| `wNewSoundID` | NOT FOUND | NOT FOUND | - | - | - | - |
| `wChannelSoundIDs` | NOT FOUND | NOT FOUND | - | - | - | - |
| `sBox` | ram/sram.asm:108 | ram/sram.asm:109 | Active Box | Active Box | 0xAD10 | 0xAD6C |
| `sBoxCount` | macro-emitted: macros/ram.asm:102 (MACRO box) <- ram/sram.asm:108 'sBox:: box sBox' | macro-emitted: macros/ram.asm:99 (MACRO curbox) <- ram/sram.asm:109 'sBox:: curbox sBox' | Active Box | Active Box | 0xAD10 | 0xAD6C |
| `sBox1` | macro-emitted: ram/sram.asm:181 (in MACRO boxes), invoked ram/sram.asm:188/193 | macro-emitted: ram/sram.asm:148 (in MACRO boxes), invoked ram/sram.asm:155/160 | Boxes 1-7 | Boxes 1-7 | 0xA000 | 0xA000 |
| `sBox7` | macro-emitted: ram/sram.asm:181 (in MACRO boxes), invoked ram/sram.asm:188/193 | macro-emitted: ram/sram.asm:148 (in MACRO boxes), invoked ram/sram.asm:155/160 | Boxes 1-7 | Boxes 1-7 | 0xB9E0 | 0xB9E0 |
| `sBox8` | macro-emitted: ram/sram.asm:181 (in MACRO boxes), invoked ram/sram.asm:188/193 | macro-emitted: ram/sram.asm:148 (in MACRO boxes), invoked ram/sram.asm:155/160 | Boxes 8-14 | Boxes 8-14 | 0xA000 | 0xA000 |
| `sBox14` | macro-emitted: ram/sram.asm:181 (in MACRO boxes), invoked ram/sram.asm:188/193 | macro-emitted: ram/sram.asm:148 (in MACRO boxes), invoked ram/sram.asm:155/160 | Boxes 8-14 | Boxes 8-14 | 0xB9E0 | 0xB9E0 |
| `sPlayerData` | ram/sram.asm:94 | ram/sram.asm:94 | Save | Save | 0xA009 | 0xA009 |
| `sCurMapData` | ram/sram.asm:95 | ram/sram.asm:98 | Save | Save | 0xA833 | 0xA856 |
| `sPokemonData` | ram/sram.asm:96 | ram/sram.asm:99 | Save | Save | 0xA865 | 0xA88A |
| `sGameData` | ram/sram.asm:93 | ram/sram.asm:93 | Save | Save | 0xA009 | 0xA009 |
| `sGameDataEnd` | ram/sram.asm:97 | ram/sram.asm:100 | Save | Save | 0xAB83 | 0xAD69 |
| `sChecksum` | ram/sram.asm:101 | ram/sram.asm:102 | Save | Save | 0xAD0D | 0xAD69 |
| `sBackupGameData` | ram/sram.asm:64 | NOT FOUND | Backup Save | - | 0xB209 | - |
| `sBackupChecksum` | ram/sram.asm:72 | ram/sram.asm:172 | Backup Save | Backup Save 3 | 0xBF0D | 0xBE6D |
| `sCheckValue1` | ram/sram.asm:91 | ram/sram.asm:91 | Save | Save | 0xA008 | 0xA008 |
| `sCheckValue2` | ram/sram.asm:103 | ram/sram.asm:104 | Save | Save | 0xAD0F | 0xAD6B |
| `sBackupCheckValue1` | ram/sram.asm:62 | ram/sram.asm:170 | Backup Save | Backup Save 3 | 0xB208 | 0xBE38 |
| `sBackupCheckValue2` | ram/sram.asm:74 | ram/sram.asm:173 | Backup Save | Backup Save 3 | 0xBF0F | 0xBE6F |
| `sOptions` | ram/sram.asm:89 | ram/sram.asm:89 | Save | Save | 0xA000 | 0xA000 |
| `sBackupOptions` | ram/sram.asm:60 | ram/sram.asm:169 | Backup Save | Backup Save 3 | 0xB200 | 0xBE30 |
| `sPartyCount` | NOT FOUND | NOT FOUND | - | - | - | - |
| `sPartyMons` | NOT FOUND | NOT FOUND | - | - | - | - |

### The six incomplete rows

| symbol | verdict | evidence |
|---|---|---|
| `wGameTimerPause` | NOT FOUND in both (name differs) | repo-wide word-boundary scan: zero hits in either clone. Near miss: `wGameTimerPaused::` at pokecrystal `ram/wram.asm:1832` |
| `wNewSoundID` | NOT FOUND in both | zero hits in either clone (this is the *pokered* name from the Gen 1 notes; Gen 2 has no such label) |
| `wChannelSoundIDs` | NOT FOUND in both | zero hits in either clone; neither does the singular `ChannelSoundID` |
| `sBackupGameData` | PC found, PG NOT FOUND | `ram/sram.asm:64` (SECTION "Backup Save", SRAM) in pokecrystal; zero hits anywhere in pokegold. Gold/Silver's backup block is split: `SECTION "Backup Save 1", SRAM` holds `sBackupPlayerData3` / `sBackupPokemonData` / `sBackupPlayerData1` (pokegold `ram/sram.asm:65-69`) |
| `sPartyCount` | NOT FOUND in both | zero hits in either clone — party count lives in WRAM (`wPartyCount`), not SRAM |
| `sPartyMons` | NOT FOUND in both | zero hits in either clone |

### Symbols that exist but are emitted by a macro, not written literally

These are why a literal `^<symbol>::` grep returns nothing. pokecrystal:

```asm
macros/ram.asm:79   MACRO battle_struct
macros/ram.asm:80   \1Species::   db
macros/ram.asm:102  MACRO box
macros/ram.asm:103  \1Count::   db
macros/ram.asm:104  \1Species:: ds MONS_PER_BOX + 1
ram/sram.asm:108    sBox:: box sBox
ram/sram.asm:178    MACRO boxes
ram/sram.asm:181    	sBox{d:box_n}:: box sBox{d:box_n}
ram/sram.asm:188    boxes 7      ; SECTION "Boxes 1-7", SRAM
ram/sram.asm:193    boxes 7      ; SECTION "Boxes 8-14", SRAM
```

pokegold differs in shape but not in effect — the active box goes through `curbox` and
`box` is `curbox` plus 2 bytes of padding:

```asm
macros/ram.asm:76   MACRO battle_struct
macros/ram.asm:99   MACRO curbox
macros/ram.asm:100  \1Count::   db
macros/ram.asm:121  MACRO box
macros/ram.asm:122  	curbox \1
macros/ram.asm:123  	ds 2 ; padding
ram/sram.asm:109    sBox:: curbox sBox
ram/sram.asm:145    MACRO boxes
ram/sram.asm:148    	sBox{d:box_n}:: box sBox{d:box_n}
ram/sram.asm:155    boxes 7
ram/sram.asm:160    boxes 7
```

Expansion sites: `wEnemyMon:: battle_struct wEnemyMon` at pokecrystal `ram/wram.asm:2713`
and pokegold `ram/wram.asm:2179`; `sBox` at pokecrystal `ram/sram.asm:108` / pokegold
`ram/sram.asm:109`.

Consistency check the two repos agree on: `sBox` and `sBoxCount` carry the *same* address
in `data/pret_syms.json` (pokecrystal 0xAD10, pokegold 0xAD6C), i.e. `Count` sits at box
offset 0 in both. `sBox1` = 0xA000 and `sBox14` = 0xB9E0 in both.

## Routine label lines

| file | label | pokecrystal | pokegold |
|---|---|---|---|
| `engine/pokemon/move_mon.asm` | `TryAddMonToParty` | engine/pokemon/move_mon.asm:3 | engine/pokemon/move_mon.asm:3 |
| `engine/pokemon/move_mon.asm` | `SendMonIntoBox` | engine/pokemon/move_mon.asm:942 | engine/pokemon/move_mon.asm:942 |
| `engine/pokemon/move_mon.asm` | `GiveEgg` | engine/pokemon/move_mon.asm:1121 | engine/pokemon/move_mon.asm:1121 |
| `engine/pokemon/move_mon.asm` | `GivePoke` | engine/pokemon/move_mon.asm:1619 | engine/pokemon/move_mon.asm:1632 |
| `engine/pokemon/move_mon.asm` | `RetrieveBreedmon` | engine/pokemon/move_mon.asm:805 | engine/pokemon/move_mon.asm:805 |
| `engine/pokemon/move_mon.asm` | `DepositBreedmon` | engine/pokemon/move_mon.asm:926 | engine/pokemon/move_mon.asm:926 |
| `engine/battle/core.asm` | `HandlePlayerMonFaint` | engine/battle/core.asm:2607 | engine/battle/core.asm:2506 |
| `engine/battle/core.asm` | `UpdateFaintedPlayerMon` | engine/battle/core.asm:2656 | engine/battle/core.asm:2551 |
| `engine/battle/core.asm` | `LostBattle` | engine/battle/core.asm:2915 | engine/battle/core.asm:2763 |
| `engine/battle/core.asm` | `WinTrainerBattle` | engine/battle/core.asm:2351 | engine/battle/core.asm:2292 |
| `engine/battle/core.asm` | `FaintYourPokemon` | engine/battle/core.asm:2254 | engine/battle/core.asm:2195 |
| `engine/battle/core.asm` | `CheckPlayerPartyForFitMon` | engine/battle/core.asm:3633 | engine/battle/core.asm:3422 |
| `engine/battle/core.asm` | `ExitBattle` | engine/battle/core.asm:8268 | engine/battle/core.asm:7965 |
| `engine/battle/core.asm` | `InitEnemyWildmon` | engine/battle/core.asm:8183 | engine/battle/core.asm:7881 |
| `engine/battle/core.asm` | `InitEnemyTrainer` | engine/battle/core.asm:8128 | engine/battle/core.asm:7827 |

All 15 labels exist in both repos. Only one line number differs by more than the
repo-wide Crystal-vs-Gold shift for its file: `GivePoke` at pokecrystal
`engine/pokemon/move_mon.asm:1619` vs pokegold `:1632` (+13), while `TryAddMonToParty`,
`SendMonIntoBox`, `GiveEgg`, `RetrieveBreedmon` and `DepositBreedmon` are line-identical
in the two clones.

## pokemon_constants diff

**Verdict: identical species const list — yes, in order and in value.**

- pokecrystal `constants/pokemon_constants.asm`: 313 lines; pokegold: 308 lines; the raw
  bytes are NOT identical.
- 278 `const <NAME>` species lines in each, **same names in the same order** (compared as
  ordered lists). Stripping `;`-comments and blank lines leaves 284 lines each, byte-for-
  byte identical.
- The first differing raw line is line 16: pokecrystal `; - AnimationPointers (see
  gfx/pokemon/anim_pointers.asm)`, pokegold `	const_def 1`. The entire difference is the
  header comment block: pokecrystal lists 6 extra "see gfx/..." bullet lines
  (AnimationPointers, AnimationIdlePointers, BitmasksPointers, FramesPointers,
  EZChat_SortedPokemon) and therefore starts its first `const_def 1` at line 21 vs
  pokegold's line 16. Second `const_def 1` at pokecrystal:286 / pokegold:281.

## ElmsLab setmapscene context

`maps/ElmsLab.asm` exists in both clones. One hit each for
`setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP`: pokecrystal line 277, pokegold line
236. Nearest preceding label in both: `ElmDirectionsScript:` (pokecrystal:251,
pokegold:211). Window = 40 lines before the hit through the hit, verbatim:

### pokecrystal `maps/ElmsLab.asm:238-277`

```asm
 238| 	waitsfx
 239| 	promptbutton
 240| 	givepoke CHIKORITA, 5, BERRY
 241| 	closetext
 242| 	applymovement PLAYER, AfterChikoritaMovement
 243| 	sjump ElmDirectionsScript
 244| 
 245| DidntChooseStarterScript:
 246| 	writetext DidntChooseStarterText
 247| 	waitbutton
 248| 	closetext
 249| 	end
 250| 
 251| ElmDirectionsScript:
 252| 	turnobject PLAYER, UP
 253| 	opentext
 254| 	writetext ElmDirectionsText1
 255| 	waitbutton
 256| 	closetext
 257| 	addcellnum PHONE_ELM
 258| 	opentext
 259| 	writetext GotElmsNumberText
 260| 	playsound SFX_REGISTER_PHONE_NUMBER
 261| 	waitsfx
 262| 	waitbutton
 263| 	closetext
 264| 	turnobject ELMSLAB_ELM, LEFT
 265| 	opentext
 266| 	writetext ElmDirectionsText2
 267| 	waitbutton
 268| 	closetext
 269| 	turnobject ELMSLAB_ELM, DOWN
 270| 	opentext
 271| 	writetext ElmDirectionsText3
 272| 	waitbutton
 273| 	closetext
 274| 	setevent EVENT_GOT_A_POKEMON_FROM_ELM
 275| 	setevent EVENT_RIVAL_CHERRYGROVE_CITY
 276| 	setscene SCENE_ELMSLAB_AIDE_GIVES_POTION
 277| 	setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP
```

### pokegold `maps/ElmsLab.asm:197-236`

```asm
 197| 	playsound SFX_CAUGHT_MON
 198| 	waitsfx
 199| 	promptbutton
 200| 	givepoke CHIKORITA, 5, BERRY
 201| 	closetext
 202| 	applymovement PLAYER, AfterChikoritaMovement
 203| 	sjump ElmDirectionsScript
 204| 
 205| DidntChooseStarterScript:
 206| 	writetext DidntChooseStarterText
 207| 	waitbutton
 208| 	closetext
 209| 	end
 210| 
 211| ElmDirectionsScript:
 212| 	turnobject PLAYER, UP
 213| 	opentext
 214| 	writetext ElmDirectionsText1
 215| 	waitbutton
 216| 	closetext
 217| 	turnobject ELMSLAB_ELM, LEFT
 218| 	opentext
 219| 	writetext ElmDirectionsText2
 220| 	waitbutton
 221| 	closetext
 222| 	turnobject ELMSLAB_ELM, DOWN
 223| 	opentext
 224| 	writetext ElmDirectionsText3
 225| 	promptbutton
 226| 	waitsfx
 227| 	addcellnum PHONE_ELM
 228| 	writetext GotElmsNumberText
 229| 	playsound SFX_REGISTER_PHONE_NUMBER
 230| 	waitsfx
 231| 	waitbutton
 232| 	closetext
 233| 	setevent EVENT_GOT_A_POKEMON_FROM_ELM
 234| 	setevent EVENT_RIVAL_CHERRYGROVE_CITY
 235| 	setscene SCENE_ELMSLAB_AIDE_GIVES_POTION
 236| 	setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP
```

What the window shows (stated, not judged): in both repos the `setmapscene` is the last
line of `ElmDirectionsScript`, which is reached by `sjump ElmDirectionsScript`
(pokecrystal:243, pokegold:203) at the end of the *starter-choice* scripts — the same
block gives the player the mon (`givepoke CHIKORITA, 5, BERRY` immediately above at
pokecrystal:240 / pokegold:200), then sets `EVENT_GOT_A_POKEMON_FROM_ELM` and
`EVENT_RIVAL_CHERRYGROVE_CITY` and `setscene SCENE_ELMSLAB_AIDE_GIVES_POTION` one line
before the `setmapscene`. The two clones order the phone-number beats differently
(pokecrystal adds `addcellnum PHONE_ELM` before the text at :257; pokegold does it at
:227, after `waitsfx`), but the three terminal commands are the same three lines in both.

## Notes on the method

- `wGameTimerPause`, `wNewSoundID`, `wChannelSoundIDs`, `sPartyCount`, `sPartyMons` were
  searched with a word-boundary `\b` pattern over every `*.asm` in the clone, not just
  the two RAM files, before being called NOT FOUND.
- SECTION labels are the nearest preceding `SECTION` line, which is what the brief asks
  for; note that these do not always describe the contents — in pokecrystal the bag
  (`wNumBalls`, `wBalls`) sits inside `SECTION "Enemy Party", WRAMX` (section at
  `ram/wram.asm:2821`, bag at `:3117`), while pokegold files the same data under
  `SECTION "Game Data", WRAMX` (`ram/wram.asm:2394`, bag at `:2515`).
- The clones ship no committed `.sym` files, so the JSON values could not be re-derived
  here; they are reported as committed, not as re-computed.

DONE gen2-A2: 54/60 symbols found, 6 not found
