"""Pack-aware pairing (docs/gen3/PLAN.md §5.1, card gen3-P3a-C3a-1).

A `game_id` is too coarse to pair on: Radical Red and vanilla FireRed share `Gen3Adapter`,
so the old comparison let a clean FireRed join a run committed to RR. Pairing now compares
a DERIVED foundation (`foundation_for_rom_type`) plus a pairing kind normalized by the
foundation's adapter CLASS, and the check runs BEFORE the per-cartridge capability updates
and the adapter reselection -- a refused hello leaves the run exactly as it found it.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from server.adapters import (
    adapter_class_for_rom_type,
    foundation_for_rom_type,
    get_adapter,
)
from server.server import SLinkServer

RR = {"rom_type": "firered_rr", "artifact_kind": "companion"}
RR_CLEAN = {"rom_type": "firered_rr", "artifact_kind": "clean"}
FR = {"rom_type": "firered", "artifact_kind": "clean"}


async def _session(srv):
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    port = tcp.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)

    async def send(msg):
        w.write((json.dumps(msg) + "\n").encode())
        await w.drain()
        return json.loads(await asyncio.wait_for(r.readline(), 3))

    async def close():
        w.close()
        tcp.close()
        await tcp.wait_closed()
    return send, close


def _hello(player: str, cart: dict, **extra) -> dict:
    return {"event": "hello", "player": player, "trainer_name": player.upper(),
            "ot_id": "30B8" if player == "a" else "7B0B", "has_pokeballs": True,
            "party": [], **cart, **extra}


def _refused(reply) -> bool:
    return any(c.get("cmd") == "hud_show" and "MIXED GAMES" in c.get("text", "")
               for c in reply["commands"])


def _snapshot(srv) -> dict:
    """Everything a refused hello must not touch: persisted bytes + presentation caches."""
    links = Path(srv.state._links_path)
    links = links.read_bytes() if links.exists() else b""
    return {
        "links": links,
        "rom_type": srv.state.rom_type,
        "artifact_kind": srv.state.artifact_kind,
        "adapter": id(srv.adapter),
        "is_rr": srv.state.is_rr,
        "mon_cache": dict(srv._mon_cache),
        "party_details": json.dumps(srv.party_details, sort_keys=True),
        "panel_sig": dict(srv._last_panel_sig),
    }


# ── the derivation itself ────────────────────────────────────────────────────────────────

def test_the_two_gen3_foundations_are_distinct_but_share_one_adapter():
    assert foundation_for_rom_type("firered") == "gen3_frlg"
    assert foundation_for_rom_type("leafgreen") == "gen3_frlg"
    assert foundation_for_rom_type("firered_rr") == "gen3_rr"
    assert (adapter_class_for_rom_type("firered")
            is adapter_class_for_rom_type("firered_rr")), "same class, different foundations"


def test_every_other_pack_keeps_its_game_id_as_its_foundation():
    for rom_type in ("red", "blue", "yellow", "crystal", "platinum", "pokemon_black"):
        assert foundation_for_rom_type(rom_type) == adapter_class_for_rom_type(rom_type)().game_id
    # pureRGB is already a foundation of its own by game_id.
    assert foundation_for_rom_type("PureRed") == "gen1_purergb"
    assert foundation_for_rom_type("red") != foundation_for_rom_type("PureRed")


def test_an_unknown_rom_type_derives_nothing():
    assert foundation_for_rom_type("sapphire") is None
    assert adapter_class_for_rom_type("sapphire") is None


def test_pairing_kind_is_a_class_lookup_and_does_not_move_the_committed_kind():
    gen1 = adapter_class_for_rom_type("red")
    gen3 = adapter_class_for_rom_type("firered_rr")
    assert gen1.pairing_kind("named") == "clean" and gen1.pairing_kind("overlay") == "overlay"
    assert gen1.pairing_kind("companion") == "companion", "Gen 1 knows no companion kind"
    assert gen3.pairing_kind("companion") == "clean" and gen3.pairing_kind("rand") == "rand"
    # The committed kind is whatever was declared: set_artifact_kind never sees the mapping.
    adapter = get_adapter("gen3_frlge", is_rr=True, artifact_kind="companion")
    adapter.set_artifact_kind("companion")
    assert getattr(adapter, "artifact_kind", "companion") == "companion"


# ── the defect: a clean FireRed beside Radical Red ───────────────────────────────────────

@pytest.mark.asyncio
async def test_a_clean_firered_cannot_join_a_companion_rr_run(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", RR, panel=True, sfx=True)))
        assert srv.state.rom_type == "firered_rr"
        assert srv.state.artifact_kind == "companion", "the committed kind is the declared one"
        before = _snapshot(srv)
        reply = await send(_hello("b", FR, panel=True, sfx=True))
        assert _refused(reply)
        assert "Mixed games" in srv.state.identity_error["b"]
        assert "gen3_rr" in srv.state.identity_error["b"]
        assert _snapshot(srv) == before, "a refused hello changed the run (links.json included)"
        assert not srv.connected_players["b"].get("panel"), "capabilities updated before the gate"
        assert not srv.connected_players["b"].get("sfx")
    finally:
        await close()


@pytest.mark.asyncio
async def test_the_reverse_arrival_order_is_refused_too(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", FR)))
        assert srv.state.rom_type == "firered"
        reply = await send(_hello("b", RR))
        assert _refused(reply) and "gen3_frlg" in srv.state.identity_error["b"]
    finally:
        await close()


@pytest.mark.asyncio
async def test_a_clean_rr_pairs_with_a_companion_rr_and_firered_with_leafgreen(tmp_path):
    """Variants of ONE foundation still pair, and the companion patch is per cartridge."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", RR)))
        assert not _refused(await send(_hello("b", RR_CLEAN)))
        assert not srv.state.identity_error.get("b")
    finally:
        await close()
    srv2 = SLinkServer(data_dir=str(tmp_path / "second"))
    send, close = await _session(srv2)
    try:
        assert not _refused(await send(_hello("a", FR)))
        assert not _refused(await send(_hello("b", {"rom_type": "leafgreen"})))
    finally:
        await close()


