"""Real journal and bootstrap handlers; ordinary eligibility remains a test proof."""

import copy
import secrets
import sqlite3

import pytest

from server.execution_window import SCHEMA, VerifiedExecutionWindow
from server.frame_progress import RECEIPT
from server.gen1_frame_journal import enroll, grant, key, returned, verify_journal
from server.gen1_frame_runtime import COMPONENT
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_bootstrap_receipt import fixture
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_sessions import contract


def setup(runtime):
    instant = runtime.clock()
    runtime.clock = lambda: instant
    owners = {player: admit(runtime, player) for player in ("a", "b")}
    for player in ("a", "b"):
        initial = observation(runtime, player)
        send(runtime, player, owners[player], initial)
        receipt, _ = fixture(runtime.contract["players"][player]["variant"])
        receipt["begin"]["frame"] = 10
        receipt["end"]["frame"] = 90
        receipt.update(
            context_generation=player * 32,
            physical_instance=initial["host"]["owner_id"],
            final_sha1=initial["final_sha1"],
        )
        session = runtime.gate.sessions[player]
        runtime.process(
            {
                "protocol": runtime.protocol,
                "player": player,
                "session_id": session.session_id,
                "admission_epoch": runtime.gate.epoch,
                "seq": session.last_seq + 1,
                "operation_id": secrets.token_hex(16),
                "event": "bootstrap_observation",
                "payload": receipt,
            },
            owners[player],
        )
    from tests.unit.test_gen1_initial_save_runtime import complete_initial_save
    for player in ('a', 'b'):
        complete_initial_save(runtime, player, owners[player])


def request(runtime):
    document = runtime.state().document()
    operation = secrets.token_hex(16)
    binding = runtime.gate.sessions["a"].metadata["control_binding"]
    evidence = {"schema": "explicit-unit-eligibility-proof"}
    scope = {
        "operation_id": operation,
        "operation_digest": digest({"event": "frame_grant", "evidence": evidence}),
        "context_generation": binding["context_generation"],
        "binding_digest": binding["binding_digest"],
        "phase": "ordinary",
    }
    proof = VerifiedExecutionWindow(scope, digest(evidence), 10, 1000, digest(document))
    message = {
        "event": "frame_grant",
        "evidence": evidence,
        "window": {"schema": SCHEMA, "challenge": operation, "scope": scope},
    }
    return operation, message, proof


def closure(runtime):
    document = runtime.state().document()
    pending = document["components"][COMPONENT]["a"]["ledger"]["pending"]
    inventory = copy.deepcopy(
        document["components"]["gen1-initial-observations"]["a"]["observation"]
    )
    inventory["frame"] = pending["before"] + 5
    bundle = {"inventory": inventory, "engine_signals": None}
    receipt = {
        "schema": RECEIPT,
        "sequence": pending["sequence"],
        "scope": pending["scope"],
        "before": pending["before"],
        "after": inventory["frame"],
        "steps": 5,
        "observations_digest": digest(bundle),
    }
    return {"event": "frame_complete", "receipt": receipt, "bundle": bundle}


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_reservation_and_closure_are_atomic_replayable_and_remain_held(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        setup(runtime)
        enrollment = secrets.token_hex(16)
        enroll(runtime, "a", enrollment)
        before = runtime.journal.snapshot()
        enroll(runtime, "a", enrollment)
        assert runtime.journal.snapshot() == before
        operation, message, proof = request(runtime)
        result = grant(runtime, "a", operation, message, proof)
        assert result["frame_window"]["frames"] == 10
        before = runtime.journal.snapshot()
        grant(runtime, "a", operation, message, proof)
        assert runtime.journal.snapshot() == before
        ending = closure(runtime)
        finish = secrets.token_hex(16)
        returned(runtime, "a", finish, ending)
        before = runtime.journal.snapshot()
        returned(runtime, "a", finish, ending)
        assert runtime.journal.snapshot() == before
        verify_journal(runtime, runtime.state().document())
        assert runtime.state().barrier.ticket() is None
        assert not any(runtime.journal.pending_ids(p) for p in ("a", "b"))
        operation, message, proof = request(runtime)
        with pytest.raises(JournalError, match="observations must settle"):
            grant(runtime, "a", operation, message, proof)
        assert runtime.journal.snapshot() == before
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        verify_journal(runtime, runtime.state().document())
        assert runtime.state().document()["components"][COMPONENT]["a"]["ledger"]["frame"] == 105
    finally:
        runtime.close()


@pytest.mark.parametrize("phase", ["enroll", "grant", "return"])
def test_sql_record_failure_never_publishes_half_a_frame_transition(tmp_path, phase):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        if phase != "enroll":
            enroll(runtime, "a", secrets.token_hex(16))
        if phase == "return":
            operation, message, proof = request(runtime)
            grant(runtime, "a", operation, message, proof)
        before = runtime.journal.snapshot()
        runtime.journal._db.execute(
            "CREATE TRIGGER fail_frame BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'fixture'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            if phase == "enroll":
                enroll(runtime, "a", secrets.token_hex(16))
            elif phase == "grant":
                operation, message, proof = request(runtime)
                grant(runtime, "a", operation, message, proof)
            else:
                returned(runtime, "a", secrets.token_hex(16), closure(runtime))
        assert runtime.journal.snapshot() == before
        verify_journal(runtime, before.state)
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        verify_journal(runtime, runtime.state().document())
    finally:
        runtime.close()


def test_corrupt_frame_record_refuses_even_when_snapshot_is_unchanged(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        enroll(runtime, "a", secrets.token_hex(16))
        runtime.journal._db.execute(
            "UPDATE records SET digest=? WHERE namespace=? AND record_key=?",
            ("0" * 64, COMPONENT, key("a")),
        )
        with pytest.raises(JournalError):
            verify_journal(runtime, runtime.state().document())
    finally:
        runtime.close()
