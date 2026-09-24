# G4 final-cut runbook (card C4-FINALCUT-RUNBOOK)

Written for the moment the coordinator freezes the G4 cut: every live invocation the frozen cut
needs, grouped by G4 item, with the receipt it produces and the line to look for. Sources are
`docs/gen3/G4_request_draft.md` (§1, §2, §3.2, §6), `docs/gen3/research/g4_2b_matrix_plan_2026-09-23.md`,
and the receipt headers under `docs/gen3/probes/`. Every command below was copied from a receipt's
own header or `# invocation:` line, from a tool's argparse, or from a wrapper's source; nothing is
invented. Items with no command anywhere in the tree are listed as UNKNOWN at the end and in place.
One emulator lane at a time (`docs/gen3/PLAN.md:23`).

Vocabulary from the draft §2: **DONE** = citable receipt exists, **REHEARSED** = re-take on the
final cut, **OPEN** = not started, **BLOCKED** = cannot run with the current hardware/fixtures.

---

## 0. Preconditions

1. **A clean lane**: a detached worktree of this repo at the frozen cut, clean working tree, whose
   sha is what the receipts record as `source=`/`lane=`. The receipts in the tree were taken from
   `.claude/worktrees/gen3-lane-clean` (e.g. `checkpoint_fr_clean_c4probe2_2026-09-23.txt:1`
   `lane=b0511ff2eb3e04c8504ca9bc71806fa5283e0bdf tracked_clean=True`,
   `save_then_write_fr_as_a_b261d045_2026-09-23.txt:5` `source=b261d045741e…`).
   *Provisioning command*: **UNKNOWN** — no script creates the lane; take it as the coordinator did
   (a `git worktree` of the cut plus the run-config copies the harness makes per instance, per
   `tools/e2e_duo.py`'s module docstring).
2. **Rewind off.** `C4-6t` (`10e4a702`) forces it off in every generated run config; the machine's
   base `E:/Howard/Bizhawk/config.ini` still has it ON, so any manually launched EmuHawk must not use
   the base config (`docs/gen3_resume.md`, CHECKPOINT 13's closing line).
3. **Emulator and inputs present**: `E:/Howard/Bizhawk/EmuHawk.exe`; the dumps at the repo root
   (`Pokemon - FireRed Version (USA).gba`, `Pokemon - LeafGreen Version (USA).gba`); the staged
   copies under `patch/build/` the gates use; the fixtures under `tests/fixtures/gen3/` (committed,
   see §1.3); for Gen 1/6, `patch/gen1/build/slink_{red,blue}.gb` and the Gen 1 fixtures.
4. **State builds first** (§1). The `.State` files are lane-local artifacts, never committed, so a
   fresh lane must rebuild them before any probe row.
5. **Fixtures are committed.** At the lane level a skip is a failure unless `ALLOWED_SKIPS`
   excuses it (`tools/release_lanes.py`'s rules, `tools/verify_gen3_release.py:27-34`); the duo
   wrapper fails outright on a missing EmuHawk/ROM/fixture (`tests/e2e/test_duo_gen3.py:70-75`),
   while the hook-probe test skips on one (`tests/live/test_gen3_probe_gates.py:34-36`) and is then
   failed by the lane.

---

## 1. Builds, in order

### 1.1 Probe states (town/battle) — needed by item 3 and §3.2

```
python tools/mkstates_gen3.py --title firered   --kind town   --out-dir <lane>/patch/build/gen3_probe_states_c4p2/firered   --rom patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba
python tools/mkstates_gen3.py --title firered   --kind battle --out-dir <lane>/patch/build/gen3_probe_states_c4p2/firered   --rom patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba
python tools/mkstates_gen3.py --title leafgreen --kind town   --out-dir <lane>/patch/build/gen3_probe_states_c4p2/leafgreen --rom patch/build/gen3_Pokemon_-_LeafGreen_Version_(USA).gba
python tools/mkstates_gen3.py --title leafgreen --kind battle --out-dir <lane>/patch/build/gen3_probe_states_c4p2/leafgreen --rom patch/build/gen3_Pokemon_-_LeafGreen_Version_(USA).gba
```
Flags are `--title/--kind/--out-dir/--rom/--saveram-name/--timeout` (`tools/mkstates_gen3.py:30-35`);
the `_c4p2` out-dir name is the one the probe receipt used (`checkpoint_fr_clean_c4probe2_2026-09-23.txt:4`
`SLINK_STATE_DIR=…/patch/build/gen3_probe_states_c4p2/firered`).
- **Receipts** in the tree: `docs/gen3/probes/mkstates_gen3_{firered,leafgreen}_{town,battle}_2026-09-23.txt`.
- **PASS line**: `RESULT: PASS town states in <dir>` / `RESULT: PASS battle states in <dir>`
  (the `[gate]` prefix is `tools/run_gate.py`'s; the receipt wraps each mkstates run).
- **Wall-clock**: ~6 s per build (receipt: `(6s)`).

### 1.2 Tutorial states (old man + Pokedude) — required by the bw U1/U2 rows

```
python tools/mkstates_gen3_tutorials.py --title firered   --out-dir <lane>/patch/build/gen3_probe_states/firered
python tools/mkstates_gen3_tutorials.py --title leafgreen --out-dir <lane>/patch/build/gen3_probe_states/leafgreen
```
Flags `--title/--out-dir/--rom/--saveram-name/--timeout` (`tools/mkstates_gen3_tutorials.py:42-46`;
default out-dir `patch/build/gen3_probe_states/<title>`). The probe resolves
`slink_oldman.State`/`slink_pokedude.State` in **its own** `SLINK_STATE_DIR`, so either build these
into the probe's state dir or point `SLINK_CHECKPOINT_OLDMAN_STATE` / `SLINK_CHECKPOINT_POKEDUDE_STATE`
at them (`lua/tests/probe_gen3_checkpoint.lua:5-10`, bw rows at `:200-204`).
- **Receipt**: `docs/gen3/probes/tutorial_states_{fr,lg}_2026-09-23.txt`.
- **PASS line**: `RESULT: PASS tutorial states in <dir>`; the states it must produce are named in the
  receipt (`slink_oldman.State … in_battle=true flags=00000204 ctrl0=080E78E1`,
  `slink_pokedude.State … flags=00010004 ctrl0=0815614D`, `tutorial_states_fr_2026-09-23.txt:12,15`).
- **Wall-clock**: ~16 s per title (receipt: `(16s)`).

### 1.3 (Optional) Fixture rebuild — only if a fixture is missing

No emulator needed for `import`/`qualify`/`derive-b`:
```
python tools/gen3_fixtures.py import --src <SaveRAM> --out tests/fixtures/gen3/<pack>_<scene>.sav [--rr]
python tools/gen3_fixtures.py qualify <files…> [--rr]
python tools/gen3_fixtures.py derive-b <a.sav> <b.sav> [--rr]
python tools/gen3_fixtures.py make-fr --rom <dump> --out <fixture.sav> --title firered|leafgreen
```
(`tools/gen3_fixtures.py:866-905`, `tests/fixtures/gen3/README.md`). `derive-b --rr` always refuses
by design; an RR B-side fixture needs its own card. The FR/LG battery saves the harness boots are
`tests/fixtures/gen3/{firered,leafgreen}_party_{town,battle}{,_b}.sav`
(`tools/e2e_duo.py:1776-1784`).

---

## 2. Item 1 — FR↔LG faint on a clean cut (optional frozen-cut re-run)

Per `RECEIPT_AUDIT_2026-09-23.md`, a final re-run of faint/link/boxsync/reconnect is **optional
regression evidence**; the gate row is DONE (`duo_frlg_faint_cmd_gen3_clean_2026-09-23b.txt`).

```
python tools/e2e_duo.py --game gen3_frlg --scenario faint_cmd_gen3
```
(or the lane wrapper, which runs every scenario it selects and fails closed on a skip:
`SLINK_E2E=1 pytest tests/e2e/test_duo_gen3.py -q`, `tests/e2e/test_duo_gen3.py:1-8`).
- **Receipt**: capture stdout → `docs/gen3/probes/duo_frlg_faint_cmd_gen3_clean_<date>.txt`
  (observed: `duo_frlg_faint_cmd_gen3_clean_2026-09-23.txt`, `…b.txt`).
- **PASS line**: `[duo] faint_cmd_gen3: a=PASS b=PASS` and the summary `faint_cmd_gen3: PASS (attempt 1 of 1)`.
- **Wall-clock**: no measured time in the receipt; the registry budget is `timeout: 900` s
  (`tools/e2e_duo.py:220`).
- **Caveat to keep**: the receipt proves an injected-event overworld faint, not a natural battle one.

## 3. Item 2 — the seven FRLG scenarios (optional frozen-cut re-run)

One invocation each, same wrapper:
```
for s in faint_cmd_gen3 link_gen3 boxsync_gen3 reconnect_gen3 deadzone_gen3 whiteout_gen3 linked_faint_active_gen3; do
  python tools/e2e_duo.py --game gen3_frlg --scenario "$s"
done
```
`reconnect_gen3`'s fail-closed C-1 leg takes an optional second-OT save:
`SLINK_WRONG_SAVE=<second-OT FR flash save>` (`tests/e2e/test_duo_gen3.py:78-79`).
- **Receipts** (observed): `duo_frlg_{faint_cmd,link,boxsync,reconnect,reconnect_wrong_save,deadzone,whiteout,linked_faint_active}_gen3_clean_2026-09-23*.txt`.
- **PASS line**: `[duo] <scenario>: a=PASS b=PASS`, plus `PYDEC: PASS asserted scenario facts` and
  `SAVE_WITNESS_SHA256 match=true` with a counter delta on each saving side
  (`RECEIPT_AUDIT_2026-09-23.md`; draft §1).
- **Wall-clock**: budgets 900–2400 s (`tools/e2e_duo.py:220-253`); the summary records the attempt
  count, not seconds (e.g. `link_gen3: PASS (attempt 2 of 3)`).

## 4. Item 2a — Center writes: whiteout + the 2F controls, both orientations

Whiteout (the write lands inside the Center) and the 2F controls (Cable Club welcome, cable link
wait, Union Room attendant, all refusals), FR-as-A and LG-as-A:
```
python tools/e2e_duo.py --game gen3_frlg --scenario whiteout_gen3          # FR as A
python tools/e2e_duo.py --game gen3_lgfr  --scenario whiteout_gen3          # LG as A
python tools/e2e_duo.py --game gen3_frlg --scenario center_controls_gen3    # FR as A
python tools/e2e_duo.py --game gen3_lgfr  --scenario center_controls_gen3   # LG as A
```
`gen3_lgfr` is the same family with the sides swapped (LG as A) — `tools/e2e_duo.py:1790-1798`.
- **Receipts**: `center_receipt_whiteout_{fr,lg}_as_a_2026-09-23.txt`,
  `center_controls_{fr,lg}_as_a_b261d045_2026-09-23.txt` (earlier cuts: `…_c4saverows…`, and the
  pre-b261d045 plain names).
- **PASS line**: `[duo] whiteout_gen3: a=PASS b=PASS` / `[duo] center_controls_gen3: a=PASS b=PASS`,
  plus the control markers the draft quotes (`CONTROL_LIVE nurse map=5.4 at=(7,4)`,
  `CONTROL_REFUSED … clause=field_controls_locked attempted=0 writes=0 bytes=unchanged`,
  `CABLE_CALLBACK_NULL limit=no-cable-partner`, `PYDEC: PASS asserted scenario facts`).
- **Wall-clock**: budgets 2400 s each; b261d045's four runs are the current re-take.
- The Union Room **entry/return** row stays owner ruling (b), unreachable while
  `IsWirelessAdapterConnected` reads false (draft §2 2a).

## 5. Item 2b — the in-battle matrix

**Mechanism P+H (owner rulings 15-16/19) superseded the T2/A2 hold plan.** There are four scenarios,
each run both orientations (FR-as-A and LG-as-A) — 8 rows, `tools/gen3_final_cut.py:148-153`, tag
`§5 item2b`:

| Row (id = `<scenario>_<orientation>`) | Scenario | Orientation (`ORIENT`, `:79`) |
|---|---|---|
| `linked_faint_active_gen3_fr_as_a` / `_lg_as_a` | **A1**: natural faint of the active linked mon | `--game gen3_frlg` (FR-as-A) / `--game gen3_lgfr` (LG-as-A) |
| `active_end_gen3_fr_as_a` / `_lg_as_a` | **A2**: engine Perish KO in battle with no input | same |
| `linked_faint_active_whiteout_gen3_fr_as_a` / `_lg_as_a` | whiteout after the last linked pair dies (ruling 21) | same |
| `linked_faint_active_trainer_gen3_fr_as_a` / `_lg_as_a` | trainer battle (route to Rick 102) | same |

Command per row (`_duo()`, `tools/gen3_final_cut.py:120-123`):
```
python tools/e2e_duo.py --game gen3_frlg --scenario linked_faint_active_gen3          # A1, FR-as-A
python tools/e2e_duo.py --game gen3_lgfr  --scenario linked_faint_active_gen3          # A1, LG-as-A
python tools/e2e_duo.py --game gen3_frlg --scenario active_end_gen3                    # A2, FR-as-A
python tools/e2e_duo.py --game gen3_lgfr  --scenario active_end_gen3                   # A2, LG-as-A
python tools/e2e_duo.py --game gen3_frlg --scenario linked_faint_active_whiteout_gen3  # whiteout, FR-as-A
python tools/e2e_duo.py --game gen3_lgfr  --scenario linked_faint_active_whiteout_gen3 # whiteout, LG-as-A
python tools/e2e_duo.py --game gen3_frlg --scenario linked_faint_active_trainer_gen3   # trainer, FR-as-A
python tools/e2e_duo.py --game gen3_lgfr  --scenario linked_faint_active_trainer_gen3  # trainer, LG-as-A
```
- **Receipt (final-cut run)**: `docs/gen3/probes/fc_<row>_<cut8>.txt` (`receipt_path`, `:265-266`).
  The REHEARSED evidence at the pre-final cuts `b0483efe`/`28e48c9c` is
  `docs/gen3/probes/ph_<scenario>_<orientation>_<cut8>.txt` (G4-LANE-2, committed at `6d6227c6`):
  8 PASS files, one per row above, mostly at `b0483efe` — the two exceptions are
  `linked_faint_active_whiteout_gen3_fr_as_a`, which PASSes at `28e48c9c` (its `b0483efe` attempt is a
  kept FAIL instrument record, see below), and `linked_faint_active_trainer_gen3_lg_as_a`, which only
  ran at `28e48c9c` (no `b0483efe` attempt exists for that row).
- **PASS line**: `RESULT_LINE a`/`b` both `RESULT: PASS (…)` — A1/whiteout/trainer read `natural
  faint of the active linked <key>`, A2 reads `P+H: engine Perish KO in battle with no input
  (command)` or `(trainer)` — then the row's own exit 0 / `<scenario>: PASS` summary line and
  `PYDEC: PASS asserted scenario facts`.
- **Known FAIL record**: `ph_linked_faint_active_whiteout_gen3_fr_as_a_b0483efe.txt` is a FAIL
  (`RESULT_LINE b: RESULT: FAIL (scenario error: table: …)`) — an instrument/carrier problem (an
  incidental wild battle during the post-deposit walk), not a product defect; the fix (W2, flee
  incidental battles on a one-mon walk) landed in `28e48c9c`, and the re-run at that cut PASSes. Keep
  both files; do not cite the FAIL as a PASS.
- **Wall-clock**: budget 1800 s per row (`duo_budget`, `:107-117`).
- Owner ruling (d) signs D1–D5/N3/U3 as limits, so no doubles/target/Safari invocation is owed.

## 6. Item 3 — the full FRLG probe, both titles (the bw rows included)

Exact invocation, copied from `checkpoint_fr_clean_c4probe2_2026-09-23.txt:7` (LG variant `:7` of its file):

```
SLINK_GEN3_CHECKPOINT=<lane>/data/games/gen3_frlg/write_checkpoint.json \
SLINK_GEN3_TITLE=firered SLINK_GEN3_KIND=clean \
python tools/run_gate.py lua/tests/probe_gen3_checkpoint.lua \
  --rom "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba" --timeout 1200
```
with the lane env the receipt also records:
```
SLINK_STATE_DIR=<lane>/patch/build/gen3_probe_states_c4p2/firered
SLINK_CHECKPOINT_ROWS=script_running,battle_input_wild,battle_input_trainer,battle_move_menu,battle_animation,battle_faint_prompt,battle_intro,battle_over,battle_commit_state3,native_absent,sound_driver
```
Repeat for `SLINK_GEN3_TITLE=leafgreen` with the LeafGreen ROM/staged copy and its state dir.
Notes:
- The row list must contain the **bw rows** for the 2b pass (`bw_n1_action_draw`, `bw_n4_bag`,
  `bw_n5_party`, `bw_n6_summary`, `bw_n7_switch`, `bw_n9_run`, `bw_u1_oldman`, `bw_u2_pokedude`,
  `bw_n8_item` — `lua/tests/probe_gen3_checkpoint.lua:171-211`); they are FRLG-only states.
- The bw rows additionally need `SLINK_BW_HASHES=<json>` and the tutorial states (§1.2). The JSON
  shape is documented by the probe itself (`lua/tests/probe_gen3_checkpoint.lua:5-10`): top level
  `pack` and `source`, and `states["<state file basename>"] = {"state": …, "fixture": …,
  "prep": "<normal-input preparation receipt>"}`, read by `P.bw_meta` (`:484-497`); the ROM hash is
  read at runtime from `gameinfo.getromhash()`. **No producer for this file exists in the tree**
  — the live bw lane supplied it ad hoc; see UNKNOWN.
- **Receipt**: `docs/gen3/probes/checkpoint_{fr,lg}_clean_c4probe2_2026-09-23.txt`, header pattern
  `# probe_gen3_checkpoint.lua title=… kind=clean lane=<sha> tracked_clean=True`, then `# script=`,
  `# rom=`, `# SLINK_STATE_DIR=`, `# SLINK_CHECKPOINT_ROWS=`, `# states:`, `# invocation:`.
  (`tracked_clean`/`lane` are written by a wrapper not present in this tree — see UNKNOWN.)
- **PASS line**: `RESULT: PASS all checkpoint controls`, with per-row `PROBE <name> PASS` and the
  count the draft records (22 rows per title: 18 PASS + 4 not-selected SKIP, 0 FAIL). For the bw
  rows specifically: `BWROW bw_<row> PASS samples=… windows=… terminals=… admitted=0 misattributed=0`,
  and `BWSAMPLE bw_<row> …` receipts per row, which now also carry `party_count`, `slot1_hp`,
  `slot1_usable` and `keys=` (`fbfae6fa`, which replaced the bw taps with `P.press`: every press
  waits for `gMain.heldKeys` to read released → pressed → released, i.e. a real JOY_NEW edge).
  `bw_n7_switch` was UNREACHED on the lane (`0b37e14d` found the cause: the popup A and the SHIFT A
  were one held press) and is expected UNREACHED until a post-fix lane run confirms it — treat it as
  an open row, not a PASS.
- **Wall-clock**: the receipt shows no measured time; the budget is `--timeout 1200` s per title, and
  the nine bw rows add ≤ ~20k frames (`ffceb394` raised the probe budget to 90k).

## 7. §3.2 — the ten save rows

Runnable now, as two scenarios plus one witness env:

Rows 1/9 (START save + dismissal + the saved-fixture dialog witness) and 10 (positive recovery):
```
python tools/e2e_duo.py --game gen3_frlg --scenario save_then_write_gen3
python tools/e2e_duo.py --game gen3_lgfr  --scenario save_then_write_gen3
```
Rows 3/6 (script/Cable Club save refusal; the cable-callback limit form) — the same two runs of
`center_controls_gen3` from §4 produce them.

- **Receipts**: `save_then_write_{fr,lg}_as_a_b261d045_2026-09-23.txt`
  (`…_c4saverows_…` at lane `0feb9383`), `center_controls_{fr,lg}_as_a_c4saverows_2026-09-23.txt`.
- **PASS line**: `[duo] save_then_write_gen3: a=PASS b=PASS`, `PYDEC: PASS asserted scenario facts`,
  and the markers the draft quotes: `SAVE_DISMISSAL by=a_press`, `DIALOG_WITNESS_FALSE` off SAVE,
  `SAVE_CANCEL_WRITE_FRAME … field_free=true start_menu_task=false`, `CONTROL_REFUSED cable_save …
  clause=field_controls_locked held_frames=600 attempted=0 writes=0 bytes=unchanged`,
  `CABLE_CALLBACK_NULL limit=no-cable-partner`.
- **Wall-clock**: budgets 1200 s / 2400 s.
- Rows 2, 4, 5, 7, 8 are recorded limits with their reasons (draft §3.2) — no invocation owed; a
  limit is signed, not run.

## 8. Item 4 — cold-boot admission 8/8

Eight runs: two titles × two fixtures (town/battle) × two sides (a/b). The receipt's own seeding and
gate lines (`bootcheck_frlg_rehearsal_keys_2026-09-23.txt:3-6`) show the driver:
```
python tools/gen3_fixtures.py boot-check \
  --rom patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba \
  --fixture tests/fixtures/gen3/firered_party_battle.sav --title firered
```
(`boot-check` flags: `--rom/--fixture/--rr/--title/--saveram-name/--timeout`,
`tools/gen3_fixtures.py:887-897`.) Repeat per title and per fixture; the harness copies each fixture
into a disposable SaveRAM dir and launches its own config and `lua/tests/gen3_boot_check.lua`
(receipt line `[gate] E:/Howard/Bizhawk/EmuHawk.exe --config=patch/build/gate_cfg_gen3_boot_check.ini
--lua=lua/tests/gen3_boot_check.lua …`).
- **Receipt**: `docs/gen3/probes/bootcheck_frlg_rehearsal_keys_2026-09-23.txt`.
- **PASS line**: `[gate] gen3_boot_check: RESULT: PASS counter N -> N+1  (Ns)` per run, then the
  `RESULT: PASS counter …` echo; the rehearsal's claim is **8/8** with the PID:OTID key oracle.
- **Wall-clock**: ~6–7 s per run (receipt) ⇒ ~1 min for all eight.

## 9. Item 5 — pinned zip, `check_release_zip`, boot

```
python tools/make_release.py --version <v> --out <dir>          # build the zip (REHEARSED)
python tools/check_release_zip.py <zip> --rev <frozen cut>      # the hygiene gate
```
(`tools/make_release.py:530-544`; `tools/check_release_zip.py:224-228`.) The rehearsal's correction
(`release_zip_boot_fr_rehearsal_2026-09-23.txt:1-4`) is the reason for `--rev`: the export that was
booted was an unpinned `git archive HEAD`, so the tool PASSES it at `--rev 99c70d9c` and FAILS it at
`a0657c20`; the final zip must be built **from the frozen cut** and checked at that rev.
- **Receipt**: `docs/gen3/probes/release_zip_boot_fr_rehearsal_2026-09-23.txt`.
- **PASS line**: `… tools/check_release_zip.py PASSES it at --rev <cut> (85 members == blobs, 23/23
  closure)`, then boot evidence: the extracted `slink_lua.log` line
  `[SLink-gen3] gen3_frlg/firered (clean by hash) player a -> 127.0.0.1:<port>` and `TCP connected`.
- **Boot step**: **UNKNOWN command** — the rehearsal used a temporary config plus a bootstrap Lua
  that sets `SLINK_HOST/PORT/PLAYER`, taps A for 300–1500 frames and dofiles `<extract>/lua/slink.lua`,
  with `python -m server.server` from the same export (receipt's own prose). No tool in the tree
  performs it.
- **Wall-clock**: not measured in the receipt.

## 10. Item 6 — route-differential per owner ruling (a)

Ruling (a) (`dd42cde6`, §6 items 10-13): take `44bf25d6` into the cut (landed as `48709f39`), and
judge the Gen 1 command-ordering case and the legacy Gen 2 failure by **route-differential evidence
against master's baseline** — `3941198c` stays with the post-G4 convergence card
(`docs/gen3/research/item6_integration_feasibility_2026-09-23.md`).

The Gen 1 SFX gate at the cut is the Gen 1 `live-gates` lane:
```
SLINK_LIVE=1 python -m pytest tests/live/test_gen1_gates.py -q -p no:randomly -rs
```
(`tools/verify_gen1_release.py:114-117`; the SFX matrix is `test_gen1_sfx_matrix`, which writes its
own receipt `tests/fixtures/gen1/receipts/test_gen1_sfx_gate_{red,blue}_{town,battle}_result.txt` —
`tests/live/test_gen1_gates.py:105-131`. Its battle half needs
`python tools/gen1_fixtures.py <rom> battle` first, per the test's own skip message.)
- **PASS line**: the pytest run is green; per receipt, the gate's own `RESULT: PASS` (the fixture
  receipts are the shipped evidence, re-pinned by `48709f39`).
- The **baseline side** of the differential (the same lanes at `master`, and the Gen 2 duo at both):
  the vehicles are `python tools/e2e_duo.py --game gen1_new --scenario <gen1 scenario>` and
  `--game gen2 --scenario <gen2 scenario>`, plus `python tools/verify_gen1_release.py`. **The exact
  differential procedure/command is UNKNOWN** — no script or doc in the tree names one, and the
  draft's own count is "34 invocations" for the item as written (`item6_integration_feasibility…`
  §4). Settle it by asking which lanes must be green at the cut *and* at master, then diffing the two
  pytest summaries; do not run 34 blind invocations.
- **Wall-clock**: UNKNOWN.

## 11. The single mechanical pass (when the frozen cut is ready)

**One command** (card G4-FINALCUT-RUNNER):
```
python tools/gen3_final_cut.py --cut <frozen cut>              # the whole pass, sequential, one lane
python tools/gen3_final_cut.py --cut <frozen cut> --dry-run    # the full command plan, no emulator
python tools/gen3_final_cut.py --cut <frozen cut> --resume     # skip rows already PASSed at this cut
python tools/gen3_final_cut.py --cut <frozen cut> --rows 'item2b,zip_*' --stop-at 2026-09-25T06:00Z
python tools/gen3_final_cut.py --cut <frozen cut> --list       # the row ids
# fast mode (--carry / --shard / --merge-summary): below
```
It provisions `.claude/worktrees/gen3-lane-clean` (override `--lane`) detached at the cut — `git worktree add
--detach` if absent, else `checkout --detach`, with W3's `update-ref --no-deref HEAD` + `read-tree`/`checkout-index`
fallbacks for the broken shared ref — and aborts before any row unless `git status --porcelain --untracked-files=no`
is empty (a lane that is already tracked-dirty is never touched). It copies the §0.3 gitignored inputs it lacks from
the main checkout (root dumps, the staged `patch/build/gen3_*` copies, the Gen 1/Gen 2 inputs item 6 needs; no
`.cache` item is read by any row). Then it runs **41 rows** in runbook order: §1 builds (6), §2-§3 FRLG scenarios (5:
faint_cmd, link, boxsync, reconnect, deadzone), §4 whiteout + center_controls × FR/LG-as-A (4), §5 the P+H rows
`linked_faint_active{,_whiteout,_trainer}_gen3` and `active_end_gen3` × FR/LG-as-A (8; they supersede the A1/A2 hold
rows and T2, `G4_request_draft.md` @ `4aaaee7e`), §6 the probe × 2 titles (through `gen3_probe_receipt.py`, which runs
`gen3_bw_hashes.py` first), §7 save_then_write × 2, §8 boot-check 8/8, §9 zip build/check/boot (3), §10 item 6 (1),
§11 `verify_gen3_release.py --quick` and the `probe-gates` lane (2).

Rules it enforces itself: one retry only for a failure classified as a CPU-contention timeout (a harness timeout with
no failing verdict in the output), never for a real failure; a FAIL receipt at the same cut blocks that row on later
invocations too (move the receipt aside to re-run it deliberately); it kills only the process tree of a child it
launched (`taskkill /PID <child> /T`), never by image name; every BizHawk config a row wrote under the lane's
`patch/build` is read back and rewind-on fails the row; a SKIP fails unless `ALLOWED_SKIPS` names the row with an
owner ruling (today only RR R5, ruling 20, and no RR row is in the plan); a row that leaves the lane tracked-dirty
fails and aborts the pass.

**Receipts**: `docs/gen3/probes/fc_<row>_<cut8>.txt` per row (header by `gen3_probe_receipt.run_receipt_text`: row,
item, cut, lane, command, env, verdict, then per attempt the LOAD snapshot, start/end UTC, tracked_clean before/after,
the output verbatim, exit and classification), the probe's own `checkpoint_{fr,lg}_clean_<cut8>.txt`, and the summary
table `fc_SUMMARY_<cut8>.txt` (rewritten after every row; `OVERALL: PASS` only when every selected row PASSed or was
an allowed SKIP). Exit 0 = PASS, 1 = a row failed, 2 = aborted (lane).

**Fast mode** (card G4-FINALCUT-FAST, owner-approved synthetic evidence):
```
python tools/gen3_final_cut.py --cut <cut> --carry --dry-run                         # RUN vs CARRY, est. minutes
python tools/gen3_final_cut.py --cut <cut> --carry --shard 1/2 --lane <gen3-lane-clean>
python tools/gen3_final_cut.py --cut <cut> --carry --shard 2/2 --lane <gen3-lane-2>
python tools/gen3_final_cut.py --cut <cut> --merge-summary                           # one fc_SUMMARY_<cut8>.txt
```
`--carry`: a row is CARRIED, not run, when a PASS receipt for the same row+orientation exists at a cut X
(`fc_*`, `ph_*`, and the older duo/center/save/checkpoint receipts that name a single cut sha) and
`git diff --name-only X <cut>` touches none of the row's dependency globs (`row_deps` in the runner:
the client closure `lua/*.lua`, `lua/gen3/**`, `lua/core/**`, the `gen3_frlg` pack, the harness tools and
`lua/tests/gen3_*.lua`, `server/**`, `tools/e2e_duo.py`, `duo_gen3_main.lua` plus the row's own carrier,
and the FRLG party fixtures; conservative by design). Its receipt says `CARRIED from <receipt> @X; diff X..cut
touches no dependency (list checked)` and lists the checked globs and the diff. Builds, the zip rows and the
source gate are never carried; item 6 carries only while `master` has not moved. `--shard i/n` splits the RUN
rows deterministically (longest first by receipt history, else budget); shard 1 also writes the CARRIED
receipts; each shard writes `fc_SUMMARY_<cut8>_shard<i>of<n>.txt`, and `--merge-summary` builds the one summary
from every row's receipt (RUN / CARRIED / FAIL counted separately; a row with no receipt is NOT RUN = FAIL).

`python tools/verify_gen3_release.py` (all lanes) stays the release gate's own entry point; the runner runs its
`--quick` source lanes and its `probe-gates` lane, and replaces its `duo-pairs-gen3` pytest lane with the per-scenario
rows above so each scenario gets its own receipt.

---

## 12. UNKNOWN / not found in the tree — status after G4-FINALCUT-RUNNER

1. **Lane provisioning** (§0.1): **CLOSED** — `tools/gen3_final_cut.py` `provision()`/`copy_inputs()` (§11).
2. **`SLINK_BW_HASHES` producer** (§6): **CLOSED** — `tools/gen3_bw_hashes.py` (`587453bf`) hashes the pack, the lane
   sha and the four bw states the §1 builds produce; `gen3_probe_receipt.py` runs it before each bw probe, and the
   runner runs the §1 builds first. (Its per-state `prep` strings are fixed text naming the builder tools, not the
   runner's build receipts.)
3. **Probe receipt wrapper** (§6): **CLOSED** — `tools/gen3_probe_receipt.py` (`587453bf`) writes the
   `# probe…lane=… tracked_clean=…` header; every other row's header is its `run_receipt_text`.
4. **Item 5's zip-boot step** (§9): **CLOSED** — `python tools/gen3_final_cut.py zip-boot --zip <zip> --lane <lane>`
   extracts to a space-free temp dir, seeds `firered_party_town.sav`, writes a rewind-off config, runs the cut's
   `python -m server.server` from the lane, taps A through CONTINUE and dofiles the extracted `lua/slink.lua`; PASS on
   `[SLink-gen3] gen3_frlg/firered (clean by hash) player a`, `TCP connected` and the server's `hello rom=firered`.
   The zip itself is `make_release.py --version g4-<cut8> --skip-generators` from the lane (the cut's committed data
   ships) and `check_release_zip.py --rev <cut>`.
5. **Item 6's baseline differential** (§10): **CLOSED** — `python tools/gen3_final_cut.py item6 --branch <lane>
   --master <tree>` runs the three cases of `item6_route_diff_{master,branch}_2026-09-24.txt` paired back to back
   (the `3941198c` ordering test as an untracked scratch file, the Gen 1 SFX town gate with its tracked receipts
   restored, the legacy Gen 2 duo × 3) and fails only on a regression (master PASS, branch FAIL). Item 6 is already
   DONE at `b0483efe`; the row re-takes it at the final cut.
6. **T2/A2 receipt names and PASS lines** (§5): **SUPERSEDED** — mechanism P+H replaced the hold rows; the runner's
   §5 rows are `fc_{linked_faint_active,active_end,linked_faint_active_whiteout,linked_faint_active_trainer}_gen3_{fr,lg}_as_a_<cut8>.txt`,
   PASS = `e2e_duo.py` exit 0 (`<scenario>: PASS` in the summary, `PYDEC: PASS asserted scenario facts`).
7. **`--game` help text** is stale in `tools/e2e_duo.py` (it lists only `gen3_rr`, `gen1`, `gen2` while the real keys
   are `gen3_rr, gen1_new, gen1_pure, gen1_pure_overlay, gen1_pure_green, gen2, gen3_frlg, gen3_lgfr, gen3_rr_new`).
   Still open (e2e_duo is not this card's file); use the keys, ignore the help.
