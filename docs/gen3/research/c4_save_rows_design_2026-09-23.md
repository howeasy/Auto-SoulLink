# C4-SAVE physical rows: the cheapest self-proving extensions (static design, 2026-09-23)

Scope: design only, no emulator, no commit. Worktree `E:/Google Drive/SLink/.claude/worktrees/
gen3-migration-planning-5d8e45` @ `7ebb1216`; pret `E:/Google Drive/SLink/.cache/pret/pokefirered`
@ `c75f3523`. The four rows are §3.2 of `docs/gen3/G4_request_draft.md` (rows 1, 3, 6, 9).
`lua/tests/probe_gen3_checkpoint.lua` belongs to C4-PROBE2 (landed `10e4a702`): this design
**reads** it and never assumes an edit — the rows below exercise its `dialog` row physically.

Vocabulary used below: *refused* / *admitted* are about the overworld checkpoint
(`lua/gen3/safety.lua:12-108`), whose clauses are the ten predicates
(`lua/gen3/safety.lua:5-7`: `callback1, callback2, field_controls_locked, in_battle, link_callback,
link_players_received, link_transferring, palette_fade_active, script_context_status,
soft_reset_disabled`) plus `cpu` (`:78-83`), `task` (the allow-list, `:84-95`), `native` (`:97-99`)
and `pointer` (`:100-…`). Each predicate's failure message is `forbidden state: <name>`
(`lua/gen3/safety.lua:27`), which is what the scenarios and the runner parse
(`scenario_gen3_save_then_write.lua:44`, `tools/e2e_duo.py:1494-1512`). The pack is
`data/games/gen3_frlg/write_checkpoint.json`: `predicates` (10 keys), `tasks.
allowed_overworld_tasks` (7 entries), `witnesses.save_dialog_cb` — a **witness**, never a clause
(same file; `lua/gen3/safety.lua` no longer lists it, and `gen3_boot_check.lua:189-197`'s `M.pred`
falls back to `witnesses`).

## 0. The two extension points, and why they cover four rows

| Rows | Extends | Why that scenario |
|---|---|---|
| **1** (START prompts/cancel/dismissal) and **9** (dialog witness false on another submenu) | `lua/tests/duo/scenario_gen3_save_then_write.lua` | both are START-menu steps taken *after* an in-game save, which is that scenario's whole subject; its `ctx.save` helper already drives the menu (`gen3_boot_check.lua:396-…`) |
| **3** (Cable Club save as its own witness row) and **6** (cable open-before-exchange / null callback while open) | `lua/tests/duo/scenario_gen3_center_controls.lua` | it already stands at the Cable Club welcome message, already performs that save (`center_controls_chain`, `tools/e2e_duo.py:1502`), and already holds a probe across the link wait (`scenario_gen3_center_controls.lua:140-155`) |

**Launch budget: 2 launches, not 4** — rows 1+9 share the `save_then_write_gen3` launch
(`tools/e2e_duo.py:233`, timeout 1200) and rows 3+6 share the `center_controls_gen3` launch
(`tools/e2e_duo.py:228`, timeout 2400). Both scenarios are `gen3_frlg` rows, so each launch is the
usual duo pair plus the duo server. Adding legs also fits the existing margins: the FR
`save_then_write` receipt ran ~2162 frames after boot and the FR Center receipt ~14162
(`docs/gen3/probes/*_2026-09-23.txt`), far below either timeout.

## 1. Row 1 — START save: the overwrite prompt, cancel, and the success dismissal

**Extend `scenario_gen3_save_then_write.lua`** with one leg after the existing
`WRITE_LANDED`/second-save sequence; the current chain stays intact (`save_then_write_chain`,
`tools/e2e_duo.py:1483-1491`).

Steps, with pret citations (all in `src/start_menu.c`):

1. **Second save → the overwrite prompt.** The scenario already does a second save. With a save
   present and `gDifferentSaveFile == FALSE`, `SaveDialogCB_AskSaveHandleInput` routes to
   `SaveDialogCB_PrintAskOverwriteText` (`:726-743`, condition at `:731`), which prints
   `gText_AlreadySaveFile_WouldLikeToOverwrite` (`:745-752`) and then
   `DisplayYesNoMenuDefaultYes()` (`:754-759`). *This* is the prompt `save_via_menu` currently
   bull-dozes through with A.
