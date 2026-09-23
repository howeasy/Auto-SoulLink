"""A Crystal/Gold/Silver run persisted BEFORE the U5 cutover, reloaded after it.

docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md item 5: a run saved before U5 has
`game_id="gen2_crystal"` and `rom_type="Crystal"` on disk. server/adapters/__init__.py's
`_ROM_TYPE_TO_GAME_ID` now maps "Crystal"/"Gold"/"Silver" to `gen2_gsc`, so this run's
saved game_id disagrees with what its rom_type resolves to today.

The two adapters are NOT interchangeable over the same persisted state: they put the
SAME physical event under DIFFERENT `area_id` keys. A starter pickup persists as bare
"new_bark_town" under Gen2CrystalAdapter (gen2_crystal.py `_GIFT_AREAS` + the base
`gift_link_area` default: its `is_gift_area` already matches the bare place name), but
as "gift_new_bark_town" under Gen2GSCAdapter (gen2_gsc.py `is_gift_area` only matches a
"gift_"-prefixed id, so the base `gift_link_area` remaps it). The daycare area is bare
"route_34" under the old adapter vs "gift_daycare" under the new one
(gen2_gsc.py:336-337). Reinterpreting old `area_states`/`pending_captures` keys under the
new adapter would silently orphan a pending gift/daycare capture (the new client will
never again emit the old key) or reset area cooldown tracking for gift locations.

So this migration is refused outright (server/adapters/__init__.py
`persisted_migration_refusal`, consulted from server/state.py's `load()`): the server
raises `UnsafeGameMigration` rather than starting under either adapter. This replaces the
previous version of this test, which documented the OLD (buggy) behavior of silently
keeping the legacy `Gen2CrystalAdapter` and letting a post-cutover hello through.
"""
from __future__ import annotations

import json

import pytest

from server.adapters.gen2_crystal import Gen2CrystalAdapter
from server.server import SLinkServer
from server.state import UnsafeGameMigration


def _write_run(tmp_path, *, game_id: str, rom_type: str) -> None:
    (tmp_path / "links.json").write_text(json.dumps({
        "links": [], "area_states": {}, "pending_captures": {}, "mon_stats": {},
        "game_id": game_id, "rom_type": rom_type, "artifact_kind": "clean",
    }))


@pytest.mark.parametrize("rom_type", ["Crystal", "Gold", "Silver"])
def test_a_pre_flip_persisted_run_refuses_to_load(tmp_path, rom_type):
    _write_run(tmp_path, game_id="gen2_crystal", rom_type=rom_type)
    with pytest.raises(UnsafeGameMigration, match="gen2_crystal.*gen2_gsc"):
        SLinkServer(data_dir=str(tmp_path))


def test_a_pre_flip_persisted_crystal_ap_run_still_loads_on_the_legacy_adapter(tmp_path):
    # crystal_ap has NO row in _ROM_TYPE_TO_FOUNDATION/no cutover (O-8): its rom_type still
    # resolves to gen2_crystal today, so there is no migration to refuse.
    _write_run(tmp_path, game_id="gen2_crystal", rom_type="crystal_ap")
    srv = SLinkServer(data_dir=str(tmp_path))
    assert isinstance(srv.state.adapter, Gen2CrystalAdapter)
    assert srv.state.rom_type == "crystal_ap"
