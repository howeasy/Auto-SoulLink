# Write checkpoint facts (HGSS)

Source: pokeheartgold @ad7a3afa. Addresses come from the pinned xMAP.
OMP card G4-R6 `cx-8f1d0eff`.
The coordinator re-checked `battle_setup.c:425-434`, `task.c:70-72`, `main.c:120-123`, the asm `winFlag` store and the xMAP addresses below.

## 1. A battle works on copies, and the field copies them back (SOURCE, verified)

- `BattleSetup` allocates its own `Party` per battler (`src/battle/battle_setup.c:57`). It copies the save party in with `BattleSetup_SetParty` → `Party_Copy` (`:174-177`, via `BattleSetup_InitFromFieldSystem` `:257-260`).
- At battle end the engine copies its party into `BattleSetup` (`asm/overlay_12_022378C0.s:892-895`). The ordinary encounter path runs `sub_0205239C` through `src/encounter.c:110-113` (except `BATTLE_TYPE_DEBUG`), which copies **profile, party and bag** back into the save (`src/battle/battle_setup.c:425-434`):

  ```
  PlayerProfile_Copy(setup->profile[BATTLER_PLAYER], profile);
  Party_Copy(setup->party[BATTLER_PLAYER], party);
  Save_Bag_Copy(setup->bag, bag);
  ```

- **Consequence:** a write to the save party, profile or bag between battle setup and the copy-back is lost. The checkpoint must refuse from battle setup until the encounter task finishes, not merely while ov12 is resident.
- Link and Frontier battles copy back only the Pokédex (`battle_setup.c:449-460`; `encounter.c:212-213, 272-273`). Safari, Bug Contest and Catching Show go through the same field copy-back (`encounter.c:545-560, 599, 716-717`).
- Evolution at battle end mutates the **setup copy** before the copy-back (`src/battle/battle_022378C0.c:147-148`). Level-up/stone evolution from the menu mutates the save party directly (`src/start_menu.c:1472-1474`).
- In `Task_StartEncounter`, a `BATTLE_TYPE_11` loss heals the save party (`src/encounter.c:145-148`); an NPC-follower flag also heals after a win (`:154-156`). The wild-loss task copies back and jumps to `Task_Blackout` (`:369-375`), whose first state heals (`src/blackout.c:189-205`). The follower flag is tied to a follower trainer number (`src/scrcmd_battle.c:109-110`), not established by an ordinary walking Pokémon. A linked-faint witness must separate pre-heal battle/save-copy state from post-heal native save/reload and Soul Link death state.

## 2. Battle outcome (SOURCE, verified)

- The engine keeps its outcome byte at `BattleSystem+0x2420` (`include/battle/battle.h:604-605`).
- `ov12_0223843C` (0x0223843C, called in `BSTATE_END_INIT`, `src/battle/battle_022378C0.c:104`) stores `battleOutcomeFlag & 0x3F` into `BattleSetup+0x14` (`winFlag`) at `asm/overlay_12_022378C0.s:962-968`.
- `Encounter_GetResult` (0x020506F4, `src/encounter.c:102-107`) copies setup's result to `VAR_BATTLE_RESULT` in the generic encounter task. The wild-loss task instead reads `setup->winFlag` directly (`:369-375`) and does **not** update that variable on this path. A variable-only poll may miss that loss or reuse an older result. Retain encounter identity and the setup outcome through copy-back/blackout, clear the latch exactly once, and never keep the battle application's pointer as a writable handle after teardown. This lifetime contract still needs a PHYSICAL consecutive-battle receipt.

## 3. "Overworld idle" (SOURCE; addresses from the xMAP)

