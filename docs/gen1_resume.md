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

## State at compaction (2026-09-17 ~23:55Z) — reconcile-only mode, no new dispatch

HEAD b94e2ad. Committed after the break note: d9225a1 server in-flight sync window · 1c3a324 client
storage classification (no echo mark) · 580b3f8 trade-watchdog notice · a7c0a00 ledger corrections ·
9176698 pc_drive `[%a_]+` op parser · 6c9f72c HUD drops cleartext + stronger test · e6aa7a4 explode
B-taps + fail-fast, species cap 8 + RNG phrase · b94e2ad D.run counter mandatory + recheck.

Still running (integrate on report, then stop): Opus DUO-1 (walk-back grass delegation, receptionist
mark after overworld_ok, drain the 40th Growl) → `duo1.patch`; Opus A13-r2 (client swap window: park
early reply, init timeout ≥ transition + $FF closing edge; Route 22 driver cursor/switch/KO) →
`a13r2.patch` (client change: needs a headless review before commit); Sonnet UI-1 (board stat labels
from capabilities) → `ui1.patch`; Sonnet PO-2 (forest PSN masking) → `po2.patch`; OMP H-1 (+ addenda
e–j) then A13-py — replies in the mailbox; headless P8-2/P8-3 deletions (cx-74f72d15).
Apply hints: patches carry three prefix styles — `git apply -p0` (repo-relative), `-p1`
(`wt-*-base/` prefix), `-p11` (absolute scratch paths); check with `--check` first.

Queue for the next session (from the reconciled reviews; all under `scratchpad/prep/`):
1. Land the in-flight patches above; commit H-1/A13-py from the tree once OMP reports.
2. Reruns in order: poison_new, species_clause_new (8 attempts), pc_ops_new, whiteout_new,
   explode_new, soft_reset_new, then rival_swap_new (after A13-r2 + A13-py). Retain the Yellow lab
   gate's own SIGNALS/PARTY_RAW output as the S-1 receipt (`-s` or the gate log).
3. explode_new is a coin flip while the hunt weakens catches to 1/3 HP: give it the RNG-retry
   classification (`EXPLOSION never executed`) or stop weakening below one Route 1 hit.
4. Docs patches to apply after `--check`: `protocol_md.patch`, `engine_sites.patch`,
   `citations.patch` (after A13-r2), `shared_runtime.md` draft, `RELEASE_NOTE_v0.3.0.md`,
   `REBASE_PLAN.md` (fill the git inventory: 3 master commits since d2c30fb).
5. Track B drafts: `P8-0_P8-1_isolation_launcher.md` (six Gen 1 identity branches in state.py;
   production launchers `lua/slink.lua:65`, `lua/slink_gen1.lua:18` still load the OLD client;
   `tools/make_release.py` manifests), `P8-2_P8-3_deletions_memory_gb.md` (pending),
   `P8-6_P8-7_gen3_package.md` (FF = fast-forward master; extracted-ZIP boot).
6. Smaller queued fixes: Yellow driver comments (script 9 = five texts, 11 = two before
   AddPartyMon); legacy clients render the HUD inside the protected handler (move after pcall);
   `harness_waits.patch` after H-1; `driver_dedup.patch` after the reruns pass; `A9_dashboard.md`
   + `gen1_board_snapshot.py` selftest before use; `LEDGER_drafts.md` cells as receipts land.

## Phase R1 (resumed 2026-09-17 ~20:00Z) — work mode again; owner: use union-alpha headless agents freely, validate everything

Commits this phase (all verified by the coordinator before commit, falsifiers rerun locally):
d9f95e7 PO-2 forest PSN masking · f453238 DUO-1 walk-back grass / receptionist mark / Growl drain ·
35d2745 H-1 harness (waits end on client RESULT, canonical soft-reset compare, species budget 8 + RNG
phrase, pc_ops active box, save-witness ordering) · 93a1602 + 5000ab4 SMALL-1 (Yellow comments,
tools/gen1_board_snapshot.py) · 5b30e20 whiteout_new receipts (PASS attempt 1 at f453238) ·
733cd59 EX-2 explode KO phrase · 77d1e91 HUD-3 legacy clients render after the pcall ·
ca17a26 P8-1 launchers load the new client + manifest closure.

Lane results: whiteout_new PASS (attempt 1, all new markers seen). poison_new: both clients PASS, oracle
FAILED on two dead-zone rows in links.json (legit no-catch dead zones; H-2 item k). pc_ops_new: both
clients PASS, oracle FAILED on `PC_FINAL ... init=true` vs receipt `init=false` (H-2 item n). Both runs
also reproduced the traceback-instead-of-summary shape (H-2 item l).

