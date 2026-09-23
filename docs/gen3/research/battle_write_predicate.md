# Battle write predicate — design (P4 card C4-B)

Research + design only. HEAD `f37fbcf2`. No pack, no `lua/gen3/*`, no test edits; the deliverable
is this note. Two owner rulings (PLAN §0, 2026-09-23) shape it: in-battle faint must work on
vanilla FRLG the way it works on Radical Red today, and the old RR client's addresses are
production-tested evidence for RR (not a behaviour-for-behaviour port).

Evidence grades used below:

| grade | meaning |
|---|---|
| **PRET** | `E:/Google Drive/SLink/.cache/pret/pokefirered` at `c75f352304d529f6ba92d4f74b9cf8b5c3810788` (`docs/gen3/research/pins.md` §1) |
| **SYM** | `data/gen3/pret/pokefirered.sym` / `pokeleafgreen.sym` (addresses; both titles checked, equal unless noted) |
| **RR-PROD** | an address the shipped old client uses on RR in production (`lua/games/gen3_frlge.lua`, `lua/memory_gba.lua`), which `data/games/gen3_rr/profile.json` also carries |
| **INFER** | reasoned from the above, not yet witnessed |

## 1. The problem this predicate solves

`safety:check(snapshot)` takes no reason (`lua/gen3/safety.lua:42`), and `writes:arm` passes one
anyway (`lua/gen3/writes.lua:17`: `safety:check(snapshot, reason)`) — Lua drops the extra argument,
so every clause in the pack's one predicate set is evaluated for every arm. That set is the
overworld one (`version: "gen3-overworld-v1"`, `data/games/gen3_{frlg,rr}/write_checkpoint.json`),
so `arm("battle_faint")` / `arm("battle_commit")` inside a battle always refuses, and the new
client's policy (`policy.check(snap, reason)` → hold) can never write. The pack *does* have
callbacks that fire mid-battle (`battle_begin` = `CB2_InitBattle`, `faint` = `Cmd_tryfaintmon`,
`capture_wild` = `Cmd_givecaughtmon`, `data/games/gen3_frlg/engine_signals.json`), but a write at
one of those frames is refused by the checkpoint — a callback is not a safe window.

