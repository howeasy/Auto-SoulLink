# RR parity for the in-battle active faint (mechanism P): scope, 2026-09-23 (card C5-RR-ACTIVE-FAINT-SCOPE)

Static, bytes-only research for the Gen 3 G5 gate. No emulator run, and no code, pack or patch change. The
only new files are this doc and `tools/research/rr_active_faint.py`.

**The question.** The owner wants RR to match FR/LG. On FR/LG the new client now faints the active linked mon
in battle through the engine's own Perish KO (mechanism P). The commit is `1b3943e3` and the spec is
`active_faint_in_battle_scope_2026-09-23.md` §2d. RR cannot follow today because `battle_commit_hold`
(`a1bbc686`) holds every `battle_commit` there. After a commit, CFRU's parked action menu stays live, and an
L press runs `RemoveBagItem` (`rr_battle_tuple_2026-09-23.md` §1 e).

**Inputs**
- ROMs: RR clean `964f951a`, RR companion `b7d1e075`, and FR `41cb23d8` as the vanilla control. These are the
  pins in `tools/research/rr_save_callers.py`.
- pret/pokefirered `c75f3523` (`E:/Google Drive/SLink/.cache/pret/pokefirered`). It is cited only for bodies
  that are proven byte-identical in RR.
- SLink HEAD `66595498`.

**Tool.** `tools/research/rr_active_faint.py` is new. It reuses the decoders in `rr_battle_tuple.py` and
`rr_save_callers.py`. It asserts 58 byte facts on each RR artifact, and all 116 pass. `--selftest` runs the
known-positive and known-negative FR controls. Every listing cited below can be reproduced with
`rr_save_callers.py --rom clean --disasm ADDR:LEN`.

**Tags.**
- **PROVEN**: read from the RR bytes, or from pret for a body that is FR-identical in both RR artifacts.
- **INFERRED**: reasoned from proven facts, not read or witnessed.
- **OPEN**: not settled.

Nothing here is PHYSICAL.

---

## 0. Answer

1. **CFRU replaces FR's end-turn Perish block, and the replacement does the same thing.**
   - `HandleWishPerishSongOnTurnEnd` is detoured to an RR body that has no Perish code.
   - Perish is state 34 of CFRU's end-turn state machine, `0x090923C8`.
   - That state reads the same RAM with the same layout: `gStatuses3 & 0x20`, and the low nibble of
     `gDisableStructs[b]+0x0F` with stride `0x1C`.
   - At counter 0 it clears the flag, sets `gBattleMoveDamage = hp`, and runs **FR's own**
     `BattleScript_PerishSongTakesLife` (the bytes are identical). That script prints, drains the bar, zeroes HP
     through CFRU's `datahpupdate`, and faints through CFRU's `tryfaintmon`, which raises `PLAYER_FAINTED`,
     `playerFaintCounter++` and the friendship drop.
   - **PROVEN.** §1.
2. **Every address and constant P writes is proven on RR, and the numbers equal FR/LG's** (§2):
   - `gStatuses3` = `0x02023DFC`;
   - `gDisableStructs` = `0x02023E0C`, stride `0x1C`, timer at `+0x0F` (low nibble);
   - `gChosenActionByBattler` = `0x02023D7C`;
   - `gBattleCommunication` = `0x02023E82`;
   - `STATUS3_PERISH_SONG` = `0x20`;
   - `B_ACTION_NOTHING_FAINTED` = `13`, with `sTurnActionsFuncsTable[13]` = `HandleAction_NothingIsFainted`.

   The RR profile already carries the chosen-action, comm and battle-mons addresses. It lacks `STATUS3_ADDR`,
   `DISABLE_STRUCTS_ADDR` and the four derived constants. The old client carries none of the P fields.
3. **The L-throw blocker is closed by one extra 4-byte write in the same plan: the controller hand-off**
   (§3).
   - The write is `gBattlerControllerFuncs[0] = PlayerBufferExecCompleted` (`0x0802E33D`), and it goes last.
   - On the next pass, `BattleMainCB1` calls it for battler 0. The engine's own code (with CFRU's hook) then
     installs `PlayerBufferRunCommand` and clears the exec bit, exactly as a real commit ends.
   - From then on no key reaches CFRU's action-menu body, so no L or R press can reach `RemoveBagItem`
     (literal census, §3.4).
   - As a side effect, RR needs **no A press**; FR/LG still does.
   - The Lua client can do this with plain writes, but **not through today's `writes.lua`**. That sink
     re-checks the permit before every write, and a hand-off plan has two self-invalidating writes (`comm`
     and the controller slot). It needs an opt-in validate-once plan write (§3.3).
   - **No companion opcode and no rebuild are needed.**
4. **CFRU adds nothing that stops the KO in normal play** (§4).
   - State 34 has no ability, item, Dynamax, Z-move or mega test.
   - Substitute is bypassed by the script's `IGNORE_SUBSTITUTE`, and Disguise and Ice Face are skipped for
     passive damage.
   - The one exception depends on a CFRU flag whose meaning is OPEN. Even in that case the client re-commits
     and the next KO lands.
