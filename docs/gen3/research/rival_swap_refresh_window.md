# The rival-swap window — revised contract (P4 card C5-8b, after Codex REV-3)

C5-8's redesign accepted the ordering claim (a swap that lands before the opponent controller's
snapshot is carried by the engine end to end) but was **rejected as specified**. Three majors and
five minors are folded in below. The window values are the C5-9 pins. Doc-only: no code.

Grading vocabulary: **PRET** (`E:/Google Drive/SLink/.cache/pret/pokefirered` at `c75f3523`),
**SYM** (`data/gen3/pret/*.sym`, FR = LG), **RR-PROD** (`data/games/gen3_rr/profile.json`),
**RR-BIN** (measured against `patch/build/slink_RR.gba`, sha1 `b7d1e075…`), **INFER**.

## 1. Why the first window was unsafe (unchanged, Codex-confirmed)

| what | cite | consequence |
|---|---|---|
| `HandleEndTurn_ContinueBattle` zeroes all of `gBattleCommunication` after waiting for exec flags to clear; `BattleTurnPassed` likewise | PRET `src/battle_main.c:2929-2937`, `:2980-2998`; RR-BIN `0x08013B1E` (pool `0x08013BB4` = `0x02023BC8`), comm via pool `0x08013BC4`, bytes cleared `0x08013B30..3B3A` | a five-data-clause set admits **every turn end** |
| `MULTIUSE_STATE` is byte 0 of `gBattleCommunication` | PRET `include/constants/battle_script_commands.h:31` | it is a shared scratch stage (`CB2_HandleStartBattle` drives 0..16 with it), never a phase signal |
| the first trainer dex write is inside the copy frame | PRET `src/battle_main.c:2611` | the C4-8 doc's `:2785` deadline was the **second** write |
| `gEnemyParty + 0` is the PID (`struct Pokemon.personality` at `+0x00`), not the species | PRET `include/pokemon.h:128-131` | a PID read is not a species witness |

## 2. The phase model (PRET, single-player trainer battle, non-link)

| # | phase | what happens | cite |
|---|---|---|---|
| 0 | `CB2_InitBattle` **entry** | the pack's `battle_begin` hook. `gEnemyParty` is **not yet the rival's** | `engine_signals.json` site `battle_begin`, `capture_offset 0` |
| 1 | `CB2_InitBattleInternal` | `SetUpBattleVars()` sets `gBattleMainFunc = BeginBattleIntroDummy`, **then** `CreateNPCTrainerParty(&gEnemyParty[0], …)` (with `SetWildMonHeldItem`, which skips trainer battles) | PRET `src/battle_controllers.c:41-45`; `src/battle_main.c:699,707-708` |
| 2 | `CB2_HandleStartBattle` states 0..16 | case 15 → `InitBattleControllers` → `InitSinglePlayerBtlControllers` (**sets `gBattleMainFunc = BeginBattleIntro`**) → **`SetBattlePartyIds()`**; case 16 → `callback1 = BattleMainCB1`, `SetMainCallback2(BattleMainCB2)` | PRET `src/battle_controllers.c:66-75,113`; `src/battle_main.c:1058-1066` |
| 3 | `BattleIntroGetMonsData` case 0, **one battler per invocation** | `BtlController_EmitGetMonData(BUFFER_A, REQUEST_ALL_BATTLE, 0)`; the controller (which runs after `gBattleMainFunc` in `BattleMainCB1`) builds a `struct BattlePokemon` field by field from `gEnemyParty[gBattlerPartyIndexes[b]]` and transfers it into `gBattleBufferB[b]` — **the snapshot** | PRET `src/battle_main.c:2522-2542`; `src/battle_controller_opponent.c:429-451` (handler), **`:466-500`** (the `REQUEST_ALL_BATTLE` converter: species, item, moves, PP, ppBonuses, friendship, exp, IVs, abilityNum, personality, status1, level, hp, maxHP, atk/def/spd/spa/spd, otId, nickname, otName), `:246,255` are `TryShinyAnimation`/healthbox readers, **not** the snapshot |
| 4 | `BattleIntroDrawTrainersOrMonsSprites` | in **one frame**: `gBattleMons[b] = gBattleBufferB[b][4..]` (`gBattleBufferB` is `[MAX_BATTLERS_COUNT][0x200]`, PRET `src/battle_main.c:141`), then `type1/type2` from `gSpeciesInfo`, `ability = GetAbilityBySpecies(...)`, `statStages = DEFAULT_STAT_STAGE`, `status2 = 0`, then **the first dex write** | PRET `src/battle_main.c:2560-2637` |
| 5 | send-outs, then `BattleIntroRecordMonsToDex` | the HP boxes read `&gEnemyParty[...]`; the dex is written a **second** time from the same `gBattleMons` | PRET `src/battle_main.c:2643-2803`, `:2771-2786`; `src/battle_interface.c:1044-1054` |
| 6 | `TryDoEventsBeforeFirstTurn` → the turn loop | then per-turn the end-turn clear above | PRET `src/battle_main.c:2831,2912,2929,2980` |

