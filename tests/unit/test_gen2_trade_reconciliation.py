"""Watchdog reconciliation receipts must prove ordered post-await saved-party evidence."""
import json
from copy import deepcopy
from datetime import datetime

import pytest

from tools.gen2_trade_reconciliation import verify_reconciliation

SIDES = ("a", "b")
OLD = {"a": "AAAA:1111:001", "b": "BBBB:2222:004"}
NEW = {"a": "BBBB:2222:005", "b": "AAAA:1111:001"}


def _pending(verdict, phase="uncertain"):
    return {"token": "t7", "phase": phase, "a_key": OLD["a"], "b_key": OLD["b"],
            "verdict": dict(verdict)}


def _record(verdict, outcome, at):
    return {"token": "t7", "outcome": outcome, "at": at, "a_key": OLD["a"],
            "b_key": OLD["b"], "a_new": NEW["a"] if verdict["a"] == "traded" else None,
            "b_new": NEW["b"] if verdict["b"] == "traded" else None,
            "verdict": dict(verdict), "problem": ""}


def _row(seq, side, message, before, after, last, *, watchdog=None, watchdog_last=None):
    midpoint = before if watchdog is None else watchdog

    def problem(value):
        result = deepcopy(value) if value and value["phase"] in ("uncertain", "conflict") else None
        if result:
            result.setdefault("problem", "")
        return result

    return {"seq": seq, "source": "server_dispatch", "evidence_class": "HARNESS_ONLY_OVERLAY",
            "run_id": "fixture", "scenario": "gen2_trade_reset_commit", "player": side,
            "message": {"player": side, **message}, "outcome": {
                "dispatch": "returned", "pending_trade_before": deepcopy(before),
                "pending_trade": deepcopy(after), "trade_problem": problem(after),
                "watchdog_observed": True, "pending_trade_after_watchdog": deepcopy(midpoint),
                "trade_problem_after_watchdog": problem(midpoint),
                "trade_last_after_watchdog": deepcopy(last if watchdog_last is None else watchdog_last),
                "trade_last": deepcopy(last)}}


def _committed():
    initial = _pending({"a": None, "b": None}, "applying")
    awaiting = _pending({"a": "await", "b": "await"})
    partial = _pending({"a": "traded", "b": "await"})
    uncertain = _record(awaiting["verdict"], "uncertain", 1800000000.25)
    final = _record({"a": "traded", "b": "traded"}, "committed", 1800000002.25)
    journal = [
        _row(1, "a", {"event": "tick", "party": [{"key": OLD["a"]}]}, initial, initial, None),
        _row(2, "b", {"event": "noop"}, initial, awaiting, uncertain, watchdog=awaiting),
        _row(3, "a", {"event": "tick", "party": [{"key": NEW["a"]}]}, awaiting, partial, uncertain),
        _row(4, "b", {"event": "hello", "party": [{"key": NEW["b"]}]}, partial, None, final,
             watchdog_last=uncertain),
    ]
    events = [{"type": f"trade_{rec['outcome']}", "key": "t7", "player": "",
               "ts": datetime.fromtimestamp(rec["at"]).isoformat(timespec="seconds")}
              for rec in (final, uncertain)]
    return {"token": "t7", "before_keys": dict(OLD), "after_keys": dict(NEW),
            "final_party_keys": {side: [NEW[side]] for side in SIDES},
            "independent_verdicts": {"a": "traded", "b": "traded"},
            "events": events, "status": {"trade_last": final, "trade_problem": None},
            "journal": journal}


def test_committed_receipt_requires_both_later_independently_matched_parties():
    evidence = _committed()
    original = deepcopy(evidence)
    result = verify_reconciliation(**evidence)
    assert result["outcome"] == "committed"
    assert result["evidence"] == {"a": {"kind": "party", "seq": 3},
                                  "b": {"kind": "party", "seq": 4}}
    assert evidence == original


