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
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLIENT_DIR = os.path.join(REPO, "lua", "clients")

CLIENTS = sorted(f for f in os.listdir(CLIENT_DIR) if f.endswith("_client.lua"))


def _read(fn):
    with open(os.path.join(CLIENT_DIR, fn), encoding="utf-8") as f:
        return f.read()


def test_there_are_clients_to_check():
    """Guards against the glob silently matching nothing and the suite passing vacuously."""
    assert len(CLIENTS) >= 5


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


def test_gen2_confirms_the_already_boxed_or_missing_case():
    """The specific Gen 2 regression.

    Deliberately NOT generalised across clients. Gen 3 routes every outcome through a single
    `memorialize_finish` helper, so counting send-sites would flag it as broken when it is in
    fact the better shape — an earlier version of this test did exactly that, and would have
    pushed someone to duplicate Gen 3's ack for no reason. The invariant that matters is "no
    path exits without reporting", which is not something a regex can see; so this pins the one
    branch that was genuinely silent.
    """
    src = _read("gen2_crystal_client.lua")
    idx = src.index('cmd.cmd == "memorialize"')
    branch = src[idx:idx + 3000]
    tail = branch[branch.index("Try box scan"):]
    assert "memorialize_done" in tail, (
        "Gen 2's already-boxed / not-found branch does not confirm, so the server re-queues "
        "that memorialize on every reconnect for a mon that no longer exists"
    )
