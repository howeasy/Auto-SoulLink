# Gen 1 master release — resume note (2026-09-17 ~22:30Z, owner break)

Read this first after a context reset or harness restart. The ledger `docs/gen1_requirements.md`
is the authority on evidence; this note is the working state around it. Plan (owner-approved,
v3.9): `C:\Users\howar\.claude\plans\system-reminder-you-are-operating-gleaming-pretzel.md`. The
standing worker contract every card brief points at is `docs/agents/worker_card.md`.

## Native sound (2026-09-21, session 57038e13) — DONE on the branch, reviewed

Plan `C:/Users/howar/.claude/plans/splendid-stirring-toast.md` (owner-approved 2026-09-20).
Commits `7d70678` (ROM: SlinkSfxService on the DelayFrame bridge, caps $03), `5533162` (client
`play_sound` -> mailbox codes, Manager `native_sounds` on for Red/Blue), `c8edcd1` (state-matrix
gate; the Joypad dispatch site for menu loops; frame-stamped 240-frame hold), `b35f378` (pureRGB
overlay port, `native_sounds` on for pureRGB). Facts: mailbox `+7` = semantic code 1/2/3, the ROM
resolves it per `wAudioROMBank` at play time (`$89/$A5/$8C` in `$02`/`$1F`, `$86/$8C/$8C` in
`$08`), holds through fades and busy CHAN5/6/8, bounded at 240 frames (`+12`/`+13`). Two
main-thread sites: the DelayFrame bridge and `Joypad` (menus never reach DelayFrame). Receipts:
`tests/fixtures/gen1/receipts/test_gen1_sfx_gate_*` (Red/Blue/purered_overlay, town + battle),
patch gate, menu-row and receptionist re-runs, duo `trade_new` PASS with `--native-sounds`.
Codex REVIEW `cx-5f7b86be`: MAJOR (low-health alarm consumed TINK/DENIED into silence) + MINOR (queue outlived `native_sounds=false`) fixed in `dcf8cb4` with gate case G (alarm armed by Growl; vanilla persistent flag -> LEVEL_UP for every code, pureRGB bounded tone pairs -> plain row once it ends). HEAD `dcf8cb4`. Owner decides push/merge.
pureRGB rebuild needs the toolchains at a space-free path (`C:/slink-tools`, see the commit) and
the pinned checkout at `.cache/purergb-src` with the three clean `.gbc` copied beside it; run
gates with `SLINK_PURERGB_ROMS=E:/Google Drive/SLink/.cache/purergb`.

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
Lane note (2026-09-17 ~21:50Z): gen3_rr trade/faint failed at the MYKEY handshake because `patch/build/slink_RR.gba`
(gitignored build artifact) was absent from this worktree — EmuHawk started with no core. Copied from the main
checkout; rerun queued after the Gen 1 sweep (LANE-REG2). HUD-3 / hud.lua / memory_gb / gatelib changes were ruled
out as causes (DIAG-G3). Package boot + HUD pixel proof committed at 05bc4f1.

