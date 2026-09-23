# The rival-swap window — redesign (P4 card C5-8, supersedes the C4-8 refresh design)

C4-8 designed a **Lua refresh** of `gBattleMons[1]`/`[3]` placed in a `battle_intro` write window
built from five *data* clauses (`gBattleCommunication[0] == 0`, exec flags idle, not link,
`gBattleOutcome == 0`, `gBattleMons[0].maxHP > 0`). Codex verified that window is **unsafe**, and
then that the refresh it guarded is **unsound**. This note replaces both the window and the
mechanism. Nothing here is implemented; the code landed for C5-8's first shape is reverted.

Grading vocabulary is `battle_write_predicate.md`'s: **PRET** (the pinned pokefirered checkout),
**SYM** (`data/gen3/pret/*.sym`; FR and LG agree on every address below), **RR-PROD** (an address
the shipped old client uses on RR and `data/games/gen3_rr/profile.json` carries), **INFER**.

## 1. Why the C4-8 window was unsafe (Codex's two findings, both confirmed)

| what | cite | consequence |
|---|---|---|
| `HandleEndTurn_ContinueBattle` waits for `gBattleControllerExecFlags == 0` and zeroes `gBattleCommunication` | PRET `src/battle_main.c:2929-2937`; `BattleTurnPassed` `src/battle_main.c:2980-2998` | in an ordinary continuing battle `outcome == 0` and `maxHP > 0` hold, so **all five clauses pass after every turn** |
| `MULTIUSE_STATE` is byte 0 of `gBattleCommunication` | PRET `include/constants/battle_script_commands.h:31` | comm0 is a *shared scratch stage*, not a phase signal: `CB2_HandleStartBattle` drives 0..16 with it (`src/battle_main.c:949-1067`), the intro uses it as its own stage counter |
| the dex deadline is **earlier** than C4-8 said: the first write is in `BattleIntroDrawTrainersOrMonsSprites`, not in `BattleIntroRecordMonsToDex` | PRET `src/battle_main.c:2611` vs `:2785` | a window that admits the post-dex frames is already past the thing it was protecting |

A one-shot latch does not save it: a delayed op or a late ACK lands mid-battle.

## 2. The corrected phase model (PRET, single trainer battle, non-link)

| # | phase | what happens | cite |
|---|---|---|---|
| 0 | `CB2_InitBattle` **entry** | the pack's `battle_begin` hook (the `trainer_battle_start` signal). `gEnemyParty` is **not yet the rival's** | `engine_signals.json` site `battle_begin`, `capture_offset 0`, contract: "Capture ENTRY before relocation, not an initialized party snapshot" |
| 1 | `CB2_InitBattleInternal` | `CreateNPCTrainerParty(&gEnemyParty[0], gTrainerBattleOpponent_A)` — the rival team lands; `SetWildMonHeldItem()` skips trainer battles outright | `src/battle_main.c:648,704-708`; `src/pokemon.c:6032-6036` (`BATTLE_TYPE_TRAINER` gate) |
| 2 | `CB2_HandleStartBattle` states 0..16 | windows/pals, `SetAllPlayersBerryData`, `InitBattleControllers` (which sets `gBattleMainFunc = BeginBattleIntro` per battle type), `BattleInitAllSprites` → `callback1 = BattleMainCB1`, `callback2 = BattleMainCB2` | `src/battle_main.c:934-1067`; `src/battle_controllers.c:88,113,150,175,213` |
| 3 | **`gBattleMainFunc == BeginBattleIntro`** | a stable parked value until `BattleMainCB1` first calls it; `BeginBattleIntro` clears battle data and sets `gBattleMainFunc = BattleIntroGetMonsData` | `src/battle_main.c:2196-2200` |
| 4 | **`BattleIntroGetMonsData`** — case 0 **per battler** | `BtlController_EmitGetMonData(BUFFER_A, REQUEST_ALL_BATTLE, 0)` + `MarkBattlerForControllerExec`; the controller (which runs *after* `gBattleMainFunc` in `BattleMainCB1`) fills `gBattleBufferB[gActiveBattler]` **from `gEnemyParty`** — this is the snapshot | `src/battle_main.c:2522-2542`; `src/battle_main.c:2203-2212` (`BattleMainCB1`); `src/battle_controller_opponent.c:246,255,450,466`. **RR:** the stage increments at `0x08012FD6..0x08012FDA` and resets at `0x08013018` (Codex, same sha1) |
| 5 | `BattleIntroPrepareBackgroundSlide` | a fade gate, then the copy phase | `src/battle_main.c:2544-2558` |
| 6 | **`BattleIntroDrawTrainersOrMonsSprites`** | in **one frame, one function body**: `gBattleMons[b] = gBattleBufferB[b][4..]` for every battler, then `type1/type2` from `gSpeciesInfo`, `ability = GetAbilityBySpecies(...)`, `statStages = DEFAULT_STAT_STAGE`, `status2 = 0`, and **the first dex write** `HandleSetPokedexFlag(... gBattleMons[b].species ..., gBattleMons[b].personality)`. Opponent side only for the trainer branch | `src/battle_main.c:2560-2637` (copy `:2576-2578`, ability/types `:2580-2582`, stat stages/status2 `:2585-2586`, dex `:2611`). **RR (Codex, staged ROM sha1 `b7d1e0756fcc66575878affc8f7b95c45386bb1c`):** the copy is kept at `0x080130FA..0x0801310E` (0x58 bytes from `gBattleBufferB`, pool `0x08013234` = `0x020233C4`), but the type/ability init that follows is CFRU's (jump at `0x08013144` → `0x090430A5`), so the RR field set must be enumerated from that branch, not assumed vanilla |
| 7 | `BattleIntroDrawPartySummaryScreens` … `BattleIntroPlayerSendsOutMonAnimation` | HP boxes, texts, send-outs; **`BattleIntroRecordMonsToDex`** writes the dex a *second* time from the same `gBattleMons` | `src/battle_main.c:2643,2692,2715,2725,2748,2769-2786,2803` |
| 8 | `TryDoEventsBeforeFirstTurn` → the input wait | the turn loop begins (`HandleTurnActionSelectionState`, then per-turn `HandleEndTurn_ContinueBattle`/`BattleTurnPassed`, each zeroing `gBattleCommunication`) | `src/battle_main.c:2831,2912,2929,2980`. **RR:** the same clear exists — `0x08013B1E` loads exec flags through pool `0x08013BB4` (`0x02023BC8`) and waits for zero, then `0x08013B2E` loads comm through pool `0x08013BC4` (`0x02023E82`) and `0x08013B30..3B3A` clears all 8 bytes (Codex, same sha1) — so C4-8's set admits every RR turn end too |

