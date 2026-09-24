"""Check token-bound reconciliation against caller-supplied independent save evidence.

The caller decodes both final saves and projects any trade evolution independently.
This module never derives a save verdict from server state. ``events`` is the raw,
newest-first events.json list; ``journal`` is ascending server_dispatch JSONL rows.
Journal sequence numbers and an observed post-watchdog midpoint prove ordering:
the journal has no per-dispatch timestamp. Qualification is watchdog-only; a fast
``trade_done uncertain:true`` path without a native ``trade_uncertain`` outcome
remains unqualified. No missing server event or intermediate state is invented.
Source contract: server/state.py at 1ac09296 + 9a436c95.
"""
from __future__ import annotations

import math
from datetime import datetime
from functools import wraps

SIDES = ("a", "b")
TERMINAL = {"committed", "rolled_back", "conflict"}
CRITICAL = {"applying", "uncertain", "conflict"}
PENDING_FIELDS = {"token", "phase", "a_key", "b_key", "verdict", "problem"}
RECORD_FIELDS = {"token", "outcome", "at", "a_key", "b_key", "a_new", "b_new", "verdict", "problem"}


def _need(condition, reason):
    if not condition:
        raise RuntimeError(f"reconciliation: {reason}")


def _checked(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (KeyError, TypeError, ValueError, IndexError, OverflowError, OSError) as exc:
            raise RuntimeError(f"reconciliation: malformed evidence: {exc}") from exc
    return checked


def _pair(value, label):
    _need(isinstance(value, dict) and set(value) == set(SIDES), f"invalid {label} sides")
    return value


def _key(value):
    return isinstance(value, str) and bool(value.strip())


def _verdict(value, side):
    if value in (None, "await", "traded", "none"):
        return value
    _need(isinstance(value, str) and value.startswith(f"{side}: ") and len(value) > 3,
          f"invalid {side} server verdict")
    return "conflict"


def _time(value):
    _need(type(value) in (int, float) and math.isfinite(value) and value > 0,
          "invalid trade timestamp")
    return value


def _pending(value, token, before_keys):
    if value is None:
        return None
    _need(isinstance(value, dict) and set(value) <= PENDING_FIELDS, "invalid pending-trade projection")
    _need(_key(value.get("token")) and _key(value.get("phase")), "missing pending token/phase")
    if value["token"] == token and value["phase"] in CRITICAL:
        _pair(value.get("verdict"), "pending verdict")
        for side in SIDES:
            _need(value.get(f"{side}_key") == before_keys[side], "pending old-key mismatch")
            _verdict(value["verdict"][side], side)
    return {**value, "problem": value.get("problem", "")}


def _record(value, token, before_keys, after_keys):
    _need(isinstance(value, dict) and set(value) == RECORD_FIELDS, "invalid trade_last record")
    _need(value["token"] == token, "trade_last token mismatch")
    _need(value["outcome"] in TERMINAL | {"uncertain"}, "invalid trade outcome")
    _time(value["at"])
    _pair(value["verdict"], "trade_last verdict")
    _need(isinstance(value["problem"], str), "invalid trade problem text")
    for side in SIDES:
        _need(value[f"{side}_key"] == before_keys[side], "trade_last old-key mismatch")
        verdict = _verdict(value["verdict"][side], side)
        want = after_keys[side] if verdict == "traded" else None
        _need(value[f"{side}_new"] == want, "trade_last new-key mismatch")
    return value


def _problem(value, pending):
    want = pending if pending and pending["phase"] in ("uncertain", "conflict") else None
    _need(value == want, "trade_problem disagrees with pending trade")


@_checked
def verify_reconciliation(*, token, before_keys, after_keys, final_party_keys,
                          independent_verdicts, events, status, journal,
                          expected_outcomes=("committed", "rolled_back")) -> dict:
    """Return a reconciliation receipt or raise RuntimeError on missing/conflicting proof.

    Key/verdict inputs are dictionaries keyed by ``a`` and ``b``. ``after_keys``
    names each side's independently decoded final selected mon (the old key for
    ``none``); ``conflict`` may use None when no unique final mon exists. Party
    keys are nonempty lists without duplicate identities, compared without slot
    ordering. Only an explicitly expected conflict is a successful *check*.
    """
    _need(isinstance(token, str) and token.startswith("t") and token[1:].isdigit(), "invalid token")
    for value, label in ((before_keys, "before keys"), (after_keys, "after keys"),
                         (final_party_keys, "final party"), (independent_verdicts, "independent verdict")):
        _pair(value, label)
    _need(all(_key(value) for value in before_keys.values()) and before_keys["a"] != before_keys["b"],
          "invalid/duplicate offered keys")
    for side in SIDES:
        verdict = independent_verdicts[side]
        _need(verdict in ("traded", "none", "conflict"), "independent verdict is unresolved/invalid")
        party = final_party_keys[side]
        _need(isinstance(party, list) and 1 <= len(party) <= 6 and all(_key(key) for key in party)
              and len(set(party)) == len(party), "empty/duplicate/invalid independently saved party")
        if verdict == "traded":
            _need(_key(after_keys[side]) and after_keys[side] in party
                  and before_keys[side] not in party, "traded verdict contradicts final saved keys")
        elif verdict == "none":
            _need(after_keys[side] == before_keys[side] and before_keys[side] in party,
                  "none verdict contradicts final saved keys")
        else:
            _need(after_keys[side] is None or _key(after_keys[side]), "invalid conflict final key")
    values = tuple(independent_verdicts.values())
    expected = "committed" if values == ("traded", "traded") else (
        "rolled_back" if values == ("none", "none") else "conflict")
    _need(isinstance(expected_outcomes, (tuple, list)) and expected_outcomes
          and all(item in TERMINAL for item in expected_outcomes), "invalid expected outcomes")
    _need(expected in expected_outcomes, f"independent outcome {expected} is not expected")
    _need(isinstance(status, dict) and "trade_problem" in status, "missing final status")
    final = _record(status.get("trade_last"), token, before_keys, after_keys)
    _need(final["outcome"] == expected, "status disagrees with independent outcome")
    for side in SIDES:
        _need(_verdict(final["verdict"][side], side) == independent_verdicts[side],
              "status verdict disagrees with independent save")
    if expected == "conflict":
        _need(bool(final["problem"]), "conflict has no problem")
        want_problem = {key: final[key] for key in ("token", "a_key", "b_key", "verdict", "problem")}
        want_problem["phase"] = "conflict"
        _need(status["trade_problem"] == want_problem, "conflict is not surfaced in final status")
    else:
        _need(status["trade_problem"] is None and final["problem"] == "", "settled status retains a problem")

    _need(isinstance(journal, list) and journal, "missing dispatch journal")
    await_seq, evidence, done, records = {}, {}, set(), []
    previous_seq, previous_after, provenance = 0, None, None
    for row in journal:
        _need(isinstance(row, dict) and row.get("source") == "server_dispatch", "invalid journal source")
        seq = row.get("seq")
        _need(type(seq) is int and seq > previous_seq, "journal sequence repeats/reverses")
        previous_seq = seq
        identity = (row.get("run_id"), row.get("scenario"), row.get("evidence_class"))
        _need(all(_key(item) for item in identity[:2]) and identity[2] == "HARNESS_ONLY_OVERLAY",
              "missing journal provenance")
        _need(provenance is None or identity == provenance, "journal provenance changes")
        provenance = identity
        side, message, result = row.get("player"), row.get("message"), row.get("outcome")
        _need(side in SIDES and isinstance(message, dict) and message.get("player") == side,
              "journal player mismatch")
        _need(isinstance(result, dict) and result.get("dispatch") == "returned", "dispatch did not return")
        _need({"pending_trade_before", "pending_trade", "trade_problem", "trade_last",
               "watchdog_observed", "pending_trade_after_watchdog", "trade_problem_after_watchdog",
               "trade_last_after_watchdog"} <= result.keys(),
              "missing reconciliation journal fields")
        before = _pending(result["pending_trade_before"], token, before_keys)
        midpoint = _pending(result["pending_trade_after_watchdog"], token, before_keys)
        after = _pending(result["pending_trade"], token, before_keys)
        _need(type(result["watchdog_observed"]) is bool, "watchdog observation must be a literal boolean")
        _problem(result["trade_problem_after_watchdog"], midpoint)
        _problem(result["trade_problem"], after)
        if previous_after is not None and previous_after.get("token") == token:
            _need(before == previous_after, "pending journal chain is discontinuous")
        previous_after = after
        if not result["watchdog_observed"]:
            _need(midpoint is None and result["trade_last_after_watchdog"] is None and before == after,
                  "unobserved watchdog cannot prove a state transition")
            rec = result["trade_last"]
            if isinstance(rec, dict) and rec.get("token") == token:
                _need(records and rec == records[-1], "unobserved watchdog cannot establish an outcome")
            continue
        event = message.get("event")
        if event == "trade_done" and (message.get("token") == token
                                      or before and before.get("token") == token):
            _need(midpoint and midpoint.get("token") == token and midpoint.get("phase") == "applying"
                  and message.get("token") == token and side not in done,
                  "missing/wrong/late/duplicate trade_done token/side")
            done.add(side)
        stages = (
            ("watchdog", before, midpoint, result["trade_last_after_watchdog"],
             result["trade_problem_after_watchdog"]),
            ("handler", midpoint, after, result["trade_last"], result["trade_problem"]),
        )
        for stage, prior, current, rec, problem in stages:
            relevant = prior and prior.get("token") == token and prior.get("phase") in CRITICAL
            if stage == "watchdog" and relevant:
                expected_midpoint = {**prior, "phase": "uncertain", "verdict": {
                    player: "await" if verdict is None else verdict
                    for player, verdict in prior["verdict"].items()}}
                _need(current == prior or prior["phase"] == "applying" and current == expected_midpoint,
                      "watchdog midpoint is not a source-permitted transition")
            if isinstance(rec, dict) and rec.get("token") == token:
                _record(rec, token, before_keys, after_keys)
                if not records or rec != records[-1]:
                    if rec["outcome"] == "uncertain":
                        _need(stage == "watchdog" and relevant and prior["phase"] == "applying"
                              and current and current.get("phase") == "uncertain"
                              and rec["verdict"] == current["verdict"]
                              and "await" in rec["verdict"].values() and rec["problem"] == "",
                              "uncertain record does not describe an observed watchdog await state")
                    else:
                        _need(stage == "handler" and relevant and rec == final
                              and problem == status["trade_problem"]
                              and (current is None if expected != "conflict" else
                                   current is not None and current.get("phase") == "conflict"),
                              "terminal record disagrees with its dispatch state")
                    records.append(rec)
            if not relevant:
                continue
            _need(current is None or current.get("token") == token, "pending token changed during reconciliation")
            terminal_now = current is None or current.get("phase") == "conflict"
            if terminal_now:
                _need(rec == final and problem == status["trade_problem"],
                      "terminal dispatch lacks the final outcome state")
            next_verdict = rec["verdict"] if terminal_now else current["verdict"]
            for player in SIDES:
                was, now = prior["verdict"][player], next_verdict[player]
                if now == "await" and was != "await":
                    _need(was is None and player not in await_seq
                          and (stage == "watchdog" or event == "trade_done" and player == side
                               and (message.get("uncertain") or not message.get("new_key"))),
                          "invalid repeated/unobserved await transition")
                    await_seq[player] = seq
                if now == was:
                    continue
                if now in (None, "await"):
                    _need(now == "await", "verdict regressed")
                    continue
                _need(stage == "handler" and was in (None, "await") and player == side and player not in evidence,
                      "verdict changed without that side's evidence")
                _need(_verdict(now, player) == independent_verdicts[player], "dispatch verdict disagrees with save")
                if was == "await":
                    _need(player in await_seq and seq >= await_seq[player] and event in ("hello", "tick", "safe"),
                          "resolution lacks observed post-await hello/tick/safe")
                    party = message.get("party")
                    _need(isinstance(party, list) and party and all(isinstance(mon, dict) for mon in party),
                          "resolution has no party")
                    keys = [mon.get("key") for mon in party]
                    _need(all(_key(key) for key in keys) and len(set(keys)) == len(keys)
                          and sorted(keys) == sorted(final_party_keys[player]),
                          "post-await party disagrees with independently saved final party")
                    kind = "party"
                else:
                    _need(prior["phase"] == "applying" and event == "trade_done" and not message.get("uncertain")
                          and message.get("new_key") == after_keys[player]
                          and independent_verdicts[player] in ("traded", "none"),
                          "pre-await snapshot/report cannot establish reconciliation")
                    kind = "trade_done"
                evidence[player] = {"kind": kind, "seq": seq}

    _need(await_seq and set(evidence) == set(SIDES), "missing await transition or resolved side evidence")
    _need(len(records) == 2 and records[0]["outcome"] == "uncertain" and records[1] == final,
          "missing/duplicate/extra token-bound outcomes in journal")
    uncertain = records[0]
    _need(uncertain["at"] <= final["at"], "trade timestamps reverse")
    _need(isinstance(events, list) and all(isinstance(event, dict) for event in events), "invalid events.json")
    matching = [event for event in events if event.get("key") == token
                and isinstance(event.get("type"), str) and event["type"].startswith("trade_")]
    _need([event["type"] for event in matching] == [f"trade_{expected}", "trade_uncertain"],
          "missing/duplicate/extra/reversed events.json outcomes")
    times = []
    for event, rec in zip(matching, (final, uncertain), strict=True):
        stamp = event.get("ts")
        _need(isinstance(stamp, str) and "T" in stamp, "missing event timestamp")
        parsed = datetime.fromisoformat(stamp)
        _need(parsed.tzinfo is None and parsed.microsecond == 0, "event timestamp is not native local seconds")
        at = parsed.timestamp()
        _need(rec["at"] < at + 1, "event timestamp precedes its trade record")
        times.append(at)
    _need(times[0] >= times[1] and times[1] <= final["at"], "event timestamps reverse")
    return {"token": token, "outcome": expected, "verdicts": dict(independent_verdicts),
            "await_sequences": await_seq, "evidence": evidence,
            "uncertain_at": uncertain["at"], "settled_at": final["at"]}
