"""Checked event audit reads remain distinct from semantic replay validation."""

import hashlib

import pytest

from server.protocol_journal import EventSnapshot, JournalError, ProtocolJournal

OPERATION = "a" * 32
REQUEST = {"event": "observed", "payload": {"samples": [1, 2]}}
RESULT = {"ack": "ACK", "proof": {"accepted": [1]}}


@pytest.fixture
def journal(tmp_path):
    instance = ProtocolJournal(tmp_path / "journal.sqlite3", contract_hash="b" * 64)
    instance.bootstrap({"count": 0})
    instance.commit(
        "a", OPERATION, REQUEST, expected_revision=0, state={"count": 1},
        commands={"a": [{"cmd": "first"}], "b": [{"cmd": "second"}]}, result=RESULT,
    )
    yield instance
    instance.close()


def test_found_missing_detached_and_read_only(journal):
    before = journal._db.total_changes
    stored = journal.event_snapshot("a", OPERATION)
    receipt = journal.event("a", OPERATION, REQUEST)
    assert stored == EventSnapshot(1, REQUEST, RESULT, receipt.command_ids)
    assert journal.event_snapshot("b", OPERATION) is None
    assert journal.event_snapshot("a", "c" * 32) is None
    stored.request["payload"]["samples"].append(99)
    stored.result["proof"]["accepted"].clear()
    again = journal.event_snapshot("a", OPERATION)
    assert again.request == REQUEST and again.result == RESULT
    assert journal._db.total_changes == before


@pytest.mark.parametrize("player,operation", [
    ("c", OPERATION), (None, OPERATION), ("a", "A" * 32),
    ("a", "a" * 31), ("a", None), ("a", 123),
])
def test_invalid_identifiers_refuse(journal, player, operation):
    with pytest.raises(JournalError):
        journal.event_snapshot(player, operation)


@pytest.mark.parametrize("field", ["request", "result"])
@pytest.mark.parametrize("text,rehash", [
    pytest.param('{"changed":true}', False, id="changed-content"),
    pytest.param('{"unfinished":', True, id="invalid-json"),
    pytest.param('[1,2]', True, id="non-object"),
    pytest.param('{ "noncanonical": true }', True, id="noncanonical"),
    pytest.param('{"duplicate":1,"duplicate":2}', True, id="duplicate-key"),
    pytest.param('{"nested":' + '[' * 1100 + '0' + ']' * 1100 + '}', True, id="deep-nesting"),
    pytest.param("é", False, id="non-ascii"),
    pytest.param(b"{}", False, id="non-text"),
])
def test_corrupt_or_malformed_documents_refuse(journal, field, text, rehash):
    journal._db.execute(f"UPDATE events SET {field}=?", (text,))
    if rehash:
        digest = hashlib.sha256(text.encode("ascii")).hexdigest()
        journal._db.execute(f"UPDATE events SET {field}_digest=?", (digest,))
    with pytest.raises(JournalError):
        journal.event_snapshot("a", OPERATION)


@pytest.mark.parametrize("field", ["request_digest", "result_digest"])
@pytest.mark.parametrize("digest", ["0" * 64, "A" * 64, "bad", b"0" * 64])
def test_invalid_document_digests_refuse(journal, field, digest):
    journal._db.execute(f"UPDATE events SET {field}=?", (digest,))
    with pytest.raises(JournalError):
        journal.event_snapshot("a", OPERATION)


@pytest.mark.parametrize("revision", [0, -1, 2, 1.5, "unknown"])
def test_invalid_event_revision_refuses(journal, revision):
    journal._db.execute("UPDATE events SET revision=?", (revision,))
    with pytest.raises(JournalError, match="committed revision"):
        journal.event_snapshot("a", OPERATION)


@pytest.mark.parametrize("revision", [-1, 1.5, "unknown"])
def test_invalid_snapshot_revision_refuses(journal, revision):
    journal._db.execute("UPDATE snapshot SET revision=?", (revision,))
    with pytest.raises(JournalError, match="state revision"):
        journal.event_snapshot("a", OPERATION)


def test_event_without_committed_snapshot_refuses(journal):
    journal._db.execute("DELETE FROM snapshot")
    with pytest.raises(JournalError, match="state revision"):
        journal.event_snapshot("a", OPERATION)


def test_corrupt_command_identifier_refuses(journal):
    journal._db.execute("UPDATE commands SET command_id='invalid' WHERE player='a'")
    with pytest.raises(JournalError, match="identifiers"):
        journal.event_snapshot("a", OPERATION)


def test_old_event_remains_readable_and_replay_conflicts_still_refuse(journal):
    before = journal.event_snapshot("a", OPERATION)
    journal.commit(
        "b", "d" * 32, {"event": "later"}, expected_revision=1, state={"count": 2},
        commands={"a": [], "b": []}, result={"ack": "ACK"},
        acknowledgements=[{
            "player": "a", "command_id": before.command_ids[0], "outcome": "ACK",
            "receipt": {"verified": True},
        }],
    )
    assert journal.event_snapshot("a", OPERATION) == before
    receipt = journal.event("a", OPERATION, REQUEST)
    assert receipt.revision == before.revision and receipt.command_ids == before.command_ids
    with pytest.raises(JournalError, match="reused with different semantic content"):
        journal.event("a", OPERATION, {"event": "other"})
    assert journal.event_snapshot("a", OPERATION) == before


def test_snapshot_survives_reopen(journal):
    before = journal.event_snapshot("a", OPERATION)
    reopened = ProtocolJournal(journal.path, contract_hash="b" * 64)
    try:
        assert reopened.event_snapshot("a", OPERATION) == before
    finally:
        reopened.close()
