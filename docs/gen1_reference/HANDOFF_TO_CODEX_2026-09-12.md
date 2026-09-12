# Handoff back to Codex, 2026-09-12

Codex was offline from 2026-09-09 01:24. The owner directed the Claude peer to take ownership, stabilize the
tree and resume the work; Codex is back now. This page is the entry point: what the branch is, what changed and
why, what is proven, what is open, and where to pick up. It supersedes `CODEX_HANDOFF_2026-09-10.md` as the
current plan of record (that page remains the agreed decision table and the item list those decisions came from).

## 1. The branch

`gen1/rc` in `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, pushed to `origin/gen1/rc`.

- It is built on **your own chain tip `codex/gen1-gambatte-hold` (7c7c0a6)**, which already contained the old
  worktree HEAD `79d5172`, so your 59 commits are history, not a parallel line. The four `codex/gen1-*` branches
  are ancestors and need no merge.
- `ead07af` is the uncommitted sweep working tree exactly as you left it, committed under your own intended
  message. Before committing it I diffed every one of the 56 files that differed from the chain tip: each
  chain-added line absent from the working tree is a later edit of the same line (regenerated codec and
  admission hashes, renamed node ids, changed signatures, refactored journal and store lines). Nothing of yours
  was dropped. The review is `E:/Google Drive/SLink/.cache/snapshots/gen1-sweep-2026-09-11/review.md`, with the
  pre-move snapshot beside it (tracked diff, 716 untracked files, evidence tar, the git admin dir).
- Everything after that is 37 commits, listed by `git log --oneline 7c7c0a6..gen1/rc`. Total diff versus the
  chain tip: 615 files, +201,100 / -12,042 (most of the insertions are the previously untracked docs and data).
- `master` is untouched (still `adf3362`, 27 days old). Nothing was stashed. Gen 2, Gen 3 and UI branches
  and directories are untouched. I never moved the root checkout; something switched it from
  `codex/gen2base` to `master` at 2026-09-12 07:00 (section 6).

## 2. What changed, in the order it happened

**The proposal series is canonical** (commits `07ba1ca`..`c9bf980`, one per patch, in the verified order P1, P7,
P8, P12, P9, P10, P10-verifiers, P10-free-run-live, P11, P13, P14). The eleven notes under
`docs/gen1_reference/proposals/` stay as the rationale and evidence record.

**One engine** (`0d7db99`). `server/capture_rules.py`, `party_grant_rules.py`, `member_identity_rules.py` and
`acquisition_disposition_rules.py` are deleted; `no_catch_rules` keeps only `decision` (naming) and
`linked_death_rules` only `update_run_over`. Every rule decision is `SoulLinkState.handle_event` through
`server/gen1_semantic_events.py` and `server/gen1_engine_bridge.py`. Test importers moved to
`tests/unit/rules_fixture.py`. The `boxed_deferred` disposition was never assigned by any code path, so its
reads are gone too; that is what the five "stale" acquisition tests were asserting.

**One loop** (`48c64d0`). The ordinary frame-credit path is deleted: `server/gen1_frame_control.py`,
`gen1_frame_journal.py`, `gen1_frame_runtime.py`, `gen1_frame_acquisitions.py`, `lua/gen1_frame_client.lua`, the
ordinary and cold-native launcher gates and live tests, and ten credit-only unit suites. `free_service` is the
only gameplay mode; `ordinary_frames` is refused by `gen1_run_config` and `gen1_client_entry`. **Tier 2 is
kept** (`execution_window`, `frame_progress`, `gen1_native_execution`, `gen1_native_observation`,
`gen1_native_frame_accounting`, `gen1_execution_authority`, `lua/execution_window.lua`, `frame_pacer.lua`,
`gen1_native_frame_client.lua`, `gen1_native_runtime.lua`) because live-proven native-trade requirement rows
stand on it; the ledger helpers the deleted modules owned moved into `gen1_native_frame_accounting.py`. Note:
nothing seeds `gen1-frame-progress` in production any more, and the composed `native_manifest` launch is refused
by the durable entry until it is re-composed on the free loop. The registered native-trade live rows are
unaffected (they run Lua gates through `tools/run_gb_gate.py`, not the durable entry).

**Your battle-force authority is finished and live** (`296a66f`). Your `BATTLE_FORCE_INTEGRATION.md` section 5
diff targeted four files the series deletes, so the path-independent parts were carried over and the rest
re-targeted onto the free loop. The durable reply is `{ack, commands}` only, so the authority travels as the
peer's own `battle_instruction` command and closes with an `rby-instruction-window-receipt-v1` receipt:
`battle_force_authority.pending_instruction` issues from `stage_observation` when the batch is in battle and the
oldest pending command is a death command for a `pending_faint` death; the client service arms the same 64-frame
authority every in-battle frame (windows may be entered late); the server reproduces it (`verify_issued`),
verifies the rows (`verify_window` over `instruction_authority.verify_window` with `verify_evidence`) and
`gen1_faint_runtime.enforce` records `death["enforcement"]` once; refused, not_reached and declined re-issue
while the battle lasts; the overworld no-op receipt closes the death. **Live PASS on Red, Blue and Yellow**:
fainted at the `player_action` site on frames 1815 / 4229 / 3970, every window server-verified, SRAM diff 0
(`.cache/battle-force-{red-o0c_dfht,blue-7ikhcis8,yellow-478z2b85}`, `.cache/junit/free_window_*.xml`).

**The rest of the wiring** (`c5be9f5`, `d319d4b`, `993e961`, `6f07831`): `force_explode` is a held command with
its own receipt schema (overworld: the same HP write, as the Gen 3 client does out of battle); `replace_rival_team`
dispatches to the P12 executor and whiteout records are verified on restore; the engine's single-half species
rejection is recorded as a violation with its constraint hold instead of reading as a clean exempt grant (a real
P9 defect); retirement jobs report `memorialize_done` so a dead-zone pair reaches MEMORIAL as in Gen 3;
`starter_clause` is a retirement cause sourced from the P14 rejection record; `trainer_battle_start` exists as a
signal (`wCurOpponent`, 3-tick debounce) and feeds Rival Swap; and statics, NPC exchanges, evolutions and wild
encounters ride the observation batch, which restores `test_gen1_source_pipeline_adversarial.py` and
`test_gen1_no_catch_retirement_flow.py` and the batch-driven cases of the wild, evolution and storage suites.

**The release gate is consistent again** (`3981525`, `929e8cd`, `c877785`, `e596116`, `2bac48b`, `f271cd5`).
New helper `tools/repin_gen1_release_hashes.py` recomputes every `source_sha256` and `supporting_sources` digest
with the gate's own `proof_sha256`. The first run found **20,291 stale entries over 169 rows**, which predates
this work: each row was pinned at its own registration time and never re-pinned, so up to seven different
pinned hashes existed for one file and those rows were already failing dependency drift. Every proof whose source
test or supporting module was deleted or rewritten is re-registered onto the surviving test that carries its
assertion, with `assertion_basis` re-read; the six `sept8.*` frame rows keep their ids and describe the
observation batch; `runtime.held-faint-authority` registers the new parametrized ids so it proves both death
commands; `checks.live-gates.argv` gains the free-service and battle-force gates. **388 rows and their ids are
intact, no cuts.** Both inventories are regenerated.

## 3. Evidence as of this page

| Gate | Result |
| --- | --- |
| Unit + integration | 7,399 passed, 2 skipped (symlink privilege), 0 failed over 7,401 nodes (`.cache/junit/phase6_full.xml`) |
| Portable CI (`tools/verify_portable_ci.py`) | PASS: 6,754 passed, 526 deferred by named reason |
| Release gate `--list` | 187 registered / 201 missing (unchanged by all of this) |
| Release gate `--quick` | every validator passes; fails only on the unset emulator and UPR paths |
| `--verify-inputs` | OK with `SLINK_EMUHAWK=E:/Howard/Bizhawk/EmuHawk.exe` and `SLINK_UPR_JAR=E:/Google Drive/SLink/.cache/upr/PokeRandoZX.jar` (both match the pins) |
| Lua syntax gate, ruff CI selection | 299 files clean, clean |
| Live | P11 Explode R/B/Y (earlier), P10 free-run Yellow/Yellow at cartridge rate, the new in-battle faint window R/B/Y |

## 4. Open work, in the order I would take it

1. **Live duo evidence on the free loop.** `tools/e2e_duo.py` still drives the legacy client; the Rival Swap,
   whiteout and mid-battle-death duo scenarios need two-launcher tests of the `free_service` shape (the pattern
   is `tests/live/test_gen1_free_service.py`). This is also what the `single-player` stage's 60 rows need
   (`CODEX_HANDOFF_2026-09-10.md` item 7a).
2. **Manifest closure**, per item 7 of the old handoff: 7a single-player 60, 7b ordered-contracts 18 and the duo
   rows, 7c trade-receptionist 55, 7d patch-browser 40 (the browser tests now pass locally, see the resume note
   for the `NODE_PATH` and `SLINK_CHROMIUM` recipe), 7e the umbrella registrations.
3. **HUD delivery.** No Gen 1 runtime delivers prompts on the durable path: every engine `gui_prompt`,
   `msgbox` and `play_sound` is drained by the bridges, and the held executor completes physical commands only,
   so players see no link, violation or clause feedback that the Gen 3 client shows. Producers are ready (for
   example `gen1_starter_settlement.rejection_prompt`); a HUD executor on the free loop is the missing half.
4. **Native trade on the free loop**, which retires tier 2 and re-composes the `native_manifest` launch.
5. **P1 has no live evidence.** It is a one-line restoration of the Gen 3 trade staging gate, applied because it
   sits in this branch's copy of `lua/clients/gen3_frlge_client.lua`. Proving it needs the patched Radical Red
   ROM; the owner has deferred it, and no Gen 3 branch was touched.
6. **The Gen 3 port** is a separate worktree: `.claude/worktrees/shared-framework` on `claude/shared-framework`
   at your published spine `codex/shared-operation-binding-v1`, no merges done. Its 22 files that diverge from
   `gen1/rc` are listed in `GEN3_BINDING_PLAN.md` step 0a as the first task there.

## 5. Decisions taken while you were away

All by the owner, in session, recorded here so nothing is inferred from code alone.

| Decision | Where it lives |
| --- | --- |
| Starters are under the clauses in every generation; Yellow/Yellow is exempt | P14, adapter policy |
| Game Corner prizes are player-choice gifts under the clauses; the engine's species clause means two different prizes link and the same prize on both sides is the violation | `test_gen1_acquisition_runtime.py` |
| A clause-rejected starter faints in place (both archive kernels refuse the last party member; emptying the party as Gen 3 does is a kernel policy change) | `gen1_retirement_runtime`, ponytail-marked |
| Apply P1 with the series; leave the UI branches alone; leave `codex/rr-foundation` local and unpushed | this page, section 4 |
| The consolidated branch stays a branch until the release gate is green; master untouched | section 1 |
| One Gen 1 worktree for finished work, one for the in-flight shared layer, Gen 2 and Gen 3 left alone | section 6 |

Still open for the owner: whether to empty the party for a rejected starter (above); whether `sept8.*` row
descriptions should keep their re-wording; when master moves.

## 6. Worktrees and the trap that ate fourteen of them

`.claude/worktrees/` now holds live worktrees only, and `.claude/worktrees/README.md` is the map kept beside
them (that folder is gitignored, so the map lives on disk, not in this branch):

| Directory | Branch | Purpose |
| --- | --- | --- |
| `gen1-rby-code-sweep-8d06e2` | `gen1/rc` | the Gen 1 RC, all finished Gen 1 work (directory name is historical) |
| `shared-framework` | `claude/shared-framework` at `codex/shared-operation-binding-v1` | in-flight shared layer and the Gen 3 port |
| `agent-a7f68e4f2daf34d8d` | `claude/ui-mockup-track-b` | UI mockup track B, one unique commit, left alone |
| `gen1-collab-bad73b` | `claude/gen1-collab-bad73b` | session sandbox at master, removable when idle |
| `gen2-production`, `rr-foundation`, `gen3-non-rr-planning-2b0be2` | none, content only | Gen 2 and Gen 3 content whose git admin entries were gutted long ago; untouched by owner instruction, and their branches `codex/gen2-production` (fb754a2) and `codex/rr-foundation` (e4fd473) are intact |

Five former worktree directories that carry content not on any branch moved to `.claude/worktrees-archive/`
(`agent-a6f8ce62fc90289c2`, `soul-link-ui-mockups-40f67b`, `ui-phase0-ci`, `ui-phase0-integration`,
`ui-phase7b-sources`); their deltas are tarred under `.cache/snapshots/orphans-2026-09-11/` with a MANIFEST.
Seven further orphans were verified byte-identical to their branches and deleted. The dead admin entries of
`gen2-production` and `rr-foundation` were cleared, which is what had been printing a "failed to delete ...
Permission denied" block on every git command; their content directories and branches are untouched.

The root checkout was switched from `codex/gen2base` to `master` by an unknown actor at 2026-09-12 07:00. It is
clean and matches `origin/master`, and `codex/gen2base` still exists at b5d1aa7. I did not move it; flagging it
because your 2026-09-06 handoff asked that unexplained root switches be reported rather than assumed.

**Directories under `E:/Google Drive/SLink` carry the Windows read-only attribute.** `rmdir` on such a directory
fails with access denied although deleting the files inside succeeds, so every `git worktree remove` and every
automatic prune deleted the admin files (`HEAD`, `gitdir`, `commondir`, `index`) and then failed on the
directory: that is exactly the fourteen orphaned worktrees, and one more was orphaned this way during this
session. To delete one, use Python `shutil.rmtree` with an `onerror` handler that `chmod`s `stat.S_IWRITE` and
retries, on both `.claude/worktrees/<name>` and `.git/worktrees/<name>`. The PowerShell tool refuses
`Remove-Item` on the spaced path and Git Bash mangles `cmd //c rmdir /s /q`.

