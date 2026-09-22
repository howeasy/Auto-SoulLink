# Checkpoint forbidden states with no PHYSICAL receipt: SOURCE + MODEL disposition

Card gen3-P3-R11, 2026-09-22, worktree HEAD `8d65cf0`. This is SOURCE and unit-model work only.
No emulator was run and no pack, Lua or generator file was edited. The only other file this card
adds is `tests/unit/test_gen3_safety_unreached.py`.

**Scope.** PLAN §5.3 (`docs/gen3/PLAN.md:125`) requires every forbidden state to make the overworld
write checkpoint false with an empty write log. The G3 audit
(`docs/gen3/research/g3_evidence_gap_audit.md:127-131`) lists four states with no receipt
(evolution, link, native op staged, mid-relocation) and says the write log is only
`predicate_only`. For each state this doc gives the SOURCE path, the predicate clause that refuses
it, the unit test that exercises the refusal, and a verdict. §5 covers the other §5.3 rows that
still have no PHYSICAL receipt on some artifact.

**Pins.** pret/pokefirered `c75f352304d529f6ba92d4f74b9cf8b5c3810788`. That is the provenance pin
in `data/gen3/pret/provenance.json`, re-fetched read-only for this card. `pret:` below means that
tree. Symbols come from `data/gen3/pret/pokefirered.sym` / `pokeleafgreen.sym`. ROM byte reads are
from the four pinned artifacts in `tools/gen_gen3_write_checkpoint.py:44-56` (FR `41cb23d8`,
LG `574fa542`, RR clean `964f951a`, RR companion `b7d1e075`).

**Verdict vocabulary.**
- **SOURCE+MODEL covered**: a pret/ROM path shows which clause holds while the state is in
  progress, and a lupa test drives that clause through `safety.lua` + `writes.lua` with an empty
  write log.
- **GAP**: the SOURCE or model chain is incomplete.

None of these verdicts is PHYSICAL. A G3 PHYSICAL row still needs a live receipt.

## 0. The clauses (lua/gen3/safety.lua @ 8d65cf0)

| clause | lines | refusal text |
|---|---|---|
| predicates (`callback1`, `callback2`, `in_battle`, `link_*`, `wireless_comm_type`, ...) | `:51-56` (assert `:55`) | `forbidden state: <name>` |
| parked CPU | `:59-62` | `CPU outside parked checkpoint` |
| task allow-list | `:63-73` (assert `:71`) | `unknown active task` |
| native idle | `:74` | `native transaction in flight or unreadable` |
| pointer revalidation | `:75-79` (asserts `:77`, `:78`) | `pointer moved: <name>` / `pointer layout changed` |

The write sink is `lua/gen3/writes.lua`:
- `arm()` takes a snapshot (`:20`) and must pass `check` (`:22-23`).
- Every `write_bytes()` fails if the frame has changed since arming (`:35`), re-runs `check`
  against the arm-time snapshot (`:37-38`), and writes only after that (`:40`).

Allowed tasks (all four packs): `Task_RunPerStepCallback`, `Task_RunTimeBasedEvents`,
`Task_WeatherMain`. See `data/games/gen3_{frlg,rr}/write_checkpoint.json` `tasks.allowed_overworld_tasks`.

## 1. Evolution — SOURCE+MODEL covered (FR/LG); SOURCE+MODEL covered with one UNVERIFIED leg (RR)

**SOURCE (pret).** There are three entry paths, and none of them runs under the overworld callback
pair with only allowed tasks.

- **Post-battle evolution.**
  - `pret:src/battle_main.c:3853` sets `gCB2_AfterEvolution = BattleMainCB2`.
  - `:3861-3877` `FreeResetData_ReturnToOvOrDoEvolutions` goes to `TryEvolvePokemon` (`:3880`),
    which calls `EvolutionScene(&gPlayerParty[i], ...)` at `:3900`.
  - `gMain.inBattle` is set at `:711` and cleared only in `ReturnFromBattleToOverworld`
    (`:3915`, clear at `:3925`), which runs after every evolution has finished.
  - So `in_battle` holds for the whole post-battle scene (`include/main.h:43`, bit 1 of
    `gMain+0x439` = pack `in_battle` mask 2).
