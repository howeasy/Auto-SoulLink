"""Accounting only: the caller supplies policy, physical evidence, TTL and journal."""

import copy

import pytest

from server.execution_window import VerifiedExecutionWindow
from server.frame_progress import (
    MAX_INTEGER,
    RECEIPT,
    complete,
    covers,
    initial,
    reserve,
    validate,
    verify_closed,
)
from server.protocol import digest
from server.protocol_journal import JournalError


def proof(number=1, frames=60, **scope):
    return VerifiedExecutionWindow(
        {
            "operation_id": f"{number:032x}",
            "operation_digest": "d" * 64,
            "context_generation": "c" * 32,
            "binding_digest": "b" * 64,
            "phase": "ordinary",
            **scope,
        },
        "e" * 64,
        frames,
        1000,
    )


def start():
    return initial(context_generation="c" * 32, physical_digest="f" * 64, frame=100)


def receipt(state, steps=30):
    grant = state["pending"]
    return {
        "schema": RECEIPT,
        "sequence": grant["sequence"],
        "scope": copy.deepcopy(grant["scope"]),
        "before": grant["before"],
        "after": grant["before"] + steps,
        "steps": steps,
        "observations_digest": digest({"explicit-test-observations": steps}),
    }


@pytest.mark.parametrize("steps", [0, 1, 30, 60])
def test_consumption_advances_only_actual_steps_and_retires_unused_capacity(steps):
    state = start()
    original = copy.deepcopy(state)
    granted = reserve(state, proof())
    before = copy.deepcopy(granted)
    after, closed = complete(granted, receipt(granted, steps))
    assert state == original and granted == before
    assert after["frame"] == 100 + steps and after["steps"] == steps and after["pending"] is None
    assert verify_closed(closed, anchor=after["anchor"]) == closed
    assert not covers(closed, 100, anchor=after["anchor"])
    assert covers(closed, 100 + steps, anchor=after["anchor"]) is (steps > 0)
    assert not covers(closed, 101 + steps, anchor=after["anchor"])
    second = reserve(after, proof(2))
    assert second["pending"]["before"] == 100 + steps
    assert second["pending"]["previous_digest"] == digest(closed)


def test_lost_receipt_never_allows_an_overlapping_grant():
    pending = reserve(start(), proof())
    with pytest.raises(JournalError, match="reconciliation"):
        reserve(pending, proof(2))
    closed, _ = complete(pending, receipt(pending))
    with pytest.raises(JournalError, match="no outstanding"):
        complete(closed, receipt(pending))


@pytest.mark.parametrize(
    "fault",
    [
        "extra_step",
        "step_count",
        "rewind",
        "start",
        "sequence",
        "context",
        "binding",
        "operation",
        "phase",
        "missing",
        "boolean",
        "observations",
    ],
)
def test_ungranted_or_misbound_frame_receipts_cannot_change_state(fault):
    pending = reserve(start(), proof())
    value = receipt(pending)
    snapshot = copy.deepcopy(pending)
    if fault == "extra_step":
        value.update(steps=61, after=161)
    elif fault == "step_count":
        value["steps"] += 1
    elif fault == "rewind":
        value.update(after=99, steps=-1)
    elif fault == "start":
        value.update(before=101, after=131)
    elif fault == "sequence":
        value["sequence"] += 1
    elif fault in ("context", "binding", "operation"):
        field = {
            "context": "context_generation",
            "binding": "binding_digest",
            "operation": "operation_id",
        }[fault]
        value["scope"][field] = "a" * len(value["scope"][field])
    elif fault == "phase":
        value["scope"]["phase"] = "trade"
    elif fault == "missing":
        del value["steps"]
    elif fault == "boolean":
        value["steps"] = True
    else:
        value["observations_digest"] = "unbound"
    with pytest.raises(JournalError):
        complete(pending, value)
    assert pending == snapshot


@pytest.mark.parametrize("field", ["frame", "steps", "sequence", "previous_digest"])
def test_unused_anchor_and_progress_must_be_consistent(field):
    state = start()
    state[field] = "a" * 64 if field == "previous_digest" else state[field] + 1
    with pytest.raises(JournalError):
        validate(state)


def test_grant_context_and_numeric_bounds_fail_closed():
    with pytest.raises(JournalError):
        reserve(start(), object())
    with pytest.raises(JournalError):
        reserve(start(), proof(context_generation="a" * 32))
    state = initial(context_generation="c" * 32, physical_digest="f" * 64, frame=MAX_INTEGER)
    with pytest.raises(JournalError):
        reserve(state, proof())


def test_closed_range_cannot_be_reused_with_another_physical_anchor():
    state = reserve(start(), proof())
    _, closed = complete(state, receipt(state))
    wrong = {**state["anchor"], "physical_digest": "a" * 64}
    with pytest.raises(JournalError):
        covers(closed, 110, anchor=wrong)


def test_many_ranges_keep_only_one_pending_grant_in_active_state():
    import json

    state = start()
    for number in range(1, 201):
        state = reserve(state, proof(number))
        state, _ = complete(state, receipt(state, 20))
    assert state["steps"] == 4000 and state["frame"] == 4100 and state["sequence"] == 200
    assert len(json.dumps(state)) < 500