def test_late_duplicate_trade_done_is_not_hidden_by_a_cleared_pending_trade():
    evidence = _committed()
    evidence["journal"].append(_row(
        5, "a", {"event": "trade_done", "token": "t7", "new_key": NEW["a"]},
        None, None, evidence["status"]["trade_last"],
    ))
    with pytest.raises(RuntimeError, match="trade_done"):
        verify_reconciliation(**evidence)


def _resolved(verdicts):
    evidence = _committed()
    raw = {side: f"{side}: holds BOTH offered and incoming (duplicated)"
           if verdicts[side] == "conflict" else verdicts[side] for side in SIDES}
    terminal = "rolled_back" if verdicts == {"a": "none", "b": "none"} else "conflict"
    final = _record(raw, terminal, 1800000002.25)
    if terminal == "conflict":
        final["problem"] = "; ".join(f"{side}: {raw[side]}" for side in SIDES)
    partial = _pending({"a": raw["a"], "b": "await"})
    after = None if terminal == "rolled_back" else {**_pending(raw, "conflict"), "problem": final["problem"]}
    evidence["independent_verdicts"] = verdicts
    evidence["after_keys"] = {side: NEW[side] if verdicts[side] == "traded" else (
        OLD[side] if verdicts[side] == "none" else None) for side in SIDES}
    evidence["final_party_keys"] = {side: [OLD[side], NEW[side]] if verdicts[side] == "conflict"
                                    else [evidence["after_keys"][side]] for side in SIDES}
    uncertain = evidence["journal"][1]["outcome"]["trade_last"]
    awaiting = evidence["journal"][1]["outcome"]["pending_trade"]
    evidence["journal"][2] = _row(3, "a", {"event": "tick", "party": [
        {"key": key} for key in evidence["final_party_keys"]["a"]]}, awaiting, partial, uncertain)
    evidence["journal"][3] = _row(4, "b", {"event": "hello", "party": [
        {"key": key} for key in evidence["final_party_keys"]["b"]]}, partial, after, final,
        watchdog_last=uncertain)
    evidence["events"][0]["type"] = f"trade_{terminal}"
    evidence["status"] = {"trade_last": final, "trade_problem": after}
    return evidence


def test_both_independently_unchanged_saves_require_rolled_back():
    result = verify_reconciliation(**_resolved({"a": "none", "b": "none"}))
    assert result["outcome"] == "rolled_back"


@pytest.mark.parametrize("verdicts", [{"a": "traded", "b": "none"},
                                     {"a": "none", "b": "conflict"}])
def test_conflict_never_passes_by_default_but_can_be_an_explicit_negative_control(verdicts):
    evidence = _resolved(verdicts)
    with pytest.raises(RuntimeError, match="not expected"):
        verify_reconciliation(**evidence)
    result = verify_reconciliation(**evidence, expected_outcomes=("conflict",))
    assert result["outcome"] == "conflict"


def test_other_side_may_have_reported_valid_trade_done_before_watchdog():
    evidence = _committed()
    initial = evidence["journal"][0]["outcome"]["pending_trade_before"]
    reported = _pending({"a": "traded", "b": None}, "applying")
    awaiting = _pending({"a": "traded", "b": "await"})
    uncertain = _record(awaiting["verdict"], "uncertain", 1800000000.25)
    evidence["journal"][0] = _row(1, "a", {"event": "trade_done", "token": "t7",
        "new_key": NEW["a"], "new_species": 5}, initial, reported, None)
    evidence["journal"][1] = _row(2, "b", {"event": "noop"}, reported, awaiting, uncertain, watchdog=awaiting)
    evidence["journal"][2] = _row(3, "a", {"event": "tick", "party": [{"key": NEW["a"]}]},
                                  awaiting, awaiting, uncertain)
    evidence["journal"][3]["outcome"]["trade_last_after_watchdog"] = deepcopy(uncertain)
    result = verify_reconciliation(**evidence)
    assert result["await_sequences"] == {"b": 2}
    assert result["evidence"]["a"] == {"kind": "trade_done", "seq": 1}


