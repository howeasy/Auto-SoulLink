"""Durable native windows: what NativeExecutionPolicy verified is retained in the journal without a
frame ledger, in the grant's own commit, audited against its event and the issued command."""

import copy
import secrets

import pytest

from server.execution_window import SCHEMA as WINDOW_SCHEMA, issue
from server.gen1_native_frame_accounting import persist_grant
from server.gen1_native_windows import COMPONENT, key, persist, verify_journal, windows_for
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_native_execution import armed, case, verify  # noqa: F401  (fixture)


def request_for(proof):
    return {"schema": WINDOW_SCHEMA, "challenge": secrets.token_hex(16), "scope": dict(proof.scope)}


def issued(case, evidence=None, *, free_native=True):
    value, policy, command, original = case
    value.runtime.verify_operation_execution = policy
    if free_native:  # the production selection this component serves; standalone runtimes keep None
        value.runtime.free_service = True
        value.runtime.native_trade = True
    proof = verify(case, evidence)
    request = request_for(proof)
    return value, policy, command, (evidence or original), request, issue(request, proof), proof


def test_free_player_windows_are_journaled_with_the_grant_and_survive_reopen(case):
    value, policy, command, evidence, request, response, proof = issued(case)
    assert "gen1-frame-progress" not in value.runtime.state().document()["components"]
    before = value.runtime.journal.snapshot()
    result = persist_grant(value.runtime, "a", request, response, evidence)
    assert result == {"ack": "ACK", "native_window_grant": request["challenge"], "ordinary_execution": False}
    entry = windows_for(value.runtime.state().document(), "a")[command["command_id"]]
    assert entry["challenge"] == request["challenge"] and entry["scope"] == dict(proof.scope)
    assert entry["proof_digest"] == proof.proof_digest and entry["frames"] == proof.frames
    assert entry["host"] == {"process_id": 123, "frame": 100, "steps": 0}
    assert entry["armed"] is False and entry["sequence_length"] == 0 and entry["start"] == 100
    assert entry["intent_digest"] == digest(evidence["native"]["intent"])
    assert value.runtime.journal.record(COMPONENT, key("a")).value == {command["command_id"]: entry}
    assert value.runtime.journal.snapshot().revision == before.revision + 1
    # Replaying the same control returns the committed result without a second commit.
    assert persist_grant(value.runtime, "a", request, response, evidence) == result
    assert value.runtime.journal.snapshot().revision == before.revision + 1
    # The armed renewal advances the same command's entry: later frame, longer routine prefix.
    renewal = armed(evidence)
    _, _, _, _, request2, response2, proof2 = issued(case, renewal)
    persist_grant(value.runtime, "a", request2, response2, renewal)
    entry2 = windows_for(value.runtime.state().document(), "a")[command["command_id"]]
    assert entry2["armed"] is True and entry2["sequence_length"] == 2 and entry2["host"]["frame"] == 115
    assert entry2["start"] == 100 and entry2["challenge"] == request2["challenge"]
    verify_journal(value.runtime.journal, value.runtime.state())
    value.runtime.state()  # the state audit (verify_state) runs on every read


@pytest.mark.parametrize("fault", ["unverified", "foreign_response", "backwards", "not_native_policy"])
def test_windows_refuse_unverified_or_regressing_progress_and_commit_nothing(case, fault):
    value, policy, command, evidence, request, response, proof = issued(case)
    before = value.runtime.journal.snapshot()
    if fault == "unverified":
        request = request_for(proof)
        request["scope"]["operation_id"] = secrets.token_hex(16)
        response = {**response, "scope": dict(request["scope"])}
    elif fault == "foreign_response":
        response = {**response, "proof_digest": "0" * 64}
    elif fault == "backwards":
        persist_grant(value.runtime, "a", request, response, evidence)
        before = value.runtime.journal.snapshot()
        earlier = copy.deepcopy(evidence)
        earlier["host"]["frame"] -= 1
        policy.observed[("a", command["command_id"], value.runtime.gate.sessions["a"].metadata["control_binding"]["binding_digest"])]["frame"] -= 1
        request, response = request_for(proof), None
        response = issue(request, proof)
        evidence = earlier
    elif fault == "not_native_policy":
        from server.gen1_held_faint import verify as held
        value.runtime.verify_operation_execution = held
    with pytest.raises((JournalError, ValueError)):
        persist(value.runtime, "a", request, response, evidence)
    assert value.runtime.journal.snapshot() == before


@pytest.mark.parametrize("selection", ["standalone", "held_native", "free_only"])
def test_runtimes_that_did_not_select_free_native_persist_nothing(case, selection):
    value, policy, command, evidence, request, response, proof = issued(case, free_native=False)
    value.runtime.free_service = selection == "free_only"
    value.runtime.native_trade = selection == "held_native"
    before = value.runtime.journal.snapshot()
    assert persist_grant(value.runtime, "a", request, response, evidence) is None
    assert value.runtime.journal.snapshot() == before
    assert COMPONENT not in value.runtime.state().document()["components"]


def test_a_window_record_that_lost_its_event_fails_the_audit(case):
    value, policy, command, evidence, request, response, proof = issued(case)
    persist_grant(value.runtime, "a", request, response, evidence)
    stage = value.runtime.state()
    document = stage.document()
    document["components"][COMPONENT]["a"][command["command_id"]]["challenge"] = secrets.token_hex(16)

    class Forged:
        def document(self):
            return document

    with pytest.raises(JournalError):
        verify_journal(value.runtime.journal, Forged())
