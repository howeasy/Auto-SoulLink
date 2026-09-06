"""Render fixtures use isolated real state and never invent admission evidence."""

import copy
import json
from pathlib import Path

import pytest

from tests.ui_support import hydrate_capture

SOURCE = Path(__file__).resolve().parents[1] / "fixtures/ui/source"


@pytest.mark.parametrize("game", ["gen3", "gen1"])
def test_hydration_exercises_serializer_indexes_and_caches_without_mutations(tmp_path, game):
    capture = json.loads((SOURCE / f"{game}.json").read_text(encoding="utf-8"))
    original = copy.deepcopy(capture)
    srv = hydrate_capture(capture, tmp_path / game)
    payload = srv._build_status_dict()
    assert len(payload["links"]) == len(capture["links"])
    assert payload["pending_captures"]
    assert payload["killfeed"]
    assert all(srv.state._key_index.get(mon.key) for link in srv.state.links for mon in (link.a, link.b) if mon)
    assert all(srv.pc_boxes[pid] and srv._mon_cache for pid in ("a", "b"))
    assert {p["admission"] for p in payload["players"].values()} == {"contract_pending"}
    assert all(p["last_seen_age"] is None for p in payload["players"].values())
    before = srv.state.to_document()
    assert "Sparky" in srv._build_status_html()
    assert srv.state.to_document() == before
    assert capture == original
    assert not list((tmp_path / game).rglob("*.json"))


def test_hydration_refuses_existing_data_directory(tmp_path):
    (tmp_path / "links.json").write_text("do not touch")
    with pytest.raises(ValueError, match="empty isolated"):
        hydrate_capture({}, tmp_path)
    assert (tmp_path / "links.json").read_text() == "do not touch"


@pytest.mark.asyncio
async def test_live_rby_mock_injection_refuses_before_any_io(monkeypatch):
    from tools import inject_full_mocks as mocks

    monkeypatch.setattr(mocks, "GAME", "gen1")

    def forbidden(*args, **kwargs):
        pytest.fail("attempted live HTTP/TCP mutation")

    monkeypatch.setattr(mocks, "http_post", forbidden)
    monkeypatch.setattr(mocks, "send_tcp", forbidden)
    with pytest.raises(RuntimeError, match="restricted runtime boundary"):
        await mocks.main()


def test_gen1_mock_keys_use_actual_internal_species_indices(monkeypatch):
    from tools import inject_full_mocks as mocks

    indices = json.loads((SOURCE.parents[3] / "data/games/gen1_rby/species_index.json").read_text())["index_to_national"]
    captures = [mon for _, a, b in mocks.GEN1_PAIRS for mon in (a, b)]
    captures += [mocks.GEN1_PENDING_A, mocks.GEN1_BOXED_A, mocks.GEN1_BOXED_B, mocks.GEN1_DEAD_ZONE_BOB]
    for species, key, *_ in captures:
        assert indices[str(int(key.rsplit(":", 1)[1], 16))] == species
    monkeypatch.setattr(mocks, "GAME", "gen1")
    stored = mocks._stored("A1", "30B8", 133)
    assert indices[str(int(stored.rsplit(":", 1)[1], 16))] == 133