Two facts carry the design: the **snapshot** is what the copy consumes, and the converter that
fills it is *the engine's own field mapping* (`:466-500`) — the same mapping C4-8's Lua refresh
reimplemented (with drift: `ppBonuses` at `+0x3A` instead of `+0x3B`, and 7 of 8 `statStages`).

## 3. Battle epoch and recipient binding (MAJOR 1)

The wire carries **no** epoch or request id: `queue_rival_team_swap` emits
`{cmd, trainer_id, n, blobs_hex, source}` (PRET-n/a, `server/state.py:3052-3080`), and the blob
cache validates *shape* only (`state.py:3026-3046`). The client therefore owns the correlation:

**Epoch record (client-local, in `lua/gen3/client.lua`'s driver state):**

| field | meaning |
|---|---|
| `id` | monotonic counter, incremented on every battle-begin signal |
| `trainer_id` | the trainer id the client read at the signal (the same value that went out in `trainer_battle_start`) |
| `opened_frame` | `io.framecount()` at the signal |
| `open` | false once any close condition fires |

**Open:** the client's own battle-begin signal for a **trainer** battle (the pack's `battle_begin`
site). One epoch per battle — a new battle invalidates the previous.

**Close (invalidate):** `battle_end`; `whiteout`; a new battle-begin signal; a session/native
reset (`native.lua`'s "native reset" poison path); or the window itself closing (§5).

**At dispatch (the `native.transfer("enemy", …, valid)` guard):** all of

1. `epoch.open` and `cmd.trainer_id == epoch.trainer_id` — else refuse `stale_epoch` /
   `trainer_mismatch`;
2. the window clause of §5 passes — else refuse `window_closed`;
3. (W2 only) the slot-viability rule of §4 passes — else refuse `slots_unviable`.

A refusal never writes, so the rival keeps its own team: the failure mode is "no swap", never a
half-swap.

**Late replies.** With `trainer_id` as the only correlator, two consecutive battles against the
same rival id are indistinguishable from the wire alone: a reply from battle *n* arriving inside
battle *n+1*'s window would pass checks 1–2. Bound it two ways: the window closes at the
opponent's data request (seconds at most after the signal, §5), and the server re-caches the
partner's blobs every tick, so the worst case swaps in a party a few hundred ms old. The clean fix
is a server-side request id echoed by the client — a follow-up card on `state.py`, not this design.

## 4. Slot selection happens before the window (MAJOR 2)

`InitBattleControllers` calls `SetBattlePartyIds()` (PRET `src/battle_controllers.c:66-75`), which
picks, per battler, the first party slot satisfying
`HP != 0 && species ∉ {SPECIES_NONE, SPECIES_EGG} && !isEgg` (and `!= gBattlerPartyIndexes[i-2]`
for the second battler of a side) and stores it in `gBattlerPartyIndexes[i]`
(`src/battle_controllers.c:290-350`; enemy lead `:315-320`, second enemy `:341-347`). Index 0 is
the **player** in non-link battles (`:104-108`, `:128-136`), so the enemy lead is index 1 and the
enemy partner index 3.

Three ways to be correct, in order of preference:

- **W1 — land the swap before the selection** (recommended). The pre-selection window is the
  `BeginBattleIntroDummy` value set in phase 1 (`SetUpBattleVars`, `src/battle_main.c:699`) and
  live until case 15 runs `InitBattleControllers`; `CB2_HandleStartBattle` advances one switch case
  per frame (case 0 waits on `IsDma3ManagerBusyWithBgCopy`, case 1 does the berry data and jumps to
  15 for non-link), so the selection is at least two frames after the value appears. The engine
  then selects the swapped team's slots itself — correct for singles *and* doubles, with no
  viability rule.
- **W2 — land after the selection and validate it** (fallback). Admitted only when every
  preselected enemy index is viable **in the replacement**: for each enemy battler
  (`gBattlerPartyIndexes[1]`, plus `[3]` when `gBattlersCount >= 4`),
  `idx < n`, and the staged blob at `idx` satisfies the same predicate the engine used
  (HP ≠ 0, species ∉ {NONE, EGG}, not an egg, and `[3] != [1]`). The blobs are in hand (the
  command carries `blobs_hex`), so this is a decode-only check; if any fails, refuse
  (`slots_unviable`) — a refusal keeps the rival's own team.
- **Re-running the selection ourselves** (writing `gBattlerPartyIndexes`) is *not* recommended:
  it adds a second game-state write with its own window and its own risk of disagreeing with the
  engine's later reads.

**Doubles** are covered by both tiers (W1 by construction; W2 by checking both enemy battlers).

**RR pinning of the selection path — OPEN, with the target located.** RR-BIN: `InitBattleControllers`
is byte-identical to FR (88 bytes), but `SetBattlePartyIds`' tail is a CFRU stub
(`00 48 00 47` + pool `0x0904449D` at FR body `+0x138`), and `InitSinglePlayerBtlControllers`' tail
likewise (`0x09044531`). So the *call order* is pinned and the *viability predicate* is CFRU code
that must be enumerated from `0x0904449D` before W2 is used on RR. Until then: **W2 is unavailable
on RR** (the reason refuses by name) and **W1 carries RR**, because W1 never depends on the
predicate.

## 5. The window (with the C5-9 pin names)

| clause | field / source | test | why it is in the set |
|---|---|---|---|
| `intro_entry_dummy` | `rom.BEGIN_BATTLE_INTRO_DUMMY_ADDR` (0x080123BD) | `gBattleMainFunc == 0x080123BD` | **W1**: set by `SetUpBattleVars` (PRET `src/battle_controllers.c:44`, called at `src/battle_main.c:699`) and live until case 15 sets `BeginBattleIntro`; the op's blob write lands at the next `CallCallbacks`, i.e. after `CreateNPCTrainerParty` (`:707`) and at least one frame before `InitBattleControllers`/`SetBattlePartyIds` |
| `intro_entry` | `rom.BEGIN_BATTLE_INTRO_ADDR` (0x080123C1) | `gBattleMainFunc == 0x080123C1` | **W2**: set inside `InitBattleControllers` (PRET `src/battle_controllers.c:113`), i.e. *after* the selection — requires §4's viability rule |
| `intro_request_open` | `rom.BATTLE_INTRO_GET_MONS_DATA_ADDR` (0x08012FAD) and `ram.BATTLE_COMM_ADDR + 1` (0x02023E83) | `gBattleMainFunc == 0x08012FAD` **and** the per-battler request index `== 0` | the request walk starts at index 0 (the player), so the enemy's snapshot has not been requested; each invocation handles exactly one index (PRET `src/battle_main.c:2523-2536`) |
| `battle_not_link` | `gBattleTypeFlags` (write_checkpoint `battle_not_link`) | `& 0x02 == 0` | **essential**: in a link battle index 0 is not guaranteed to be the player and there is no rival team to replace |
| epoch (§3) | client-local | open + trainer id match | binds the reply to this battle |
| slots (§4) | `ram.BATTLER_PARTY_INDEXES_ADDR` + blobs | viability predicate | W2 only |

Do **not** add a `callback2 == CB2_HandleStartBattle` clause: `SetMainCallback2(BattleMainCB2)` at
`src/battle_main.c:1066` replaces it before the intro runs, so the equality would exclude exactly
the frames the window needs (0x08010509 vs 0x08011101).

Excluded, with what excludes it: the setup frames *before* `SetUpBattleVars` (no clause admits them
— the residual gap the probe measures); any post-`InitBattleControllers` frame without the
viability rule (W2's check); every intro frame from `DrawTrainersOrMonsSprites` on (the copy and
the first dex write are one frame); the send-outs and the second dex write; `TryDoEvents…`; the
input wait; every end-turn state; the overworld; link battles; wild battles (no trainer id).

**What ends up correct.** Under W1 and W2 the dex's *first* and *second* writes, `gBattleMons`
species/personality/otId/ability/types/stats/IVs/moves/PP/item/level/HP, `statStages` (DEFAULT) and
`status2` (0) all carry the partner's mon — the engine's own converter and copy do that work. A
W2 refusal, or any epoch/window refusal, leaves the rival's own team fully intact and untouched.

## 6. Dispatch is a frame-end write (MAJOR 2 note, minor 4)

(b) — swapping *between* the copy and the first dex write — is unavailable to a **frame-end**
writer: both live in one function body in one frame. It is not impossible for in-ROM code, which
is (c). (b′) — a post-copy refresh — is sound but its admissible range spans the *second* dex write
as well, so the dex keeps the original rival's species; it is a partial fix, not a design.

## 7. The old client's behaviour — withdrawn, now OPEN (MAJOR 3)

The earlier claim ("triggers at the hook", "~1-2 frames", "second battle onward", "the refresh is
redundant") was **not evidence-backed and is withdrawn**:

| what the old client actually does | cite |
|---|---|
| polls `M.isInBattle()` every frame and emits `trainer_battle_start` only after the same non-zero trainer id reads back identically for `TRAINER_STABLE_GATE = 2` **consecutive frames**, once per battle | `lua/clients/gen3_frlge_client.lua:1497-1504` (the gate and its comment: "gTrainerBattleOpponent_A is set in stages during CFRU battle init"), `:2329-2351`, poll at `:2058` |
| `M.isInBattle()` for CFRU is `gBattleOutcome == 0` and `gBattleMons[0].maxHP > 0` | `lua/memory_gba.lua:465-473` |
| `gBattleOutcome` is reset to 0 at the intro's start | PRET `src/battle_main.c:2265` (`BattleStartClearSetData`) |

Those three facts mean the old client cannot emit before `BattleStartClearSetData` and adds two
more frames on top, so its swap and refresh land *some* frames into the intro — but *where*
relative to the snapshot, the copy and the dex is **not established by static reading**, and its
production success must not be used as evidence for any timing claim. Settle it with the
`swap_window_margins` probe row (§8) on the shipped client; until then the old client explains
nothing about the new design.

## 8. Probe rows and negative controls

Witnesses (read directly, never through `safety`):

| witness | address | meaning |
|---|---|---|
| `battle_main_func` | `0x03004F84` | the phase value, compared against the C5-9 pins |
| `battle_comm` | `0x02023E82` + i | request index / scratch stages (shared — never a phase signal alone) |
| `battle_exec_flags` | `0x02023BC8` | a controller is mid-exec |
| `battle_outcome` | `0x02023E8A` | a resolved battle |
| `battler_party_indexes` | `ram.BATTLER_PARTY_INDEXES_ADDR` (+2, +6) | the preselected enemy slots — index 1 and 3 |
| `enemy_party_pid` / `enemy_party_species` | `gEnemyParty +0` (PID; PRET `include/pokemon.h:128-131`) / the decoded species | `+0` is the **PID**; the species witness must decode the mon |
| `buffer_payload_pid` | `gBattleBufferB[b]` (0x020233C4 + b*0x200) **+ 4 + 0x48** | the snapshot's personality, at the payload's own offset |
| `battle_mon_pid` / `battle_mon_species` | `gBattleMons` 0x02023BE4 + b*0x58, +0x48 / +0x00 | what the fight uses |
| `dex_seen` | the Pokédex seen flag | the release-side observable |
| `player_slot` | `gBattlerPartyIndexes[0]` | the request-walk cursor witness (see below) |

Row mechanics: the intro is transient, so the positive rows are driver rows (walk into the rival
battle, sample every frame, record frame indices); the negative rows are ordinary parked states
from the existing checkpoint fixtures and must name one of their `expect_clauses` (C3-24).

| row | state | expectation | expect_clauses | what it proves |
|---|---|---|---|---|
| `swap_pre_selection` | a driver stages the op while `gBattleMainFunc == BEGIN_BATTLE_INTRO_DUMMY_ADDR` | positive, W1 | — | the swap precedes the engine's own selection: the enemy index that the fight sends out resolves to the **partner's** mon, and the request-buffer payload carries the partner's PID |
| `swap_window_margins` | the same run, all witnesses stamped per frame | positive (timing receipt) | — | the frame deltas: signal → staging → the patch's blob write → the selection (`InitBattleControllers`) → the request for index 0 → for index 1 → the copy → the first dex write. This row is what makes any timing claim admissible — including the old client's |
| `swap_after_selection_viable` | the op staged at `BEGIN_BATTLE_INTRO_ADDR` with a staged team whose preselected slots are all viable, singles | positive, W2 | — | W2 works when the viability rule holds |
| `intro_request_zero` | the first request frame with the request index `0` | positive | — | the second clause's index is observable |
| `stale_epoch` | an op dispatched after `battle_end` (epoch closed) | negative | `stale_epoch` | a late reply cannot touch the next battle's party |
| `late_reply_next_battle` | battle *n*'s op delivered inside battle *n+1*'s window (same rival id) | negative (or the documented residual refusal) | `trainer_mismatch` / `window_closed` | the correlation contract; the same-id case is the residual §3 names |
| `invalid_slot_fainted` | W2, the preselected enemy index holds a fainted or egg mon in the staged team | negative | `slots_unviable` | the viability rule refuses instead of sending out an impossible mon |
| `invalid_slot_short_team` | W2, the staged team is shorter than the preselected index | negative | `slots_unviable` | the same, for an index past the team |
| `end_turn_idle` | the after-turn state (comm zeroed, exec idle, outcome 0, maxHP > 0) | negative | `intro_entry_dummy`, `intro_entry`, `intro_request_open` | **the row that refutes the C4-8 clause set** |
| `post_first_dex` | `gBattleMainFunc == BattleIntroDrawTrainersOrMonsSprites` (copy + first dex write) | negative | the three intro clauses | the copy/dex frame is out |
| `post_faint_replacement` | a faint mid-battle, the engine choosing the next mon | negative | the three intro clauses | the swap cannot run when the replacement is chosen; the replacement still comes from the swapped team because it was swapped pre-selection |
| `input_wait_refused` | `HandleTurnActionSelectionState` | negative | the three intro clauses | the rest frame of the battle is not an intro frame |
| `link_battle_refused` | a link battle at the same phase values | negative | `battle_not_link` | link exclusion is load-bearing |
| `wild_battle_refused` | a wild battle's intro | negative | the trainer/epoch gate | no trainer id, no epoch, no swap |

## 9. Open items

1. **RR selection pin** (`0x0904449D` / `0x09044531` CFru tails) — required before W2 is allowed on
   RR. W1 does not need it.
2. **The timing receipt** (`swap_window_margins`) — settles both the new design's margin and the
   old client's actual behaviour.
3. **A server-side request id** for the wire (`state.py:3052-3080`) — removes the same-rival-id
   ambiguity in §3.
4. **Doubles on RR**: the second enemy battler's predicate lives in the CFru tail; until it is
   enumerated, W2 refuses doubles on RR and W1 covers them.
5. **The dummy-value gap**: frames between `CB2_InitBattle`'s entry and `SetUpBattleVars` admit no
   clause; the probe should record how wide that gap is in practice relative to the op's latency.
