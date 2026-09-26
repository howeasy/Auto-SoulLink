"""A Gen 2 run persisted under the RETIRED legacy adapter (`gen2_crystal`), reloaded now.

docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md item 5: a run saved before U5 has
`game_id="gen2_crystal"` and `rom_type="Crystal"` on disk. server/adapters/__init__.py's
`_ROM_TYPE_TO_GAME_ID` maps "Crystal"/"Gold"/"Silver" to `gen2_gsc`, so this run's saved
game_id disagrees with what its rom_type resolves to today.

The two adapters were NOT interchangeable over the same persisted state: they put the
SAME physical event under DIFFERENT `area_id` keys. A starter pickup persisted as bare
"new_bark_town" under the legacy Gen2CrystalAdapter, but as "gift_new_bark_town" under
Gen2GSCAdapter (gen2_gsc.py `is_gift_area` only matches a "gift_"-prefixed id, so the base
`gift_link_area` remaps it). The daycare area was bare "route_34" under the old adapter vs
"gift_daycare" under the new one. Reinterpreting old `area_states`/`pending_captures` keys
under the new adapter would silently orphan a pending gift/daycare capture (the new client
never emits the old key) or reset area cooldown tracking for gift locations.

P3b.8 then REMOVED the legacy adapter, and owner ruling O-25 refused Archipelago Crystal,
the last rom_type that still routed to it. So `gen2_crystal` is a RETIRED game_id
(server/adapters/__init__.py `_RETIRED_GAME_IDS`, consulted by `persisted_migration_refusal`
from server/state.py's `load()`): EVERY run persisted under it is refused with
`UnsafeGameMigration` -- whatever its rom_type now resolves to, including nothing at all --
rather than starting under the default adapter or failing on a missing module.
"""
from __future__ import annotations

import json

import pytest

from server import adapters
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


@pytest.mark.parametrize("rom_type", ["crystal_ap", "Crystal (AP)", ""])
def test_a_persisted_run_whose_rom_type_no_longer_routes_is_refused_too(tmp_path, rom_type):
    """Archipelago Crystal runs (O-25) -- and a run saved before any hello named its
    rom_type -- resolve to NO game_id today. Before P3b.8 such a run skipped the migration
    check and quietly reloaded under the legacy adapter; with that adapter gone it would
    have kept the DEFAULT (Gen 3) adapter over Gen 2 links. It is refused instead."""
    _write_run(tmp_path, game_id="gen2_crystal", rom_type=rom_type)
    with pytest.raises(UnsafeGameMigration, match="gen2_crystal"):
        SLinkServer(data_dir=str(tmp_path))


def test_the_refusal_needs_no_legacy_adapter(tmp_path, monkeypatch):
    """The refusal is a registry fact, not an import: it holds with no `gen2_crystal`
    adapter registered (the adapter module itself is deleted by P3b.8)."""
    monkeypatch.delitem(adapters._REGISTRY, "gen2_crystal", raising=False)
    assert "gen2_crystal" not in adapters.available_game_ids()
    for rom_type in ("Crystal", "crystal_ap"):
        _write_run(tmp_path, game_id="gen2_crystal", rom_type=rom_type)
        with pytest.raises(UnsafeGameMigration, match="gen2_crystal"):
            SLinkServer(data_dir=str(tmp_path))


def test_a_persisted_gen2_gsc_run_is_not_touched_by_the_retirement(tmp_path):
    """Negative control: the refusal is keyed on the RETIRED game_id only."""
    _write_run(tmp_path, game_id="gen2_gsc", rom_type="Gold")
    srv = SLinkServer(data_dir=str(tmp_path))
    assert srv.state.adapter.game_id == "gen2_gsc" and srv.state.rom_type == "Gold"
