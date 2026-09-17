# Gen 1 master release — resume note (2026-09-17 ~22:30Z, owner break)

Read this first after a context reset or harness restart. The ledger `docs/gen1_requirements.md`
is the authority on evidence; this note is the working state around it. Plan (owner-approved,
v3.9): `C:\Users\howar\.claude\plans\system-reminder-you-are-operating-gleaming-pretzel.md`. The
standing worker contract every card brief points at is `docs/agents/worker_card.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279`, branch
  `claude/gen1-master-release-plan-6b4279` = master `d2c30fb` + ~135 commits. HEAD `471529b` at
  the time of writing. Untracked `tools/e2e_duo_head.py` = frozen copy of the harness for lane
  runs while OMP leases `tools/e2e_duo.py` (refresh with `git show HEAD:tools/e2e_duo.py >
  tools/e2e_duo_head.py` before each run; delete when OMP is done).
- Uncommitted on the lane tree: `tools/e2e_duo.py` = OMP's card H-1 in progress (see Workers).
- Workers: Codex capped until 2026-09-19 07:34. OMP live `Gen1 Peer 2` (pid 25980, cwd repo
  root; name it explicitly). Live Union Alpha session: address it by its FULL id
  `01a0b05f-22eb-7702-8c70-e000a2dca0d8` (its display name and pid do not route). Headless
  `openrouter/stealth/union-alpha` no longer blocks (owner repaired the bridge; a request returns
  `running` at once and the reply arrives as a cross-session message). Peer replies that miss the
  session land in the bridge mailbox: read with
  `node "E:/Howard/ClaudEx/bin/magi.mjs" exchange <task_id>`; every reply needs a recorded
  `outcome` before the next request (RECONCILE_FIRST). Corrections to a running DELEGATE go as
  `kind: note` (a `reply` from the orchestrator is a ROLE_VIOLATION).
- Lua/driver/client/server workers edit a SCRATCH COPY of HEAD (`git archive HEAD | tar -x` into
  the session scratchpad) and deliver `git diff --no-index --src-prefix= --dst-prefix=` patches;
  the coordinator applies them (`git apply -p1`, or `-p0` when the patch paths are repo-relative;
  a NEW file needs a proper `/dev/null` new-file diff or a plain copy). Shared-module patches
  (`server/`) go through the `slink-adapter-guard` agent before commit. One emulator lane; a
  subagent may hold it with a bounded run count. No duo run on a tree that differs from HEAD.
- Owner rulings today: HUD/GUI text drawn with `gui.drawText` must be cleared explicitly
  (`gui.clearGraphics`/`gui.cleartext`) — fixed in 9826465; the shared runtime defines the
  standard and Gen 3 conforms to it later (no Gen 3 accommodations in shared code).
- Checkpoint (hook contract): `gen1-rby-code-sweep-8d06e2/docs/gen1_reference/RC_MASTER_GUIDE.md`
  worker `master-release-lane` + `WORKTREE_REGISTER.md`; refreshed by
  `gen1-rby-code-sweep-8d06e2/docs/gen1_reference/refresh_master_lane_checkpoint.py`
  (args: state, files-json, next_action, live_lane, head, register-note).

## Live results today (receipts under `tests/fixtures/gen1/receipts/`, committed)

| Scenario | Result | Rows | Commit |
|---|---|---|---|
| `linked_faint_active_new` | PASS (attempt 2; `LOOP_HEAD_WRITE … hp_before=5`; first S-7 witness dumps, byte-identical to the flushed saves) | W-2, S-7 partial | 764bab7 |
| `type_clause_new` | PASS first run | D-5 type half | 854cd35 |
| `changebox_new` | PASS first run | W-5 box change, D-3 | d065ab5 |
| `trade_decline_new` | PASS after the rendezvous fix | T-3/T-4 decline half | 67185fd |
| `species_clause_new` | attempt 1 PASS (reroll not met); attempt 2 reroll OBSERVED then the second RUN stuck | D-4 partial | 44c92e5 |
| Yellow lab gate | 1 passed | S-1 Yellow half | b908bfd (log receipt) |
| `soft_reset_new` | clients PASS, oracle byte-compared links.json that re-ordered after the re-hello | — (H-1b) | evidence `scratchpad/soft_reset_run/` |
| `whiteout_new` | run 1 no party_to_box (client latch, FIXED 43de809); run 2 Growl loop stalled (FIXED 07c15ee); run 3 wild battle on the walk back (OPEN, WO-2) | — | evidence `scratchpad/whiteout_run{2,3}/` |
| `pc_ops_new` | deposit OK, WITHDRAW misread as RELEASE_SEEN (client r2/r3 in flight) | — | evidence `scratchpad/pc_ops_run/` |
| `poison_new` | walk to the forest OK; RUN stuck (driver FIXED 471529b, rerun pending) | — | evidence `scratchpad/poison_run/` |
| `explode_new` | attempt 2: Explode Mode chain on B complete (LOOP_HEAD_EXPLODE, self-KO) then post-faint stall (EX-1 in flight) | — | evidence `scratchpad/explode_run/` |

