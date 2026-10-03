"""Worktrees under F:/slink-work/wt reach the shared inputs through a `.cache` JUNCTION, so a missing Gen 2
build is reported at its resolved path (the main checkout's .cache), not under the worktree. The absent-clone
skip must still recognise it: an unbuilt Gen 2 repo is an absent input there too, not a failure."""
import os
import subprocess
import sys

import pytest

import tests.conftest as conftest


def _junction(link, target):
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


def _fnf(path):
    return FileNotFoundError(2, "No such file or directory", str(path))


def test_a_missing_build_under_a_junctioned_cache_is_an_absent_clone(tmp_path, monkeypatch):
    shared = tmp_path / "main" / ".cache"
    (shared / "gen2-build").mkdir(parents=True)          # the cache exists, pokecrystal was never cloned
    worktree = tmp_path / "wt"
    worktree.mkdir()
    _junction(worktree / ".cache", shared)
    monkeypatch.setattr(conftest, "_GEN2_BUILD", str(worktree / ".cache" / "gen2-build"))
    missing = shared / "gen2-build" / "pokecrystal" / "pokecrystal.gbc"   # as the tool reports it: resolved
    assert conftest._absent_gen2_clone(_fnf(missing)) is not None


def test_a_present_clone_missing_a_file_still_fails_through_the_junction(tmp_path, monkeypatch):
    shared = tmp_path / "main" / ".cache"
    (shared / "gen2-build" / "pokecrystal").mkdir(parents=True)   # cloned, just not built
    worktree = tmp_path / "wt"
    worktree.mkdir()
    _junction(worktree / ".cache", shared)
    monkeypatch.setattr(conftest, "_GEN2_BUILD", str(worktree / ".cache" / "gen2-build"))
    missing = shared / "gen2-build" / "pokecrystal" / "pokecrystal.gbc"
    assert conftest._absent_gen2_clone(_fnf(missing)) is None


def test_a_wrapped_missing_build_is_still_found_through_the_chain(tmp_path, monkeypatch):
    shared = tmp_path / "main" / ".cache"
    (shared / "gen2-build").mkdir(parents=True)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    _junction(worktree / ".cache", shared)
    monkeypatch.setattr(conftest, "_GEN2_BUILD", str(worktree / ".cache" / "gen2-build"))
    try:
        try:
            raise _fnf(shared / "gen2-build" / "pokecrystal" / "pokecrystal.gbc")
        except FileNotFoundError as e:
            raise ValueError("HARNESS_ONLY_OVERLAY: malformed or unavailable manifest artifact") from e
    except ValueError as wrapped:
        assert conftest._absent_gen2_clone(wrapped) is not None


def test_a_path_outside_every_cache_root_is_not_an_absent_clone(tmp_path, monkeypatch):
    monkeypatch.setattr(conftest, "_GEN2_BUILD", str(tmp_path / "wt" / ".cache" / "gen2-build"))
    assert conftest._absent_gen2_clone(_fnf(tmp_path / "elsewhere" / "pokecrystal" / "x.gbc")) is None


@pytest.fixture(autouse=True)
def _cleanup_junctions(tmp_path):
    yield
    link = tmp_path / "wt" / ".cache"
    if link.exists() and sys.platform == "win32":
        subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)   # unlink only, never the target
