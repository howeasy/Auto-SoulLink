"""An UNCERTAIN native trade is settled from party evidence, never by guessing.

A side is uncertain when it declares so (trade_done uncertain / no key) or when the
'applying' watchdog fires before it reported. Its NEXT party snapshot decides:
outgoing gone + incoming (or an evolved descendant) present -> traded; outgoing
present + incoming absent -> not traded; anything else -> a sticky conflict that
is surfaced (state.trade_problem()) and never auto-resolved.
"""

from server.adapters.gen1_rby import Gen1Adapter
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_state import _offer_and_pick, _with_trade_blobs, has_cmd, make_state_with_link


def _applying(tmp_path, monkeypatch):
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = _with_trade_blobs(make_state_with_link())
    state.links[0].a.species, state.links[0].b.species = 1, 4
    token = _offer_and_pick(state, slot=0)
    state.handle_event("b", {"event": "menu_result", "token": token, "choice": 1})
    assert state.pending_trade["phase"] == "applying"
    return state, token


def _mon(key, species):
    return {"key": key, "species_id": species, "hp": 10, "maxHP": 10}


def _tick(state, pid, *mons):
    return state.handle_event(pid, {"event": "tick", "party": list(mons)})


def _fire_watchdog(state):
    for _ in range(state.TRADE_WATCHDOG_EVENTS + 1):
        state.handle_event("a", {"event": "noop"})


def test_watchdog_never_fabricates_and_a_silent_side_stays_uncertain(tmp_path, monkeypatch):
    state, token = _applying(tmp_path, monkeypatch)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": "B:2", "new_species": 4})
    _fire_watchdog(state)
    e = state.links[0]
    assert e.a.key == "A:1" and e.b.key == "B:2", "the watchdog must not fabricate B's outcome"
    assert state.pending_trade["phase"] == "uncertain"
    problem = state.trade_problem()
    assert problem and problem["phase"] == "uncertain" and problem["verdict"]["b"] == "await"
    # B never reports: still uncertain, still surfaced, however long it takes.
    _fire_watchdog(state)
    assert state.pending_trade["phase"] == "uncertain" and state.trade_problem()
    # B's next snapshot is the evidence: the swap happened.
    _tick(state, "b", _mon("A:1", 1), _mon("X:9", 7))
    assert state.pending_trade is None and state.trade_problem() is None
    assert e.a.key == "B:2" and e.b.key == "A:1"
    assert "B:2" in state.party_keys["a"] and "A:1" in state.party_keys["b"]


def test_declared_uncertain_side_is_settled_by_its_next_snapshot(tmp_path, monkeypatch):
    state, token = _applying(tmp_path, monkeypatch)
    _tick(state, "b", _mon("B:2", 4))           # mid-scene snapshot: NOT evidence yet
    assert state.pending_trade["verdict"]["b"] is None
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": "B:2", "new_species": 4})
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})
    assert state.pending_trade["verdict"]["b"] == "await"
    _tick(state, "b", _mon("A:1", 1))
    assert state.pending_trade is None
    assert state.links[0].b.key == "A:1"


def test_empty_key_report_is_uncertain_not_a_fallback_key(tmp_path, monkeypatch):
    state, token = _applying(tmp_path, monkeypatch)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": "B:2", "new_species": 4})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": "", "new_species": 0})
    assert state.pending_trade["verdict"]["b"] == "await"


def test_both_sides_show_no_trade_rolls_back(tmp_path, monkeypatch):
    state, token = _applying(tmp_path, monkeypatch)
    _fire_watchdog(state)
    _tick(state, "a", _mon("A:1", 1))
    assert state.pending_trade is not None, "one side is not enough"
    cmds = _tick(state, "b", _mon("B:2", 4))
    assert state.pending_trade is None and state.trade_problem() is None
    e = state.links[0]
    assert e.a.key == "A:1" and e.b.key == "B:2" and e.a.species == 1
    assert any("did not go through" in c.get("text", "") for c in cmds if c.get("cmd") == "msgbox")