- **Item or party-menu evolution.**
  - `pret:src/party_menu.c:5166-5176` `PartyMenuTryEvolution` calls `BeginEvolutionScene`.
  - `pret:src/evolution_scene.c:200-208` does `CreateTask(Task_BeginEvolutionScene)` (`:202`),
    then `SetMainCallback2(CB2_BeginEvolutionScene)` (`:207`).
- **The scene itself.**
  - `EvolutionScene` (`:210`) creates `Task_EvolutionScene` (`:293`) and installs
    `CB2_EvolutionSceneUpdate` (`:310`, and again after graphics reload at `:374`).
  - That callback2 only runs sprites, text, fade and `RunTasks` (`:532-539`).
  - The party write happens inside the task: `SetMonData(mon, MON_DATA_SPECIES)` at `:779`,
    `CalculateMonStats` at `:780`, `EvolutionRenameMon` at `:781`, and `CreateShedinja` (a new
    party slot) at `:827`.
  - callback2 is handed back only at `:833` (`SetMainCallback2(gCB2_AfterEvolution)`), after
    `DestroyTask` (`:829`).
  - Trade evolution follows the same pattern: `CreateTask(Task_TradeEvolutionScene)` at `:509`,
    `CB2_TradeEvolutionSceneUpdate` at `:529`, species store at `:1213`, hand-back at `:1257`.

**Clauses that refuse it.** There are three independent refusals.
1. `callback2` at `safety.lua:55`: `CB2_EvolutionSceneUpdate` (FR `0x080CE710`, LG `0x080CE6E4`)
   is not the pack's `predicates.callback2.expect` `CB2_Overworld|1` (`0x080565B5`).
2. The task allow-list at `safety.lua:71`: `Task_EvolutionScene` (FR `0x080CE8DC`, LG `0x080CE8B0`)
   and `Task_BeginEvolutionScene` (FR `0x080CDD28`) are not in `allowed_overworld_tasks`.
3. `in_battle` at `safety.lua:55`, for the post-battle path.

**RR.**
- `CB2_EvolutionSceneUpdate` is byte-identical in both RR ROMs (`docs/gen3_write_checkpoint.md:107`)
  and pinned as `data/games/gen3_rr/profile.json` `titles.radical_red.rom.CB2_EVOLUTION_UPDATE_ADDR`
  = `0x080CE711`.
- `Task_EvolutionScene` is at the FR address `0x080CE8DC` in RR. `data/games/gen3_rr/engine_signals.json`
  `evolve_species_store.function.address` = 135063772, with context bytes anchored in RR.
- **UNVERIFIED:** `EvolutionScene` itself differs in RR (`docs/gen3_write_checkpoint.md:283`), and
  RR's rewritten battle end has not been decoded. So it is not SOURCE-proven that RR installs that
  exact callback2, or keeps `inBattle` set through the post-battle scene. The task clause does not
  depend on either fact, because any task outside the three-entry allow-list refuses.

**Existing tests.**
- `tests/unit/test_gen3_safety.py:70-78` perturbs `callback2` to `expect^1`. This covers the RR pack
  only, and not with the SOURCE value.
- `:102-106` puts an unknown task `0x08000001` in RR.

**Added tests.** `tests/unit/test_gen3_safety_unreached.py:67-82` `test_evolution` covers
{FR, LG, RR clean, RR companion} × {callback2 = `CB2_EvolutionSceneUpdate`, `Task_EvolutionScene`
active, `Task_BeginEvolutionScene` active, `in_battle`}. Each clause is tested alone. For each case,
`check` returns false with the named reason, `writes.arm` raises the same reason, the write is
refused as unarmed, and `writes` and `log` both stay empty.

