"""Component records commit with state, events, ACKs and both outboxes."""
import sqlite3

import pytest

from server.protocol_journal import JournalError, ProtocolJournal, RevisionConflict

RUN, CONTRACT, KEY = "1"*32, "2"*64, "3"*32


def open_journal(path):
    return ProtocolJournal(path, run_id=RUN, contract_hash=CONTRACT)


def commit(journal, op, *, revision, value, commands=None, acknowledgements=()):
    return journal.commit("a", op, {"event": "record-test", "value": value}, expected_revision=revision,
        state={"active": KEY, "phase": value}, commands=commands or {"a": [], "b": []},
        result={"ack": "ACK"}, acknowledgements=acknowledgements,
        records=[{"namespace": "native-trade", "key": KEY, "value": {"phase": value}}])


def test_records_outboxes_and_ack_survive_reopen_atomically(tmp_path):
    path = tmp_path / "run.sqlite3"
    with_journal = open_journal(path)
    with_journal.bootstrap({"active": None})
    first = commit(with_journal, "4"*32, revision=0, value="prepare",
                   commands={"a": [{"cmd": "prepare"}], "b": [{"cmd": "prepare"}]})
    cmd = with_journal.pending("a")[0]
    commit(with_journal, "5"*32, revision=1, value="ready",
           acknowledgements=[{"player": "a", "command_id": cmd["command_id"], "outcome": "ACK",
                              "receipt": {"schema": "prepared-test"}}])
    with_journal.close()
    journal = open_journal(path)
    try:
        assert journal.record("native-trade", KEY).value == {"phase": "ready"}
        assert journal.record("native-trade", KEY).revision == journal.snapshot().revision == 2
        assert not journal.pending("a") and journal.pending("b")[0]["command_id"] in first.command_ids
        assert journal._db.execute("SELECT count(*) FROM records").fetchone()[0] == 2
        assert [r.value["phase"] for r in journal.record_history("native-trade", KEY)] == ["prepare", "ready"]
        assert [r.revision for r in journal.record_history("native-trade", KEY, after_revision=1, limit=1)] == [2]
        assert dict(journal._db.execute("SELECT name,value FROM metadata"))["atomic_records"] == "v1"
        detached = journal.record("native-trade", KEY).value
        detached["phase"] = "forged"
        assert journal.record("native-trade", KEY).value["phase"] == "ready"
    finally:
        journal.close()


@pytest.mark.parametrize("failure", ["records", "capacity", "revision"])
def test_failure_publishes_neither_record_state_ack_nor_commands(tmp_path, failure):
    journal = open_journal(tmp_path / "run.sqlite3")
    try:
        journal.bootstrap({"active": None})
        commit(journal, "4"*32, revision=0, value="prepare", commands={"a": [{"cmd": "prepare"}], "b": []})
        command = journal.pending("a")[0]
        before = journal.snapshot()
        if failure == "records":
            journal._db.execute("CREATE TRIGGER refuse_records BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'injected'); END")
        if failure == "capacity":
            journal.max_pending = 1
        with pytest.raises((JournalError, sqlite3.DatabaseError, RevisionConflict)):
            commit(journal, "5"*32, revision=0 if failure == "revision" else 1, value="commit",
                   commands={"a": [{"cmd": "apply"}], "b": [{"cmd": "apply"}]},
                   acknowledgements=[{"player": "a", "command_id": command["command_id"],
                                      "outcome": "ACK", "receipt": {"schema": "prepared-test"}}])
        assert journal.snapshot() == before
        assert journal.record("native-trade", KEY).value == {"phase": "prepare"}
        assert journal.command("a", command["command_id"])["outcome"] is None
        assert len(journal.pending("a")) == 1 and not journal.pending("b")
        assert journal.event("a", "5"*32, {"event": "record-test", "value": "commit"}) is None
    finally:
        journal.close()


