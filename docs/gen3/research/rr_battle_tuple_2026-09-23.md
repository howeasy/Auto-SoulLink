# RR in-battle write permit at the parked action menu, 2026-09-23 (card C5-RR-BW)

This is a static, bytes-only research card for the Gen 3 G5 gate. No emulator was run. It closes item (2)
of `rr_save_callers_2026-09-23.md` §4 and finding 2 of `checkpoint_predicate_audit_2026-09-23.md`
("RR's parked battle tuple needs its own proof").

**Inputs**
- ROMs: RR clean `964f951a`, RR companion `b7d1e075`, FR `41cb23d8` (vanilla control). These are the same pins
  as `tools/gen_gen3_write_checkpoint.py` and `tools/research/rr_save_callers.py`.
- Symbols: pret/pokefirered `c75f3523` (`data/gen3/pret/pokefirered.sym`). They are used only to name functions
  whose RR bodies are byte-identical to FR.
- SLink HEAD: `dd42cde6`.
- Checkpoint under test: `data/games/gen3_rr/write_checkpoint.json` `radical_red.battle`, evaluated by
  `lua/gen3/safety.lua` `battle()` (`:198-214`, `clause_entries` `:181-195`).

**Tool:** `tools/research/rr_battle_tuple.py` (new). It reuses the ROM pins, `.sym` parser and Thumb BL/LDR
decoder from `rr_save_callers.py`. It asserts 41 byte facts on each RR artifact, and all 82 pass. It also has a
`--selftest` with known-positive and known-negative FR controls. Every listing cited below can be reproduced with
`rr_save_callers.py --disasm`.

Tags: **PROVEN** means read from the bytes, or from pret for a function whose RR body is byte-identical to FR.
**INFERRED** means reasoned, not read. **OPEN** means not settled.

## Verdict: UNSAFE (with a liveness failure as well)

RR's player controller is CFRU's, but it follows the vanilla exec-flag protocol exactly:
- Battler 0's exec bit is set when the engine emits `CHOOSE_ACTION`, and it stays set for the whole input wait.
- CFRU's input handler clears the bit only by calling `PlayerBufferExecCompleted`, inside the same controller call
  that writes the choice to `gBattleBufferB`.

So at the parked menu `gBattleControllerExecFlags == 1`, exactly as C4-BW found on FR/LG. The RR clause
`battle_exec_flags_idle == 0` therefore has two problems:
- **Liveness failure:** it refuses every parked-menu frame.
- **Unsafe:** it admits the one frame after each committed choice. That frame ends with the main function still on
  `HandleTurnActionSelectionState`, `gBattleCommunication[0]` still at 1, the exec word at 0, and the choice
  waiting in `gBattleBufferB`. This is the frame `battle_write_predicate.md` §2.3 classes as unsafe.

On RR there is also a concrete consequence. The L-button "last used ball" shortcut calls `RemoveBagItem` inside that
same commit call (`0x090AA114`). A `battle_commit` write that frame overrides a throw whose ball has already been
consumed.

The fix is the FR/LG shape: `battle_exec_flags_input == 1` plus a battler-0 controller pin (§5).

## 1. Battler 0's exec bit across one action choice (PROVEN)

Frame order: `BattleMainCB1` (FR-identical in both artifacts) calls `gBattleMainFunc` first and then every
`gBattlerControllerFuncs[i]`, in the same frame (pret `battle_main.c:2203-2209`).

