"""Patch-first (owner 2026-10-02), Gen 2 half: the SLink companion overlay is REQUIRED for Crystal, Gold
and Silver. The launcher admits only an activated overlay row (tests/unit/test_gen2_entry.py,
test_gen2_overlay_admission.py), the server refuses a clean Gen 2 hello, and the Manager refuses to
prepare a pick whose overlay row is not activated (tests/unit/test_cartridges.py). The other families:
test_companion_required.py.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from server.adapters import adapter_class_for_rom_type
from server.server import SLinkServer

REASON = "needs the SLink companion patch"
TITLES = ["Crystal", "Gold", "Silver", "crystal", "gold", "silver"]


PINNED = 3   # data/games/gen2_*/profile.json overlay.abi == patch/gb/slink_abi.inc SLINK_ABI_VERSION


def _hello(rom_type, kind="overlay", **extra):
    return {"rom_type": rom_type, "artifact_kind": kind, **extra}


@pytest.mark.parametrize("rom_type", TITLES)
@pytest.mark.parametrize("kind", ["clean", "named", "rand", "overlay", "rand_overlay", "companion", None])
def test_gen2_refuses_every_kind_without_the_cartridges_own_evidence(rom_type, kind):
    """The kind is the launcher's own claim, never evidence: only the mailbox a LIVE overlay's service
    publishes (`companion_abi`, read from cartridge RAM by lua/gen2/panel.lua) admits a hello."""
    cls = adapter_class_for_rom_type(rom_type)
    hello = {"rom_type": rom_type} if kind is None else _hello(rom_type, kind)
    assert REASON in cls.companion_refusal(hello)


@pytest.mark.parametrize("rom_type", TITLES)
@pytest.mark.parametrize("bad", [True, False, "3", 3.0, 0, 1, 2, 4, 255, -3, None, [3], {"abi": 3}])
def test_gen2_evidence_must_be_the_exact_pinned_integer(rom_type, bad):
    cls = adapter_class_for_rom_type(rom_type)
    assert REASON in cls.companion_refusal(_hello(rom_type, companion_abi=bad))


@pytest.mark.parametrize("rom_type", TITLES)
def test_gen2_admits_a_real_overlay(rom_type):
    cls = adapter_class_for_rom_type(rom_type)
    assert cls.companion_refusal(_hello(rom_type, companion_abi=PINNED)) is None
    # evidence on a hello that says it is not the overlay is contradictory: refused, never trusted
    for kind in ("clean", "rand", "named"):
        assert REASON in cls.companion_refusal(_hello(rom_type, kind, companion_abi=PINNED))


def test_gen2_reads_the_pin_from_the_pack_and_fails_closed(monkeypatch):
    from server.adapters import gen2_gsc
    assert gen2_gsc._companion_abi("crystal") == PINNED
    gen2_gsc._companion_abi.cache_clear()
    monkeypatch.setattr(gen2_gsc, "_DATA", gen2_gsc._DATA / "no-such-games-dir")
    try:
        assert gen2_gsc._companion_abi("crystal") is None
        cls = adapter_class_for_rom_type("Crystal")
        assert REASON in cls.companion_refusal(_hello("Crystal", companion_abi=PINNED)), "an unreadable pin refuses"
    finally:
        gen2_gsc._companion_abi.cache_clear()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("rom_type", ["Crystal", "Gold", "Silver"])
async def test_the_server_refuses_a_clean_gen2_hello(tmp_path, rom_type):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send({"event": "hello", "player": "a", "rom_type": rom_type, "artifact_kind": "clean",
                            "trainer_name": "Alice", "has_pokeballs": True})
        assert any(c.get("cmd") == "hud_show" and "COMPANION" in c.get("text", "") for c in reply["commands"])
        assert REASON in srv.state.identity_error["a"] and not srv.state.rom_type
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rom_type", ["Crystal", "Gold", "Silver"])
@pytest.mark.parametrize("extra", [{}, {"companion_abi": 2}, {"companion_abi": True}, {"companion_abi": "3"}])
async def test_the_server_refuses_an_overlay_hello_whose_cartridge_shows_no_evidence(tmp_path, rom_type, extra):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send({"event": "hello", "player": "a", "rom_type": rom_type, "artifact_kind": "overlay",
                            "trainer_name": "Alice", "has_pokeballs": True, **extra})
        assert any(c.get("cmd") == "hud_show" and "COMPANION" in c.get("text", "") for c in reply["commands"])
        assert REASON in srv.state.identity_error["a"] and not srv.state.rom_type
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rom_type", ["Crystal", "Gold", "Silver"])
async def test_the_server_admits_an_overlay_hello_with_the_pinned_evidence(tmp_path, rom_type):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send({"event": "hello", "player": "a", "rom_type": rom_type, "artifact_kind": "overlay",
                    "companion_abi": PINNED, "trainer_name": "Alice", "has_pokeballs": True})
        assert not srv.state.identity_error.get("a")
        assert srv.state.rom_type == rom_type and srv.state.artifact_kind == "overlay"
    finally:
        await close()


def test_a_hello_that_skips_the_socket_is_refused_by_admission_too(tmp_path):
    """`_dispatch`/`_decide_admission` are reachable without handle_client (tests, tools)."""
    srv = SLinkServer(data_dir=str(tmp_path))
    hello = {"event": "hello", "player": "a", "rom_type": "Crystal", "artifact_kind": "overlay",
             "trainer_name": "Alice", "ot_id": "30B8", "has_pokeballs": True, "party": []}
    verdict = srv._decide_admission("a", hello)
    assert verdict["state"] == "rejected" and REASON in verdict["reason"]
    assert srv._decide_admission("a", {**hello, "companion_abi": PINNED})["state"] != "rejected"
