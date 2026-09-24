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
