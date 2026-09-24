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
