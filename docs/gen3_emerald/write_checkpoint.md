# Emerald write checkpoint (E1-CHECKPOINT)

`data/games/gen3_emerald/write_checkpoint.json` is vanilla Emerald's overworld and battle write
checkpoint. It uses the FR/LG shape from `docs/gen3_write_checkpoint.md`. Every value is a SOURCE
fact: an address from `data/gen3/pret/pokeemerald.sym`, a layout from pret/pokeemerald
`c65e93f2`, or ROM bytes sliced from the admitted BPEE dump
(`f3ae088181bf583e55daf962a92bb46f4f1d07b7`). Nothing here has been observed on hardware yet.
The PHYSICAL half (census, positives, negative controls) belongs to E2.

`tools/gen_gen3_write_checkpoint.py` generates the file. Emerald is listed in `UNADMITTED_PACKS`,
not in `PACKS`. That means `--check` regenerates it, but the admitted-pack test matrix in
`tests/unit/test_gen3_write_checkpoint.py` does not cover it. Emerald stays unadmitted until EG4
(ruling 24). The FR/LG and RR packs regenerate byte-identical.

```
python tools/gen_gen3_write_checkpoint.py            # rewrites frlg, rr and emerald
python tools/gen_gen3_write_checkpoint.py --check
pytest tests/unit/test_gen3_emerald_checkpoint.py
```

## 1. The player-controller span without a .map

pret does not publish `pokeemerald.map` (see `pokeemerald_provenance.json` `"map"`). When the
`.map` next to a `.sym` is missing, `player_span()` falls back to `sym_text_span()`. FR/LG still
read their `.map`.

- **Membership.** The function names come from `src/battle_controller_player.c`, read with
  `git show <source_commit>:…` from the pret checkout. The commit is the one pinned in the
  provenance file. A definition is a column-0 line that ends in `)` and is followed by a `{` line.
  This yields 123 names, all distinct.
- **Proof.** Exactly one run of consecutive `.sym` symbols must consist of exactly those names.
  Every gap inside the run must be alignment padding (under 4 bytes; there are 13 gaps of 2).
  The run must start on a `.gcc2_compiled.` object marker. The next symbol must be the next
  marker, within alignment, and no marker may fall inside the run.
- **Result.** The span is `[0x08057458, 0x0805D116)`.
  - The predecessor, `BattlePalace_TryEscapeStatus`, ends exactly at `0x08057458`.
  - The next object, `AllocateBattleSpritesData`, starts at `0x0805D118`, and a marker sits there.
  - Both bounds are recorded in the battle clause source and the hand-off source.
- **Duplicate spellings.** Emerald has 2 × `HandleInputChooseAction` and 3 ×
  `HandleChooseActionAfterDma3`. `parse_sym` keeps the first spelling, which is the player's
  (`0x08057588` and `0x0805C004`). The span check in `build_title` is the proof. The non-player
  spellings all fall outside the span: Safari `0x081593D8` and `0x08159A54`, Wally `0x0816A430`.
  A test swaps in the Safari address and the build stops.
- **Negative tests.**
  - Dropping the last function breaks the end-marker check.
  - Dropping a middle function splits the run.
  - Adding the next object's first function puts a marker inside the span.

## 2. Renames and per-title rows

