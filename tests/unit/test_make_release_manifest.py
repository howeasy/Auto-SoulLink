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

import json
import os
import re
import sys
import zipfile

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import make_release  # noqa: E402


def test_gen2_player_manifest_names_each_overlay_binding_and_its_own_proofs():
    paths = {f"data/games/{game}/{name}" for game, names in make_release._DATA_GAME_LUA.items() for name in names}
    paths |= {f"lua/gen2/{name}" for name in make_release._LUA_GEN2}
    for title in ("crystal", "gold", "silver"):
        prefix = f"data/games/gen2_{title}/"
        assert prefix + "overlay/binding.json" in paths
        assert prefix + f"receipts/overlay/{title}.engine_sites.json" in paths
        assert prefix + f"receipts/overlay/{title}.write_window.json" in paths
    assert "lua/gen2/artifact.lua" in paths


@pytest.mark.parametrize("status", ["BUILT", "ADMITTED"])
def test_gen2_overlay_shipping_requirement_follows_its_catalog(tmp_path, monkeypatch, status):
    import json
    for title in ("crystal", "gold", "silver"):
        path = tmp_path / f"data/games/gen2_{title}/admission.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"artifacts": [{"kind": "overlay", "status": status,
                                                  "selection": "SELECTED" if status == "ADMITTED" else "FUTURE"}]}))
    manifest = make_release.data_game_files(tmp_path)
    for title in ("crystal", "gold", "silver"):
        names = manifest[f"gen2_{title}"]
        assert ("overlay/binding.json" in names) == (status == "ADMITTED")
        assert (f"receipts/overlay/{title}.write_window.json" in names) == (status == "ADMITTED")
    if status == "ADMITTED":
        # Preflight must refuse these declared but absent files, before producing a ZIP.
        monkeypatch.setattr(make_release, "REPO_ROOT", tmp_path)
        with pytest.raises(SystemExit):
            make_release.build_release(version="model", out_dir=tmp_path / "out", skip_generators=True)
        assert not (tmp_path / "out/SLink-player-model.zip").exists()


@pytest.mark.parametrize("status", ["BUILT", "ADMITTED"])
def test_the_companion_ups_set_follows_the_same_catalog_test_as_the_manifest(tmp_path, status):
    """E1: the two halves of a release must not disagree. data_game_files gated the binding sidecar and
    the proofs on the catalog, but the companion UPS list was a static tuple, so a BUILT Gen 2 overlay
    shipped its patch and withheld the evidence explaining why the launcher refuses it."""
    import json
    for title in ("crystal", "gold", "silver"):
        path = tmp_path / f"data/games/gen2_{title}/admission.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"artifacts": [{"kind": "overlay", "status": status,
                                                  "selection": "SELECTED" if status == "ADMITTED" else "FUTURE"}]}))
    ups = make_release.gb_companion_ups(tmp_path)
    manifest = make_release.data_game_files(tmp_path)
    gen2_ups = {"SLink-Crystal.ups", "SLink-Gold.ups", "SLink-Silver.ups"}
    assert (gen2_ups & set(ups)) == (gen2_ups if status == "ADMITTED" else set())
    # Gen 1 / pureRGB are unaffected by a Gen 2 catalog state.
    assert {"SLink-RB-Red.ups", "SLink-PureGreen.ups"} <= set(ups)
    for title in ("crystal", "gold", "silver"):
        assert ("overlay/binding.json" in manifest[f"gen2_{title}"]) == (status == "ADMITTED")


def test_the_gen2_ups_and_the_binding_sidecar_agree_by_construction(tmp_path):
    """One source of truth: whatever gb_companion_ups and data_game_files decide about a title, they
    decide the same thing. A future edit that re-gates one and not the other fails here."""
    import json
    for title, status in (("crystal", "ADMITTED"), ("gold", "BUILT"), ("silver", "ADMITTED")):
        path = tmp_path / f"data/games/gen2_{title}/admission.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"artifacts": [{"kind": "overlay", "status": status,
                                                  "selection": "SELECTED" if status == "ADMITTED" else "FUTURE"}]}))
    ups, manifest = make_release.gb_companion_ups(tmp_path), make_release.data_game_files(tmp_path)
    for title in ("crystal", "gold", "silver"):
        admitted = f"SLink-{title.capitalize()}.ups" in ups
        assert admitted == ("overlay/binding.json" in manifest[f"gen2_{title}"]), title