Consequence today: the two RR-proven behaviours (a benched linked mon dying immediately; Explode
Mode's coerced Explosion) are impossible on the new client. This note designs the clause set that
makes them possible, and answers whether the *active* battler can be written too (§4: no).

A third reason exists and is *not* about game state: `native` (the RR companion's mailbox and
staging arena, `lua/gen3/native.lua` + `patch/src/handlers.c`). `writes.lua` already admits it
(`reasons.native`, `lua/gen3/writes.lua:4-5`) and `lua/gen3/entry.lua:250-256` refuses it by name
until a policy supplies a predicate. §3.5 designs that clause set, which is deliberately *not* the
overworld one.

## 2. The battle frame, from pret

### 2.1 The phase machine: `gBattleMainFunc`

`gBattleMainFunc` (`0x03004F84` **SYM**, RR-PROD via `profile.ram.BATTLE_MAIN_FUNC_ADDR`) is called
once per frame by `BattleMainCB2` (`src/battle_main.c:388-420`); the assignments below are every
phase the engine passes through (PRET `src/battle_main.c`):

| phase | symbol | address (FR = LG) | what runs |
|---|---|---|---|
| intro | `BattleIntroGetMonsData` | `0x0800FD…`† | party → `gBattleMons` load for every battler (`:2519-2534`) |
| pre-turn | `TryDoEventsBeforeFirstTurn` | `0x0801…`† | turn-start effects |
| **input** | `HandleTurnActionSelectionState` | `0x08014040` **SYM** | the player's action menu; the engine polls `gBattleBufferB` (`:3097-3391`) |
| order | `SetActionsAndBattlersTurnOrder` | `0x080150A8` **SYM** | builds `gBattlerByTurnOrder`/`gActionsByTurnOrder` (`:3532-3620`) |
| execute | `RunTurnActionsFunctions` | `0x080155C8` **SYM** | dispatches `sTurnActionsFuncsTable[gCurrentActionFuncId]` (`:3704-3723`) |
| turn end | `BattleTurnPassed` | `0x08013BD4` **SYM** | end-of-turn bookkeeping, then back to input |

† not needed by the predicate; listed to show the phase map is complete. The five phases above are
the only ones the input wait is distinct from.

### 2.2 The action-selection state machine (the frame we want)

`HandleTurnActionSelectionState` (PRET `src/battle_main.c:3097-3391`) switches on
`gBattleCommunication[gActiveBattler]` (`0x02023E82` **SYM**, RR-PROD `BATTLE_COMM_ADDR`) over
`enum { STATE_BEFORE_ACTION_CHOSEN = 0, STATE_WAIT_ACTION_CHOSEN = 1, STATE_WAIT_ACTION_CASE_CHOSEN
= 2, STATE_WAIT_ACTION_CONFIRMED_STANDBY = 3, STATE_WAIT_ACTION_CONFIRMED = 4,
STATE_SELECTION_SCRIPT = 5, STATE_WAIT_SET_BEFORE_ACTION = 6 }` (`:3084-3095`), for
`gActiveBattler = 0 .. gBattlersCount-1`. Battler indices are slots `0..3` of that array;
`ACTIONS_CONFIRMED_COUNT` is index **4** (`include/constants/battle_script_commands.h:37`).

What the states mean for a writer:

- **0** — the engine is about to emit `BtlController_EmitChooseAction` and hand the battler to its
  controller (`:3121-3139`). Not a rest state.
- **1 (WAIT_ACTION_CHOSEN)** — the engine has emitted the menu and now only *polls*:
  `if (!(gBattleControllerExecFlags & (bit | 0xF0000000 | bit<<4 | bit<<8 | bit<<12))) { … read
  gBattleBufferB[battler][1] … }` (`:3140-3151`). Nothing else in the frame touches that battler.
  **This is the rest state**, and it persists for as long as the player leaves the menu alone
  (the same "parked" property the overworld predicate relies on at `WaitForVBlank`).
- **2** — the engine is consuming the chosen case (move/item/switch) from the buffer (`:3262+`).
- **3/4** — the action is committed; the engine emits a standby message and then counts
  (`:3352-3366`). When `gBattleCommunication[4] == gBattlersCount` the turn starts (`:3388-3390`).
- **5** — a selection *script* is running (e.g. "can't run from a trainer battle") (`:3367-3380`).
- **6** — bounce/standby bookkeeping.

`gBattleControllerExecFlags` (`0x02023BC8` **SYM**) is the engine's "a controller is mid-exec"
latch: every script command and every animation emit sets it and the engine waits for it to clear
(`MarkBattlerForControllerExec`, PRET `src/battle_controllers.c:600-616`). `gBattleBufferB`
(`0x020233C4` **SYM**) is the controller→engine channel; the player's menu writes it.

### 2.3 Who touches the party struct during a battle (PRET)

| writer | when | cite |
|---|---|---|
| `Cmd_setatkhptozero` → `BtlController_EmitSetMonData(REQUEST_HP_BATTLE)` | the Explosion user's own HP → 0, in the move's script | `src/battle_script_commands.c:6294-6303` |
| passive damage (poison/burn/…) → same emit | after end-of-turn passive damage | `src/battle_script_commands.c:1857-1859` |
| `Cmd_getexp` (`MonGainEVs`, level, exp, stats via `CalculateMonStats`) | the exp/level-up script, for `gBattleStruct->expGetterMonId` | `src/battle_script_commands.c:3150-3330` |
| `PokemonUseItemEffects` (Potion/Revive/…) | the player's `B_ACTION_USE_ITEM` turn, and out of battle | `src/pokemon.c:4001,4245-4317` |
| status / PP / held-item emitters (`REQUEST_STATUS_BATTLE`, `REQUEST_PPMOVE1_BATTLE`, `REQUEST_HELDITEM_BATTLE`) | inside move scripts | `src/battle_script_commands.c:1159,2363,2906,2937,5652,7807,7975,8086` |
| `AdjustFriendship*` (faint, level-up) | inside scripts | `src/battle_script_commands.c:3314`, `src/battle_main.c:713` |

| reader | when | cite |
|---|---|---|
| `HasNoMonsToSwitch` (party HP ≠ 0 scan) | the doubles send-out decision | `src/battle_util.c:1144-1200`, sym `0x08019C10` |
| `Cmd_openpartyscreen` (the forced send-out menu) | after a faint, inside `BattleScript_HandleFaintedMon` | sym `0x080243EC` |
| the party menu (HP bars, summary) | the in-battle Pokémon menu | `src/party_menu.c:2657,2691` |
| `Cmd_getexp` (party HP decides the level-up box) | exp script | `src/battle_script_commands.c:3150,3223,3282` |
| `PokemonUseItemEffects` | item use | `src/pokemon.c:4245-4317` |
| `Cmd_getswitchedmondata` → `BtlController_EmitGetMonData(REQUEST_ALL_BATTLE)` | **switch-in**: party → `gBattleMons` | `src/battle_script_commands.c:4452-4461` |

Two facts from that table matter for the design:

1. **Every writer and every reader above runs inside a battle *script* or a controller exec** —
   i.e. while `gBattleMainFunc != HandleTurnActionSelectionState` or while
   `gBattleControllerExecFlags != 0`. The input wait is the one phase with no script and no pending
   controller exec, so it is the one frame in which the engine neither reads nor writes the party
   for any battler. That is the whole safety argument for a party-struct write.
2. A **level-up cannot resurrect a written 0 HP**: `CalculateMonStats` takes the early `return`
   when `currentHP == 0 && oldMaxHP != 0` (`src/pokemon.c:2155-2161`), so the exp path rewrites
   stats/level/exp but not HP. An Exp. Share recipient that SLink killed mid-battle stays dead
   through its level-up.

### 2.4 Who touches `gBattleMons` (PRET)

`gBattleMons` (`0x02023BE4` **SYM**, RR-PROD), `struct BattlePokemon` size `0x58`, `hp` at
`+0x28`, `maxHP` `+0x2C`, `level` `+0x2A`, `moves` `+0x0C`, `pp` `+0x24`, `status1` `+0x4C`,
`status2` `+0x50` (PRET `include/pokemon.h:170-206`; the same offsets as the old client's
`M.BATTLE_MON_*`, `lua/memory_gba.lua:395-406` — CFRU preserves the layout, RR-PROD).

Writers: every damage/status/stat-stage script command (all inside scripts), `Cmd_setatkhptozero`,
`FaintClearSetData` (`0x08012BC8` **SYM**), `SwitchInClearSetData` (`0x08012760` **SYM**),
`Cmd_switchindataupdate` (`0x08023F48` **SYM**), `Cmd_getexp`'s level-up refresh
(`src/battle_script_commands.c:3319-3321`), the item-use re-copy (`src/pokemon.c:4270`), the intro
load (`src/battle_main.c:2574-2588`). Readers: everything — damage maths, the HP bar
(`Cmd_healthbar_update` `0x08022C68` **SYM**), the AI, and the faint check (§4).

## 3. The safe points

Addresses are shared by FR/LG and RR (SYM for FR/LG; RR-PROD for RR, all twelve identical — the
RR profile carries the same values and the shipped client uses them). Evidence per title differs
only in *how* the address is proven, which is a generator question (§7).

### 3.1 `battle_input` — the rest frame for every battle write

| clause | address | width | test | source |
|---|---|---|---|---|
| `battle_main_func` | `gBattleMainFunc` `0x03004F84` | 4 | `== HandleTurnActionSelectionState \| 1` (`0x08014041`) | PRET `src/battle_main.c:2912,2998`; SYM |
| `battle_comm_0` | `gBattleCommunication` `0x02023E82` +0 | 1 | `== 1` (`STATE_WAIT_ACTION_CHOSEN`) | PRET `src/battle_main.c:3140-3151` |
| `battle_exec_flags_idle` | `gBattleControllerExecFlags` `0x02023BC8` | 4 | `== 0` | PRET `src/battle_controllers.c:600-616` |
| `battle_not_link` | `gBattleTypeFlags` `0x02022B4C` | 4 | `& 0x02 == 0` (`BATTLE_TYPE_LINK`) | PRET `include/constants/battle.h:48` |
| `battle_engine_loaded` | `gBattleMons` `0x02023BE4` +`0x2C` | 2 | `> 0` (`gBattleMons[0].maxHP` — battle data live) | RR-PROD `lua/memory_gba.lua:465-473`; INFER for FR/LG |
| `battle_outcome_open` | `gBattleOutcome` `0x02023E8A` | 1 | `== 0` | RR-PROD `lua/memory_gba.lua:472`; PRET `src/battle_main.c:3706` |

`battle_comm_0` is battler 0 — the player's primary. In singles that is the only player battler; in
doubles the state machine iterates battlers in index order, so battler 0's menu is up first and
battler 2 is handled before it reaches 0 again (PRET `:3103-3140`). A write while battler 0 waits
therefore has *no* player battler mid-action (battler 2 is in 3/4 at that point, `:3352-3366`).

`battle_engine_loaded` + `battle_outcome_open` are the RR-side "we are in a battle" evidence the
shipped client already uses; on FR/LG they are redundant with `battle_main_func` but harmless, and
they are what keeps the RR clause set honest where `gBattleMainFunc`'s *code* is CFRU's.

**RR caveat on the first two rows.** The *addresses* (`gBattleMainFunc` `0x03004F84`,
`gBattleCommunication` `0x02023E82`) are the ones the shipped client uses on RR, so a comparison
against them is RR-PROD — but the *expected value* of `battle_main_func` is
`HandleTurnActionSelectionState|1`, a FireRed *code* address (`0x08014041`). CFRU's battle code is
heavily rewritten, so on RR that expect is **INFER, not proven**: the RR clause set should be
`battle_comm_0 == 1` + `battle_exec_flags_idle` + `battle_not_link` + `battle_engine_loaded` +
`battle_outcome_open` until a physical row (or a byte-level check) admits a `gBattleMainFunc`
value for RR. `battle_comm_0 == 1` alone is weaker (the array is used by other battle phases) but
it is read by the same code the old client's commit path relies on, which is why the probe rows
exist.

### 3.2 `battle_bench` — the immediate faint of a party mon that is not a battler

Same frame as `battle_input`. The write is party HP (`gPlayerParty` `0x02024284` + slot*100 +
`0x56`, **SYM**; RR-PROD `PARTY_BASE`/`OFF_HP`) = 0, plus nothing else: the party struct is the
master for a mon that is not on the field, and §2.3 shows the engine touches it only in scripts.
Why this is the *correct* mechanism and not just a safe one:

- The engine never sends out a 0-HP party mon: `HasNoMonsToSwitch` and `Cmd_openpartyscreen` both
  scan for HP ≠ 0 (PRET `src/battle_util.c:1144-1200`), so the mon stays out of the battle.
- The in-battle party menu reads the same struct (`src/party_menu.c:2691`), so the player sees it
  fainted, which is the intended visible outcome.
- A level-up through Exp. Share cannot undo it (§2.3 fact 2).
- An item used on it *can* undo it (`PokemonUseItemEffects` → Revive clears
  `gAbsentBattlerFlags` and re-copies the battler, `src/pokemon.c:4258-4272`). That is a rules
  question (the server considers the pair dead), not a memory-safety one; the write plan should
  not re-write the same mon every frame after a successful faint, so a revive is not fought.

`gBattlerPartyIndexes` (`0x02023BCE` **SYM**, RR-PROD) is how the client tells "is this party slot
a battler right now" — the same read the old client makes (`lua/clients/gen3_frlge_client.lua:2559-2566`).

### 3.3 `battle_commit` — Explode Mode's coerced Explosion

The RR path is a *state pre-fill*, not a menu press: the old client writes the engine's committed
action so the FIGHT/BAG/POKÉMON/RUN menu is never opened, then reinforces it each frame until the
move commits (PP drops) or the fallback fires
(`lua/memory_gba.lua:1303-1350`; `lua/clients/gen3_frlge_client.lua:773-790,2364-2436`). Every
address it uses is the vanilla one:

| write | address | value | vanilla evidence |
|---|---|---|---|
| `gChosenActionByBattler[battler]` | `0x02023D7C` | `0` (`B_ACTION_USE_MOVE`) | PRET `include/battle.h:34`; SYM (`gChosenActionByBattler`); RR calls it `gActionForBanks` |
| `gChosenMoveByBattler[battler]` | `0x02023DC4` (u16 stride 2) | `153` (`MOVE_EXPLOSION`) | PRET `include/constants/moves.h:157`; SYM |
| `gBattleCommunication[battler]` | `0x02023E82` | `3` (`STATE_WAIT_ACTION_CONFIRMED_STANDBY`) | PRET `src/battle_main.c:3084-3095,3352-3366` |
| `gBattleStruct->chosenMovePositions[battler]` | `*(0x02023FE8) + 0x80` | `0` | PRET `include/battle.h:412` (offset computed from the struct; matches RR-PROD `derived.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF = 128`) |
| `gBattleStruct->moveTarget[battler]` | `*(0x02023FE8) + 0x0C` | `1` (foe primary) | PRET `include/battle.h:380`; RR-PROD `derived.BATTLE_STRUCT_MOVE_TARGET_OFF = 12` |
| `gLockedMoves[battler]` (clear) | `0x02023DB8` | `0` | PRET SYM; old client `clear_lock_state` |

The vanilla state machine *proves* the mechanism, which is stronger than the RR port alone: a
battler whose `gBattleCommunication[battler]` is 3 is handled by
`case STATE_WAIT_ACTION_CONFIRMED_STANDBY:` — the engine emits a standby message and increments to
4, where `case STATE_WAIT_ACTION_CONFIRMED:` counts it; when the count equals `gBattlersCount` the
turn starts and `gChosenActionByBattler`/`gChosenMoveByBattler` are what the turn order and
`HandleAction_UseMove` read (PRET `src/battle_main.c:3352-3390,3963-4000,3532-3620`). The menu is
never entered because states 3/4 are past the state that emits `BtlController_EmitChooseAction`
(`:3121-3139`).

**The guard is the state itself, and it is mandatory:** writing 3 is only safe while the current
value is **0, 1 or 2**. If the engine has already reached 4 and SLink writes 3, the `case` for 4
still runs `++gBattleCommunication[ACTIONS_CONFIRMED_COUNT]` on a value of 3 → 4 → 5
(`STATE_SELECTION_SCRIPT`) with `gSelectionBattleScripts[battler]` never set → the engine jumps to
a garbage script pointer. That is the softlock the shipped client's `cur_state < 3` guard exists to
prevent (`lua/clients/gen3_frlge_client.lua:2401-2410`) — it is not a heuristic, it is the state
machine's own contract.

Clauses for `battle_commit` = `battle_input` **plus** the dynamic per-battler guard
`gBattleCommunication[battler] < 3` evaluated for the *target* battler (index from the command, not
from the pack — §5).

### 3.4 Forbidden states for both battle reasons

| forbidden state | rejected by |
|---|---|
| move/status animation, damage script, any script running | `battle_exec_flags_idle` (a script sets exec flags), `battle_main_func` |
| the intro / send-out sequence | `battle_main_func` (not the input wait) |
| the forced send-out menu after a faint (`HandleFaintedMonActions` → `Cmd_openpartyscreen`) | `battle_main_func`, `battle_comm_0` (0/5 during that flow) |
| the move submenu (`STATE_WAIT_ACTION_CASE_CHOSEN`) or the confirmed states 3/4/5 | `battle_comm_0` |
| a link battle (party memcpys into `gPlayerParty+2`/`+5`, `src/battle_main.c:1356-1390`) | `battle_not_link` |
| the battle's own end (`gBattleOutcome != 0`) | `battle_outcome_open` |
| overworld / stale battle data | `battle_engine_loaded` (`gBattleMons[0].maxHP == 0`) |
| the target battler already committed (`gBattleCommunication[battler] >= 3`) | the `battle_commit` guard |
| a native write on a non-companion artifact (FR/LG, RR clean) | `native_present` (§3.5) |
| a native write while the mailbox is busy (opcode pending or status BUSY) | `native_idle` (§3.5) |
| a native write outside the arena spans | the `allow` predicate (`writes.lua`), not a safety clause |

### 3.5 `native` — the RR companion's mailbox and staging arena

This reason is different in kind: the bytes are **SLink-owned EWRAM**, not game state, so the
predicate that matters is the *handshake* with the injected handler, not the game's phase.

The arena: `patch/src/ADDRESSES.md:40-77` puts the mailbox at `0x0203F800` (64 B, ABI v1) — chosen
*above* CFRU's highest known EWRAM symbol (`0x0203F3AE`) and explicitly **not** in the gap below it
("do not allocate below `0x0203F800`", `:44-47`) — followed by the staging spans this design cares
about: `SwapState 0x0203F840` (8), `GhostState 0x0203F850` (44), `ArmedMove 0x0203F8C0` (8),
`SlinkState 0x0203F8D0` (4), `TradeNpcState 0x0203F8D4` (4), `SLINK_CALC_OFF 0x0203F8D8` (1),
`SLINK_SCRIPT_BUF 0x0203F8E0` (32), `SLINK_TEXT_BUF 0x0203F900` (256),
`SLINK_BLOB_BUF 0x0203FA00` (600), `GHOST_PAL_BUF 0x0203FC60` (32), `UiState 0x0203FC80` (12),
`SLINK_MENU_BUF 0x0203FC90` (112) (`:59-77`). The mailbox itself is 64 B: `abi`, `opcode`, `seq`,
`status`, `ack_seq`, `reason`, `args`, `result` (`patch/src/handlers.c:20-30`; the Lua mirror is
`lua/gen3/native.lua:14` and `lua/mailbox.lua:13,21`).

The handshake, from the injected side: `slink_hook()` runs from the `CallCallbacks` hook site
(`patch/src/handlers.c:4`, i.e. the pack's own `frame_control` anchor,
`data/games/gen3_frlg/write_checkpoint.json`) and **every frame**: it re-writes the presence beacon
(`MB->signature`/`abi_version`), reads `MB->opcode` (`:1821`), consumes it (`MB->opcode = 0` on
BUSY, `:1947-2005`) and settles with `ack()` → `status = ST_OK/ST_FAIL`, `ack_seq = seq`,
`opcode = 0` (`:559-565`). It does **not** gate on the battle phase: only the sprite-touching field
drivers are gated on the overworld callback (`:1787-1820`), and the comment says the async pollers
"only read state + the mailbox, so they always run". From the writer's side both clients publish
**the opcode last**, after the args: the old client's `post()` writes the args and then
`memory.write_u16_le(MB.BASE + O_OPCODE, opcode)  -- write opcode LAST (triggers dispatch)`
(`lua/mailbox.lua:491-498`, single-slot mailbox, `:480-489`), and the new module does the same
("publish last", `lua/gen3/native.lua:120-127`) after asserting the mailbox is idle.

Clause set:

| clause | address | test | source |
|---|---|---|---|
| `native_present` | the pack's signature + ABI words (`profile.native`) | signature matches **and** `artifact_kind == "companion"`; on any other artifact the *reason itself* refuses | `lua/gen3/native.lua:40-46` (`present()`); `patch/src/handlers.c:1787-1790` (the beacon) |
| `native_idle` | `MB + opcode` (`0x0203F800+6`), `MB + status` (+10), and the panel handshake | `opcode == 0` **and** `status != ST_BUSY` **and** the panel's `drawn == ack` pair equal | `lua/gen3/native.lua:45-54` (`self:idle()`); `patch/src/handlers.c:559-565,227-232`; `lua/mailbox.lua:514-520` (the old client's `busy`) |
| allow range | `writes.lua`'s `allow` | every byte inside `[MB + opcode, MB + result]` or one of the job's staged spans | `lua/gen3/native.lua:86-97` (`allow_for`), `:111` (`arm("native", …)`) |
| *deliberately absent* | — | the overworld predicates (`callback1/2`, tasks, `cpu`, `field_controls_locked`, `save_dialog_cb`, …) are **not** clauses for this reason | see below |