Cleanup done: three idle worktrees removed; seven orphans verified byte-identical to their branch tips and
deleted; five orphans with unique content archived as deltas and kept
(`E:/Google Drive/SLink/.cache/snapshots/orphans-2026-09-11/MANIFEST.md` records dir, branch, ORIG_HEAD,
verification result and action per directory). `ui-phase7b-sources` is archived and kept because it holds
`docs/ui_migration/gen1_integration_map.md`, which exists only on `codex/ui-rework`. `gen2-production`,
`rr-foundation` and `gen3-non-rr-planning-2b0be2` were not touched at all.

For the UI merge when it comes: `codex/ui-rework` and this branch change 130 of the same paths; 93 are
byte-identical, 37 are real three-way conflicts, and two of those decide the cost: `server/server.py`
(ui +840/-4588 versus ours +778/-145) and `server/templates/manager.html`, where the UI extraction deletes what
this branch extends.

## 7. How to pick the branch up

`gen1/rc` is checked out in this worktree (`.claude/worktrees/gen1-rby-code-sweep-8d06e2`), which is the one
consolidated Gen 1 worktree the owner asked for. Git refuses to check the same branch out twice, so:

- **To continue the RC directly**, work in this directory. It is clean, its HEAD equals `origin/gen1/rc`, and the
  gitignored inputs it needs (ROMs, savestates, `.cache/pret`, the UPR jar, `.cache/node`) are already here.