def test_refused_reports_on_both_sides_roll_back_without_swapping(tmp_path, monkeypatch):
    state, token = _applying(tmp_path, monkeypatch)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": "A:1", "new_species": 0})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": "B:2", "new_species": 0})
    assert state.pending_trade is None
    e = state.links[0]
    assert (e.a.key, e.a.species, e.b.key, e.b.species) == ("A:1", 1, "B:2", 4)


def test_duplicate_is_a_sticky_surfaced_conflict(tmp_path, monkeypatch):
    state, token = _applying(tmp_path, monkeypatch)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": "B:2", "new_species": 4})
    _fire_watchdog(state)
    cmds = _tick(state, "b", _mon("B:2", 4), _mon("A:1", 1))      # kept its mon AND got A's
    assert state.pending_trade["phase"] == "conflict"
    problem = state.trade_problem()
    assert problem["phase"] == "conflict" and "b" in problem["problem"]
    assert has_cmd(cmds, "msgbox")
    e = state.links[0]
    assert e.a.key == "A:1" and e.b.key == "B:2", "a conflict never mutates the link"
    # Sticky: later evidence does not auto-resolve it.
    _tick(state, "b", _mon("A:1", 1))
    _fire_watchdog(state)
    assert state.pending_trade["phase"] == "conflict"


def test_neither_half_present_is_a_conflict(tmp_path, monkeypatch):
    state, token = _applying(tmp_path, monkeypatch)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": "B:2", "new_species": 4})
    _fire_watchdog(state)
    _tick(state, "b", _mon("X:9", 7))
    assert state.pending_trade["phase"] == "conflict"


def test_one_side_refused_other_traded_is_a_conflict_not_a_commit(tmp_path, monkeypatch):
    state, token = _applying(tmp_path, monkeypatch)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": "B:2", "new_species": 4})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": "B:2", "new_species": 0})
    assert state.pending_trade["phase"] == "conflict"
    assert state.links[0].a.key == "A:1"


def test_empty_party_is_no_evidence(tmp_path, monkeypatch):
    state, token = _applying(tmp_path, monkeypatch)
    _fire_watchdog(state)
    _tick(state, "b")                                             # unreadable party -> []
    assert state.pending_trade["verdict"]["b"] == "await"


def test_uncertain_trade_freezes_reconcile_for_its_keys(tmp_path, monkeypatch):
    """While unresolved, A holding B's old key must not read as ghost-boxed (spurious Unbox to B)."""
    state, token = _applying(tmp_path, monkeypatch)
    _fire_watchdog(state)
    state.party_keys["b"].discard("B:2")
    _tick(state, "a", _mon("B:2", 4))       # settles A's side only; B still awaits evidence
    assert state.pending_trade["phase"] == "uncertain"
    assert not has_cmd(state.queued_commands["b"], "party_mon")


def _gen1_confirming(tmp_path):
    """Gen 1: A offers a Kadabra (internal 0x26) that trade-evolves into Alakazam (0x95) on B.
    Returns (state, entry, token, A's commands from the offer)."""
    state = SoulLinkState(data_dir=str(tmp_path), adapter=Gen1Adapter())
    a_key, b_key = "ABCD:1234:26", "1234:5678:15"
    entry = LinkEntry(area_id="route_1", a=MonInfo(key=a_key, species=0x26, level=30),
                      b=MonInfo(key=b_key, species=0x15, level=30), status=LinkStatus.ALIVE)
    state.links.append(entry)
    state._index_entry(entry)
    state.party_keys["a"].add(a_key)
    state.party_keys["b"].add(b_key)
    state.party_size = {"a": 2, "b": 2}
    state.pokeballs_obtained = {"a": True, "b": True}
    state.partner_blobs["a"] = [{"slot": 2, "key": a_key, "blob": bytes(66), "species_id": 0x26}]
    state.partner_blobs["b"] = [{"slot": 4, "key": b_key, "blob": bytes(66), "species_id": 0x15}]
    state.player_identity["a"] = {"trainer_name": "Alice", "ot_id": "1234"}
    state.player_identity["b"] = {"trainer_name": "Bob", "ot_id": "5678"}
    a_cmds = state.handle_event("a", {"event": "trade_offer", "slot": 2})
    return state, entry, state.pending_trade["token"], a_cmds