@pytest.mark.parametrize(("path", "value"), [
    (("journal", 2, "message", "party"), []),
    (("journal", 2, "message", "party"), [{"key": NEW["a"]}, {"key": NEW["a"]}]),
    (("journal", 2, "message", "party"), [{"key": OLD["a"]}]),
    (("journal", 2, "message", "party"), [{"key": NEW["a"]}, {"key": "extra"}]),
    (("journal", 2, "message", "event"), "noop"),
    (("journal", 2, "seq"), 2),
    (("journal", 2, "seq"), True),
    (("journal", 2, "source"), "client_tx"),
    (("journal", 2, "run_id"), "other-run"),
    (("journal", 2, "message", "player"), "b"),
    (("journal", 2, "outcome", "dispatch"), "raised"),
    (("journal", 1, "outcome", "watchdog_observed"), False),
    (("journal", 1, "outcome", "watchdog_observed"), "true"),
    (("journal", 1, "outcome", "watchdog_observed"), 1),
    (("journal", 1, "outcome", "pending_trade_after_watchdog"), None),
    (("journal", 1, "outcome", "trade_last_after_watchdog"), None),
    (("journal", 2, "outcome", "pending_trade_before", "a_key"), "wrong-old"),
    (("journal", 2, "outcome", "pending_trade_before", "token"), "t8"),
    (("journal", 2, "outcome", "pending_trade_before", "verdict", "a"), None),
    (("status", "trade_last", "token"), "t8"),
    (("status", "trade_last", "a_key"), "wrong-old"),
    (("status", "trade_last", "a_new"), "wrong-new"),
    (("status", "trade_last", "outcome"), "uncertain"),
    (("status", "trade_last", "at"), float("nan")),
    (("status", "trade_problem"), {"phase": "uncertain"}),
    (("independent_verdicts", "a"), "await"),
    (("independent_verdicts", "a"), "none"),
    (("final_party_keys", "a"), []),
    (("final_party_keys", "a"), [NEW["a"], NEW["a"]]),
    (("events", 0, "key"), "t8"),
    (("events", 0, "ts"), "bad timestamp"),
    (("events", 0, "type"), "trade_rolled_back"),
])
def test_missing_or_contradictory_evidence_refuses(path, value):
    evidence = _committed()
    target = evidence
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(RuntimeError):
        verify_reconciliation(**evidence)


def test_scene_time_snapshot_cannot_replace_later_party_evidence():
    evidence = _committed()
    evidence["journal"][0]["message"]["party"] = [{"key": NEW["a"]}]
    evidence["journal"].pop(2)
    with pytest.raises(RuntimeError):
        verify_reconciliation(**evidence)


@pytest.mark.parametrize("change", ["reverse", "duplicate", "missing"])
def test_events_require_exactly_one_uncertain_then_one_terminal(change):
    evidence = _committed()
    if change == "reverse":
        evidence["events"].reverse()
    elif change == "duplicate":
        evidence["events"].insert(0, deepcopy(evidence["events"][0]))
    else:
        evidence["events"].pop()
    with pytest.raises(RuntimeError):
        verify_reconciliation(**evidence)


def test_uncertain_record_must_describe_the_observed_await_transition():
    evidence = _committed()
    for row in evidence["journal"][1:3]:
        rec = row["outcome"]["trade_last"]
        rec.update(verdict={"a": "traded", "b": "traded"}, a_new=NEW["a"], b_new=NEW["b"])
    with pytest.raises(RuntimeError):
        verify_reconciliation(**evidence)


def test_terminal_dispatch_must_match_the_final_problem_state():
    evidence = _committed()
    conflict = {**_pending({"a": "traded", "b": "traded"}, "conflict"), "problem": "conflict"}
    evidence["journal"][-1]["outcome"].update(pending_trade=conflict, trade_problem=deepcopy(conflict))
    with pytest.raises(RuntimeError):
        verify_reconciliation(**evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["tick", "hello", "safe"])
