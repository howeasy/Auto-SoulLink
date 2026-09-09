"""Exact snapshot byte validation can be reused without caching record reads."""

import pytest

from server import protocol_journal as module
from server.protocol_journal import JournalError, ProtocolJournal


@pytest.fixture
def journal(tmp_path):
    value = ProtocolJournal(tmp_path / "journal.sqlite3", contract_hash="b" * 64)
    value.bootstrap({"value": 0})
    value.commit(
        "a",
        "a" * 32,
        {"event": "fixture"},
        expected_revision=0,
        state={"value": 1},
        commands={"a": [], "b": []},
        result={"ack": "ACK"},
        records=[{"namespace": "fixture", "key": "c" * 32, "value": {"record": 1}}],
    )
    yield value
    value.close()


def test_repeated_revision_reads_reuse_only_exact_snapshot_validation(journal, monkeypatch):
    raw = journal._db.execute("SELECT body FROM snapshot").fetchone()[0]
    original = module._decode
    reads = []

    def decode(body, fingerprint):
        reads.append(body)
        return original(body, fingerprint)

    monkeypatch.setattr(module, "_decode", decode)
    journal._validated_snapshot_row = None
    for _ in range(4):
        record = journal.record("fixture", "c" * 32)
        record.value["record"] = 900
    assert reads.count(raw) == 1
    assert journal.record("fixture", "c" * 32).value == {"record": 1}
    journal._db.execute("UPDATE records SET digest=?", ("0" * 64,))
    with pytest.raises(JournalError):
        journal.record("fixture", "c" * 32)


@pytest.mark.parametrize("mutation", ["body", "digest", "revision", "delete", "marker"])
def test_cached_revision_still_detects_changed_storage(journal, mutation):
    assert journal.record("fixture", "c" * 32).revision == 1
    if mutation == "body":
        journal._db.execute("UPDATE snapshot SET body=?", ('{"value":2}',))
    elif mutation == "digest":
        journal._db.execute("UPDATE snapshot SET digest=?", ("0" * 64,))
    elif mutation == "revision":
        journal._db.execute("UPDATE snapshot SET revision=0")
    elif mutation == "delete":
        journal._db.execute("DELETE FROM snapshot")
    else:
        journal._db.execute("DELETE FROM metadata WHERE name='atomic_records'")
    with pytest.raises(JournalError):
        journal.record("fixture", "c" * 32)


def test_valid_same_revision_replacement_is_revalidated(journal, monkeypatch):
    journal.record("fixture", "c" * 32)
    body, fingerprint = module._encode({"value": 2})
    journal._db.execute("UPDATE snapshot SET body=?,digest=?", (body, fingerprint))
    original = module._decode
    checked = []

    def decode(raw, sha):
        checked.append(raw)
        return original(raw, sha)

    monkeypatch.setattr(module, "_decode", decode)
    assert journal.record_history("fixture", "c" * 32)[0].value == {"record": 1}
    assert body in checked and journal.snapshot().state == {"value": 2}
