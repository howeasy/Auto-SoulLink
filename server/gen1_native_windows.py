"""Durable native execution windows for the free_service path (no frame ledger).

Every native window `NativeExecutionPolicy` issues is verified against in-memory
progress (``policy.observed``): the process, frame, step, intent digest, armed flag
and routine-prefix length of the previous window for the same command. On the
retired frame-credit loop that progress was also journaled through the
``gen1-frame-progress`` ledger; a free_service player has no ledger, so
``gen1_native_frame_accounting.persist_grant`` skipped it and a restart lost every
window. This component keeps the same progress durably, one record per player,
keyed by command id, written in the same commit as the grant event.

It grants nothing: it retains what was independently verified and issued, so a
reopened runtime can read where a native command was (before/armed/releasing,
how many original routine steps were confirmed) instead of guessing. Forward
recovery reads it; nothing here decides recovery.
"""

import copy

from server import event_reference
from server.execution_window import VerifiedExecutionWindow
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier

COMPONENT = "gen1-native-windows"
EVENT = "native_window_grant"
HOST = frozenset({"process_id", "frame", "steps"})
ENTRY = frozenset({"origin", "challenge", "scope", "frames", "ttl_ms", "proof_digest", "state_digest",
                   "host", "start", "intent_digest", "armed", "sequence_length", "extra"})
MAX_INT = 2**53 - 1


def key(player):
    return digest({"component": COMPONENT, "player": player})[:32]


def entry_from(policy, player, command_id, binding, request, response, evidence, *, origin):
    """The durable mirror of what publish() just verified for this (player, command, binding)."""
    observed = policy.observed.get((player, command_id, binding["binding_digest"]))
    proof = policy.published.get((player, command_id, binding["binding_digest"]))
    if observed is None or not isinstance(proof, VerifiedExecutionWindow):
        raise JournalError("native window has no independently verified progress to retain")
    if (response.get("challenge") != request.get("challenge") or dict(response.get("scope") or {}) != dict(proof.scope)
            or response.get("proof_digest") != proof.proof_digest or response.get("frames") != proof.frames):
        raise JournalError("native window response differs from its verified proof")
    extra = {k: v for k, v in observed.items()
             if k not in {"process_id", "frame", "steps", "start", "intent_digest", "armed", "sequence_length"}}
    return {
        "origin": origin,
        "challenge": request["challenge"],
        "scope": dict(proof.scope),
        "frames": proof.frames,
        "ttl_ms": proof.ttl_ms,
        "proof_digest": proof.proof_digest,
        "state_digest": proof.state_digest,
        "host": {name: evidence["host"][name] for name in HOST},
        "start": observed["start"],
        "intent_digest": observed["intent_digest"],
        "armed": observed["armed"],
        "sequence_length": observed.get("sequence_length", 0),
        "extra": copy.deepcopy(extra),
    }


