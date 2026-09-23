# The rival-swap window — revised contract (P4 card C5-8d, after Codex REV-5)

C5-8's redesign accepted the ordering claim (a swap that lands before the opponent controller's
snapshot is carried by the engine end to end) but was **rejected as specified**. Three majors and
five minors are folded in below. The window values are the C5-9 pins. Doc-only: no code.

C5-8d folds in Codex REV-5's remaining items: the rival swap gets its **own opcode** (16 stays
the trade's), the window check lives in the **patch** at consumption with link and trainer context,
**W2 is deferred**, and §3.3 restates the identity contract as built (nonce + counter + the
`battle_identity` capability). Earlier: two owner rulings (PLAN §0, 2026-09-23): the server tags every `replace_rival_team`
with a **battle request id** that the client must match (§3.3), and the **RR patch enforces the
window at consumption** (§5.3), which makes the patch the authority and the Lua guard a
pre-filter. Three Codex REV-4 majors are folded in: the W1 trailing edge (§5.2, with the
counter-evidence I could read), the request-id/epoch equality and the queued-blob staleness (§3.3),
and the selectable-team precondition (§4.3). Doc-only.

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

## 3. Battle epoch, request id and recipient binding (MAJOR 1 + owner ruling 1)

As shipped, the wire carries no epoch or request id: `queue_rival_team_swap` emits
`{cmd, trainer_id, n, blobs_hex, source}` (`server/state.py:3052-3080`) with the blobs frozen at
queue time, and the blob cache validates *shape* only (`state.py:3026-3046`). The owner ruling adds
one (§3.3); until that card lands, the client-local correlation below is the only defence, and it is
weaker exactly where §3.3 says — same-rival consecutive battles.

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
3. the selectable-team rule of §4.3 passes — for **every** tier, W1 included (§4.3), else
   refuse `slots_unviable`.

A refusal never writes, so the rival keeps its own team: the failure mode is "no swap", never a
half-swap.

**Late replies (§3.3, owner ruling 1).** `trainer_id` alone cannot tell two consecutive battles
against the same rival apart, and the command carries the blobs *frozen at queue time*
(`queue_rival_team_swap` writes `blobs_hex` into the queued command, `server/state.py:3074-3079`),
so a late same-rival reply can carry arbitrarily old party data. The owner's ruling closes this
with a battle request id. The contract:

