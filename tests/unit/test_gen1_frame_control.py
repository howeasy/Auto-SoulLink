"""Real admitted control packets carry finite frames, never an unbounded ticket."""

import secrets

import pytest

from server.execution_window import SCHEMA
from server.gen1_frame_runtime import COMPONENT, boundary_from_inventory
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import ProtocolError, digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_frame_journal import closure, setup
from tests.unit.test_gen1_sessions import contract


def request(runtime, *, boundary=None, sequence=1):
    session = runtime.gate.sessions["a"]
    binding = session.metadata["control_binding"]
    operation = secrets.token_hex(16)
    challenge = secrets.token_hex(16)
    initial = runtime.state().document()["components"]["gen1-initial-observations"]["a"][
        "observation"
    ]
    evidence = {
        "schema": "rby-frame-request-v1",
        "boundary": boundary or boundary_from_inventory(initial),
        "sequence": sequence,
    }
    scope = {
        "operation_id": operation,
        "operation_digest": digest({"event": "frame_grant", "evidence": evidence}),
        "context_generation": binding["context_generation"],
        "binding_digest": binding["binding_digest"],
        "phase": "ordinary",
    }
    return {
        "protocol": runtime.protocol,
        "player": "a",
        "session_id": session.session_id,
        "admission_epoch": runtime.gate.epoch,
        "seq": session.last_seq + 1,
        "operation_id": challenge,
        "event": "control",
        "control": {**binding, "challenge": challenge},
        "operation_execution": {
            "window": {"schema": SCHEMA, "challenge": operation, "scope": scope},
            "evidence": evidence,
        },
    }


def test_real_control_grants_accounted_frames_and_semantic_return_settles(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), ordinary_frames=True)
    try:
        setup(runtime)
        owner = runtime.gate.sessions["a"].owner
        response = runtime.process(request(runtime), owner)
        assert response["control"]["authority"] == "hold"
        assert response["operation_execution"]["frames"] == 60
        state = runtime.state().document()
        assert state["components"][COMPONENT]["a"]["ledger"]["pending"]
        message = closure(runtime)
        session = runtime.gate.sessions["a"]
        message.update(
            protocol=runtime.protocol,
            player="a",
            session_id=session.session_id,
            admission_epoch=runtime.gate.epoch,
            seq=session.last_seq + 1,
            operation_id=secrets.token_hex(16),
        )
        response = runtime.process(message, owner)
        assert response["ack"] == "ACK" and response["operation_id"] == message["operation_id"]
        state = runtime.state().document()
        assert state["components"][COMPONENT]["a"]["ledger"]["frame"] == 105
        assert state["components"][COMPONENT]["a"]["pending_observation"] is None
        boundary = boundary_from_inventory(
            state["components"]["gen1-inventory-observations"]["a"]["observation"]
        )
        assert (
            runtime.process(request(runtime, boundary=boundary, sequence=2), owner)[
                "operation_execution"
            ]["frames"]
            == 60
        )
        assert runtime.state().barrier.ticket() is None
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert runtime.ordinary_frames
    finally:
        runtime.close()


def test_unselected_network_route_never_issues_frames(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        before = runtime.journal.snapshot()
        with pytest.raises(ProtocolError):
            runtime.process(request(runtime), runtime.gate.sessions["a"].owner)
        assert runtime.journal.snapshot() == before
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["frame", "owner", "sequence", "scope", "context"])
def test_foreign_frame_scope_or_boundary_cannot_reserve(fault, tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"), ordinary_frames=True)
    try:
        setup(runtime)
        packet = request(runtime)
        evidence = packet["operation_execution"]["evidence"]
        if fault == "frame":
            evidence["boundary"]["frame"] += 1
        elif fault == "owner":
            evidence["boundary"]["host"]["process_id"] += 1
        elif fault == "sequence":
            evidence["sequence"] = 2
        elif fault == "scope":
            packet["operation_execution"]["window"]["scope"]["operation_digest"] = "f" * 64
        else:
            evidence["boundary"]["context_generation"] = "f" * 32
        with pytest.raises((JournalError, ProtocolError)):
            runtime.process(packet, runtime.gate.sessions["a"].owner)
        entry = runtime.state().document()["components"].get(COMPONENT, {}).get("a")
        assert entry is None or entry["ledger"]["pending"] is None
    finally:
        runtime.close()
