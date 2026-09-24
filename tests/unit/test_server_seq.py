"""A `seq` counter belongs to a TCP connection, and a connection proves itself with hello.

The live `reconnect_new` run found both halves missing at once. Slot A's same-save relaunch
sent nine messages and was killed; a DIFFERENT cartridge then connected as slot A and sent
`hello` with seq 1. The old guard compared that seq against the *slot's* last seq across
connections, and its restart escape hatch only fired for `seq <= 1 and last > 10` — nine is
not more than ten, so the hello was dropped as a duplicate with no log line at all. Every
later tick carried seq > last, so it sailed through with no accepted hello behind it, and at
12:14:23 the unidentified cartridge's party reconciled as slot A and discarded the run's
linked keys.

So: the counter resets with the connection, and nothing but hello is listened to until this
connection has said hello.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest
import pytest_asyncio

from server.server import SLinkServer

HELLO_A = {"event": "hello", "player": "a", "rom_type": "red", "trainer_name": "Alice",
           "ot_id": "30B8", "has_pokeballs": True}


def _tick(seq: int) -> dict:
    return {"event": "tick", "player": "a", "seq": seq, "party": [], "area_id": "pallet_town"}


@pytest.fixture
def srv(tmp_path):
    """A server whose every _dispatch call is recorded as (player, event, seq)."""
    s = SLinkServer(data_dir=str(tmp_path))
    s.dispatched = []
    inner = s._dispatch

    def recording(player_id, msg):
        s.dispatched.append((player_id, msg.get("event"), msg.get("seq")))
        return inner(player_id, msg)

    s._dispatch = recording
    return s


class _Conn:
    """One TCP connection to `srv`, opened and closed like a real client's."""

    def __init__(self, port):
        self._port = port

    async def __aenter__(self):
        self._r, self._w = await asyncio.open_connection("127.0.0.1", self._port)
        return self

    async def __aexit__(self, *exc):
        self._w.close()
        await self._w.wait_closed()
        # The handler's finally block runs on the server's own task; let it.
        await asyncio.sleep(0.05)

    async def send(self, msg):
        self._w.write((json.dumps(msg) + "\n").encode())
        await self._w.drain()
        return json.loads(await asyncio.wait_for(self._r.readline(), 3))


@pytest_asyncio.fixture
async def port(srv):
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    try:
        yield tcp.sockets[0].getsockname()[1]
    finally:
        tcp.close()
        await tcp.wait_closed()


@pytest.mark.asyncio
async def test_a_new_connection_starts_the_seq_counter_over(srv, port):
    """The exact live shape: a short session, then a second connection helloing at seq 1."""
    async with _Conn(port) as first:
        await first.send(dict(HELLO_A, seq=1))
        for n in (2, 3, 4):
            await first.send(_tick(n))

    async with _Conn(port) as second:
        await second.send(dict(HELLO_A, seq=1, ot_id="8C4C"))

    hellos = [d for d in srv.dispatched if d[1] == "hello"]
    assert len(hellos) == 2, f"the second connection's hello was swallowed: {srv.dispatched}"
    assert hellos[1] == ("a", "hello", 1)


@pytest.mark.asyncio
async def test_a_tick_before_hello_never_reaches_dispatch(srv, port, caplog):
    caplog.set_level(logging.WARNING, logger="server.server")
    async with _Conn(port) as c:
        assert (await c.send(_tick(1)))["commands"] == [{"cmd": "noop", "refused": "no_hello"}]
        await c.send(_tick(2))
        # ...and hello still works afterwards, on the same connection.
        await c.send(dict(HELLO_A, seq=3))
        await c.send(_tick(4))

    assert [d[1] for d in srv.dispatched] == ["hello", "tick"], srv.dispatched
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and "before hello" in r.getMessage()]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert "tick" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_a_repeated_seq_on_one_connection_is_still_a_duplicate(srv, port):
    async with _Conn(port) as c:
        await c.send(dict(HELLO_A, seq=1))
        await c.send(_tick(2))
        assert (await c.send(_tick(2)))["commands"] == [{"cmd": "noop", "refused": "duplicate"}]
        assert (await c.send(_tick(1)))["commands"] == [{"cmd": "noop", "refused": "duplicate"}]

    assert [d[2] for d in srv.dispatched] == [1, 2], srv.dispatched


# ── INV-SERVER x INV-CLIENT: a line the server did not process says so (`refused`) ──────────────
# The client retires an owed report only on a reply WITHOUT a `refused` command.

@pytest.mark.asyncio
async def test_every_unprocessed_line_is_answered_with_a_refused_noop(srv, port):
    async with _Conn(port) as c:
        assert (await c.send(_tick(1)))["commands"] == [{"cmd": "noop", "refused": "no_hello"}]
        accepted = await c.send({**HELLO_A, "seq": 1})
        assert not any(cmd.get("refused") for cmd in accepted["commands"])
        assert (await c.send(_tick(1)))["commands"] == [{"cmd": "noop", "refused": "duplicate"}]
        srv.state.identity_error["a"] = "wrong save"
        assert (await c.send(_tick(2)))["commands"] == [{"cmd": "noop", "refused": "identity"}]
        srv.state.identity_error.pop("a")
        srv.is_admitted = lambda pid: False
        assert (await c.send(_tick(3)))["commands"] == [{"cmd": "noop", "refused": "admission"}]