In flight: OMP A13-py then H-2 (k,l,m,n) in place on tools/e2e_duo.py; A13-r3 (Opus, fix-ups from
review cx-a00d4b8d: $FF closing-edge frame-boundary check, exactly-once write, measured window frames,
tests past 161 + staged expiry, KO slot attribution); P8-0 patch `p80.patch` (-p1; adapter guard PASS,
correctness review cx-ce9f92b9 pending; commit when the lane is idle); DOCS-1 patch; LANE-BOOT1 EmuHawk
boot smoke of ca17a26 through the Manager launcher shape (Opus). Then species_clause_new (8 attempts),
soft_reset_new, poison/pc_ops/explode reruns after H-2, rival_swap_new after A13-r3 + A13-py.
Union-alpha reviews accepted so far: PO-2 (cx-38bd0176), HUD placement (cx-27d06ce5 -> HUD-3),
explode analysis (cx-08436c96; its candidate-2 recommendation rejected on its own catch-rate math),
P8-1 fact-check (cx-21d6ae90) and review (cx-c4e4f53c).

### Phase R1, later stretch (2026-09-17 ~20:45Z)
Committed: e19fc68 A13-py rival scenario · 030b545 species receipts (PASS attempt 1, reroll observed; D-4 ✓) ·
0f49b06 ledger (D-7/S-7 ✓, S-4 ◐, D-4 ✓) · 9b87246 H-2 (dead-zone rows, FAIL summary + exit 1, explode KO
row + A consequence, pc_ops init=false + codec flag, soft-reset baseline quiescence) · 7d0dc23 A13-r2/r3/r4
client rebuild (parked early reply, RIVAL_INIT_FRAMES=240 / RIVAL_STAGED_FRAMES=60, at-most-once write,
RIVAL_WINDOW log; route22 forced replacement on wPlayerMonNumber) · 9aa7989 P8-2a legacy gates/probes retired.
Lane: soft_reset_new both clients PASS, oracle caught the mon_stats baseline race (H-2 p); explode_new KO
before Explosion twice -> EX-3 (Opus) tests the in-battle switch-in free-hit hypothesis; LANE-REG1 regression
sweep of the receipted scenarios running (link_new, deadzone_new done). In flight: OMP H-3 (harness-waits
audit reconcile, stale receipts, --list, item o rival oracle constants), P8-2b legacy unit-consumer migration
(Opus), P8-0 correctness review (re-dispatched cx-ce9f92b9 -> new task), EX-3.
Queue after those: reruns poison/pc_ops/soft_reset at the H-2 harness; explode after EX-3; rival_swap_new after
H-3(o); P8-2 step 3 (old duo scenarios + wrapper, OMP lease) then step 5 (old client/game deletion) then
memory_gb trim; HUD pixel proof with ScreenshotCaptureOsd; ledger R-2 control cite (test_gen1_stat_rebuild.lua
deleted) and the pc_ops/poison/soft_reset cells once receipts commit; driver_dedup.patch; citations.patch.

### Implementation mode (owner 2026-09-17 ~20:40Z: "stop worrying so much about tests and get implementing")
Standing gates only from here (unit suite, lua_syntax_check, ruff, lane runs); no review rounds or per-patch falsifiers.
Committed: eef6a1c P8-0 native_trade_ui · 1d710ac ledger R-2 cite · 042a79e client citation comments · 832d499 EX-4
nurse heal before explode (+ H-4 deletions in its index) · 2395145 H-3/H-4 harness + old duo titles · 03fc7dc P8-6a docs ·
8245e1c P8-2b legacy unit migration · b3481dd P8-4a tooling cutover · 21ff0d7 P8-4b old client/game deleted ·
9969845 P8-5 memory_gb trimmed to Gen 2. Track B P8-0..P8-5 are implemented; P8-6 first pass done; P8-7 pending.
Feature retirement to note for the owner: the Lua-side Archipelago WRAM-relocation profile (red_ap/blue_ap Lua
addresses, detect_archipelago) left with the old client and the AP gate; server-side red_ap/blue_ap routing stays.
Package: `make_release.py` ZIP carries the new client closure; dispatch test 8/8 from the extracted tree (PKG-1).
Lane: LANE-REG1 sweep passed link/deadzone/ball_gate/type_clause; the other six were skipped while lua/ was dirty
(OMP edits in place) — rerun with a narrowed precondition (only files the new client loads must be clean).
In flight: OMP D-1 (setNoBattles removal, stale comments, driver dedup across gen1_rb_*_inputs.lua), LANE-BOOT2
(extracted-ZIP boot + HUD OSD capture). Queue: reruns poison/pc_ops/soft_reset/explode(4 attempts, healed)/
rival(new oracle)/changebox/linked_faint_active/trade/trade_decline/reconnect/admit after D-1; Yellow S-1 gate -s;
verify_gen1_release.py full pass; Gen 3 gen3_rr trade + faint duo; ledger cells for new receipts; P8-6b final docs;
P8-7 (rebase plan docs/gen1_rebase_plan.md, FF master, owner tag) needs owner authority.