| Step | Code | Effect on battler 0 |
|---|---|---|
| a. Engine, `gBattleCommunication[0] == 0` | HTAS jump table `0x0801409C`: [0] = `0x080140B8`, [1] = `0x080141DC`. Case 0 goes through the CFRU gate `0x080140C8`→`0x09042BBD`→(`0x09068738`)→`0x08014114`. It emits `BL@0x080141CC` `BtlController_EmitChooseAction`, then `BL@0x080141D0` to the shared tail `0x08014B26`: `MarkBattlerForControllerExec(b)` and `gBattleCommunication[b]++`. The tail is byte-identical to FR. | exec bit 0 set; comm 0 → **1** |
| b. Controller, same frame | `PlayerBufferRunCommand` (FR-identical) sees the bit and dispatches `sPlayerBufferCommands[18]` = `0x08032BD5`. That entry is detoured (`ldr/bx`) to CFRU `0x090AAF38`. In singles it stores `HandleChooseActionAfterDma3` (`LDR@0x090AB096` = `0x08032B95`), draws the menu, and returns. | bit still set |
| c. Draw frames | `HandleChooseActionAfterDma3` (FR-identical) waits for DMA idle, then stores `LDR@0x08032BB6` = **`0x0802E439`** into `gBattlerControllerFuncs[b]`. | bit still set |
| d. **Parked** | `0x0802E438` is detoured to the CFRU body **`0x090A9EA0`**. Each frame the body bounces the battler sprites and reads `gMain.newKeys` (`0x030030F0+0x2E`). If nothing commits, it returns (`pop` at `0x090AA068`). The body contains **no** load of `&gBattleControllerExecFlags`: the only clear is through `PlayerBufferExecCompleted`, which the body loads at `0x090A9EFE`. | **flags bit 0 = 1**, comm = 1 |
| e. **Commit** (A, R, L-throw) | A: `bl 0x090003C4` (a `case_uqi` switch on `gActionSelectionCursor[b]`) with table bytes `02 05 13 20` → FIGHT `0x090A9F28` (action 0), BAG `0x090A9F2E` (1), POKéMON `0x090A9F4A` (2), RUN `0x090A9F64` (3, or 0xC = cancel-partner for the doubles right flank). Every case goes through `0x090A9F10` `EmitTwoReturnValues(1, action, …)`, then `0x090A9EFE` `PlayerBufferExecCompleted`. R (`0x090AA0D6`) takes the same route with action 3. L with the ball shortcut (`0x090AA0F0-0x090AA13E`) calls `RemoveBagItem`, then emits action 1 and runs ExecCompleted. | choice in `gBattleBufferB[0]` |
| f. `PlayerBufferExecCompleted`, same call | `0x0802E33C` loads `&gBattlerControllerFuncs[b]`, then detours at `0x0802E34A` → `0x0904459A`. The detour stores `PlayerBufferRunCommand` (`LDR@0x090445B6` = `0x0802E3B5`), or `0x090ACD8D` when `gBattleTypeFlags` bit 24 is set (a CFRU mode). It then jumps back to `0x0802E34E` (`LDR@0x090445BC`). If not a link battle, that goes to `0x0802E390`: `gBattleControllerExecFlags &= ~gBitTable[b]` (BICS, byte-identical to FR). | **bit 0 cleared in the same frame as the commit** |
| g. Engine, next frame | The case-1 poll `0x080141DC-0x08014206` (identical to FR) now passes. It reads `gBattleBufferB[b][1]` and emits the next exec (ChooseMove / ChooseItem / ChoosePokemon), then `Mark` and `comm++` → 2. Some actions instead reset comm to 0 (trainer RUN; CFRU `0x090903CC`). | comm 1 → 2 (or 0) |

Between (f) and (g) there is exactly one frame end where `main == HTAS`, `comm[0] == 1` and battler 0's bit is 0.
That is the frame the RR clause admits.

**The CFRU L-button sub-UI.** When `0x0906A454 != 0`, L opens a CFRU window instead of throwing
(`0x090AA140-0x090AA172`). The controller becomes `0x090A9E41` and the exec bit stays set. When that window closes
(keys `0x2F3`), `0x090A9E40` stores **`0x090A9EA1`** directly (`LDR@0x090A9E76`). The CFRU body is then the
controller, with no detour in front of it. This is the same parked state under a second pointer value.

Independent witness: CFRU's own sprite callbacks `0x09068D54` and `0x09069818` compare
`gBattlerControllerFuncs[b]` against both `0x0802E439` and `0x090A9EA1` (`LDR@0x09068D6C/72`, `0x09069832/38`).
So CFRU itself treats both values as "action menu up".

Live corroboration, from before this card: `patch/src/ADDRESSES.md` records a 2026-06-11 probe that read
`gBattlerControllerFuncs[0] == 0x0802E439` at the RR action menu.

**The opponent side** (for the full exec word):
- `OpponentHandleChooseAction` and `OpponentHandleLinkStandbyMsg` are FR-identical and call
  `OpponentBufferExecCompleted` (FR-identical BICS) synchronously. **PROVEN**
