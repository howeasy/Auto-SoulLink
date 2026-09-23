"""The release ZIP has to contain everything the Gen 1 client loads at runtime.

`tools/make_release.py` ships hand-maintained manifests, and the Gen 1 client resolves its
own dependencies at runtime -- `lua/gen1/entry.lua` dofiles ten Lua modules and reads five
JSONs off the repo root. A launcher rewire that only works in a git checkout is the exact
failure this pins: every file is present when you test locally and absent in the ZIP the
player downloads, where the first missing dofile is a Lua error in BizHawk's console.

So rather than restating the manifest, the closure is re-derived here from the Lua source
(every quoted path / `require` name reachable from the two production launchers, `lua/slink.lua`
and `lua/slink_gen1.lua`), and the actual built ZIP has to contain it.
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

# The two scripts a player actually loads in BizHawk's Lua Console. Rooting the closure at
# `lua/gen1/run.lua` alone (as this test used to) misses anything only the launchers reach:
# slink.lua's own game_detect dispatch and its lua/games/gen{2,4,5}_*.lua registry, and the
# Gen 1 route's dofile of gen1/entry.lua for Entry.detect_title. Since U5, slink.lua's own
# Gen 2 route dofiles gen2/entry.lua and gen2/run.lua the same way, so the closure follows
# entry.lua's literal PACK_FILES/RECEIPT_FILES data paths too -- no separate root needed.
_ENTRYPOINTS = ["lua/slink.lua", "lua/slink_gen1.lua"]

# Paths a Lua source names literally: "lua/gen1/reads.lua", '/data/games/.../x.json', or a
# bare dir-relative literal like "gen1/entry.lua" (the `_dir .. "x"` idiom the launchers use,
# where _dir is their own directory, lua/). Single- or double-quoted.
_PATH_RE = re.compile(r'["\']/?([\w.-]+(?:/[\w.-]+)+\.(?:lua|json))["\']')
# require("x"), require('x'), require "x" (no parens), and pcall(require, "x") -- all four
# appear in this codebase. A bare `pcall(require, name)` with a variable (game_detect.lua's
# module registry) still can't be traced textually; that residual gap is real but its targets
# (lua/games/gen{2,4,5}_*.lua) are independently reached below via each client's own require.
_REQUIRE_RE = re.compile(r'\brequire\s*[(,]?\s*[\'"]([\w.]+)[\'"]')
# lua/socket.lua requires these; they are the interpreter's, not files SLink ships.
_STDLIB = {"string", "math", "table", "io", "os", "coroutine", "debug", "utf8", "package"}

# Extra roots a `require()` name can resolve against, beyond plain lua/<name>.lua: each Gen
# 2-5 client prepends lua/games/, lua/clients/, and its own data/games/<gen>/ to package.path
# (e.g. lua/clients/gen4_hgsspt_client.lua:56-59). Mirrors that search order so a name that
# only exists under one of these roots (e.g. "gen4_hgsspt_areas") resolves to the real file
# instead of a lua/<name>.lua that doesn't exist.
_REQUIRE_SEARCH_DIRS = ["lua", "lua/games", "lua/clients"] + [
    f"data/games/{gen}" for gen in make_release._DATA_GAME_LUA
]


def _require_to_path(name: str) -> str:
    rel = name.replace(".", "/") + ".lua"
    for d in _REQUIRE_SEARCH_DIRS:
        candidate = f"{d}/{rel}"
        if os.path.exists(os.path.join(_REPO, candidate)):
            return candidate
    return f"lua/{rel}"  # not found anywhere -- keep it so a real typo still surfaces as "missing"


def _resolve_literal_path(rel: str, literal: str) -> str | None:
    """A `_PATH_RE` match is repo-root-relative if it already carries the lua/ or data/
    prefix. Otherwise it's only a real dofile target when it appears in one of the launcher
    scripts at the lua/ root (the `_dir .. "x"` idiom, _dir == lua/) -- anywhere else a bare
    "sub/dir.lua"-shaped string is prose (e.g. a comment naming another file), and resolving
    it as if it were relative to *this* file's directory produces a path that doesn't exist.
    """
    if literal.startswith("lua/") or literal.startswith("data/"):
        return literal
    if rel.rsplit("/", 1)[0] == "lua":
        return f"lua/{literal}"
    return None


def _closure(starts: list[str]) -> set[str]:
    """Every repo-relative file reachable from `starts` by dofile / require / load_json."""
    seen: set[str] = set()
    todo = list(starts)
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
        found: set[str] = set()
        for m in _PATH_RE.findall(src):
            resolved = _resolve_literal_path(rel, m)
            if resolved:
                found.add(resolved)
        for name in _REQUIRE_RE.findall(src):
            if name not in _STDLIB:
                found.add(_require_to_path(name))
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
    closure = _closure(_ENTRYPOINTS)
    for expected in (
        # The Gen 1 client, reached via slink_gen1.lua -> gen1/run.lua -> gen1/entry.lua,
        # and via slink.lua's own Gen 1 route (dofile("gen1/entry.lua") for detect_title).
        "lua/gen1/entry.lua", "lua/gen1/client.lua", "lua/json_codec.lua",
        "lua/gen1_write_safety.lua", "lua/write_permit.lua", "lua/connector.lua", "lua/hud.lua",
        "lua/gb_checkpoint.lua", "lua/token_scanner.lua",
        "lua/admission.lua",
        "lua/hook_registry.lua", "lua/gb_hook_binding.lua",
        "lua/hello_session.lua", "lua/reply_dispatch.lua",
        "data/games/gen1_rby/profile.json",
        # Only reachable once the closure is rooted at the launchers, not run.lua alone.
        "lua/game_detect.lua",
        "lua/clients/gen4_hgsspt_client.lua",
        "lua/clients/gen5_bw_client.lua",
        "lua/games/gen4_hgsspt.lua",
        "lua/games/gen5_bw.lua",
        "data/games/gen4_hgsspt/gen4_hgsspt_areas.lua",
        "data/games/gen5_bw/gen5_bw_areas.lua",
        # The Gen 2 (Crystal) production graph, cut over at U5.
        "lua/gen2/entry.lua", "lua/gen2/run.lua", "lua/gen2/client.lua",
        "lua/gen2_write_safety.lua",
        "data/games/gen2_crystal/admission.json",
        "data/games/gen2_crystal/receipts/crystal.engine_sites.json",
        "data/games/gen2_gold/admission.json",
    ):
        assert expected in closure, f"{expected} was not derived from {_ENTRYPOINTS}: {closure}"


def test_every_runtime_dependency_of_the_new_gen1_client_is_packaged(archive):
    missing = sorted(f for f in _closure(_ENTRYPOINTS) if f not in archive)
    assert not missing, (
        "the release ZIP is missing files a launcher loads at runtime; a player "
        f"extracting it would hit a Lua error on the first one: {missing}"
    )


def test_every_manifest_entry_names_a_file_that_exists():
    """The build's own pre-flight, run without building: a typo here fails the release."""
    listed = (
        [f"lua/{f}" for f in make_release._LUA_ROOT]
        + [f"lua/gen1/{f}" for f in make_release._LUA_GEN1]
        + [f"lua/gen2/{f}" for f in make_release._LUA_GEN2]
        + [f"lua/clients/{f}" for f in make_release._LUA_CLIENTS]
        + [f"lua/games/{f}" for f in make_release._LUA_GAMES]
        + [f"data/games/{gen}/{f}"
           for gen, files in make_release._DATA_GAME_LUA.items() for f in files]
    )
    missing = [p for p in listed if not os.path.exists(os.path.join(_REPO, p))]
    assert not missing, f"manifest names files that do not exist: {missing}"


