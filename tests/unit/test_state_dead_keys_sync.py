"""INV-CLIENT-2: every accepted hello carries this player's authoritative dead/memorial keys.

The Gen 1/Gen 2 clients REPLACE their dead-key re-zero set with it (lua/gen1/client.lua,
lua/gen2/client.lua `dead_keys`), so a debug revive, an unlink, a rollback or another save with the
same OT leaves no stale kill. No emulator.
"""
from __future__ import annotations

from server.adapters.gen2_gsc import Gen2GSCAdapter
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState


def _link(st, a_key, b_key, status):
    entry = LinkEntry(area_id="route_" + a_key[-1], a=MonInfo(key=a_key, level=5, nickname="A"),
                      b=MonInfo(key=b_key, level=5, nickname="B"), status=status)
    st.links.append(entry)
    st._index_entry(entry)


def _dead_keys(cmds):
    rows = [c for c in cmds if c.get("cmd") == "dead_keys"]
    assert len(rows) == 1, cmds
    return rows[0]["keys"]


def test_every_accepted_hello_lists_this_players_dead_and_memorial_keys(tmp_path):
    st = SoulLinkState(data_dir=str(tmp_path), adapter=Gen2GSCAdapter(rom_type="Crystal"))
    _link(st, "AAAA:1111:01", "BBBB:2222:01", LinkStatus.ALIVE)
    _link(st, "AAAA:1111:02", "BBBB:2222:02", LinkStatus.DEAD)
    _link(st, "AAAA:1111:03", "BBBB:2222:03", LinkStatus.MEMORIAL)
    hello = {"event": "hello", "party": [], "ot_id": "1111", "trainer_name": "A"}
    assert _dead_keys(st.handle_event("a", dict(hello))) == ["AAAA:1111:02", "AAAA:1111:03"]
    assert _dead_keys(st.handle_event("b", dict(hello, ot_id="2222"))) == ["BBBB:2222:02", "BBBB:2222:03"]
    st.links[1].status = LinkStatus.ALIVE                       # an admin revive
    assert _dead_keys(st.handle_event("a", dict(hello))) == ["AAAA:1111:03"], "every hello: a fresh list"


def test_a_rejected_hello_carries_no_dead_keys(tmp_path):
    st = SoulLinkState(data_dir=str(tmp_path), adapter=Gen2GSCAdapter(rom_type="Crystal"))
    _link(st, "AAAA:1111:02", "BBBB:2222:02", LinkStatus.DEAD)
    st.handle_event("a", {"event": "hello", "party": [], "ot_id": "1111", "trainer_name": "A"})
    cmds = st.handle_event("a", {"event": "hello", "party": [], "ot_id": "9999", "trainer_name": "Z"})
    assert not any(c.get("cmd") == "dead_keys" for c in cmds)