**Verdict.** SOURCE+MODEL covered on FR/LG. On RR it is covered by the task clause; the callback2
and in-battle legs are UNVERIFIED. PHYSICAL is still missing on every artifact.

## 2. Link — SOURCE+MODEL covered

**What the pack reads** (identical in all four packs):
- `link_callback`: `gLinkCallback` `0x03003F80` == 0
- `link_transferring`: `gLinkTransferringData` `0x030030E4` == 0
- `wireless_comm_type`: `gWirelessCommType` `0x03003F3C` == 0
- `callback1` == `CB1_Overworld|1`, plus the task allow-list

`gReceivedRemoteLinkPlayers` (`0x03003F64`) is **not** in the pack. None of the paths below needs
it.

**Where the link paths set these (pret).**

*Wired Cable Club*
- `src/cable_club.c:196` `Task_LinkupStart` calls `OpenLinkTimed`, and `:579`
  `Task_ReestablishLink` calls `OpenLink`.
- `src/link.c:386-415` `OpenLink` sets `gLinkCallback = LinkCB_RequestPlayerDataExchange` (`:394`)
  and creates `Task_TriggerHandshake`. The callback clears itself to NULL once it runs
  (`:1128-1134`).
- Seat entry: `src/cable_club.c:873` `CreateTask(Task_EnterCableClubSeat, 80)`, with
  `LockPlayerFieldControls` at `:884` / `:916`.
- The link rooms run `CB2_Overworld` with callback1 `CB1_UpdateLinkState`. See `src/overworld.c:1600-1608`
  `CB2_LoadMapOnReturnToFieldCableClub` (`:1605`) and `:1639-1643` `CB2_ReturnToFieldFromMultiplayer`.
- So in a link room, `callback1` refuses even when callback2 is `CB2_Overworld`.

*Wireless / Union Room*
- `src/union_room.c:407` `Task_TryBecomeLinkLeader` and `:1161` `Task_TryJoinLinkGroup` (and six
  more sites) call `SetWirelessCommType1`.
- `src/link.c:1690-1694` sets `gWirelessCommType = 1` unless `gReceivedRemoteLinkPlayers` is set.
- `link_rfu_2.c:2077` sets it to 2 on an e-Reader error, and `link.c:1447` sets it to 3 in
  `CB2_LinkError`.

*Frame ownership*
- `src/main.c:220-224` skips both callbacks while `HandleLinkConnection()` returns TRUE.
- `gLinkTransferringData` is set TRUE only around `UpdateLinkAndCallCallbacks` (`:195-197`,
  `:208-210`) and is FALSE again before `WaitForVBlank` (`:216`).

**Clauses that refuse it.** `callback1`, `link_callback`, `wireless_comm_type`, and the task
allow-list (`Task_EnterCableClubSeat`, `Task_TriggerHandshake`, the union-room tasks). All four are
checked at `safety.lua:55` / `:71`.

**Note on `link_transferring`.** At the parked frame end it is always 0 by construction
(main.c:197/201/210), so it never does the refusing at a frame-end checkpoint. It stays as
defense in depth for a mid-frame read, which the CPU clause `:61-62` already refuses.

**Existing tests.** `test_gen3_safety.py:70-78` runs `link_callback`, `link_transferring` and
`wireless_comm_type` on the RR pack with value `expect^1` = 1.

**Added tests.** `test_gen3_safety_unreached.py:85-100` `test_link` covers all four artifacts ×
{`gLinkCallback = LinkCB_RequestPlayerDataExchange|1`, `gWirelessCommType = 1`,
`gLinkTransferringData = 1`, `callback1 = CB1_UpdateLinkState|1`, `Task_EnterCableClubSeat`
active}. Each case asserts refusal with an empty write log.

**Verdict.** SOURCE+MODEL covered. RR link code is not re-derived: the link rows are "same" in
`docs/gen3_write_checkpoint.md:95-99`, and the predicates are literal-pool proven in RR
(`:30-44`). PHYSICAL is missing on every artifact.