def test_the_shipped_socket_dll_is_packaged(archive):
    """lua/socket.lua (socket.lua:18-49) resolves its native lib to
    lua/x64/socket-<os>-<lua major>-<lua minor>.<ext> at runtime -- computed, not read from
    make_release's own _LUA_X64_OPTIONAL list, so a manifest that silently drops the row
    would still be caught. On Windows x64 / Lua 5.4 (this machine's BizHawk) that's
    socket-windows-5-4.dll; skip only if the tree itself doesn't have the DLL to ship."""
    dll_name = "socket-windows-5-4.dll"
    if not os.path.exists(os.path.join(_REPO, "lua", "x64", dll_name)):
        pytest.skip(f"lua/x64/{dll_name} not present in this checkout")
    arcname = f"lua/x64/{dll_name}"
    assert arcname in archive, (
        f"{arcname} exists in the tree (lua/socket.lua will try to load it on Windows "
        "x64/Lua 5.4) but the built release ZIP does not contain it"
    )


def test_the_old_gen1_client_is_not_shipped(archive):
    """The old client's files are out of the manifest (tooling half of the cutover); the files
    themselves stay on disk until their unit consumers are migrated."""
    assert "lua/clients/gen1_rby_client.lua" not in archive
    assert "lua/games/gen1_rby.lua" not in archive


def test_the_legacy_gen2_runtime_is_neither_derived_nor_shipped(archive):
    """P3b.8 removed the legacy Gen 2 client (Archipelago Crystal, its last route, is refused:
    O-25). Nothing a launcher reaches may name it, and the ZIP must not carry it."""
    legacy = {
        "lua/slink_gen2.lua", "lua/clients/gen2_crystal_client.lua", "lua/memory_gb.lua",
        "lua/games/gen2_crystal.lua", "lua/games/gen2_crystal_trainers.lua",
        "lua/gen2_crystal_areas.lua", "lua/gen2_crystal_locations.lua",
    }
    assert not legacy & _closure(_ENTRYPOINTS)
    assert not legacy & archive


def test_gb_companion_bundle_names_every_pure_overlay_ups():
    """--with-patch ships one UPS per Game Boy companion build: vanilla Red/Blue and the three
    pureRGB overlays (PLAN M3). A missing name here is a title whose players get no native trade."""
    assert set(make_release._GB_COMPANION_UPS) == {
        "SLink-RB-Red.ups", "SLink-RB-Blue.ups",
        "SLink-PureRed.ups", "SLink-PureBlue.ups", "SLink-PureGreen.ups"}
    for name in make_release._GB_COMPANION_UPS:
        assert "Yellow" not in name  # no Yellow build exists (no free WRAM for the mailbox)