Why the overworld clauses are absent, and what that costs:

1. The arena is not game state: the engine never reads or writes `0x0203F800..0x0203FCFF` (it is
   above CFRU's highest EWRAM symbol by construction, `ADDRESSES.md:40-47`), and the save system
   writes SRAM/flash, not EWRAM — so **"not during a save" is not needed for the arena's
   integrity** and the `cpu`/parked-PC clause (which exists to make an overworld *game-state* write
   land at a stable point) has no meaning for a write that only the hook reads.
2. The handler is frame-driven and phase-independent (`handlers.c:1787-1820`), so the *game* phase
   does not change whether a posted op is consumed — the hook consumes one opcode per frame
   (`mailbox.lua:480`).
3. **Native ops must be issuable mid-battle, and two of them require it**: `OP_SET_ENEMY_PARTY`
   (16) is the Rival Team Swap, triggered from `trainer_battle_start`, and `OP_SHOW_BATTLE_MESSAGE`
   (23) is the native in-battle notification text (`patch/src/handlers.c:39,46`; the old client's
   trigger and ack: `lua/clients/gen3_frlge_client.lua` `replace_rival_team` →
   `rival_team_replaced`). Adding the overworld clauses would refuse exactly those two.
4. What *does* need a game-state window is the **post-op refresh**, not the op: after the patch has
   copied `gEnemyParty`, the old client refreshes the active foe's `gBattleMons[1]`/`[3]` cache
   with a *Lua* write (`lua/memory_gba.lua:1699-1729` `refreshActiveEnemyBattlers` /
   `refreshEnemyPartyNative`) which must land before the first send-out
   (`lua/gen3/native.lua:7-8` says the new module expects the same). That is a `gBattleMons` write
   in the battle's first frames, i.e. a **third window** this design does not yet establish — see
   §7 item 6. Per-op preconditions like `panel_closed()` or "the party menu is not open" belong to
   the op's caller (`lua/gen3/native.lua`'s `valid()` hooks), not to this clause set.

