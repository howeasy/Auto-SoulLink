# Active-battler faint in battle: scope (card C4-ACTIVE-FAINT-SCOPE, 2026-09-23)

Static research only. No emulator run, no code or pack change; this file is the only edit. The owner's request was
"scope the faint change": today, when a linked partner dies while our linked mon is the ACTIVE battler, the new
Gen 3 client holds the write (`lua/gen3/client.lua:699-706`, `return "hold", "active battler"`) and applies it on
switch-out or battle end (PLAN §0 row "In-battle faint", `docs/gen3/PLAN.md:16`). The question is what it would take
for the active mon to faint promptly, through the game's own sequence ("X fainted!", then the forced send-out, or a
whiteout).

**Sources.** pret/pokefirered `c75f3523` (`E:/Google Drive/SLink/.cache/pret/pokefirered`; pret paths below are
relative to it). Symbols come from `data/gen3/pret/pokefirered.sym` and `pokeleafgreen.sym`; every address used here is
equal in both. Repo HEAD is `89442a97`.

**Tags.** **PROVEN** means read from pret source or repo source. **INFERRED** means reasoned from proven facts but not
read or witnessed. **OPEN** means not settled. Everything here is SOURCE-grade. Nothing is PHYSICAL.

---

## 0. Answer

1. **A raw HP write to the active battler does not produce the faint sequence.** Only `Cmd_tryfaintmon` prints
   "X fainted!", plays the faint animation, sets `HITMARKER_PLAYER_FAINTED`, and bumps `playerFaintCounter`, and it
   runs only inside battle scripts. A 0-HP battler with no script touching it gets a *silent* faint: no message, no
   animation, no "Use next POKéMON?" prompt, and the party screen is forced (§2a).
2. **"The engine refreshes an active battler's gBattleMons" is not true in pret** (§1.4). No per-frame party→battle
   copy exists. The real hazard runs the other way: a party-only write is overwritten by the next `datahpupdate`
   (battle→party).
3. **There is a clean engine hook: Perish Song with its counter at 0.** At the parked action menu we write the
   Perish flag and a zero counter for our battler, plus a committed no-op action (`B_ACTION_NOTHING_FAINTED`),
   through the existing `battle_commit` reason. At the end of that turn the engine runs its own
   `BattleScript_PerishSongTakesLife` (HP bar drains → `datahpupdate` → `tryfaintmon` → "X fainted!"). Then
   `HandleFaintedMonActions` gives the vanilla "Use next POKéMON?" prompt (wild), the forced party screen (trainer),
   or a whiteout (last mon). SLink writes no HP at all. The one extra line of text is "X's PERISH count fell to 0!"
   (§2d).
4. **Recommendation:** implement mechanism **P** (§2d) on **FR/LG singles, battler 0 only**. Keep the hold for
   doubles, RR, locked turns and every non-player controller. RR cannot follow as things stand: `battle_commit` is
   held there (`a1bbc686`), and CFRU's end-turn and struct layout are OPEN (§4). Adopting P therefore **breaks
   literal FR/LG↔RR parity**. That is an owner decision. If strict parity wins, keep the hold. Estimated cost is about
   300-400 lines including tests, plus about 4 live duo launches (§6).

---

## 1. The FRLG faint pipeline

### 1.1 Where HP 0 is detected