**Liveness observation (not a safety hole).**
- `gWirelessCommType` is sticky. `CloseLink` (`link.c:419-426`) does not clear it.
- It returns to 0 only through `SetWirelessCommType0_Internal` (the failed-adapter path in
  `IsWirelessAdapterConnected`, `:243-261`), `CB2_PrintErrorMessage` (`:1558`), or the unused
  `SetWirelessCommType0`.
- `docs/gen3/probes/checkpoint_fr_clean_2026-09-22b.txt:17` shows the FR `script_running` row
  (`slink_fr_parcel_deliver.State`) refused with reason `wireless_comm_type`, so that savestate
  carries a non-zero `gWirelessCommType`.
- **UNVERIFIED:** why this happens, and whether the value persists into the field idle that follows
  the cutscene. If it does, FR writes from that save lineage would be refused forever. The failure
  is closed, but liveness is lost. Worth one read of `0x03003F3C` on that state.

## 3. Native operation staged (RR companion) — GAP (the predicate is MODEL-covered; the supplier is not)

**Predicate.** `safety.lua:74` requires `deps.native_idle() == true`. False, nil, a non-boolean or
an error all refuse, because the `pcall` at `:39` turns an error into false.

**Who supplies it.** Only the probe does.
- `lua/gen3/entry.lua:243-246` loads the safety module file but constructs nothing.
- `lua/gen3/shadow_run.lua` never calls `safety.lua`.
- Neither passes `native_idle`.
- `lua/gen3/native.lua`, the owner PLAN §6 P5 C5-1 assigns ("queue owns staging"), does not exist
  yet.

The probe's supplier (`lua/tests/probe_gen3_checkpoint.lua:104-111`) works like this:
- On RR it loads a **fresh** `lua/mailbox.lua` instance (`:106`).
- `native_idle` is `mb.present() and not mb.busy()`. If the mailbox is absent it returns **true**
  (`:108-110`).
- `present()` (`mailbox.lua:475-478`) means `SIG` `0x4B4E4C53` at `0x0203F800` and ABI 1 at `+4`.
- `busy()` (`:519-521`) means that instance's Lua `outbox` is non-empty or the opcode halfword at
  `0x0203F806` is non-zero.

**What `native_idle=opcode_queue_only` covers:** C3-24's probe prints
`WRITE_SURFACE none (predicate-only probe) native_idle=opcode_queue_only`
(`lua/tests/probe_gen3_checkpoint.lua:375`). Older receipts used `WRITE_LOG ...`; neither
label supplies PHYSICAL write-gate evidence, because the probe has no `writes.lua` instance.

- An opcode posted but not yet consumed by the frame hook. The opcode is written last
  (`mailbox.lua` `post`), and the hook clears it in `ack()` (`patch/src/handlers.c:559-565`).
- Multi-frame opcodes that keep the slot occupied until they finish, such as FORCE_MOVE while
  armed, which clears at `handlers.c:587/604`.

**What it does not cover:**
1. **The client's own outbox.** `outbox` is module-local (`mailbox.lua` `local outbox`), so the
   probe's fresh instance always reports an empty queue. Ops queued by the real client's instance
   are invisible to it.
2. **Staged payload buffers.** `TEXT_BUF 0x0203F900`, `MENU_BUF 0x0203FC90` and
   `BLOB_BUF 0x0203FA00` (`mailbox.lua:45,96,158`; for example `write_enemy_blobs`) are written
   *before* the opcode is posted. "Buffer staged, opcode not yet posted" reads as idle.
3. **Ghost / interact state** (`handlers.c` ghost block `active`, `:111`). PLAN §5.3 names
   "no ghost/interact op staged", and nothing reads it.
4. **An absent or corrupt mailbox on the companion kind.** `present()` false leads to `true`
   (idle). This is correct on the clean kind, but on a companion artifact it is **fail-open**. A
   production supplier should return false (or error) when kind is `companion` and the signature
   is missing.
