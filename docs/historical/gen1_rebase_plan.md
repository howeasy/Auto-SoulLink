# Gen 1 v0.3.0 — rebase plan

> **HISTORICAL — superseded 2026-09-26.** This plan targeted rebasing the
> `gen1-master-release-plan-6b4279` branch (worktree since removed) onto master `cb9cf5c`. That
> rebase happened: the branch was rebased and fast-forwarded into local master as `24fdb06`
> (2026-09-18), then the final-review fix branch merged as `5c97aa4` (2026-09-20), then the
> pureRGB integration merged as `0937f3d` (2026-09-20) — see `docs/gen1_resume.md`'s "MERGED …"
> sections for the exact commits. Master has moved substantially further since (Gen 2 and Gen 3
> landed 2026-09-26) and none of it was pushed/tagged as of this pass. The git-inventory numbers
> below (commit counts, the three-file overlap, `d2c30fb`/`cb9cf5c` as endpoints) describe a
> base and a branch that no longer exist as such; read this for the recipe and rationale, not as
> a plan still awaiting execution.

## Scope and evidence status

**Planning only. No rebase, commit, stash or tag was executed by this card; only read-only `git log`/`git diff`/`merge-base` inventory queries were run.** `git merge-base master HEAD` confirms the base is exactly `d2c30fbbe263041d34038e2ad781a4a2cb78d86a`. `git rev-list --count d2c30fb..HEAD` at the release worktree (`E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279`, HEAD `d9f95e7`) is **152**, not the task's approximate 137 or the fallback resume's approximate 135 (`docs/gen1_resume.md:10-14`) — both were under-counts taken at an earlier point in the branch's life; commits kept landing after they were written. `master` is at `cb9cf5cfb93c05bda9d62a4f2a1e4e4333b1d12b`, three commits ahead of `d2c30fb`, matching the task's reported count. `BASE_HEAD:1` recording `c2605ae` is a separate, older marker inside the prep snapshot; it is superseded by this session's direct query, not used to override it.

## Master movement and touched-file comparison

`git log --oneline d2c30fb..master` (newest last, chronological):

```
9269d81 refactor(ui): one chrome in the tree — the run server wears the shell too
bab593c fix(manager): a run gets ports it can bind, and a dead spawn is not "running"
cb9cf5c style(ui): panel copy in the interface's voice; fix doubled JS escapes
```

`git diff --stat d2c30fb master`: **34 files changed, 434 insertions(+), 1504 deletions(-)**. Touched: `README.md`, `docs/REFERENCE.md`, `docs/ui_migration_plan.md`, `server/board.py`, `server/chrome.py` (deleted), `server/manager.py`, `server/patcher.py`, `server/server.py`, `server/static/board.css`, `server/static/dashboard.css` (deleted), `server/static/dashboard.js`, `server/static/sidebar.css` (deleted), `server/static/slink.css`, `server/templates/_board.html`, `server/templates/_debug_panel.html`, `server/templates/_obs_panel.html`, `server/templates/_rail.html`, `server/templates/_twitch_panel.html`, `server/templates/base.html`, `server/templates/broadcast.html` (deleted), `server/templates/calc.html` (deleted), `server/templates/dashboard.html`, `server/templates/debug.html` (deleted), `server/templates/manager.html`, `server/templates/memorial.html`, `server/templates/obs.html` (deleted), `server/templates/panel_page.html` (new), `server/templates/patcher.html`, `server/templates/run_panel.html` (deleted), `server/templates/stream_index.html`, `server/templates/twitch.html` (deleted), `tests/integration/test_cli_native_toggles.py`, `tests/unit/test_manager_http_hardening.py`, `tests/unit/test_manager_spawn_flags.py`. This is a UI-chrome consolidation (drops the separate dashboard/sidebar chrome, folds several panel templates into one shared shell) plus a manager port-allocation/dead-spawn fix — neither was anticipated by this plan's original branch-side candidate list below, which focused on Gen 1 sync/transport/harness paths.

**Exact overlap** (`git diff --name-only d2c30fb HEAD` intersected with the master file list above): exactly three files — `server/patcher.py`, `server/server.py`, `server/templates/_board.html`. Per-file change size on each side:

| File | Branch (`d2c30fb..HEAD`) | Master (`d2c30fb..master`) |
|---|---|---|
| `server/server.py` | 47 lines | 112 lines — the larger UI-chrome refactor's share of this file |
| `server/patcher.py` | 4 lines | 2 lines |
| `server/templates/_board.html` | 10 lines | 13 lines |

