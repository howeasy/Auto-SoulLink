"""INV-SERVER: the server findings of the independent Soul Link invariant review
(docs/gen2/reviews/REVIEW_SOULLINK_INVARIANTS_2026-09-24.md). Each reviewer probe (P1b, P2b,
P3b, P4/P7, P5, P6, P8) is a red test here. The trade FSM is generation-neutral; the Gen 1
fixtures of test_state_trade_uncertain are reused."""

import pytest

from server.state import LinkStatus
from tests.unit.test_state_trade_uncertain import _gen1_applying, _mon, _tick

A_GETS, B_GETS = "1234:5678:15", "ABCD:1234:26"     # _gen1_applying: A gives ABCD:1234:26, B gives 1234:5678:15


def _cmds(state, pid):
    return state.handle_event(pid, {"event": "noop"})


def _keys(cmds, name):
    return [c.get("key") for c in cmds if c.get("cmd") == name]


def _one_sided(tmp_path):
    """A committed and holds B's mon; B is uncertain (silent or reset)."""
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})
    return state, entry, token


def _hello(state, pid, *mons):
    ot, name = {"a": ("1234", "Alice"), "b": ("5678", "Bob")}[pid]
    return state.handle_event(pid, {"event": "hello", "ot_id": ot, "trainer_name": name, "party": list(mons)})


def _fainted(key, species):
    return {**_mon(key, species), "hp": 0}


# ── MAJOR-2 (probe P1b): the hello's hp==0 faint goes through the trade hold and the evidence ──────

def test_a_hello_with_the_received_mon_fainted_is_held_until_the_swap(tmp_path):
    state, entry, _token = _one_sided(tmp_path)
    a_cmds = _hello(state, "a", _fainted(A_GETS, 0x15), _mon("ABCD:1234:99", 7))
    b_cmds = _cmds(state, "b")
    assert entry.status == LinkStatus.ALIVE, "held: the unswapped halves name the wrong holders"
    assert not _keys(a_cmds + b_cmds, "force_faint") and not _keys(a_cmds + b_cmds, "memorialize")
    assert state.pending_trade["held_events"]
    b_cmds = _tick(state, "b", _mon(B_GETS, 0x26))                  # B's evidence: traded
    assert state.pending_trade is None and entry.a.key == A_GETS
    b_cmds += _cmds(state, "b")
    a_cmds = _cmds(state, "a")
    assert _keys(b_cmds, "force_faint") == [B_GETS], "A's received mon's partner is B's received mon"
    assert not _keys(a_cmds, "force_faint")
    assert _keys(a_cmds, "memorialize") == [A_GETS] and _keys(b_cmds, "memorialize") == [B_GETS]
    assert entry.status != LinkStatus.ALIVE


def test_a_hello_that_settles_the_trade_routes_its_own_deaths_by_the_swapped_link(tmp_path):
    state, entry, _token = _one_sided(tmp_path)
    b_cmds = _hello(state, "b", _fainted(B_GETS, 0x26), _mon("0101:5678:99", 7))
    a_cmds = _cmds(state, "a")
    assert state.pending_trade is None and entry.b.key == B_GETS, "the hello was B's evidence"
    assert _keys(a_cmds, "force_faint") == [A_GETS], "A holds A_GETS, never B_GETS"
    assert not _keys(b_cmds, "force_faint")
    assert _keys(b_cmds, "memorialize") == [B_GETS]


# ── MAJOR-3 (probes P4, P7b, P7c): a one-sided commit is resolved to what each side holds ─────────

def _split_conflict(tmp_path):
    """A committed (holds a COPY of B's mon, its own is gone); B refused and kept its own."""
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    assert state.trade_problem()["phase"] == "conflict"
    assert state.pending_trade["verdict"] == {"a": "traded", "b": "none"}
    return state, entry, token