5. **Consumed ops whose effect continues.** These are not the supplier's job and are already
   refused by other clauses. Native text and menu boxes start a field script
   (`ScriptContext1_SetupScript`, `handlers.c:705,957,977,1000,1016`, which trips
   `script_context_status` / `field_controls_locked`). Multichoice starts a task
   (`CreateTask(TASK_MULTICHOICE_INPUT)`, `:671,883`), which is not in the allow-list.

**Tests.**
- Existing: `test_gen3_safety.py:121-127` (idle false/nil, RR) and `:134-140` (`native_idle`
  raises).
- Added: `test_gen3_safety_unreached.py:110-115` `test_native_staged` covers all four artifacts ×
  {false, nil, 1}, each refused with an empty write log.
- The probe's supplier function is local to `P.run` and has no unit test.

**Verdict.** The predicate contract is MODEL-covered. The state as a whole is a **GAP**: there is
no production supplier, the probe supplier covers only the opcode slot, and it fails open when the
mailbox is absent on the companion kind. The owner is P5 C5-1 (`native.lua`).
`docs/gen3_write_checkpoint.md:313` already assigns this to P5. G3 should list it as OPEN/deferred,
not as covered.

## 4. Mid-relocation — SOURCE+MODEL covered (FR/LG); vacuous for RR pointer values (see finding)

**SOURCE: vanilla FR/LG do relocate.**
- `pret:src/load_save.c:69-83` `SetSaveBlocksPointers` computes
  `offset = Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)` (`:75`, `SAVEBLOCK_MOVE_RANGE 128` at
  `:15`). It then re-points `gSaveBlock2Ptr`, `gSaveBlock1Ptr` and `gPokemonStoragePtr` (`:77-79`).
- `MoveSaveBlocks_ResetHeap` (`:85-130`) copies all three blocks into `gHeap`, calls the setter
  (`:110`), copies them back to the new addresses (`:114-116`) and re-inits the heap.
- It is called from `CB2_InitBattle` (`pret:src/battle_main.c:614`) and from every map load through
  `InitOverworldBgs` → `MoveSaveBlocks_ResetHeap_` (`src/overworld.c:1337`, `:2048-2050`). Those
  loaders are `LoadMapInStepsLink` `:1776`, `LoadMapInStepsLocal` `:1853`, `ReturnToFieldLocal`
  `:1941` and `ReturnToFieldLink` `:1971`.

`docs/gen3_write_checkpoint.md:260-262` says "Vanilla FRLG sets `gSaveBlock1Ptr`/`gSaveBlock2Ptr`
once at boot". **That is stale:** `main.c:232-233` is only the boot value.
`lua/gen3/reads.lua:29-35` already has this right.

**SOURCE: RR (ROM bytes, both RR artifacts identical).**
- `SetSaveBlocksPointers` is at the FR address `0x0804C058`.
- At `+0x0A` FR has `7C21 4001` (`movs r1,#0x7C; ands r1,r0`). RR clean and companion have
  `0021 0021` (`movs r1,#0` twice). **RR's offset is always 0.**
- RR still runs `MoveSaveBlocks_ResetHeap` from `CB2_InitBattle` and from the map-load wrapper
  `0x08056E74` (`BR:docs/rr_reference/GAME_HEAP_RESERVATION.md:48-58`; `BR` =
  `archive/codex/rr-foundation`). The copy-out and copy-back return to the same addresses.
- So RR's pointer **values** do not move. RR "relocation" is the heap reset plus the save-block
  copy round trip inside a single callback.
- Pinned by `test_gen3_safety_unreached.py:135-146` `test_save_block_offset_instruction`, which
  reads the four ROMs and skips if any is absent.

**Finding: RR pack pointers are not the setter's pointers.** UNVERIFIED which one is authoritative.
- RR's `SetSaveBlocksPointers` literal pool still names `0x03005008` / `0x0300500C` / `0x03005010`
  (ROM file `0x4C08C..0x4C0A0`, `docs/gen3/research/rr_save_layout.md:60-67`).
