"""A hello naming a rom_type nothing routes is refused out loud, not absorbed.

Before this, `game_id_for_rom_type()` returned None, the adapter guard never switched, and
the run continued under whichever adapter was already loaded. The first Gen 1 mock payload
came out with Gen 3 genders and abilities because of exactly that, and
`server/adapters/__init__.py` records the same thing having happened to Gen 2.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from server.server import SLinkServer


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
async def test_unknown_rom_type_is_rejected_and_nothing_else_gets_through(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send({"event": "hello", "player": "a", "rom_type": "gen1_rby",
                            "trainer_name": "Alice", "has_pokeballs": True})
        assert any(c.get("cmd") == "hud_show" and "UNKNOWN ROM" in c.get("text", "") for c in reply["commands"])
        assert "gen1_rby" in srv.state.identity_error["a"]
        assert srv.adapter.game_id == "gen3_frlge", "the adapter must not silently stay wherever it was AND be trusted"
        # Every later event is dropped while the error stands, the way an identity mismatch drops them.
        await send({"event": "area_enter", "player": "a", "area_id": "route_1"})
        assert "route_1" not in srv.state.area_states
        assert srv._build_status_dict()["players"]["a"]["identity_error"]
    finally:
        await close()


@pytest.mark.asyncio
async def test_a_routable_hello_clears_the_rejection(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send({"event": "hello", "player": "a", "rom_type": "gen1_rby", "trainer_name": "Alice"})
        assert srv.state.identity_error.get("a")
        # A routable hello: Red must now show the SLink companion (panel mailbox), patch-first 2026-10-02.
        await send({"event": "hello", "player": "a", "rom_type": "red", "trainer_name": "Alice",
                    "ot_id": "30B8", "has_pokeballs": True, "artifact_kind": "named", "panel": True})
        assert not srv.state.identity_error.get("a")
        assert srv.adapter.game_id == "gen1_rby"
    finally:
        await close()