5. **Recommendation: port P to RR with the in-plan hand-off (mechanism P+H).** It is data-gated, has no title
   in `client.lua`, and needs no rebuild. The hold is lifted only for plans whose last entry is the proven
   hand-off, so Explode stays held. The cost is about 250-350 lines with tests, plus building the RR battle
   fixtures, plus about 5 live launches (§5). The residual risk is the known lag-frame window, and on RR it has
   a ball-loss outcome (§3.5). Record it as a limit. The companion opcode is the upgrade path if that is ever
   unacceptable.

---

## 1. CFRU's end-of-turn Perish handling

| # | Fact | Bytes | Tag |
|---|---|---|---|
| 1.1 | FR's `HandleWishPerishSongOnTurnEnd` (`0x08018C98`) is entry-detoured to `0x090936CD`. That RR body handles an RR-specific scripted event (it tests `FlagGet(0x91A)` and `gBattleResults+0x13 > 8`, then runs `0x09002D0F`/`0x09002CB4`). It never reads `gStatuses3`, and it returns 0 otherwise. | `rr_save_callers --disasm 90936cc:0xd0` | PROVEN |
| 1.2 | FR's Perish block survives only as dead bytes behind that detour. The **only** live loads of the two Perish scripts are in CFRU: `LDR@0x09092420 = 0x081D8D33` (TakesLife) and `LDR@0x09092438 = 0x081D8D4E` (CountGoesDown). The other sites, `0x08018F0E`/`0x08018F3E`, are the dead FR body. | `refs` census | PROVEN |
| 1.3 | `BattleTurnPassed` (RR body): `BL DoBattlerEndTurnEffects @0x08013BF8`, then `BL HandleFaintedMonActions @0x08013C04`, then `HandleWishPerishSongOnTurnEnd`. The 12 NOP bytes at `0x08013BEC` are where FR called `DoFieldEndTurnEffects`, which CFRU folds into its own state machine. | disasm `8013bd4:0x60` | PROVEN |
| 1.4 | `DoBattlerEndTurnEffects` is detoured to `0x090910B5`. That is a state machine over `gBattleStruct[0]` (state 1..62, `cmp #0x3e`) and `gBattleStruct[1]` (turn-order index). The dispatch is `bl 0x090003D6` (gcc `case_uhi`) with its table at `0x0909110C`. **State 34 → `0x090923C8`.** The common tail `0x0909161E`/`0x090918C6` advances the index, then the state, and returns 1 after a script is started. It returns early only in Safari (`gBattleTypeFlags & 0x80`). | disasm `90910b4`, `909161e`, `90918c6` | PROVEN |
| 1.5 | **State 34, the Perish case** (`0x090923C8..0x0909243C`), for battler `b = gBattlerByTurnOrder[idx]`: (a) `gStatuses3[b] & 0x20`, else skip; (b) `gBattleMons[b].hp` (`+0x28`, stride `0x58`) `!= 0`, else skip. This hp test is CFRU's addition; FR tests `gAbsentBattlerFlags` instead. (c) It writes `gBattleTextBuff1 = {FD 01 01 01 timer FF}`. (d) The timer is the low nibble of the byte at `gDisableStructs + 0x1C*b + 8 + 7`. (e) **timer == 0**: `gStatuses3[b] &= ~0x20`, `gBattleMoveDamage = hp`, `gBattlescriptCurrInstr = 0x081D8D33`, `BattleScriptExecute`. (f) Otherwise the timer is decremented with the high nibble kept, and CountGoesDown runs. There is **no** ability, item, Dynamax, Z or mega test. | halfword pins `0x090923C8..0x0909243A` | PROVEN |
| 1.6 | `BattleScript_PerishSongTakesLife` at `0x081D8D33` is byte-identical to FR in both artifacts: `printstring 0x97; waitmessage 0x40; orword gHitMarker, 0x00100100; healthbarupdate; datahpupdate; tryfaintmon BS_ATTACKER; end2`. | 27-byte compare | PROVEN |
| 1.7 | RR runs scripts through its replacement opcode table, `0x0903EF20` (`LDR@0x08015C7E`). `printstring`, `orword` and `end2` are FR (`0x0801FD51`, `0x08022B1D`, `0x08022CED`). `waitmessage`, `healthbarupdate`, `datahpupdate` and `tryfaintmon` are CFRU (`0x0909E329`, `0x0909D5E1`, `0x0909D7BD`, `0x0909E5BD`). | table words | PROVEN |
| 1.8 | **CFRU `datahpupdate` on the Perish damage.** Substitute is skipped when `gHitMarker & 0x100` (`lsls #0x17` at `0x0909D816`), and the script sets that bit. The damage path zeroes HP when damage ≥ hp (`strh r3,[r2,#0x28]` at `0x0909DC10`). The tail then emits `SetMonData(HP)` and marks the battler, so the party HP follows. | disasm `909d7bc:0x1c0`, `909db34`, `909dbe8` | PROVEN (HP store) / INFERRED (the emit is reached on this path through the shared tail `0x0909DA86`) |
| 1.9 | **CFRU `tryfaintmon`** (`0x0909E5BC`): for `hp == 0` and not absent, it sets `HITMARKER_FAINTED(b)`, pushes, and jumps to CFRU's faint script `0x090031A0` (`LDR@0x0909E644`). That script begins `playfaintcry; pause 0x10; dofaintanimation; printstring 0x1C ("fainted!"); cleareffectsonfaint`. On the player side it sets `HITMARKER_PLAYER_FAINTED` (`0x400000`, `0x0909E6DA/DE`), increments `playerFaintCounter` unless it is `0xFF` (`0x0909E8C2`), and calls `AdjustFriendshipOnBattleFaint` (`LDR@0x0909E6F0`). | disasm `909e5bc:0x1c0`, script bytes | PROVEN |
| 1.10 | That faint fires SLink's RR faint site. RR's witness is CFRU `cleareffectsonfaint` completion (`0x0909EED2`, `data/games/gen3_rr/engine_signals.json:128`), and the faint script runs `cleareffectsonfaint` (1.9). Echo suppression (`mark_commanded`) therefore works as on FR/LG. | engine_signals + 1.9 | PROVEN (repo) / INFERRED (fires for this faint) |
| 1.11 | Afterwards, `HandleFaintedMonActions` (CFRU-detoured, `0x09093045`) handles the send-out, the "Use next POKéMON?" prompt, and the whiteout. It is the same path every RR faint takes; it was not traced here. | — | INFERRED |