`server/server.py` is the highest-risk file: both sides changed it substantially (this branch's per-connection `last_seq`/hello-seen/admission work; master's UI-chrome wiring), so a mechanical three-way merge is unlikely to be clean and the file needs an actual read of both diffs at rebase time, not just the line counts here. `server/patcher.py` and `server/templates/_board.html` changed by only single-digit-to-teens line counts on each side; still verify by reading, not by size alone. Every other candidate this plan lists below (adapter/state/harness/launcher/docs files) has **zero** textual overlap with master's three commits — those remain semantic-risk-only predictions, not confirmed intersections, and the reverse is also true: nothing below flagged `server/manager.py`, `server/board.py`, `docs/REFERENCE.md`, `README.md` or the seven-plus other UI-chrome files master touched, none of which this branch has modified, so they carry no rebase risk regardless of their size in master's diff.

### Do not reuse the previous rebase's inventory

The plan's old context concerns **`e2fefa9` → `d2c30fb`**, not the requested **`d2c30fb` → current master** interval. That old interval changed 37 files, including `server/server.py`, `server/manager.py`, `server/patcher.py`, `board.py`, `chrome.py`, templates/CSS and five unit tests. At that earlier branch tip only `server/patcher.py` and `tests/unit/test_patcher_routes.py` overlapped, hence the old two-MD5 resolution (`prep/PLAN_v3.9.md:5-12,229-234`). Those are historical facts, **not** the list of files touched by the three newer master commits.

The present branch has since changed shared server paths: wrong-save/per-connection sequencing and pre-hello rejection are recorded in `server/server.py`, with `tests/unit/test_server_seq.py`; reconnect queue handling changed `lua/connector.lua`, with `tests/unit/test_connector_reconnect.py` (`docs/gen1_requirements.md:92-93,117`). The current resume also lists server sync and trade-watchdog work, some still in flight (`docs/gen1_resume.md:73-80`). Therefore a blanket “take master's shared files” would risk deleting release fixes even if the earlier rebase was mechanical.

### Branch-side candidates supported by documents, not a Git diff

| Paths / area | Evidence | Conflict prediction |
|---|---|---|
| `server/server.py`, `tests/unit/test_server_seq.py` | Per-connection sequence and pre-hello fixes (`docs/gen1_requirements.md:92,117`). | **CONFIRMED overlap** (see the exact-overlap table above): branch changed 47 lines, master changed 112 lines of this same file. High semantic risk is no longer just inferred — the intersection is real. Preserve wrong-save refusal and accepted-hello sequencing; do not overwrite the whole file. |
| `lua/connector.lua`, `tests/unit/test_connector_reconnect.py` | Reconnect queue clear (`docs/gen1_requirements.md:93`). | **[INFERENCE] Medium/high if master changes transport queues or hello order.** Reconnect's first event must not be stale gameplay. |
| `server/state.py`, `server/adapters/base.py`, `server/adapters/gen1_rby.py` | Adapter-isolation work is planned; server sync/watchdog work is in flight (`prep/PLAN_v3.9.md:892-895,953`; `docs/gen1_resume.md:73,79`). | **No textual overlap confirmed:** master's three commits do not touch any of these three files (checked directly against the diff-stat above). Semantic risk from a parallel `server/server.py` change still applies through shared call sites — these entries include planned/uncommitted work; they are not asserted to be in the committed diff at branch HEAD `d9f95e7`. Shared code must receive adapter-guard review (`docs/gen1_resume.md:25-30`). |
| `server/patcher.py`, `tests/unit/test_patcher_routes.py` | Previous rebase's patch checksum overlap (`prep/PLAN_v3.9.md:10-12,230-234`). | **CONFIRMED overlap, small**: branch changed 4 lines, master changed 2 lines of `server/patcher.py` (see the exact-overlap table above) — likely mechanical but read both diffs before assuming so. Re-derive current full checksums from the final patch; never paste abbreviated old MD5s. |
| `lua/gen1/`, `data/games/gen1_rby/`, `lua/gen1_write_safety.lua`, `lua/json_codec.lua` | Rewrite composition and generated dependencies (`lua/gen1/entry.lua:28-44,71-87`; `docs/gen1_requirements.md:135-137`). | **[INFERENCE] Lower textual risk if master does not touch them; semantic dependencies still require the full gate.** |
| `lua/hud.lua`, `tools/e2e_duo.py`, new driver/test/receipt files | HUD clear fix, harness work, driver fixes and receipt commits (`docs/gen1_resume.md:39-65,73-88`). | **[INFERENCE] Medium/high if master changes shared HUD/harness APIs.** Do not confuse frozen untracked `e2e_duo_head.py` with production code (`docs/gen1_resume.md:12-15`). |
| `lua/slink.lua`, `lua/slink_gen1.lua`, `tools/make_release.py` | Launcher/package cutover is still required (`lua/slink.lua:63-78`; `docs/gen1_gen2_runtime_checks.md:3-8`; `tools/make_release.py:58-107`; `prep/PLAN_v3.9.md:899-902`). | **[INFERENCE] High release risk even without a textual conflict:** a successful rebase can still ship the old client. Not asserted to be already changed in the branch diff. |
| `docs/gen1_requirements.md`, `docs/gen1_resume.md` and other release docs | Ledger authority and resume state (`docs/gen1_requirements.md:3-11`; `docs/gen1_resume.md:1-6`); regeneration inventory (`prep/PLAN_v3.9.md:860-873`). | **[INFERENCE] Preserve limits verbatim and re-check every claim against final receipts.** Planned docs updates are not a substitute for the Git inventory. |