- `OpponentHandleChooseMove` is detoured to CFRU `0x09068418`. Its main path ends in `OpponentBufferExecCompleted`
  (`LDR@0x090684F0`), but not every path was traced. **INFERRED**

The steady parked word is therefore `0x00000001`. Any frame that still carries an opponent bit reads 3, which both
clause sets refuse, so that case fails closed.

## 2. Lifecycle hooks and stale state (PROVEN unless noted)

| Hook | Bytes | Effect on the tuple |
|---|---|---|
| `SetUpBattleVars` `0x0800D278` | The FR prefix is kept: `gBattleMainFunc = BeginBattleIntroDummy` (`0x080123BD`), all four controllers = `BattleControllerDummy`, `gBattleControllerExecFlags = 0` (`0x0800D2BE-C2`). Then the detour at `0x0800D2CC` → `0x09042B98` calls CFRU `0x0906E3B0` and `0x090C7988(0xF)`, zeroes `0x02022B54`, and jumps back to the FR tail `0x0800D2D4`. | A new battle starts with main = dummy and exec = 0. No stale HTAS or stale exec word survives into the intro. |
| `BattleStartClearSetData` (RR body differs) | `gBattleOutcome = 0` (`0x08012536-38`), `gBattleControllerExecFlags = 0` (`0x0801253A-3C`). | `battle_outcome_open` reopens only at a real battle start. |
| HTAS stores | The only LDRs of `0x08014041` are: `0x08013A66` (FR `TryDoEventsBeforeFirstTurn` body, dead behind the entry detour `0x0801385C`→`0x0906FF21`), `0x08013CCC` (`BattleTurnPassed`, stored by the tail hook `0x08013D14`→`0x09042D40` `str r0,[sl]`), and CFRU `0x09070628` (the first-turn replacement, which also zeroes `gBattleCommunication[0..4]`). | `battle_main_func` is HTAS only between the turn-start store and HTAS's own hand-off to `SetActionsAndBattlersTurnOrder`. |
| `BattleTurnPassed` `0x08013BD4` | `HandleFaintedMonActions` is `BL@0x08013C04`. The `gBattleOutcome != 0` → `RunTurnActionsFunctions` branch is at `0x08013C60/6E`. Both come before the HTAS store at the tail hook. The 12 NOPped bytes at `0x08013BEC` remove an FR end-turn call. | A forced send-out and a decided battle never run under HTAS. |
| `HandleEndTurn_FinishBattle` | Detour `0x080159DC` → `0x09002734`: calls CFRU `0x09090750`, then `gBattleMainFunc = FreeResetData_ReturnToOvOrDoEvolutions` (`LDR@0x0900273A` = `0x08015A31`). | Battle end leaves HTAS for good. |
| `ReturnFromBattleToOverworld` `0x08015B58` | The two NOPs at `0x08015BB6` only change the roamer `gBattleOutcome` test. The function reads `gBattleOutcome` (`0x08015B88`, `0x08015BB4`), clears `gMain.inBattle` (`0x08015B8E-9C`), restores `callback1` and sets `callback2`. It writes no battle-tuple word. | The first overworld frame keeps a non-HTAS main function and a non-zero outcome. |
| `DoSoftReset` | FR-identical. `SoftReset(RESET_ALL & ~RESET_SIO_REGS)` clears EWRAM and IWRAM (pret `main.c:480-488`). | A reset from a parked menu cannot leave a stale admitted tuple. |

## 3. The other RR clauses

| Clause | Reads | Status |
|---|---|---|
| `battle_main_func == 0x08014041` | `0x03004F84` | Its value and stores are PROVEN (§2). It refuses the animation, send-out, end and overworld phases on its own. |
| `battle_comm_0 == 1` | `0x02023E82` | PROVEN, 1 while parked (§1 a). The array doubles as the scripts' `MULTIUSE_STATE`, so outside HTAS its value is arbitrary (INFERRED). `battle_main_func` covers those frames. |
| `battle_exec_flags_idle == 0` | `0x02023BC8` | **Wrong** (§1): 1 while parked, 0 only on the commit frame. |
| `battle_not_link` | `0x02022B4C & 2` | Holds for every single-player battle (INFERRED; a flag property, not traced). |
| `battle_engine_loaded` | `gBattleMons[0].maxHP` | Loaded at the intro and never cleared at battle end (INFERRED). It does not help refuse the overworld; §2 carries that. |
| `battle_outcome_open` | `0x02023E8A` | Zeroed only at battle start (PROVEN, §2). Non-zero from the deciding action until the next battle (INFERRED; the full set of RR writers was not censused). |
| `commit_guard` (`battle_commit`) | `comm[battler] < 3` | Passes on the commit frame (comm = 1). It does not close the gap. |

