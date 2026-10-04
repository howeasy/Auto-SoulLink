"""Every client must confirm the deferred commands the server waits on.

`memorialize` is not fire-and-forget. The server holds the key in `pending_memorials` until a
`memorialize_done` arrives, and until then:

  * the pair never reaches `LinkStatus.MEMORIAL`,
  * `_write_memorial` never runs, so the Memorial page stays empty for the whole run,
  * and `handle_event`'s reconnect path re-queues the same command every single time the client
    reconnects (`state.py`, "reconnect: re-queued memorialize").

Gen 2 shipped without it — the only one of five clients that did — so a Gen 2 run had a
permanently empty Memorial wall and an ever-replaying command backlog. Nothing failed loudly.

This is a cross-client invariant test rather than a Gen 2 regression test, because the same
omission in a future client would be just as silent.
"""
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLIENT_DIR = os.path.join(REPO, "lua", "clients")

CLIENTS = sorted(f for f in os.listdir(CLIENT_DIR) if f.endswith("_client.lua"))


def _read(fn):
    with open(os.path.join(CLIENT_DIR, fn), encoding="utf-8") as f:
        return f.read()


def test_there_are_clients_to_check():
    """Guards against the glob silently matching nothing and the suite passing vacuously.

    P8-2b: four, not five. Gen 1 left lua/clients/ for lua/gen1/, where the client is a module
    rather than a BizHawk entry script, and its acks are covered below against that path.
    Written as a lower bound so it holds before and after the old client's deletion.
    P3b.8: three -- Gen 2's legacy client went the same way (lua/gen2/ replaces it).
    C5-6: two -- the old Gen 3 client was deleted too (lua/gen3/ replaces it).
    G3a: one -- the legacy Gen 4 client was deleted (lua/gen4/ replaces it); gen5_bw_client.lua is
    the last BizHawk entry-script client. Gen 4's acks are checked below against its module graph.
    """
    assert len(CLIENTS) >= 1


GEN1_CLIENT = os.path.join(REPO, "lua", "gen1", "client.lua")


def test_the_gen1_client_confirms_and_can_refuse_every_deferred_command():
    """The same invariant for the rewritten client, read off the protocol rather than
    restated: a command added to tests/unit/protocol_schema.py:ACKS with no reply here
    fails, which is exactly the omission Gen 2 shipped."""
    from tests.unit.protocol_schema import ACKS

    with open(GEN1_CLIENT, encoding="utf-8") as f:
        src = f.read()
    for cmd, (done, failed) in ACKS.items():
        for reply in (done, failed):
            if reply is None:
                continue
            assert reply in src, (
                f"lua/gen1/client.lua handles {cmd!r} but never sends {reply!r}; the server "
                f"waits on that reply and re-queues the command on every reconnect")


GEN4_GRAPH = [os.path.join(REPO, "lua", "gen4", "client.lua"),
              os.path.join(REPO, "lua", "core", "session.lua"),
              os.path.join(REPO, "lua", "core", "deferred.lua")]


def test_the_gen4_client_graph_confirms_and_can_refuse_every_deferred_command():
    """G3a: the Gen 4 client is a module on the shared core, like Gen 1, so its acks are read off the
    protocol across the files that send them (the core owns the generic replies, the client its own)."""
    from tests.unit.protocol_schema import ACKS

    src = ""
    for path in GEN4_GRAPH:
        with open(path, encoding="utf-8") as f:
            src += f.read()
    # Gen 4 implements the deferred party/box/memorialize commands only (no rival team, menus or trade
    # yet): a command is held to its acks once the graph names it, and the floor below keeps the filter
    # from silently matching nothing.
    handled = [cmd for cmd in ACKS if f'"{cmd}"' in src]
    assert {"party_mon", "box_mon", "memorialize"} <= set(handled), handled
    for cmd in handled:
        done, failed = ACKS[cmd]
        for reply in (done, failed):
            if reply is None:
                continue
            assert reply in src, (
                f"the Gen 4 client graph handles {cmd!r} but never sends {reply!r}; the server "
                f"waits on that reply and re-queues the command on every reconnect")


@pytest.mark.parametrize("client", CLIENTS)
def test_a_client_that_handles_memorialize_also_confirms_it(client):
    src = _read(client)
    if 'cmd.cmd == "memorialize"' not in src and 'c.cmd == "memorialize"' not in src:
        pytest.skip(f"{client} does not implement memorialize")
    assert "memorialize_done" in src, (
        f"{client} executes `memorialize` but never sends `memorialize_done`. The server will "
        f"keep the key in pending_memorials forever: the pair never becomes MEMORIAL, the "
        f"Memorial page stays empty, and every reconnect re-queues the command."
    )


@pytest.mark.parametrize("client", CLIENTS)
def test_a_client_that_confirms_also_reports_failure(client):
    """Done and failed are a pair. A client that can only report success leaves the server
    waiting forever on the one case that actually needs attention."""
    src = _read(client)
    if "memorialize_done" not in src:
        pytest.skip(f"{client} does not implement memorialize")
    assert "memorialize_failed" in src, (
        f"{client} confirms success but can never report a failed memorialize"
    )


