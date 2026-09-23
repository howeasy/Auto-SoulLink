"""A Crystal run persisted BEFORE the U5 cutover, reloaded after it.

docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md item 5: a run saved before U5 has
`game_id="gen2_crystal"` and `rom_type="Crystal"` on disk (server/state.py:905-913 restores
the adapter from the PERSISTED game_id, not from a fresh `game_id_for_rom_type` lookup).
After U5 the live row for "Crystal" points at `gen2_gsc`, but the reloaded run's adapter is
still resolved from the OLD persisted string, so it comes back as the legacy
`Gen2CrystalAdapter` -- and `server/server.py:1406` only re-resolves the adapter from an
incoming hello's rom_type while `state.rom_type` is still empty, which it is not once a run
has a committed rom_type. So a new-client hello (foundation="gen2_gsc",
artifact_kind/rom_sha1, no game_id) for this persisted run is NOT refused -- the mixed-games
foundation check compares two `foundation_for_rom_type("Crystal")` values, both "gen2_gsc",
so they agree -- but the run keeps running under the LEGACY adapter, silently.

This is the migration gap the card names, not something to patch here: deleting the legacy
`gen2_crystal.py` adapter would instead make `state.py:917-922`'s `except (KeyError, ...)`
fall back to whatever adapter was already installed (the Gen 3 default), which is worse. The
card is pinned to STOP and report this rather than editing state.py, so this test documents
the actual (imperfect but non-crashing) behavior as the falsifiable contract: don't refuse
the reconnect, and don't silently "fix" the adapter mismatch here either.
"""
from __future__ import annotations

import json

import pytest

from server.adapters.gen2_crystal import Gen2CrystalAdapter
from server.server import SLinkServer
from tests.unit.test_mixed_foundations import _hello, _refused, _session


def _write_pre_flip_run(tmp_path) -> None:
    """The on-disk shape a pre-U5 Crystal run left behind: legacy game_id, no foundation
    field existed yet on the wire when this run was made, `links.json` is otherwise empty."""
    (tmp_path / "links.json").write_text(json.dumps({
        "links": [], "area_states": {}, "pending_captures": {}, "mon_stats": {},
        "game_id": "gen2_crystal", "rom_type": "Crystal", "artifact_kind": "clean",
    }))


@pytest.mark.asyncio
async def test_a_new_client_hello_is_not_refused_by_a_pre_flip_persisted_run(tmp_path):
    _write_pre_flip_run(tmp_path)
    srv = SLinkServer(data_dir=str(tmp_path))
    # The persisted adapter is the LEGACY one, resolved from the saved game_id string --
    # not re-derived from rom_type through the now-flipped `_ROM_TYPE_TO_GAME_ID` row.
    assert isinstance(srv.state.adapter, Gen2CrystalAdapter)
    assert srv.state.rom_type == "Crystal"

    send, close = await _session(srv)
    try:
        # The new client's hello: foundation declared, no game_id on the wire at all.
        reply = await send(_hello("a", {
            "rom_type": "Crystal", "artifact_kind": "clean", "foundation": "gen2_gsc",
            "rom_sha1": "0" * 40,
        }))
        assert not _refused(reply), reply
        assert not srv.state.identity_error
    finally:
        await close()

    # The finding: state.rom_type was already committed at load, so server.py's hello
    # handler never re-resolves the adapter (server.py:1406, `if not self.state.rom_type`)
    # -- the run keeps serving the new client under the legacy adapter class.
    assert isinstance(srv.state.adapter, Gen2CrystalAdapter), (
        "if this ever becomes Gen2GSCAdapter, server.py grew a migration path -- "
        "update this test's docstring, it is no longer documenting a gap")
    assert srv.state.adapter.game_id == "gen2_crystal"
