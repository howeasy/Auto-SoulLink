"""The release ZIP has to contain everything the Gen 1 client loads at runtime.

`tools/make_release.py` ships hand-maintained manifests, and the Gen 1 client resolves its
own dependencies at runtime -- `lua/gen1/entry.lua` dofiles ten Lua modules and reads five
JSONs off the repo root. A launcher rewire that only works in a git checkout is the exact
failure this pins: every file is present when you test locally and absent in the ZIP the
player downloads, where the first missing dofile is a Lua error in BizHawk's console.

So rather than restating the manifest, the closure is re-derived here from the Lua source
(every `"...lua"` / `"...json"` path and `require` name reachable from run.lua), and the
actual built ZIP has to contain it.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import make_release  # noqa: E402

_ENTRYPOINT = "lua/gen1/run.lua"
# Paths a Lua source names literally, e.g. "lua/gen1/reads.lua" or "/data/games/.../x.json".
_PATH_RE = re.compile(r'"/?((?:lua|data)/[\w./-]+\.(?:lua|json))"')
_REQUIRE_RE = re.compile(r'require\(\s*"([\w.]+)"\s*\)')
# lua/socket.lua requires these; they are the interpreter's, not files SLink ships.
_STDLIB = {"string", "math", "table", "io", "os", "coroutine", "debug", "utf8", "package"}


def _closure(start: str) -> set[str]:
    """Every repo-relative file reachable from `start` by dofile / require / load_json."""
    seen: set[str] = set()
    todo = [start]
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        path = os.path.join(_REPO, rel)
        if not rel.endswith(".lua") or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        found = set(_PATH_RE.findall(src))
        found |= {f"lua/{name.replace('.', '/')}.lua"
                  for name in _REQUIRE_RE.findall(src) if name not in _STDLIB}
        todo.extend(found - seen)
    return seen


@pytest.fixture(scope="module")
def archive(tmp_path_factory) -> set[str]:
    """Repo-relative paths in a real release ZIP (generators skipped: they are separately tested)."""
    out = tmp_path_factory.mktemp("release")
    zip_path = make_release.build_release(version="test", out_dir=out, skip_generators=True)
    prefix = "SLink-player-test/"
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert all(n.startswith(prefix) for n in names), "unexpected arcname outside the prefix"
    return {n[len(prefix):] for n in names}


def test_the_closure_is_the_gen1_client_and_nothing_stale():
    """A guard on the derivation itself: if this drifts, the manifest test means nothing."""
    closure = _closure(_ENTRYPOINT)
    for expected in ("lua/gen1/entry.lua", "lua/gen1/client.lua", "lua/json_codec.lua",
                     "lua/gen1_write_safety.lua", "lua/connector.lua", "lua/hud.lua",
                     "data/games/gen1_rby/profile.json"):
        assert expected in closure, f"{expected} was not derived from {_ENTRYPOINT}: {closure}"


def test_every_runtime_dependency_of_the_new_gen1_client_is_packaged(archive):
    missing = sorted(f for f in _closure(_ENTRYPOINT) if f not in archive)
    assert not missing, (
        "the release ZIP is missing files lua/gen1/run.lua loads at runtime; a player "
        f"extracting it would hit a Lua error on the first one: {missing}"
    )


def test_every_manifest_entry_names_a_file_that_exists():
    """The build's own pre-flight, run without building: a typo here fails the release."""
    listed = (
        [f"lua/{f}" for f in make_release._LUA_ROOT]
        + [f"lua/gen1/{f}" for f in make_release._LUA_GEN1]
        + [f"lua/clients/{f}" for f in make_release._LUA_CLIENTS]
        + [f"lua/games/{f}" for f in make_release._LUA_GAMES]
        + [f"data/games/{gen}/{f}"
           for gen, files in make_release._DATA_GAME_LUA.items() for f in files]
    )
    missing = [p for p in listed if not os.path.exists(os.path.join(_REPO, p))]
    assert not missing, f"manifest names files that do not exist: {missing}"


def test_the_old_gen1_client_is_not_shipped(archive):
    """The old client's files are out of the manifest (tooling half of the cutover); the files
    themselves stay on disk until their unit consumers are migrated."""
    assert "lua/clients/gen1_rby_client.lua" not in archive
    assert "lua/games/gen1_rby.lua" not in archive
