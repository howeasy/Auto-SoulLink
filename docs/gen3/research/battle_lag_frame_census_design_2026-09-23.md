# Battle lag-frame census + design: should `battle()` gain a CPU/parked-PC clause?

Card C5-LAGFRAME-DESIGN, 2026-09-23. Static design only: no emulator run, no ROM build, no code or
pack change. Question for the owner: **should the in-battle write permit (`lua/gen3/safety.lua`'s
`battle()`) gain a CPU / parked-PC clause like the overworld's?** Two reviews flagged the same
narrow window (REV-C5-RR-BW-FIX finding 3; the C5-RR-BW-FIX author's note in `a1bbc686`): if a frame
boundary lands inside the controller call that commits a choice — after the choice is written to
`gBattleBufferB`, but before `PlayerBufferExecCompleted` stores the new controller and clears the exec
bit — the seven clauses still read as parked and the write is admitted.

Sources: pret c75f3523 (`E:/Google Drive/SLink/.cache/pret/pokefirered`), the RR bytes through
`tools/research/rr_save_callers.py --rom {fr,clean} --disasm <addr>:<len>` (the decoder
`tools/research/rr_battle_tuple.py` uses), `lua/gen3/safety.lua`, the pack's `cpu` block,
`docs/gen3_write_checkpoint.md` §4.3, the census receipts under `docs/gen3/probes/`, and
`docs/gen3/research/battle_write_predicate.md` §3.

---

## 1. The window, per title, and whether a frame end can fall in it

### 1.1 What the permit reads today

`safety.lua`'s `battle()` (`lua/gen3/safety.lua:204-306`) evaluates the seven battle clauses plus,
for `reason == "battle_commit"`, the commit guard (`< 3`) or the RR `commit_hold`. There is **no CPU
or PC clause** on this path — the `cpu` clause (`lua/gen3/safety.lua:108-114`) is only part of the
overworld predicate. So any frame whose *memory* reads parked is admitted, wherever the PC is.

The parked reading is exactly what the commit sequence briefly still exposes, because the two
writes that make it a commit are separated:

| step | FR/LG | RR (CFRU) |
|---|---|---|
| the choice is fully in `gBattleBufferB` (the controller→engine channel, `0x020233C4`) | returns from `BtlController_EmitTwoReturnValues` — `src/battle_controllers.c`, called at `src/battle_controller_player.c:232/235/238/241` (action), `:342` (move), `:1340` (item), `:1315-1318` (party) | returns from the CFRU emit at `0x090A9F10`/`0x090A9F12` (the doc's `EmitTwoReturnValues(1, action, …)`, `patch/src/ADDRESSES.md`) |
| the exec bit is cleared and the slot handed back | `PlayerBufferExecCompleted()`, `src/battle_controller_player.c:244` (action), `:344` (move), `:1341` (item), `:1321` (party); body `:186-200`, the slot store at `:188` and `gBattleControllerExecFlags &= ~gBitTable[b]` at `:198` | the same function via CFRU's detour: `0x090A9EFE` loads `0x0802E33D`, `0x090A9F00` calls it through CFRU's thunk `0x090ACCDE`; the body detours at `0x0802E34A` → `0x0904459A`, stores `PlayerBufferRunCommand` (`LDR@0x090445B6` = `0x0802E3B5`, or `0x090ACD8D` under `gBattleTypeFlags` bit 24), then clears the bit (`ADDRESSES.md`, "PlayerBufferExecCompleted, same call" row) |

**The admitted sub-window ends at the slot store** (`src/battle_controller_player.c:188` on FR; the
corresponding store inside `0x0904459A` on RR): from that instant `gBattlerControllerFuncs[b]` is
`PlayerBufferRunCommand`, so the `battle_input_controller` clause fails and the frame is refused.
Between the emit's return and that store, all seven clauses still read parked: the buffer holds the
choice, `comm == 1`, `gBattleControllerExecFlags` still has battler 0's bit, and the controller is
still the input handler.

### 1.2 Exact instruction spans (read with the repo's decoder)

* **FR** (`--rom fr`): `HandleInputChooseAction` is `0x0802E438 + 0x206` (`data/gen3/pret/pokefirered.sym`).
  The shortest pair is `0x0802E612: bl 0x0800E848 (BtlController_EmitTwoReturnValues)` → `0x0802E616:
  bl 0x0802E33C (PlayerBufferExecCompleted)`; another case emits at `0x0802E4CA`. The callee
  (`0x0802E33C`): `push {r4,lr}` → `sub sp,#4` → `ldr r1,[pc]` (slot base `0x03004FE0`) → `ldr r4,[pc]`
  → `ldrb r0,[r4]` (gActiveBattler) → `lsls r0,r0,#2` → `adds r0,r0,r1` → `ldr r1,[pc]`
  (`0x0802E3B5`) → **`str r1,[r0]` at `0x0802E34C`** — i.e. **~10 instructions** from the emit's
  return on the short path, plus whatever a longer case's path adds (at most a few dozen; I mapped
  the two emit sites and the callee, not every case's route — **partial**, see §6).
* **RR** (`--rom clean`): `0x090A9F12: bl 0x090ACCDE` (emit) → `0x090A9F16: b 0x090A9EFE` →
  `0x090A9EFE: ldr r3,[pc,#0x290] ; = 0x0802E33D` → `0x090A9F00: bl 0x090ACCDE` (exec-completed) →
  into the detour `0x0904459A`, whose store is the RR equivalent of `0x0802E34C`. Three instructions
  of straight-line code plus the two thunk calls — **the same shape, shorter**.

Both are single-frame transients of a few hundred nanoseconds; nothing in the seven clauses can see
them differently from the parked menu.

### 1.3 Can a frame end fall inside such a window? Yes — the boundary is a PPU event, not a code event

The repo already contains the decisive measurement, for the overworld:
`docs/gen3/probes/census_fr_overworld_2026-09-21.txt`, taken by `lua/tests/probe_gen3_frameend_pc.lua`
(which samples R15/CPSR/tasks on every `event.onframeend`, `:143-206`), over 1800 frame ends:

```
R15=0x080008AC x780   R15=0x080008B0 x244   R15=0x080008B2 x232
R15=0x080008B4 x230   R15=0x080008AE x221   R15=0x0000001C x93
CPSR mode/T=31/1 x1707   CPSR mode/T=18/0 x93
```

Five *different* PCs inside one function (`WaitForVBlank`, `0x08000890 + 0x30`, a busy-wait on
`gMain.intrCheck`, `src/main.c:462-468`; called as the last statement of every `AgbMain` iteration,
`src/main.c:214-216`) plus 93 frames inside the BIOS IRQ vector in IRQ mode. If the frame end were
tied to a VBlank *yield* in the game's code, R15 would be one value per loop; it is instead spread
across the spin loop, and in 5% of frames the boundary interrupts an IRQ handler mid-flight. The Gen 1
lane states the same rule plainly: "a BizHawk frame boundary is a PPU event, not a code [event]"
(`lua/gen1/client.lua:52`). `docs/gen3_write_checkpoint.md:57` records the same reading for the
parked-PC clause's provenance ("`WaitForVBlank` … spins on `gMain.intrCheck`; **the frame boundary the
census sampled**").

**Therefore: yes, a frame end can land between the emit and the exec clear**, in exactly the same way
it lands at five different offsets inside `WaitForVBlank`. The window is not *unobservable*; it is
*narrow*.

### 1.4 Order-of-magnitude, so the owner has the size

Frame = 280,896 GBA cycles. A window of ~10-80 Thumb instructions at ROM wait states is roughly
40-300 cycles ⇒ **~1.4e-4 to ~1.1e-3 of commits** end inside it. A duo battle commits a handful of
choices and the client issues at most a few writes per battle, so the compound chance that a *write*
is decided on such a frame is of order **1e-3 per battle** — about one in a thousand battles. This is
an arithmetic estimate from the instruction counts above, not a measurement; §3's census cannot
measure a 1e-4 event either (it would need ~10^5 commits), so it is designed to *bound* the rate and
to measure the thing that *is* measurable: where battle frames actually end.

---

## 2. How the overworld's `cpu` clause works, and whether it transfers

`safety.lua:108-114` evaluates the pack's `cpu` block: `CPSR % 32 == cpu.mode`,
`floor(CPSR/32) % 2 == cpu.thumb`, and `cpu.pc_min <= R15 <= cpu.pc_max`, with the comment that "a
frame end taken inside an IRQ handler fails the mode test on purpose; the next parked frame admits"
(`:108-109`). The block is **per title** and comes from a census:

| title | parked range | mode/T | census |
|---|---|---|---|
| firered | `WaitForVBlank`'s whole body `0x08000890-0x080008BF` (`observed_pc` `0x080008AC`) | `0x1F`, T=1 | `docs/gen3/probes/census_fr_overworld_2026-09-21.txt` (1707/1800 in range, 93 refused IRQ frames) |
| leafgreen | the same symbol address; no census, no `observed_pc` (generator emits the symbol only) | `0x1F`, T=1 | — |
| radical_red | the **BIOS** `IntrWait` path, `[0x0000,0x3FFF]` (`observed_pc` `0x1C4`) | `0x1F`, T=0 | `docs/gen3/probes/census_rr_overworld_2026-09-21.txt` (1800/1800 in range) |

(`data/games/gen3_frlg/write_checkpoint.json` `cpu`; `data/games/gen3_rr/write_checkpoint.json`
`cpu`; rationale and the FRLG-vs-RR difference: `docs/gen3_write_checkpoint.md` §4.3.)

**Transfer assessment.** The *mechanism* transfers unchanged — it is one R15 range plus a mode test,
already emitted per title, and the liveness argument (an IRQ or other transient frame is refused and
the next parked frame admits) is title-independent. What does **not** exist yet is the *battle* data:
every census above is overworld-idle. Two things would have to be measured before a battle clause
could be written:

1. **Where battle frame ends actually land**, per title and per phase. For FRLG the battle's per-frame
   work (CB1 + CB2 + the controllers; `docs/gen3/probes/census_rr_battle_2026-09-21.txt:3` records
   `BattleMainCB1 0x080123E4 hits=1348` / `BattleMainCB2 0x08011100 hits=1347` over 1800 frames) is
   much longer than the field's, so the share parking in `WaitForVBlank` will be *lower* than the
   field's 95% — an unknown.
   For RR the field parks in the BIOS on every frame; whether CFRU's battle loop does the same is
   unmeasured.
2. **The exclusion's precision.** An allow-list clause (option B below) refuses everything else,
   including phases where a write is otherwise fine (animations, message printing) — that is a
   liveness cost, not a safety gain, and it must be sized before it is imposed.

Note also that R15/CPSR are already recorded for every probe row: the checkpoint probe's `P.tally`
keeps `r15`/`cpsr`/`frame` per witnessed frame (`lua/tests/probe_gen3_checkpoint.lua`), and the 2b rows
module samples them on every frame and prints them in its receipt (`lua/tests/gen3_battle_window_rows.lua`,
`R.sample`'s `r15`/`cpsr`, printed by `R.receipt`). The census is a *reporting* change, not new
plumbing.

---

## 3. The census probe design (FR, LG, RR)

**Vehicle.** `lua/tests/probe_gen3_frameend_pc.lua` already does per-frame R15/CPSR/task bucketing on
`event.onframeend` and prints a histogram per situation (`:126-140` prints R15 top-10, CPSR mode/T
counts, task-set counts; `:189` is an explicit extension point for "a bucketing dimension beyond
R15/CPSR"). It is driven by `tools/run_gate.py` with `SLINK_STATE` + `SLINK_GEN3_TITLE` and a
`SLINK_CENSUS_FILE`-free path for this census (the census file flag belongs to the *battle-start*
exec census, a different probe).

**Rows** (one row = one loaded state + a scripted input sequence; reuse the state builders and the 2b
row machinery):

| row | state / input | what it must show |
|---|---|---|
| `parked_wild` | `slink_prebattle.State`, no input, ≥300 frames | the rest state the permit admits; percentage of frame ends inside `WaitForVBlank` |
| `commit_run` | same state, A on RUN (action cursor 3), sampled ~30 frames around the commit | whether any frame end lands in the ~10-instruction window (expected 0; the receipt records the count and the frames' PCs) |
| `commit_fight_move` | FIGHT → move cursor → A | the move-menu window (`:342-344`) |
| `commit_item` | BAG → item → A | the item window (`:1340-1341`) |
| `commit_switch` | POKéMON → slot → SHIFT | the party window (`:1315-1321`) |
| `menu_idle_move` | the move menu parked, no input | does a *submenu* park in `WaitForVBlank` like the action menu |
| `animation` | a real move/HP animation | the phase with the most non-parked frames (the liveness cost of option B) |
| `intro_outro` | the wild intro and the battle end | `battle_intro`/`battle_over` already exist as checkpoint rows; reuse them |

**Samples.** Every frame end within the row's window (the frame-end hook), i.e. no subsampling; the
existing floors apply (`min_samples=60`, and the positive rows' non-IRQ denominator).

**Receipt fields.** Reuse the BWSAMPLE receipt plus: `r15`, `cpsr` (already there), the seven clause
truths and `comm`/`ctrl`/`bufB0` (already there), plus **derived classifications** the census needs:
`pc_class` ∈ {`wait_for_vblank`, `input_choose_action`, `input_choose_move`, `exec_completed`,
`bios_irq`, `other`} — the ranges being `[0x08000890,0x080008BF]`, `[0x0802E438,+0x206)`,
`[0x0802EA10,+0x3CC)`, `[0x0802E33C,+0x78)`, `[0x0000,0x4000)`, and for RR the CFRU bodies
(`0x090A9EFE-0x090A9F20`, `0x0904459A`, `0x090ACD8D`) — plus a per-row top-10 R15 histogram printed
once at row end, in the overworld census's exact format.

**Titles.** FR and LG use the vanilla dump (`SLINK_GEN3_TITLE`); RR uses the **companion** build (the
patched ROM the client ships with) and, if cheap, RR clean as a control. The census must be run per
title because the parked range differs (§2's table) and because RR's loop parks in the BIOS.

**Deliverable.** One receipt per title: per row, the frame count, the PC-class histogram, the count of
frame ends inside either commit window, and the percentage parked in the title's `WaitForVBlank`
(RR: BIOS) range. The last number is what decides whether option B is viable at all.

**Wrapping.** Use `tools/gen3_probe_receipt.py` for the header/receipt (§6 of the runbook) so the
census receipt carries the lane, the script's git-blob sha and the invocation, like the probe rows.

---

## 4. Options for the owner

| option | what changes | cost | risk |
|---|---|---|---|
| **A. No change; document** | nothing; the census is recorded as the bound (§1.4) | one probe run per title | the ~10-instruction window stays theoretically admissible; the client must never act on a frame that *looks* parked but is mid-commit. If the estimate is wrong by orders of magnitude, a write can land there — fail-*open* by ~1e-3/battle |
| **B. Battle `cpu` clause = the overworld parked range** | `pack.battle` gains a `cpu` clause; `safety.lua` gains nothing (the clause type already exists) | a census per title **per phase**; a pack regeneration | an allow-list refuses every frame not parked in `WaitForVBlank`: animations, message printing, the intro/outro, and RR's battle loop if it does not park in the BIOS. Liveness must be re-proved for every battle write (the C4-SAVE class of failure: a permit that never holds) |
| **C. Narrow inverse clause (forbid the commit ranges)** | a new clause kind in `safety.lua` + `pack.battle` (e.g. `forbid_pc`: any R15 inside the menu-commit bodies); title-specific addresses for RR | one census; a new clause type; pack regeneration per title | precise, but it is still a *safety* clause for a *single-frame* transient: it only helps if the client is evaluated on that frame, and a wrong range could refuse a legitimate parked frame (the parked controller body is *in* `HandleInputChooseAction`'s object on FR, so the range must be the commit *instructions*, not the object) |
| **D. RR-only hold** (like `commit_hold`) | `pack.battle.commit_hold` already exists for `battle_commit`; extend the idea to `battle_faint` on RR | pack only | treats RR as unproven rather than measuring; and if RR simply parks in the BIOS during battle, this gives up writes it did not need to |
| **E. Client-side two-frame confirm** | the client's policy requires the permit to have held on the *current and the previous* frame before it applies a write | one extra clause evaluation per frame while connected (a few memory reads), plus one frame of latency; **no pack change, no title branch** | closes the whole class of single-frame transients, including this one; the cost is latency and the added per-frame evaluation — the harness's own frame budget is unaffected (the client already reads the snapshot every frame in a battle) |

---

## 5. Recommendation

1. **Do not add a battle `cpu` clause on the strength of this analysis (not option B).** Its benefit is
   a window of ~10 instructions out of 280,896 cycles; its cost is an allow-list over a phase where the
   parked share is unmeasured, and a permit that never holds is the failure mode this project has
   already paid for once (C4-SAVE).
2. **Implement option E (client-side two-frame confirm) as the structural fix.** It is title-free, needs
   no pack regeneration, costs one frame of latency, and closes not only this window but any other
   single-frame transient the seven clauses cannot see — a strictly better trade than a PC range.
3. **Run the §3 census anyway, as evidence for the record and for option B's viability**: the numbers
   (per title, per phase: frame ends inside `WaitForVBlank`, inside either commit window, inside the
   BIOS IRQ) are what a future relaxation of the battle permit would need, and they cost one lane
   invocation per title.
4. **If the census shows battle frames parking outside `WaitForVBlank` in a large share of frames**,
   record that as the reason option B is off the table rather than leaving it as an open design
   question.

---

## 6. Unverified / open

1. **Every case's instruction route in `HandleInputChooseAction`** is not fully mapped: I disassembled
   two emit sites (`0x0802E4CA`, `0x0802E612`) and the callee head (`0x0802E33C-0x0802E356`), so the
   ~10-instruction figure is the short path. A full disassembly would give the exact span per case.
2. **The frame-end rate inside a window this narrow is not measurable** with a practical run; §1.4's
   estimate is arithmetic, and the census bounds rather than measures it.
3. **RR's battle-loop parking** (BIOS vs ROM) is unknown; only the overworld is measured (1800/1800 in
   BIOS).
4. **LG has no overworld census** either (`docs/gen3_write_checkpoint.md` §4.3: "LG has no census; its
   block has no `observed_pc`/`census`, only the symbol"), so its battle census would be the first LG
   CPU evidence of any kind.
5. **Whether the client is already evaluated on every frame** in a battle (needed for option E's cost
   estimate) is not settled here; it would be settled by reading `lua/gen3/client.lua`'s per-frame pump.

## Coordinator note (2026-09-23): the two-frame confirm does not close this window

Recommendation (1) above is rejected. Take a frame T whose end falls inside the commit call: the
choice has already been emitted, but the exec bit is not yet cleared, so T reads as parked. The
frame before it, T-1, really was parked. A rule of "the permit held on this frame AND the previous
one" therefore still admits T. A frame-end hook cannot tell at T that T is transient; that only
shows at T+1. And a write made at T+1 after seeing T parked has the same exposure if T+1 is itself
the start of a new commit. The confirm moves the window; it does not close it.

What does close it at frame granularity is option C: refuse when R15 lies inside the commit
routines. Those ranges are the per-title `HandleInputChooseAction` / `HandleInputChooseMove` /
`PlayerBufferExecCompleted` bodies, plus the CFRU bodies on RR, and the census in §3 measures
them. The analysis in §1-§3 stands, and so does the size estimate (about 1e-4 to 1e-3 per commit).
The decision goes to the owner, with two choices: (a) record the window as a limit, or (b) add the
inverse R15 clause after the census. Separately, the LG CPU census (finding 6) is worth running
whichever way the owner decides.