2. **Cancel.** At the yes/no menu, press **B** (or Down+A to select NO): both land in
   `SaveDialogCB_AskOverwriteOrReplacePreviousFileHandleInput`'s `case 1/-1` (`:775-780`), which
   closes the message window and returns `SAVECB_RETURN_CANCEL`; the save-dialog task's caller then
   draws the START menu again and re-arms `StartCB_HandleInput` (`:589-594`) — the field stays
   locked because the menu is still open (`Task_StartMenuHandleInput` is alive, `:378-394`, and
   `ShowStartMenu` locked it at `:405`).
3. **Dismiss the menu.** Press **B**: `StartCB_HandleInput` calls `CloseStartMenu()` (`:441`), whose
   body unlocks the field (`CloseStartMenu` at `:1003-1009`, `UnlockPlayerFieldControls()`).
4. **Success dismissal.** For the *saving* path, the dialog's last state is
   `SaveDialogCB_ReturnSuccess` (`:827-835`), which waits 60 frames or an A press
   (`SaveDialog_Wait60FramesOrAButtonHeld`, `:671-687`) before returning `SAVECB_RETURN_OKAY`, and
   only then does the caller unlock the field and restore help context (`:583-588`). The leg should
   assert **which of the two dismissals** it saw (60-frame timeout vs A press) rather than assume,
   because `ctx.save`'s helper currently returns as soon as the counter advances.

Clause expectation per step (from `lua/gen3/safety.lua` + the pack):

| Step | Expected | Clause that should name the refusal |
|---|---|---|
| prompt on screen, menu open | refused | `task` (the START task is not in `tasks.allowed_overworld_tasks`) and `field_controls_locked` — the pair named in `0e7f89e7`'s message; the dialog witness `save_dialog_cb` is non-zero but is **not** a clause |
| cancel, menu redrawn | refused | same two; the pointer stays stale (`PrintAskSaveText` set it at `:608`, nothing clears it) |
| menu dismissed | **admitted** | no clause fails; `task` passes because `Task_StartMenuHandleInput` was destroyed at `:390-391` |
| the saving path's dismissal | **admitted** after `SAVECB_RETURN_OKAY` | `:586`'s unlock; witness still stale |

Marker / oracle:

- the leg logs `SAVE_CANCEL_PROMPT <linked> row=save prompt=overwrite`, then
  `SAVE_CANCEL_MENU_CLOSED <linked>` after the B press and `SAVE_CANCEL_FIELD_FREE <linked>` when
  `field_controls_locked` reads free — each immediately preceded by a `ctx.hold_probe` (or a
  one-shot `ctx.received`/`ctx.queued` check) so the runner can queue a probe at each state,
  exactly as `center_controls` does (`scenario_gen3_center_controls.lua:11-12`);
- the oracle extends `orchestrate_save_then_write_gen3` (`tools/e2e_duo.py:5274`) with a
  `_gen3_mark("a", "^SAVE_CANCEL_PROMPT ", …)` and a second `_gen3_mark` at
  `SAVE_CANCEL_FIELD_FREE`, then requires, in order: the two markers, a refused probe at the
  prompt (`gen3_rx`/`CONTROL_REFUSED`-style line with `clause=task` or `clause=field_controls_locked`),
  and a **landed** probe after `SAVE_CANCEL_FIELD_FREE` (RX + `stats_cache` + boxed readback, the
  same tuple `save_then_write_chain` already uses).

First falsifier: a lupa case in `tests/unit/test_e2e_duo_gen3.py`'s fake-ctx harness
(`_FAKE_CTX`, `:1025`; `_run_module(lua, "save_then_write", "a", "initial", spec)`), where `spec`
makes the *prompt* an admit (`field_controls_locked` free and the task list clean) — the leg must
then return `false` naming the prompt, proving it cannot pass on a field that never refused. The
mirror case (cancel → refused forever) must fail at `SAVE_CANCEL_FIELD_FREE`.

## 2. Row 3 — the Cable Club save as its own witness row

**Extend `scenario_gen3_center_controls.lua`** — no new run: the save already happens inside the
`cable_welcome_message` → `cable_link` sequence (`tools/e2e_duo.py:1502` requires a
`SAVE_WITNESS_DUMP` between them), it is simply not *named* as its own control.

Steps (pret):

1. At the 2F attendant's no-adapter branch the script offers the Colosseum/Trade options; choosing
   one reaches `CableClub_EventScript_TryEnterColosseum` (`data/scripts/cable_club.inc:268-284`) or
   `CableClub_EventScript_TradeCenter` (`:363-380`), both of which `call EventScript_AskSaveGame`
   (`:269`, `:367`).
