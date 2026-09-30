# Engine sites per Soul Link event (HGSS)

Source: pokeheartgold @ad7a3afa (line numbers). Addresses come from the pinned xMAP.
OMP card G4-R2 `cx-1fa4562d` (18 accepted, 0 rejected, 4 open).
The coordinator re-checked six citations: poison floor, `sOverlayRegions`, TryFaintMon, the capture paths, `Encounter_GetResult` plus the blackout jump, and the doubles mapping.

## Overlay map (SOURCE)

- Static ARM9 = `main.lsf:1-479`.
- Battle = `Overlay OVY_12` (`main.lsf:624-644`): `battle_system.o`, `battle_command.o`, `battle_controller_player.o`, `overlay_12_0224E4FC.o`.
- Field encounter = `OVY_2` (`encounter_check.o`, `main.lsf:567-579`).
- Some overlays are **named, not numbered**: `npc_trade`, `bug_contest`, `field`.
- `ov12_*` is a function-name prefix, not a file-name convention.

## Events

| Event | Site(s) | Where | Data at the site |
|---|---|---|---|
| Wild encounter decided | `FieldSystem_PerformLandOrSurfEncounterCheck` `src/field/encounter_check.c:214`; level roll `:741`; `addGeneratedMonToBattleSetupParty` `:1349` → `Party_AddMon(setup->party[battler])` `:1355` | OVY_2 | built `Pokemon*`, encounter slot |
| Battle types | `include/constants/battle.h:133-148`: TRAINER, DOUBLES, LINK, MULTI, TAG, SAFARI, AI, FRONTIER, ROAMER, PAL_PARK, TUTORIAL, BUG_CONTEST. **No static bit:** a static is `BATTLE_TYPE_NONE` + a script win flag (`IsBattleResultStaticWildWin`, `src/battle/battle_setup.c:548`) | | |
| `BattleSetup` layout | battleType 0x0, party[] 0x4, winFlag 0x14, trainerId[] 0x18, trainer[] 0x28, profile[] 0xF8, bugContestMon 0x1C8 (offset comments in source) | `include/battle/battle_setup.h:28-73` | |
| Trainer battle start | `SetupAndStartTrainerBattle(taskman, opp1, opp2, …)`; trainer ids are args 1 and 2 (`src/scrcmd_battle.c:242`) | arm9 (`encounter.o`) | |
| Battle outcome | enum NONE/WIN/LOSE/DRAW/MON_CAUGHT/PLAYER_FLED/FOE_FLED `include/constants/battle.h:112-118`. `Encounter_GetResult` `src/encounter.c:102-107` copies `setup->winFlag` into `VAR_BATTLE_RESULT` in the generic encounter task. The wild-loss task uses `setup->winFlag` directly (`:369-375`), so `VAR_BATTLE_RESULT` is not a complete whiteout oracle. `ov12_0223843C` copies the battle outcome to setup (`asm/overlay_12_022378C0.s:962-968`). MON_CAUGHT is written at `battle_command.c:7134`; FOE_FLED has no located writer. | arm9 (0x020506F4) and ov12 | encounter-bound winFlag |
| Capture stored | `STATE_GET_POKEMON_STORE_MON_*` `src/battle/battle_command.c:6985-7046`: `Party_AddMon` `:7003`; if the party is full, `PCStorage_FindFirstBoxWithEmptySlot` + `SetActiveBox` `:7012-7014` then `PCStorage_PlaceMonInBoxFirstEmptySlot(pc, emptyBox, …)` `:7027` | OVY_12 | mon, box |
| Faint in battle | `BtlCmd_TryFaintMon` `src/battle/battle_command.c:978-990`: if HP is zero, sets `battlerIdFainted`, FAINTED status bit and count; `BtlCmd_PlayFaintAnimation` `:993-1003` emits the animation. The turn-end HP sweeps (`battle_controller_player.c:1658-1669,3416-3619`) can handle replacement/loss independently. A raw zero-HP write alone does not establish the script/animation. | OVY_12 (0x0223E22C for vanilla command) | `BattleSystem*` r0, `BattleContext*` r1 |
| Battler → party | **not identity**: MULTI or TAG(side) → `trainerParty[battlerId]`; DOUBLES → `trainerParty[battlerId & 1]`; stable handle `ctx->selectedMonIndex[battlerId]` | `src/battle/battle_system.c:92-98`; `battle_command.c:6975` | |
| `BattleMon` offsets (G4-R7, asm literal pools) | `BattleSystem+0x30` → `BattleContext`. `ctx+0x219C` = `selectedMonIndex[4]`; `ctx+0x2D40 + 0xC0*i` = `battleMons[i]`. BattleMon: species 0x00, moves 0x0C, form/shiny 0x26, level 0x34, nickname 0x36 (derived), **hp 0x4C is signed 32-bit (full four-byte read/write)**, maxHp 0x50, exp 0x64, personality 0x68, **status 0x6C**, status2 0x70, gender 0x7E, **size 0xC0** (not 0xBC: the 28-bit-field group takes 8 bytes). The party-tail HP is separately u16 at `PartyPokemon+0x8E` (`include/battle/battle.h:248`; `include/pokemon_types_def.h:203`). `ctx+0x312C` = party slot order. The header's `unk_3xxx` names are inconsistent by 0x38 bytes; don't use them. | ov12 | `asm/overlay_12_battle_controller.s:101, 516-592, 605-607, 662-680, 1289-1292, 1690-1746, 1832-1851, 2051-2058`; `asm/overlay_10_trainer_ai.s:756-760, 920-923` |
| Field poison | **no faint**: `if (hp > 1) hp--` (`src/script_pokemon_util.c:179-183`); `SurvivePoisoning` cures at 1 HP (`:200-204`). The local `n_fainted` actually counts mons at 1 HP. | arm9 | |
| Whiteout | `Task_Blackout` `src/blackout.c:189`; script `ScrCmd_WhiteOut` `src/scrcmd_battle.c:200`; **battle loss** `TaskManager_Jump(..., Task_Blackout)` `src/encounter.c:373-375` | arm9 (0x02052858) | |
| Map change | `*fieldSystem->location = *location` `src/field_warp_tasks.c:147`; post-change `Field_InitMapEvents` `:149` | arm9 | `Location` |
| PC model ops | `PCStorage_PlaceMonInBoxByIndexPair` `.c:86`, `SwapMonsInBoxByIndexPair` `:100` (move), `DeleteBoxMonByIndexPair` `:109` (release), `PlaceMonInBoxFirstEmptySlot` `:70`, `PlaceMonInFirstEmptySlotInAnyBox` `:54` (`src/pokemon_storage_system.c`). The UI handlers were not located. | arm9 | |
| Evolution | `sub_02075A7C(...)` (`include/unk_020755E8.h:14`, **asm** `unk_020755E8.o`); completion `sub_02075D3C`/`sub_02075D4C`; callers post-battle `src/battle/battle_022378C0.c:148`, level-up/stone `src/start_menu.c:1472-1474` | arm9 | |
| Egg hatch | `Task_HatchEggInParty` `src/hatch_egg_task.c:35`; `Party_AddMon` `src/get_egg.c:640` (daycare withdraw / pickup `:156`) | arm9 | |
| NPC trade | `Party_AddMon` `src/npc_trade.c:70` | overlay `npc_trade` | |
| Gift by script | `ScrCmd_GiveMon` `src/scrcmd_party.c:18` → `src/script_pokemon_util.c:41/62`; `ScrCmd_GiveEgg` `:79` | arm9 | see [acquisition.md](acquisition.md) |
| Daycare | deposit `Save_Daycare_PutMonIn` `src/get_egg.c:101`; withdraw `:640` | arm9 | |
| Save done | `Save_WriteManFinish` `src/save.c:674` (0x02027CEC); `Save_WriteFileAsync` `:268` runs per sector | arm9 | |
| Overlay load | `HandleLoadOverlay` `src/poke_overlay.c:64` (0x02006FF8); `UnloadOverlayByID` `:32`; `FS_LoadOverlay` is NitroSDK, so don't hook it | arm9 | residency table `sOverlayRegions` `:20` (0x021D0DF0), set `:76-79`, cleared `:28-32` |

