"""A server populated the way `tools/inject_full_mocks.py` populates one — in-process.

The route smoke test renders one linked pair and one memorial, which is enough to prove a
template compiles and not enough to prove it says anything. The mock injector is the
complete cast (six pairs, a pending capture, a dead zone, a boxed pair, a battle, PC boxes,
held items, badges), and it is what the mockup fixtures under `server/static/mockups/
fixtures/` were captured from. Driving it through the REAL TCP handler — not `_dispatch`
directly — is what makes the adapter switch on hello, `connected_players` and the seq guard
all run, so the page under test is the page a live run shows.

The socket stays open until the fixture is torn down. The server marks a player disconnected
when its socket closes, and a dashboard rendered for two offline players is a different
page (see the injector's HOLD note).
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from server.server import SLinkServer, build_app

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INJECTOR = os.path.join(_REPO, "tools", "inject_full_mocks.py")

GAMES = ("gen3", "gen1")


def _load_injector():
    # tools/ is not a package; load the script as a module so its cast and helpers are ours.
    spec = importlib.util.spec_from_file_location("inject_full_mocks", _INJECTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def populate(srv: SLinkServer, game: str):
    """Run the injector's whole script against `srv` over a real socket. Returns the open
    writer so the caller decides when the players go offline."""
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0, limit=4 * 1024 * 1024)
    port = tcp.sockets[0].getsockname()[1]
    mod = _load_injector()
    mod.GAME = game
    mod.TCP_HOST, mod.TCP_PORT, mod.HOLD = "127.0.0.1", port, 0
    held: list[asyncio.StreamWriter] = []

    async def send_tcp(events):
        if not held:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            held.append(w)
            held.append(r)
        w, r = held[0], held[1]
        for m in events:
            w.write((json.dumps(m) + "\n").encode())
            await w.drain()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(r.readline(), timeout=2)

    def http_post(path, body):
        if path == "/api/attempts":
            srv.state.attempts_count = int(body.get("count", 0))
            srv.state._save()
        return {"ok": True}

    mod.send_tcp, mod.http_post = send_tcp, http_post
    mod.print = lambda *a, **k: None
    await mod.main()

    async def close():
        if held:
            held[0].close()
        tcp.close()
        await tcp.wait_closed()
    return close


@pytest_asyncio.fixture(params=GAMES, ids=GAMES)
async def populated(request, tmp_path):
    """(srv, client) for a fully populated run of the parametrized generation."""
    srv = SLinkServer(data_dir=str(tmp_path))
    close = await populate(srv, request.param)
    client = TestClient(TestServer(build_app(srv)))
    await client.start_server()
    try:
        yield srv, client
    finally:
        await client.close()
        await close()


@pytest.fixture
def game(request):
    return request.node.callspec.params.get("populated", "gen3")