def test_a_malformed_catalog_is_an_error_not_a_silent_skip(tmp_path):
    import json
    path = tmp_path / "data/games/gen2_crystal/admission.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"artifacts": [{"kind": "overlay", "status": "PLANNED"}]}))
    with pytest.raises(ValueError, match="catalog missing or malformed"):
        make_release.overlay_state("gen2_crystal", tmp_path)


# The scripts a player actually loads in BizHawk's Lua Console. Rooting the closure at
# `lua/gen1/run.lua` alone (as this test used to) misses anything only the launchers reach:
# slink.lua's own game_detect dispatch and its lua/games/gen{4,5}_*.lua registry, the
# Gen 1 route's dofile of gen1/entry.lua for Entry.detect_title, the Gen 2 route's dofile of
# gen2/entry.lua and gen2/run.lua (U5; the closure follows entry.lua's literal
# PACK_FILES/RECEIPT_FILES data paths too), and (P4) the Gen 3 route's dofile of
# gen3/entry.lua for Entry.admit/header_code plus lua/slink_gen3.lua itself, which is now a
# thin dofile("slink.lua") wrapper (docs/gen3/research/p4_gen1_contract_map.md §3.6) and so
# reaches the same closure as slink.lua, plus gen3/run.lua once admitted.
_ENTRYPOINTS = ["lua/slink.lua", "lua/slink_gen1.lua", "lua/slink_gen3.lua"]

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
    shipping = make_release.data_game_files()
    todo = list(starts)
    while todo:
        rel = todo.pop()
        parts = rel.split("/")
        if len(parts) >= 4 and parts[:2] == ["data", "games"] and parts[2].startswith("gen2_"):
            name = "/".join(parts[3:])
            if (name == "overlay/binding.json" or name.startswith("receipts/overlay/")) and name not in shipping[parts[2]]:
                continue  # unactivated overlay paths are literals, never clean runtime dependencies
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
        # The Gen 3 route (slink.lua -> gen3/run.lua -> gen3/entry.lua) and its shared core
        # (P4 C4-1/C4-4). gen3_rr ships even though a gen3_frlg cartridge never loads it at
        # runtime, because Entry.admit/admission_table reads every pack's sites to admit any
        # cartridge (entry.lua Entry.PACK_FILES names both packs literally).
        "lua/gen3/run.lua", "lua/gen3/entry.lua", "lua/gen3/client.lua",
        "lua/gen3/trade_journal.lua",
        "lua/core/session.lua", "lua/core/identity.lua", "lua/core/deferred.lua",
        "data/games/gen3_frlg/profile.json", "data/games/gen3_rr/engine_signals.json",
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
        + [f"lua/gen3/{f}" for f in make_release._LUA_GEN3]
        + [f"lua/core/{f}" for f in make_release._LUA_CORE]
        + [f"lua/gen2/{f}" for f in make_release._LUA_GEN2]
        + [f"lua/clients/{f}" for f in make_release._LUA_CLIENTS]
        + [f"lua/games/{f}" for f in make_release._LUA_GAMES]
        + [f"data/games/{gen}/{f}"
           for gen, files in make_release.data_game_files().items() for f in files]
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


def test_the_licence_and_notices_ship_with_the_code(archive):
    """Review cx-66e7600f F3: MIT (ours, Alpine's, LuaSocket's for the DLL above) requires the
    copyright and permission notice to travel with the copies."""
    assert {"LICENSE", "NOTICE.md"} <= archive


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
    """--with-patch ships one UPS per Game Boy companion build that is ADMITTED: vanilla Red/Blue and
    the three pureRGB overlays (PLAN M3) always; a Gen 2 title's overlay UPS only once its catalog row
    is ADMITTED, because until then lua/gen2/entry.lua refuses the cartridge the patch would produce."""
    assert set(make_release._GB_COMPANION_UPS) == {
        "SLink-RB-Red.ups", "SLink-RB-Blue.ups",
        "SLink-PureRed.ups", "SLink-PureBlue.ups", "SLink-PureGreen.ups"}
    assert dict(make_release._GEN2_OVERLAY_UPS) == {
        "crystal": "SLink-Crystal.ups", "gold": "SLink-Gold.ups", "silver": "SLink-Silver.ups"}
    shipped = set(make_release.gb_companion_ups())
    assert set(make_release._GB_COMPANION_UPS) <= shipped
    assert shipped - set(make_release._GB_COMPANION_UPS) == {
        name for title, name in make_release._GEN2_OVERLAY_UPS.items()
        if make_release.overlay_state(f"gen2_{title}") == "ADMITTED"}
    for name in shipped:
        assert "Yellow" not in name  # no Yellow build exists (no free WRAM for the mailbox)