| Point | What it tests | Cite | Tag |
|---|---|---|---|
| `Cmd_tryfaintmon` (script opcode 0x19) | `!(gAbsentBattlerFlags & bit) && gBattleMons[b].hp == 0`. Then it sets `HITMARKER_FAINTED(b)`, pushes `BattleScript_FaintAttacker/Target` (cry, `dofaintanimation`, `cleareffectsonfaint`, "fainted!"), and, for the player side, sets `HITMARKER_PLAYER_FAINTED`, `playerFaintCounter++` and `AdjustFriendshipOnBattleFaint`. This is the **only** place any of these happen. | `src/battle_script_commands.c:2831-2917` (test `:2866-2867`, player side `:2871-2876`); scripts `data/battle_scripts_1.s:2801-2817` | PROVEN |
| `HandleFaintedMonActions` | Case 1: `gBattleMons[b].hp == 0 && !givenExpMons && !absent` → `BattleScript_GiveExp`. Case 4: `hp == 0 && !absent` → `BattleScript_HandleFaintedMon`. It does **not** require `HITMARKER_FAINTED`. Returns FALSE at once in Safari. | `src/battle_util.c:1144-1230` (Safari `:1146-1147`, case 1 `:1162-1172`, case 4 `:1186-1197`) | PROVEN |
| Callers of `HandleFaintedMonActions` | (i) `HandleAction_TryFinish`, which is `B_ACTION_TRY_FINISH` and is set by every script `end`/`end2`, i.e. **after every action**. (ii) `BattleTurnPassed` at end of turn. | `src/battle_main.c:4433-4440`; `src/battle_script_commands.c:3797-3809`; `src/battle_main.c:2965` | PROVEN |
| `BattleScript_HandleFaintedMon` | `checkteamslost` (party HP sum → `B_OUTCOME_LOST`), then `jumpifbyte gBattleOutcome != 0 → end`. In a wild battle **with `HITMARKER_PLAYER_FAINTED`** it shows "Use next POKéMON?"; answering No runs `jumpifplayerran`. Otherwise it goes to `openpartyscreen BS_FAINTED` (forced send-out). Singles ends with `cancelallactions`. | `data/battle_scripts_1.s:2824-2888` (prompt gate `:2827`) | PROVEN |
| `Cmd_checkteamslost` | Reads **party** HP (`GetMonData(&gPlayerParty[i], MON_DATA_HP)`), not `gBattleMons`. | `src/battle_script_commands.c:3385-3401` | PROVEN |
| `gAbsentBattlerFlags` | Set only by `openpartyscreen` when there is no replacement (`HasNoMonsToSwitch`, which is always FALSE in singles). Cleared in `HandleFaintedMonActions` case 0 for doubles. Copied to `gBattleStruct->absentBattlerFlags` at turn start. | `src/battle_script_commands.c:4643-4677,4866-4871`; `src/battle_util.c:1542-1548,1155-1160`; `src/battle_main.c:2911,2997` | PROVEN |
| `faintedActionsState` | Reset at the first turn and after every completed pass: `TryDoEventsBeforeFirstTurn :2923`, `BattleTurnPassed :2967`, `HandleAction_TryFinish :4437`. | same | PROVEN |

### 1.2 What reads `gBattleMons[b].hp` and what reads party HP

- **`gBattleMons[b].hp` is read by:** `tryfaintmon`, both `HandleFaintedMonActions` loops, `attackcanceler`
  (`if (gBattleMons[gBattlerAttacker].hp == 0 …) → BattleScript_MoveEnd`, `src/battle_script_commands.c:828-833`),
  damage and `datahpupdate` (`:1744-1866`), and end-turn effects (`src/battle_util.c:744+`). **PROVEN**
- **Party HP is read by:** `checkteamslost`, `HasNoMonsToSwitch` and the send-out party menu
  (`src/battle_util.c:1590-1596`), exp distribution (`src/battle_script_commands.c:3282`), and item use. **PROVEN**
  (`battle_write_predicate.md` §2.3 lists the rest.)

### 1.3 When the engine copies battle→party and party→battle

- **Battle → party (`BtlController_EmitSetMonData`).** On every HP change in a script (`datahpupdate` `:1861-1862`,
  `setatkhptozero` `:6300-6302`). The player controller writes it straight into
  `gPlayerParty[gBattlerPartyIndexes[b]]` (`src/battle_controller_player.c:2019-2020`). Status and PP go the same way.
  **PROVEN**
- **Party → battle.** Only at these points (**PROVEN**):
  - the intro: `BattleIntroGetMonsData` + `BattleIntroDrawTrainersOrMonsSprites`, `src/battle_main.c:2519-2588`;
  - switch-in: `getswitchedmondata`/`switchindataupdate`, `src/battle_script_commands.c:4452-4495`;
  - the level-up refresh in `Cmd_getexp`, **guarded by `gBattleMons[0].hp` / `[2].hp` being non-zero**, `:3317-3345`;
  - item use: `CopyPlayerPartyMonToBattleData`, `src/pokemon.c:3916-3945,4270,4322`;
  - the unused `Cmd_updatebattlermoves` (`:5388-5398`).

### 1.4 Is "the engine refreshes an active battler's gBattleMons" true?

**No, not per frame and not on FR/LG.** **PROVEN** from §1.3: party→battle happens only at the points listed there.
The comment in `lua/gen3/client.lua:703-704` ("a direct write races it"), inherited from the old client
(`lua/clients/gen3_frlge_client.lua:795-797`), describes a hazard that pret does not have. The real hazards are:

1. **A party-only write is undone.** The next `datahpupdate` on that battler copies `gBattleMons.hp` back into the
   party (`:1861` → `battle_controller_player.c:2020`). **PROVEN**
2. **Writing both HP words is stable but silent.** Nothing is overwritten, but no script processes the faint: see §2a.
   **PROVEN**
3. **On RR, whether CFRU adds a refresh is OPEN.** The old client wrote both words anyway in `M.forceFaint`
   (`lua/memory_gba.lua:1277-1287`).