## 4. Would writing the ACTIVE battler's HP at the input wait be safe? (item 4)

**No — not as an improvement over holding.** Three independent reasons, all PRET:

1. `Cmd_tryfaintmon` (the only place a faint is decided) runs **inside a battle script** and tests
   `gBattleMons[gActiveBattler].hp == 0` (`src/battle_script_commands.c:2831-2885`). Nothing polls
   HP per frame, so a write at the input wait is not processed until some later script step reaches
   a `tryfaintmon`.
2. The engine does **not** skip a 0-HP battler before it acts: `SetActionsAndBattlersTurnOrder`
   builds the order from `gChosenActionByBattler` with no HP filter
   (`src/battle_main.c:3532-3620`), and `HandleAction_UseMove` only checks
   `gBattleStruct->absentBattlerFlags` — not HP (`src/battle_main.c:3963-3972`). So a mon whose
   `gBattleMons.hp` SLink zeroed would still take its turn (and could KO its opponent), and only
   then be fainted by the turn's faint pass (`HandleFaintedMonActions`, `src/battle_util.c:1144-1230`,
   called from `src/battle_main.c:2965,4435`) or by the opponent's damage script. That is a
   behaviour change, not a faint.
3. The engine's own faint *evidence* would not be produced: `gBattleResults.playerFaintCounter`
   (the C3-36 witness, `0x03004F90` +0, RR-PROD `BATTLE_RESULTS_PLAYER_FAINTS_OFF`) is incremented
   inside `Cmd_tryfaintmon` (`src/battle_script_commands.c:2851-2854`), i.e. only when the script
   processes the faint. A raw HP write produces no counter, no faint animation and no exp
   bookkeeping.