@pytest.mark.parametrize("action", ["rollback", "commit", "adopt"])
def test_any_resolve_of_a_one_sided_commit_points_each_half_at_what_that_side_holds(tmp_path, action):
    state, entry, token = _split_conflict(tmp_path)
    state.handle_event("b", {"event": "faint", "key": A_GETS})         # B's real mon faints
    assert entry.status == LinkStatus.ALIVE, "held while the conflict stands"
    held = state.trade_held()
    assert held == [{"player": "b", "event": "faint", "key": A_GETS}], "the board shows what waits"
    seen = []
    state.on_trade_outcome = seen.append
    assert state.resolve_trade(token, action) == (True, "")
    assert state.pending_trade is None and state.trade_problem() is None
    assert (entry.a.key, entry.b.key) == (A_GETS, A_GETS), "A holds the copy, B its own"
    assert entry.a.species == 0x15 and state._key_index[A_GETS] is entry
    assert B_GETS not in state._key_index and B_GETS not in state.party_keys["a"]
    a_cmds = _cmds(state, "a")
    assert _keys(a_cmds, "force_faint") == [A_GETS], "A's copy dies, never a key A does not hold"
    assert entry.status != LinkStatus.ALIVE
    assert [r["outcome"] for r in seen] == ["split"] and seen[0]["problem"] == f"resolved by admin: {action}"


def test_rollback_of_an_uncertain_side_splits_when_the_other_traded(tmp_path):
    state, entry, token = _one_sided(tmp_path)
    assert state.resolve_trade(token, "adopt")[0] is False, "adopt needs both outcomes known"
    assert state.resolve_trade(token, "rollback") == (True, "")
    assert (entry.a.key, entry.b.key) == (A_GETS, A_GETS)



# ── O-35: a PC release of a linked mon loses it; its partner dies like a faint ────────────────────

def _linked(tmp_path):
    state, entry, _token = _gen1_applying(tmp_path)
    state.pending_trade = None                                  # no trade in flight
    return state, entry


def test_releasing_a_linked_mon_kills_and_memorializes_its_partner(tmp_path):
    state, entry = _linked(tmp_path)
    a_cmds = state.handle_event("a", {"event": "release", "key": B_GETS})     # A's own mon (entry.a)
    b_cmds = _cmds(state, "b")
    assert entry.status == LinkStatus.DEAD and entry.cause == "release"
    assert _keys(b_cmds, "force_faint") == [A_GETS] and _keys(b_cmds, "memorialize") == [A_GETS]
    assert not _keys(a_cmds, "memorialize") and not _keys(a_cmds, "force_faint"), "A's mon no longer exists"
    assert B_GETS not in state.pending_memorials["a"] and B_GETS not in state.party_keys["a"]


def test_duplicate_release_queues_partner_kill_and_memorial_once(tmp_path):
    state, _entry = _linked(tmp_path)
    release = {"event": "release", "key": B_GETS}
    state.handle_event("a", release)
    state.handle_event("a", release)
    b_cmds = _cmds(state, "b")
    assert _keys(b_cmds, "force_faint") == [A_GETS]
    assert _keys(b_cmds, "memorialize") == [A_GETS]


def test_release_of_an_already_dead_link_changes_no_state_or_queue(tmp_path):
    state, entry = _linked(tmp_path)
    state.handle_event("a", {"event": "faint", "key": B_GETS})
    assert entry.status == LinkStatus.DEAD
    queued_before = {pid: list(cmds) for pid, cmds in state.queued_commands.items()}
    state.handle_event("a", {"event": "release", "key": B_GETS})
    queued_after = {pid: list(cmds) for pid, cmds in state.queued_commands.items()}
    assert entry.status == LinkStatus.DEAD
    assert queued_after == queued_before


def test_release_queues_partner_force_faint_before_memorialize(tmp_path):
    state, _entry = _linked(tmp_path)
    state.handle_event("a", {"event": "release", "key": B_GETS})
    b_queued = state.queued_commands["b"]
    force_index = next(i for i, cmd in enumerate(b_queued) if cmd.get("cmd") == "force_faint")
    memorialize_index = next(i for i, cmd in enumerate(b_queued) if cmd.get("cmd") == "memorialize")
    assert force_index < memorialize_index


def test_a_release_of_an_unlinked_or_dead_key_changes_nothing(tmp_path):
    state, entry = _linked(tmp_path)
    state.handle_event("a", {"event": "release", "key": "ABCD:1234:99"})
    assert entry.status == LinkStatus.ALIVE and not _keys(_cmds(state, "b"), "force_faint")
    state.handle_event("b", {"event": "release", "key": B_GETS})               # A's key, released by B?
    assert entry.status == LinkStatus.ALIVE, "only the releaser's own half counts"