**Answer to Q1:** replaced, and equivalent. Counter 0 KOs through a battle script that prints, and the mon
faints natively. Two small differences from FR follow:
- CFRU skips a battler with 0 HP (harmless: ours has HP).
- The message pause is `0x10` rather than `0x40`.

---

## 2. RR addresses, layouts and constants

| Item | RR value | Proof from bytes | Same as FR/LG? | Already carried? |
|---|---|---|---|---|
| `gStatuses3` | `0x02023DFC` (u32 × 4) | `LDR@0x090923CA` in state 34, indexed `b<<2` (`0x090923CC`) | yes | **no**: add `ram.STATUS3_ADDR` |
| `STATUS3_PERISH_SONG` | `0x20` | `movs r7,#0x20; tst r1,r7` (`0x090923C8`, `0x090923D2`) | yes | **no**: add `derived.STATUS3_PERISH_SONG` |
| `gDisableStructs` | `0x02023E0C` | `LDR@0x09092402` | yes | **no**: add `ram.DISABLE_STRUCTS_ADDR` |
| `sizeof(DisableStruct)` | `0x1C` | `subs r3,#0xfc` (r3 = 1), `adds r3,#0x1b`, `muls r3,r6` (`0x090923F4..FE`). The same stride appears in `datahpupdate` (`movs r1,#0x1c`, `0x0909D804`). | yes (CFRU did **not** extend it) | **no**: add `derived.DISABLE_STRUCT_SIZE` |
| `perishSongTimer` | byte `+0x0F`, low nibble | `adds r2,#8; ldrb r3,[r2,#7]; lsls #0x1c; lsrs #0x1c` (`0x09092406..0C`). The decrement keeps the high nibble (`0x0909242A..36`). | yes | **no**: add `derived.DISABLE_STRUCT_PERISH_TIMER_OFF` |
| `gChosenActionByBattler` | `0x02023D7C` | `LDR@0x0801412E` in HTAS case 0's absent path (FR bytes, live after the CFRU gate returns to `0x08014114`), which stores `#0xd` (`0x08014132`) | yes | yes: `ram.CHOSEN_ACTION_ADDR` (it had old-client provenance; now byte-proven) |
| `B_ACTION_NOTHING_FAINTED` | `13` | (i) that absent-path store; (ii) CFRU `RunTurnActionsFunctions` (`0x0906F52C`) calls `sTurnActionsFuncsTable[gCurrentActionFuncId]` (`LDR@0x0906F964` = FR table, FR-identical); (iii) entry 13 is `0x08016D3D` `HandleAction_NothingIsFainted` (FR-identical) | yes | **no**: add `derived.B_ACTION_NOTHING_FAINTED` |
| `gBattleCommunication` | `0x02023E82` | `rr_battle_tuple` §1 a; the absent path's `LDR` at `0x08014142` | yes | yes: `ram.BATTLE_COMM_ADDR` |
| `gBattleMons` hp | `0x02023BE4 + 0x58*b + 0x28` | `LDR@0x090923E0`, `ldrh [r3,#0x28]` (`0x090923E4`) | yes | yes: `ram.BATTLE_MONS_ADDR` |
| `gBattlerControllerFuncs` | `0x03004FE0` (u32 × 4) | the pool of FR-identical `HandleChooseActionAfterDma3` (`LDR@0x08032BAC`) | yes | yes: the `battle_input_controller` clause of the write checkpoint |
| **Hand-off value** `PlayerBufferExecCompleted` | `0x0802E33D` | `LDR@0x090A9EFE`: the call CFRU's action menu makes on every commit | yes (FR and LG `.sym`: `0x0802E33C`) | **no**: new `battle.handoff` block (§5.1) |
| `gBattleControllerExecFlags` | `0x02023BC8` | `rr_battle_tuple` §1 f | yes | yes: `ram.BATTLE_CONTROLLER_EXEC_FLAGS_ADDR` |

**Carried today.**
- The old RR client (`lua/clients/gen3_frlge_client.lua:2397-2403`, `lua/memory_gba.lua:1317-1329`) carries
  only chosen-action, chosen-move and comm, for Explode. It has no Perish or controller fields. **PROVEN**
  (grep).
- The RR profile (`data/games/gen3_rr/profile.json`) has `BATTLE_COMM_ADDR`, `CHOSEN_ACTION_ADDR`,
  `CHOSEN_MOVE_ADDR`, `BATTLE_MONS_ADDR`, `BATTLE_RESULTS_ADDR` and `BATTLE_CONTROLLER_EXEC_FLAGS_ADDR`.
  **PROVEN.**

