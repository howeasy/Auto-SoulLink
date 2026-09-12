"""Adversarial retained-authority audit using synthetic enrollment and real SQLite.

These private accounting tests grant no ordinary gameplay policy or ROM claim.
"""

import copy
import secrets

import pytest

from server.gen1_frame_journal import GRANTS, enroll, grant, key, returned
from server.gen1_frame_runtime import COMPONENT
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import canonical_json, digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_engine_signal_runtime import payload
from tests.unit.test_gen1_frame_journal import closure, request, setup
from tests.unit.test_gen1_sessions import contract


@pytest.fixture
def runtime(tmp_path):
    value = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(value)
        enroll(value, "a", secrets.token_hex(16))
        yield value
    finally:
        value.close()


def finish(runtime):
    operation, message, proof = request(runtime)
    grant(runtime, "a", operation, message, proof)
    record = runtime.journal.record(GRANTS, operation)
    returned(runtime, "a", secrets.token_hex(16), closure(runtime))
    return operation, record


def refuses_now_and_after_reopen(runtime, path):
    with pytest.raises(JournalError):
        runtime.state()
    runtime.close()
    reopened = None
    try:
        with pytest.raises(JournalError):
            reopened = open_runtime(path)
            reopened.state()
    finally:
        if reopened is not None:
            reopened.close()


@pytest.mark.parametrize(
    "fault",
    ["event", "authority", "old_reproduction", "request_hash", "result_hash", "record_hash"],
)
def test_completed_range_requires_retained_grant_event_and_authority(runtime, tmp_path, fault):
    operation, record = finish(runtime)
    snapshot = runtime.journal.snapshot()
    db = runtime.journal._db
    if fault in ("event", "old_reproduction"):
        db.execute("DELETE FROM events WHERE player=? AND operation_id=?", ("a", operation))
    if fault in ("authority", "old_reproduction"):
        db.execute("DELETE FROM records WHERE namespace=? AND record_key=?", (GRANTS, operation))
    if fault == "old_reproduction":
        db.execute(
            "DELETE FROM records WHERE namespace=? AND record_key=? AND revision=?",
            (COMPONENT, key("a"), record.revision),
        )
    elif fault in ("request_hash", "result_hash"):
        column = "request_digest" if fault == "request_hash" else "result_digest"
        db.execute(
            f"UPDATE events SET {column}=? WHERE player=? AND operation_id=?",
            ("0" * 64, "a", operation),
        )
    elif fault == "record_hash":
        db.execute(
            "UPDATE records SET digest=? WHERE namespace=? AND record_key=?",
            ("0" * 64, GRANTS, operation),
        )
    assert runtime.journal.snapshot() == snapshot
    refuses_now_and_after_reopen(runtime, tmp_path)


@pytest.mark.parametrize(
    "fault", ["operation", "evidence", "operation_digest", "phase", "no_state"]
)
def test_checked_record_hash_cannot_replace_exact_original_policy_proof(runtime, tmp_path, fault):
    operation, record = finish(runtime)
    value = copy.deepcopy(record.value)
    proof = value["proof"]
    if fault == "operation":
        proof["scope"]["operation_id"] = "f" * 32
    elif fault == "evidence":
        proof["proof_digest"] = "f" * 64
    elif fault == "operation_digest":
        proof["scope"]["operation_digest"] = "f" * 64
    elif fault == "phase":
        proof["scope"]["phase"] = "trade"
    else:
        proof["state_digest"] = None
    runtime.journal._db.execute(
        "UPDATE records SET body=?,digest=? WHERE namespace=? AND record_key=?",
        (canonical_json(value), digest(value), GRANTS, operation),
    )
    refuses_now_and_after_reopen(runtime, tmp_path)


@pytest.mark.parametrize("fault", ["duplicate", "late", "entry"])
def test_grant_alias_is_immutable_precedes_return_and_matches_exact_pending_entry(
    runtime, tmp_path, fault
):
    operation, record = finish(runtime)
    db = runtime.journal._db
    if fault == "duplicate":
        db.execute(
            "INSERT INTO records VALUES (?,?,?,?,?)",
            (
                GRANTS,
                operation,
                record.revision - 1,
                canonical_json(record.value),
                digest(record.value),
            ),
        )
    elif fault == "late":
        completion_revision = runtime.journal.snapshot().revision
        db.execute(
            "UPDATE records SET revision=? WHERE namespace=? AND record_key=?",
            (completion_revision, GRANTS, operation),
        )
        db.execute(
            "UPDATE events SET revision=? WHERE player=? AND operation_id=?",
            (completion_revision, "a", operation),
        )
    else:
        value = copy.deepcopy(record.value)
        value["entry"]["ledger"]["pending"]["limit"] += 1
        db.execute(
            "UPDATE records SET body=?,digest=? WHERE namespace=? AND record_key=?",
            (canonical_json(value), digest(value), GRANTS, operation),
        )
    refuses_now_and_after_reopen(runtime, tmp_path)


@pytest.mark.parametrize("window", [None, {}, {"schema": "wrong"}])
def test_malformed_window_is_journal_refusal_without_publication(runtime, window):
    operation, message, proof = request(runtime)
    message["window"] = window
    before = runtime.journal.snapshot()
    with pytest.raises(JournalError):
        grant(runtime, "a", operation, message, proof)
    assert runtime.journal.snapshot() == before
    assert runtime.journal.record(GRANTS, operation) is None
    assert runtime.journal.event("a", operation, message) is None


@pytest.mark.parametrize("location", ["inventory", "engine"])
@pytest.mark.parametrize("name", ["50" * 11, "00" + "50" * 10])
def test_invalid_name_in_held_bundle_is_journal_refusal_without_closure(runtime, location, name):
    operation, message, proof = request(runtime)
    grant(runtime, "a", operation, message, proof)
    ending = closure(runtime)
    bundle = ending["bundle"]
    if location == "inventory":
        bundle["inventory"]["source"]["fields"]["name"] = name
    else:
        bundle["engine_signals"] = payload(runtime, "a", ["battle_faint"])
        bundle["engine_signals"]["signals"][0]["point"]["trainer_hex"] = name
    ending["receipt"]["observations_digest"] = digest(bundle)
    before = runtime.journal.snapshot()
    finish_operation = secrets.token_hex(16)
    with pytest.raises(JournalError):
        returned(runtime, "a", finish_operation, ending)
    assert runtime.journal.snapshot() == before
    assert runtime.journal.event("a", finish_operation, ending) is None