@pytest.mark.parametrize("qualification", ["watchdog", "fast_report"])
async def test_real_dispatch_can_enter_await_and_settle_in_the_same_event(tmp_path, event, qualification):
    from server import server as server_module
    from server.state import LinkEntry, LinkStatus, MonInfo
    from tests.unit.test_gen2_trade_lane import hello, manifest
    from tests.unit.test_mixed_foundations import _session
    from tools.gen2_trade_lane import install_server_gate

    doc = manifest()
    audit = tmp_path / "wire.jsonl"
    restore = install_server_gate(server_module, doc, audit_path=audit)
    srv = server_module.SLinkServer(data_dir=str(tmp_path), run_id=doc["run_id"])
    send_a, close_a = await _session(srv)
    send_b, close_b = await _session(srv)
    a_key, b_key = "1234:30B8:10", "5678:7B0B:13"
    try:
        await send_a(hello(doc, "a"))
        await send_b(hello(doc, "b"))
        entry = LinkEntry(area_id="route_29", a=MonInfo(key=a_key, species=16, level=5),
                          b=MonInfo(key=b_key, species=19, level=5), status=LinkStatus.ALIVE)
        srv.state.links.append(entry)
        srv.state._index_entry(entry)
        for side, half in (("a", entry.a), ("b", entry.b)):
            srv.state.party_keys[side].add(half.key)
            srv.state.partner_blobs[side] = [{"slot": 0, "key": half.key, "blob": bytes(70),
                                              "species_id": half.species, "level": half.level}]
        await send_a({"event": "trade_offer", "player": "a", "slot": 0})
        token = srv.state.pending_trade["token"]
        await send_b({"event": "menu_result", "player": "b", "token": token, "choice": 1})
        await send_a({"event": "trade_done", "player": "a", "token": token,
                      "new_key": b_key, "new_species": 19})
        if qualification == "watchdog":
            srv.state.pending_trade["age"] = srv.state.TRADE_WATCHDOG_EVENTS
        else:
            await send_b({"event": "trade_done", "player": "b", "token": token, "uncertain": True})
        message = hello(doc, "b") if event == "hello" else {"event": event, "player": "b"}
        message["party"] = [{"key": a_key, "species_id": 16, "hp": 10, "maxHP": 10,
                             "slot": 0, "level": 5}]
        await send_b(message)
        assert srv.state.pending_trade is None
        assert srv.state.trade_last["outcome"] == "committed"
        journal = [json.loads(line) for line in audit.read_text().splitlines()]
        evidence = {
            "token": token, "before_keys": {"a": a_key, "b": b_key}, "after_keys": {"a": b_key, "b": a_key},
            "final_party_keys": {"a": [b_key], "b": [a_key]}, "independent_verdicts": {"a": "traded", "b": "traded"},
            "events": list(srv._recent_events), "status": srv._build_status_dict(), "journal": journal,
        }
        if qualification == "fast_report":
            assert not any(item["type"] == "trade_uncertain" for item in srv._recent_events)
            with pytest.raises(RuntimeError, match="outcomes"):
                verify_reconciliation(**evidence)
        else:
            result = verify_reconciliation(**evidence)
            assert result["outcome"] == "committed"
            assert result["await_sequences"]["b"] == result["evidence"]["b"]["seq"]
            for mutation in ("missing", "unobserved", "end_state"):
                changed = deepcopy(evidence)
                outcome = changed["journal"][-1]["outcome"]
                if mutation == "missing":
                    del outcome["pending_trade_after_watchdog"]
                elif mutation == "unobserved":
                    outcome["watchdog_observed"] = False
                else:
                    outcome["pending_trade_after_watchdog"] = outcome["pending_trade"]
                with pytest.raises(RuntimeError):
                    verify_reconciliation(**changed)
    finally:
        await close_a()
        await close_b()
        restore()