def _gen1_applying(tmp_path):
    state, entry, token, _ = _gen1_confirming(tmp_path)
    state.handle_event("b", {"event": "menu_result", "token": token, "choice": 1})
    assert state.pending_trade["phase"] == "applying"
    return state, entry, token


def test_gen1_trade_evolution_is_recognised_from_the_snapshot(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token,
                             "new_key": "1234:5678:15", "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})
    # B's party: the Kadabra evolved into Alakazam (new key), B's own mon is gone.
    _tick(state, "b", _mon("ABCD:1234:95", 0x95), _mon("0101:5678:99", 153))
    assert state.pending_trade is None
    assert entry.b.key == "ABCD:1234:95" and entry.b.species == 0x95
    assert entry.a.key == "1234:5678:15"
    assert state._key_index["ABCD:1234:95"] is entry and "ABCD:1234:26" not in state._key_index
    assert "ABCD:1234:95" in state.party_keys["b"]


def test_gen1_unrelated_new_mon_is_not_a_descendant(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token,
                             "new_key": "1234:5678:15", "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})
    # same OT, different family (Spearow 0x05): not the traded Kadabra
    _tick(state, "b", _mon("ABCD:1234:05", 0x05))
    assert state.pending_trade["phase"] == "conflict"


def test_status_payload_surfaces_the_trade_problem(tmp_path):
    from server.server import SLinkServer
    srv = SLinkServer(data_dir=str(tmp_path))
    assert srv._build_status_dict()["trade_problem"] is None
    srv.state.pending_trade = {"phase": "conflict", "token": "t1", "a_key": "A:1", "b_key": "B:2",
                               "verdict": {"a": "traded", "b": "b: holds NEITHER"}, "problem": "x"}
    assert srv._build_status_dict()["trade_problem"]["phase"] == "conflict"


def test_every_outcome_is_recorded_with_its_token(tmp_path, monkeypatch):
    """trade_last + on_trade_outcome: the durable, token-bound record an oracle binds to."""
    seen = []
    state, token = _applying(tmp_path, monkeypatch)
    state.on_trade_outcome = seen.append
    _fire_watchdog(state)
    assert state.trade_last["token"] == token and state.trade_last["outcome"] == "uncertain"
    _tick(state, "a", _mon("A:1", 1))
    _tick(state, "b", _mon("B:2", 4))
    assert [r["outcome"] for r in seen] == ["uncertain", "rolled_back"]
    last = state.trade_last
    assert last["token"] == token and last["verdict"] == {"a": "none", "b": "none"}
    assert last["a_key"] == "A:1" and last["b_key"] == "B:2" and last["at"]
    assert last["a_new"] is None and last["b_new"] is None

    state2, token2 = _applying(tmp_path, monkeypatch)
    state2.handle_event("a", {"event": "trade_done", "token": token2, "new_key": "B:2", "new_species": 4})
    state2.handle_event("b", {"event": "trade_done", "token": token2, "new_key": "A:1", "new_species": 1})
    assert state2.trade_last["outcome"] == "committed" and state2.trade_last["b_new"] == "A:1"

    state3, token3 = _applying(tmp_path, monkeypatch)
    state3.handle_event("a", {"event": "trade_done", "token": token3, "new_key": "B:2", "new_species": 4})
    state3.handle_event("b", {"event": "trade_done", "token": token3, "new_key": "B:2", "new_species": 0})
    assert state3.trade_last["outcome"] == "conflict" and state3.trade_last["problem"]


def test_server_journals_trade_outcomes_and_status_carries_trade_last(tmp_path):
    from server.server import SLinkServer
    srv = SLinkServer(data_dir=str(tmp_path))
    assert srv._build_status_dict()["trade_last"] is None
    srv.state._record_trade({"token": "t7", "a_key": "A:1", "b_key": "B:2",
                             "verdict": {"a": "traded", "b": "traded"},
                             "new": {"a": ("B:2", 4), "b": ("A:1", 1)}}, "committed")
    assert srv._build_status_dict()["trade_last"]["outcome"] == "committed"
    ev = srv._recent_events[0]
    assert ev["type"] == "trade_committed" and ev["key"] == "t7"


def test_a_declared_uncertain_side_is_journaled_once_like_the_watchdog(tmp_path, monkeypatch):
    """trade_done uncertain (a reset after the native commit entry, a DONE result 2) journals the
    same `uncertain` outcome the watchdog does, at the declaration, not ~17 minutes later."""
    seen = []
    state, token = _applying(tmp_path, monkeypatch)
    state.on_trade_outcome = seen.append
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})
    assert [r["outcome"] for r in seen] == ["uncertain"]
    assert seen[0]["token"] == token and seen[0]["verdict"] == {"a": None, "b": "await"}
    state.handle_event("b", {"event": "trade_done", "token": token, "uncertain": True})   # a replay
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": "B:2", "new_species": 4})
    _fire_watchdog(state)                        # nothing new to await: no second uncertain record
    assert [r["outcome"] for r in seen] == ["uncertain"]
    _tick(state, "b", _mon("A:1", 1))
    assert [r["outcome"] for r in seen] == ["uncertain", "committed"]


