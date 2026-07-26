"""What the missing Gen 2 ack actually cost, proven server-side.

`test_client_acks.py` checks that each client *sends* the message. These tests check what the
server does with it — because the message is not the point, the consequences are:

  1. the pair only reaches LinkStatus.MEMORIAL when BOTH sides confirm,
  2. memorial.json is only written at that moment (so the Memorial page was empty for an entire
     Gen 2 run), and
  3. an unconfirmed key is re-queued on every single reconnect, forever.

Written against the state machine rather than a client, so it holds for any generation.
"""
import json
import os

import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState


@pytest.fixture
def st(tmp_path):
    s = SoulLinkState(data_dir=str(tmp_path), adapter=Gen3Adapter(is_rr=True))
    entry = LinkEntry(area_id="route_3",
                      a=MonInfo(key="A:1", level=9, species=1),
                      b=MonInfo(key="B:1", level=9, species=4),
                      status=LinkStatus.DEAD)
    s.links.append(entry)
    s._index_entry(entry)
    s.pending_memorials["a"].add("A:1")
    s.pending_memorials["b"].add("B:1")
    return s


def test_one_side_confirming_is_not_enough(st):
    """A pair is memorialised when BOTH halves are in their box, not when the first one is."""
    st._handle_memorialize_done("a", {"key": "A:1"})
    assert st.links[0].status == LinkStatus.DEAD
    assert not os.path.exists(st._memorial_path)


def test_both_sides_confirming_writes_the_memorial(st):
    st._handle_memorialize_done("a", {"key": "A:1"})
    st._handle_memorialize_done("b", {"key": "B:1"})
    assert st.links[0].status == LinkStatus.MEMORIAL
    assert os.path.exists(st._memorial_path), "the Memorial page's data file is never written"
    with open(st._memorial_path, encoding="utf-8") as f:
        assert json.load(f), "memorial.json written but empty"


def test_without_the_ack_the_pair_never_memorialises(st):
    """This was Gen 2's entire run: the deposit happened in-game, the server never heard, and the
    Memorial wall stayed empty from start to finish."""
    assert st.links[0].status == LinkStatus.DEAD
    assert st.pending_memorials["a"] == {"A:1"}
    assert not os.path.exists(st._memorial_path)


def test_an_unconfirmed_memorial_is_requeued_on_every_reconnect(st):
    """The second, quieter cost: the command replays forever.

    Each reconnect re-queues it, so a Gen 2 run accumulated a permanent backlog for mons that
    had already been deposited.
    """
    def _reconnect():
        # handle_event DRAINS the queue and returns the batch, so the outgoing commands are the
        # return value — reading state.queued_commands afterwards only sees an emptied list.
        sent = st.handle_event("a", {"event": "hello", "party": []})
        return [c for c in sent
                if c.get("cmd") == "memorialize" and c.get("key") == "A:1"]

    for _ in range(3):
        assert _reconnect(), "expected the unconfirmed memorial to be re-queued"

    # ...and once confirmed, it stops.
    st._handle_memorialize_done("a", {"key": "A:1"})
    assert not _reconnect(), "a confirmed memorial must not be re-queued"
