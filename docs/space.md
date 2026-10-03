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

Run `--apply` yourself, because the auto-mode classifier blocks bulk deletes. It takes the plan
file that the dry run wrote (`--plan` overrides the path). It rebuilds the plan from live state and
does nothing unless the rebuilt plan is identical, so re-run the dry run after any change.

## What gets scanned

The work root, `C:/slink-wt`, `C:/slink-cache`, `C:/slink`, `%LOCALAPPDATA%/Temp/{fs[0-9]*,
fsw-*,g2*,uiamb,exp-fc-*,pytest-of-*}`, the repo's `.claude/worktrees`, every registered git
worktree, orphan `.git/worktrees` admin dirs, and two Drive hazards:

- a conflict-copy ref such as `.git/refs/heads/master (1)`
- untracked files in the main checkout that match an old committed revision

Nothing outside that set is touched.

## Retention rules

prune removes:

- worktrees that are merged into master, clean, and untouched for `--older-than`. Their branches
  go with `git branch -d`, never `-D`.
- lanes and state dirs untouched for `--older-than`, when no running process names them.
- pytest and tool temps older than `--tmp-older-than`.
- orphan admin dirs, Drive conflict copies, and untracked copies of old revisions.

prune never removes:

- a dirty or unmerged worktree
- a worktree locked by a live pid, or locked with no pid
- an unregistered checkout
- `cache/`, `evidence/`, or anything whose name says evidence, receipt or proof
- an admin dir that a checkout still points at
- a conflict ref holding commits no branch contains

move-to-work-root moves each kind of item a different way:

- **Clean worktree:** `git worktree add --detach`, remove the old one, check the branch out
  again, then verify HEAD, a clean status and that the old dir is gone. `git worktree move`
  fails across volumes with "Improper link".
- **Dirty worktree:** `robocopy /E /XJ`, then `git worktree repair`. The old dir is removed only
  if `git status` matches.
- **Plain dirs:** `robocopy /MOVE /XJ`.

Junctions are never followed. They are recreated at the new path. The move refuses anything
locked by a live pid or used by a running process, and it lists the tracked lines that still
name an old path.
