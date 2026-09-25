"""adapter.calc_profile() gates the web damage calc per game, and the calc payloads
carry it. See docs/calc_multigen/HANDOFF.md tasks 1-2 and 10-11.
"""
from __future__ import annotations

import json

import pytest

from server.adapters.gen1_rby import Gen1Adapter
from server.adapters.gen3_frlge import Gen3Adapter
from server.manager import _calc_profile_for_run
from server.server import SLinkServer


def test_rr_adapter_calc_profile():
    assert Gen3Adapter(is_rr=True).calc_profile() == {"gen": 9, "dex": "rr"}


def test_vanilla_frlg_adapter_calc_profile_is_none():
    assert Gen3Adapter(is_rr=False).calc_profile() is None


def test_base_default_calc_profile_is_none():
    # Gen1Adapter does not override calc_profile; this exercises the base inert default.
    assert Gen1Adapter().calc_profile() is None


def test_calc_profile_for_run_rr_live_rom_type():
    run = {"game": ""}
    status = {"players": {"a": {"rom_type": "firered_rr"}, "b": {"rom_type": "firered_rr"}}}
    assert _calc_profile_for_run(run, status) == {"gen": 9, "dex": "rr"}


def test_calc_profile_for_run_vanilla_is_none():
    run = {"game": ""}
    status = {"players": {"a": {"rom_type": "firered"}, "b": {"rom_type": "firered"}}}
    assert _calc_profile_for_run(run, status) is None


def test_calc_profile_for_run_disagreement_is_none():
    run = {"game": ""}
    status = {"players": {"a": {"rom_type": "firered_rr"}, "b": {"rom_type": "red"}}}
    assert _calc_profile_for_run(run, status) is None


def test_calc_profile_for_run_falls_back_to_declared_family():
    """Before either player says hello (a stopped run, or one that just started), the
    run's declared game family stands in for a live rom_type."""
    assert _calc_profile_for_run({"game": "gen3_rr"}, {"players": {}}) == {"gen": 9, "dex": "rr"}
    assert _calc_profile_for_run({"game": "gen1"}, {"players": {}}) is None


def test_calc_profile_for_run_never_raises():
    """Every declared family, a malformed live status, and an unregistered adapter all
    hide the calc instead of failing the board page."""
    from server import manager
    for game in manager.GAME_MEMBERS:
        for status in ({"players": {}}, None, [], "x"):
            _calc_profile_for_run({"game": game}, status)
    import server.adapters as adapters
    saved = adapters._REGISTRY.pop("gen5_bw", None)
    try:
        assert _calc_profile_for_run({"game": "gen5_bw"}, {"players": {"a": {"rom_type": "pokemon_black"}}}) is None
    finally:
        if saved is not None:
            adapters._REGISTRY["gen5_bw"] = saved
    assert _calc_profile_for_run({"game": ""}, {"players": {}}) is None


@pytest.mark.asyncio
async def test_calc_mons_includes_calc_key_for_rr(tmp_path):
    from tests.unit.populated_server import populate

    srv = SLinkServer(data_dir=str(tmp_path))
    close = await populate(srv, "gen3")  # Radical Red
    try:
        resp = await srv.handle_calc_mons(None)
        body = json.loads(resp.text)
    finally:
        await close()
    assert body["calc"] == {"gen": 9, "dex": "rr"}
    assert body["a"]["party"] and body["b"]["party"]


@pytest.mark.asyncio
async def test_calc_mons_calc_key_is_none_for_unverified_game(tmp_path):
    from tests.unit.populated_server import populate

    srv = SLinkServer(data_dir=str(tmp_path))
    close = await populate(srv, "gen1")  # Gen 1: calc_profile() not verified, stays None
    try:
        resp = await srv.handle_calc_mons(None)
        body = json.loads(resp.text)
    finally:
        await close()
    assert body["calc"] is None


@pytest.mark.asyncio
async def test_calc_mons_uses_per_player_adapter(tmp_path):
    """handle_calc_mons must call self.adapter_for(pid), not the run-wide self.adapter:
    the mock injector never sends rom_content, so both players fall back to the same
    self.adapter instance unless a per-player one is set explicitly here."""
    from tests.unit.populated_server import populate

    srv = SLinkServer(data_dir=str(tmp_path))
    close = await populate(srv, "gen3")
    try:
        fake_a = Gen3Adapter(is_rr=True)
        fake_a.species_name = lambda sid: "Zzztest"  # a fresh instance, player a only
        srv._player_adapters["a"] = fake_a
        resp = await srv.handle_calc_mons(None)
        body = json.loads(resp.text)
    finally:
        await close()
    assert body["a"]["party"][0]["species_name"] == "Zzztest"
    assert body["b"]["party"][0]["species_name"] != "Zzztest"


def test_calc_tab_hidden_when_profile_is_none(tmp_path):
    """A fresh standalone server defaults to vanilla FRLG (is_rr=False): calc_profile()
    is None, so the rail hides the Calc link."""
    srv = SLinkServer(data_dir=str(tmp_path))
    assert srv._calc_profile() is None
    assert srv._rail_ctx()["show_calc"] is False


@pytest.mark.asyncio
async def test_calc_tab_shown_for_rr(tmp_path):
    from tests.unit.populated_server import populate

    srv = SLinkServer(data_dir=str(tmp_path))
    close = await populate(srv, "gen3")
    try:
        assert srv._calc_profile() == {"gen": 9, "dex": "rr"}
        assert srv._rail_ctx()["show_calc"] is True
    finally:
        await close()
