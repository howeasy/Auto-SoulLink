"""C5-6: tools/gen_gen3_profile.py's native (companion) block must not depend on
archive/gen3-old-client:lua/mailbox.lua or archive/gen3-old-client:lua/peer_ghost_npc.lua -- C5-6 deletes both files. It is generated from
patch/src/handlers.c instead (docs/gen3/research/c5_6_deletion_plan_2026-09-24.md risk 4).

This runs native_block() against a REPO that carries ONLY patch/src/handlers.c (no lua/ dir
at all), so a regression that reintroduces a read of either deleted Lua file fails loudly
with FileNotFoundError instead of silently passing because the real checkout still has them.
"""
from __future__ import annotations

import pathlib

import pytest

from tools import gen_gen3_profile as g

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS = REPO / "patch" / "src" / "handlers.c"


def _isolated_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A REPO subset containing only patch/src/handlers.c -- notably NOT archive/gen3-old-client:lua/mailbox.lua or
    archive/gen3-old-client:lua/peer_ghost_npc.lua, which this generator must no longer read."""
    dest = tmp_path / "patch" / "src" / "handlers.c"
    dest.parent.mkdir(parents=True)
    dest.write_text(HANDLERS.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_native_block_does_not_need_the_deleted_lua_files(monkeypatch, tmp_path) -> None:
    isolated = _isolated_repo(tmp_path)
    assert not (isolated / "lua").exists()  # the scrape targets C5-6 deletes are simply absent
    monkeypatch.setattr(g, "REPO", isolated)
    got = g.native_block()
    monkeypatch.undo()
    want = g.native_block()  # the real checkout, same handlers.c content -> byte-identical
    assert got == want
    assert got["BASE"] == 0x0203F800 and got["OP_RIVAL_SWAP"] == 28  # not an empty/trivial dict
    for where in got["_src"].values():
        assert where.startswith("patch/src/handlers.c:")


def test_native_block_fails_loudly_without_handlers_c(monkeypatch, tmp_path) -> None:
    """No fallback to some other source: an absent patch/src/handlers.c must not silently
    produce a partial or empty native block."""
    monkeypatch.setattr(g, "REPO", tmp_path)  # no patch/src/handlers.c under here at all
    with pytest.raises(FileNotFoundError):
        g.native_block()


def test_native_block_matches_committed_profile() -> None:
    """The committed data/games/gen3_rr/profile.json's native block (minus _src, which is a
    file:line citation and so is allowed to move) must already equal a fresh generation --
    i.e. nobody hand-edited profile.json out of step with the generator."""
    import json

    profile = json.loads((REPO / "data/games/gen3_rr/profile.json").read_text(encoding="utf-8"))
    committed = dict(profile["native"])
    committed.pop("_src")
    fresh = g.native_block()
    fresh.pop("_src")
    assert committed == fresh