def test_a_release_of_a_received_mon_waits_for_the_trade(tmp_path):
    state, entry, _token = _one_sided(tmp_path)
    state.handle_event("a", {"event": "release", "key": A_GETS})              # A releases B's old mon
    assert entry.status == LinkStatus.ALIVE and state.trade_held() == [
        {"player": "a", "event": "release", "key": A_GETS}]
    b_cmds = _tick(state, "b", _mon(B_GETS, 0x26)) + _cmds(state, "b")        # B's evidence: traded
    assert _keys(b_cmds, "force_faint") == [B_GETS] and entry.cause == "release"


# ── MINOR-4 (probe P2b): a whiteout's per-link kill of a trade key waits for the swap ─────────────

def test_a_whiteout_in_the_trade_window_kills_by_the_swapped_link(tmp_path):
    state, entry, _token = _one_sided(tmp_path)
    a_cmds = state.handle_event("a", {"event": "whiteout"})
    b_cmds = _cmds(state, "b")
    assert entry.status == LinkStatus.ALIVE and not _keys(a_cmds + b_cmds, "force_faint")
    assert not _keys(a_cmds + b_cmds, "memorialize")
    assert state.trade_held() == [{"player": "a", "event": "faint", "key": B_GETS}]
    b_cmds = _tick(state, "b", _mon(B_GETS, 0x26)) + _cmds(state, "b")       # B's evidence: traded
    a_cmds = _cmds(state, "a")
    assert _keys(b_cmds, "force_faint") == [B_GETS], "B holds B_GETS, A's received mon's partner"
    assert _keys(a_cmds, "memorialize") == [A_GETS] and not _keys(a_cmds, "force_faint")
    assert entry.status == LinkStatus.DEAD and entry.cause == "whiteout"


# ── MINOR-5 (probe P8): the O-24 repair runs while a rebuild or a trade owns party bookkeeping ────

def _dead_pair(state, a_key="ABCD:1234:77"):
    from server.state import LinkEntry, MonInfo
    dead = LinkEntry(area_id="route_9", a=MonInfo(key=a_key, species=0x77, level=9),
                     b=MonInfo(key="1234:5678:77", species=0x77, level=9), status=LinkStatus.DEAD)
    state.links.append(dead)
    state._index_entry(dead)
    return a_key


def test_a_dead_mon_alive_in_party_is_re_killed_during_a_rebuild(tmp_path):
    state, _entry = _linked(tmp_path)
    dead = _dead_pair(state)
    state.rebuild_pending["a"] = {"started_at": "", "queued_keys": ["ABCD:1234:99"],
                                  "queued_partner_keys": [], "restored_keys": set()}
    assert _keys(_tick(state, "a", _mon(dead, 0x77)), "force_faint") == [dead]


def test_a_dead_mon_alive_in_party_is_re_killed_during_an_applying_trade(tmp_path):
    state, _entry, _token = _gen1_applying(tmp_path)
    dead = _dead_pair(state)
    assert _keys(_tick(state, "a", _mon(B_GETS, 0x26), _mon(dead, 0x77)), "force_faint") == [dead]


# ── MINOR-6 (probe P3b): a restart loses the queue; the hello kills before it buries ──────────────

def test_after_a_restart_the_hello_queues_force_faint_before_memorialize(tmp_path):
    from server.adapters.gen1_rby import Gen1Adapter
    from server.state import SoulLinkState
    state, entry = _linked(tmp_path)
    _dead_pair(state)                                             # a second pair keeps the run alive
    state.links[-1].status = LinkStatus.ALIVE
    state.handle_event("a", {"event": "faint", "key": B_GETS})
    assert entry.status == LinkStatus.DEAD and state.queued_death_cmd("b", A_GETS) and not state.run_over
    back = SoulLinkState.load(data_dir=str(tmp_path), adapter=Gen1Adapter())   # B never polled
    cmds = [(c["cmd"], c.get("key")) for c in _hello(back, "b", _mon(A_GETS, 0x15))
            if c.get("key") == A_GETS]
    assert cmds[:2] == [("force_faint", A_GETS), ("memorialize", A_GETS)], cmds
    assert [c for c, _ in cmds].count("force_faint") == 1


# ── MINOR-8 (probe P6): a key_change in the trade window does not strand the original keys ────────