So: hold the active battler (owner ruling), and for Explode Mode use `battle_commit` (§3.3), which
*is* the engine's own commit path. The one case where writing a battler's HP is right is the
whiteout sweep the old client already does (`M.forceImmediateWhiteout`,
`lua/memory_gba.lua:1372-1390`: party HP + `gBattleMons[0]`/`[2]` HP + `gBattleOutcome`), which
ends the battle rather than faking a faint inside it — that belongs to a later card, not to this
predicate.

## 5. `safety.lua`: how the reason selects a clause set (item 6)

Design (no code here): keep the pack declarative and static, add the *reason* dispatch in the
library.

1. **Pack schema.** Keep `version: "gen3-overworld-v1"` for the existing block, and add a sibling
   `battle` block per title holding only *addresses* (symbol, address, offset, width, mask, expect)
   for the clauses in §3.1/§3.3 — the same shape as `predicates`, so
   `tools/gen_gen3_write_checkpoint.py` can emit it from the sym (FR/LG) and from the RR
   provenance (§7). The dynamic per-battler guard cannot live in the pack (no indexing) and does
   not need to: it is one address (`gBattleCommunication`) and one comparison.
2. **Library.** `self:check(snapshot, reason, args)`:
   - `reason == "overworld"` (or `nil`) → today's code path, clause for clause, in the same order,
     with the same `last_clauses` keys and the same `"verified overworld checkpoint"` message. This
     is the byte-identical requirement: no clause added, removed, reordered or renamed for the
     overworld reason, so the G3-signed receipts and `tests/unit/test_gen3_safety*.py` keep their
     meaning.
   - `reason == "battle_faint"` → `battle_input` (§3.1) only.
   - `reason == "battle_commit"` → `battle_input` plus `gBattleCommunication[args.battler] < 3`
     with `args.battler` an integer in `0..3`; a missing or out-of-range `battler` **refuses**
     (fail closed), never defaults.
   - `reason == "native"` → the §3.5 set: `native_present` + `native_idle` (+ the `allow` range,
     which `writes.lua` already enforces). No overworld clause, no `cpu`, no pointer snapshot
     requirement — the arena is SLink's EWRAM and the hook is the only reader. On an artifact that
     is not the companion, the reason refuses by name (`native absent`) rather than evaluating a
     clause against addresses that do not exist in that build.
   - any other reason → refuse with the clause key `"reason"` (a new key, only ever emitted for an
     unknown reason — so the overworld key set is untouched).
