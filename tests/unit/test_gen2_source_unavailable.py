"""SourceUnavailable is NARROW: only an ABSENT pinned clone (.cache/gen2-build/<repo> not a
directory) becomes the named skip. A clone that exists but is wrong -- another commit, a dirty
tree, not a git repository at all -- and a sym/map hash mismatch stay plain ValueError hard
failures, and the tests/conftest.py wrapper lets them through un-skipped. (Gen1-Collab2's
condition on the unprovisioned-checkout fix: absent != tampered must be held by a test.)"""
import shutil
import subprocess
from pathlib import Path

import pytest
from _pytest.outcomes import Skipped

import tools.gen2_source_data as sd

REAL = Path(sd.ROOT)
WRAPPED = sd._load_context
RAW = WRAPPED.__wrapped__
LOCKED = "7a7881d0d62e0ddbd82dcf10e7116807487ac651"   # data/gen2_sources.lock.json pokecrystal


def _root(tmp_path):
    """A root with the committed lock, provenance and pinned sym/map files, and no clone."""
    for rel in ("data/gen2_sources.lock.json", "data/gen2/build_provenance.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REAL / rel, tmp_path / rel)
    for name in ("pokecrystal", "pokecrystal11", "pokegold", "pokesilver"):
        for ext in ("sym", "map"):
            shutil.copyfile(REAL / "data/gen2" / f"{name}.{ext}", tmp_path / "data/gen2" / f"{name}.{ext}")
    return tmp_path


def _wrong(exc):
    return isinstance(exc, ValueError) and not isinstance(exc, sd.SourceUnavailable)


def test_an_absent_clone_is_source_unavailable_and_the_wrapper_skips_it(tmp_path):
    root = _root(tmp_path)
    with pytest.raises(sd.SourceUnavailable, match="pokecrystal not cloned"):
        RAW("crystal", root)
    with pytest.raises(Skipped, match="pokecrystal not cloned"):
        WRAPPED("crystal", root)


def test_a_clone_at_another_commit_hard_fails_and_is_not_skipped(tmp_path):
    root = _root(tmp_path)
    source = root / ".cache/gen2-build/pokecrystal"
    source.mkdir(parents=True)
    git = ["git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    (source / "x").write_text("x")
    subprocess.run([*git, "add", "x"], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    with pytest.raises(ValueError, match="differs from locked commit") as raw:
        RAW("crystal", root)
    assert _wrong(raw.value)
    with pytest.raises(ValueError, match="differs from locked commit"):
        WRAPPED("crystal", root)     # not Skipped


def test_a_directory_that_is_not_a_repository_hard_fails(tmp_path):
    root = _root(tmp_path)
    (root / ".cache/gen2-build/pokecrystal").mkdir(parents=True)
    with pytest.raises(ValueError) as raw:
        RAW("crystal", root)
    assert _wrong(raw.value)
    with pytest.raises(ValueError):
        WRAPPED("crystal", root)


def test_a_dirty_clone_at_the_locked_commit_hard_fails(tmp_path, monkeypatch):
    root = _root(tmp_path)
    source = (root / ".cache/gen2-build/pokecrystal")
    source.mkdir(parents=True)
    answers = {"--show-toplevel": str(source.resolve()), "HEAD": LOCKED, "--porcelain": " M engine/x.asm"}
    monkeypatch.setattr(sd, "_git", lambda _s, *args: next(v for k, v in answers.items() if k in args))
    with pytest.raises(ValueError) as raw:
        RAW("crystal", root)
    assert _wrong(raw.value)
    with pytest.raises(ValueError):
        WRAPPED("crystal", root)


def test_a_pinned_hash_mismatch_hard_fails_even_with_the_clone_absent(tmp_path):
    root = _root(tmp_path)
    sym = root / "data/gen2/pokecrystal.sym"
    sym.write_bytes(sym.read_bytes() + b"; tampered\n")
    with pytest.raises(ValueError, match="differs from pinned") as raw:
        RAW("crystal", root)
    assert _wrong(raw.value)
    with pytest.raises(ValueError, match="differs from pinned"):
        WRAPPED("crystal", root)
