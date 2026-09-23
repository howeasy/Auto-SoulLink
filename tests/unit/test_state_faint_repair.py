"""Owner ruling O-24: the server repairs a lost `force_faint` (OMP review O13).

`force_faint` has no ack on the wire, and `_propagate_faint` marks the pair DEAD in the
same call that queues it, so a command the client never applied left a dead mon alive
for the rest of the run.  The repair reads only what every client already sends: the
tick's party snapshot (`key`, `hp`) and `in_battle`.  A key in the PARTY snapshot at
HP > 0 whose link is not ALIVE gets `force_faint` again -- once per in-flight window,
never while a death command is queued or still on the wire, never counting down during
a battle (the client holds an active battler's faint to battle end), and at most
FAINT_REPAIR_BUDGET times before it stops and logs an error.

Shared-runtime tests: reconciler passes, never frames, and the same body under a Gen 1,
Gen 2 and Gen 3 adapter.  No emulator.
"""
from __future__ import annotations

import logging

import pytest

import server.state as state_mod
from server.adapters.gen1_rby import Gen1Adapter
from server.adapters.gen2_crystal import Gen2CrystalAdapter
from server.adapters.gen3_frlge import Gen3Adapter
from server.state import SYNC_INFLIGHT_RECONCILES, LinkEntry, LinkStatus, MonInfo, SoulLinkState


@pytest.fixture(params=[Gen1Adapter, Gen2CrystalAdapter, Gen3Adapter], ids=["gen1", "gen2", "gen3"])
def st(request, tmp_path):
    s = SoulLinkState(data_dir=str(tmp_path), adapter=request.param())
    s.pokeballs_obtained = {"a": True, "b": True}
    s.party_size = {"a": 2, "b": 2}
    return s


def _link(st, a_key, b_key, status=LinkStatus.ALIVE, area="route_1") -> LinkEntry:
    entry = LinkEntry(area_id=area, a=MonInfo(key=a_key, level=5, nickname="AMON"),
                      b=MonInfo(key=b_key, level=5, nickname="BMON"), status=status)
    st.links.append(entry)
    st._index_entry(entry)
    if status == LinkStatus.ALIVE:
        st.party_keys["a"].add(a_key)
        st.party_keys["b"].add(b_key)
    return entry


def _killed(st) -> LinkEntry:
    """A's A:1 faints -> B:1 is owed a force_faint; a second pair keeps the run alive."""
    _link(st, "A:2", "B:2", area="route_2")
    entry = _link(st, "A:1", "B:1")
    st._propagate_faint("a", entry)
    return entry


def _tick(st, player="b", hp=20, key=None, in_battle=False) -> list[dict]:
    key = key or f"{player.upper()}:1"
    party = [{"key": key, "hp": hp, "maxHP": 20},
             {"key": f"{player.upper()}:2", "hp": 20, "maxHP": 20}]
    return st.handle_event(player, {"event": "tick", "party": party, "in_battle": in_battle})


def _faints(cmds, key="B:1") -> int:
    return sum(1 for c in cmds if c.get("cmd") in state_mod.DEATH_COMMANDS and c.get("key") == key)


def test_lost_faint_is_reissued_once_per_window_and_stops_at_the_budget(st, caplog):
    """RED at c5275252: a DEAD half alive in the party is never killed again."""
    budget = state_mod.FAINT_REPAIR_BUDGET
    _killed(st)
    issued_at = []
    with caplog.at_level(logging.WARNING, logger="server.state"):
        for n in range(SYNC_INFLIGHT_RECONCILES * (budget + 3)):
            hits = _faints(_tick(st))
            assert hits <= 1, f"double-issued on pass {n}"
            if hits:
                issued_at.append(n)
    # pass 0 delivers the ORIGINAL (still queued when the snapshot arrived: no duplicate)
    assert issued_at[0] == 0
    assert len(issued_at) == 1 + budget, issued_at
    gaps = [b - a for a, b in zip(issued_at, issued_at[1:], strict=False)]
    assert all(g == SYNC_INFLIGHT_RECONCILES for g in gaps), gaps
    assert sum(r.levelno == logging.WARNING and "re-issued force_faint" in r.message
               for r in caplog.records) == budget, "every re-issue is logged"
    gave_up = [r for r in caplog.records if r.levelno == logging.ERROR and "B:1" in r.message]
    assert len(gave_up) == 1, "budget exhaustion must be logged loudly, exactly once"


def test_battle_hold_does_not_spend_the_window(st):
    """The client defers an active battler's faint to battle end: a long battle is one window."""
    _killed(st)
    assert _faints(_tick(st, in_battle=True)) == 1          # the original goes out mid-battle
    for _ in range(SYNC_INFLIGHT_RECONCILES * 5):
        assert _faints(_tick(st, in_battle=True)) == 0
    # back in the overworld the window runs; the faint may land at the checkpoint
    for _ in range(SYNC_INFLIGHT_RECONCILES - 1):
        assert _faints(_tick(st)) == 0
    assert _faints(_tick(st)) == 1


def test_revived_dead_mon_is_rekilled_and_hp0_triggers_nothing(st):
    """Dead stays dead -- on either side.  A's own fainted half at HP 0 is simply dead."""
    _killed(st)
    _tick(st)                                               # deliver B's original
    for _ in range(SYNC_INFLIGHT_RECONCILES * 3):
        assert _faints(_tick(st, player="a", hp=0), "A:1") == 0
        assert _faints(_tick(st, hp=0)) == 0
    assert _faints(_tick(st, player="a", hp=12), "A:1") == 1   # A revived its dead half


def test_budget_resets_once_the_repair_lands(st):
    """HP 0 is proof the kill took; a later revive is a new incident with a fresh budget."""
    budget = state_mod.FAINT_REPAIR_BUDGET
    _killed(st)
    for _ in range(SYNC_INFLIGHT_RECONCILES * (budget + 2)):
        _tick(st)                                           # exhaust
    assert _faints(_tick(st)) == 0
    _tick(st, hp=0)
    assert _faints(_tick(st)) == 1


@pytest.mark.parametrize("status", [LinkStatus.DEAD, LinkStatus.MEMORIAL])
def test_dead_mon_in_the_box_triggers_nothing(st, status):
    _link(st, "A:2", "B:2", area="route_2")
    _link(st, "A:1", "B:1", status=status)
    for _ in range(SYNC_INFLIGHT_RECONCILES * 3):
        cmds = st.handle_event("b", {"event": "tick",
                                     "party": [{"key": "B:2", "hp": 20, "maxHP": 20}]})
        assert _faints(cmds) == 0


def test_alive_entry_and_hpless_snapshot_trigger_nothing(st):
    _link(st, "A:2", "B:2", area="route_2")
    _link(st, "A:1", "B:1")
    for _ in range(SYNC_INFLIGHT_RECONCILES * 3):
        assert _faints(_tick(st)) == 0
    # a dead link but a snapshot that carries no hp is no evidence either way
    st._propagate_faint("a", st._key_index["A:1"])
    _tick(st)
    for _ in range(SYNC_INFLIGHT_RECONCILES * 3):
        cmds = st.handle_event("b", {"event": "tick", "party": [{"key": "B:1"}, {"key": "B:2"}]})
        assert _faints(cmds) == 0


def test_run_over_triggers_nothing(st):
    entry = _link(st, "A:1", "B:1")
    st._propagate_faint("a", entry)
    assert st.run_over
    _tick(st)
    for _ in range(SYNC_INFLIGHT_RECONCILES * 3):
        assert _faints(_tick(st)) == 0
