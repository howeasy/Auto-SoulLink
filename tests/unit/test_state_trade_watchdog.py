"""Watchdog abandonment must notify both trade participants, without swapping."""

from tests.unit.test_state import (
    _offer_and_pick,
    _with_trade_blobs,
    make_state_with_link,
)


def test_confirming_watchdog_notifies_both_sides_once(tmp_path, monkeypatch):
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = _with_trade_blobs(make_state_with_link())
    monkeypatch.setattr(state, "TRADE_WATCHDOG_EVENTS", 4)
    token = _offer_and_pick(state, slot=0)
    assert state.pending_trade["phase"] == "confirming"

    # Deliver B's confirmation menu; neither side answers it. This is event 1.
    prompt = state.handle_event("b", {"event": "tick"})
    assert any(c.get("cmd") == "show_menu" for c in prompt)
    # At the exact event budget the offer remains live, with no cancellation.
    for _ in range(state.TRADE_WATCHDOG_EVENTS - 1):
        cmds = state.handle_event("b", {"event": "tick"})
        assert not any(c.get("cmd") == "msgbox" for c in cmds)
    assert state.pending_trade is not None

    # B triggers abandonment; A is silent until its next event (e.g. reconnect).
    received_b = state.handle_event("b", {"event": "tick"})
    assert state.pending_trade is None
    received_a = state.handle_event("a", {"event": "tick"})
    for received in (received_a, received_b):
        notices = [c for c in received if c.get("cmd") == "msgbox"]
        assert len(notices) == 1, "each participant must receive one cancellation notice"
        assert not any(c.get("cmd") == "apply_trade" for c in received)

    assert state.links[0].a.key == "A:1"
    assert state.links[0].b.key == "B:2"
    assert "A:1" in state.party_keys["a"]
    assert "B:2" in state.party_keys["b"]

    # A late acceptance cannot execute an expired offer or repeat the notice.
    late = state.handle_event("b", {"event": "menu_result", "token": token, "choice": 1})
    assert not any(c.get("cmd") in ("msgbox", "apply_trade") for c in late)
    for pid in ("a", "b"):
        cmds = state.handle_event(pid, {"event": "tick"})
        assert not any(c.get("cmd") == "msgbox" for c in cmds)

    # Releasing the expired offer must leave the next trade usable.
    new_token = _offer_and_pick(state, slot=0)
    assert new_token != token and state.pending_trade["phase"] == "confirming"