| FR spelling | Emerald | Address | Source |
|---|---|---|---|
| `sSaveDialogCB` | `sSaveDialogCallback` | `0x0203761C` (EWRAM; FR's is IWRAM) | `src/start_menu.c:88` |
| `RunSaveDialogCB` | `RunSaveCallback` | `0x0809FF4C` | `src/start_menu.c:884-894` |

`title_syms()` applies `RENAMES` straight after `parse_sym`. Two conditions are fatal:

- the FR spelling is itself present, which means the rename is stale;
- the target is missing.

The witness is emitted under the Emerald name.

The `frame_control` anchor is the whole `CallCallbacks` body (`0x0800051C`, 0x24 bytes). FR's
slice at +0x0A is the `bl RunHelpSystemCallback`, and Emerald's `CallCallbacks`
(`src/main.c:188-195`) has neither a help-system gate nor a save-failed gate. This matches the
+0 entry that `engine_sites.md` captures.

## 3. Field offsets, re-derived from pokeemerald headers

| Use | Offset | pret pokeemerald c65e93f2 |
|---|---|---|
| `gMain.callback1` / `callback2` | +0x000 / +0x004 | `include/main.h:10-11` |
| `gMain.inBattle` | +0x439 bit 1 (mask 0x02) | `include/main.h:38-40` (bit 2 is Emerald's `anyLinkBattlerHasFrontierPass`, not read) |
| `gPaletteFade.active` | +7 bit 7 | `include/palette.h:35-53` (u32, then u8:6, u16:5, u16:5, u16:15, `active:1` = bit 31) |
| `struct Task` | func +0, isActive +4, size 0x28, 16 tasks | `include/task.h:8,13-21` |
| script lock / context | `sLockFieldControls`, `sGlobalScriptContextStatus`, SHUTDOWN = 2 | `src/script.c:17-28` |
| `sLinkOpen` | set `InitLink` :354, cleared `CloseLink` :405, gates `gLinkCallback` :492-503 | `src/link.c:112` |
| `gReceivedRemoteLinkPlayers` | set :522, cleared :391,:402 | `src/link.c:93` |
| `gSoftResetDisabled` / `gLinkTransferringData` | whole-byte flags | `src/main.c:66`, `include/main.h:50,53`; save `src/save.c:985-1047` |
| `battle_engine_loaded` | `gBattleMons` +0x2C = `BattlePokemon.maxHP` | `include/pokemon.h:285` (FR's field and offset; the card's "+44 HP" means maxHP) |
| `battle_not_link` | `BATTLE_TYPE_LINK` = (1 << 1) | `include/constants/battle.h:60` |
| hand-off head: perish status | `gStatuses3` `STATUS3_PERISH_SONG` = 0x20 | `include/constants/battle.h:162` |
| hand-off head: perish timer | `gDisableStructs` +0x0F, keep 0xF0 | `include/battle.h:70-85` (`perishSongTimer:4` at :84) |
| hand-off head: no-op action | `gChosenActionByBattler` = 13 | `include/battle.h:41` |
| sound | SoundInfo +0x24 head; MusicPlayerInfo +0x2C tracks, +0x34 ident, +0x3C next; track +0x0F/+0x13/+0x19/+0x20/+0x40 | `include/gba/m4a_internal.h:185-221,272-315,327-350` (same layout as FR; the diffs are the `ALIGNED(4)` pcmBuffer tail and field names) |

The hand-off head addresses come from `data/games/gen3_emerald/profile.json` (the E1-PACK
lease), and they equal the `.sym`: `0x020242AC`, `0x020242BC`+0x0F, and `0x0202421C`.

C4-BW holds as it does in FR:

- `STATE_BEFORE_ACTION_CHOSEN` emits CHOOSE_ACTION (`src/battle_main.c:4143-4168`).
- `MarkBattlerForControllerExec` sets the exec bit (`src/battle_util.c:856-862`).
- Only `PlayerBufferExecCompleted` clears it (`src/battle_controller_player.c:200-214`).
- `HandleChooseActionAfterDma3` parks the slot on `HandleInputChooseAction` (:2565-2571).

The `PlayerBufferExecCompleted` ROM prefix is byte-equal to the FR/LG pret build. Its pool holds
`0x03005D60` and `0x08057505`.

## 4. The task allow-list

| Task | Address | Why it is idle-overworld |
|---|---|---|
| `Task_RunPerStepCallback` | `0x0809D88C` | `SetUpFieldTasks`, `src/field_tasks.c:181-194` |
| `Task_RunTimeBasedEvents` | `0x0809D908` | same (`:150-177`); see finding F2 |
| `Task_MuddySlope` | `0x0809E638` | **Emerald-only**, same `SetUpFieldTasks`; its reach is the map grid and BG tilemap only (`:880-957`) |
| `Task_WeatherMain` | `0x080AB1B0` | `src/field_weather.c:154-181,216-227` |
| `Task_InitUnionRoom`, `Task_SearchForChildOrParent`, `Task_UnionRoomListen` | `0x0801697C`, `0x08016CA0`, `0x0800EB44` | Center 1F `CableClub_OnResume` → `special InitUnionRoom` (`data/scripts/cable_club.inc:1226-1228`); `src/union_room.c:3294-3377,3465-3497`; `src/link_rfu_2.c:510-565,2640-2649` |

`Task_RunPokemonLeagueLightingEffect` is **excluded**. It is absent from Emerald (0 hits in the
`.sym`, 0 in `src/`), and `tasks.excluded_tasks` records the reason. The allow-list loop now fails
with a named `SystemExit` when a listed task is missing from the `.sym`, where it used to raise a
`KeyError`.

## 5. Emerald forbidden-state inventory

This is `tasks.forbidden_inventory`: 47 names. Every name is checked against the `.sym`, and a
missing one stops the build. The checkpoint is already fail-closed on these states:

- every `CB2_*` fails `callback2` (it is not `CB2_Overworld`);
- every `Task_*` fails the `task` clause (it is off the allow-list);
- the link states also fail `link_callback` or `link_players_received`.

The inventory is documentation and the target list for E2's negative controls.

- **Contests:** `CB2_StartContest` 0x080D7B24, `CB2_ContestMain` 0x080D823C, `Task_StartContest`
  0x080F83E0, and all 30 `Task_LinkContest_*` (RS and Em variants).
- **Secret bases:** `Task_EnterSecretBase` 0x080E8FD0, `Task_WarpOutOfSecretBase` 0x080E96A4.
- **Record mixing:** `Task_DoRecordMixing` 0x080E7FF8, `Task_RecordMixing_Main` 0x080E715C.
- **Berry Blender:** `CB2_LoadBerryBlender` 0x0807FAC8, `CB2_StartBlenderLink` 0x08080018,
  `CB2_StartBlenderLocal` 0x080808D4.
- **Frontier, Pyramid and Trainer Hill:** `CB2_FrontierPass` 0x080C5438,
  `Task_BattlePyramidChooseMonHeldItems` 0x081B9640, `Task_TrainerHillWaitForPaletteFade`
  0x0813C5BC.
- **Multi-partner battle:** `CB2_HandleStartMultiPartnerBattle` 0x08037458,
  `CB2_PreInitMultiBattle` 0x08037ADC, `CB2_HandleStartMultiBattle` 0x08037DF4.
- **Union Room battle:** `CB2_UnionRoomBattle` 0x0801AC54.
- **Berry Crush and Dodrio Berry Picking** are not listed by name. `StartBerryCrush`
  (`src/berry_crush.c:995-1001`) exits unless `gReceivedRemoteLinkPlayers` is set and the link is
  wireless, and its `MainCB`/`MainTask` are generic static names. Those states are refused by
  `link_players_received`, `callback2` and the task clause.

No name from the brief is missing.

## 6. The parked-CPU clause: census (E2, PHYSICAL)

AgbMain ends every frame in `WaitForVBlank` (`src/main.c:167` for the call, `:410-416` for the
body). The range is that symbol's body, `0x080008AC..0x080008DB`, in System mode with Thumb.

The E2 census (`docs/gen3_emerald/probes/census_emerald_overworld_2026-09-25.txt`) sampled 1800 idle
Oldale frame ends with no input:
- 1678 non-IRQ frame ends fell inside `0x080008C8..0x080008D0`, System mode, Thumb. The modal PC,
  `0x080008C8` (801 frames), is `observed_pc`. It sits at WaitForVBlank+0x1C, the same offset as FR/LG.
- 122 ended in the BIOS IRQ vector. The clause rejects those by design, as on FR/LG.

Every sampled frame carried the four always-on field tasks, including `Task_MuddySlope`, which
physically confirms EG1 decision 4. The first 111 frames after CONTINUE also carried
`Task_MapNamePopUpWindow` (0x080D487D), which is not allowed, so the checkpoint is fail-closed while
the map-name popup shows (an E2 checkpoint-card question).

## 7. Findings for E2 and the coordinator

- **F1: `Task_MuddySlope` is admitted.** PLAN §1 lists only the league-lighting drop.
  `SetUpFieldTasks` also creates `Task_MuddySlope` on every field load. Without it, every Emerald
  field frame would refuse on "unknown active task". Its reach is write-free for party, storage
  and save (§4). Revert by removing `EMERALD_ONLY_TASKS` if EG1 disagrees.
- **F2: Emerald's `Task_RunTimeBasedEvents` writes the party.** It is not FR's no-op.
  `Task_RunTimeBasedEvents` → `RunTimeBasedEvents` (`src/field_tasks.c:150-177`) calls
  `DoTimeBasedEvents` once per `gMain.vblankCounter1 & (1 << 12)` window, and only when
  `!ArePlayerFieldControlsLocked()`. `DoTimeBasedEvents` (`src/clock.c:26-34`) reaches two writers:
  - `UpdatePerDay` (`src/clock.c:36-57`), once per RTC day rollover (`VAR_DAYS` moves, the
    `*days <= localTime->days` guard): daily flags cleared, Dewford trends, TV shows, weather,
    **party Pokérus** (`UpdatePartyPokerusTime`, the only party write, through `SetMonData`),
    Mirage RNG, Prof. Birch's state, both Frontier NPCs, the shoal item flag, the lottery number,
    and `VAR_DAYS` itself.
  - `UpdatePerMinute` (`src/clock.c:59-74`), on any whole-minute change: `BerryTreeTimeUpdate` and
    `gSaveBlock2Ptr->lastBerryTreeUpdate`.

  All of it is synchronous and in-RAM inside that one task step: `clock.c` issues no save or flash
  call of its own (its only `Save*` tokens are `gSaveBlock2Ptr`), and the game flushes the save
  block later, on its own path. The parked frame-end checkpoint therefore never observes one of
  these writes in progress, and the checkpoint's model still holds. What a static read cannot settle
  is the sequencing: a host party write can be followed by a game-side Pokérus update on the next
  day rollover. **E2 decides whether a day-rollover frame needs a guard**, and the signal for that
  decision is `VAR_DAYS` changing, not a CPU census.
- **F3: the Union Room background reach is carried by structure.** The Emerald task bodies name no
  party or save routine, and every step out creates an off-list task (`Task_PlayerExchange`/`Chat`,
  `link_rfu_2.c:540-560`). The full callee re-audit that FR's C4-UR did is †UNVERIFIED for
  Emerald. E2's Oldale Center positive is the physical check.
- **F4:** the card's "gBattleMons +44 HP" is `maxHP` (+0x2C). `hp` is +0x28. The FR clause reads
  the same field.
- **F5:** the RR companion ROM (`patch/build/slink_RR.gba`) is not in this worktree. The RR
  byte-identity run borrowed the sha1-pinned copy from `gen3-lane-clean`, and the new test skips
  RR when the ROM is absent.