def _entry_pack_files() -> dict[str, dict[str, str]]:
    """`Entry.PACK_FILES` from the real `lua/gen3/entry.lua`, via lupa -- every pack it names is
    opened unconditionally by `Entry.admission_table` (entry.lua:121-140), routed or not, so a
    release zip missing one of these paths refuses EVERY GBA cartridge (F1, cx-7b74a808)."""
    import lupa

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    entry_path = os.path.join(_REPO, "lua", "gen3", "entry.lua").replace(os.sep, "/")
    entry = lua.eval(f'dofile("{entry_path}")')
    out: dict[str, dict[str, str]] = {}
    for pack, files in entry.PACK_FILES.items():
        out[str(pack)] = {str(k): str(v) for k, v in files.items()}
    return out


def test_every_entry_pack_file_is_in_the_release_manifest():
    """F3: the falsifier for F1 -- a future pack registered in `Entry.PACK_FILES` but left out
    of `make_release._DATA_GAME_LUA` repeats the gen3_emerald bug (a release zip that refuses
    every GBA cartridge, not just the unshipped pack's own). MUTATION-CHECK: comment out the
    "gen3_emerald" row in tools/make_release.py's `_DATA_GAME_LUA` and this test goes red."""
    manifest_paths = {
        f"data/games/{gen}/{f}"
        for gen, files in make_release._DATA_GAME_LUA.items() for f in files
    }
    for pack, files in _entry_pack_files().items():
        for key, rel in files.items():
            assert rel in manifest_paths, (
                f"Entry.PACK_FILES.{pack}.{key} = {rel!r} is not in make_release's "
                "_DATA_GAME_LUA manifest -- a release zip would ship without it"
            )


def test_every_emerald_adapter_data_file_is_in_the_release_manifest():
    """OMP cx-9f0eacae F1: server/adapters/gen3_frlge.py `_emerald_json` returns {} for a missing
    file, so an unshipped Emerald table fails OPEN (the fixed-gift clause bypasses silently vanish)
    instead of refusing. Every file `_load_emerald()` opens must ship. MUTATION-CHECK: drop
    "statics.json" from the gen3_emerald row of `_DATA_GAME_LUA` and this goes red."""
    import inspect
    import re

    from server.adapters import gen3_frlge
    opened = set(re.findall(r'_emerald_json\("([^"]+)"\)', inspect.getsource(gen3_frlge._load_emerald)))
    assert opened >= {"area_map.json", "statics.json", "write_checkpoint.json"}, opened
    missing = opened - set(make_release._DATA_GAME_LUA["gen3_emerald"])
    assert not missing, f"gen3_emerald adapter tables not shipped in the release zip: {sorted(missing)}"


def test_the_retired_gen3_modules_are_not_shipped(archive):
    """C5-6 (owner ruling 24): the old Gen 3 client is deleted and lua/games/gen3_frlge.lua stays
    only as cited source material; neither may ship in the player ZIP."""
    assert "lua/clients/gen3_frlge_client.lua" not in archive
    assert "lua/games/gen3_frlge.lua" not in archive
    assert "gen3_frlge.lua" not in make_release._LUA_GAMES


