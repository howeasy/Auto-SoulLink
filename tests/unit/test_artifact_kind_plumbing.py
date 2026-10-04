"""The committed artifact kind reaches the run's adapter (docs/purergb/PLAN.md §5.2 A3).

`SLinkServer` commits the hello's `artifact_kind` once (server/state.py) and from then on the
adapter's per-run capabilities -- `native_trade_ui()`, `supports_info_panel()` -- follow it:
a pure run on the SLink companion overlay (kind overlay / rand_overlay) drives the native trade
scene and the START panel, a clean or rand run does not. The plumbing is adapter-neutral: the
base adapter's `set_artifact_kind` is a no-op, so Gen 3 is untouched. A mixed clean/overlay
pair never gets this far: the hello check refuses it as MIXED GAMES.
"""
from __future__ import annotations

import pytest

from server.adapters import get_adapter
from server.adapters.base import GameAdapter
from server.server import SLinkServer
from server.state import SoulLinkState
from tests.unit.test_state_key_change_ack import _session


def _hello(pid: str, rom_type: str, kind: str | None) -> dict:
    msg = {"event": "hello", "player": pid, "rom_type": rom_type, "trainer_name": pid.upper(),
           "ot_id": {"a": "30B8", "b": "7B0B"}[pid], "has_pokeballs": True, "party": []}
    if kind is not None:
        msg["artifact_kind"] = kind
    return msg


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["overlay", "rand_overlay"])
async def test_a_pure_runs_adapter_follows_the_committed_kind(tmp_path, kind):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(_hello("a", "PureRed", kind))
        assert srv.state.artifact_kind == kind
        assert srv.adapter.game_id == "gen1_purergb"
        assert srv.adapter.native_trade_ui() is True
        assert srv.adapter.supports_info_panel() is True
        assert srv.state.adapter is srv.adapter
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["clean", "rand"])
async def test_a_clean_pure_cartridge_is_refused_and_commits_nothing(tmp_path, kind):
    """Patch-first (owner 2026-10-02): the companion overlay is required for pureRGB, so a clean or
    randomized-clean hello never reaches the adapter's committed kind (it used to commit clean/rand with
    no native trade, no panel)."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(_hello("a", "PureRed", kind))
        assert srv.state.artifact_kind == "" and not srv.state.rom_type
        assert "needs the SLink companion patch" in srv.state.identity_error["a"]
    finally:
        await close()


@pytest.mark.asyncio
async def test_a_gen3_run_is_untouched(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(_hello("a", "firered", None))     # the session patches it: a companion FireRed
        assert srv.state.artifact_kind == "companion"
        assert srv.adapter.game_id == "gen3_frlge" and srv.adapter.native_trade_ui() is False
    finally:
        await close()


def test_the_base_adapter_accepts_the_kind_as_a_no_op():
    assert GameAdapter.set_artifact_kind(get_adapter("gen3_frlge"), "overlay") is None
    assert get_adapter("gen3_frlge").native_trade_ui() is False


def test_a_restored_run_rebinds_the_kind_to_its_rebuilt_adapter(tmp_path):
    st = SoulLinkState(data_dir=str(tmp_path))
    st.rom_type, st.artifact_kind = "PureRed", "overlay"
    st.adapter = get_adapter("gen1_purergb", rom_type="PureRed")
    st._save()
    srv = SLinkServer(data_dir=str(tmp_path))
    assert srv.state.artifact_kind == "overlay"
    assert srv.adapter.game_id == "gen1_purergb" and srv.adapter.native_trade_ui() is True


def test_a_players_own_rom_adapter_carries_the_run_kind(tmp_path):
    """_ingest_rom_content builds a per-player adapter: it must not fall back to clean."""
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.rom_type, srv.state.artifact_kind = "PureRed", "overlay"
    srv.state.adapter = srv.adapter = get_adapter("gen1_purergb", rom_type="PureRed", artifact_kind="overlay")
    srv.connected_players["a"] = {"rom_type": "PureRed"}
    srv._ingest_rom_content("a", {"not": "a payload"})  # rejected payload -> adapter with {} tables
    assert srv._player_adapters["a"].native_trade_ui() is True