## 4. Frame-phase table (wild singles; trainer differences noted)

Columns: **M** main func, **C** `comm[0]`, **F** exec word, **P** `gBattlerControllerFuncs[0]` (not in the current
RR set; shown for the proposed set), then L/H/O. The last two columns give the verdict of the current RR set and of
the proposed set (§5).

| Phase | M | C | F | P | L / H / O | Current RR | Proposed |
|---|---|---|---|---|---|---|---|
| Menu draw (AfterDma3 frames) | HTAS ✓ P | 1 ✓ P | 1 P | `0x08032B95` ✗ P | ✓ I / ✓ I / 0 ✓ P | REFUSE (F) P | REFUSE (P) P |
| **Parked menu** | HTAS ✓ P | 1 ✓ P | **1** P (bit 0), I (bit 1 steady) | `0x0802E439` ✓ P (or `0x090A9EA1` after the L sub-UI, P) | ✓ I / ✓ I / 0 ✓ P | **REFUSE (F): liveness failure** P | **ADMIT** P (with `0x090A9EA1`: admit only if the clause takes both spellings, §5) |
| L sub-UI open | HTAS ✓ P | 1 ✓ P | 1 P | `0x090A9E41` ✗ P | ✓ / ✓ / 0 | REFUSE (F) P | REFUSE (P) P |
| **Frame after A on FIGHT** | HTAS ✓ P | 1 ✓ P | **0** P (bit 0), I (bit 1) | `0x0802E3B5` ✗ P | ✓ / ✓ / 0 | **ADMIT: unsafe** P | REFUSE (F, P) P |
| Move menu and the frame after the move choice | HTAS ✓ P | 2 ✗ P | 1, then 0 P | move controllers ✗ | ✓ / ✓ / 0 | REFUSE (C) P | REFUSE (C, F/P) P |
| **Frame after BAG / POKéMON / RUN / R / L-throw** | HTAS ✓ P | 1 ✓ P | **0** P | `0x0802E3B5` ✗ P | ✓ / ✓ / 0 | **ADMIT: unsafe** P (L-throw: ball already removed, `0x090AA114`) | REFUSE (F, P) P |
| Bag / party UI | HTAS ✓ P | 2 ✗ P (FR tail `comm++`; SWITCH via CFRU `0x090BFDB8` then the FR tail, I) | 1 I | bag/party controllers ✗ I | ✓ / ✓ / 0 | REFUSE (C) P | REFUSE (C, P) |
| Trainer RUN / CFRU forfeit (`0x090903CC`) next frame | script runner ✗ P | 0 P | varies I | varies | ✓ / ✓ / 0 | REFUSE (M, C) P | REFUSE P |
| Move animation / damage scripts | `RunTurnActionsFunctions` or a script runner ✗ P (store census) | varies I | varies I | varies I | ✓ / ✓ / 0 | REFUSE (M) P | REFUSE (M) P |
| Forced send-out (party menu after a faint) | script runner under `BattleTurnPassed` ✗ P (the faint BL `0x08013C04` precedes the HTAS store) | MULTIUSE I | bit 0 while choosing I | party controllers I | ✓ / ✓ / 0 | REFUSE (M) P | REFUSE (M) P |
| Battle end (outcome decided through `FreeResetData`) | not HTAS ✗ P (`0x0900273A`) | varies I | varies I | varies I | ✓ / ✓ / **≠0** ✗ I | REFUSE (M, O) P | REFUSE P |
| First overworld frame | stale `FreeResetData`/`ReturnFromBattleToOverworld`/evo ✗ P (no HTAS store after the end) | stale I | stale I | stale I | ✓ / ✓ stale / ≠0 ✗ I | REFUSE (M) P | REFUSE (M) P |
| Next battle before the first menu | `BeginBattleIntroDummy` then intro phases ✗ P | 0 P | 0 P | dummy ✗ P | – / – / 0 | REFUSE (M) P | REFUSE (M, P) P |
| Doubles: battler 2's menu | HTAS ✓ | 4 ✗ I (pret; RR gate `0x09068738` not traced) | 4 I | `PlayerBufferRunCommand` ✗ I | ✓ / ✓ / 0 | REFUSE (C) | REFUSE (C, F, P) |

