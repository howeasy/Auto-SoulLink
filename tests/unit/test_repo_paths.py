"""tools/repo_paths.py: a junctioned `.cache` is inside the repo; a real `..` escape is not.

The F:/slink-work worktrees link `.cache` to the main checkout's (mklink /J). A resolve()+is_relative_to(root)
guard then refused every cached artifact ("artifact path escapes repository": 66 Gen 2 trade tests).
"""
import subprocess
import sys

import pytest

from tools.gen2_trade_lane import _repo_path
from tools.repo_paths import inside_repo


@pytest.fixture
def repo_with_junctioned_cache(tmp_path):
    if sys.platform != "win32":
        pytest.skip("mklink /J is Windows-only")
    repo, shared = tmp_path / "repo", tmp_path / "shared_cache"
    (shared / "gen2-build").mkdir(parents=True)
    (shared / "gen2-build" / "x.gbc").write_bytes(b"x")
    repo.mkdir()
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(repo / ".cache"), str(shared)], capture_output=True)
    if done.returncode:
        pytest.skip("cannot create a junction here")
    (tmp_path / "outside.txt").write_text("secret")
    return repo, shared


def test_a_junctioned_cache_is_inside_the_repo(repo_with_junctioned_cache):
    repo, shared = repo_with_junctioned_cache
    assert inside_repo(repo / ".cache" / "gen2-build" / "x.gbc", repo)
    assert _repo_path(repo, ".cache/gen2-build/x.gbc") == (shared / "gen2-build" / "x.gbc").resolve()


@pytest.mark.parametrize("bad", ["../outside.txt", "..\outside.txt", ".cache/../../outside.txt",
                                 ".cache/gen2-build/../../../outside.txt"])
def test_a_dotdot_escape_is_still_refused(repo_with_junctioned_cache, bad):
    repo, _ = repo_with_junctioned_cache
    assert not inside_repo(repo / bad, repo)
    with pytest.raises(ValueError, match="escapes repository"):
        _repo_path(repo, bad)


def test_an_ordinary_tree_without_a_junction_is_unchanged(tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "a.json").write_text("{}")
    assert inside_repo(tmp_path / "data" / "a.json", tmp_path)
    assert not inside_repo(tmp_path.parent / "elsewhere.txt", tmp_path)
    assert _repo_path(tmp_path, "data/a.json") == (tmp_path / "data" / "a.json").resolve()