@pytest.mark.parametrize("report_first", [True, False])
def test_a_commit_after_a_mid_window_key_change_follows_the_migrated_key(tmp_path, report_first):
    state, entry, token = _gen1_applying(tmp_path)
    evolved = "1234:5678:16"                                   # A's received mon evolves (Gen 1/3 shape)
    state.bonus_keys["b"].add(A_GETS)                          # B had caught it as a shiny
    done_a = {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15}
    if report_first:
        state.handle_event("a", done_a)
    state.handle_event("a", {"event": "key_change", "old_key": A_GETS, "new_key": evolved,
                             "new_species": 0x16, "reason": "evolution"})
    if not report_first:
        state.handle_event("a", {**done_a, "new_key": evolved, "new_species": 0x16})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": B_GETS, "new_species": 0x26})
    assert state.pending_trade is None
    assert entry.a.key == evolved and state._key_index[evolved] is entry and A_GETS not in state._key_index
    assert evolved in state.party_keys["a"] and B_GETS not in state.party_keys["a"]
    assert A_GETS not in state.party_keys["b"], "no ghost of B's traded-away key"
    assert evolved in state.bonus_keys["a"] and A_GETS not in state.bonus_keys["b"]


# ── NIT-11 (probe P5): an after_reset declaration still counts once the trade is `uncertain` ──────

def test_an_after_reset_report_in_the_uncertain_phase_waits_for_the_hello(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.pending_trade["age"] = state.TRADE_WATCHDOG_EVENTS
    _cmds(state, "a")
    assert state.pending_trade["phase"] == "uncertain" and state.pending_trade["verdict"]["b"] == "await"
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True, "after_reset": True})
    _tick(state, "b", _mon("0101:5678:99", 7))                   # the soft-locked RAM: neither mon
    assert state.pending_trade and state.pending_trade["verdict"]["b"] == "await"
    _hello(state, "b", _mon(B_GETS, 0x26))                       # the reloaded save
    assert state.pending_trade is None and (entry.a.key, entry.b.key) == (A_GETS, B_GETS)


# ── OMP review of 779c73c2: resolve_trade hardening ──────────────────────────────────────────────

def _queued(state, pid, *names):
    return [c for c in state.queued_commands[pid] if c.get("cmd") in names]


def test_resolve_refuses_while_a_side_never_answered_its_apply(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})
    assert _queued(state, "a", "apply_trade"), "control: A has not picked up its apply yet"
    ok, why = state.resolve_trade(token, "rollback")
    assert not ok and "answer" in why and state.pending_trade is not None


def test_resolve_purges_an_undelivered_apply_for_the_trade(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})
    state.pending_trade["age"] = state.TRADE_WATCHDOG_EVENTS
    state.handle_event("b", {"event": "noop"})                  # A still silent: uncertain, a awaits
    assert state.pending_trade["verdict"] == {"a": "await", "b": "await"}
    assert _queued(state, "a", "apply_trade")
    assert state.resolve_trade(token, "rollback") == (True, "")
    assert not _queued(state, "a", "apply_trade", "apply_prepare"), "a stale apply would still commit"


def test_contradictory_evidence_is_never_filled_by_the_action(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})
    _tick(state, "b", _mon("0101:5678:99", 7))                  # B holds NEITHER
    assert state.pending_trade["phase"] == "conflict"
    for action in ("commit", "rollback", "adopt"):
        ok, why = state.resolve_trade(token, action)
        assert not ok and "NEITHER" in why, action
    ok, _ = state.resolve_trade(token, "commit", sides={"b": "bogus"})
    assert not ok
    assert state.resolve_trade(token, "commit", sides={"b": "traded"}) == (True, "")
    assert (entry.a.key, entry.b.key) == (A_GETS, B_GETS)