P = PROVEN, I = INFERRED. No cell is OPEN for the verdict. Every refusal marked P rests on at least one PROVEN
clause. The unsafe admission rests on PROVEN bytes for battler 0 and on the INFERRED fact that the opponent's bit
is clear at that moment. If the opponent's bit were still set, the frame would be refused, but only by accident.

## 5. Proposed corrected RR clause set

Replace `battle_exec_flags_idle` and add a controller pin. This makes the RR set carry the same seven names as
FR/LG, so `lua/tests/gen3_battle_window_rows.lua` (which needs all seven, `R.ALIASES`) can run on RR unchanged.

| name | address | test | RR provenance (no FR code symbol asserted) |
|---|---|---|---|
| `battle_main_func` | `0x03004F84` | `== 0x08014041` (`eq_rom`) | unchanged |
| `battle_comm_0` | `0x02023E82` | `== 1` | unchanged; PROVEN by §1 a |
| **`battle_exec_flags_input`** | `0x02023BC8` | **`== 1`** | same address and `_src` as today; the value comes from §1 a/d/f |
| **`battle_input_controller`** | `0x03004FE0` (u32) | **`== 0x0802E439`** | Address: the pool of the FR-identical `HandleChooseActionAfterDma3` (`LDR@0x08032BAC`) and `BattleMainCB1` (`LDR@0x080123FC`), which is the generator's existing "data symbol verified by a witness function" rule. Value: the literal the same FR-identical body stores (`LDR@0x08032BB6`). It is **not** `eq_symbol HandleInputChooseAction`, whose RR body differs, so `ok_code` rightly fails. |
| `battle_not_link` | `0x02022B4C` & 2 | `== 0` | unchanged |
| `battle_engine_loaded` | `0x02023BE4+0x2C` | `!= 0` | unchanged |
| `battle_outcome_open` | `0x02023E8A` | `== 0` | unchanged |

**The second spelling.** After a player opens and closes the CFRU L-button window, the parked controller is
`0x090A9EA1` until the next action menu. With the single `eq` above, those frames are refused. That is fail-closed:
a liveness gap only until the next turn's menu.

Admitting them would need a set compare (`in: [0x0802E439, 0x090A9EA1]`). `safety.lua` `clause_entries` supports
only `eq` and `nonzero`, so that is a `safety.lua` change, and it is out of scope here. Recommendation: ship the
single `eq` now and record the gap. The `in` compare is a follow-up only if G5 shows the L window in real play.
If it is added, pin `0x090A9EA1` through `LDR@0x090A9E76` plus the `0x0802E438` detour word.

No `in_battle` clause is needed. `battle_main_func` already refuses every post-battle frame (§2), and adding
`gMain` bits to the battle block would widen the G3-signed predicate surface for no gain.

Not changed here, and noted for the implementation card: `battle_commit` at the parked menu writes `comm = 3`
while battler 0's `CHOOSE_ACTION` exec is still pending. HTAS case 3 polls the exec mask (jump table [3] = `0x08014AA0`, which loads `0x02023BC8` there), so the
coerced action runs only after the player's controller completes. FR/LG after C4-BW behaves the same way. This is a
liveness question for Explode Mode, not a safety question, and it is INFERRED (the case-3 path was not traced
end-to-end).

## 6. Falsifiers the implementation card must make red first

Each of these must fail against today's pack (`battle_exec_flags_idle`) and pass after the fix.

