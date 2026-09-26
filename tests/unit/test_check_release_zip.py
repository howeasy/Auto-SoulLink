"""tests/unit/test_check_release_zip.py — the release-zip hygiene gate (card C4-ZIPCHK).

Drives tools/check_release_zip.py against small zips built in tmp_path from REAL blobs
(`git show`), so the gate's own logic is what is under test -- not make_release's build.

The four cases the card names: PASS on a faithful zip, FAIL on a modified member, FAIL on a
dev-only member, FAIL on a missing closure file. Plus the two invariants that keep the gate
honest over time: the closure list must stay a subset of make_release's manifest, and the one
allowance (a launcher rewritten by patch_launcher) must not hide a real difference.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "tools"))

import check_release_zip as gate  # noqa: E402

PREFIX = "SLink-player-test/"


def _blob(rel: str, rev: str = "HEAD") -> bytes:
    proc = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=_REPO, capture_output=True)
    assert proc.returncode == 0, f"no blob at {rev}:{rel}: {proc.stderr[:200]!r}"
    return proc.stdout


@pytest.fixture(scope="module")
def closure_bytes() -> dict[str, bytes]:
    """The 23 closure files as the repo has them right now (read once for the whole module)."""
    return {rel: _blob(rel) for rel in gate.GEN3_FRLG_CLOSURE}


def _zip(tmp_path: Path, members: dict[str, bytes], name: str = "SLink-player-test.zip") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for member, data in members.items():
            zf.writestr(PREFIX + member, data)
    return path


def _faithful(closure: dict[str, bytes]) -> dict[str, bytes]:
    return {**closure, "PLAYER_SETUP.md": b"# SLink - Player Setup Guide\n"}


def test_a_faithful_zip_passes_and_the_manifest_mode_demands_completeness(tmp_path, closure_bytes):
    path = _zip(tmp_path, _faithful(closure_bytes))

    failures, notes, count = gate.check_zip(path, repo=_REPO, require_manifest=False)
    assert failures == [], failures
    assert count == len(closure_bytes) + 1
    assert any("prefix" in n for n in notes)

    # The default (manifest) mode is the real gate: a closure-only zip is incomplete by design.
    failures, _, _ = gate.check_zip(path, repo=_REPO, require_manifest=True)
    assert any(f.startswith("missing member: ") for f in failures), failures


def test_a_modified_member_fails(tmp_path, closure_bytes):
    members = _faithful(closure_bytes)
    members["lua/gen3/reads.lua"] = members["lua/gen3/reads.lua"] + b"\n-- smuggled\n"
    failures, _, _ = gate.check_zip(_zip(tmp_path, members), repo=_REPO, require_manifest=False)
    assert any(f.startswith("lua/gen3/reads.lua: content differs") for f in failures), failures


@pytest.mark.parametrize("dev_only", ["tests/unit/test_something.py", "patch/build/rr_clean.gba",
                                      "lua/gen3/slink_gen3_session.baton", ".cache/x.bin",
                                      "lua/__pycache__/client.pyc", "save.sav"])
def test_a_dev_only_member_fails(tmp_path, closure_bytes, dev_only):
    members = _faithful(closure_bytes)
    members[dev_only] = b"x"
    failures, _, _ = gate.check_zip(_zip(tmp_path, members), repo=_REPO, require_manifest=False)
    assert any(f.startswith("dev-only member present: ") and dev_only in f for f in failures), failures


def test_a_missing_closure_file_fails(tmp_path, closure_bytes):
    members = _faithful(closure_bytes)
    del members["lua/core/deferred.lua"]
    failures, _, _ = gate.check_zip(_zip(tmp_path, members), repo=_REPO, require_manifest=False)
    assert any("closure file missing" in f and "lua/core/deferred.lua" in f for f in failures), failures


def test_the_closure_list_is_a_subset_of_the_release_manifest():
    manifest = gate.load_manifest(_REPO)
    expected, generated, optional = gate.expected_members(manifest)
    known = set(expected) | generated | optional
    assert set(gate.GEN3_FRLG_CLOSURE) <= known, sorted(set(gate.GEN3_FRLG_CLOSURE) - known)
    # ...and the DLL the closure needs is optional-by-construction, not missing from the manifest.
    assert "lua/x64/socket-windows-5-4.dll" in expected


def test_the_launcher_allowance_hides_only_the_slink_lines(tmp_path, closure_bytes):
    """patch_launcher rewrites SLINK_HOST/PORT/PLAYER in the _LAUNCHER_SCRIPTS files
    (lua/slink_gen*.lua; slink.lua itself carries no assignments). A launcher differing only
    there is the intended artifact; anything else is not."""
    launcher = "lua/slink_gen3.lua"
    original = _blob(launcher)
    patched = original.replace(b'SLINK_HOST   = "127.0.0.1"', b'SLINK_HOST   = "10.0.0.5"')
    assert patched != original, "the fixture line moved; update this test"

    members = _faithful(closure_bytes)
    members[launcher] = patched
    failures, notes, _ = gate.check_zip(_zip(tmp_path, members), repo=_REPO, require_manifest=False)
    assert failures == [], failures
    assert any("SLINK_* lines" in n for n in notes), notes

    members[launcher] = patched + b"\n-- not a launcher edit\n"
    failures, _, _ = gate.check_zip(_zip(tmp_path, members), repo=_REPO, require_manifest=False)
    assert any(f.startswith(f"{launcher}: content differs") for f in failures), failures


def test_the_cli_exits_zero_on_a_faithful_zip(tmp_path, closure_bytes):
    path = _zip(tmp_path, _faithful(closure_bytes))
    proc = subprocess.run([sys.executable, str(_REPO / "tools" / "check_release_zip.py"),
                           str(path), "--repo", str(_REPO), "--no-manifest"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS:" in proc.stdout and "closure files present" in proc.stdout


def test_every_make_release_lua_list_is_an_expected_member():
    """Each lua/<dir> list make_release ships must be in the checker's manifest: the Gen 2 merge added
    _LUA_GEN2 to make_release and the RR zip check failed 'member is not in make_release's manifest:
    lua/gen2/*' at a9ad03d3. A new _LUA_<dir> list without a checker branch fails here, not live."""
    import re
    m = gate.load_manifest(_REPO)
    exp, _gen, _opt = gate.expected_members(m)
    lists = [n for n in vars(m) if re.fullmatch(r"_LUA_[A-Z0-9]+", n) and n != "_LUA_X64_OPTIONAL"]
    assert lists, "no _LUA_* lists found"
    for name in lists:
        for f in getattr(m, name):
            assert any(k.endswith("/" + f) or k == f"lua/{f}" for k in exp), (name, f)