## Wrap-up 2 (owner 2026-09-17 ~22:05Z: "after all in-flight work is done, pause so we can check in and compact")
Reconcile-only from here. In flight at the pause request: OMP H-5 (dead-process rule misfire in tools/e2e_duo.py that
aborted duo runs when one half exited after writing RESULT; plus the soft-reset stats-baseline wait placement), OMP RB-1
(rebase dry run in scratch clone <scratchpad>/rb1, paused for H-5), DIAG-R2 (Opus: poison_new B 'hunt-timeout' at
d2b107f — real or consequence), L-10 (ledger cells: S-1 Yellow ✓ candidate cdaa596, package boot 05bc4f1, Track B audit).
Committed since the last section: 05bc4f1 package-boot receipts, 63f7475 HUD geometry fix, d2b107f D-1 dedup,
f76b506 R-1 fast lanes PASS, 210d295 resume, cdaa596 Yellow S-1 receipt.
NEXT SESSION, in order: (1) commit H-5 when it lands, refresh tools/e2e_duo_head.py; (2) lane: rerun sweep of all
Gen 1 scenarios (poison, pc_ops, soft_reset, explode, rival, changebox, linked_faint_active, trade_decline, trade,
reconnect, admit, ball_gate) with the narrowed precondition; commit receipts; (3) gen3_rr trade + faint; (4)
verify_gen1_release.py without --quick (P8-7 full pass); (5) ledger cells for the new receipts, P8-6b docs; (6) owner
decision: rebase onto master (RB-1 resolutions), FF, tag.
DIAG-R2 outcome (~22:10Z): poison_new B 'hunt-timeout' was a real pre-existing budget bug, fixed in 5b17723 (leg budget
= Forest.MAX_ENCOUNTERS x 3000; the retryable HUNT_EXHAUSTED phrase is now reachable). Driver dedup, EX-4, hud.lua and
the deletions were ruled out as causes. The A-half truncations were the H-3 dead-process misfire (OMP H-5, in the tree
uncommitted at the pause). Ledger 66cb89a: S-1 Yellow ✓.
PAUSED for owner check-in + compaction (~22:25Z). All in-flight work reconciled: H-5 committed as f054b79 (dead-process
rule fixed and pinned; soft-reset baseline wait after the go-file); tools/e2e_duo_head.py == HEAD:tools/e2e_duo.py.
RB-1: the rebase of f76b506 onto master cb9cf5c was CONFLICT-FREE (185/185; the predicted server.py/patcher.py/
_board.html overlaps touch different hunks); scratch clone <scratchpad>/rb1 at f3ad072, resolutions file
<scratchpad>/rb1_resolutions.patch lists the gitignored inputs a fresh clone needs (ROMs, sibling checkout for
test_gen1_trade_patch.py:80). No worker is running; OMP Gen1 Peer 2 idle. Tree clean except the untracked frozen copy.
Resume with the 'Wrap-up 2' order above: rerun sweep (12 Gen 1 scenarios) at f054b79, gen3_rr trade+faint, release
runner without --quick, ledger cells, P8-6b docs, then the owner's rebase/FF/tag decision.

## Phase R2 (resumed 2026-09-17 ~22:26Z after compaction) -- implementation mode; owner: 3 Claude subagents max, OMP live "Gen1 Peer 2" (id 01a0aff5-7a52-71c8-98a4-432e5727f0c6), union-alpha headless freely (validated, never trusted)
Headless omp_peer now returns at once (no relay needed). Sequence of this stretch, all committed on the branch:
- Rerun sweep at 3475c6f (reg_sweep3, 7f23199): 8 PASS first attempt + gen3_rr trade/faint PASS (RR ROM present). Oracle-only
  failures on PASS receipts -> H-6 (2c17161, Opus): explode move-menu regexes vs the real `@frame` padded format; soft_reset hello
  baseline back before the go-file + 0.25 s stats poll; wait_for gives the predicate the last word when both halves finished
  without a FAIL. rerun_h6 (2cd3d1f): soft_reset, explode, reconnect(--wrong-save red_town_ot2) PASS.
- rival_swap_new first live run: swap applied within 181 frames, then the fight stalled 51200 frames = 400 x 128 pressing Left
  into the trainer intro text box: the battle driver's DisplayBattleMenu baseline and RUN-column cursor RAM survived the walk's
  incidental wild battle (DIAG-RIVAL, Opus). Fix 8e345ac: D.new_battle() re-seeds menu_base; battle_plan calls it; failed
  D.choose('FIGHT') B-mashes. rival PASS e803b91 (ENEMY_SENDOUT species=176). battle-stuck stays non-retryable (deterministic).
- SR-CHORD (03db464, OMP): two-step release for soft_reset_new (`<go>.chord` after the stats baseline). DEADLOCKED on the lane:
  A waits at the gate, the runner waits for both keys' mon_stats which never arrive pre-reset -> DIAG-SR2 (Opus, in flight):
  establish what carries mon_stats (server._cache_mon_info callers) and pick (a) different pre-chord quiescence signal,
  (b) later release point, or (c) revert the gate. 3600-frame Lua deadline is also a few seconds at unthrottled speed.
- H-7 (same Opus card, in flight): species_clause_new A 'hunt ended out-of-balls' (RNG class) with B still running ended the
  attempt as ClientFinishedEarly -> RuntimeError -> no retry (budget 8 wasted). Fix at the shared seam: one-sided retryable FAIL
  -> retryable attempt end (kill the other half), non-retryable abort unchanged; pin.
