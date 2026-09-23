# The rival-swap refresh window — design (P4 card C4-B, `battle_write_predicate.md` §7.6)

Question: `OP_SET_ENEMY_PARTY` is safe at the `native` clause set (idle mailbox, any phase), but
the post-op refresh — the old client's `refreshEnemyPartyNative` writing `gBattleMons[1]`/`[3]`
from `gEnemyParty` (`lua/memory_gba.lua:1699,1720`) — is a game-state write that must land in the
battle's first frames. Which frames, exactly, and on whose evidence?

Grading vocabulary is `battle_write_predicate.md`'s: **PRET** (the pinned pokefirered checkout),
**SYM** (`data/gen3/pret/pokefirered.sym`), **RR-PROD** (an address the shipped old client uses on
RR in production, which `data/games/gen3_rr/profile.json` also carries), **INFER**.

## 1. The battle-start frame, in order (pret)

| # | what | cite |
|---|---|---|
| 1 | `CB2_InitBattle` entry — **where the pack's `battle_begin` hook fires** | `battle_main.c:612`; `data/games/gen3_rr/engine_signals.json`, site `battle_begin`, `capture_offset 0`, contract: "Capture ENTRY before relocation, **not an initialized party snapshot**" |
| 2 | `CB2_InitBattleInternal` → `CreateNPCTrainerParty(&gEnemyParty[0], gTrainerBattleOpponent_A)` | `battle_main.c:648,707` |
| 3 | `CB2_HandleStartBattle` (next frames) → `BeginBattleIntro` → `BattleStartClearSetData` zeroes `gBattleCommunication[i]` → `gBattleMainFunc = BattleIntroGetMonsData` | `battle_main.c:2196-2200,2211,2272` |
| 4 | **the intro's party → `gBattleMons` copy**, all battlers; the opponent controller fills from `gEnemyParty[gBattlerPartyIndexes[...]]` | `battle_main.c:2200`; `battle_controller_opponent.c:246,255` |
| 5 | intro phases: `BattleIntroPrepareBackgroundSlide` :2534, `...DrawTrainersOrMonsSprites` :2549, `...DrawPartySummaryScreens` :2643, `...PrintTrainerWantsToBattle` :2692, `...PrintOpponentSendsOut` :2725, `...OpponentSendsOutMonAnimation` :2748, `...RecordMonsToDex` :2769, `...PlayerSendsOutMonAnimation` :2803 | `battle_main.c` (SYM: `0x08013070`, `0x0801333c`, `0x08013568`) |
| 6 | `TryDoEventsBeforeFirstTurn` :2831 → the input wait (`HandleTurnActionSelectionState`, `gBattleCommunication[0] == 1`) | `battle_main.c:2831`; predicate doc §3.1 |

Two consequences the earlier note did not have:

- **At the signal (1) `gEnemyParty` is not yet the rival's** — the pack's own capture contract says
  so, and `CreateNPCTrainerParty` runs one line later *inside the same frame*. An op consumed
  before that would be clobbered. The op cannot be: a staged op is consumed by the patch's hook on
  the **next** frame's `CallCallbacks`, and the old client additionally refuses to act unless it is
  already `in_battle` (`lua/clients/gen3_frlge_client.lua:818-828`, `error="not_in_battle"`). Keep
  that gate; it is not decoration.
- **The refresh is a race with (4), and (4) is the engine doing the same job.** If the op's blobs
  land before `BattleIntroGetMonsData` copies them, the engine's own copy *is* the refresh and the
  Lua write is redundant — but the op arrives on a ≥1-frame round trip and (4) is a multi-frame
  state machine, so neither ordering can be assumed. The Lua refresh is therefore required in
  *both* cases, and it is **idempotent**: when (4) already saw the swapped party it writes back the
  values it read.

## 2. What each reader actually reads (this is the deadline)

| reader | reads | cite | consequence |
|---|---|---|---|
| HP box HP/nickname | `&gEnemyParty[gBattlerPartyIndexes[i]]` | `battle_interface.c:992,1044-1054` | the *display* is correct with **no** refresh — the swap already moved the party |
| Pokédex "seen" entry | `gBattleMons[gActiveBattler].species` / `.personality` | `battle_main.c:2785` | **a hard, player-visible deadline**: miss it and the dex records the original rival species |
| turn order, AI, damage, type, ability, move script | `gBattleMons[battler]` | predicate doc §2.4 | the actual fight is wrong until the refresh lands |
| `SwapHpBarsWithHpText` | `&gEnemyParty[...]` | `battle_interface.c:992` | so the old note's "before the first send-out" is about the *fight*, not the picture |