def test_the_initiator_withdrawing_cancels_the_offer_before_a_late_accept(tmp_path):
    """Trade-driver finding: A's cartridge timed out / withdrew its offer, THEN B answered YES.
    The server used to send apply_trade to both and B committed alone. A's withdrawal (menu_result
    choice 0 under the token its trade_offer_ack carried) cancels the offer; B's late YES is refused;
    both see the did-not-go-through path and nothing is applied."""
    state, entry, token, offer_cmds = _gen1_confirming(tmp_path)
    a_cmds = state.handle_event("a", {"event": "menu_result", "token": token, "choice": 0, "withdraw": True})
    assert state.pending_trade is None
    b_cmds = state.handle_event("b", {"event": "menu_result", "token": token, "choice": 1})
    assert state.pending_trade is None
    a_cmds += state.handle_event("a", {"event": "noop"})
    for cmds in (a_cmds, b_cmds):
        assert not has_cmd(cmds, "apply_trade")
        assert any("did not go through" in c.get("text", "") for c in cmds if c.get("cmd") == "msgbox")
    assert (entry.a.key, entry.b.key) == ("ABCD:1234:26", "1234:5678:15")
    assert state.trade_last is None, "nothing was applied, so there is no outcome to record"
    # the client learns the token to withdraw with from its offer's ack
    acks = [c for c in offer_cmds if c.get("cmd") == "trade_offer_ack"]
    assert acks == [{"cmd": "trade_offer_ack", "ok": True, "token": token}]


def test_only_the_initiator_can_withdraw_and_only_with_the_offer_token(tmp_path):
    state, _entry, token, _ = _gen1_confirming(tmp_path)
    state.handle_event("a", {"event": "menu_result", "token": "t999", "choice": 0, "withdraw": True})
    assert state.pending_trade["phase"] == "confirming"
    state.handle_event("a", {"event": "menu_result", "token": token, "choice": 0})
    assert state.pending_trade["phase"] == "confirming", "m3: a bare choice 0 (a Gen 3 menu replay) is not a withdrawal"
    state.handle_event("a", {"event": "menu_result", "token": token, "choice": 1})
    assert state.pending_trade["phase"] == "confirming", "the initiator cannot accept its own offer"
    state.handle_event("b", {"event": "menu_result", "token": token, "choice": 1})
    assert state.pending_trade["phase"] == "applying"
    state.handle_event("a", {"event": "menu_result", "token": token, "choice": 0, "withdraw": True})
    assert state.pending_trade["phase"] == "applying", "apply_trade went out: the trade stays open"
    assert state.pending_trade["verdict"]["a"] == "none", "m7: a withdrawn side certainly did not trade"