Two facts decide everything:

- **The snapshot (4) is what the later copy (6) consumes.** If the rival party is replaced after
  the snapshot, the copy restores the *old* team, and the dex writes then record the old species.
  If it is replaced **before** the snapshot, the snapshot, the copy, both dex writes, the send-out
  and the turn loop all carry the new team — nothing else needs to be written.
- **The copy and the first dex write are in the same frame's function body.** There is no
  inter-frame window between them for a Lua writer to use (a Lua write lands between frames).

## 3. What the old client actually did, and why RR rival swap works in production

`trainer_battle_start` (the `battle_begin` hook) → the server's `replace_rival_team` →
`lua/clients/gen3_frlge_client.lua:818-828` refuses unless `M.isInBattle()`, stages the blobs
(`:854`), and on `ST_OK` runs `M.refreshEnemyPartyNative` (`:2446-2458`) =
`refreshActiveEnemyBattlers` (`lua/memory_gba.lua:1699-1729`).

`M.isInBattle()` for CFRU is `gBattleOutcome == 0` **and** `gBattleMons[0].maxHP > 0`
(`lua/memory_gba.lua:465-473`). `gBattleMons[0].maxHP` is stale from the previous battle, so:

- **after some earlier battle in the session**, the gate is already true when the signal fires →
  the op is dispatched within ~1 frame of phase 0 and the patch's copy lands ~2-3 frames in →
  **before the snapshot at phase 4**, which is many frames later (states 0..16, palettes, the
  `PrepareBackgroundSlide` fade). The engine then carries the swap end to end. This is the
  production path, and it explains why the swap works.
- **in the session's first battle**, `gBattleMons[0]` is zero, so the gate reports "not in battle"
  and the client skips the swap entirely (`:825-828`, `error="not_in_battle"`). Untested on
  hardware as far as this note can tell; it is a refusal, not a mis-swap.

