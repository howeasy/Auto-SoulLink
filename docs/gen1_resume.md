# Gen 1 master release — resume note (2026-09-17 ~19:00Z, harness restart for the Magi repair)

Read this first after a context reset or harness restart. The ledger `docs/gen1_requirements.md`
is the authority on evidence; this note is the working state around it. Plan (owner-approved,
v3.9): `C:\Users\howar\.claude\plans\system-reminder-you-are-operating-gleaming-pretzel.md`. The
standing worker contract every card brief points at is `docs/agents/worker_card.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279`, branch
  `claude/gen1-master-release-plan-6b4279` = master `d2c30fb` + ~118 commits. HEAD `1a205c3` at
  the time of writing (see the commit list below). Untracked `tools/e2e_duo_head.py` is a frozen
  copy of the harness for lane runs while OMP leases `tools/e2e_duo.py`; delete it when OMP is
  done with that file.
- Workers: Codex capped until 2026-09-19 07:34. OMP live `Gen1 Peer 2` (pid 25980, cwd repo
  root, purpose "Implement A6-py duo scenarios"; name it explicitly) takes harness/oracle cards
  with literal specs, never commits; a second live OMP session on Union Alpha (`01a0b05f-…`,
  purpose "ping") takes fact-checks; headless `openrouter/stealth/union-alpha` takes reviews
  (the owner repaired the Magi bridge so headless calls no longer block; until confirmed, route
  them through a background Sonnet relay subagent — see memory `feedback_no_blocking_peer_calls`).
  Opus subagents take Lua bodies/drivers/independent reviews, Sonnet takes docs/ledger/relays;
  the coordinator only orchestrates. Rules: no duo lane run while `lua/gen1/` or
  `lua/tests/duo/duo_gen1_main.lua` is leased on the lane tree (Lua workers now edit a SCRATCH
  COPY of HEAD under the session scratchpad and deliver `git diff --no-index` patches the
  coordinator applies with `git apply -p1`); one emulator lane, lent to a subagent only with a
  bounded run count; every peer reply gets a recorded `outcome` before the next request
  (the bridge refuses new requests otherwise: RECONCILE_FIRST); the coordinator cannot `reply`
  to its own DELEGATE task — send corrections as `kind: note` to the peer.
- Checkpoint (hook contract): `gen1-rby-code-sweep-8d06e2/docs/gen1_reference/RC_MASTER_GUIDE.md`
  worker `master-release-lane` + `WORKTREE_REGISTER.md`; refreshed by
  `gen1-rby-code-sweep-8d06e2/docs/gen1_reference/refresh_master_lane_checkpoint.py`
  (args: state, files-json, next_action, live_lane, head, register-note).

## Committed this session (all reviewed or fact-checked independently)

| Commit | What | Review |
|---|---|---|
| 90ca378 | `whiteout_new` Python (registry, BOTH_BOXED gate on `/api/debug/raw_state` `_live.party_keys`, oracle) | headless union-alpha: no blocking defect; two low fixes on the OMP S-7-py card |
| b2f29f8 | three duo bodies: F-1 active-faint fix (free move-menu cancel to the loop head), A4 `type_clause_new`/`species_clause_new`, A7 `poison_new` | F-1: Opus review says FIX FIRST (below); A4/A7 regions: union-alpha review in flight |
| f79ebaa | ledger cells T-1/C-1/C-2/D-1 (fact-checked, narrowed) | union-alpha fact-check + coordinator git check |
| 27aaf23 | A4/A7 Python (registry, `A_PENDING` release gate, retry-on-PASS for the reroll branch, `saved_money`, per-instance `target`) | union-alpha review: 5 findings → OMP card r2 (queued) |
| d27387a | S-7 save-witness Lua dump inside the `SaveMenu.save+3` bus callback | Union Alpha fact-check: gate the dump on a VALIDATED fire (fix-up in flight) |
| 1a205c3 | Yellow lab driver first contact fixed (wJoyIgnore mask; script 11), `yellow_town` rebuilt clean and dropped from LEGACY | falsifier 43 screens; qualify sweep |

## Root causes found this session

- `linked_faint_active_new` run at 27a324b: the driver's real move commit (pad fix e95cefa) let
  the wild KO the 5/15-HP linked mon inside the turn; the client demoted the queued loop-head
  write to the checkpoint and dropped it (`client.lua:754-756`, silent, no NACK — product
  finding for the ledger limits list). The old PASS receipt came from a driver that pressed
  nothing. Fix b2f29f8 + the pending `hp_before` guard.