**A correction to `docs/gen3/research/battle_write_predicate.md` §4 reason 2** (`:349-354`). That section says that
"a mon whose gBattleMons.hp SLink zeroed would still take its turn (and could KO its opponent)". Part of this is
right: `HandleAction_UseMove` has no HP check. But the move script's first command, `attackcanceler`, sends a 0-HP
attacker to `BattleScript_MoveEnd` (`src/battle_script_commands.c:828-833`), so a zeroed mon **cannot use a move**.
It can still switch, run, or use an item (§2a). Reasons 1 and 3 of that section stand.

---

## 2. Candidate mechanisms (safest first)

Every candidate writes at **the parked action menu**. This is the frame the battle permit already admits: the seven
`battle` clauses in `data/games/gen3_frlg/write_checkpoint.json:50-135` (`gBattleMainFunc == HTAS`,
`gBattleCommunication[0] == 1`, exec flags `== 1`, `gBattlerControllerFuncs[0] == HandleInputChooseAction`, not link,
engine loaded, outcome open). **PROVEN**

At that frame the opponent has already chosen: the exec word is exactly battler 0's bit (`battle_write_predicate.md`
§3.1). **INFERRED** from the clause.

### (a) Write `gBattleMons[b].hp = 0` and party HP = 0, then let the player's action run

- **Writes.** The existing `faint_plan(slot, battler)` (`lua/gen3/client.lua:600-608`) through `battle_faint`.
  That is the old `M.forceFaint` shape (`lua/memory_gba.lua:1277-1287`).
- **What the engine then does.** The player picks from the live menu.
  - **FIGHT.** When our turn comes, `attackcanceler` stops the move (`:828-833`); the mon does **not** act.
    **PROVEN**
  - **SWITCH / RUN / BAG.** These go ahead. Switching withdraws the 0-HP mon cleanly. RUN can succeed in a wild
    battle: `IsRunningFromBattleImpossible` and `HandleAction_Run` never read HP (`src/battle_main.c:3002-3048`,
    `:4283-4330`). A Revive on the active mon brings it back (`src/pokemon.c:4258-4272`). **PROVEN**