**Consequence (INFERRED).** Adding the six P fields makes `active_faint_capable` true on RR
(`lua/gen3/client.lua:552`). On its own that is safe, because `battle_commit` is still refused by the hold.
The entry then keeps today's behaviour, holding with the hold's reason.

---

## 3. The L-throw blocker and the controller hand-off

### 3.1 What the parked CFRU menu does with each key (PROVEN, `rr_save_callers --disasm 90a9e40:0x340`)

The CFRU body (`0x090A9EA0`) bounces the battler every frame and reads `gMain.newKeys` (`+0x2E`). It tests
exactly the bits for A, B, Right, Left, Up, Down, R and L. It does **not** test START or SELECT.

| Key | Path | Side effect before `PlayerBufferExecCompleted` |
|---|---|---|
| A | `PlaySE(5)`, then a `case_uqi` switch on the cursor → `EmitTwoReturnValues(1, action)` → ExecCompleted | BAG/POKéMON/RUN also zero two per-battler gimmick-toggle bytes, `gNewBS+0x174+b` and `+0x188+b` (FIGHT does not) |
| R (`0x090AA0D6`) | `PlaySE`, then emit action 3 (run) → ExecCompleted | as RUN |
| B | doubles right flank only: cancel-partner (`0xC`) | none |
| D-pad | cursor destroy/create, `gActionSelectionCursor[b] ^= 1/2` | none |
| **L**, when `0x0906A454() == 0` | if party and storage are not full: `PlaySE`, the ball id → `0x0203AD30`, **`RemoveBagItem(ball, 1)`** (`LDR@0x090AA114`), a `gNewBS+0xEB` bit, then emit action 1 → ExecCompleted | **destroys a ball** |
| L, otherwise | CFRU sub-UI: the controller becomes `0x090A9E41` and the exec bit stays set. On close it returns to `0x090A9EA1`. | none |

If `battle_commit` leaves this body in place, a later A/R/B press is discarded harmlessly: `comm = 3` makes
the engine ignore buffer B. An L press loses a ball and throws nothing. That is why the hold exists.

### 3.2 The hand-off: `gBattlerControllerFuncs[0] = PlayerBufferExecCompleted` (`0x0802E33D`)

**What the engine does with it.**

1. **Frame N+1.** `BattleMainCB1` (FR-identical) calls `gBattleMainFunc` first. HTAS case 3 (FR-identical,
   `0x08014AA0..0x08014B44`) sees battler 0's exec bit still set and waits. Then, for `gActiveBattler = 0`,
   `BattleMainCB1` calls `gBattlerControllerFuncs[0]`, which is now `PlayerBufferExecCompleted`.
2. **What that call does.**
   - `0x0802E33C` loads the slot address from `gActiveBattler` alone.
   - It detours to `0x0904459A`. The detour stores `PlayerBufferRunCommand` (`0x0802E3B5`), or `0x090ACD8D` in
     CFRU's bit-24 mode; this is the same choice a real commit makes.
   - It returns to the FR tail: a non-link battle takes `gBattleControllerExecFlags &= ~gBitTable[0]`
     (`0x0802E390`).
   - The hook uses only `r0`/`r4`, which the FR prefix set, so it is valid as a one-shot controller.
   - **PROVEN** (disasm `802e33c:0x78`, `904459a:0x28`).
3. **Frame N+2.** HTAS case 3 emits `LINK_STANDBY_MSG` (stop-bounce), marks battler 0, and moves to comm 4.
   `PlayerBufferRunCommand` (FR-identical) dispatches `sPlayerBufferCommands[0x35]` =
   `PlayerHandleLinkStandbyMsg` (FR-identical). That handler calls `EndBounceEffect` ×2 (FR-identical), then
   ExecCompleted. This is the engine's post-commit sequence, byte for byte. **PROVEN.**
4. **The turn.** Our slot runs action 13, which is a silent no-op. The foe acts. End-of-turn state 34 KOs us
   (§1). **PROVEN** (dispatch) / **INFERRED** (CFRU's turn-order sort accepts 13; the engine's own absent
   path feeds it 13 in every doubles faint).

**What it skips relative to a real press.**
- It skips `PlaySE(5)`, so the hand-off is silent.
- On a non-FIGHT pick it also skips the two gimmick-byte clears. §4 row 6 covers why those do not matter.