3. **`writes.lua`** needs no change beyond passing `args` through (it already passes the reason),
   and `native` stays as it is (the RR native surface is P5's).
4. **Policy.** The client's `policy.check(snap, reason)` should stop being a blanket refusal: it
   maps `battle_faint` → `safety:check(snap, "battle_faint")` when the *target* is not a battler,
   and `battle_commit` → `safety:check(snap, "battle_commit", {battler = b})` for the Explode path,
   and keeps refusing (hold) otherwise. The hold path stays the default for anything the policy
   cannot classify — that is what makes the change additive.

## 6. Probe rows (G4 item, item 5)

Rows mirror `lua/tests/probe_gen3_checkpoint.lua` (`P.STATES` shape, `expectation`,
`expect_clauses`, `min_samples`, `artifacts`, and `P.tally`/`P.verdict` clause attribution — the
C3-24 rule that every counted refusal must name an expected clause). Witnesses read the engine
variables directly (independent of `safety`, as the existing rows do):

| witness | address | meaning |
|---|---|---|
| `battle_main_func` | `0x03004F84` | the current phase; `== 0x08014041` is the input wait (FR/LG) |
| `battle_comm` | `0x02023E82` + battler | the per-battler state 0..6 |
| `battle_exec_flags` | `0x02023BC8` | non-zero = a controller is mid-exec |
| `battle_outcome` | `0x02023E8A` | non-zero = the battle is resolved |
| `native_beacon` | `0x0203F800` (signature) / `+0x04` (ABI) | the patch is present; the same words `native.lua`'s `present()` reads |
| `native_mailbox` | `0x0203F800 + 0x06` (opcode, u16) / `+0x0A` (status, u16) | idle (`opcode == 0`, `status != BUSY`) — the §3.5 clause's own inputs |

| row | state | expectation | expect_clauses | artifacts | what it proves |
|---|---|---|---|---|---|
| `battle_input_wild` | wild battle, menu left alone (parked) | positive | — | firered/clean, leafgreen/clean, radical_red/clean, radical_red/companion | the new clause set admits a real input wait, ≥ 300 non-IRQ samples |
| `battle_input_trainer` | trainer battle, menu left alone | positive | — | as above | not a wild-only property (trainer battles have their own intro/scripts) |
| `battle_move_menu` | the same battle after one Down/A (move submenu up) | negative | `battle_comm_0` | as above | state 2 is refused |
| `battle_animation` | mid move animation (exec flags set) | negative | `battle_exec_flags_idle`, `battle_main_func` | as above | the animation window is refused |
| `battle_faint_prompt` | the forced send-out prompt after a faint | negative | `battle_main_func`, `battle_comm_0` | as above | the post-faint flow is refused (this is where a bench write *must* have landed earlier) |
| `battle_intro` | the send-out sequence / intro | negative | `battle_main_func` | as above | the intro is refused |
| `battle_link` | a link battle, input wait | negative | `battle_not_link` | firered/clean, leafgreen/clean (RR link entry is a CFRU unknown, `docs/gen3_write_checkpoint.md` §4.2) | link party memcpys cannot race a write |
| `battle_over` | the frame after `gBattleOutcome != 0` | negative | `battle_outcome_open`, `battle_engine_loaded` | as above | a resolved battle is not a write window |
| `battle_commit_state3` | the input wait with `gBattleCommunication[0] == 3` | negative for `battle_commit` | `battle_commit_guard` | as above | the softlock guard (§3.3) refuses a write past the commit point |
| `native_idle_field` | RR companion, overworld, mailbox idle | positive for `native` | — | radical_red/companion | the §3.5 set admits a real write window outside battle |
| `native_idle_battle` | RR companion, in a trainer battle, mailbox idle | positive for `native` | — | radical_red/companion | the row that earns the "ops may be issued mid-battle" claim (§3.5 point 3) — the rival-swap frame |
| `native_busy` | a posted opcode the hook has not consumed (`opcode != 0` or `status == ST_BUSY`) | negative for `native` | `native_idle` | radical_red/companion | a second op cannot be staged over an un-consumed one (single-slot mailbox) |
| `native_absent` | FR/LG or RR clean (no companion) | negative for `native` | `native_present` | firered/clean, leafgreen/clean, radical_red/clean | the reason refuses on a build with no handler, instead of writing into unowned EWRAM |

Row mechanics: the probe already drives savestates + joypad and narrows via
`SLINK_CHECKPOINT_ROWS`; the battle rows need savestates parked in a wild and a trainer battle with
the action menu up (the state is stable, which is the point), plus one per negative state. The
*positive* rows must report a non-IRQ denominator (`P.POSITIVE_MIN_NON_IRQ`) like the existing idle
row. Anchors for the new sites (if a row wants to pin a *code* site such as
`HandleTurnActionSelectionState`) come from `tools/pin_gen3_site.py` (8–16 exact bytes, sha1-checked
per ROM, `--symbol` + `--symbol-file` bounds check) — its own output says `UNVERIFIED` until a
physical row admits, which is exactly the grading this lane wants.

## 7. Open items (what this design does not settle)

1. **RR provenance for the new data clauses.** `tools/gen_gen3_write_checkpoint.py` proves an RR
   data address through `WITNESS` (a FR function whose literal pool holds the address, unchanged in
   the RR ROMs; `:108-118,240-251`). The battle addresses have no witness entry yet, so adding the
   `battle` block for RR needs either a witness function that survives CFRU (candidates: a small
   helper that reads `gBattleCommunication`/`gBattleMons`, to be found by
   `tools/pin_gen3_site.py` + the literal-pool check) or an explicit, recorded exception that takes
   the address from the old client (owner ruling: trusted evidence) and prints it in the generator's
   "dropped/unproven" list instead of failing. Decide before C4-3 writes the pack.
2. **`Cmd_getexp` is †UNVERIFIED for RR** (`docs/gen3_write_checkpoint.md` §5): CFRU rewrites it.
   The level-up argument in §2.3 fact 2 is pret's; for RR it is INFER until a physical row or a
   binary check settles it. The *bench* write does not depend on it (nothing in the input wait
   writes the party), but a future "write while a script runs" relaxation would.
3. **Doubles.** §3.1's `battle_comm_0` covers the player's first menu; a doubles write while
   battler 0 waits has not been witnessed. A `battle_input_double` positive row would settle it.
4. **The `battle_link` negative row** needs a link savestate pair; the RR link entry is a CFRU
   unknown (existing checkpoint doc §4.2 limit), so the row is FR/LG-only until pinned.
5. **Where the hold lives.** The client's policy is in flight (`lua/gen3/client.lua`); this note
   assumes `policy.check(snap, reason)` can take the extra `args` (battler). If it cannot, the
   `battle_commit` guard has to move into the Explode executor instead — the guard's *content* is
   unchanged either way.
6. **The rival swap's second write window (native addendum).** `OP_SET_ENEMY_PARTY` itself is fine
   at the §3.5 clause set (idle mailbox, any phase), but the *post-op refresh* — the old client's
   `refreshEnemyPartyNative` writing `gBattleMons[1]`/`[3]` from `gEnemyParty`
   (`lua/memory_gba.lua:1699-1729`) — is a **game-state** write that must land before the first
   send-out, i.e. in the battle's first frames, not at the action-selection wait. The patch's own
   handler comment decides who must do it: "The active-foe gBattleMons refresh stays in Lua
   (refreshActiveEnemyBattlers): CFRU substruct decrypt has no clean engine fn"
   (`patch/src/handlers.c:1867-1888`) — so this is a Lua write the new client has to place, not
   something the op covers. Two ways to settle it: (a) give the predicate an `intro`-phase clause
   set with its own pret research (who reads `gBattleMons[1]` during the intro: the send-out script,
   the HP box draw) plus a `battle_intro` probe row; or (b) add a new opcode that performs the
   refresh from the staged `SLINK_BLOB_BUF` (SLink-owned EWRAM) — note that for the *enemy* party
   CFRU stores mons NO_ENCRYPT (`handlers.c:1875-1880`), so a plain copy needs no decrypt and the
   ABI has room, but that is a patch change (G4/G5 scope), not this design's. Until either lands,
   the new client cannot do the swap's refresh through `writes.lua`.
7. **`profile.native` does not exist yet.** `lua/gen3/native.lua` reads `profile.native` (BASE,
   SIG, ABI, the staging spans, `INFO`; `:14,40-54`) but `data/games/gen3_rr/profile.json` has no
   `native` block, and the old client's addresses live in `lua/mailbox.lua:13` +
   `patch/src/ADDRESSES.md:59-77`. The pack field has to be added (generator + a
   `test_gen3_write_checkpoint`-style assertion) before either the module or a `native` clause can
   be exercised; that is a pack change, i.e. not this card.
8. **The `native` clause set is a decision, not a derivation.** Dropping `cpu` and the overworld
   predicates for this reason is argued in §3.5 (the arena is not game state; the hook is
   frame-driven; two ops require battle), but it is the coordinator's call whether the predicate
   should *additionally* require the overworld callback pair for the ops that only make sense on
   the field (`OP_SPAWN_PEER_NPC`, `OP_SHOW_MENU`, …). If it should, that belongs in the op's
   `valid()` hook, not in the reason's clause set — otherwise the two in-battle ops become
   unpostable.