- Yellow lab route: two Yellow script states run with `wJoyIgnore = 0`; the R/B-derived
  `== $FC` test never matched (1a205c3). `yellow_battle` still LEGACY: the shared parcel driver's
  unbounded `unexpected-menu` guard (`gen1_rb_parcel_inputs.lua:114-117`) deadlocks after the
  Viridian Mart handover on Yellow (card Y-2).
- Harness: `assert_explode_saved` delegates to `assert_linked_faint_saved(active=True)` which
  requires `RX force_faint`/`LOOP_HEAD_WRITE`, then asserts them absent → `explode_new` cannot
  pass its oracle (finding 6 on OMP card r2).

## In flight at the restart (re-dispatch what did not report; OMP cards survive)

| Worker | Card | Lease | Deliverable |
|---|---|---|---|
| Opus (lane tree) | S-7 dump gate on validated fire + F-1 `hp_before` guard + comment fixes | `lua/tests/duo/duo_gen1_main.lua` | edited file in the tree; commit after lua_syntax_check |
| Opus (emulator) | Y-2 parcel-driver deadlock, rebuild `yellow_battle`, one Red non-writing smoke | `lua/tests/gen1_rb_parcel_inputs.lua`, `gen1_rb_mart_signature.lua`, its test, `yellow_battle.SaveRAM` | logs `scratchpad/y2_run<k>.log`; then drop `yellow_battle` from the LEGACY sets (`tools/gen1_fixtures.py:56-62`, `tests/unit/test_gen1_stat_control.py:37`, `tests/unit/test_gen1_fixture_qualify.py:28-30`) |
| Sonnet relay | union-alpha adversarial review of b2f29f8 regions A4/A7 | read-only | findings → fix-up card |
| OMP Gen1 Peer 2 | S-7-py (cx-e352942a): witness sha256 vs `saveram[0x498:0x8000]`, `SAVE_WITNESS_SHA256` PYDEC line, stale-file cleanup, + two A5 review fixes | `tools/e2e_duo.py`, `tests/unit/test_e2e_duo_whiteout.py`, new `test_e2e_duo_save_witness.py` | then r2 (cx-3e16820d): six findings on 27aaf23 |

Session scratchpad (patches, logs, scratch copies):
`C:/Users/howar/AppData/Local/Temp/claude/E--Google-Drive-SLink--claude-worktrees-gen1-master-release-plan-6b4279/e136b7e5-2160-411d-b1cf-7b538efc4203/scratchpad/`
(`f1_faint.patch`, `a4_clauses.patch`, `a7_poison.patch` are applied; `faint_run/` holds the
failed run's receipts; `lane_faint_active.log`, `yellow_*.log`, `y1_*.log`, `y2_*.log`).

## Lane queue (in order, after the fix-ups above are committed and the tree is unleased)

1. `linked_faint_active_new` via `tools/e2e_duo_head.py` (refresh the copy from HEAD first if
   OMP still holds `tools/e2e_duo.py`) — first exercise of the S-7 witness; replace the committed
   receipt `tests/fixtures/gen1/receipts/linked_faint_active_new_b_result.txt` (pre-pad-fix) on PASS.
2. `whiteout_new` (first run), then `type_clause_new` (deterministic), `poison_new`
   (RNG-retryable), `species_clause_new` (up to 3 attempts; NOT-observed line = D-4 stays ◐).
3. `soft_reset_new`, `trade_decline_new`, `explode_new` (after r2's oracle fix), `pc_ops_new`,
   `changebox_new`; diagnose every failure from its kept run dir (`--keep-data`) before a rerun.
4. Yellow lab gate once `yellow_battle` is rebuilt:
   `SLINK_LIVE=1 pytest tests/live/test_gen1_new_gates.py -k "new_game_lab_route and yellow"`.
5. A9 dashboard snapshots during a link_new-family run; A13 optional; then A12 full `duo-pairs`
   pass, ledger pass (incl. the client.lua:754 silent-downgrade limit and the S-7 row wording:
   sha256 of the raw 0x7B68 witness bytes, lower-case hex), Track B, tag `v0.3.0`.

## Commands

```bash
python -m pytest tests/unit -q -p no:cacheprovider          # 3056 passed at 27aaf23
ruff check . && python tools/lua_syntax_check.py
python tools/e2e_duo.py --game gen1_new --scenario <name> --keep-data
python tools/gen1_fixtures.py --qualify
```
