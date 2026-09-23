"""Owner ruling O-24: the server repairs a lost `force_faint` (OMP reviews O13, O18).

`force_faint` has no ack on the wire, and `_propagate_faint` marks the pair DEAD in the
same call that queues it, so a command the client never applied left a dead mon alive
for the rest of the run.  The repair reads only what every client already sends: the
tick's party snapshot (`key`, `hp`) and `in_battle`.  A key in the PARTY snapshot at
HP > 0 whose link is not ALIVE gets `force_faint` again: never while a death command is
queued or inside its FAINT_REPAIR_RECONCILES window (long, because Gen 1/2 hold a
delivered faint out of battle until their overworld checkpoint; the window does not run
in battle at all), at most FAINT_REPAIR_BUDGET times, then a stall for
FAINT_REPAIR_COOLDOWN passes after which the budget refills.

The repair is on for every generation (no per-game switch).  The Gen 1/2/3 adapter
parametrization only shows the shared rule does not consult the adapter; it proves
nothing generation-specific.  Reconciler passes, never frames.  No emulator.
"""
from __future__ import annotations

import asyncio
import functools
import logging

import pytest

from server.adapters.gen1_rby import Gen1Adapter
from server.adapters.gen2_gsc import Gen2GSCAdapter
from server.adapters.gen3_frlge import Gen3Adapter
from server.state import (
    DEATH_COMMANDS,
    FAINT_REPAIR_BUDGET as BUDGET,
    FAINT_REPAIR_COOLDOWN as COOLDOWN,
    FAINT_REPAIR_RECONCILES as WINDOW,
    LinkEntry,
    LinkStatus,
    MonInfo,
    SoulLinkState,
)


@pytest.fixture(params=[Gen1Adapter, functools.partial(Gen2GSCAdapter, rom_type="Crystal"), Gen3Adapter],
                ids=["gen1", "gen2", "gen3"])
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
    return sum(1 for c in cmds if c.get("cmd") in DEATH_COMMANDS and c.get("key") == key)


def test_held_faint_is_reissued_once_per_long_window_stalls_then_refills(st, caplog):
    """F1 falsifier: a client that holds (menu/PC/script) or wipes its queue, hp unchanged.

    At most one issue per WINDOW, the stall is surfaced, and the budget comes back:
    the issue after the cool-down is the repair of a genuine later loss (a wiped queue
    looks exactly like this from the server).  RED at 6e9bff5b: the window was 6 passes
    and the budget, once spent, never refilled.
    """
    _killed(st)
    issued_at, stalled_at = [], []
    total = WINDOW * (BUDGET + 1) + COOLDOWN + WINDOW + 1
    with caplog.at_level(logging.WARNING, logger="server.state"):
        for n in range(total):
            hits = _faints(_tick(st))
            assert hits <= 1, f"double-issued on pass {n}"
            if hits:
                issued_at.append(n)
            if "B:1" in st.faint_repair_stalled["b"]:
                stalled_at.append(n)
    # pass 0 delivers the ORIGINAL (still queued when the snapshot arrived: no duplicate)
    assert issued_at[:BUDGET + 1] == [k * WINDOW for k in range(BUDGET + 1)], issued_at
    gaps = [b - a for a, b in zip(issued_at, issued_at[1:], strict=False)]
    assert all(g >= WINDOW for g in gaps), gaps
    stall = (BUDGET + 1) * WINDOW
    assert stalled_at[0] == stall and len(stalled_at) == COOLDOWN, (stalled_at[:1], len(stalled_at))
    assert issued_at[BUDGET + 1] == stall + COOLDOWN, "the budget must refill after the cool-down"
    warned = [r for r in caplog.records
              if r.levelno == logging.WARNING and "re-issued force_faint" in r.message]
    assert len(warned) == len(issued_at) - 1, "every re-issue is logged"
    stalls = [r for r in caplog.records if r.levelno == logging.ERROR and "B:1" in r.message]
    assert len(stalls) == 1, "the stall is logged loudly, once"


def test_out_of_battle_hold_of_50_seconds_gets_no_duplicate(st):
    """Absolute floor, not relative to WINDOW: Gen 1/2 hold a delivered faint until the
    overworld checkpoint, and a player in the PC or a menu holds it.  100 passes is ~50 s
    at the 0.5 s tick every Gen 1/2/3 client uses.  RED at 6e9bff5b (6-pass window)."""
    _killed(st)
    assert _faints(_tick(st)) == 1
    for n in range(100):
        assert _faints(_tick(st)) == 0, f"duplicate after {n + 1} out-of-battle passes"


def test_battle_hold_does_not_spend_the_window(st):
    """The client defers an active battler's faint to battle end: a long battle is one window."""
    _killed(st)
    assert _faints(_tick(st, in_battle=True)) == 1          # the original goes out mid-battle
    for _ in range(WINDOW * 3):
        assert _faints(_tick(st, in_battle=True)) == 0
    for _ in range(WINDOW - 1):                              # back in the overworld the window runs
        assert _faints(_tick(st)) == 0
    assert _faints(_tick(st)) == 1