- **To work on a topic branch**, cut it from the tip without disturbing this checkout:
  `git -C "E:/Google Drive/SLink" worktree add -b codex/gen1-<topic> "E:/Google Drive/SLink/.claude/worktrees/gen1-<topic>" gen1/rc`.
  Remember the read-only-attribute trap in section 6 before removing any worktree again.
- **Never** switch or reset the root checkout; it stays on `codex/gen2base` by the owner's standing rule.

CI (`.github/workflows/test.yml`, on every push) runs ruff's bug-class selection, the Lua syntax gate and
`tools/verify_portable_ci.py`. It is green at checkpoint 5 (`7135d8f`) and at the branch tip. The intermediate
Phase 6 commits (`c5be9f5` through `4fd5cce`) are red for one reason only: the portable-CI inventory was
reconciled once at the end of the phase (`f271cd5`), so those commits carry node-classification drift. Worth
knowing before bisecting; nothing else is wrong with them.

## 8. Where to read next

`INTERIM_LEDGER_2026-09-10.md` rows 14 to 25 are the blow-by-blow with evidence paths, and its findings list
holds everything noticed in passing. `RESUME_2026-09-11.md` has the current state at its head plus the tool
recipes (browser tests, release-gate environment, the short-path rule for live runs from a copy).
`RC_CHECKLIST.md` is the 388-row status page. `FRAMEWORK.md` is the shared-module inventory with a dated status
block. The approved plan this work followed is `C:/Users/howar/.claude/plans/dazzling-painting-sparkle.md`.