So the deadline is not the send-out animation (`:2748`/`:2803`) but `BattleIntroRecordMonsToDex`
(`:2769`, writing from `gBattleMons` at `:2785`) and, at the latest, the first `gBattleMons` read
of the input wait.

## 3. The window: `battle_intro`

The `battle_main_func` clause of `battle_input` compares against a **FireRed code address**
(`HandleTurnActionSelectionState|1`), and entry 5 above is FireRed code too — CFRU rewrites the
intro, so no code comparison can carry RR. The window therefore has to be defined from **data**,
and all six addresses below are in `data/games/gen3_rr/profile.json` (`ram.BATTLE_COMM_ADDR`,
`ram.BATTLE_CONTROLLER_EXEC_FLAGS_ADDR`, `ram.BATTLE_TYPE_ADDR`, `ram.BATTLE_MONS_ADDR`,
`ram.BATTLE_OUTCOME_ADDR`) and used by the shipped client on RR (RR-PROD).

| clause | address | width | test | source |
|---|---|---|---|---|
| `battle_comm_0_zero` | `gBattleCommunication` `0x02023E82` +0 | 1 | `== 0` | PRET `battle_main.c:2211,2272` (`BattleStartClearSetData` zeroes the array at battle start; the first single-battle write is the input wait's `1` at `:3140-3151`); RR-PROD address |
| `battle_exec_flags_idle` | `gBattleControllerExecFlags` `0x02023BC8` | 4 | `== 0` | PRET `battle_controllers.c:600-616`; RR-PROD |
| `battle_not_link` | `gBattleTypeFlags` `0x02022B4C` | 4 | `& 0x02 == 0` | PRET `include/constants/battle.h:48`; RR-PROD |
| `battle_engine_loaded` | `gBattleMons` `0x02023BE4` +`0x2C` | 2 | `> 0` | RR-PROD `lua/memory_gba.lua:465-473`; INFER for FR/LG (see §6.2) |
| `battle_outcome_open` | `gBattleOutcome` `0x02023E8A` | 1 | `== 0` | RR-PROD `lua/memory_gba.lua:472`; PRET `battle_main.c:3706` |

`battle_comm_0_zero` + `battle_outcome_open` are what separate the intro from the overworld:
`gBattleCommunication[0]` is left at the state machine's last value after a battle and
`gBattleOutcome` is stale non-zero in CFRU (the safe-state doc's three-condition model), so the
pair holds only inside a live battle before its "action chosen" state. `battle_comm_0 == 0` also
covers the whole intro (entries 3-6) — including `BattleIntroRecordMonsToDex` — while the input
wait is excluded by construction.

Reason name in the client: **`battle_intro`** (its own clause set; the `policy.check(snap, reason)`
seam already carries the reason, and `safety.lua` selects the set per reason).

## 4. The old client's production timing (the trusted side)

| step | cite |
|---|---|
| `replace_rival_team` arrives → refuse unless `M.isInBattle()` | `lua/clients/gen3_frlge_client.lua:818-828` |
| stage the blobs, dispatch `OP_SET_ENEMY_PARTY` | `:854` |
| consume on `ST_OK` → `M.refreshEnemyPartyNative(#blobs)` | `:2446-2458` (refresh at `:2451`) |
| the refresh itself: `refreshActiveEnemyBattlers` re-populates `gBattleMons[1]`/`[3]` field-by-field (species, item, moves, PP, PP bonuses, ability) via `_refreshBattleMonFromPartyAddr` | `lua/memory_gba.lua:1699,1720,1621` |
| timeout fallback (`ENEMY_PARTY_TIMEOUT`) → ack with an error, no fallback write | `:2458` |

The old client writes on "in battle", which by §1 lands somewhere in the intro-or-input region, and
it has worked in play — but it never *checked* the window, so its success is evidence that the
window is *reachable*, not that it is *bounded*. `battle_intro` makes the bound explicit.

## 5. Option (B): a patch opcode that does the refresh

Feasible: for the **enemy** party CFRU stores mons NO_ENCRYPT (`patch/src/handlers.c:1875-1880`), so
the C side is a straight field copy from the staged `SLINK_BLOB_BUF` into the BattlePokemon struct
— no decrypt, unlike the Lua path which has to go through `decryptSpecies`/`decryptMoves`.

Two reasons not to pick it now:

1. **It does not remove the timing constraint.** The opcode still executes at the hook's
   consumption moment (≥1 frame after staging), i.e. the same race against entry 4, so
   `battle_intro` (or its equivalent) is needed either way. (B) moves *who* writes, not *when*.
2. It costs an ABI bump, a re-pin of the shipped RR binaries, and a C port of a field mapping that
   already exists and is exercised in Lua.

(B) stays the cleaner long-term answer if the client is ever to hold no game-state write at all;
that is a G4/G5 call, not this design's.

## 6. Recommendation

**Adopt (A): reason `battle_intro` (the five clauses in §3) + the Lua refresh, one-shot per battle.**

1. Gate the *staging* on the battle-start signal **and** `in_battle` (keep `:818-828`'s rule).
2. When the op acks `ST_OK`, run the refresh under `battle_intro`; latch it per battle (one write
   per battler, not a per-frame re-write — the engine's own copy at entry 4 must not be fought).
3. Keep the ack's species readback (`rival_team_replaced`) as the observable, and read it from
   `gEnemyParty` **and** `gBattleMons[1].species` so the ack is evidence for both sides.
4. Do not wait for the send-out animation as the deadline; the deadline is entry 5's
   `BattleIntroRecordMonsToDex` (`battle_main.c:2769,2785`).

### 6.1 Probe rows (C3-24 shape: `expectation`, `expect_clauses`, `min_samples`, `artifacts`)

| witness | address | meaning |
|---|---|---|
| `battle_comm_0` | `0x02023E82` | 0 = intro window (per `BattleStartClearSetData`), 1 = input wait |
| `battle_exec_flags` | `0x02023BC8` | non-zero = a controller is mid-exec |
| `battle_outcome` | `0x02023E8A` | non-zero = resolved |
| `battle_mons_foe_species` | `0x02023BE4 + 0x58` (battler 1) | what the fight will actually use |
| `enemy_party_species` | `gEnemyParty` +0 (`0x0202402C`, battler `gBattlerPartyIndexes[1]`) | what the display and the intro copy read |
| `dex_seen_species` | the Pokédex seen flag for the recorded species | entry 5's observable |

| row | state | expectation | expect_clauses | artifacts | what it proves |
|---|---|---|---|---|---|
| `rival_intro_window` | a driver walks into a rival battle; sample every frame | positive | — | radical_red/companion (needs the patch, since the op must exist) | `battle_comm_0_zero` + `battle_outcome_open` hold for a real intro, with a non-IRQ denominator |
| `rival_intro_after_swap` | the same run, after the op ack | positive | — | as above | `battle_mons_foe_species == enemy_party_species == the partner's species` — the refresh landed and entry 4's copy is not stale |
| `rival_intro_input_wait` | the same battle once the menu is up | negative for `battle_intro` | `battle_comm_0_zero` | as above | the window closes at the input wait |
| `rival_intro_overworld` | engine idle in the overworld right after the battle | negative for `battle_intro` | `battle_outcome_open` | as above | stale comm/outcome values do not re-open the window |
| `rival_intro_dex` | the same run, dex screen after the fight | positive | — | as above | the *seen* entry is the partner's species — the deadline that makes the window matter |

Mechanics: the intro is transient, so these rows cannot park on a savestate the way
`battle_input_wild` does — they run as a driver row (walk in, sample, walk out), and the tally must
carry the frame index so the window's *width* is recorded, not just its existence.

### 6.2 Open / grading

1. **RR provenance for `battle_comm_0_zero`'s expected value.** The address is RR-PROD; that the
   array is 0 through the *CFRU* intro is INFER until `rival_intro_window` admits it (CFRU rewrites
   the intro; the old client only relies on `== 1` at the input wait).
2. **`battle_engine_loaded` admits stale data.** `gBattleMons` is a static array that is not cleared
   at battle start, so `maxHP > 0` can hold from the previous battle — it is redundant here and must
   not be the *only* evidence for "this battle's data is loaded" (the predicate doc's INFER stands).
3. **The op's consumption frame is an invariant, not a proof.** §1's "the op cannot be consumed in
   the same frame it is staged" rests on the patch's hook being a once-per-frame `CallCallbacks`
   site; if a hook on another site were used, entry 2 would clobber the swap. The `in_battle` gate
   is the defence; a row that stages an op *at* the signal frame would settle it.
4. **Doubles.** `gBattleMons[3]` is battler 3; the rows above sample battler 1 only. A doubles
   rival battle has not been witnessed on RR.
5. **No savestate can hold the intro**, so `rival_intro_*` rows need the driver harness
   (`tests/gen3/probes/*`) rather than `lua/tests/probe_gen3_checkpoint.lua`'s parked states.