| step | who | what |
|---|---|---|
| mint | **client** | when it emits `trainer_battle_start`, it emits **both halves**: `session` (a nonce minted once per client PROCESS — seeded by the bootstrap, `lua/gen3/run.lua`, from wall clock + process CPU clock + a random draw + the ROM hash) and `battle_id` (a counter bumped on every battle-begin signal, §3.1). A reconnect inside the same process keeps both; only a restart re-mints the nonce. **The counter alone is not the identity** (Codex REV-5): a restarted session's battle 1 and a previous session's battle 1 are both 1, so a command queued for the old session would pass; the nonce is what makes that impossible. |
| echo | **server** | `_handle_trainer_battle_start` stores the latest `(session, battle_id, trainer_id)` per player and passes the pair through `queue_rival_team_swap` into the command as `"session"` + `"battle_id"` (`{cmd, trainer_id, session, battle_id, n, blobs_hex, source}`). The pair is copied into the queued command and **never retagged** — a command always carries the identity it was created for. For the dashboard's manual inject (`source='manual'`) the server uses the latest stored pair. |
| check | **client** | at dispatch: the epoch is open, `cmd.session == epoch.session` (this process's nonce), `cmd.battle_id == epoch.battle_id`, `cmd.battle_id` is an integral number, and — when both sides name one — the trainer ids match. Missing, malformed, other-session or mismatched → refuse. |
| reply | **client** | `rival_team_replaced{trainer_id, species_ids = {}, error = "stale_battle_id"}` and nothing is written (the rival keeps its own team). |
| capability | **client → server** | the new client declares `battle_identity: true` in its hello. The server refuses an identity-less **manual** inject only for a client that declared it: Gen 1, Gen 2 and the old Gen 3 RR client (which stays the production RR client until the patch card lands) keep the pre-card behaviour and get a command with neither field. Capability is never inferred from anything else, and a restart of the server is covered because the dropped connection makes the client re-hello. |
| protocol | `docs/protocol.md` | the `trainer_battle_start` event row carries `session` + `battle_id` (minted per battle-begin, echoed on every command of that battle, refused on mismatch); the `replace_rival_team` row carries the optional pair; `rival_team_replaced` gained `stale_battle_id`; hello gained `battle_identity`; §9 item 45a records all of it. |

Job epoch equality (Codex REV-4): the *job* is bound to the epoch that existed when it was
queued, not merely to a live epoch — the guard therefore compares the command's `battle_id`
against the epoch id, and the epoch object is replaced (not mutated) on every battle-begin so a
stale closure cannot pass. The window itself still closes at the opponent's data request (§5),
which bounds the *useful* part of the epoch.

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
  then selects the swapped team's slots itself — correct for singles *and* doubles — **and it still
  needs §4.3's selectable-team precondition**: moving the selection to the replacement means the
  replacement has to be selectable. §4.3 is not a W2-only rule (C5-8d corrected an earlier draft
  that said so).
- **W2 — land after the selection and validate it — DEFERRED (C5-8d).** The patch's consumption
  predicate (§5.3) is W1-only: it proves "before the selection", which is precisely what W2 is
  *not*. W2 is therefore unavailable until it has its own consumption predicate (e.g. a phase value
  strictly after `BattleIntroDrawTrainersOrMonsSprites`), and nothing in this design may rely on
  it. The bullet below is what such a predicate would have to validate. Admitted only when every
  preselected enemy index is viable **in the replacement**: for each enemy battler
  (`gBattlerPartyIndexes[1]`, plus `[3]` when `gBattlersCount >= 4`),
  `idx < n`, and the staged blob at `idx` satisfies the same predicate the engine used
  (HP ≠ 0, species ∉ {NONE, EGG}, not an egg, and `[3] != [1]`). The blobs are in hand (the
  command carries `blobs_hex`), so this is a decode-only check; if any fails, refuse
  (`slots_unviable`) — a refusal keeps the rival's own team.
- **Re-running the selection ourselves** (writing `gBattlerPartyIndexes`) is *not* recommended:
  it adds a second game-state write with its own window and its own risk of disagreeing with the
  engine's later reads.

**Doubles** are covered by W1 (the engine's own selection), with §4.3's two-viable precondition;
W2's doubles half is deferred with W2.

**W2's rule is *eligibility*, not selection order (Codex REV-4).** `SetBattlePartyIds` picks the
*first* viable slot per battler and stores that index; after a swap the stored index is what the
engine keeps using, so W2 (in its deferred form) would only have to prove that index is still
*eligible* in the replacement
(`HP != 0`, `species ∉ {SPECIES_NONE, SPECIES_EGG}` with `SPECIES_EGG = 412`
(PRET `include/constants/species.h:421`), not an egg, and distinct from the other battler's index
in doubles). It does **not** have to be the replacement's first viable slot, and must not be
computed that way.

### 4.3 The replacement must offer a selectable team (Codex REV-4 major 3)

W1 does not escape the engine's selection: it moves the *selection* to the swapped party, so the
swapped party has to be selectable. `OP_SET_ENEMY_PARTY` clears only the *unused* trailing slots'
`maxHP` (the count terminator), so the used slots keep the blobs' own HP — a blob with `hp == 0`
is skipped by the scan like any fainted party mon.

| battle shape | the replacement must have | refusal |
|---|---|---|
| singles | ≥ 1 enemy mon eligible by the engine's predicate | `slots_unviable` (nothing written) |
| doubles | ≥ 2 **distinct** eligible enemy mons (the second battler's scan excludes the first's index) | `slots_unviable` |

**The predicate is the engine *getter's* semantics, not a raw header bit (C5-8d).** The engine
asks `GetMonData(&gEnemyParty[j], MON_DATA_SPECIES_OR_EGG)`, which returns `species` except when
`species != 0 && (Misc.isEgg || boxMon.isBadEgg)`, in which case it returns `SPECIES_EGG`
(PRET `src/pokemon.c:3245-3249`) — so an empty slot, an egg **and a bad egg** all fail it — plus
`MON_DATA_HP != 0` and `MON_DATA_IS_EGG == 0` (`src/battle_controllers.c:306-320,341-347`). The Lua
side must reproduce *that*, not a decoded header bit: `lua/gen3/reads.lua`'s `decode_party_mon`
yields `hp`, `species`, `is_egg_flag` and `is_bad_egg` (`lua/gen3/reads.lua:238-276`), and the rule
is `hp != 0 and species != 0 and not is_egg_flag and not is_bad_egg`.

The check is decode-only: the command carries `blobs_hex`, and `lua/gen3/reads.lua`'s
`decode_party_mon` already yields those fields. It runs
in the same dispatch guard as the window clauses, for **both** tiers, because it is a property of
the request rather than of the window. RR's own selection stub (`0x0904449D`) remains OPEN — but
this precondition does not depend on it: it reuses pret's eligibility rule, which RR inherits for
the *loop* (only the tail is CFRU code, §4.2).

**RR pinning of the selection path — OPEN, with the target located.** RR-BIN: `InitBattleControllers`
is byte-identical to FR (88 bytes), but `SetBattlePartyIds`' tail is a CFRU stub
(`00 48 00 47` + pool `0x0904449D` at FR body `+0x138`), and `InitSinglePlayerBtlControllers`' tail
likewise (`0x09044531`). So the *call order* is pinned and the *viability predicate* is CFRU code
that must be enumerated from `0x0904449D` before W2 is used on RR. Until then: **W2 is unavailable
on RR** (the reason refuses by name) and **W1 carries RR**, because W1 never depends on the
predicate.

## 5. The window (with the C5-9 pin names), and the patch as authority

| clause | field / source | test | why it is in the set |
|---|---|---|---|
| `intro_entry_dummy` | `rom.BEGIN_BATTLE_INTRO_DUMMY_ADDR` (0x080123BD) | `gBattleMainFunc == 0x080123BD` | **W1**: set by `SetUpBattleVars` (PRET `src/battle_controllers.c:44`, called at `src/battle_main.c:699`) and live until case 15 sets `BeginBattleIntro`; the op's blob write lands at the next `CallCallbacks`, i.e. after `CreateNPCTrainerParty` (`:707`) and at least one frame before `InitBattleControllers`/`SetBattlePartyIds` |
| `intro_entry` | `rom.BEGIN_BATTLE_INTRO_ADDR` (0x080123C1) | `gBattleMainFunc == 0x080123C1` | **W2**: set inside `InitBattleControllers` (PRET `src/battle_controllers.c:113`), i.e. *after* the selection — requires §4's viability rule |
| `intro_request_open` | `rom.BATTLE_INTRO_GET_MONS_DATA_ADDR` (0x08012FAD) and `ram.BATTLE_COMM_ADDR + 1` (0x02023E83) | `gBattleMainFunc == 0x08012FAD` **and** the per-battler request index `== 0` | the request walk starts at index 0 (the player), so the enemy's snapshot has not been requested; each invocation handles exactly one index (PRET `src/battle_main.c:2523-2536`) |
| `battle_not_link` | `gBattleTypeFlags` (write_checkpoint `battle_not_link`) | `& 0x02 == 0` | **essential**: in a link battle index 0 is not guaranteed to be the player and there is no rival team to replace |
| epoch (§3) | client-local | open + trainer id match | binds the reply to this battle |
| slots (§4.3) | the staged blobs (decode-only) | selectable-team rule | **every tier** |
| link | `gBattleTypeFlags` (write_checkpoint `battle_not_link`) | `& 0x02 == 0` | Lua pre-filter AND the patch (§5.3) |

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

### 5.2 W1's trailing edge (Codex REV-4 major 1)

The concern: case 15 could be suspended inside `InitBattleControllers` with `gBattleMainFunc` still
`BeginBattleIntroDummy`; a frame-end Lua guard would then admit the swap, the *current* callback
would run `SetBattlePartyIds` on the old party, and only the next `CallCallbacks` would consume it.

What the FR/LG source says (PRET `src/battle_controllers.c:66-82`): `InitBattleControllers` is
straight-line — `InitLinkBtlControllers`/`InitSinglePlayerBtlControllers()`, **then**
`SetBattlePartyIds()`, **then** the `BufferBattlePartyCurrentOrderBySide` loop. No state argument,
no early return, no re-entry. `InitSinglePlayerBtlControllers` writes
`gBattleMainFunc = BeginBattleIntro` at its very top (`:113`), i.e. *inside* the same call and
*before* the selection. So once the selection has run, the phase value is `BeginBattleIntro`, never
`Dummy`: if the client observes `Dummy` at the end of frame *F*, `InitBattleControllers` did not run
in *F*, and the op is consumed at frame *F+1*'s `slink_hook` (`0x0800051A`) which the REV-3 review
placed *before* the callback1/callback2 dispatch — so the selection, whenever it does run, sees the
swapped party. RR keeps this: `InitBattleControllers` is byte-identical to FR on RR (88 bytes,
RR-PIN).

The concern still has one honest foothold: CFRU replaces the *tails* of `SetBattlePartyIds`
(`0x0904449D`) and `InitSinglePlayerBtlControllers` (`0x09044531`) with stubs (RR-BIN, measured), so
a CFRU-only wait between the phase write and the selection cannot be excluded by FR source.

**Codex's resolution (REV-5), recorded here as the accepted reading.** My source reading is not
disputed: the two operations are in one straight-line call, the phase store first. What it does not
do is *prove atomicity as the client observes it* — the emulator can stop the CPU mid-call (a
savestate, a frame-advance, a debugger halt, or a CFRU-only wait inside one of the stubs) after
`SetUpBattleVars` set `Dummy` and before `InitBattleControllers` stores `BeginBattleIntro`, and a
frame-end hook that then publishes an op is admitted by a Lua-only guard while the resumed call
still runs the selection on the old party. So the ordering argument is *evidence about the normal
path*, not a guarantee; the patch-side check of §5.3 covers the interrupted path by construction,
which is why it is the authority and the Lua clause set is only a pre-filter.

### 5.3 The rival swap gets its OWN opcode (REV-5 blocker 2), and the patch enforces the window

`OP_SET_ENEMY_PARTY` is **shared**: the field trade stages the partner's mon with it and then runs
the scene — `transfer("enemy")` from `lua/gen3/client.lua:1017-1026` reaches
`native:transfer("enemy", …)`, which is `OP_SET_ENEMY_PARTY` + `BLOB_BUF`
(`lua/gen3/native.lua:224-245`), and the scene handler itself documents the dependency: "trades
`gPlayerParty[slot]` with the mon staged in `gEnemyParty[0]` (caller must OP_SET_ENEMY_PARTY count=1
first)" (`patch/src/handlers.c:1993-1998`). A window check on opcode 16 would therefore reject every
trade. The rival swap gets its own opcode:

| item | value |
|---|---|
| name / number | `OP_RIVAL_SWAP = 28` — the enum's current maximum is `OP_SHOW_INFO = 27` (`patch/src/handlers.c:52-53`) |
| args | `args[0] = count` (1..6), `args[1] = trainer_id` (the trainer the client announced) |
| staging | identical to 16: `count` × 100 raw party-mon bytes in `BLOB_BUF`, no Lua-side gating of the stage |
| `OP_SET_ENEMY_PARTY` (16) | **unchanged**, still the trade's transport, no window check, no trainer context |
| profile / Lua | the key `OP_RIVAL_SWAP` joins the profile's `native` block next to `OP_SET_ENEMY_PARTY` (`data/games/gen3_rr/profile.json:49`, sourced from the old client's mailbox table `lua/mailbox.lua:307`, which must gain the row too); `native.lua` gains a `transfer("rival", {blobs_hex, trainer_id})` step that uses it, and its `replace_rival_team` path switches from `transfer("enemy", …)` to it |
| ABI | the mailbox **layout** does not change, so `abi_version` stays **1** (`patch/src/ADDRESSES.md:371`). A version bump would be wrong here: `native.lua`'s `present()` requires *exact* equality of the ABI word, so bumping it for an *additive* opcode would report the native part absent on every old patch and disable trades, menus and sounds too. Compatibility comes from the dispatcher instead: an unknown opcode takes `ack(ST_FAIL)` (the enum's own note, `handlers.c:31-36`), so a new client on an old patch refuses the swap cleanly. If a future change alters the *layout*, the bump must ship with a range check in `present()` |
| `ADDRESSES.md` | rows for the new opcode, the reason code, and the enum note; `patch/dist/SLink-RR.ups` rebuilt (`patch/tools/build.py`) |
| re-pin | `server/patcher.py:66-76` (`patched_md5` for the RR target, `data/games/gen3_rr/profile.json`'s `rom`/`_rom_anchors`, and the write_checkpoint/engine_signals anchors) re-verified against the rebuilt companion; `--check` on the profile generator must stay current |

**The consumption check** (inside the new opcode's case, before the first byte is copied) — all in
RAM, no Lua:

| part | source | why |
|---|---|---|
| `gBattleCommunication[0] < 15` | `ram.BATTLE_COMM_ADDR` (RR-PROD `0x02023E82`), also `MULTIUSE_STATE` (PRET `include/constants/battle_script_commands.h:31`) | `CB2_HandleStartBattle` advances exactly one case per frame and case 15 is `InitBattleControllers`; `< 15` proves the selection has **not** run |
| `gBattleMainFunc == BEGIN_BATTLE_INTRO_DUMMY_ADDR` (`0x080123BD`) | C5-9 pin (RR-BIN: pool `0xD2E8`, store at `0xD282`) | the setup phase value, alive only from `SetUpBattleVars` (PRET `src/battle_main.c:699`) until `InitBattleControllers` (`:113`) |
| `gMain.callback2 == CB2_HandleStartBattle\|1` (`0x08010509`) | write_checkpoint pack / SYM | this battle's own setup callback, not the overworld and not `BattleMainCB2` |
| `!(gBattleTypeFlags & BATTLE_TYPE_LINK)` | `ram.BATTLE_TYPE_ADDR` | **REV-5 major**: a link battle has no rival team to replace, and the Lua pre-filter must not be the only place that says so |
| `gTrainerBattleOpponent_A == args[1]` | `ram.TRAINER_OPPONENT_ADDR` | the intended trainer context: the patch only swaps for the trainer the client announced |

Any part failing → **no copy at all**, `status = ST_FAIL`, `ack = job.seq`, `reason =
REASON_WINDOW_CLOSED` in the mailbox reason slot (u16 at offset 14, `patch/src/ADDRESSES.md:376`);
the reason-code list is ABI and lands with the rebuild. The op is *refused*, never partially
applied. The Lua clause set of §5.1 stays as a **pre-filter**.

Surfacing it: `native.lua`'s completion branch already distinguishes `OK`/`FAIL`
(`lua/gen3/native.lua:353-356`). It gains one line — on `FAIL`, read the reason word and carry it
into the job's `why` — and `replace_rival_team`'s `reply()` keeps the existing protocol shape while
adding the reason: `rival_team_replaced{trainer_id, species_ids = {}, error = "refresh_failed",
reason = "window_closed"}`. The server already logs the error field; the added `reason` is
additive, so no consumer breaks. Nothing is written on any refusal path.

The Lua window clauses of §5.1 stay, as a **pre-filter only**: they avoid staging ops the engine
would refuse (cheaper, and they are where the epoch/request-id checks live), but they are not the
authority. A Lua-side acceptance that the patch rejects is simply a refusal one frame later.

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
| ~~`swap_after_selection_viable`~~ | — | — | — | **removed (C5-8d): W2 is deferred**, so there is no positive row for it until it has its own consumption predicate |
| `trade_staging_and_scene` | a field trade: `transfer("enemy")` staging → `OP_TRADE_SCENE` | positive (regression) | — | the **other** user of opcode 16 is untouched by this design: the staged mon still reaches `gEnemyParty[0]`, the scene still runs, and the reply is `trade_done`. The row exists so a rival-swap change can never silently break trades (`lua/gen3/client.lua:1017-1026`, `lua/gen3/native.lua:224-245`, `patch/src/handlers.c:1993-1998`) |
| `rival_swap_opcode` | a rival battle with the new opcode staged | positive (regression) | — | `OP_RIVAL_SWAP` copies the partner's team and `OP_SET_ENEMY_PARTY` is *not* what the rival path posts — the two uses are separable on the wire and in the mailbox opcode log |
| `intro_request_zero` | the first request frame with the request index `0` | positive | — | the second clause's index is observable |
| `stale_epoch` | an op dispatched after `battle_end` (epoch closed) | negative | `stale_epoch` | a late reply cannot touch the next battle's party |
| `late_reply_next_battle` | battle *n*'s op delivered inside battle *n+1*'s window (same rival id) | negative (or the documented residual refusal) | `trainer_mismatch` / `window_closed` | the correlation contract; the same-id case is the residual §3 names |
| `invalid_slot_fainted` | a replacement whose only enemy mons are fainted | negative | `slots_unviable` | the selectable-team rule (§4.3, every tier) refuses instead of sending out an impossible mon |
| `invalid_slot_bad_egg` | a replacement whose lead is a **bad egg** (or species 0) — the case a raw header-bit check would miss | negative | `slots_unviable` | the rule follows the engine getter (`MON_DATA_SPECIES_OR_EGG`, PRET `src/pokemon.c:3245-3249`), not a decoded header bit |
| `end_turn_idle` | the after-turn state (comm zeroed, exec idle, outcome 0, maxHP > 0) | negative | `intro_entry_dummy`, `intro_entry`, `intro_request_open` | **the row that refutes the C4-8 clause set** |
| `post_first_dex` | `gBattleMainFunc == BattleIntroDrawTrainersOrMonsSprites` (copy + first dex write) | negative | the window clauses (§5.3) | the copy/dex frame is out |
| `post_faint_replacement` | a faint mid-battle, the engine choosing the next mon | negative | the window clauses (§5.3) | the swap cannot run when the replacement is chosen; the replacement still comes from the swapped team because it was swapped pre-selection |
| `input_wait_refused` | `HandleTurnActionSelectionState` | negative | the window clauses (§5.3) | the rest frame of the battle is not an intro frame |
| `link_battle_refused` | a link battle at the same phase values, with the op **staged past the Lua pre-filter** (a probe that dispatches anyway) | negative at the **patch** | the patch's link clause (§5.3) | link exclusion is load-bearing in the authority, not only in Lua |
| `wild_battle_refused` | a wild battle's intro | negative | the trainer/epoch gate | no trainer id, no epoch, no swap |
| `mid_case15_suspension` | a driver samples every frame across the setup and stamps, in order: the frame the op is **published** (while `Dummy`, before any selection), the frame `gBattlerPartyIndexes[0..3]` is first **written** (the selection), and the frame the op is **consumed or refused** | negative for the interrupted case | the five patch parts (§5.3) | the REV-5 interruption case: if the CPU can be stopped between the phase store and the selection, the consumption check must still refuse; the row also records the Dummy→selection gap (the W1 margin) |
| `stale_battle_id` | three shapes, one row each in the harness: (a) a same-trainer reply from battle *n* delivered in battle *n+1*; (b) a **cross-session** reply (the previous client process's nonce, the same counter); (c) the server/manual lifecycle — a declared client with no stored identity is refused a manual inject server-side, and a client that never declared one still gets the old command | negative | `battle_id` / `session` (client), the identity gate (server) | the identity contract as built (§3.3): (a) and (b) are what `trainer_id` alone cannot catch, and (c) is the capability gate — including the queued-blob staleness (`server/state.py:3074-3079`) that rides with a late reply |
| `no_viable_singles` | a replacement with no eligible mon at all (all fainted/egg) | negative | `slots_unviable` | the engine's selection would find no eligible slot; the refusal happens before any write, on every tier |
| `one_viable_doubles` | a doubles battle whose replacement has exactly one eligible enemy mon | negative | `slots_unviable` | doubles needs two *distinct* eligible mons (the second battler's scan excludes the first's index) |
| `patch_window_refusal` | the rival opcode consumed outside the patch's condition (a probe posts it with the phase value moved on) | negative | the patch's `REASON_WINDOW_CLOSED` | the patch, not Lua, is the authority: the reply is `refresh_failed` with `reason = window_closed` and `gEnemyParty` is byte-identical |
| `patch_trainer_context` | the rival opcode consumed with `args[1]` naming a different trainer than `gTrainerBattleOpponent_A` | negative | the patch's trainer clause | the intended-trainer context is enforced in the authority, so a stale op for another trainer cannot swap |

## 9. Open items

1. **The patch change (G5 scope)** — `OP_RIVAL_SWAP = 28` with the consumption check of §5.3, the
   `REASON_WINDOW_CLOSED` code, the `ADDRESSES.md` rows (enum + reason + the ABI note), the
   `lua/mailbox.lua` row, the profile's `native` key, a rebuild of `patch/dist/SLink-RR.ups`, the
   `server/patcher.py` `patched_md5` update, and the companion re-pin (profile `_rom_anchors` +
   write_checkpoint/engine_signals anchors re-verified on the rebuilt ROM). Until it lands, the Lua
   pre-filter is the only gate and the interruption case of §5.2 is unenforced on RR. The ABI
   version stays 1 (see §5.3): `present()` requires exact equality, so bumping it for an additive
   opcode would disable every native feature on old patches.
2. **The identity contract** — implemented by C5-10/C5-10b (§3.3 now describes what shipped:
   nonce + counter, the `battle_identity` capability, the manual refusal only for declared clients,
   never-retagged commands). Still open there: a lane capture with ids so conformance item 45a's
   transcript checker stops being vacuous.
3. **W2's own consumption predicate** — W2 is deferred (§4) because the patch's predicate proves
   "before the selection", which is the opposite of W2. If W2 is ever wanted (e.g. to keep the
   dex right when an op arrives late), it needs a phase value strictly after
   `BattleIntroDrawTrainersOrMonsSprites` and its own probe rows.
4. **RR selection pin** (`0x0904449D` / `0x09044531` CFru tails) — required before W2 is allowed on
   RR. W1 does not need it; the §4.3 precondition does not either (it reuses the inherited loop).
5. **The timing receipt** (`swap_window_margins`, `mid_case15_suspension`) — settles both the new
   design's margin and the old client's actual behaviour.
6. **Doubles on RR**: the second enemy battler's predicate lives in the CFru tail; W1 covers
   doubles with §4.3's two-viable precondition, and W2's doubles half is deferred with W2.
7. **The dummy-value gap**: frames between `CB2_InitBattle`'s entry and `SetUpBattleVars` admit no
   clause; the probe should record how wide that gap is in practice relative to the op's latency.
8. **Dashboard copy**: an identity-less manual inject now refuses *server-side* for a client that
   declared `battle_identity` (§3.3), and a swap issued outside a battle the client is in is refused
   by the client's own epoch check. Both are correct; the button's help text should say so rather
   than let a player read the refusal as a failure.