1. **`tests/unit/test_gen3_write_checkpoint.py` `RR_BATTLE_CLAUSES` (`:275`)** must equal the FR/LG tuple of seven
   names. Also assert, for RR:
   - `battle_exec_flags_input.expect == 1`;
   - `battle_input_controller` has `address == 0x03004FE0` and `expect == 0x0802E439`;
   - its source names `LDR@0x08032BB6`.

   Add a mutation test: flipping a byte of the `0x08032BB6` pool word (`0x08032BD0`) in a ROM copy must drop the
   clause, and the generator must list it as unverified (fail-closed).
2. **`tests/unit/test_gen3_safety.py`, RR pack, fake RAM**. Common state: main `0x08014041`, comm0 1, type 0,
   maxHP 50, outcome 0.
   - (a) Parked: exec 1, ctrl0 `0x0802E439` → **admit**. Today this is refused with `battle_exec_flags_idle`.
   - (b) Commit frame: exec 0, ctrl0 `0x0802E3B5` → **refuse**, naming `battle_exec_flags_input` and
     `battle_input_controller`. Today this is admitted.
   - (c) AfterDma3: exec 1, ctrl0 `0x08032B95` → refuse (`battle_input_controller`).
   - (d) L sub-UI open: ctrl0 `0x090A9E41` → refuse.
   - (e) Post-L spelling: ctrl0 `0x090A9EA1` → refuse. This pins the documented gap; flip it if the `in` compare
     lands.
   - (f) Opponent bit pending: exec 3 → refuse.
   - (g) Doubles battler-2 menu: comm0 4, exec 4 → refuse.
   - (h) Bit-24 CFRU mode after commit: ctrl0 `0x090ACD8D`, exec 0 → refuse.
3. **`battle_commit` on the RR pack** with state 2b (the commit frame) and battler 0 → refuse. The commit guard
   alone (comm = 1 < 3) passes today, so the refusal must come from the new clauses.
4. **G5 physical rows, both RR artifacts.** Use `gen3_battle_window_rows.lua` rows with the RR pack. The
   `mkstates_gen3` kind `battle` states are enough. Cover:
   - a parked wild menu, at least 300 frames, all admitted;
   - the A frame on FIGHT, BAG, POKéMON and RUN, each refused;
   - an L-button window round trip, refused throughout, including after return (single-`eq` build);
   - a trainer battle forced send-out;
   - 60 frames after `ReturnFromBattleToOverworld`.

   Also receipt the steady exec word (expect `0x00000001`) to close the INFERRED opponent-bit cells.

## 7. Out-of-scope finding (companion, not this pack)

The companion's `FORCE_MOVE_SLOT` driver (`patch/src/handlers.c:601-633`, default OFF behind
`--native-battle-control`) has two problems:
- It gates on `comm == 2 && ctrl == 0x0802E439`, but the bytes above prove the action menu parks at comm **1**.
  With `0x0802E439` the gate matches no frame in the flow traced in §1 (INFERRED). With `ACTION_CTRL_B` (`0x0802E3B5`) it matches only a post-commit
  comm-2 frame.
- `slink_force_controller` writes comm **4**, which is `STATE_WAIT_ACTION_CONFIRMED` (jump table [4] =
  `0x08014B44`), not standby ([3] = `0x08014AA0`).

`patch/src/ADDRESSES.md:574-575` records a 1-based enum that the case table does not support. This may explain the
2026-06 real-play softlock noted there. It is not part of the write-checkpoint permit and was not changed here.

## Reproduce

```
python tools/research/rr_battle_tuple.py --selftest
python tools/research/rr_battle_tuple.py                                  # 41 facts x {clean, companion}
python tools/research/rr_save_callers.py --rom clean --disasm 90a9ea0:0x2d8   # CFRU HandleInputChooseAction
python tools/research/rr_save_callers.py --rom clean --disasm 90aaf38:0x240   # CFRU PlayerHandleChooseAction
python tools/research/rr_save_callers.py --rom clean --disasm 802e33c:0x78    # ExecCompleted + BICS tail
python tools/research/rr_save_callers.py --rom clean --disasm 904459a:0x28    # its CFRU hook
python tools/research/rr_save_callers.py --rom clean --disasm 8014040:0x1d0   # HTAS case 0 + poll
python tools/research/rr_save_callers.py --rom clean --disasm 800d278:0x94    # SetUpBattleVars
python tools/research/rr_save_callers.py --rom clean --disasm 8015b58:0x80    # ReturnFromBattleToOverworld
```