- rerun_rest6 (b9f5bee): link, deadzone, linked_faint_bench, type_clause, whiteout PASS at the final Lua tree. 16 of 18
  gen1_new scenarios now have receipts at that tree; open: soft_reset (chord gate), species (H-7 then rerun).
- Release runner at HEAD: 8 fast lanes PASS (unit 3020, 293523f) and live-gates 5 / live-new-gates 9 / live-trade-gates 2 PASS
  (a04b14a). duo-pairs (P8-7 full) waits for soft_reset + species. verify_gen1_release.py:26 text corrected (Red A vs Blue B only,
  ac7594c); wrapper TimeoutExpired now a named pytest.fail (5879972, R-6).
- Docs: P8-6b final pass 68e91ce (Sonnet; UA-1 union-alpha stale-reference audit cx-7f3c1b45 validated by git grep, 11 stale
  sentences reworded); UA-2 package closure audit cx-dec65cf8 validated (manifest test 4 passed, 17 closure files tracked;
  only qualification: LuaSocket binary is Windows x64 Lua 5.4 only, now in release_notes). Ledger L-11 8228a57 (S-6/W-6/W-3 ✓,
  D-11 ◐ explosion half, S-4 ◐ with poison live). R-3 d23482d (board snapshot ruff + S-7 prose).
- Frozen harness copy: refresh with `git show HEAD:tools/e2e_duo.py > tools/e2e_duo_head.py` after every e2e_duo.py commit
  (CRLF differs from the working copy; compare with tr -d '\r'). Lane precondition is narrowed to client-loaded files, so in-place
  Python/docs edits by workers do not skip runs; Lua edits go through scratch copies + patches (-p2 with a/wt-*-base prefixes).
- Lane invocation notes: reconnect_new needs `--wrong-save tests/fixtures/gen1/red_town_ot2.SaveRAM` when run directly (the
  duo-pairs wrapper adds it); scenarios run ~30-90 s each unthrottled, so a `[duo]` line grep on the log is the receipt.