**Cleanup CFRU does on its own.** CFRU's menu-side sprite callbacks `0x09068D54`/`0x09069818` slide their
icons out as soon as the slot stops being `0x0802E439`/`0x090A9EA1`, and call their teardown once fully out.
That is the same cleanup a real commit gets. **PROVEN** (compare and slide code) / **INFERRED** (the icons are
CFRU's action-menu indicators).

**Why `ExecCompleted` rather than `RunCommand` plus an exec clear (INFERRED, from 3.2 and 3.5).**
- It is one write instead of two.
- The engine clears its own bit, in context, with `gActiveBattler` set.
- It honours CFRU's bit-24 alternative controller.
- In the lag case of §3.5 it degrades to "press to continue" instead of a lost standby message.

**Plan order (PROVEN reasoning).** The hand-off must come **after** `comm = 3`. With `comm = 1`, the exec bit
cleared by ExecCompleted lets HTAS case 1 (`0x080141DC..0x08014218`) read `gBattleBufferB[0][1]`, which is
stale, as this turn's action. The previous turn's action would replay.

The plan is:

| # | Address | Width | Value |
|---|---|---|---|
| 1 | `0x02023DFC` | 4 | current \| `0x20` |
| 2 | `0x02023E0C + 0x0F` | 1 | current & `0xF0` |
| 3 | `0x02023D7C` | 1 | `13` |
| 4 | `0x02023E82` | 1 | `3` |
| 5 | `0x03004FE0` | 4 | `0x0802E33D`, **last** |

Keeping the high nibble in row 2 differs from FR's plain `0` write. It avoids asserting CFRU semantics for
bits the Perish code preserves (§1.5 f).

### 3.3 Can the Lua client do it with plain writes? Yes, but `writes.lua` needs one opt-in API

- **Atomicity.** BizHawk runs the Lua callback between two emulated instructions. No game code runs between
  the five writes, so the plan is atomic with respect to the game. **INFERRED** (the same premise every Gen 3
  permit rests on).
- **The obstacle is SLink's own sink.**
  - `writes:write_bytes` re-runs `safety:check` on **live** RAM before every write (`lua/gen3/writes.lua:40`;
    `value_of` reads memory, `lua/gen3/safety.lua:164-170`).
  - Writing `comm = 3` fails `battle_comm_0` and the commit guard. Writing the slot fails
    `battle_input_controller`.
  - Only one write can be last, so the five-entry plan is refused at entry 5 after entry 4 has landed. That is
    a PARTIAL commit with the hold's hazard.
  - The FR/LG P plan works only because it has exactly one self-invalidating write (F4,
    `tests/unit/test_gen3_client.py:611`). **PROVEN** (source).
- **Minimum fix: `writes:write_plan(entries)`.** It keeps the same frame check, the allow check for every
  entry, and **one** `safety:check` immediately before the first byte. It then writes every byte with no reads
  in between. This keeps the sink's invariant ("no reads/callbacks between the final revalidation and the
  first write"). `armed_write` uses it only when the plan ends in the hand-off. Every other caller, FR/LG's P
  and F4 included, keeps per-write revalidation. **INFERRED** design; about 15 lines.
- **Rejected: a second same-frame permit reason** (`battle_handoff`). It keeps the sink unchanged but needs a
  second clause set, and it leaves a partial state (comm 3 with the menu live) whenever the second write
  fails.
- **Rejected: routing the choice through buffer B instead of `comm`.** That would mean
  `gBattleBufferB[0][1] = 13` plus the hand-off, which has only one invalidating write. But action 13 would
  then flow through CFRU's case-1 default tail (`0x080146AC` → `0x09042EED` → `0x090903CC`) and CFRU's case 2
  (`0x080148C0` → `0x090441E9`), neither traced. **OPEN, not recommended.**

### 3.4 Proof that no L/R press can reach `RemoveBagItem` after the hand-off

1. **Keys reach the throw only through CFRU's action-menu body.** Battle-time input reaches
   `RemoveBagItem`'s L path only inside the CFRU body, via `0x090AA114`. That body runs only while a battler's
   slot is `0x0802E439` (detoured into it) or `0x090A9EA1`. **PROVEN** (§3.1; `rr_battle_tuple` §1 d).
2. **Literal census of every producer** (`rr_active_faint.py` `PTR_CENSUS`, both artifacts, excluding the
   companion's own FORCE_MOVE gate at `0x0837xxxx`). **PROVEN.**
   - `0x0802E439` is stored only by `HandleChooseActionAfterDma3` (`LDR@0x08032BB6`). The two other sites are
     compares.
   - `0x090A9EA1` is stored only by the sub-UI (`LDR@0x090A9E76`), which runs only while the slot is
     `0x090A9E41`. That value is stored only at `LDR@0x090AA16E`, inside the body itself. The other sites are
     the detour, a pool word and compares.
   - `0x08032B95` (AfterDma3) is stored only by CFRU's `PlayerHandleChooseAction` (`LDR@0x090AB096`). The FR
     body's site `0x08032BE0` is dead behind the `0x08032BD4` detour.
3. **`PlayerHandleChooseAction` runs only on a new menu.** It runs only when `PlayerBufferRunCommand`
   dispatches `CHOOSE_ACTION` (`sPlayerBufferCommands[18]`), which HTAS emits only in case 0
   (`BL@0x080141CC`), i.e. at the **next** turn's legitimate menu. **PROVEN.**
4. **The other `RemoveBagItem` callers are out of reach.** Its battle-bag callers (CFRU ball use
   `0x09042CD8`; the bag and party-menu item callbacks) need `CHOOSE_ITEM`. HTAS emits that only from case 1
   on action BAG, which `comm = 3` never reaches (case 3 and case 4 are FR-identical). The rest of the census
   (`0x0909xxxx`/`0x090B3-6xxx`, the FR overworld and shop tasks) are not battle controllers. **PROVEN**
   (census) / **INFERRED** (classification of the CFRU `0x090B` functions).
5. **Residual: runtime-computed pointers.** A store of a pointer computed at run time, such as a saved copy of
   a controller slot being restored, is invisible to a literal census. None is known, but that is **INFERRED**
   (the same limit as `rr_save_callers`).

### 3.5 The lag-frame window (a limit, same class as the FR/LG decision)

If a frame ends *inside* the CFRU body, the seven clauses still read parked and the plan is admitted
(`battle_lag_frame_census_design_2026-09-23.md` §1). "Inside" means after its key read (`0x090A9EBE`) and
before the slot store in the ExecCompleted hook (`0x090445BA`). The CPU then resumes the half-finished press:

| Key held on that frame | Outcome | Tag |
|---|---|---|
| none / D-pad / B | the body returns; next frame the hand-off runs | INFERRED |
| A / R | the body finishes the commit: its emit is ignored (comm 3), and its ExecCompleted duplicates ours | INFERRED |
| **L (throw)** | `RemoveBagItem` has already run, and the throw is discarded: **one ball is lost** | INFERRED |
| L (sub-UI) | the body overwrites our slot with `0x090A9E41` and the exec bit stays set. This degrades to FR/LG's "press to continue": the window closes, the player presses, and the turn runs. An L-throw then loses a ball. | INFERRED |

The size is about 1e-4 to 1e-3 per commit (the lag doc's estimate), multiplied by the chance that L was newly
pressed on that exact frame. Without the hand-off (today's design with the hold lifted), the same L outcome
exists for the whole wait, not just one frame.

The upgrades are, in cost order:
- (a) a `battle` `cpu` clause scoped to `battle_commit`, which is option B/C of the lag doc and needs the
  parked-phase census;
- (b) the companion opcode, §5.6.

---

## 4. Abilities and CFRU mechanics that could stop the KO

| # | Mechanism | Effect on P | Tag |
|---|---|---|---|
| 1 | Soundproof, Damp, and any ability or item | State 34 has no ability or item read (§1.5). A direct flag write bypasses the move entirely. | PROVEN |
| 2 | Substitute | Skipped: the script sets `IGNORE_SUBSTITUTE`, and `datahpupdate` tests it (`0x0909D816`) | PROVEN |
| 3 | Disguise (ability `0x9F`, species `0x3E3`) and Ice Face (ability `0xFA`, species `0x48F`) | `datahpupdate` skips both whenever `gHitMarker & 0x00100100` (the script sets both bits) **and** `gNewBS+0xEB` bit 1 is clear (`0x0909D8BE..D0`, `0x0909D9D2..E4`). Our linked Mimikyu or Eiscue dies normally. If that CFRU bit is set, the form absorbs the hit (1/8 max HP), the flag has already been cleared (1.5 e), and the mon lives. The client's `active_faint_step` then re-commits at the next parked menu, and the busted form takes the second KO. | PROVEN (branches) / **OPEN** (what bit 1 of `+0xEB` means and who writes it) / INFERRED (self-healing) |
| 4 | Endure, Focus Sash, Sturdy | `datahpupdate` has no such test on this path, and the damage path zeroes HP at `damage ≥ hp` (`0x0909DC08-10`) | PROVEN (the path read) |
| 5 | The RR-only scaler `0x0908E0A8` | Scales damage (`0x090C1850`) only for the battler at position 1 (the foe), and swaps the foe's faint script. Battler 0 is untouched. | PROVEN |
| 6 | Mega, Z, Ultra Burst | State 34 has no test. Our slot never emits a move, so CFRU's move-emit (`0x090AA73C`, which carries the toggles `+0x174/+0x188/+0x190/+0x19E`) never happens this turn. A mega toggled in the move menu, then backed out of, leaves the toggle bytes set. Whether the turn-start gimmick loop (`0x0906F550..`) reads them for a non-move action is **OPEN**. The G5 row R5 covers it. | PROVEN (no test) / OPEN |
| 7 | Dynamax / raids | No test in state 34. RR's special-battle gate `0x0908EDD0` changes the A path and `tryfaintmon` for the foe only. | PROVEN (state 34) / INFERRED (RR 4.1 ships no Dynamax) |
| 8 | Battle ends before the end of turn (foe flees, is caught, or KOs itself as its last mon) | Perish never runs. The entry stays held → `battle_write(…, ending=true)` → the overworld path, as on FR/LG | INFERRED (CFRU `BattleTurnPassed` keeps the outcome branch, `rr_battle_tuple` §2) |
| 9 | CFRU pre-faint hooks `0x0909E3A0`/`0x0909E430` | Run for every RR faint before the faint script, e.g. a form reverting. They are native. | INFERRED |
| 10 | Baton Pass / acting | Blocked by the no-op commit plus the hand-off, as on FR/LG | PROVEN (action 13) |

---

## 5. Parity plan

### 5.1 Pack and profile fields

- **`data/games/gen3_rr/profile.json`**, via `tools/gen_gen3_profile.py`'s RR table. Each `_src` cites the
  `rr_active_faint.py` fact.
  - `ram.STATUS3_ADDR` = `33701372`: state 34, `LDR@0x090923CA`.
  - `ram.DISABLE_STRUCTS_ADDR` = `33701388`: `LDR@0x09092402`.
  - `derived.STATUS3_PERISH_SONG` = `32`: `0x090923C8`.
  - `derived.DISABLE_STRUCT_SIZE` = `28`: `0x090923F4..FE`.
  - `derived.DISABLE_STRUCT_PERISH_TIMER_OFF` = `15`: `0x09092406..0C`.
  - `derived.B_ACTION_NOTHING_FAINTED` = `13`: `0x08014132` plus table entry `0x0825006C`.

  `CHOSEN_ACTION_ADDR`'s `_src` is upgraded to `LDR@0x0801412E`.
- **`data/games/gen3_rr/write_checkpoint.json`**, via `tools/gen_gen3_write_checkpoint.py`. Add a new
  `battle.handoff` block:
  ```
  {"symbol": "gBattlerControllerFuncs", "address": 50352096, "stride": 4, "width": 4, "value": 134406973,
   "source": "rom: slot LDR@0x08032BAC (HandleChooseActionAfterDma3, FR-identical); value LDR@0x090A9EFE (the
              PlayerBufferExecCompleted call every CFRU action-menu commit makes)"}
  ```
  The generator derives both words from the ROM pools, like `RR_INPUT_CONTROLLER`. Any byte change drops the
  block, and then the hold stands (fail closed). `commit_hold` **stays** in the pack; it becomes the refusal
  for every plan that does *not* hand off.
- **FR/LG (the owner's call, for exact UX parity).** The same `handoff` block, from `.sym`:
  `PlayerBufferExecCompleted` is `0x0802E33C` in both titles, and FR `HandleInputChooseAction` commits
  through it (pret `battle_controller_player.c:244`). This would make P press-free on all three titles.
  Without it, FR/LG keep the one A press and RR does not need it.

### 5.2 Client change (data-gated; no title name in `client.lua`)

- **`perish_plan(battler)`**: row 2 becomes `current & 0xF0`. When `policy:handoff_entry(battler)` returns an
  entry (from the pack's `handoff`), append it **last**.
- **`armed_write`**: pass `args.plan = plan`. When the plan ends in the hand-off, write through the new
  `writes:write_plan`.
- **`active_faint_step`**: when the hand-off landed, the hold reason is "active faint committed", with no
  press hint. Everything else stays: `mark_commanded`, the `hp == 0` done test, and the re-arm on `comm < 3`
  (which also re-covers §4 row 3).
- **Scope:** `force_faint`, singles, battler 0. Explode is not touched: `commit_plan` gets no hand-off, so it
  stays held on RR.
- **Size:** about 25 lines. The no-title test (`test_the_driver_names_no_bizhawk_global_and_no_title`) stays
  green, because the gate is `active_faint_capable` plus the presence of the pack's `handoff` block.

### 5.3 Lifting `battle_commit_hold` for P only

In `safety.lua` `battle()`, for `reason == "battle_commit"` with `commit_hold` set, the hold clause is
**replaced** by a `battle_commit_handoff` clause. That clause passes only when all of these hold:
- the pack's `handoff` block is well formed;
- `args.plan`'s **last** entry is exactly `{handoff.address + handoff.stride*battler, 4, handoff.value}`;
- no earlier entry touches that slot;
- the entry just before it is the commit guard's `comm` write.

Otherwise it keeps refusing with the hold's text. The policy therefore enforces the rule from the plan itself
instead of trusting a flag. `commit_plan` (Explode) has no such tail and stays refused, which is what "lift
the hold just for P" means. It is about 20 lines. FR/LG packs without `handoff` are byte-identical in
behaviour.

### 5.4 Tests (units, lupa; about 150-200 lines)

1. **Profile and pack.**
   - The RR profile has the six fields, with `_src` citing the ROM sites.
   - `rr_active_faint.py` facts pass.
   - The generator derives `handoff` from the two pools.
   - A mutation test flips one byte of the `0x090A9EFE` pool word (in a ROM copy), which drops `handoff`.
     `battle_commit` on RR then still refuses with `battle_commit_hold`.
2. **Safety (RR pack, fake RAM parked tuple).**
   - A P plan with the hand-off tail → admitted.
   - The same plan without the tail → `battle_commit_hold`.
   - A tail with the wrong value, wrong slot, or wrong battler → refused.
   - The hand-off before `comm` → refused (the ordering rule of §3.2).
   - Explode's `commit_plan` → `battle_commit_hold`.
   - The FR/LG pack is unchanged.
3. **Sink.**
   - `write_plan` validates once and writes all five entries, although entries 4 and 5 invalidate the tuple.
   - A frame change → nothing written.
   - An entry outside allow → nothing written (checked before the first byte).
   - `write_bytes`' per-write revalidation is unchanged; FR's F4 stays green.
4. **Client (RR pack).**
   - The plan has 5 entries, with values and order as in §3.2, and no HP address.
   - Row 2 keeps the high nibble.
   - Doubles and battler 2 → hold.
   - `MULTIPLETURNS` → hold.
   - The echo is suppressed.
   - Hold text has no "press A".
   - `test_protocol_conformance` item 34: RR becomes P.
5. **Falsifiers made red first** on today's tree: RR `force_faint` active → hold (today) must flip to commit;
   `write_plan` absent → the 5-entry plan PARTIALs at entry 5.

### 5.5 Live G5 rows (RR; both artifacts)

**Blocker.** `tests/fixtures/gen3/rr_battle{,_b}.sav` do not exist (`lua/tests/duo/scenario_gen3_explode.lua:19-20`;
the fixture directory has only `rr_town*`). Build them first with `mkstates` kind `battle`, which needs tall
grass.

| Row | Scenario | Oracles (engine reads, never the client's RESULT) |
|---|---|---|
| R1 | `linked_faint_active_gen3` on RR companion, A→B | `playerFaintCounter` (`0x03004F90`+0) +1. The RR faint site (`0x0909EED2`) with `gActiveBattler == 0` and the slot's key. `gStatuses3[0] & 0x20` set after the commit, cleared by the KO. **No input** from commit to KO: slot `0x0802E33D` → `0x0802E3B5` within 2 frames, exec bit 0 clear. The PP of all four moves is unchanged (the mon did not act; `lastUsedMovePlayer` `+0x22` is unverified on RR). B sends no `faint` |
| R2 | R1 on RR clean | same (the Lua path needs no companion) |
| R3 | L hammer: B pulses L every frame from the commit to the Perish message | ball pocket (`ram.BALL_POCKET_ADDR`) and `0x0203AD30` unchanged; the KO still lands |
| R4 | one-mon party | whiteout: outcome LOST and the client's `whiteout` TX |
| R5 | trainer battle, with mega toggled in the move menu and then backed out, before the command | forced party screen; no mega evolution message (closes §4 row 6) |

Optional falsifier: R3 with the hand-off tail stripped under a test-only waived hold loses a ball. It proves
the R3 probe (`feedback_verify_the_probe_first`). Per the owner's "standing gates only", it is optional.

### 5.6 The alternative: a companion opcode (not recommended as the primary)

A new mailbox opcode would reuse `drive_force_move`'s gate (`patch/src/handlers.c:638-660`: comm 1, slot
`0x0802E439`/`0x090A9EA1`, not link). A routine swapped into the slot would write the four P words, set
`comm = 3`, clear the exec mask, and call `PlayerBufferExecCompleted`, in context, from `slink_hook` in
`CallCallbacks` before `BattleMainCB1` (`patch/src/ADDRESSES.md:21-29`).

**Advantages (INFERRED):**
- No lag-frame window, because the gate reads the slot on the game thread.
- It also admits the post-L-window spelling `0x090A9EA1`, which the Lua permit refuses.

**Costs:**
- About 40 lines of C plus a `test_patch_*` falsifier.
- A **rebuild, a UPS regen, and a re-pin** of the companion sha1/md5 in `server/patcher.py` and three RR pack
  JSONs. The C5-FMS-FIX rebuild is already pending, so this could share it.
- **RR clean keeps the hold**, which breaks parity on that artifact.

Choose it only if the owner rejects the §3.5 limit.

### 5.7 Cost and recommendation

| Part | Size |
|---|---|
| profile + generator + checkpoint `handoff` | ~40 lines + regen |
| `writes.lua` `write_plan` | ~15 |
| `safety.lua` hand-off clause | ~20 |
| `client.lua` | ~25 |
| units (§5.4) | ~150-200 |
| duo scenario + `tools/e2e_duo.py` markers for R1-R5 | ~60-80 |
| **total** | **~250-350 lines**, one lane |
| fixtures `rr_battle{,_b}.sav` | 1 lane, a prerequisite (not yet built) |
| live | R1-R5 = 5 launches (+1 optional falsifier) |

**Recommendation: mechanism P+H on RR** (P plus the in-plan `PlayerBufferExecCompleted` hand-off). It is
data-gated, needs no companion rebuild, lifts the hold only for hand-off plans, and records the §3.5 lag
window as a limit. **Adding the same `handoff` block to FR/LG** would make all three titles behave the same,
with no A press; that is the owner's call. Explode on RR stays held; it is a one-line follow-up
(`commit_plan` gains the tail) with its own G5 row.

---

## 6. Open

1. What bit 1 of CFRU `gNewBS+0xEB` means (§4 row 3). It only matters for a linked Mimikyu or Eiscue, and the
   case is self-healing.
2. Whether the turn-start gimmick loop reads stale mega/Z toggles for a non-move action (§4 row 6). G5 R5
   covers it.
3. Whether CFRU's detoured turn-order sort and `HandleFaintedMonActions` behave as FR for action 13 and for
   this faint. INFERRED from the engine's own absent path and from every RR faint.
4. The classification of the `0x090B3xxx-0x090B6xxx` `RemoveBagItem` callers (§3.4 step 4), and any
   runtime-computed controller-pointer store (§3.4 step 5).
5. Whether a frame ending inside the CFRU body is ever observed at the parked menu (§3.5). The lag doc's
   census, run for the parked phase, would size it.

## Reproduce

```
python tools/research/rr_active_faint.py --selftest
python tools/research/rr_active_faint.py                                    # 58 facts x {clean, companion}
python tools/research/rr_save_callers.py --rom clean --disasm 90923c8:0x74  # CFRU end-turn state 34 (Perish)
python tools/research/rr_save_callers.py --rom clean --disasm 90910b4:0x60  # end-turn dispatcher
python tools/research/rr_save_callers.py --rom clean --disasm 909d7bc:0x1c0 # CFRU datahpupdate
python tools/research/rr_save_callers.py --rom clean --disasm 909e5bc:0x1c0 # CFRU tryfaintmon
python tools/research/rr_save_callers.py --rom clean --disasm 90a9e40:0x340 # CFRU action menu + sub-UI
python tools/research/rr_save_callers.py --rom clean --disasm 802e33c:0x78  # PlayerBufferExecCompleted
python tools/research/rr_save_callers.py --rom clean --disasm 8014114:0x60  # HTAS absent path (action 13)
```