Its Lua refresh is therefore **redundant in the success case** (the buffer already carries the
swap; the refresh either rewrites identical data or is overwritten by identical data) and **cannot
repair the failure case** (if the op landed after the snapshot the refresh can still be undone by
phase 6 when it runs before it — Codex's finding — and after phase 6 the dex is already wrong).
It is a belt that can be undone by the engine's own copy.

## 4. The options

### (a) Land the swap before the snapshot — **recommended**

Replace `gEnemyParty` after phase 1 and before the enemy's request in phase 4, and let the engine
do everything (snapshot → copy → dex → send-out). No Lua game-state write, no new write reason:
the only bytes SLink writes are the mailbox ones the `native` reason already covers.

**Window (a positive discriminator, two clauses; nothing else is admitted):**

| clause | address | width | test | source |
|---|---|---|---|---|
| `battle_intro_entry` | `gBattleMainFunc` `0x03004F84` | 4 | `∈ { BeginBattleIntro\|1, BeginBattleIntroDummy\|1 }` (`0x080123C1`, `0x080123BD`) | SYM (`BeginBattleIntro` `0x080123C0`, `BeginBattleIntroDummy` `0x080123BC`); PRET `src/battle_main.c:2191,2196`; assignment per battle type `src/battle_controllers.c:88,113,150,175,213` |
| `battle_intro_request_open` | `gBattleMainFunc` `0x03004F84` + `gBattleCommunication` `0x02023E82` +1 | 4 + 1 | `== BattleIntroGetMonsData\|1` (`0x08012FAD`) **and** the per-battler request index `== 0` (only battler 0 has been asked for data) | SYM; PRET `src/battle_main.c:2522-2542` (`gBattleCommunication[1]` is the battler index) |

`callback2 == CB2_HandleStartBattle` (`0x08010509`) can be added as a cheap "we are in the battle's
own callback" clause, but it does not discriminate the intro (it holds for the whole battle) and is
not load-bearing.

**RR column** (Codex's binary evidence, staged ROM sha1 `b7d1e0756fcc66575878affc8f7b95c45386bb1c`).
The clause *addresses* are RR-PROD (`profile.ram.BATTLE_MAIN_FUNC_ADDR` = `0x03004F84`,
`profile.ram.BATTLE_COMM_ADDR` = `0x02023E82`), so the reads are the same two words. The two
*values* need an entry pin each: RR's data-request body is anchored at `0x08012FD6..0x08013018`
(and the copy at `0x080130FA..0x0801310E`), so pinning `BattleIntroGetMonsData`'s and
`BeginBattleIntro`'s entries by whole-body identity against the FR functions is the remaining
mechanical step. If an entry pin fails, **the RR reason refuses by name** — a refusal never swaps,
so the failure mode is "no rival swap on RR", not a wrong swap. The window's *negative* half is
already RR-proven: the end-turn clear (`0x08013B1E`, comm through `0x08013BC4`, bytes cleared at
`0x08013B30..3B3A`) is the exact state C4-8's five clauses admitted.

**Every excluded state**, with what excludes it:

| state | excluded by |
|---|---|
| phases 0..2 (`CB2_InitBattle` entry, `CreateNPCTrainerParty`, `HandleStartBattle` states 0..16 before `InitBattleControllers`) | no clause admits them: `gBattleMainFunc` is not yet an intro value. This is the residual gap the probe must measure (§5) |
| phase 4 with the enemy already asked for data (`comm[1] >= 1`) | `battle_intro_request_open` |
| phase 5 (`PrepareBackgroundSlide`), phase 6 (copy + first dex write), phase 7 (send-outs, second dex write), phase 8 (`TryDoEventsBeforeFirstTurn`) | neither clause |
| the input wait (`HandleTurnActionSelectionState` `0x08014040`), `BattleTurnPassed` `0x08013BD4`, `HandleEndTurn_ContinueBattle` `0x08013B1C`, `SetActionsAndBattlersTurnOrder`, `RunTurnActionsFunctions` | neither clause — this is the class the C4-8 set wrongly admitted |
| the overworld (and any non-battle state) | neither clause (both require intro values) |
| link battles (`BATTLE_TYPE_LINK`) | `gBattleTypeFlags` — a link battle's `gEnemyParty` is the other player's party; add a `battle_not_link` clause (`0x02022B4C & 0x02 == 0`) |
| wild battles | the same clause set admits the intro of a wild battle, but `replace_rival_team` is trainer-gated upstream (the pack's `battle_begin` consumer reads the opponent id; the server only sends the op for a rival trainer id) |

**What ends up correct under (a):** dex **seen entry = the partner's species**, `gBattleMons`
species **= the partner's**, `personality`/`otId` **= the partner's**, plus ability, types, stats,
IV/abilityNum dword, moves, PP, item, level, HP/maxHP, `statStages = DEFAULT_STAT_STAGE`,
`status2 = 0` — all written by the engine's own copy (`:2576-2586`), not reimplemented in Lua.
For RR the exact field set is CFRU's (the `0x08013144` → `0x090430A5` branch above), which is
precisely why the engine should write it: a Lua path would have to mirror code the patch owns.
That is the design's biggest advantage over C4-8: its refresh was a Lua re-implementation of
`REQUEST_ALL_BATTLE` plus three derived fields, and it had already drifted (below).

The pinning mechanics for RR's two window values are the ones the C4-8 handoff used for
`HandleTurnActionSelectionState` (`profile.rom`, whole-body byte identity via `verify_code` in
`tools/gen_gen3_write_checkpoint.py`); see the RR column above for the anchors and the
refuse-by-name fallback.

### (b) Swap between the copy and the first dex write — **refused: unreachable from Lua**

The copy (`:2576-2578`) and the dex write (`:2611`) are in the same function body executed in the
same frame (`src/battle_main.c:2560-2637`). A Lua write lands between frames, so no such window
exists for this design; only in-ROM code could hit it, which is (c). If it *were* hit, the dex,
species and personality would all end up the partner's (the copy's stale content is overwritten
before the dex reads it) — but it is not reachable, so it is not a design.

### (b′) A post-copy fallback refresh (what C4-8 was trying to be), for completeness

Admissible window: `gBattleMainFunc ∈ { BattleIntroDrawPartySummaryScreens, …,
TryDoEventsBeforeFirstTurn }` (`0x0801333C` … `0x0801385C`) — strictly after the copy, before the
turn loop, so a refresh there cannot be undone by a later `gBattleBufferB → gBattleMons` copy
(the only other copy is `Cmd_getswitchedmondata` on a switch-in, which writes the *incoming* mon).
Cost: **the dex keeps the original rival's species** (both dex writes already ran), and the Lua
must reimplement every field of `struct BattlePokemon`. Useful only if (a)'s window proves too
narrow in practice, and only as a partial fix.

### (c) A patch opcode that swaps inside the engine — G5 scope

An opcode executed from the engine's own battle-start path (e.g. right after
`CreateNPCTrainerParty`, `src/battle_main.c:707`) is the cleanest possible answer: it removes the
round-trip race entirely and keeps the dex correct. Costs: an ABI bump, a re-pin of the shipped
RR binaries, and C code that must build the same `gEnemyParty` shape the handler already builds.
Recommend it as the long-term fix, not now.

## 5. Recommendation

**(a)**, with the op dispatch (`native.lua`'s `transfer("enemy", …, valid)` hook, `post_stage` in
`lua/gen3/client.lua`) gated on the two clauses of §4(a); when the window is missed, the client
refuses by name and replies with the existing `refresh_failed` shape — the party is never touched,
so a refusal is always safe. No Lua `gBattleMons` write, no `battle_intro` write reason, no change
to `safety.lua`'s existing reasons.

Residual risk to measure before landing: the window's width. The op needs ~1-2 frames from the
signal to the blob write, and phases 0..2 occupy an unknown number of frames (DMA wait, palettes,
Berry data, `BattleInitAllSprites`). If phases 0..2 are shorter than the op's latency, (a) refuses
in practice and the answer is (c) — which is exactly what the probe below must decide.

## 6. Probe rows

Witnesses (all read directly, independent of `safety`):

| witness | address | meaning |
|---|---|---|
| `battle_main_func` | `0x03004F84` | the current phase (compare against the SYM values) |
| `battle_comm` | `0x02023E82` + i | per-battler / scratch stages (shared, so never a phase signal by itself) |
| `battle_exec_flags` | `0x02023BC8` | non-zero = a controller is mid-exec |
| `battle_outcome` | `0x02023E8A` | non-zero = resolved |
| `enemy_party_pers` | `gEnemyParty` `0x0202402C` + slot*100 | what the snapshot reads |
| `enemy_buffer_pers` | `gBattleBufferB` `0x020233C4` (SYM) + battler, mon offset +0x00 (personality) | the snapshot itself: equal to `enemy_party_pers` ⇒ the snapshot matches the current party, different ⇒ stale |
| `battle_mon_pers` | `gBattleMons` `0x02023BE4` + 0x58 + 0x48 | what the fight uses |
| `dex_seen` | the Pokédex seen flag for the recorded species | the release-side observable |

| row | state | expectation | expect_clauses | artifacts | what it proves |
|---|---|---|---|---|---|
| `intro_entry` | a driver parked at the `BeginBattleIntro` frames (a savestate taken during the intro; no parked fixture exists yet) | positive for the window | — | firered/clean, leafgreen/clean, radical_red/companion | `battle_intro_entry` admits a real pre-snapshot frame, and `enemy_buffer_pers != enemy_party_pers` there (the snapshot has not run) |
| `intro_request_zero` | the first `BattleIntroGetMonsData` frame, `comm[1] == 0` | positive | — | as above | the second clause's per-battler index is observable and sane |
| `intro_after_copy` | `main_func == DrawTrainersOrMonsSprites`, the frame after the copy | negative | `battle_intro_entry`, `battle_intro_request_open` | as above | the copy/dex frame is refused |
| `intro_after_dex` | `main_func == BattleIntroRecordMonsToDex` | negative | as above | as above | the post-dex frames are refused |
| `turn_end_idle` | the after-turn state: `comm` zeroed, exec flags idle, `outcome == 0`, `maxHP > 0` (`HandleEndTurn_ContinueBattle`/`BattleTurnPassed`) | negative | `battle_intro_entry`, `battle_intro_request_open` | firered/clean, leafgreen/clean, radical_red/companion | **the row that refutes C4-8's five-clause set** (all five pass there) |
| `input_wait_refused` | the action-selection input wait (`HandleTurnActionSelectionState`) | negative | as above | as above | the rest frame of the battle is not an intro frame |
| `swap_before_snapshot` | a driver walks into a rival battle with the op staged at `intro_entry` | positive for the invariant | — | radical_red/companion | over the intro's frames: `enemy_party_pers` flips to the partner's **before** `enemy_buffer_pers` is first filled, and `enemy_buffer_pers == enemy_party_pers` at the copy; `battle_mon_pers` and `dex_seen` then carry the partner |
| `swap_missed_refusal` | the same driver, the op delayed past `intro_request_zero` | negative | `battle_intro_request_open` | radical_red/companion | the refusal path fires and `gEnemyParty` is untouched (`enemy_party_pers` stays the rival's) |

Mechanics: the intro is transient, so `intro_entry`/`intro_request_zero`/`swap_*` cannot use
`probe_gen3_checkpoint.lua`'s parked states as-is — they need a savestate captured *during* an
intro, or the driver harness (`tests/gen3/probes/`) sampling every frame. The negative rows
(`intro_after_copy`, `intro_after_dex`, `turn_end_idle`, `input_wait_refused`) are ordinary parked
states and can reuse the existing checkpoint fixtures. Each negative refusal must name one of its
`expect_clauses` (the C3-24 rule). The `turn_end_idle` and `input_wait_refused` rows carry the
regression that the C4-8 clause set failed, and must be run for **every** artifact that has a
battle fixture.

## 7. Open items

1. **The window's width** (§5) — the one measurement that decides (a) vs (c).
2. **RR pinning** of the window's two `gBattleMainFunc` values (`BeginBattleIntro|1`,
   `BattleIntroGetMonsData|1`). Codex's anchors place the RR bodies (`0x08012FD6..0x08013018` for
   the data request, `0x080130FA..0x0801310E` for the copy), so the remaining step is the entry
   address: whole-body byte identity against the FR function (`verify_code` in
   `tools/gen_gen3_write_checkpoint.py`), and if the body differs, refuse the reason by name for RR
   rather than reusing the FR value unproven. RR's end-turn clear and copy are both confirmed, so
   the *negative* half of the window is proven even if the entry pin fails.
3. **The first-battle stale gate.** The old client's `isInBattle()` reads a stale
   `gBattleMons[0].maxHP`, so its production path may skip the session's first rival battle. The
   new client's window clauses are data-driven and do not depend on that staleness; the probe
   should confirm the client can now swap in the first battle of a session.
4. **Doubles**: the enemy partner is battler 3 and is asked for data in the same per-battler walk;
   a doubles rival battle has not been witnessed on RR.
5. **C4-8's refresh is not merely redundant**: it reimplements `REQUEST_ALL_BATTLE` in Lua and
   already differs from pret in two places — it writes `ppBonuses` at `+0x3A`
   (`lua/memory_gba.lua:1689`, which is `nickname[10]`; pret puts `ppBonuses` at `+0x3B`,
   `include/pokemon.h` `struct BattlePokemon`), and it clears 7 of the 8 `statStages`
   (`:1670-1671`, `for i = 0, 6`; pret `NUM_BATTLE_STATS = NUM_STATS + 2` = 8,
   `include/constants/pokemon.h:178`). Both are arguments for (a), where
   the engine writes those fields itself.
