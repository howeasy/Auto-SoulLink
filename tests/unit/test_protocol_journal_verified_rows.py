"""Opt-in canonical row reuse preserves every fresh SQL and mutable receipt check."""

import copy
import secrets

import pytest

from server.protocol_journal import JournalError, _encode
from tests.unit.test_protocol_journal import AFTER, BEFORE, COMMANDS, REQUEST, commit, open_journal

KEY = "a" * 32


def opened(tmp_path):
    journal = open_journal(tmp_path / "verified.sqlite3")
    journal.bootstrap(BEFORE)
    assert journal.verified_row_cache_info() is None, "other consumers remain cache-disabled by default"
    journal.enable_verified_row_cache()
    return journal


def test_successful_commit_seeds_detached_rows_and_mutable_receipt_stays_fresh(tmp_path):
    journal = opened(tmp_path)
    try:
        receipt = commit(journal, records=[{"namespace": "test-proof", "key": KEY,
                                            "value": {"blob": "A" * 74000}}])
        assert journal.verified_row_cache_info()["entries"] >= 4
        snapshot = journal.snapshot()
        snapshot.state["links"].clear()
        assert journal.snapshot().state == AFTER
        event = journal.event_snapshot("a", "3" * 32)
        event.request["event"] = "forged"
        assert journal.event_snapshot("a", "3" * 32).request == REQUEST
        record = journal.record("test-proof", KEY)
        record.value["blob"] = "caller mutation"
        assert journal.record("test-proof", KEY).value["blob"] == "A" * 74000
        command_id = receipt.command_ids[0]
        assert journal.command("a", command_id)["outcome"] is None
        journal.acknowledge("a", command_id, "ACK", {"proof": "current"})
        assert journal.command("a", command_id)["receipt"] == {"proof": "current"}
        assert journal.verified_row_cache_info()["hits"] > 0
    finally:
        journal.close()


def test_post_commit_caller_mutation_cannot_poison_exact_byte_cache(tmp_path):
    journal = opened(tmp_path)
    original_db = journal._db
    state, request, result = copy.deepcopy(AFTER), copy.deepcopy(REQUEST), {"ack": "ACK"}
    record = {"namespace": "test-proof", "key": KEY, "value": {"blob": "A" * 74000}}
    original_state, original_request, original_result, original_record = (
        copy.deepcopy(state), copy.deepcopy(request), copy.deepcopy(result), copy.deepcopy(record["value"])
    )

    class CommitThenMutate:
        def __getattr__(self, name):
            return getattr(original_db, name)

        def commit(self):
            original_db.commit()  # mutation happens only AFTER exact bytes became durable
            state["links"].clear()
            request["event"] = "forged"
            result["ack"] = "NACK"
            record["namespace"] = "forged"
            record["key"] = "b" * 32
            record["value"]["blob"] = "caller mutation"

    try:
        journal._db = CommitThenMutate()
        journal.commit("a", "3" * 32, request, expected_revision=0, state=state,
                       commands={"a": [], "b": []}, result=result, records=[record])
        journal._db = original_db
        assert journal.snapshot().state == original_state
        event = journal.event_snapshot("a", "3" * 32)
        assert event.request == original_request and event.result == original_result
        assert journal.record("test-proof", KEY).value == original_record
        assert journal.verified_row_cache_info()["hits"] >= 3
    finally:
        journal._db = original_db
        journal.close()


