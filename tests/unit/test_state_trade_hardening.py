"""TRADE-HARDEN-2: the server trade state machine fixes from review e9d5e136
(docs/gen2/reviews/REVIEW_TRADE_SERVER_2026-09-24.md). One section per review item."""

from server.adapters.gen1_rby import Gen1Adapter
from server.state import SoulLinkState
from tests.unit.test_state_trade_uncertain import _gen1_applying, _gen1_confirming, _mon, _tick

A_GETS, B_GETS = "1234:5678:15", "ABCD:1234:26"     # _gen1_applying: A gives ABCD:1234:26, B gives 1234:5678:15


def _reload(tmp_path):
    return SoulLinkState.load(data_dir=str(tmp_path), adapter=Gen1Adapter())


# ── BLOCKER-1: a restart mid-trade restores it as uncertain; party evidence settles it ─────────────

def test_a_restart_while_applying_restores_the_trade_as_uncertain_and_evidence_settles_it(tmp_path):
    state, _entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    back = _reload(tmp_path)
    pt = back.pending_trade
    assert pt and pt["token"] == token and pt["phase"] == "uncertain"
    assert back.trade_problem()["verdict"] == {"a": "traded", "b": "await"}, "A's report survived; B awaits"
    seen = []
    back.on_trade_outcome = seen.append              # the server wires the journal after load
    assert [r["outcome"] for r in seen] == ["uncertain"] and seen[0]["token"] == token
    back.handle_event("b", {"event": "trade_done", "token": token, "new_key": B_GETS, "new_species": 0x26})
    _tick(back, "a", _mon(A_GETS, 0x15))
    _tick(back, "b", _mon(B_GETS, 0x26))
    assert back.pending_trade is None
    entry = back.links[0]
    assert (entry.a.key, entry.b.key) == (A_GETS, B_GETS), "the link follows the mons, not the restart"
    assert back._key_index[A_GETS] is entry and back._key_index[B_GETS] is entry
    assert [r["outcome"] for r in seen] == ["uncertain", "committed"]
    assert _reload(tmp_path).pending_trade is None, "a settled trade is not restored again"


def test_a_restart_before_apply_drops_the_offer_but_never_reuses_a_token(tmp_path):
    state, _entry, token, _ = _gen1_confirming(tmp_path)
    state._save()
    back = _reload(tmp_path)
    assert back.pending_trade is None, "nothing was applied: an unanswered offer may be dropped"
    back._handle_trade_request("a", {})
    assert back.pending_trade["token"] != token, "tokens do not restart at t1"


def test_a_rolled_back_or_conflicted_trade_is_persisted_as_such(tmp_path):
    state, _entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": "1234:5678:15", "new_species": 0})
    assert state.pending_trade["phase"] == "conflict"
    back = _reload(tmp_path)
    assert back.pending_trade["phase"] == "conflict" and back.trade_problem()["problem"]


# ── MAJOR-2: faint/box events naming a trade key wait for the swap, then go to the real holder ─────

def _cmds(state, pid):
    return state.handle_event(pid, {"event": "noop"})


def _keys(cmds, name):
    return [c.get("key") for c in cmds if c.get("cmd") == name]


def test_a_received_mon_fainting_in_the_one_sided_window_kills_the_real_partner_after_the_swap(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})
    a_cmds = state.handle_event("a", {"event": "faint", "key": A_GETS})      # A holds B's old mon now
    b_cmds = _cmds(state, "b")
    assert not _keys(a_cmds + b_cmds, "force_faint") and not _keys(a_cmds + b_cmds, "memorialize"), \
        "held: the link is not swapped yet, so B:2's half would be the wrong target"
    assert state.pending_trade["held_events"]
    b_cmds = _tick(state, "b", _mon(B_GETS, 0x26))                           # B's evidence: traded
    assert state.pending_trade is None and entry.a.key == A_GETS
    b_cmds += _cmds(state, "b")
    a_cmds = _cmds(state, "a")
    assert B_GETS in _keys(b_cmds, "force_faint"), "the partner of A's received mon is B's received mon"
    assert A_GETS not in _keys(b_cmds, "force_faint") and B_GETS not in _keys(a_cmds, "force_faint")
    assert entry.status.value != "alive"


def test_an_evolved_received_mon_fainting_before_its_report_is_not_lost(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    evolved = "1234:5678:16"                                                 # unindexed, the partner's OT
    state.handle_event("a", {"event": "faint", "key": evolved})
    assert state.pending_trade["held_events"], "an unindexed key with the partner's OT is the trade's"
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": evolved, "new_species": 0x16})
    b_cmds = state.handle_event("b", {"event": "trade_done", "token": token, "new_key": B_GETS, "new_species": 0x26})
    assert state.pending_trade is None and entry.a.key == evolved
    assert entry.status.value != "alive", "the faint replayed into the swapped link"
    assert B_GETS in _keys(b_cmds, "force_faint")


def test_a_deposit_of_a_received_mon_boxes_the_real_partner_after_the_swap(tmp_path):
    state, _entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("a", {"event": "party_to_box", "key": A_GETS})
    assert A_GETS not in _keys(_cmds(state, "b"), "box_mon")
    b_cmds = state.handle_event("b", {"event": "trade_done", "token": token, "new_key": B_GETS, "new_species": 0x26})
    boxed = _keys(b_cmds, "box_mon")
    assert boxed == [B_GETS]


def test_a_rolled_back_trade_replays_the_held_faint_against_the_unswapped_link(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "faint", "key": B_GETS})               # A's own offered mon
    assert state.pending_trade["held_events"]
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": B_GETS, "new_species": 0})
    b_cmds = state.handle_event("b", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0})
    assert state.pending_trade is None and entry.a.key == B_GETS
    assert A_GETS in _keys(b_cmds, "force_faint")
    assert entry.status.value != "alive"


def test_an_unrelated_faint_is_not_held(tmp_path):
    state, _entry, _token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "faint", "key": "ABCD:1234:99"})       # A's own OT: not the trade's
    assert not state.pending_trade.get("held_events")
