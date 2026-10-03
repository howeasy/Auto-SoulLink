# Disk space: one work root

**C: is not a work drive.** Every SLink scratch lives under one work root,
`$SLINK_WORK_ROOT` (default `F:/slink-work`):

| Subdir | Holds |
|---|---|
| `wt/` | git worktrees |
| `lanes/` | emulator lanes and their state dirs |
| `tmp/` | pytest and tool temps (`PYTEST_DEBUG_TEMPROOT` points here) |
| `cache/` | heavy pinned inputs (ROM builds, pret/expansion pins, JDK) |
| `evidence/` | archived run evidence that is not committed |

Tools get paths from `work_root()` in `tools/slink_space.py` instead of hard-coding them:

```python
from slink_space import work_root          # tools/ on sys.path
lane = work_root("lanes") / "my-lane"      # creates F:/slink-work/lanes on first use
```

Shell: `python tools/slink_space.py root lanes`.

## Commands

```bash
python tools/slink_space.py report [--json]          # sizes, worktrees, stale items, hazards
python tools/slink_space.py prune                    # DRY RUN: prints the plan, writes it to tmp/
python tools/slink_space.py prune --apply            # owner-run; re-scans, aborts if anything changed
python tools/slink_space.py move-to-work-root        # DRY RUN: plan to move C: content here
python tools/slink_space.py move-to-work-root --apply
```

`--older-than` (default `3d`) sets the age at which lanes, state dirs and merged worktrees count
as stale. `--tmp-older-than` (default `2h`) does the same for pytest and tool temps.

Run `--apply` yourself, because the auto-mode classifier blocks bulk deletes. Pass the same
`--repo`, `--older-than` and `--tmp-older-than` as the dry run. The repo, the thresholds and
the scanned locations come from the command, never from the plan file. The plan file is
hash-bound and its params must match. The apply then rebuilds the plan from live state and does
nothing unless the rebuilt plan is identical, so re-run the dry run after any change. Only one
`--apply` runs at a time per work root (`tmp/slink-space-apply.lock`).

## What gets scanned

The work root, `C:/slink-wt`, `C:/slink-cache`, `C:/slink`, `%LOCALAPPDATA%/Temp/{fs[0-9]*,
fsw-*,g2*,uiamb,exp-fc-*,pytest-of-*}`, the repo's `.claude/worktrees`, every registered git
worktree, orphan `.git/worktrees` admin dirs, and two Drive hazards:

- a conflict-copy ref such as `.git/refs/heads/master (1)`
- untracked files in the main checkout that Drive restored: `name (N).ext` copies, plus
  `lua/memory_gba.lua` and `server/adapters/gen2_crystal.py`. Any other untracked file that
  equals an old revision is refused, because it may be a deliberate `git rm --cached`.

Nothing outside that set is touched. "Merged" means merged into `master`; the repo is
master-based, so the branch name is fixed.

A process counts as using a path when its command line names the path (whole path components)
or its current directory is inside it. Current directories are read from the process PEB on
64-bit Windows and from `/proc` elsewhere. Without a cwd scan, temps get a 24 h floor.

## Retention rules

**C: content is moved, not deleted.** On C:, prune deletes only pytest temps and pure junk:
orphan admin dirs, Drive conflict copies, and the two known restored files. Old C: lanes, state
dirs and merged C: worktrees go to the work root through move-to-work-root. Old lanes land in
`evidence/`.

Off C:, prune also removes:

- worktrees that are merged into master, clean, and untouched for `--older-than`. Their branches
  go with `git branch -d`, never `-D`.
- lanes and state dirs untouched for `--older-than`, when no process uses them.
- pytest and tool temps older than `--tmp-older-than`, when no process uses them.

Every worktree removal re-checks registration, lock and `git status` at execution time.

prune never removes:

- a dirty or unmerged worktree
- a worktree locked by a live pid, or locked with no pid
- an unregistered checkout, or a lane or temp dir that holds a `.git` entry
- `cache/`, `evidence/`, or anything whose name says evidence, receipt or proof
- an admin dir that a checkout still points at
- a conflict ref holding commits no branch contains

move-to-work-root moves each kind of item a different way:

- **Clean worktree:** `git worktree add --detach`, verify, remove the old one, check the branch
  out again, then verify HEAD, a clean status and that the old dir is gone. If any step after
  the add fails, it rolls back to the original worktree. `git worktree move` fails across
  volumes with "Improper link".
- **Dirty worktree:** `robocopy /E /XJ`, then `git worktree repair`. The old dir is removed only
  if `git status` matches.
- **Plain dirs:** `robocopy /MOVE /XJ`.

Junctions are never followed. They are recreated at the new path. Link detection reads reparse
attributes off `lstat`; where those are unavailable, nothing is deleted or copied. The move
refuses anything locked by a live pid or used by a running process, and it lists the tracked
lines that still name an old path.

## Known gaps

- CI does not run these tests across Python versions (CI is not pushed). The pre-3.12 path is
  covered only by tests that delete `os.path.isjunction`.
- `git worktree prune` (and git's auto-gc, which runs it on commit) is global: it can drop an
  admin dir that this tool refuses. Setting `gc.worktreePruneExpire=never` stops the auto-gc
  part.