def test_uncertain_commit_and_exact_replay_do_not_duplicate_records(tmp_path):
    journal = open_journal(tmp_path / "run.sqlite3")
    try:
        journal.bootstrap({"active": None})
        real = journal._db
        class FailAfterCommit:
            def __getattr__(self, name):
                return getattr(real, name)
            def commit(self):
                real.commit()
                raise OSError("after commit")
        journal._db = FailAfterCommit()
        with pytest.raises(OSError):
            commit(journal, "4"*32, revision=0, value="commit")
        journal._db = real
        assert journal.record("native-trade", KEY).value["phase"] == "commit"
        receipt = commit(journal, "4"*32, revision=0, value="commit")
        assert receipt.revision == 1
        assert journal._db.execute("SELECT count(*) FROM records").fetchone()[0] == 1
    finally:
        journal.close()


@pytest.mark.parametrize("corruption", ["digest", "marker", "future"])
def test_corrupt_or_unbound_record_cannot_be_read(tmp_path, corruption):
    journal = open_journal(tmp_path / "run.sqlite3")
    try:
        journal.bootstrap({"active": None})
        commit(journal, "4"*32, revision=0, value="offered")
        if corruption == "digest": journal._db.execute("UPDATE records SET digest='bad'")
        elif corruption == "marker": journal._db.execute("DELETE FROM metadata WHERE name='atomic_records'")
        else: journal._db.execute("UPDATE records SET revision=100")
        with pytest.raises(JournalError):
            journal.record("native-trade", KEY)
        with pytest.raises(JournalError):
            journal.record_history("native-trade", KEY)
    finally:
        journal.close()


@pytest.mark.parametrize("change", ["namespace", "key", "value", "duplicate", "unknown", "marker"])
def test_invalid_record_writes_leave_snapshot_and_outbox_untouched(tmp_path, change):
    journal = open_journal(tmp_path / "run.sqlite3")
    try:
        journal.bootstrap({"active": None})
        record = {"namespace": "native-trade", "key": KEY, "value": {"phase": "prepare"}}
        records = [record]
        if change == "namespace": record["namespace"] = "../other"
        elif change == "key": record["key"] = "bad"
        elif change == "value": record["value"] = []
        elif change == "duplicate": records.append(dict(record))
        elif change == "unknown": record["extra"] = True
        else: journal._db.execute("INSERT INTO metadata VALUES ('atomic_records','unreviewed')")
        before = journal.snapshot()
        with pytest.raises(JournalError):
            journal.commit("a", "4"*32, {"event": "test"}, expected_revision=0, state={"active": KEY},
                commands={"a": [{"cmd": "prepare"}], "b": []}, result={"ack": "ACK"}, records=records)
        assert journal.snapshot() == before and not journal.pending("a")
        assert journal._db.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    finally:
        journal.close()


@pytest.mark.parametrize("revision", [-1, 0, 1.5, "invalid", 100])
@pytest.mark.parametrize("hidden_by_newer_record", [False, True])
def test_invalid_committed_revision_is_rejected_even_outside_requested_history(tmp_path, revision, hidden_by_newer_record):
    journal = open_journal(tmp_path / "run.sqlite3")
    try:
        journal.bootstrap({"active": None})
        commit(journal, "4"*32, revision=0, value="offered")
        if hidden_by_newer_record:
            commit(journal, "5"*32, revision=1, value="accepted")
        else:
            journal.commit("a", "5"*32, {"event": "unrelated"}, expected_revision=1,
                state={"active": KEY}, commands={"a": [], "b": []}, result={"ack": "ACK"})
        journal._db.execute("UPDATE records SET revision=? WHERE revision=1", (revision,))
        before = journal.snapshot()
        with pytest.raises(JournalError):
            journal.record("native-trade", KEY)
        for after in (0, 200):
            with pytest.raises(JournalError):
                journal.record_history("native-trade", KEY, after_revision=after, limit=1)
        assert journal.snapshot() == before
    finally:
        journal.close()