2. `EventScript_AskSaveGame` is `special Field_AskSaveTheGame` + `waitstate`
   (`data/scripts/std_msgbox.inc:57-60`), i.e. `src/start_menu.c:620-626`: it prepares the dialog and
   `CreateTask(task50_save_game, 80)`.
3. Answer the `gText_WouldYouLikeToSaveTheGame` prompt (`:709-717`) with **A** (yes; the menu
   defaults to yes at `:719-724`, and `:726-743` then goes straight to
   `SaveDialogCB_PrintSavingDontTurnOffPower`, since the fixture's save is a normal same-file save).
4. Let the save and its success dismissal run (`:784-835`), then continue the link path the control
   already drives.

Clause expectation: while `task50_save_game` is alive and the script is parked, **refused** — by
`task` (task50_save_game is not on the allow-list), `script_context_status`, and once the message
box is up `field_controls_locked` too; after `RunSaveDialogCB` returns 1 and `ScriptContext_Enable()`
runs (`:637-654`), the *script* continues, so the control's next refusal is the link's
(`link_callback`) rather than the save's. Nothing here is a save-dialog clause: this is the row that
proves the fix removed one.

Marker / oracle: a new named control `cable_save` between the welcome and the link rows, in the
existing control style — `CONTROL_LIVE cable_save <linked>` (with the `task50_save_game` witness as
its `live()`), a refused keyed probe with the clause named, then `CONTROL_RELEASED`/
`CONTROL_SETTLED` and a landed probe after the save returns. The oracle adds it to
`center_controls_chain` (`tools/e2e_duo.py:1494-1512`) in place of the bare `SAVE_WITNESS_DUMP`
match, and `orchestrate_center_controls_gen3` (`:5257`) queues the probe at the new
`CONTROL_LIVE`.

First falsifier: the fake-ctx case where the save's `live()` witness never becomes true — the control
must fail naming `task50_save_game`, not pass silently on the welcome message's refusal.

## 3. Row 6 — cable `open before exchange` and `null callback while open`

**Extend `scenario_gen3_center_controls.lua`'s `cable_link` control** (`:140-155`), which already
reaches the link wait and already refuses on the new clause (`link_callback=0x1` in
`docs/gen3/probes/center_controls_fr_as_a_2026-09-23.txt`).

The two states, from pret `src/link.c`:

- **open before exchange** = the two statements between `InitLink()` setting `sLinkOpen = TRUE`
  (`:373`) and `OpenLink`'s `gLinkCallback = LinkCB_RequestPlayerDataExchange` (`:394`, cable branch
  `:390-405`). They are consecutive statements in one function: **no frame boundary**, so a Lua
  harness cannot sample them. **Recorded limit**, not a row.
- **null callback while open** = `sLinkOpen == TRUE` with `gLinkCallback == NULL`. Reachable, because
  `CloseLink` clears only `sLinkOpen` (`:419-426`) and the callbacks are cleared independently by
  `ClearLinkCallback` / `ClearLinkCallback_2` (`:746-757`), whose callers include
  `src/cable_club.c:637` (Task_StartWiredCableClubBattle case 0, next to the fade) and `:693`,
  `:886`, plus `src/field_fadetransition.c:661`. `LinkMain2` is the reason the clause exists: it calls
  the callback only while `sLinkOpen` (`:512-523`).

Design: drive the Colosseum/Trade option one step further than today (accept the save from row 3,
then let the linkup task run) and sample every frame, as this scenario's `live()` already does
(`:11-12`). Assert **one of**:

- a sampled frame with `sLinkOpen` true and `link_callback` false while the field is otherwise idle
  (the row), or
- `palette_fade_active` already refusing for the whole window (the fade starts in the same task
  case, `cable_club.c:635-637`), in which case the row is recorded as covered-by-fade rather than
  witnessed.

Clause expectation: at those frames **refused**; the naming clause is whichever of `task`,
`script_context_status`, `field_controls_locked`, `palette_fade_active` also fails on that frame —
the runner attributes the *first* failing clause set (`tools/e2e_duo.py:1494-1512`), so the design
requires the expected clause **set** to be recorded in the receipt line, not a single name.