| Clause | Fact | Evidence |
|---|---|---|
| Field system | `sFieldSysPtr` @ **0x021D4158** (static, `src/field_system.c:42`) | xMAP |
| Save pointer agrees | `fs+0x0C` (`saveData`) == `[sSaveDataPtr 0x021D2228]` | `include/field_system.h`; `src/overlay_124.c:26` |
| No field task | `fs+0x10` (`taskman`) == NULL. Scripts (`src/fieldmap.c:70-91`), the start menu (`src/start_menu.c:233`), warps and the battle launch are all field tasks. `FieldSystem_TaskIsRunning` = 0x02050590. | `src/task.c:70-72` |
| Player may act | `fs->unk0->isPaused == 0` and `fs+0x6C != 0`. `unk6C` is a latch set TRUE once the field is live (the only writer is `asm/overlay_01_021E5900.s:286-292`) and cleared on field reload and on every app launch (`src/field_system.c:95,101`). TRUE means "field live". | `src/field_system.c:199-201` (`FieldSystem_IsPlayerMovementAllowed` = `!isPaused && unk6C && !taskman`) |
| No launched app | **`fs->unk0->unk4 == NULL`** (bag/party/battle/summary; `FieldSystem_LaunchApplication`, `src/field_system.c:127-133`). **Correction (G4-R7):** `fs->unk0->unk0` is the *field app itself*, non-NULL for the whole field session (`src/field_system.c:97`). So `FieldSystem_ApplicationIsRunning` is TRUE all through overworld play and is **not** an idle test. | `src/field_system.c:93-97, 117-133, 173-192` |
| No save in flight | The save driver at `fs+0xD8` is a 16-byte `{u8 mode, u8 state, u8 reqMode, SysTask* sub, FieldSystem*, user}`. `state` byte +1: 0 init, **1 idle** (the only state that accepts a request, `ov01_021F6A9C`), 2 requested, 3-7 fade/run/finish. Require **`state == 1`**. `asyncWriteMan.rollbackCounter` is never cleared, so it is useless. `ov01_021F6830` only plays the jingle; it is not the request API. | `asm/overlay_01_021F6830.s:122-146, 248-378`; `src/save.c:622` |
| CPU parked | end-of-frame `OS_WaitIrq(TRUE, OS_IE_VBLANK)` at `src/main.c:122` (`OS_WaitIrq` = 0x020D0E6C); `gSystem.vblankCounter` @ `gSystem(0x021D110C)+0x2C`, `frameCounter` +0x30 | `include/system.h:21-57` |

`include/field_system.h` annotates only a few offsets (0x7A, 0x7C, 0x7E, 0xE4). The 0x0C/0x10/0x3C/0x40/0x6C/0xD8 offsets were cross-checked against asm loads (`asm/overlay_01_021E6880.s:375,393,483`; `asm/overlay_01_021F6830.s:365`). A G3 PHYSICAL receipt must confirm them.

## 4. PC box persistence (SOURCE, verified)

- `PCStorage+0x12004` holds `boxModifiedFlag`. The game sets `|= 1<<box` in every mutator (`src/pokemon_storage_system.c:336-342`, called from `:59, :79, :93, :106, :115`).
- The incremental save flashes only boxes with a set bit (`src/save.c:1220-1231, 1326-1328, 1354-1361`). The bits are cleared after a successful save (`:682-687`).
- **A Soul Link box write must OR `1<<box` into +0x12004.** Save CRCs and footers are regenerated at save time, so no other bookkeeping is needed.
- Keep each PK4 record's representation consistent: box-data edits require re-encryption and box checksum regeneration, while party-tail-only HP edits use the PID stream when encrypted and do not change the box checksum ([pk4_and_save.md](pk4_and_save.md)). Inspect `partyDecrypted`/`boxDecrypted` before writing.

## 5. Candidate checkpoint predicate (all clauses verified or marked)

Write only when **all** of these hold:
1. **Measured (platform.md, live probe):** the frame-end PC is never in `OS_WaitIrq`. The main thread waits there, but frame end usually lands in the idle thread's `OS_Halt` (PC 0x020D3F64) or IRQ code. So the CPU clause is **not** "PC in `OS_WaitIrq`". Use `gSystem.vblankCounter` (+0x2C, +1 per frame) to detect a new frame, plus the field-state clauses below. If a CPU clause is still wanted, use an exec hook on `OS_WaitIrq` (fires once per frame) to mark "main loop reached its wait"; it costs one hook from the budget.
2. `fs = [0x021D4158]` is non-NULL, `fs->unk0` is non-NULL, and `[fs+0x0C] == [0x021D2228]`.
3. `[fs+0x10] == 0` (no field task: no script, menu, warp or battle launch).
4. No launched app: `fs->unk0->unk4 == NULL`. `unk0->unk0` must be **non-NULL**, meaning the field app is alive.
5. `fs+0x6C != 0` and `fs->unk0->isPaused == 0`. Together with clause 3 this is the game's own `FieldSystem_IsPlayerMovementAllowed`.
6. The save driver at `[fs+0xD8]` has data byte +1 == 1 (idle).

Then write through `SaveArray_Get(fs->saveData, …)` and, for box edits, OR the box bit into +0x12004.

**Linked-faint consequence:** this checkpoint is for benched/deferred writes after battle settlement. D7 requires the active battler's effect **in battle**, and D12 does not accept a checkpoint fallback. A command whose active opportunity ended without a proved game-observed faint remains unresolved; do not label a later checkpoint zero-HP write as D7 success.

## Open

- Resolved by G4-R7 `cx-2fe25ca0`: the `unk6C` writer, the `unk0->unk0/unk4` lifecycle and the save-driver states. A live census at G1/G3 still confirms them PHYSICALLY.
- Whether any other `HealParty`/`SetMonData` caller clobbers an idle-time write.
