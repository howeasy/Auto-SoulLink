"""Bounded frame accounting shared by generation policies.

This module neither authorizes a game state nor reads a clock. A caller must
verify its generation policy before reserve(), persist the returned state and
grant atomically before delivery, and verify physical/observation evidence before
complete(). A lost response leaves an outstanding grant, never permission to
guess consumption or issue an overlapping range.
"""

import copy
import re

from server.execution_window import VerifiedExecutionWindow
from server.protocol import digest
from server.protocol_journal import JournalError

SCHEMA = "slink-frame-progress-v1"
RECEIPT = "slink-frame-progress-receipt-v1"
MAX_INTEGER = 2**53 - 1


def integer(value, low=0, high=MAX_INTEGER):
    if type(value) is not int or not low <= value <= high:
        raise JournalError("bounded frame integer required")
    return value


def identifier(value, size=32):
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{" + str(size) + "}", value) is None:
        raise JournalError("canonical frame identity required")
    return value


def initial(*, context_generation, physical_digest, frame):
    anchor = {
        "context_generation": identifier(context_generation),
        "physical_digest": identifier(physical_digest, 64),
        "frame": integer(frame),
    }
    return {
        "schema": SCHEMA,
        "anchor": anchor,
        "frame": frame,
        "steps": 0,
        "sequence": 0,
        "previous_digest": digest(anchor),
        "pending": None,
    }


def validate(state):
    if (
        not isinstance(state, dict)
        or set(state)
        != {"schema", "anchor", "frame", "steps", "sequence", "previous_digest", "pending"}
        or state["schema"] != SCHEMA
    ):
        raise JournalError("complete frame progress state required")
    anchor = state["anchor"]
    if not isinstance(anchor, dict) or set(anchor) != {
        "context_generation",
        "physical_digest",
        "frame",
    }:
        raise JournalError("complete physical frame anchor required")
    baseline = initial(**anchor)
    for key in ("frame", "steps", "sequence"):
        integer(state[key])
    identifier(state["previous_digest"], 64)
    if state["frame"] != anchor["frame"] + state["steps"]:
        raise JournalError("frame differs from the anchored consumed-step count")
    pending = state["pending"]
    if state["sequence"] == 0 and state != baseline:
        raise JournalError("unused frame ledger differs from its anchor")
    completed_count = state["sequence"] - (pending is not None)
    if completed_count == 0 and (
        state["frame"] != anchor["frame"]
        or state["steps"] != 0
        or state["previous_digest"] != baseline["previous_digest"]
    ):
        raise JournalError("first grant must retain the original frame anchor")
    if completed_count > 0 and state["previous_digest"] == baseline["previous_digest"]:
        raise JournalError("consumed grant has no completion-chain digest")
    if pending is not None:
        if not isinstance(pending, dict) or set(pending) != {
            "sequence",
            "anchor_digest",
            "previous_digest",
            "before",
            "limit",
            "scope",
            "proof_digest",
            "ttl_ms",
        }:
            raise JournalError("complete outstanding frame grant required")
        try:
            proof = VerifiedExecutionWindow(
                pending["scope"],
                pending["proof_digest"],
                pending["limit"] - pending["before"],
                pending["ttl_ms"],
            )
        except (TypeError, ValueError, KeyError) as error:
            raise JournalError("invalid outstanding frame grant") from error
        integer(pending["before"])
        integer(pending["limit"])
        integer(pending["sequence"], 1)
        if (
            pending["sequence"] != state["sequence"]
            or pending["before"] != state["frame"]
            or pending["anchor_digest"] != digest(anchor)
            or pending["previous_digest"] != state["previous_digest"]
            or proof.scope["context_generation"] != anchor["context_generation"]
        ):
            raise JournalError("outstanding grant differs from frame progress")
    return state


def reserve(state, proof):
    """Reserve one range from an independently verified execution-window proof."""
    validate(state)
    if not isinstance(proof, VerifiedExecutionWindow):
        raise JournalError("independently verified frame-window proof required")
    if state["pending"] is not None:
        raise JournalError("outstanding frame consumption requires reconciliation")
    if proof.scope["context_generation"] != state["anchor"]["context_generation"]:
        raise JournalError("frame grant belongs to another context generation")
    next_state = copy.deepcopy(state)
    next_state["sequence"] = integer(state["sequence"] + 1, 1)
    next_state["pending"] = {
        "sequence": next_state["sequence"],
        "anchor_digest": digest(state["anchor"]),
        "previous_digest": state["previous_digest"],
        "before": state["frame"],
        "limit": integer(state["frame"] + proof.frames),
        "scope": dict(proof.scope),
        "proof_digest": proof.proof_digest,
        "ttl_ms": proof.ttl_ms,
    }
    validate(next_state)
    return next_state


def complete(state, receipt):
    """Account for a verified held return; unused grant capacity is retired.

    The returned closed record must be persisted alongside next_state. Durable
    operation replay is the caller's journal responsibility, not a second call
    to this pure transition with guessed current state.
    """
    validate(state)
    grant = state["pending"]
    if grant is None:
        raise JournalError("frame receipt has no outstanding grant")
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        != {"schema", "sequence", "scope", "before", "after", "steps", "observations_digest"}
        or receipt["schema"] != RECEIPT
    ):
        raise JournalError("complete frame-consumption receipt required")
    for key in ("sequence", "before", "after", "steps"):
        integer(receipt[key])
    identifier(receipt["observations_digest"], 64)
    if (
        receipt["sequence"] != grant["sequence"]
        or receipt["scope"] != grant["scope"]
        or receipt["before"] != grant["before"]
        or receipt["after"] != receipt["before"] + receipt["steps"]
        or not grant["before"] <= receipt["after"] <= grant["limit"]
    ):
        raise JournalError("frame consumption differs from its exact granted range")
    closed = {"grant": copy.deepcopy(grant), "receipt": copy.deepcopy(receipt)}
    next_state = copy.deepcopy(state)
    next_state.update(
        frame=receipt["after"],
        steps=integer(state["steps"] + receipt["steps"]),
        previous_digest=digest(closed),
        pending=None,
    )
    validate(next_state)
    return next_state, closed


def verify_closed(closed, *, anchor):
    if (
        not isinstance(closed, dict)
        or set(closed) != {"grant", "receipt"}
        or not isinstance(closed["grant"], dict)
    ):
        raise JournalError("complete closed frame record required")
    grant = closed["grant"]
    initial(**anchor)
    try:
        before = {
            "schema": SCHEMA,
            "anchor": copy.deepcopy(anchor),
            "frame": grant["before"],
            "steps": grant["before"] - anchor["frame"],
            "sequence": grant["sequence"],
            "previous_digest": grant["previous_digest"],
            "pending": grant,
        }
        _, expected = complete(before, closed["receipt"])
    except (TypeError, KeyError) as error:
        raise JournalError("invalid closed frame record") from error
    if expected != closed:
        raise JournalError("closed frame record differs from its grant")
    return closed


def covers(closed, frame, *, anchor):
    """A callback frame must belong to consumed steps, not unused grant capacity."""
    verify_closed(closed, anchor=anchor)
    integer(frame)
    return closed["receipt"]["before"] < frame <= closed["receipt"]["after"]
