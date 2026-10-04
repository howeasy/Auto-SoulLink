"""Extracted-release-bundle boot test (P3b.8): prove the files a player actually gets, not the
git checkout, are enough to admit Crystal, Gold and Silver.

`test_make_release_manifest.py` derives the runtime closure from Lua source and checks every
path is a name in the built ZIP's namelist. That catches a missing file, but not a file that
lands at the wrong relative path once extracted, or a `dofile`/`io.open` assumption that only
happens to hold inside a git checkout. This test builds the real release ZIP, extracts it to a
plain temp directory, and asks lupa to run `lua/gen2/run.lua`'s own dofile graph against THAT
tree -- the same way `tests/unit/test_gen2_client.py::
test_run_lua_exposes_the_production_client_only_for_an_admitted_cartridge` drives run.lua
against the git checkout, with the real ROMs from `.cache/gen2-build/{pokecrystal,pokegold}`.
No emulator: `run.lua`'s own BizHawk globals (`memory`, `emu`, `event`, `console`) are stubbed,
same idiom as that other test's `RUN_HOST`.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_release  # noqa: E402

TITLES = ["crystal", "gold", "silver"]
_ROM_REPO = {"crystal": "pokecrystal", "gold": "pokegold", "silver": "pokegold"}

RUN_HOST = r"""
return function(rom, root, pc_log)
    local frames, callbacks = {}, {}
    memory = {
        read_u8 = function(a, d) if d == "ROM" then return rom:byte(a + 1) or 0 end return 0 end,
        write_u8 = function() end,
        getmemorydomainsize = function(d) return d == "ROM" and #rom or 0x10000 end,
        getmemorydomainlist = function() return {"ROM", "System Bus", "CartRAM"} end,
    }
    emu = {framecount = function() return 1 end, getregister = function() return 0 end}
    event = {
        onframeend = function(fn) frames[#frames + 1] = fn end,
        onexit = function() end,
        on_bus_exec = function(fn, addr, name) callbacks[name] = addr; return name end,
        unregisterbyid = function() return true end,
    }
    console = {log = function(t) pc_log[#pc_log + 1] = t end}
    package.loaded.connector = {init = function() end, send = function() end, receive = function() end,
                                pump = function() end, connected = function() return false end}
    package.loaded.hud = {init = function() end, render = function() end, show = function() end}
    SLINK_GEN2_CLIENT, SLINK_GEN2_PARTS = "stale", "stale"
    dofile(root .. "/lua/gen2/run.lua")
    return frames, callbacks
end
"""


def _extract_bundle(version: str, out_dir: Path) -> Path:
    """Build the real release ZIP and extract it flat -- what a player's unzip does."""
    zip_path = make_release.build_release(version=version, out_dir=out_dir, skip_generators=True)
    extracted = out_dir / f"{version}-extracted"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extracted)
    return extracted / f"SLink-player-{version}"


def _boot(root: Path, title: str, monkeypatch: pytest.MonkeyPatch, artifact: str | None = None):
    """Run the extracted tree's lua/gen2/run.lua against the real ROM for `title`."""
    monkeypatch.delenv("SLINK_ROOT", raising=False)  # force run.lua's own-path self-location
    profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
    rom = (ROOT / f".cache/gen2-build/{_ROM_REPO[title]}/{artifact or profile['artifact']}.gbc").read_bytes()
    if artifact is None:
        # Patch-first: the production cartridge is the overlay (the clean build + the shipped UPS)
        from patch.tools.make_ups import ups_apply
        rows = json.loads((ROOT / f"data/games/gen2_{title}/admission.json").read_text())["artifacts"]
        rom = ups_apply(rom, (ROOT / next(x for x in rows if x["kind"] == "overlay")["ups"]["file"]).read_bytes())
    lua = LuaRuntime(unpack_returned_tuples=True)
    logs = lua.table()
    frames, callbacks = lua.execute(RUN_HOST)(rom, root.as_posix(), logs)
    return lua, lua.globals(), frames, callbacks, list(logs.values())


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    return _extract_bundle("bundle-boot", tmp_path_factory.mktemp("release"))


@pytest.mark.parametrize("title", TITLES)
def test_extracted_bundle_admits_each_production_title(bundle, title, monkeypatch):
    lua, g, frames, callbacks, logs = _boot(bundle, title, monkeypatch)
    assert g.SLINK_GEN2_PARTS is not None, (
        f"{title}: the extracted bundle refused to admit its own production title: {logs}")
    assert g.SLINK_GEN2_PARTS.production_admitted is True
    assert g.SLINK_GEN2_PARTS.qualification == "PHYSICAL_RECEIPTED"
    assert g.SLINK_GEN2_PARTS.title == title
    assert lua.eval("rawequal")(g.SLINK_GEN2_PARTS.client, g.SLINK_GEN2_CLIENT) and len(frames) == 1
    assert any("PRODUCTION" in line for line in logs), logs


def test_extracted_bundle_refuses_a_build_only_revision(bundle, monkeypatch):
    """Control: Crystal 1.1 is BUILD_ONLY (never admitted) -- the extracted tree must refuse it
    exactly like the git checkout does, proving this harness can actually detect a refusal."""
    _lua, g, frames, _callbacks, logs = _boot(bundle, "crystal", monkeypatch, artifact="pokecrystal11")
    assert g.SLINK_GEN2_PARTS is None and g.SLINK_GEN2_CLIENT is None and len(frames) == 0
    assert any("refused" in line for line in logs), logs


def test_a_manifest_entry_missing_from_the_bundle_refuses_every_candidate(tmp_path, monkeypatch):
    """Revert-test: the source file stays on disk, only the manifest row is dropped, so the
    built ZIP -- and the tree a player extracts from it -- is missing Gold's own U2 receipt.
    `Entry.admit`'s catalog scan loads every title's pack up front, so Gold's candidate fails
    closed (`proofs()` -> `io.open` refusal, caught by the outer pcall in lua/gen2/entry.lua)
    while Crystal and Silver, whose packs are untouched, keep booting -- pinning that ONE
    missing file only costs the ONE title it belongs to, not a silent pass-through."""
    original = make_release._DATA_GAME_LUA["gen2_gold"]
    monkeypatch.setitem(
        make_release._DATA_GAME_LUA, "gen2_gold",
        [f for f in original if f != "receipts/overlay/gold_town.qualification.json"],
    )
    broken = _extract_bundle("bundle-boot-broken", tmp_path)

    _lua, g, frames, _callbacks, logs = _boot(broken, "gold", monkeypatch)
    assert g.SLINK_GEN2_PARTS is None and g.SLINK_GEN2_CLIENT is None and len(frames) == 0
    assert any("refused" in line for line in logs), logs

    _lua2, g2, frames2, _callbacks2, logs2 = _boot(broken, "crystal", monkeypatch)
    assert g2.SLINK_GEN2_PARTS is not None, f"an unrelated title must not be caught by Gold's gap: {logs2}"
    assert len(frames2) == 1