def test_with_patch_ships_a_gen2_overlay_ups_only_once_that_title_is_admitted(tmp_path):
    """RELEASE-EVIDENCE-TOOLING: a Gen 2 companion UPS lands under companion/ with its published bytes
    ONLY when that title's overlay row is ADMITTED. Shipping it for a BUILT overlay handed the user a patch
    whose cartridge lua/gen2/entry.lua refuses, while data_game_files (correctly) withheld the binding
    sidecar and proofs that would explain it. Gen 1/pure/Gen 3 companions are unaffected."""
    import hashlib
    import json
    from pathlib import Path

    outputs = json.loads((Path(_REPO) / "data/gen2/overlay_provenance.json").read_text(encoding="utf-8"))["outputs"]
    states = {t: make_release.overlay_state(f"gen2_{t}") for t in ("crystal", "gold", "silver")}
    admitted = {t for t, s in states.items() if s == "ADMITTED"}
    zip_path = make_release.build_release(version="t", out_dir=tmp_path, skip_generators=True, with_patch=True,
                                          allow_unstamped=True)
    with zipfile.ZipFile(zip_path) as zf:
        companion = {n.split("/", 1)[1]: zf.read(n) for n in zf.namelist() if "/companion/" in n}
    for row in outputs.values():
        name, title = Path(row["ups"]["file"]).name, row["slink_title"]
        if title in admitted:
            assert hashlib.sha256(companion[f"companion/{name}"]).hexdigest() == row["ups"]["sha256"]
        else:
            assert f"companion/{name}" not in companion, \
                f"{title} overlay is {states[title]}, so its UPS must not ship"
    assert set(companion) - {f"companion/{Path(r['ups']['file']).name}" for r in outputs.values()
                              if r["slink_title"] in admitted} == {
        "companion/SLink-RR.ups", "companion/COMPANION_PATCH.md", "companion/SLink-RB-Red.ups",
        "companion/SLink-RB-Blue.ups", "companion/SLink-PureRed.ups", "companion/SLink-PureBlue.ups",
        "companion/SLink-PureGreen.ups", "companion/SLink-FireRed.ups", "companion/SLink-LeafGreen.ups",
        "companion/SLink-Emerald.ups", "companion/gen3_companions.json", "companion/companion_version.json"}
    native=json.loads(companion["companion/gen3_companions.json"])
    for row in native["titles"].values():
        assert hashlib.sha256(companion["companion/"+row["patch"]]).hexdigest()==row["ups_sha256"]


# ---- the release carries its own version: companions must be stamped for it (owner ruling 2026-10-02) ----

def _stamp_record(dist, version, files):
    import hashlib
    import json

    import stamp_release
    dist.mkdir(parents=True, exist_ok=True)
    files = {**{name: name.encode() for name in stamp_release.SHIPPED}, **files}        # a release ships every companion
    for name, body in files.items():
        (dist / name).write_bytes(body)
    (dist / "companion_version.json").write_text(json.dumps({
        "schema": stamp_release.SCHEMA, "version": version, "families": {"rb": version},
        "files": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}), encoding="utf-8")


def test_companions_stamped_for_the_release_pass(tmp_path):
    _stamp_record(tmp_path, "v1.2.3", {"SLink-RR.ups": b"rr", "SLink-RB-Red.ups": b"red"})
    assert make_release.companion_stamp_errors("1.2.3", tmp_path) == []
    assert make_release.companion_stamp_errors("v1.2.3", tmp_path) == []


def test_companions_stamped_for_another_version_are_refused(tmp_path):
    _stamp_record(tmp_path, "dev", {"SLink-RR.ups": b"rr"})
    errors = make_release.companion_stamp_errors("1.2.3", tmp_path)
    assert errors and "stamped 'dev'" in errors[0] and "stamp_release.py --version v1.2.3" in errors[0]
    assert make_release.companion_stamp_errors("dev", tmp_path) == []


def test_a_companion_edited_after_stamping_or_never_covered_is_refused(tmp_path):
    _stamp_record(tmp_path, "v1.2.3", {})
    (tmp_path / "SLink-RR.ups").write_bytes(b"edited")
    record = tmp_path / "companion_version.json"
    doc = json.loads(record.read_text(encoding="utf-8"))
    del doc["files"]["SLink-Crystal.ups"]
    record.write_text(json.dumps(doc), encoding="utf-8")
    errors = make_release.companion_stamp_errors("1.2.3", tmp_path)
    assert any("SLink-RR.ups changed after it was stamped" in e for e in errors)
    assert any("SLink-Crystal.ups is not covered" in e for e in errors)


def test_a_missing_record_is_refused_and_build_release_exits(tmp_path, monkeypatch):
    assert "companion_version.json is missing" in make_release.companion_stamp_errors("1.2.3", tmp_path)[0]
    monkeypatch.setattr(make_release, "companion_stamp_errors", lambda version, dist=None: ["nope"])
    with pytest.raises(SystemExit):
        make_release.build_release(version="1.2.3", out_dir=tmp_path, skip_generators=True, with_patch=True)


def test_a_shipped_companion_missing_from_dist_is_refused_even_if_the_record_vouches_for_it(tmp_path):
    _stamp_record(tmp_path, "v1.2.3", {})
    (tmp_path / "SLink-Emerald.ups").unlink()
    errors = make_release.companion_stamp_errors("1.2.3", tmp_path)
    assert any("SLink-Emerald.ups is missing" in e for e in errors)