def persist(runtime, player, request, response, evidence):
    """Journal one issued native window for a player without a frame ledger.

    Called by gen1_native_frame_accounting.persist_grant after issue_for_control succeeded.
    Idempotent on the challenge (the operation id): a replayed control returns the
    committed result and writes nothing.
    """
    operation = request["challenge"]
    _identifier(operation)
    message = {"event": EVENT, "request": request, "grant": response, "evidence": evidence}
    old = runtime.journal.event(player, operation, message)
    if old is not None:
        return old.result
    from server.gen1_native_execution import NativeExecutionPolicy

    policy = runtime.verify_operation_execution
    if not isinstance(policy, NativeExecutionPolicy) or policy.runtime is not runtime:
        raise JournalError("owned native execution verifier required before window publication")
    stage = runtime.state()
    document = stage.document()
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    command_id = response["scope"]["operation_id"]
    entry = entry_from(policy, player, command_id, binding, request, response, evidence,
                       origin=event_reference.make(player, operation, message))
    if entry["state_digest"] != digest(document):
        raise JournalError("native window lost its independently verified state binding")
    windows = document["components"].setdefault(COMPONENT, {}).setdefault(player, {})
    previous = windows.get(command_id)
    # Monotonic per command, whatever binding reports it: the live cache is keyed by the current
    # control binding, so a reconnect could otherwise republish an earlier stage (a fresh `before`
    # window at a later frame) over an armed prefix and erase the arming evidence. Frames and steps
    # advance by the same amount, as the live policy requires within one binding
    # (gen1_native_execution): every frame the process ran since the last window was a stepped one.
    if previous is not None and (previous["host"]["process_id"] != entry["host"]["process_id"]
                                 or previous["host"]["frame"] > entry["host"]["frame"]
                                 or previous["host"]["steps"] > entry["host"]["steps"]
                                 or (entry["host"]["frame"] - previous["host"]["frame"]
                                     != entry["host"]["steps"] - previous["host"]["steps"])
                                 or previous["sequence_length"] > entry["sequence_length"]
                                 or previous["start"] != entry["start"]
                                 or (previous["armed"] and not entry["armed"])
                                 or previous["intent_digest"] != entry["intent_digest"]):
        raise JournalError("native window progress moved backwards")
    windows[command_id] = entry
    result = {"ack": "ACK", "native_window_grant": operation, "ordinary_execution": False}
    return runtime.journal.commit(player, operation, message, expected_revision=stage.journal_revision, state=document,
                                  commands={"a": [], "b": []}, result=result,
                                  records=[{"namespace": COMPONENT, "key": key(player), "value": windows}]).result


def verify_state(stage):
    players = stage.document()["components"].get(COMPONENT, {})
    if not isinstance(players, dict) or set(players) - {"a", "b"}:
        raise JournalError("invalid native window component")
    for player, windows in players.items():
        if not isinstance(windows, dict):
            raise JournalError("native windows must be keyed by command")
        for command_id, entry in windows.items():
            _identifier(command_id)
            if not isinstance(entry, dict) or set(entry) != ENTRY:
                raise JournalError("complete native window entry required")
            if event_reference.validate(entry["origin"])["player"] != player:
                raise JournalError("native window reference changed player")
            if entry["scope"].get("operation_id") != command_id:
                raise JournalError("native window scope names another command")
            VerifiedExecutionWindow(entry["scope"], entry["proof_digest"], entry["frames"], entry["ttl_ms"],
                                    state_digest=entry["state_digest"])
            host = entry["host"]
            if (not isinstance(host, dict) or set(host) != HOST
                    or any(type(host[n]) is not int or not 0 <= host[n] <= MAX_INT for n in HOST)
                    or type(entry["start"]) is not int or not 0 <= entry["start"] <= host["frame"]
                    or type(entry["sequence_length"]) is not int or entry["sequence_length"] < 0
                    or not isinstance(entry["armed"], bool) or not isinstance(entry["intent_digest"], str)
                    or not isinstance(entry["extra"], dict)):
                raise JournalError("native window host/progress fields required")


def verify_journal(journal, stage):
    verify_state(stage)
    players = stage.document()["components"].get(COMPONENT, {})
    for player in ("a", "b"):
        windows = players.get(player)
        record = journal.record(COMPONENT, key(player))
        if (windows is None) != (record is None) or record is not None and record.value != windows:
            raise JournalError("native windows differ from their atomic record")
        if windows is None:
            continue
        for command_id, entry in windows.items():
            event = event_reference.resolve(journal, entry["origin"])
            request = event.request
            if (request.get("event") != EVENT or event.result.get("native_window_grant") != entry["challenge"]
                    or request.get("request", {}).get("challenge") != entry["challenge"]
                    or request.get("grant", {}).get("scope", {}).get("operation_id") != command_id
                    or request.get("grant", {}).get("proof_digest") != entry["proof_digest"]
                    or {n: request.get("evidence", {}).get("host", {}).get(n) for n in HOST} != entry["host"]):
                raise JournalError("native window differs from its committed grant event")
            journal.command(player, command_id)  # raises when the journal never issued it


def windows_for(document, player):
    """Detached copy of the player's durable native windows, keyed by command id."""
    return copy.deepcopy(document["components"].get(COMPONENT, {}).get(player, {}))