@pytest.mark.parametrize("fault", ["snapshot_same_revision", "snapshot_rollback", "record_digest", "record_body"])
def test_warm_cache_refuses_tampered_or_rolled_back_rows(tmp_path, fault):
    journal = opened(tmp_path)
    try:
        initial = journal._db.execute("SELECT revision,body,digest FROM snapshot").fetchone()
        commit(journal, records=[{"namespace": "test-proof", "key": KEY,
                                  "value": {"blob": "A" * 74000}}])
        journal.snapshot()
        journal.record("test-proof", KEY)
        if fault == "snapshot_same_revision":
            body, digest = _encode({"forged": True})
            journal._db.execute("UPDATE snapshot SET body=?,digest=?", (body, digest))
            read = journal.snapshot
        elif fault == "snapshot_rollback":
            journal._db.execute("UPDATE snapshot SET revision=?,body=?,digest=?", tuple(initial))
            read = journal.snapshot
        elif fault == "record_digest":
            journal._db.execute("UPDATE records SET digest=? WHERE namespace='test-proof'", ("f" * 64,))
            read = lambda: journal.record("test-proof", KEY)
        else:
            journal._db.execute("UPDATE records SET body=? WHERE namespace='test-proof'", ('{"blob":"other"}',))
            read = lambda: journal.record("test-proof", KEY)
        with pytest.raises(JournalError):
            read()
    finally:
        journal.close()


def test_warm_body_cache_never_hides_changed_command_receipt(tmp_path):
    journal = opened(tmp_path)
    try:
        receipt = commit(journal)
        command_id = receipt.command_ids[0]
        journal.command("a", command_id)
        journal.acknowledge("a", command_id, "ACK", {"proof": "current"})
        assert journal.command("a", command_id)["receipt"] == {"proof": "current"}
        journal._db.execute("UPDATE commands SET receipt_digest=? WHERE command_id=?", ("f" * 64, command_id))
        with pytest.raises(JournalError):
            journal.command("a", command_id)
    finally:
        journal.close()


@pytest.mark.parametrize("cached", [False, True])
def test_valid_same_revision_record_substitution_is_fresh_not_a_cached_old_value(tmp_path, cached):
    journal = open_journal(tmp_path / "substitution.sqlite3")
    try:
        journal.bootstrap(BEFORE)
        if cached:
            journal.enable_verified_row_cache()
        original = {"phase": "active", "body": {"cmd": "native_receptionist"}}
        forged = {"phase": "closed", "body": {"cmd": "native_receptionist"}}
        journal.commit("a", "3" * 32, REQUEST, expected_revision=0, state=AFTER,
                       commands={"a": [], "b": []}, result={"ack": "ACK"},
                       records=[{"namespace": "test-proof", "key": KEY, "value": original}])
        snapshot = journal.snapshot()
        retained = journal.record("test-proof", KEY)
        assert retained.value == original
        body, checksum = _encode(forged)
        journal._db.execute("UPDATE records SET body=?,digest=? WHERE namespace='test-proof' AND record_key=?",
                            (body, checksum, KEY))
        assert journal.snapshot() == snapshot, "the aggregate was not rewritten"
        fresh = journal.record("test-proof", KEY)
        assert fresh.revision == retained.revision and fresh.value == forged
        assert retained.value == original, "the prior caller-owned value stays detached"
        # A direct record read is not an aggregate authorization verdict.  The
        # generation validator must compare it with the unchanged snapshot.
    finally:
        journal.close()


def test_reopen_starts_cold_and_cache_stays_bounded(tmp_path):
    path = tmp_path / "verified.sqlite3"
    journal = opened(tmp_path)
    try:
        initial = tuple(journal._db.execute("SELECT revision,body,digest FROM snapshot").fetchone())
        revision = 0
        for number in range(520):
            journal.commit("a", secrets.token_hex(16), {"event": "profile", "number": number},
                           expected_revision=revision, state=copy.deepcopy(AFTER),
                           commands={"a": [], "b": []}, result={"ack": "ACK"})
            revision += 1
        info = journal.verified_row_cache_info()
        assert info["entries"] <= 64 and info["serialized_bytes"] <= 8 * 1024 * 1024
        assert journal.snapshot().revision == revision
    finally:
        journal.close()
    reopened = open_journal(path)
    try:
        assert reopened.verified_row_cache_info() is None
        reopened.enable_verified_row_cache()
        assert reopened.verified_row_cache_info()["entries"] == 0
        assert reopened.snapshot().revision == revision
        assert reopened.verified_row_cache_info()["misses"] == 1
        reopened._db.execute("UPDATE snapshot SET revision=?,body=?,digest=?", initial)
        with pytest.raises(JournalError, match="rolled back"):
            reopened.snapshot()
    finally:
        reopened.close()