def test_a_split_copies_the_stats_to_an_evolved_copy_and_drops_the_gone_mon(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.mon_stats["b"][A_GETS], state.mon_stats["a"][B_GETS] = {"atk": 7}, {"atk": 9}
    evolved = "1234:5678:16"
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.pending_trade["new"]["a"] = (evolved, 0x16)            # A's copy evolved on arrival
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    assert state.resolve_trade(token, "adopt") == (True, "")
    assert entry.a.key == evolved and state.mon_stats["a"][evolved] == {"atk": 7}
    assert state.mon_stats["b"][A_GETS] == {"atk": 7}, "B still holds the original"
    assert B_GETS not in state.mon_stats["a"], "A's own mon is gone"


import asyncio  # noqa: E402


@pytest.mark.parametrize("body", [None, [], {"token": 5, "action": "commit"},
                                  {"token": "t1", "action": ["commit"]},
                                  {"token": "t1", "action": "commit", "sides": "a"}])
def test_the_resolve_endpoint_answers_400_to_a_malformed_body(tmp_path, body):
    from unittest.mock import AsyncMock
    from server.server import SLinkServer
    srv = SLinkServer(data_dir=str(tmp_path))
    resp = asyncio.run(srv.handle_debug_resolve_trade(AsyncMock(json=AsyncMock(return_value=body))))
    assert resp.status == 400


# ── a Lua reload loses the owed trade_done: the fresh hello's party decides that side ─────────────

def test_a_fresh_hello_from_a_silent_applying_side_is_its_evidence(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    assert state.pending_trade["verdict"]["b"] is None
    _hello(state, "b", _mon(B_GETS, 0x26))                      # reloaded client: no report, no watchdog
    assert state.pending_trade is None and (entry.a.key, entry.b.key) == (A_GETS, B_GETS)


def test_a_fresh_hello_showing_no_trade_rolls_back(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": B_GETS, "new_species": 0x26})
    _hello(state, "b", _mon(A_GETS, 0x15))
    assert state.pending_trade is None and state.trade_last["outcome"] == "rolled_back"


# ── OMP review of 3b5b5a5a: coverage of the held hello faint ─────────────────────────────────────

def test_a_hello_faint_is_held_in_the_watchdogs_uncertain_phase(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.pending_trade["age"] = state.TRADE_WATCHDOG_EVENTS
    _cmds(state, "a")                                            # the real watchdog transition
    assert state.pending_trade["phase"] == "uncertain"
    _hello(state, "a", _fainted(A_GETS, 0x15), _mon("ABCD:1234:99", 7))
    assert entry.status == LinkStatus.ALIVE and state.trade_held()
    b_cmds = _tick(state, "b", _mon(B_GETS, 0x26)) + _cmds(state, "b")
    assert _keys(b_cmds, "force_faint") == [B_GETS] and not _keys(_cmds(state, "a"), "force_faint")


def test_a_held_hello_faint_survives_a_restart_and_replays_once(tmp_path):
    from server.adapters.gen1_rby import Gen1Adapter
    from server.state import SoulLinkState
    state, _entry, _token = _one_sided(tmp_path)
    _hello(state, "a", _fainted(A_GETS, 0x15), _mon("ABCD:1234:99", 7))
    back = SoulLinkState.load(data_dir=str(tmp_path), adapter=Gen1Adapter())
    assert back.trade_held() == [{"player": "a", "event": "faint", "key": A_GETS}]
    b_cmds = _tick(back, "b", _mon(B_GETS, 0x26)) + _cmds(back, "b") + _cmds(back, "b")
    a_cmds = _cmds(back, "a")
    assert _keys(b_cmds, "force_faint") == [B_GETS], "exactly once, onto the mon B holds"
    assert A_GETS not in _keys(a_cmds + b_cmds, "force_faint")
    assert back.links[0].status == LinkStatus.DEAD


def test_a_hello_faint_in_a_conflict_replays_once_through_the_split(tmp_path):
    state, entry, token = _split_conflict(tmp_path)
    _hello(state, "a", _fainted(A_GETS, 0x15), _mon("ABCD:1234:99", 7))    # A's copy fainted
    assert entry.status == LinkStatus.ALIVE and state.trade_held()
    assert state.resolve_trade(token, "adopt") == (True, "")
    b_cmds, a_cmds = _cmds(state, "b"), _cmds(state, "a")
    assert _keys(b_cmds, "force_faint") == [A_GETS], "B's real mon, once"
    assert not _keys(a_cmds, "force_faint")
    assert _keys(a_cmds, "memorialize") == [A_GETS] and _keys(b_cmds, "memorialize") == [A_GETS]


def test_an_unrelated_hello_faint_propagates_while_the_trade_keys_waits(tmp_path):
    state, entry, _token = _one_sided(tmp_path)
    other = _dead_pair(state)
    state.links[-1].status = LinkStatus.ALIVE
    _hello(state, "a", _fainted(A_GETS, 0x15), _fainted(other, 0x77), _mon("ABCD:1234:99", 7))
    assert _keys(_cmds(state, "b"), "force_faint") == ["1234:5678:77"], "the other pair dies now"
    assert state.links[-1].status == LinkStatus.DEAD
    assert entry.status == LinkStatus.ALIVE and state.trade_held() == [
        {"player": "a", "event": "faint", "key": A_GETS}]
