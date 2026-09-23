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

**A1 (FR active hold) — runnable now**, via LG-as-A so FR is the forced side:
```
python tools/e2e_duo.py --game gen3_lgfr --scenario linked_faint_active_gen3
```
- **Receipt**: `linked_faint_active_fr_forced_b261d045_2026-09-23.txt` (+ the earlier
  `duo_frlg_linked_faint_active_gen3_clean_*`).
- **PASS line**: both `RESULT_LINE` lines PASS (`a: RESULT: PASS (natural faint of the active linked
  BC73F9B0:1C600D89)`, `b: RESULT: PASS (held while active; HP 0 in battle once switched out)`), then
  `linked_faint_active_gen3: PASS (attempt 1 of 1)`.
- **Wall-clock**: budget 1800 s.

**T2 (trainer bench write) and A2 (active hold until battle end) — PENDING 2B-INTEGRATE-DUO.** The
carriers exist in the runner (`trainer_bench_gen3`, `active_end_gen3`, `tools/e2e_duo.py:61-68`,
`scenario_attempt_limit` gives trainer_bench two attempts, `tools/e2e_duo.py:517-526`) but were not
registered in the wrappers when this runbook was written, so the commands are placeholders:
```
python tools/e2e_duo.py --game gen3_frlg --scenario trainer_bench_gen3   # T2 — PENDING
python tools/e2e_duo.py --game gen3_frlg --scenario active_end_gen3      # A2 — PENDING
```
- **Receipt**: to be named by the integration card; expect `duo_frlg_trainer_bench_gen3_*` /
  `duo_frlg_active_end_gen3_*` by the existing pattern. Add `SLINK_E2E=1 pytest tests/e2e/test_duo_gen3.py`
  coverage only once the card registers them.
- **PASS line**: UNKNOWN until the card lands (the carriers' markers are not yet in any receipt).
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

```
python tools/verify_gen3_release.py            # every lane; --quick stops before the emulator lanes
python tools/verify_gen3_release.py --list     # show the lanes
```
Lanes (`tools/verify_gen3_release.py:49-71`): `unit` (every `tests/unit/test_gen3_*.py` plus
conformance and the wire-log/verify tests), `lua-parse`, `pins` (`tools/gen3_pins.py --json`),
`profile-generated` (`--check`), `probe-gates`
(`SLINK_LIVE=1 pytest tests/live/test_gen3_probe_gates.py`, the P1 hook-probe matrix — a different
row family from item 3's checkpoint probe), `duo-pairs-gen3`
(`SLINK_E2E=1 SLINK_LIVE=1 pytest tests/e2e/test_duo_gen3.py`). Fail-closed: a lane that did not run
did not pass, and a skip is a failure unless its reason is on `ALLOWED_SKIPS`.
This is the mechanical pass for items 1-3; items 4/5/6 and the §3.2 rows are the invocations above.
**Receipt**: this gate prints a per-lane verdict and a final verdict; no committed receipt pattern
exists in `docs/gen3/probes/` yet — capture it beside the cut.

---

## 12. UNKNOWN / not found in the tree

1. **Lane provisioning** (§0.1): no command creates `.claude/worktrees/gen3-lane-clean`; the receipts
   only record its sha and `tracked_clean=True`.
2. **`SLINK_BW_HASHES` producer** (§6): the probe reads a JSON with `pack`, `source` and per-state
   `{fixture, prep, state}`; nothing in `tools/` writes it (`grep -rn SLINK_BW_HASHES` matches only
   `lua/tests/probe_gen3_checkpoint.lua`). The last live bw lane supplied it ad hoc. It needs a small
   writer (hash the pack, the source rev and each built state) before the bw rows can be re-taken
   reproducibly.
3. **Probe receipt wrapper** (§6): the `# probe…lane=… tracked_clean=True` header is written by a
   wrapper that is not in this repo (`grep -rn tracked_clean` over tools/tests is empty).
4. **Item 5's zip-boot step** (§9): described in prose in the rehearsal receipt; no tool.
5. **Item 6's baseline differential** (§10): no script, no documented command.
6. **T2/A2 receipt names and PASS lines** (§5): pending 2B-INTEGRATE-DUO.
7. **`--game` help text** is stale in `tools/e2e_duo.py:6274-6276` (it lists only `gen3_rr`, `gen1`,
   `gen2` while the real keys are `gen3_rr, gen1_new, gen1_pure, gen1_pure_overlay, gen1_pure_green,
   gen2, gen3_frlg, gen3_lgfr, gen3_rr_new`). Use the keys, ignore the help.