## Design consequences

1. `BattleSetup`, `BattleContext` and `BattleSystem` are **heap-allocated** through separate lifecycles (`src/encounter.c:86,298`; `src/battle/battle_controller_player.c:146-156`; `src/overlay_manager.c:24-28` and `asm/overlay_12_022378C0.s:4264-4273`). Follow the current pointer chain and revalidate identity/epoch before a write; an old battle pointer is invalid after application teardown ([battle_pointer.md](battle_pointer.md)). Preserve an encounter-scoped *outcome value*, not a stale writable pointer, for whiteout observation.
2. Gate ov12 hooks on `sOverlayRegions` + bytes (overlays 57/58/70/72 share ov12's address; see [sources_and_symbols.md](sources_and_symbols.md)).
3. There is no poison-faint signal (Gen 3 S-11 is N/A for HGSS).
4. Doubles need `selectedMonIndex` / `BattleSystem_GetPartyMon` semantics.
5. `PCStorage_*` mutators are static ARM9 sites (`src/pokemon_storage_system.c:54-115`) called outside PC screens as well as by the UI. A phase-armed hook table needs an explicit trigger and caller coverage for battle/script acquisitions; overlay residency alone does not define the static party/PC phase. First-frame events and load/unload within one polling interval remain PHYSICAL coverage questions.

## Open (not settled by source)

- The WIN/LOSE/DRAW/FLED writer (asm; G3 research).
- Resolved by G4-R7: `BattleMon`/`BattleContext` offsets (asm-anchored; nickname derived). They still need a live read at G1/G3.
- PC UI action handlers (the model functions suffice for signals).
- Evolution body (asm).
