"""
Wire-level integration test for the peer-ghost pipeline.

Unlike test_peer_ghost.py (which drives SoulLinkState in-process), this opens
TWO real TCP clients against a live server.py subprocess and asserts the actual
on-the-wire round-trip: the JSON envelope, server.py's request/response path,
and that the relayed `ghost_pos` command carries the partner's coordinates +
animNum.  This is what catches a field that's dropped between the Lua sender,
the server, and the renderer.

Run:
    pytest tests/unit/test_peer_ghost_wire.py -v
"""
import asyncio
import itertools
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import pytest

SERVER_HOST = "127.0.0.1"

# The server rejects non-increasing seq per player (client-restart guard), so —
# exactly like the real Lua client — every event must carry a monotonically
# increasing seq.  A single shared counter keeps each player's subsequence
# increasing regardless of interleaving.
_seq = itertools.count(1)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_port():
    """A FRESH server.py subprocess per test, so peer-ghost relay state
    (peer_pos / _ghost_visible_to) never bleeds between tests."""
    tcp_port  = _free_port()
    http_port = _free_port()
    tmpdir    = tempfile.mkdtemp(prefix="slink_ghost_test_")
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.server",
         "--host", "127.0.0.1", "--port", str(tcp_port),
         "--http-port", str(http_port), "--data-dir", tmpdir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=repo_root,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", tcp_port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail(f"server did not start on port {tcp_port}")
    yield tcp_port
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


async def _send(reader, writer, payload: dict) -> dict:
    payload = {**payload, "seq": next(_seq)}   # always monotonic, like the client
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))
    await writer.drain()
    raw = await reader.readline()
    return json.loads(raw)


def _ghost_cmds(resp: dict, name: str = "ghost_pos") -> list[dict]:
    return [c for c in resp.get("commands", []) if c.get("cmd") == name]


async def _pump_both(conns, a_pos, b_pos, rounds=3):
    """Send a/b positions for several round-trips so the relay reaches steady
    state (independent of any leftover state from a prior test on the shared
    server), and return (last A response, last B response)."""
    (ra, wa), (rb, wb) = conns
    resp_a = resp_b = None
    for i in range(rounds):
        resp_a = await _send(ra, wa, {"event": "ghost_pos", "player": "a", "seq": 100 + i, **a_pos})
        resp_b = await _send(rb, wb, {"event": "ghost_pos", "player": "b", "seq": 200 + i, **b_pos})
    return resp_a, resp_b


@pytest.mark.asyncio
async def test_ghost_pos_relays_full_coords_over_the_wire(server_port):
    """A's ghost_pos must reach B as a ghost_pos COMMAND carrying A's mg/mn/x/y/
    f/mv/an — the exact bug surfaced live (command arriving with nil coords)."""
    ra, wa = await asyncio.open_connection(SERVER_HOST, server_port)
    rb, wb = await asyncio.open_connection(SERVER_HOST, server_port)
    conns = ((ra, wa), (rb, wb))
    try:
        # Both players say hello.
        await _send(ra, wa, {"event": "hello", "player": "a", "seq": 1,
                             "area_id": "route_1", "rom_type": "firered_rr", "party": []})
        await _send(rb, wb, {"event": "hello", "player": "b", "seq": 1,
                             "area_id": "route_1", "rom_type": "firered_rr", "party": []})

        # Pump both on the same map to steady state; B's response should carry
        # A's ghost_pos with full coords (order-independent on the shared server).
        _, resp_b = await _pump_both(conns,
                                     {"mg": 3, "mn": 5, "x": 10, "y": 20, "f": 2, "mv": 1, "an": 4},
                                     {"mg": 3, "mn": 5, "x": 12, "y": 20, "f": 1, "mv": 0, "an": 0})

        ghosts = _ghost_cmds(resp_b)
        assert ghosts, f"B got no ghost_pos command; response was {resp_b}"
        g = ghosts[0]
        # The coordinates MUST survive serialization (this is the regression).
        assert (g.get("mg"), g.get("mn")) == (3, 5), f"missing/wrong map: {g}"
        assert (g.get("x"), g.get("y")) == (10, 20), f"missing/wrong tile: {g}"
        assert g.get("f") == 2, f"missing facing: {g}"
        assert g.get("mv") == 1, f"missing moving bit: {g}"
        assert g.get("an") == 4, f"missing animNum (run fidelity): {g}"
    finally:
        for w in (wa, wb):
            w.close()
            await w.wait_closed()


@pytest.mark.asyncio
async def test_ghost_clear_when_partner_changes_map_over_the_wire(server_port):
    ra, wa = await asyncio.open_connection(SERVER_HOST, server_port)
    rb, wb = await asyncio.open_connection(SERVER_HOST, server_port)
    conns = ((ra, wa), (rb, wb))
    try:
        await _send(ra, wa, {"event": "hello", "player": "a", "seq": 1, "area_id": "route_1", "party": []})
        await _send(rb, wb, {"event": "hello", "player": "b", "seq": 1, "area_id": "route_1", "party": []})

        # Steady state: both on map (7,1) → B sees A.
        _, resp_b = await _pump_both(conns,
                                     {"mg": 7, "mn": 1, "x": 5, "y": 5, "f": 1, "mv": 0, "an": 0},
                                     {"mg": 7, "mn": 1, "x": 6, "y": 5, "f": 1, "mv": 0, "an": 0})
        assert _ghost_cmds(resp_b), f"B should see A while same-map; got {resp_b}"

        # A walks to a different map; B should stop seeing A and get a ghost_clear.
        await _send(ra, wa, {"event": "ghost_pos", "player": "a", "seq": 50,
                             "mg": 7, "mn": 2, "x": 0, "y": 0, "f": 1, "mv": 1, "an": 4})
        resp_b2 = await _send(rb, wb, {"event": "ghost_pos", "player": "b", "seq": 51,
                                       "mg": 7, "mn": 1, "x": 6, "y": 5, "f": 1, "mv": 0, "an": 0})
        assert _ghost_cmds(resp_b2, "ghost_clear"), f"expected ghost_clear, got {resp_b2}"
        assert not _ghost_cmds(resp_b2, "ghost_pos"), f"should not still send ghost_pos: {resp_b2}"
    finally:
        for w in (wa, wb):
            w.close()
            await w.wait_closed()