## Fixes committed today (each reviewed or fact-checked independently)

90ca378 whiteout Python · b2f29f8 three bodies (F-1 free-cancel faint, A4, A7) · f79ebaa/99bb312/
77f1c8c/8132547/b908bfd ledger cells · 27aaf23 clause/poison Python · d27387a + 6223571 S-7 witness
dump + validated-fire gate + hp_before witness · 1a205c3 Yellow lab driver + yellow_town ·
2492554 parcel stray-box fix + yellow_battle (LEGACY empty) · 43de809 client echo-guard aged
(superseded by r2/r3 in flight) · 0dcf5c7 clause/poison Lua fix-ups · 052cf62 A13 rival body +
Route 22 driver · 629e75d trade rendezvous · 9826465 HUD surface clear · 1093ee7 S-7 runner check
+ r2 harness fix-ups (explode delegate keyword, species release gate → GameRngMiss, wrapper
deadline/fixtures) · 07c15ee Growl-loop B taps · 99099ad Yellow driver review fix-ups · 471529b
battle-driver RUN re-press.

## In flight / ready to integrate (check the scratchpad first)

Scratchpad: `C:/Users/howar/AppData/Local/Temp/claude/E--Google-Drive-SLink--claude-worktrees-gen1-master-release-plan-6b4279/e136b7e5-2160-411d-b1cf-7b538efc4203/scratchpad/`

| Card | State | Where |
|---|---|---|
| SV-1 r2 server in-flight sync commands (`_arm_inflight` at the drain, `_expire_inflight` in the reconciler, 6 passes) | patch ready, adapter-guard re-review running | `sv1_party_mon_r2.patch` (apply `-p1`); round-1 guard said fix-first on the ageing unit only |
| PC-1 r3 client: no per-key echo mark; withdraw/release by snapshot membership; nil snapshot → `STORAGE_CLASSIFICATION_UNAVAILABLE`; corrected trade test | Opus working (agent a66d735…) | will be `pc1_client_r3.patch`; r2 review (cx-4303e4ae) accepted with 4 fix-ups |
| EX-1 explode post-faint stall (B_ACTIVE_COMMIT timeout after the self-KO; likely a blocking text with no button) | Opus working | `wt-ex1/`, `explode_run/` |
| H-1 harness: waits end on client RESULT (`ClientFinishedEarly`), soft-reset canonical compare + `links_baseline.json`, type-clause `unresolve_area == route_1`, poison links-empty + no RX rebuild/memorialize, `SLINK_DUO.timeout_secs`, `unexpected-battle` FINAL pin | OMP working on `tools/e2e_duo.py` (cx-1ec77dde) | reply may be in the mailbox |
| A13-py rival_swap_new registry/oracle | OMP queued (cx-095053d0) | after H-1 |
| WO-2 whiteout walk back hits grass at Route 1 (12,24) | NOT dispatched | `walk_back_to_route1` needs incidental-battle RUN handling (reuse the forest walk's escape path) |
| SV-2 server trade watchdog abandons a confirming trade silently (`state.py:491-507`) | NOT dispatched | product defect from T-1 |
| Client comment fix `client.lua:335-336` (core.asm:6689-6690) | NOT dispatched | from A13 |

## Lane queue after the break (in order)

1. Integrate SV-1 r2 (guard verdict), PC-1 r3 (+ headless review), EX-1, H-1 (+ A13-py); commit
   each; refresh `tools/e2e_duo_head.py`.
2. Reruns: `poison_new` (driver fix in), `species_clause_new` (3 attempts), `pc_ops_new` (after
   PC-1 r3), `whiteout_new` (after WO-2), `explode_new` (after EX-1), `soft_reset_new` (after
   H-1b); then `rival_swap_new` first run (after A13-py; A on the battle fixture).
3. A9 dashboard snapshots during a link_new-family run; A12 full `duo-pairs` pass; ledger pass
   (S-6 PC ops, D-4 completion, S-7 runner line, limits list: silent force-faint demotion, symmetric
   duplicate-key ceiling, trade watchdog); Track B; owner tag `v0.3.0`.

## Commands

```bash
python -m pytest tests/unit -q -p no:cacheprovider          # 3084 passed at 1093ee7 (OMP)
ruff check . && python tools/lua_syntax_check.py
python tools/e2e_duo_head.py --game gen1_new --scenario <name> --keep-data
python tools/gen1_fixtures.py --qualify                     # all seven fixtures OK
node "E:/Howard/ClaudEx/bin/magi.mjs" exchange <task_id>    # read a peer reply from the mailbox
```