NEXT: integrate DIAG-SR2 + H-7, refresh frozen copy, rerun soft_reset_new + species_clause_new, commit receipts; then
`verify_gen1_release.py --lane duo-pairs` (or the full runner) for the P8-7 verdict; ledger cells for rival (W-4/D-11 rival
half), soft_reset, species; release_notes/runtime_checks final touch; then the owner's rebase/FF/tag decision (RB-1 dry run
conflict-free at <scratchpad>/rb1 f3ad072 -- re-run the dry run on the final HEAD before asking).
Phase R2, later (~23:25Z): DIAG-SR2 (26d08f4) found the real cause of every soft_reset baseline problem: mon_stats arrive IN the
hello (server._cache_mon_info from msg.party) but the hello handler's only _save() runs 14 lines earlier and ticks never save, so
hello N persists hello N-1's stats; the 2c17161 'pre-reset' baseline was taken 50 ms AFTER the reset (vacuous) and the chord gate
could never release. Fix: baseline snapshotted after the durable-hello wait and before go(); mon_stats reconciled (deferred flush
of the second key accepted and named). H-7 (same commit): retryable_gen1_rng admits a half with no RESULT, so a one-sided
RNG-class FAIL retries. rerun_sr2 aa69f5e: soft_reset PASS (CHORD_GATE @958 before RESET_SEEN), species PASS attempt 2/8 (retry
live). ALL 18 gen1_new scenarios have PASS receipts at the final Lua tree. Ledger: W-4/D-11 ✓ (f39c34a), audit trail 33f1945;
runtime_checks 3621363. duo-pairs lane run 1 (b8a22fa): 17/18 PASS, rival refused by the qualifier 'stored spd=11 but recomputed
12' -> H-8 (Opus): stat exp accrues per defeated foe but CalcStats runs only on level CHANGE / AddPartyMon / withdrawal /
evolution / vitamins, so the check is now the band [recompute(stat exp 0), recompute(current)] with the tolerated value named in
the PYDEC line (tools/gen1_fixtures.py qualify(notes=...), pinned). duo-pairs run 2 launched at the H-8 HEAD.
RB-2 (Sonnet): rebase of aa69f5e onto master cb9cf5c conflict-free, 209 commits; clone <scratchpad>/rb2 tip f3b8c0c; ruff 0 new,
lua 181 OK, unit 3010 passed / 27 env skips (UPR jar + pokecrystal clones absent machine-wide). Branch moved since (docs/
receipts/H-8), so redo the dry run at the final HEAD before the owner's FF: `git -C "E:/Google Drive/SLink" ... merge --ff-only
<rebased sha>` after pushing -- OWNER AUTHORITY REQUIRED.
QUEUE (not release-blocking): latent server bug -- hello handler saves before _cache_mon_info writes mon_stats (server.py:1629
vs 1641); a restart between hellos loses the last hello's box-level cache; fix shape in the 26d08f4 commit body; needs
slink-adapter-guard. Hunt/forest drivers share the stale menu_base exposure fixed for rival (D.new_battle available). Manifest
closure test traverses from lua/gen1/run.lua, not the launchers, and ignores .dll rows (UA-2).

## Phase R2 finish-up (2026-09-18 ~00:00-01:25Z)
- Full release runner: run 1 (d12f441) 11/12, duo 17/18 (rival qualifier instrument -> H-8 1484de0 stat band); run 2 (2fd24b2)
  11/12, duo 16/18 (rival no-replacement -> RIVAL-2 7370ff1 then RIVAL-4 b8374a2; linked_faint_bench hunt whiteout -> 1dcb910
  retry phrase); run 3 (e7a98ef) 11/12, duo 16/18 (species: two consecutive one-ball misses, retry-once by design; memorial status
  0x80 -> DIAG-LFA 6e01e33 mask, INSTRUMENT: pokered RemoveFaintedPlayerMon leaves $80 in a red-bar faint's status byte, the client
  copies the party struct faithfully). Run 4 launched at 1267d39 for the clean P8-7 receipt.
- Rival: the product half (W-4/D-11) was green from the first live run; every later red was the driver or oracle. RIVAL-4 proved the
  replacement path live for the first time (RIVAL_SWITCH slot=1 -> RIVAL_RESULT loss -> PYDEC PASS): after a KO a NoWillText box
  owns the frame (D.commit_move's retry A on the fainted slot), watched A|B only; choose_replacement now B-mashes after each failed
  pass. Open (not release-blocking): D.commit_move presses A up to twice into a forced party menu when the foe moves first.
- Rival oracle 785d11d: blob count vs B's party AT COMMAND TIME (D-6 retires B's copy when A's linked mon falls in the fight);
  loss branch expects cause=battle when A's receipt has BATTLE_FAINT_SITE for the linked key.
- HUD (owner reports 'overflow to ...' and 'notifications aren't vanishing'): HUD-3 7d64f76 word-wrap (3/4 lines) + burst dwell
  (coalesce, 90-frame head clamp, newest 4); HUD-4 ebc2639 cleartext restored; HUD-5 92ae732 THE ROOT CAUSE: BizHawk API is NLua
  userdata, `type(gui.clearGraphics) == "function"` was false in EmuHawk, so no clear ever ran in production while lupa tests passed;
  guards are now `~= nil` + pcall and the lupa stub wraps APIs in callable tables (memory: reference_bizhawk_api_userdata). Pixel
  receipts tests/fixtures/gen1/receipts/hud_wrap/ (frame 180 three-line bar, frame 1000 clean, frame 1310 four-line prompt).
- RB-2: rebase of aa69f5e onto master cb9cf5c conflict-free (209 commits), gates green in the clone; redo at the final HEAD (RB-3)
  before the owner's FF. In flight at this note: run 4, OMP DOCS-4 (release_notes: HUD, harness hardening, runner table, limits).
NEXT: run 4 receipt -> release_notes row; RB-3; owner decides FF + tag (no push/merge/tag without owner authority).

## WRAP-UP (2026-09-18 ~02:00Z) -- owner: "Do 2 and then move on. Wrap this up."
Verdict recorded in docs/release_notes.md (c01a13f): five consecutive full runner passes at 11/12 lanes (unit up to 3038, rom/lua/
profile/statics/fixtures/patch-build, live-gates 5, live-new-gates 9, live-trade-gates 2); duo-pairs 17/18, 16/18, 16/18, 17/18,
17/18 -- every red was an instrument defect (all fixed: H-6/H-7/H-8, RIVAL-2/3/4, DIAG-SR2, DIAG-LFA) or an RNG roll (species
one-ball misses x2 then x3, poison double KO, a hunt whiteout); no product defect found. Every one of the 18 gen1_new scenarios
passed inside a full run at least once and has a committed PASS receipt at the final Lua tree. RNG budgets raised bf22342 (two
retries per RNG-class failure, default limit 3, poison 4). Owner accepted the verdict.
HUD: wrap (7d64f76), burst dwell, cleartext (ebc2639) and THE root cause of banners never vanishing -- BizHawk API is userdata, the
type()=="function" guard never fired (92ae732; memory reference_bizhawk_api_userdata); pixel receipts 1267d39.
Open, non-blocking (queue): D.commit_move stray A into a forced party menu; hello-handler save ordering for mon_stats; species
one-ball miss rate is structurally high (full-HP wild mon, plain Poke Ball) -- weaken-before-throw would make that lane robust;
manifest closure test traverses from run.lua only and ignores .dll rows.
RB-3 (Sonnet): rebase of the final head onto master cb9cf5c in <scratchpad>/rb3 -- result appended below when it lands.
OWNER ACTIONS: push the rebased branch, `git -C "E:/Google Drive/SLink" -c maintenance.auto=false -c gc.auto=0 merge --ff-only
<rebased sha>`, tag (version lives in the tag; `gh release create`). No push/merge/tag was performed by this session.
RB-3 result: rebase of bf22342 onto master cb9cf5c CONFLICT-FREE, 232 commits, clone <scratchpad>/rb3 tip 96c56f9; ruff 0, lua 181
OK, unit 3027 passed / 24 env skips. Three docs-only commits landed after bf22342 (c01a13f ca72147 7861905 + this one), so the
real rebase replays a few more; expect no conflicts (docs/ receipts only). NOTE for the FF: the main checkout's gitignored
tests/fixtures/gen1/*.SaveRAM are STALE (legacy byte-written shape, 22 unit failures); copy the worktree's fixtures (F-6 scripted
play) before running the suite there.

## MERGED TO LOCAL MASTER (2026-09-18 ~08:20Z) -- owner: "merge to main but do not create a release. I want to test a run first."
Queue items done first: Q-1 947a577 (commit_move stops on player_fainted/party_menu; hunt throws only at odds 1.00 -- measured:
45/45 catches at 1.00, every miss came from the dmax+1 rule at 0.58-0.67), Q-2 0fce67c (hello handler saves after
_cache_mon_info; slink-adapter-guard APPROVE), Q-3 3e45ebe (manifest test rooted at both launchers; FOUND AND FIXED a real
package bug: lua/games/gen2_crystal_trainers.lua was never shipped and the Crystal client requires it at load), plus 94f0058
(route walkers: detour back-off after 4 detours on a segment, fail closed after 3 back-offs -- the poison walk had oscillated
90000 frames behind Route 1's ledge). Full runner run 6 at 09d0afb: 11/12, duo 17/18 (f6dc5b0); poison + rival then PASS
first attempt (50f9803). Real rebase of the branch onto master cb9cf5c: 243 commits, conflict-free; fast lanes on the
rebased tree all PASS (unit 3042). `git -C E:/Google Drive/SLink merge --ff-only 24fdb06` done: LOCAL master = 24fdb06.
NOT pushed (origin/master adf3362 is 352 commits behind local master, most of them predating this work), NOT tagged, no
release. pureRGB session notified (branches off 24fdb06; my writes frozen).
OWNER NEXT: test a run from the main checkout (fixtures and ROM artifacts present there); then push master, tag, gh release.
If the test run finds something, new commits go on top of master (tell the pureRGB session first).

## FINAL REVIEW + MERGE (2026-09-20) -- owner: "Work directly with Codex thread 'Review RBY' to do a final review ... also send a limited context fable agent"
Both reviewers said DO NOT SHIP at bbcd037. Everything found was in the Gen 1 client; nothing corrupted a save; SRAM/checksums/
profile symbols verified sound against pret on R/B/Y. Fixed on the branch, each cross-reviewed by the other reviewer:
- 64d9663 (Codex): slow naming lost the catch (AddPartyMon hook before AskName, 600-frame budget) -> no acquire budget; NPC
  trade from a non-last slot (hook before DisplayPartyMenu; RemovePokemon then AddPartyMon) -> npc_trade repinned + npc_trade_done.
- 7616d9f (Fable): level-up evolutions never hooked (EvolutionAfterBattle bypasses TryEvolvingMon) -> evolve at the species-publish
  site 0E:6ED5/0E:6F86; whiteout rebuild deadlock with a full party -> bounded tail requeue of party_mon.
- da2cf11 (Fable, from Codex cross-review): freshness witness on the slot about to be written; old key from the pre-signal party read.
- 70b0cc8 (Fable, from Codex cross-review): the witness is a guard during naming, not a permanent veto (byte-identical re-catch).
- be29c9d: lua/slink.lua routes 'SGB' (EmuHawk reports it with GbAsSgb on).
Live proof: slow-name gate 9a41d78 (Red/Blue: 2400-frame naming hold, one capture, zero no_catch; Yellow = hunt-driver limit,
Pikachu's Thundershock KOs the Pidgey), evolution gate d0b13dc/aa8a1df (Red/Blue: LEVEL_UP 7 -> EvolutionAfterBattle ->
evolve@6ED5 -> key_change 70->71 KAKUNA; exp staged to L7-1 = instrument shortcut). Full runner: run 7 (aa8a1df) and run 8
(0b59515) GATE PASSED, 12/12 lanes, duo-pairs 18/18 -- the first all-green runs of the RC. Docs c5822bc/3887e9f/5c97aa4.
MERGED: local master = 5c97aa4 (FF of 15 commits over 79aa608). NOT pushed/tagged/released (owner tests a run first).
pureRGB session notified (rebases onto 5c97aa4); my writes frozen.
QUEUE: wEvoOldSpecies at the publish site (removes the script-initialization ambiguity; needs a profile symbol via the
generator); native Cable Club trades unsupported/unprotected (refusal or warning); NPC-trade live receipt (no fixture near one);
Yellow write-path duo evidence; MINORs from Fable: rescan_boxes per-frame cost, party_mon nickname re-encode, SameBoy core untested.

## MERGED BOTH TO MASTER (2026-09-20 ~22:30Z) -- owner: "Work with PureRGB and merge both to main"
Local master = 0937f3d: the Gen 1 RC (48883f8) plus the pureRGB integration branch (merge 8eed7e1 of 997613a, lint merge
c95a664, receipt 0937f3d) -- its full runner GATE PASSED 19/19 (the 12 vanilla lanes identical to master's run 8: duo-pairs 18/18,
slow-name + evolution gates Red/Blue; 7 pure lanes incl. duo-pairs-purergb 33/33). NOT pushed (origin/master adf3362 is 458
commits behind), NOT tagged, no release -- owner's call. The pureRGB session owns lua/gen1/* and the Gen 1 tooling from here.

## CLEANUP (2026-09-20 ~23:20Z) -- owner: "cleanup any leftover Gen1 branches, Github branches, etc.; validate no active work"
No active Gen 1 work: no EmuHawk running, Codex/OMP peers idle, the only live Claude session on the repo is the pureRGB
integration (its worktree recursing-hopper-86c382 and branch kept). Done: parked worktrees gen1-collab-bad73b,
gen1-native-free-service (+WIP commit 3a2bbdf), gen1-runtime-performance (+WIP 25ba1ab), gen1-speed-gate removed (13 orphan
.git/worktrees admin dirs deleted); 17 archive/<branch> tags for every unmerged Gen 1 branch (incl. archive/gen1/rc); the 7
Gen 1 branches on GitHub deleted after their archive tags were pushed (origin now has 0 gen1 heads); merged branches
claude/gen1-collab-* deleted; 1222 kept slink_duo_* scratch dirs removed from Temp.
LEFT FOR THE OWNER (the git guard hook refuses force-deletes from a session): the 15 archived-but-unmerged local Gen 1 branch
refs (tips preserved by the archive tags; list them with `git for-each-ref refs/heads/ | grep -i gen1`); the sweep worktree
gen1-rby-code-sweep-8d06e2 (gen1/rc; hosts tools/agent_work_guard.py referenced by three hook entries in ~/.claude/settings.json
and the sole checkpoint files -- remove the hook entries first, then remove the worktree and the gen1/rc ref); this worktree +
branch claude/gen1-master-release-plan-6b4279 (merged; remove after this session). The OMP scratch worktree
C:/Users/howar/.omp/wt/wt-20260917-184130-2273b05 (branch merged, clean) is OMP's to drop.
