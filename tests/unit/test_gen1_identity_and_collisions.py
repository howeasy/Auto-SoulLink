"""Two correctness floors that were simply absent: who the player is, and whether a
mon key identifies one mon.

**Identity was inferred from whichever mon was in slot 0.** `_handle_hello` derived the
OT id from `party[0]`'s key, so leading with an in-game-trade mon -- a different OT by
definition -- locked the run to the wrong trainer permanently, and every later hello was
rejected as WRONG SAVE until someone hand-edited links.json.

**A mon key is not unique.** Gen 1's is `DVs:OTID:species`, and OT is identical for every
mon a player caught themselves, so two of one species with the same DVs collide (~1 in
65536 per same-species pair). `_key_index` is a plain dict, so the second link silently
aliased the first and every lookup by that key -- faint propagation above all -- resolved
to the wrong pair, killing the wrong mon on the partner's cartridge.
"""
from __future__ import annotations

import pytest

from server.adapters.gen1_rby import Gen1Adapter
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    s = SoulLinkState()
    s.adapter = Gen1Adapter(variant="red")
    return s


def _mon(key, species=16, level=5):
    return MonInfo(key=key, level=level, species=species, nickname="")


# ── identity ─────────────────────────────────────────────────────────────────────────

def test_the_reported_trainer_id_wins_over_the_lead_mon(st):
    """A traded mon in slot 0 must not decide who the player is."""
    st._handle_hello("a", {"event": "hello", "ot_id": "30B8", "trainer_name": "RED",
                           "party": [{"key": "9999:7B0B:B1"}]})   # a DIFFERENT OT in the key
    assert st.player_identity["a"]["ot_id"] == "30B8"


def test_a_later_hello_with_the_same_cartridge_is_accepted(st):
    """The load-bearing control: the lock must still LOCK, or this is just a hole."""
    hello = {"event": "hello", "ot_id": "30B8", "trainer_name": "RED", "party": []}
    st._handle_hello("a", dict(hello))
    msg = dict(hello)
    st._handle_hello("a", msg)
    assert not msg.get("_rejected")
    assert not st.identity_error.get("a")


def test_a_different_cartridge_is_still_rejected(st):
    st._handle_hello("a", {"event": "hello", "ot_id": "30B8", "trainer_name": "RED",
                           "party": []})
    msg = {"event": "hello", "ot_id": "7B0B", "trainer_name": "BLUE", "party": []}
    st._handle_hello("a", msg)
    assert msg.get("_rejected"), "a different save's OT must be refused"
    assert "Identity mismatch" in st.identity_error["a"]


def test_a_client_that_reports_no_ot_still_falls_back_to_the_key(st):
    """Other generations do not send ot_id and must keep working exactly as before."""
    st._handle_hello("a", {"event": "hello", "trainer_name": "RED",
                           "party": [{"key": "9999:30B8:B1"}]})
    assert st.player_identity["a"]["ot_id"] == "30B8"


# ── key collisions ───────────────────────────────────────────────────────────────────

def test_a_capture_colliding_with_a_live_link_is_refused(st):
    """The whole point: refuse rather than alias."""
    live = LinkEntry(area_id="route_1", a=_mon("AABB:30B8:10"), b=_mon("CCDD:7B0B:10"),
                     status=LinkStatus.ALIVE)
    st.links.append(live)
    st._index_entry(live)

    # A different mon, same key as A's existing half.
    result = st._check_link_violation(_mon("AABB:30B8:10"), _mon("EEFF:7B0B:10"))
    assert result is not None, "a colliding key was accepted and would alias the live link"
    violation, pid = result
    assert "Key collision" in violation
    assert pid == "a"


def test_a_collision_with_a_DEAD_link_is_allowed(st):
    """A buried mon's key is no longer load-bearing; refusing here would cost the
    player encounters for no benefit."""
    dead = LinkEntry(area_id="route_1", a=_mon("AABB:30B8:10"), b=_mon("CCDD:7B0B:10"),
                     status=LinkStatus.DEAD)
    st.links.append(dead)
    st._index_entry(dead)
    assert st._check_link_violation(_mon("AABB:30B8:10"), _mon("EEFF:7B0B:10")) is None


def test_two_halves_reporting_one_key_are_two_players_mons(st):
    """KEY-SCOPE: identity is per player, so the two halves may share a key (a fixed-DV/OT
    NPC-trade or gift mon on both cartridges); each is looked up in its own player's index."""
    result = st._check_link_violation(_mon("AABB:30B8:10"), _mon("AABB:30B8:10"))
    assert result is None or "Key collision" not in result[0]


def test_ordinary_distinct_keys_still_link(st):
    """The control. A check that rejected everything would break every run."""
    assert st._check_link_violation(_mon("AABB:30B8:10"), _mon("CCDD:7B0B:11")) is None


def test_the_collision_check_does_not_need_the_species_lock(st):
    """It is a correctness floor, not a rule the player opted into."""
    st.species_lock = False
    live = LinkEntry(area_id="route_1", a=_mon("AABB:30B8:10"), b=_mon("CCDD:7B0B:10"),
                     status=LinkStatus.ALIVE)
    st.links.append(live)
    st._index_entry(live)
    assert st._check_link_violation(_mon("AABB:30B8:10"), _mon("EEFF:7B0B:11")) is not None


def test_index_entry_reports_a_collision_it_cannot_refuse(st, caplog):
    """Links also arrive from disk and from bonus pairs, where refusing is not an
    option; the alias must at least be loud instead of silent."""
    first = LinkEntry(area_id="route_1", a=_mon("AABB:30B8:10"), b=_mon("CCDD:7B0B:10"),
                      status=LinkStatus.ALIVE)
    second = LinkEntry(area_id="route_2", a=_mon("AABB:30B8:10"), b=_mon("EEFF:7B0B:11"),
                       status=LinkStatus.ALIVE)
    st._index_entry(first)
    with caplog.at_level("ERROR"):
        st._index_entry(second)
    assert any("KEY COLLISION" in r.message for r in caplog.records)