- `data/games/gen3_rr/write_checkpoint.json` `pointers` snapshots `profile.ram.SB1_PTR_ADDR`
  `0x03003840` and `SB2_PTR_ADDR` `0x03003838` (generator `RR_POINTERS`,
  `tools/gen_gen3_write_checkpoint.py:157,294-300`). It also uses the literal
  `pokemon_storage_base` `0x02029314`, which `safety.lua:25` never re-reads, so it cannot move.
- The two pairs may both be valid pointers (the P1/P3 receipts deref `0x03003840` successfully),
  but what writes `0x03003840` is not decoded here.
- With the offset fixed at 0, neither pair can change value from `SetSaveBlocksPointers`. So on RR
  the `pointer moved` clause is structurally vacuous against the relocation PLAN §5.3 cites.

**Why a gate armed before relocation is refused after it.** This is the MODEL, in three layers.
1. Relocation runs to completion inside one callback (`CB2_InitBattle`, or a map-load CB2). A
   frame-end reader never sees a half-copied block. A mid-frame reader is refused by the parked-CPU
   clause (`safety.lua:59-62`).
2. A `writes.lua` window is valid only for the frame it was armed in (`writes.lua:35`, tested
   `test_gen3_writes.py:51-58` `frame=8`). A window armed before a relocating frame is refused as
   `write window expired` before safety is consulted.
3. Within one frame, `write_bytes` re-runs `check(window.snapshot)` (`:37`). Any pointer that
   differs from the arm-time snapshot aborts with `pointer moved` (`safety.lua:77`), and a missing
   one aborts with `pointer layout changed` (`:78`). The write is aborted, never retargeted.

- Existing test: `test_gen3_safety.py:151-161` covers RR `gSaveBlock1Ptr` only.
- Added: `test_gen3_safety_unreached.py:118-132` `test_mid_relocation_every_pointer` covers all four
  artifacts × every pack pointer (FR/LG `gSaveBlock1Ptr`, `gSaveBlock2Ptr`, `gPokemonStoragePtr`;
  RR both SB pointers). Each pointer is moved by +4, a legal `load_save.c:75` step, between `arm`
  and `write_u16`. Expected: `pointer moved: <name>`, with bus writes and log both empty.

**Model limit.** The snapshot guards arm→write. It does **not** guard a caller that computed its
target address from a pointer read on an earlier frame and then arms on a later frame. The snapshot
is opaque (`safety.lua:32`) and is taken at arm time. The mitigation today is convention:
`reads.lua:271-272` dereferences on every call and never caches. A future writer that caches an
address across frames is outside this proof.

**Verdict.** FR/LG: SOURCE+MODEL covered. RR: the relocation risk is SOURCE-covered (the offset is
fixed at 0 and the copy happens within one callback) and the clause is MODEL-covered, but the clause
cannot fire on RR from this path. The RR pack's pointer addresses need one source decode (above).
PHYSICAL is missing on every artifact. A true "mid-relocation" live state does not exist at frame
granularity, so the honest PHYSICAL control is "arm, then advance through a battle start or map
load, then write refused". That exercises `writes.lua:35` on RR, and on FR it exercises `:35` or
`:37`.

## 5. Other PLAN §5.3 rows still lacking a PHYSICAL row on some artifact

| artifact / state | receipt status | refusing clause (SOURCE) | unit test |
|---|---|---|---|
| FR clean, PC menu | `checkpoint_fr_clean_2026-09-22b.txt:16` `SKIP not selected` | `Task_PCMainMenu` (`pret:src/pokemon_storage_system_menu.c:356`, FR `0x0808C39C`) ∉ allow-list; the PC script trips `script_context_status` first on RR (`checkpoint_rr_companion_2026-09-22.txt:17`) | added `test_gen3_safety_unreached.py:103-107` (all four artifacts) |
| FR clean, battle | `:14` `FAIL reached=false` (no in-battle state) | `in_battle` (`battle_main.c:711`), `callback2` | `test_gen3_safety.py:70-78` (RR pack); added `test_evolution[in_battle]` for all four artifacts |
| LG clean, RR clean | no checkpoint receipt at all | same packs and clauses (predicate addresses identical, `write_checkpoint.json`) | all tests in the added file run LG and RR clean |
| empty write log | current probe prints `WRITE_SURFACE none (predicate-only probe)`; older receipts' `WRITE_LOG count=0 scope=predicate_only no_writes_instance=true` was not write-gate evidence | `writes.lua:22-23,37-38` (MODEL only; the probe has no writer instance) | every added negative drives `writes.lua` and asserts `writes` and `log` both empty; `test_positive_control_arms_and_writes` (`:58-64`) proves the same harness does write when the state is idle |