## Recipe — coordinator only, after integration is quiescent

This is a proposed PowerShell recipe, not executed output. The pre-rebase tag and disabled Git maintenance/GC are the existing plan's rails (`prep/PLAN_v3.9.md:230-234`). **Never bare stash** is a requirement of this card; no confirming repository file was found in the permitted sources. The safe default below uses **no stash at all**: stop for a dirty tree; have each owner finish/commit their work or arrange an explicitly named, scoped preservation operation and record its identity. Never sweep another worker's files into an anonymous stash.

### 1. Resolve identity, work ownership and cleanliness

Work only in the real release worktree, not `` (a read-only copy) or the root checkout. Stop writers and the emulator lane before freezing the tip; commits/lane belong to the coordinator and other trees belong to their owners (`docs/agents/worker_card.md:9-18`; `docs/gen1_resume.md:25-30`).

```powershell
$repo = 'E:/Google Drive/SLink'
$wt = 'E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279'
git -c maintenance.auto=false -c gc.auto=0 -C $wt status --short --branch
git -c maintenance.auto=false -c gc.auto=0 -C $wt branch --show-current
git -c maintenance.auto=false -c gc.auto=0 -C $wt rev-parse HEAD
git -c maintenance.auto=false -c gc.auto=0 -C $wt rev-list --count d2c30fb..HEAD
git -c maintenance.auto=false -c gc.auto=0 -C $repo rev-parse master
```

Confirm the release branch and record the actual integrated tip at rebase time — this card's own query found HEAD `d9f95e7`, past both `471529b` and `c2605ae`, so re-run `rev-parse HEAD` rather than trusting either older marker. No automatic cleanup or auto-stash. In particular, the resume reports an uncommitted harness and a frozen untracked copy (`docs/gen1_resume.md:12-15`); coordinate their disposition instead of assuming cleanliness.

### 2. Obtain the missing commit and file inventories

```powershell
git -c maintenance.auto=false -c gc.auto=0 -C $repo log --reverse --format=fuller --name-status d2c30fb..master
git -c maintenance.auto=false -c gc.auto=0 -C $repo diff --stat d2c30fb master
git -c maintenance.auto=false -c gc.auto=0 -C $repo diff --name-only d2c30fb master
git -c maintenance.auto=false -c gc.auto=0 -C $wt diff --stat d2c30fb
git -c maintenance.auto=false -c gc.auto=0 -C $wt diff --name-only d2c30fb HEAD
git -c maintenance.auto=false -c gc.auto=0 -C $wt merge-base --is-ancestor d2c30fb HEAD
```

Require a clean tree before treating `git diff --stat d2c30fb` as committed branch evidence: without cleanliness it includes tracked working changes. Record all three master commits if three remain, their full touched-file lists, the full branch stat, and the exact intersection. If master has moved again, replace the task-reported three-commit assumption with the observed set. Inspect each intersecting change; a nonintersecting file set does not rule out API/behavior conflicts.

### 3. Freeze an immutable recovery point and master target

```powershell
$oldTip = git -c maintenance.auto=false -c gc.auto=0 -C $wt rev-parse HEAD
$shortTip = git -c maintenance.auto=false -c gc.auto=0 -C $wt rev-parse --short HEAD
$target = git -c maintenance.auto=false -c gc.auto=0 -C $repo rev-parse master
$backup = "pre-rebase-gen1-release-$shortTip"
git -c maintenance.auto=false -c gc.auto=0 -C $wt tag -a $backup $oldTip -m "Gen1 release before rebase onto $target"
```

Check every native Git exit code; stop on failure. If the backup tag exists, verify what it protects or choose a new unique name; **never force-update it**. Record `$oldTip`, `$target` and `$backup` outside transient shell history. A tag protects committed history only, which is why step 1 must settle uncommitted work. Recheck the target descends from `d2c30fb`; inspect merge commits before proceeding if the branch contains any, rather than blindly changing topology.

### 4. Rebase, resolve semantically, or abort

```powershell
git -c maintenance.auto=false -c gc.auto=0 -C $wt rebase --no-autostash $target
# On a conflict: inspect the stopped commit and unmerged files.
git -c maintenance.auto=false -c gc.auto=0 -C $wt status --short
git -c maintenance.auto=false -c gc.auto=0 -C $wt rebase --show-current-patch
git -c maintenance.auto=false -c gc.auto=0 -C $wt diff --name-only --diff-filter=U
```