Marker / oracle: `CABLE_CALLBACK_NULL sLinkOpen=1 gLinkCallback=0 frame=<n>` on the witnessed frame
(or `CABLE_CALLBACK_NULL limit=fade-only` when it never appears), plus a probe queued at the
previous marker that must be refused. Oracle: `center_controls_chain` gains the marker and a
refused-probe line; the "limit" form is accepted only with the fade clause named in the same line,
so it cannot be used to wave a genuine admit through.

First falsifier: the fake-ctx case that makes `sLinkOpen` true and the callback non-null on every
sample — the control must fail with "no null-callback window witnessed" rather than pass on the
link-wait refusal it already had.

## 4. Row 9 — the dialog witness on another submenu, after an earlier save

**Extend `scenario_gen3_save_then_write.lua`** (the source half landed in `10e4a702`; this is the
physical half).

Steps:

1. After the existing second save, open START (`Start`, `gen3_boot_check.lua:433`) and wait for
   `Task_StartMenuHandleInput` with `StartCB_HandleInput` (`start_menu.c:378-394, 408-441`; the
   driver's own `start_menu_witness`, used at `gen3_boot_check.lua:402`).
2. Move the cursor **off** the SAVE row: read `sStartMenuOrder` the way `save_via_menu` does
   (`:459-468`, `START_MENU_ORDER_ADDR` / `MENU_ACTION_SAVE`) and press Down/Up to any other row.
   Keep the menu open for ≥30 frames so at least one sample is taken while the cursor rests there.
3. Sample the probe's `dialog` row semantics: `start_menu_save_callback_under_live_task`
   (`lua/tests/probe_gen3_checkpoint.lua:31`, mapping at `tests/unit/test_probe_gen3_checkpoint.py:13`)
   — the witness is stale-pointer **and** live START task, and this step is exactly the case
   Codex rejected (`cx-3e10776a`: a non-zero pointer on any submenu's A).

Clause expectation: **refused** (the menu holds the field: `task` for `Task_StartMenuHandleInput`,
`field_controls_locked`), and the receipt must show that **no save-dialog key appears anywhere in
the clause list** — which is now trivially true because it is not a clause, and is precisely the
regression guard for the old pack.

Marker / oracle: `DIALOG_WITNESS_FALSE cursor=<row> menu=open` followed by the refused probe line
with its clause set; the oracle requires the marker, the refusal, the clause set to contain `task`
or `field_controls_locked`, and — as a negative — that the line does **not** contain
`save_dialog_cb`. `save_then_write_chain` (`tools/e2e_duo.py:1483`, the chain's body at `:1484-1491`) gains the pair at the end.

First falsifier: the fake-ctx case where the witness is the pre-`10e4a702` shape (stale pointer
alone) — the control must fail, i.e. the row is red on the old witness. The characterisation that
today's pack *fails by name* on `save_dialog_cb` already exists in the unit suite
(`tests/unit/test_e2e_duo_gen3.py:2975-2979`) and stays as the old-pack pin.

## 5. What stays a recorded limit, and why

| Row element | Why it cannot be a row |
|---|---|
| the **different-file** overwrite prompt (`gText_DifferentGameFile`, `start_menu.c:747-748`, default NO at `:761-766`) | needs `gDifferentSaveFile == TRUE`, i.e. a save belonging to another game file; the battery fixture is one normal save, and no harness input can produce a foreign one |
| **flash-failure recovery** (row 2 of §3.2) | needs a forced write failure; the audit covers it statically |
| **open before exchange** (row 6's first half) | straight-line code, `link.c:393-394` — no frame boundary to sample |

## 6. Unverified / to settle

- **Wall-clock cost per launch** is not measured here; only frame counts from existing receipts are
  cited. The lane's own overhead (two EmuHawk launches, the duo server, settle waits) dominates a
  ~4k-frame leg.
- Whether the `null callback while open` window is wide enough for a Lua sample at 1600% speed is
  **not** established — the design's "limit" branch exists for that reason, and the first run
  decides which branch the receipt takes.
- `save_via_menu`'s success path does not currently distinguish the 60-frame timeout from an A press
  (`start_menu.c:671-687`); step 4 of row 1 would have to read which one happened, and that read is
  not yet designed.
- The exact clause the runner attributes when several fail on one frame is observed, not documented:
  receipts name one clause while `preds=[…]` lists several (`center_controls_fr_as_a_2026-09-23.txt`
  names `clause=link_callback` on a frame where `field_controls_locked` also fails). Rows 3 and 6 are
  designed around the *set*, not the single name.