## 6. Gates run

```
python -m pytest tests/unit/test_gen3_safety_unreached.py tests/unit/test_gen3_safety.py -q -p no:randomly
100 passed
ruff check tests/unit/test_gen3_safety_unreached.py
All checks passed!
```

The ROM test ran rather than skipping, because all four artifacts are present on this host.

**Revert test.** Each added assertion was checked for failing on the defect it targets. A
throwaway `Path.read_text` patch deleted one assertion line from `safety.lua` in memory only; the
file was not edited. Failing tests in the added file:

| line deleted from `safety.lua` | failing tests |
|---|---|
| native `:74` | 12 (native × 4 artifacts × 3 values) |
| pointer `:77` | 4 (relocation × 4 artifacts) |
| task `:71` | 16 (evolution task ×8, link task ×4, PC ×4) |
| predicate `:55` | 24 (evolution callback2 / in_battle ×8, link predicates ×16) |

## 7. Table for `docs/gen3/G3_request_draft.md` §4

Clause line references below describe the original R11 cut `8d65cf0`. Per-clause attribution
landed separately in `3040b91`; the first-failure reason remains order-dependent.

| State | Artifact(s) | A refusing clause (order-dependent until per-clause attribution lands) | SOURCE | Unit test (false + empty write log) | Verdict |
|---|---|---|---|---|---|
| Evolution | FR, LG | `callback2` :55; task allow-list :71; `in_battle` :55 (post-battle) | pret `evolution_scene.c:202,207,293,310,779,833`; `battle_main.c:711,3900,3925` | `test_gen3_safety_unreached.py:67-82` | SOURCE+MODEL covered; PHYSICAL OPEN |
| Evolution | RR clean/companion | task allow-list :71 (`Task_EvolutionScene` 0x080CE8DC pinned, `engine_signals.json` `evolve_species_store`); `callback2` value pinned (`profile.json` `CB2_EVOLUTION_UPDATE_ADDR`) | as FR; RR `EvolutionScene` body differs, so the callback2 / in_battle legs are UNVERIFIED | `test_evolution` covers the generic task allow-list property, not proof of the RR address `0x080CE8DC`; added `test_rr_evolution_task_from_engine_signals_is_refused` uses the pinned RR function address from each artifact's `evolve_species_store` row (execution pending coordinator gates) | SOURCE+MODEL covered (generic task leg); PHYSICAL OPEN |
| Link (cable / wireless) | all | `callback1` (`CB1_UpdateLinkState`), `link_callback`, `wireless_comm_type` :55; task allow-list :71; `link_transferring` is always 0 at the park (defense in depth only) | pret `link.c:394,1690-1694`; `cable_club.c:579,873`; `union_room.c:407,1161`; `overworld.c:1605,1643`; `main.c:195-216` | `test_gen3_safety_unreached.py:85-100`; `test_gen3_safety.py:70-78` | SOURCE+MODEL covered; PHYSICAL OPEN |
| Native op staged | RR companion | `native_idle` :74 | probe-only supplier `probe_gen3_checkpoint.lua:104-111` = opcode slot `0x0203F806` ≠ 0; client outbox, staged buffers and ghost not covered; fail-open when the mailbox is absent | `test_gen3_safety_unreached.py:110-115`; `test_gen3_safety.py:121-127,134-140` | **GAP**: predicate MODEL-covered, no production supplier (P5 C5-1 `native.lua`); OPEN/deferred |
| Mid-relocation | FR, LG | pointer revalidation :77 (+ window expiry `writes.lua:35`) | pret `load_save.c:69-83,85-116`; `battle_main.c:614`; `overworld.c:1337` | `test_gen3_safety_unreached.py:118-132`; `test_gen3_safety.py:151-161`; `test_gen3_writes.py:51-58` | SOURCE+MODEL covered; PHYSICAL OPEN |
| Mid-relocation | RR | same clause, vacuous: RR offset is fixed at 0 (`0x0804C062` `0021 0021`); window expiry `writes.lua:35` is the effective guard | ROM bytes (`test_save_block_offset_instruction` :135-146); `BR:GAME_HEAP_RESERVATION.md:48-58` | as FR | SOURCE+MODEL covered; RR pack pointer addresses (0x03003840/38 vs setter pool 0x03005008/0C) UNVERIFIED |
| PC menu | FR clean (SKIP row) | task allow-list :71 (`Task_PCMainMenu`); script context :55 | pret `pokemon_storage_system_menu.c:356` | `test_gen3_safety_unreached.py:103-107` | SOURCE+MODEL covered; FR PHYSICAL OPEN |
| Empty write log | all | `writes.lua:22-23,37-38` | — | every negative in the added file asserts `writes` and `log` empty; positive control :58-64 | MODEL covered; PHYSICAL still `predicate_only` |