Resolve only named files after reading both changes. Preserve master's current APIs **and** the branch's proven connection, queue, write-safety and trade behavior. During rebase, “ours” means the rebased/upstream side and “theirs” the replayed commit; do not use blanket ours/theirs checkout. Stage the explicit resolved paths, then:

```powershell
git -c maintenance.auto=false -c gc.auto=0 -C $wt rebase --continue
# If correct integration cannot be established instead:
git -c maintenance.auto=false -c gc.auto=0 -C $wt rebase --abort
```

These are alternatives, not commands to execute consecutively. Do not `--skip` a commit just to clear a conflict. Shared server changes route through adapter-guard before acceptance (`docs/gen1_resume.md:25-30`). The old patcher rule is not authority to delete later server fixes (`prep/PLAN_v3.9.md:230-234`; `docs/gen1_requirements.md:92-93`).

## Post-rebase verification

Run on the integrated release tree, not the prep copy. Every item below is proposed, **not run by this drafting card**.

1. **Confirm history and tree.** Review `git range-diff d2c30fb..$oldTip $target..HEAD` for dropped/altered fixes, confirm no unmerged or unintended dirty files, and confirm HEAD descends from the pinned master target. Prefix each Git call with `-c maintenance.auto=false -c gc.auto=0`. A clean rebase is not behavioral proof; current physical receipts and the final run remain mandatory (`prep/PLAN_v3.9.md:890-903,974-976`).
2. **Unit suite:** `python -m pytest tests/unit -q -p no:cacheprovider`. The historical comparison is 3084 passed at `1093ee7`, not an expected immutable final count (`docs/gen1_resume.md:95-96`). Investigate failures and unexpected collection losses; record the new count and SHA.
3. **Static checks:** `ruff check .` and `python tools/lua_syntax_check.py` (`docs/gen1_resume.md:97`; `tools/verify_gen1_release.py:98-99`).
4. **Gen 3 shared-runtime regression:** `/slink-test 3` in the project harness, as requested by this card. **†UNVERIFIED:** the slash-command definition was not available in the permitted source tree; do not treat it as a shell command or assume which tests it runs. Capture its actual expansion/result. The owner plan additionally names `python tools/e2e_duo.py --game gen3_rr --scenario trade` and `python tools/e2e_duo.py --game gen3_rr --scenario faint`; shared-code changes require Gen 3 verification first. Missing Gen 3 ROM/savestate must be disclosed, not counted as passed (`prep/PLAN_v3.9.md:892-897`).
5. **Quick integration gate:** `python tools/verify_gen1_release.py --quick`. This selects eight fast lanes and deliberately excludes the emulator lanes; its successful output explicitly says **not a release verdict** (`tools/verify_gen1_release.py:52-53,92-139,253-255,271-274`).
6. **Release authorization remains separate:** idle machine, full `python tools/verify_gen1_release.py`, all twelve lanes, current receipts, every non-limit ledger row SOURCE+PHYSICAL. Do not run heavy unit work beside the single emulator lane (`tools/verify_gen1_release.py:28-38`; `prep/PLAN_v3.9.md:898-899,974-976`).
7. **Package surface:** build with explicit `python tools/make_release.py --version 0.3.0`, extract to a separate scratch directory, boot a Red cart through the extracted launcher and observe the new client's hello. Explicit version avoids the packager's `dev` default (`tools/make_release.py:416-418`; `prep/PLAN_v3.9.md:899-902`). Verify the new runtime and JSON assets, not merely ZIP creation; the prep manifest still lists the old client (`tools/make_release.py:83-107`; `lua/gen1/entry.lua:28-44`).
8. **Owner-controlled finish:** recheck whether master moved since `$target`; if it did, reassess/rebase and repeat affected verification. Only after acceptance, coordinator fast-forwards root master with `git -c maintenance.auto=false -c gc.auto=0 -C "E:/Google Drive/SLink" merge --ff-only <verified-tip>`; owner controls push, `v0.3.0` tag and `gh release create` with the release note and actual runner output (`prep/PLAN_v3.9.md:890-903`). Never force-push or publish as part of this prep card.

## Acceptance for this draft

The two prep documents are proposals, not release authorization. The Git inventory above (base, three master commits, the 34-file diff-stat and the three-file exact overlap) is now filled in and command-verified; this rebase plan is actionable once the authorized coordinator re-confirms master has not moved again since this card ran. No final test result is fabricated — the rebase, merge and verification steps below remain proposed, not executed. Retain the exact ledger limits, including the bank-1 two-write window and silent force-faint demotion (`docs/gen1_requirements.md:139-167`), and refresh both documents against the final tree before attaching them to a release (`prep/PLAN_v3.9.md:870-889`).