def test_a_restart_re_derives_the_lock_from_the_persisted_rom_type(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.rom_type = "firered_rr"
    srv.state.artifact_kind = "companion"
    srv.state._save()
    restarted = SLinkServer(data_dir=str(tmp_path))
    assert restarted.state.rom_type == "firered_rr"
    assert "Mixed games" in restarted._mixed_games_error("b", "firered", "clean")
    assert restarted._mixed_games_error("b", "firered_rr", "clean") == ""


# ── unknown rom_type, declared foundation ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unknown_rom_type_is_refused_not_absorbed_by_the_installed_adapter(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    installed = srv.adapter.game_id
    send, close = await _session(srv)
    try:
        reply = await send(_hello("a", {"rom_type": "sapphire"}))
        assert any("UNKNOWN ROM" in c.get("text", "") for c in reply["commands"])
        assert "Unknown rom_type" in srv.state.identity_error["a"]
        assert srv.adapter.game_id == installed and not srv.state.rom_type
    finally:
        await close()
    # The pairing check refuses it on its own too, so no caller can absorb it.
    assert "Unknown rom_type" in srv._mixed_games_error("a", "sapphire", "clean")


@pytest.mark.asyncio
async def test_a_hello_that_declares_a_contradictory_foundation_is_refused(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send(_hello("a", RR, foundation="gen3_frlg"))
        assert _refused(reply)
        assert "Foundation mismatch" in srv.state.identity_error["a"]
        assert not srv.state.rom_type, "a refused hello commits nothing"
        assert not _refused(await send(_hello("a", RR, foundation="gen3_rr")))
        assert srv.state.rom_type == "firered_rr"
    finally:
        await close()


@pytest.mark.asyncio
async def test_an_absent_foundation_is_derived_so_an_old_client_still_connects(tmp_path):
    """P4 coexistence: today's RR client sends no `foundation`."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", RR)))
        assert not _refused(await send(_hello("b", RR_CLEAN)))
        assert not srv.state.identity_error
    finally:
        await close()


# ── the rules that must not move ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gen1_named_still_pairs_with_clean_and_a_second_game_is_still_refused(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", {"rom_type": "red", "artifact_kind": "clean"})))
        assert not _refused(await send(_hello("b", {"rom_type": "blue", "artifact_kind": "named"})))
        assert srv.state.artifact_kind == "clean"
        assert _refused(await send(_hello("b", {"rom_type": "PureBlue", "artifact_kind": "clean"})))
        assert "Mixed games" in srv.state.identity_error["b"]
    finally:
        await close()


@pytest.mark.asyncio
async def test_purergb_clean_and_overlay_still_never_mix(tmp_path):
    """Owner decision U8: the overlay is a run-level capability, not a per-cartridge patch."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", {"rom_type": "PureRed",
                                                    "artifact_kind": "overlay"})))
        assert _refused(await send(_hello("b", {"rom_type": "PureBlue",
                                                "artifact_kind": "clean"})))
        assert "Mixed artifact kinds" in srv.state.identity_error["b"]
        assert not _refused(await send(_hello("b", {"rom_type": "PureBlue",
                                                    "artifact_kind": "overlay"})))
    finally:
        await close()