## 8. Findings for the coordinator (none acted on by this card)

1. **`native_idle` fails open on the companion kind** when the mailbox signature is absent, and it
   has no production supplier. See §3. This needs a P5 C5-1 disposition before G5, and G3 should
   show it as OPEN.
2. **`docs/gen3_write_checkpoint.md:260-262` is stale.** Vanilla FRLG re-points all three save
   pointers on every battle start and map load (§4). The pack and the code are already correct;
   only the prose is wrong.
3. **RR pointer provenance.** The pack snapshots `0x03003840` / `0x03003838`, but RR's setter
   writes `0x03005008` / `0x0300500C` / `0x03005010` with offset 0. One decode of what writes
   `0x03003840` in RR would settle it (§4).
4. **The FR `slink_fr_parcel_deliver.State` carries a non-zero `gWirelessCommType`.** This is a
   liveness risk for FR writes after that cutscene, if the value persists (§2).
5. **`link_transferring` cannot refuse at the parked frame end** (§2). Keep it, but do not cite it
   as the link witness.

## Errata (2026-09-22, card gen3-P3-C3-22)

- **`wireless_comm_type` was the wrong link predicate; replaced by `link_players_received`
  (`gReceivedRemoteLinkPlayers` `0x03003F64` == 0).** Resolves §2's liveness observation and §8
  finding 4. `gWirelessCommType` selects the transport (0 cable, 1 RFU); in single-player play its
  only writer is the title menu's adapter probe (`src/main_menu.c:573` -> `IsWirelessAdapterConnected`
  `src/link.c:243-261`: `SetWirelessCommType1` at `:248`, cleared at `:257` only if the adapter
  does not answer), and nothing on the field clears it (`CloseLink` `:419-426`). On hardware with
  the Wireless Adapter FRLG shipped with, it is 1 for the whole session, so the clause would refuse
  every write. Physical: `docs/gen3/probes/checkpoint_fr_parcel_lineage_2026-09-22.txt` idle 0/300.
  No Oak-lab / Pokedex code writes it; why BizHawk's probe left it non-zero on that lineage and
  not the town fixture is UNVERIFIED (one read of `0x03003F3C` on both states would settle it).
  Tests: `test_gen3_safety_unreached.py::test_wireless_comm_type_alone_is_idle` (1/2/3 alone =
  admit; plus `link_players_received` = refuse), and the `test_link` / `test_each_forbidden_state`
  rows now name `link_players_received`. Line citations in §2/§7 that name `wireless_comm_type`
  describe the old pack.