- **When the faint fires.** At the first `TRY_FINISH` of the turn, i.e. after whichever action runs first
  (`src/battle_main.c:4433-4440`). **PROVEN**
  - **Clean sequence only by accident.** It happens only if that first action is a foe damaging move that connects
    on our battler. Its script runs `tryfaintmon BS_TARGET` → "X fainted!" (§1.1). **PROVEN**
  - **Otherwise silent.** This covers our mon moving first, the foe using a status move or missing, and the foe
    being slower. `HandleFaintedMonActions` runs `GiveExp` → `HandleFaintedMon` with **no** cry, animation, "fainted!"
    text or `cleareffectsonfaint`. `HITMARKER_PLAYER_FAINTED` is never set, so a wild battle skips "Use next
    POKéMON?" and forces the party screen (`data/battle_scripts_1.s:2827`). `playerFaintCounter` does not move
    (§1.1). **PROVEN**
  - **Stale sprite.** Without `dofaintanimation` the old battler sprite is never destroyed before the send-out
    creates the new one, which may leave it visible. **INFERRED** (not traced through
    `battle_controller_player.c`'s send-out sprite code).
- **Verdict.** The outcome is correct: the mon is out, and a whiteout follows if it was the last (`checkteamslost`
  reads party HP). The sequence is **not** the game's own in the common case. **Not clean.**

### (b) Write HP 0 plus a forced no-op action (skip the mon's turn)

- **Writes** (reason `battle_commit`):
  - `faint_plan` as in (a);
  - `gChosenActionByBattler[b] = B_ACTION_NOTHING_FAINTED (13)`;
  - `gBattleCommunication[b] = 3` **last**.

  This is the engine's own shape for an absent battler (`src/battle_main.c:3113-3118`), and the same commit shape as
  Explode's `commit_plan` (`lua/gen3/client.lua:614-640`). **PROVEN**
- **What the engine then does.**
  1. State 3 waits until battler 0's exec bit clears (`:3350-3353`). The bit belongs to the still-open action menu,
     so **the player must press A once**. Whatever they pick is discarded: `HandleInputChooseAction` only emits the
     action type and completes (`src/battle_controller_player.c:225-245`). **PROVEN**
  2. The screen sequence is then the same as vanilla RUN's: RUN emits nothing between the press and the standby
     message (`:3257`, `:3326-3328`, `:3350-3366`). **PROVEN**
  3. The turn runs `HandleAction_NothingIsFainted`, a silent increment (`src/battle_main.c:4442-4451`; table
     `:577`). `GetWhoStrikesFirst` reads a move only for `B_ACTION_USE_MOVE` (`:3485-3495`). **PROVEN**
  4. The faint fires at the first `TRY_FINISH`, exactly as in (a).
- **Verdict.** This fixes "the mon acts / runs / switches" but is still **silent** unless the foe's hit lands first.
  **Not clean.**

### (c) Reuse Explode Mode's forced Explosion

- **Writes.** `commit_plan(battler, true)` (`lua/gen3/client.lua:614-640`): four move slots set to Explosion,
  `chosenAction = 0`, `chosenMove = 153`, `chosenMovePositions`, `moveTarget`, then `comm = 3` last. The engine runs
  `BattleScript_EffectExplosion` → `setatkhptozero` → the whole faint path (`data/battle_scripts_1.s:376-398`).
  **PROVEN**
- **Costs.**
  - It **damages the opponent**. Explosion has 250 power and Gen 3 halves the target's Defense. It can KO a wild mon
    the player wanted to catch, or hand out exp.
  - Damp blocks it, and the entry then falls back to the hold (`lua/gen3/client.lua:668-676`).
  - It needs the same single A press as (b).
  - The FRLG pack lacks `CHOSEN_ACTION_ADDR`/`CHOSEN_MOVE_ADDR`/`BATTLE_COMM_ADDR`, so `explode_capable` is false on
    vanilla (`lua/gen3/client.lua:547-548`, `:611-613`; `data/games/gen3_frlg/profile.json` carries none of these).
  - The server offers Explode Mode for RR only (`server/manager.py:135`).
- **Verdict.** Clean as a *faint*, but it changes the battle. It is Explode Mode's contract, not `force_faint`'s.
  **Not acceptable here.** **PROVEN** (costs) / **INFERRED** (acceptability)

### (d) Engine hooks, and the recommended mechanism P = (b) + Perish counter 0

#### Hooks considered and rejected

- **`gBattleMoveDamage`.** Only a running script consumes it (`datahpupdate`). `BattleTurnPassed` and
  `HandleAction_ActionFinished` zero it (`src/battle_main.c:2978`, `:4464`). A write at the menu does nothing.
  **PROVEN**
- **Pointing `gBattlescriptCurrInstr` or the battle callback stack at a faint script.** This hijacks control flow, and
  FR/LG has no SLink-owned bytes to point at. Rejected on safety grounds. **INFERRED**
- **Future Sight or Doom Desire damage.** The script runs `accuracycheck` and can miss
  (`data/battle_scripts_1.s:3461-3468`). **PROVEN**
- **Poison or Curse plus a small HP.** This needs a `gBattleMons` HP write and a visible status change, and prints the
  wrong text. It is dominated by P. **INFERRED**

#### Mechanism P: Perish counter 0 + no-op commit (recommended)

**Writes** (one `armed_write("battle_commit", plan, {battler = b})`; `comm` last, as `commit_plan` requires,
`lua/gen3/client.lua:634-637`):

| # | Address (FR = LG, SYM) | Width | Value | Why |
|---|---|---|---|---|
| 1 | `gStatuses3[b]` = `0x02023DFC + 4b` | 4 | current \| `STATUS3_PERISH_SONG (0x20)` | `include/constants/battle.h:138` |
| 2 | `gDisableStructs[b].perishSongTimer` = `0x02023E0C + 0x1C*b + 0x0F` | 1 | `0x00` (timer 0 in the low nibble; the high nibble is `…StartValue`, read only by Baton Pass's copy) | `include/battle.h:139-172`; `src/battle_main.c:2386-2391` |
| 3 | `gChosenActionByBattler[b]` = `0x02023D7C + b` | 1 | `13` (`B_ACTION_NOTHING_FAINTED`) | `include/battle.h:48`; `src/battle_main.c:577` |
| 4 | `gBattleCommunication[b]` = `0x02023E82 + b` | 1 | `3` (`STATE_WAIT_ACTION_CONFIRMED_STANDBY`) | `src/battle_main.c:3087-3095,3350-3366` |

No HP word is written, in the party or in `gBattleMons`.

**What the engine does, step by step.** **PROVEN** unless tagged.

1. **The press.** The player presses A once on the still-open menu; the choice is discarded (as in (b)).
2. **The standby state.** State 3 emits the stop-bounce standby message and moves to 4 (`:3350-3366`). Once every
   battler is counted, `SetActionsAndBattlersTurnOrder` runs (`:3388-3389`).
3. **The turn.** Our slot runs `HandleAction_NothingIsFainted`. The foe acts normally.
   - If the foe's damaging hit KOs us first, `tryfaintmon BS_TARGET` gives a clean faint. `cleareffectsonfaint` →
     `FaintClearSetData` zeroes `gStatuses3[b]` and `gDisableStructs[b]` (`src/battle_main.c:2440-2457`), so the
     Perish flag dies with the mon and there is no double faint.
4. **End of turn.** `BattleTurnPassed` runs field effects, battler effects, `HandleFaintedMonActions` (nothing yet),
   then `HandleWishPerishSongOnTurnEnd` (`src/battle_main.c:2957-2969`).
   - Our battler has `STATUS3_PERISH_SONG` with timer 0. That sets `gBattleMoveDamage = gBattleMons[b].hp` and runs
     `BattleScript_PerishSongTakesLife` (`src/battle_util.c:1100-1124`).
   - The script prints "X's PERISH count fell to 0!" (`src/battle_message.c:205`), drains the HP bar, and runs
     `datahpupdate` with `HITMARKER_IGNORE_SUBSTITUTE`. That ignores Substitute, and nothing in `datahpupdate` checks
     Endure (`src/battle_script_commands.c:1744-1866`). The engine writes HP 0 to `gBattleMons` **and to the party**
     (`:1861`).
   - It then runs `tryfaintmon BS_ATTACKER` (`data/battle_scripts_1.s:3391-3398`), which gives the full
     `BattleScript_FaintAttacker`, `HITMARKER_PLAYER_FAINTED`, `playerFaintCounter++`, and the friendship drop (§1.1).
   - Grudge is suppressed: `HITMARKER_GRUDGE` is set at `src/battle_util.c:1066` and tested at
     `src/battle_script_commands.c:2894-2896`.
5. **The follow-up.** `BattleScriptExecute` returns to `BattleTurnPassed` (`src/battle_util.c:2428-2434`).
   `faintedActionsState` was reset at `:2967`, so `HandleFaintedMonActions` now processes our battler:
   `GiveExp` (player side: no-op) → `BattleScript_HandleFaintedMon`. The result is one of:
   - "Use next POKéMON?" in a wild battle (No → try to run);
   - the forced party screen in a trainer battle;
   - `checkteamslost` → `B_OUTCOME_LOST` → whiteout (`data/battle_scripts_1.s:2824-2888`,
     `src/battle_main.c:3769-3796`).

   This is byte-for-byte the engine's path for a real Perish Song KO.

**Verdict.** Clean: the engine's own faint sequence, with one extra message line. SLink writes no HP.

### 2.1 Edge cases (P unless noted; (a) in brackets where it differs)

| Case | Behaviour | Tag |
|---|---|---|
| **Last usable mon** | Perish KO → `checkteamslost` sees party HP 0 → LOST → "X is out of usable POKéMON… whited out", then `DoWhiteOut` heals the party at the Center. The client already reports `whiteout` (`lua/gen3/client.lua:537-538`), and the server runs its whiteout rebuild (`lua/tests/duo/scenario_gen3_whiteout.lua:1-11`). **Behaviour change:** today the hold path lands HP 0 on the overworld with no in-game whiteout. [(a): the same whiteout, silently.] | PROVEN (engine) / INFERRED (server flow) |
| **Wild battle** | Running is impossible on the commit turn (the choice is discarded). After the faint, "Use next POKéMON?" → No runs `jumpifplayerran`, so running is still possible via the vanilla prompt (`data/battle_scripts_1.s:2827-2834`). [(a): RUN on the commit turn works; no prompt later.] | PROVEN |
| **Trainer battle** | Forced party screen; running is never possible (`src/battle_main.c:3239-3245`). | PROVEN |
| **Doubles** | The permit is battler 0's menu only. Battler 2 is in state 0 at that frame (`:3110-3113`), so a battler-2 commit would pass the guard and behave like the engine's absent path. But the D1-D5 rows are signed limits (`docs/gen3/G4_request_draft.md:269`), and a partner B-cancel (`CANCEL_PARTNER`, `src/battle_controller_player.c:286-301`, `src/battle_main.c:3232-3237`) resets battler 0 to state 0, which undoes the no-op while the Perish flag stays. **Scope P to singles** (`battlers_count == 2`) and keep doubles held as today. | PROVEN (mechanics) / INFERRED (cancel interplay) |
| **Old man, Oak's first battle, Pokédude** | `SetControllerToOakOrOldMan` / `SetControllerToPokedude` (`src/battle_controllers.c:89-104`) are refused by `battle_input_controller`, so there is no write. The entry stays held → battle end → overworld (existing path). | PROVEN |
| **Safari** | Safari controller → refused. `HandleFaintedMonActions` also returns FALSE in Safari (`src/battle_util.c:1146`), and there is no player battler (`src/battle_main.c:2566-2571`). | PROVEN |
| **Link** | `battle_not_link` refuses. | PROVEN |
| **Mid-move / charging / Bide / Outrage / Rollout / Uproar / recharge** | `STATUS2_MULTIPLETURNS` or `STATUS2_RECHARGE` makes state 0 auto-commit `USE_MOVE` with no menu (`src/battle_main.c:3125-3129`). `setbide` sets `MULTIPLETURNS` (`src/battle_script_commands.c:6839-6846`). The permit never holds, so the entry stays held until the lock ends (≤5 turns) and commits at the first parked menu. The mon keeps fighting while locked. | PROVEN |
| **Pending switch** | Nothing is pending for battler 0 at the parked menu (`monToSwitchIntoId` reset, `:3109`). The forced send-out after another faint runs under a script main function and is refused (`rr_battle_tuple` §4; `battle_write_predicate.md` §3.4). A foe Roar/Whirlwind drags us out: `SwitchInClearSetData` clears `gStatuses3` (not Baton Pass, `src/battle_main.c:2367-2371`). The benched mon then takes the existing bench write at the next menu. | PROVEN |
| **Baton Pass** | Blocked by the no-op commit: our mon cannot use a move. Without the commit (a Perish-only write) Baton Pass would carry `STATUS3_PERISH_SONG` and the 0 timer to the replacement (`src/battle_main.c:2350-2353`, `:2386-2391`) and kill it. **This is why P needs the commit.** | PROVEN |
| **Perish Song already running** | Our timer is overwritten to 0. A foe Perish Song afterwards skips battlers that are already flagged (`src/battle_script_commands.c:8139-8143`). | PROVEN |
| **Destiny Bond** | The Perish death is not an attack. `HITMARKER_DESTINYBOND` is cleared at every action end (`src/battle_main.c:4446,4458`), and our mon does not attack. No trigger either way. | PROVEN |
| **Exp** | The foe gets none (Gen 3). Our dead mon gets no further exp (`src/battle_script_commands.c:3282`). | PROVEN |
| **Evolution** | `TryEvolvePokemon` walks `gLeveledUpInBattle` with no HP test (`src/battle_main.c:3880-3907`). A linked mon that levelled earlier in the battle can still evolve after a win. That is the same as a natural Gen 3 faint, and the same exposure as today's hold. | PROVEN / INFERRED (no regression) |
| **Friendship** | New side effect: `AdjustFriendshipOnBattleFaint` (`:2875`), which the hold path never applies. It is cosmetic for a dead mon. | PROVEN |
| **Battle ends before the turn does** (foe flees, catch, or the foe's last mon faints **during an action**: recoil, Self-Destruct, a hit) | The action's `HandleAction_TryFinish` → `HandleFaintedMonActions` → `checkteamslost` sets the outcome (`src/battle_main.c:4433-4440`; `src/battle_script_commands.c:3385-3413`), and `RunTurnActionsFunctions` then jumps to `sEndTurnFuncsTable[outcome]`, skipping `BattleTurnPassed` (`src/battle_main.c:3706-3715`), so Perish never fires. The entry stays held → `battle_write(…, ending=true)` → overworld. This is today's fallback. | PROVEN |
| **The foe's last mon faints at END OF TURN** (poison, burn, Leech Seed, weather, Curse, Nightmare, trap damage) *(corrected 2026-09-23, review follow-up 2)* | The faint is processed inside `BattleTurnPassed`: its `HandleFaintedMonActions` → `checkteamslost` sets WON, but `HandleWishPerishSongOnTurnEnd` is **not** gated on the outcome (`src/battle_main.c:2958-2968`), so Perish **does** fire. If our P-committed mon was our last usable one, its `checkteamslost` ORs in LOST → `B_OUTCOME_DREW` (3), and `sEndTurnFuncsTable[DREW] = HandleEndTurn_BattleLost` (`:585`): **a whiteout in a battle the player won**. If it was not our last, the outcome stays WON (no send-out). Behaviour unchanged; owner call pending. Unit: `test_p_draw_edge_today_…`. | PROVEN (source) |

---

## 3. Fit with the safety model

- **Reason: `battle_commit`**, i.e. the seven clauses plus `commit_guard` `gBattleCommunication[b] < 3`
  (`lua/gen3/safety.lua:204-247`; `data/games/gen3_frlg/write_checkpoint.json:124-133`). FR/LG carries **no**
  `commit_hold`, so the reason is live there. **PROVEN**
  - `battle_faint` alone is not enough: it has no guard, and P must not overwrite a battler that is already committed.
  - The plan writes `comm` last, because `writes.lua` re-validates the guard before every byte
    (`lua/gen3/client.lua:634-636`).
  - `armed_write` supports widths 1/2/4 (`:563-572`). The `gStatuses3` value is read and OR-ed on the same parked
    frame. **INFERRED** safe: the engine is parked, and the only readers (switch/run checks, turn scripts) run later.
- **Lag-frame window.** The 2026-09-23 conclusion still holds for P. A frame end inside the action-commit call means
  the player has emitted only the action *type* (`src/battle_controller_player.c:232-241`). `comm = 3` makes the
  engine ignore it: the coordinator follow-up says "the forced move stands"
  (`docs/gen3/research/battle_lag_frame_census_design_2026-09-23.md:250-270`), and here the forced *no-op* stands. The
  Perish words are not read by that call. FR/LG has no L-throw in `HandleInputChooseAction`: its only inputs are A,
  the D-pad, B and START (`src/battle_controller_player.c:219-307`). **PROVEN**
- **Liveness.** The write needs a parked menu, and completing the turn needs **one player A press**. That matches the
  hold's own dependency on player input. The HUD line should say so (INFERRED UX). Entry state machine: commit → wait
  for `gBattleMons[b].hp == 0` (done), or the battler to leave (bench path), or the battle to end (overworld path).
  Re-commit if the engine resets `comm < 3`. This is the same shape as `explode_step` (`lua/gen3/client.lua:648-688`).
  The core already retries held entries every frame (`lua/core/session.lua:44-50,168-198`).
- **Echo.** The engine faint fires the `faint` site (`Cmd_tryfaintmon` +0x11C,
  `data/games/gen3_frlg/engine_signals.json:129-156`). Calling `mark_commanded(key)` at commit time
  (`lua/gen3/client.lua:305-306`) clears `st.alive`, so `settle_faints` sends no `faint` for our own KO (`:336-343`).
  **PROVEN**
- **Server / protocol.** No change. The command stays `force_faint`, the ACK path is unchanged, and the tick carries
  party HP 0 as before. One behaviour difference: the last-mon case now produces a real `whiteout` message (§2.1),
  which the server already handles. **INFERRED**

---

## 4. Parity

- **Old client, FR/LG and RR (`lua/clients/gen3_frlge_client.lua:740-816`, flush `:2555-2596`).**
  - `force_faint` on the active battler goes to `pending_battle_faints` and is applied by `M.forceFaint` (party +
    `gBattleMons` HP) when the mon is no longer active or the battle ends.
  - `force_explode` uses the Variant-3 menu skip on RR only; the helper refuses on non-RR (`:771-790`).
  - **Both titles hold the active `force_faint`.** **PROVEN**
- **New client today.** It holds on both packs (`lua/gen3/client.lua:699-706`). RR also holds `battle_commit` outright:
  `commit_hold`, `a1bbc686`. CFRU's controller stays live after `comm = 3`, and an L press runs `RemoveBagItem`
  `0x090AA114` (`docs/gen3/research/rr_battle_tuple_2026-09-23.md:38-40,55`). **PROVEN**
- **The owner's ruling** (`docs/gen3/PLAN.md:16`) set parity to *the hold*. P on FR/LG alone makes vanilla behave
  better than RR. **Parity breaks**, and the owner has to accept that direction explicitly.
- **What RR would need for P** (all **OPEN**; this is G5 work):
  1. CFRU byte proof that end-turn Perish still reads `gStatuses3`/`gDisableStructs` with vanilla semantics. The RR
     `BattleTurnPassed` body differs: 12 bytes are NOP-ed at `0x08013BEC` (`rr_battle_tuple` §2). CFRU extends
     `DisableStruct`, so the stride and offset must be re-derived.
  2. A way around `commit_hold`. Either prove the post-commit L-throw harmless, or move the whole operation into the
     companion: a new mailbox opcode that runs the same writes (or calls CFRU's faint script) from `slink_hook`. That
     means a patch rebuild, `ADDRESSES.md`, and a companion re-pin. RR clean, with no companion, would keep the hold.
  3. The RR battle duo fixtures, which are not built yet (`lua/tests/duo/scenario_gen3_explode.lua:19-20`).

---

## 5. Test plan

- **Carrier.** Reuse `linked_faint_active_gen3` (`lua/tests/duo/scenario_gen3_linked_faint_active.lua`).
  - A's side is unchanged: a natural faint of its linked lead.
  - B parks with the linked lead as battler 0. `READY_ACTIVE` / `force_faint` RX stay as now. `ACTIVE_HOLD` becomes
    `ACTIVE_COMMIT`: the client reports the committed entry and zero HP bytes attempted.
  - B presses A once (FIGHT), then runs the scripted send-out policy.
  - `tools/e2e_duo.py:5718-5719` gets the new marker set.
- **Variants.**
  - **Whiteout:** B with a one-mon party.
  - **Trainer:** reuse the R-T route of `scenario_gen3_battle_window.lua`.
  - Two title orientations (`gen3_frlg`, `gen3_lgfr`).
- **Oracles** (engine reads, never the client's own RESULT):
  - **O1.** `gBattleResults.playerFaintCounter` (`0x03004F90` +0) moves by exactly 1 across the commit→faint window.
    Only `tryfaintmon` increments it.
  - **O2.** The `faint` site fires with `gActiveBattler == 0` while `gBattlerPartyIndexes[0] == slot`.
  - **O3.** `gBattleResults.lastUsedMovePlayer` (+0x22, stamped at `src/battle_main.c:4022`) is unchanged: the mon did
    not act.
  - **O4.** At the faint frame `in_battle` is still true, and both `gBattleMons[0].hp` and the party HP are 0. The
    engine wrote both; SLink's attempted-byte log shows no HP address.
  - **O5.** `gStatuses3[0] & 0x20` is set after the commit and cleared after the faint.
  - **O6.** Afterwards, either `gBattlerPartyIndexes[0] != slot` or `gBattleOutcome == 2` (the whiteout row). The
    whiteout row also needs the client's `whiteout` TX.
  - **O7.** B's client sends no `faint` for the key.
- **Falsifiers** (each must turn its oracle red; run once each):
  - **F1.** Drop write 3/4 (Perish only) and pick a damaging FIGHT move → O3 fails.
  - **F2.** Replace P with the (a) HP write → O1/O2 fail (silent path).
  - **F3.** Drop `mark_commanded` → O7 fails.
  - **F4.** Write `comm` first → `writes.lua` refuses mid-plan (unit).
  - **F5.** Start a charging move (Fly/Dig) before the command → no write while locked; the commit lands at the next
    parked menu.
- **Units** (`tests/unit/test_gen3_client.py`, lupa):
  - plan addresses, values and order;
  - a guard refusal at `comm >= 3`;
  - the RR pack (`commit_hold`) → hold;
  - `battlers_count == 4` → hold;
  - `MULTIPLETURNS` → hold;
  - the echo suppression.

---

## 6. Cost and recommendation

| File | Change | Size |
|---|---|---|
| `lua/gen3/client.lua` | `perish_plan` + an `active_faint_step` state machine beside `explode_step`; `battle_write` active branch (`:699-706`) routes FR/LG singles battler 0 to it | ~60-80 lines |
| `data/games/gen3_frlg/profile.json` via `tools/gen_gen3_profile.py` (`SECTION` `:325-352`) and its Lua source table | add `STATUS3_ADDR`, `DISABLE_STRUCTS_ADDR`, `DISABLE_STRUCT_SIZE`, `PERISH_TIMER_OFF`, plus the chosen-action and comm addresses for FR and LG (SYM, equal) | ~20 lines + regen |
| `tests/unit/test_gen3_client.py` (+ profile test) | §5 units | ~100-150 lines |
| `lua/tests/duo/scenario_gen3_linked_faint_active.lua`, `tools/e2e_duo.py`, `tests/unit/test_e2e_duo_gen3.py` | B side + oracles + whiteout/trainer variants | ~80-120 lines |
| `docs/gen3/PLAN.md` §0, G4 request | row update; correct `battle_write_predicate.md` §4(2) | docs |
| `lua/gen3/safety.lua`, packs' `battle` block, `server/`, protocol | **none** | 0 |

About 300-400 lines in total. Live runs: 2 orientations of the active duo + 1 whiteout + 1 trainer = **4 launches**,
plus F1/F2 (2 optional).

**Risks.**

1. **`explode_capable` flips.** Adding `CHOSEN_ACTION_ADDR`/`CHOSEN_MOVE_ADDR`/`BATTLE_COMM_ADDR` to the FRLG pack
   makes `explode_capable` true on vanilla (`lua/gen3/client.lua:547-548`). The server keeps Explode RR-only
   (`server/manager.py:135`), but the client should gate explode on its own flag, or P should use differently named
   fields.
2. **One A press.** The commit needs a press. A player who never presses sees nothing happen, the same as today's
   hold.
3. **Wording.** The "PERISH count fell to 0!" line is not "X fainted!" alone.
4. **Whiteout.** The last-mon case now produces a real whiteout (party heal + rebuild) instead of an overworld HP-0
   party.
5. **Parity.** RR diverges (§4).
6. **Evidence.** Everything is SOURCE-grade. PHYSICAL receipts are a G4 extension, like the existing 2b rows.

**Recommendation.**

- **If the owner accepts FR/LG ahead of RR:** implement P for FR/LG singles battler 0. Keep the hold everywhere else
  (doubles, RR, locked turns, non-player controllers), and file the RR port as a G5 card (§4 items 1-3).
- **If parity with RR is binding:** **keep the hold** on both.
- **Either way:** reject (a), (b) and (c). (a) and (b) are silent faints; (c) damages the opponent.
- **Independently of the decision:** fix the stale "the engine refreshes gBattleMons" comment at
  `lua/gen3/client.lua:703-704`, since the hold's real reason is §1.4 point 2.

## 7. Open

1. The stale-sprite claim for the silent path (§2a) has not been traced through the player controller's send-out code.
2. Whether the action-menu window stays drawn after the discarded press until the first battle message. It should
   look the same as RUN (§2b), but no physical row has checked it.
3. Everything about RR/CFRU in §4.
4. A doubles commit on battler 2 at battler 0's parked frame is mechanically plausible (§2.1) but has not been
   witnessed. It is out of scope under decision (d).