def test_revived_dead_mon_is_rekilled_and_hp0_triggers_nothing(st):
    """Dead stays dead -- on either side.  A's own fainted half at HP 0 is simply dead."""
    _killed(st)
    _tick(st)                                               # deliver B's original
    for _ in range(WINDOW + 5):
        assert _faints(_tick(st, player="a", hp=0), "A:1") == 0
        assert _faints(_tick(st, hp=0)) == 0
    assert _faints(_tick(st, player="a", hp=12), "A:1") == 1   # A revived its dead half


def test_budget_resets_once_the_repair_lands(st):
    """HP 0 is proof the kill took; a later revive is a new incident with a fresh budget."""
    _killed(st)
    for _ in range(WINDOW * (BUDGET + 1) + 1):
        _tick(st)                                           # spend the budget and stall
    assert "B:1" in st.faint_repair_stalled["b"]
    _tick(st, hp=0)
    assert st.faint_repair_stalled["b"] == {} and st.faint_repairs["b"] == {}
    assert _faints(_tick(st)) == 1


def test_withdrawn_memorial_mon_is_rekilled_once(st):
    _link(st, "A:2", "B:2", area="route_2")
    _link(st, "A:1", "B:1", status=LinkStatus.MEMORIAL)
    assert _faints(_tick(st)) == 1
    for _ in range(WINDOW - 1):
        assert _faints(_tick(st)) == 0


@pytest.mark.parametrize("status", [LinkStatus.DEAD, LinkStatus.MEMORIAL])
def test_dead_mon_in_the_box_triggers_nothing(st, status):
    _link(st, "A:2", "B:2", area="route_2")
    _link(st, "A:1", "B:1", status=status)
    for _ in range(WINDOW + 5):
        cmds = st.handle_event("b", {"event": "tick",
                                     "party": [{"key": "B:2", "hp": 20, "maxHP": 20}]})
        assert _faints(cmds) == 0


def test_partner_half_in_the_wrong_party_is_inert(st):
    _link(st, "A:2", "B:2", area="route_2")
    _link(st, "A:1", "B:1", status=LinkStatus.DEAD)
    for _ in range(WINDOW + 5):
        assert _faints(_tick(st, key="A:1"), "A:1") == 0   # A's dead half in B's party


def test_quarantined_key_is_inert(st):
    """A pending capture that collides with a buried key (Gen 1 keys can) is not re-killed."""
    _link(st, "A:2", "B:2", area="route_2")
    _link(st, "A:1", "B:1", status=LinkStatus.DEAD)
    st.pending_captures["route_9"] = {"b": MonInfo(key="B:1", level=3)}
    for _ in range(WINDOW + 5):
        assert _faints(_tick(st)) == 0


def test_safe_event_without_party_is_inert(st):
    _killed(st)
    _tick(st)                                               # deliver the original
    for _ in range(WINDOW * 2):
        assert _faints(st.handle_event("b", {"event": "safe"})) == 0
    # a safe event is not a reconciler pass, so the window has not moved either
    for _ in range(WINDOW - 1):
        assert _faints(_tick(st)) == 0
    assert _faints(_tick(st)) == 1


def test_alive_entry_and_hpless_snapshot_trigger_nothing(st):
    _link(st, "A:2", "B:2", area="route_2")
    _link(st, "A:1", "B:1")
    for _ in range(WINDOW + 5):
        assert _faints(_tick(st)) == 0
    # a dead link but a snapshot that carries no hp is no evidence either way
    st._propagate_faint("a", st._key_index["A:1"])
    _tick(st)
    for _ in range(WINDOW + 5):
        cmds = st.handle_event("b", {"event": "tick", "party": [{"key": "B:1"}, {"key": "B:2"}]})
        assert _faints(cmds) == 0


def test_run_over_triggers_nothing(st):
    entry = _link(st, "A:1", "B:1")
    st._propagate_faint("a", entry)
    assert st.run_over
    _tick(st)
    for _ in range(WINDOW + 5):
        assert _faints(_tick(st)) == 0


def _stall(st) -> None:
    _killed(st)
    for _ in range(WINDOW * (BUDGET + 1) + 1):
        _tick(st)
    assert "B:1" in st.faint_repair_stalled["b"] and st.faint_repairs["b"]


def test_rollback_reload_starts_with_a_fresh_budget(st):
    """server.handle_rollback_api rebuilds via SoulLinkState.load: the spend is in-memory only."""
    _stall(st)
    fresh = SoulLinkState.load(data_dir=st._data_dir, adapter=st.adapter)
    fresh.pokeballs_obtained = {"a": True, "b": True}
    assert fresh.faint_repairs == fresh.faint_repair_stalled == fresh.death_inflight == {"a": {}, "b": {}}
    assert _faints(_tick(fresh)) == 1                       # the reloaded DEAD link repairs at once


def test_reset_builds_fresh_state_and_status_surfaces_the_stall(tmp_path):
    from server.server import SLinkServer
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.pokeballs_obtained = {"a": True, "b": True}
    srv.state.party_size = {"a": 2, "b": 2}
    _stall(srv.state)
    assert srv._build_status_dict()["faint_repair_stalled"] == {"a": [], "b": ["B:1"]}
    asyncio.run(srv.handle_reset_api(None))
    assert srv.state.faint_repairs == srv.state.faint_repair_stalled == {"a": {}, "b": {}}
    assert srv._build_status_dict()["faint_repair_stalled"] == {"a": [], "b": []}
