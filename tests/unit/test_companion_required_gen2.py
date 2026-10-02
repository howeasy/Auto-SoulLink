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


@pytest.mark.parametrize("rom_type", TITLES)
def test_gen2_refuses_clean_and_admits_the_overlay(rom_type):
    cls = adapter_class_for_rom_type(rom_type)
    assert REASON in cls.companion_refusal({"rom_type": rom_type, "artifact_kind": "clean"})
    assert REASON in cls.companion_refusal({"rom_type": rom_type})                       # absent kind == clean
    assert cls.companion_refusal({"rom_type": rom_type, "artifact_kind": "overlay"}) is None


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
