"""Repo-containment checks that survive a junctioned `.cache`.

Worktrees under F:/slink-work/wt link `.cache` to the main checkout's (mklink /J), so a path under
`.cache/` RESOLVES outside the worktree. A guard that asked only `resolved.is_relative_to(root.resolve())`
refused every cached artifact there (66 Gen 2 trade tests, the Gen 2 live gates' ROM check). The cache's own
resolved target is therefore a second allowed root. A real `..` escape still resolves under neither and is refused.
"""
from __future__ import annotations

from pathlib import Path


def repo_roots(root) -> tuple[Path, ...]:
    """The repo and the resolved target of its `.cache` (the same directory unless `.cache` is a junction)."""
    root = Path(root)
    return root.resolve(), (root / ".cache").resolve()


def inside_repo(path, root) -> bool:
    """Does `path`, resolved, lie under the repo or under its (possibly junctioned) `.cache`?"""
    path = Path(path).resolve()
    return any(path.is_relative_to(allowed) for allowed in repo_roots(root))
