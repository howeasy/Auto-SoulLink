"""Real SQLite reopen, rollback and process-death proofs; no physical ACK is inferred."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from server.protocol_journal import JournalError, ProtocolJournal, RevisionConflict

ROOT = Path(__file__).resolve().parents[2]
RUN = "1" * 32
CONTRACT = "2" * 64
OP = "3" * 32
REQUEST = {"event": "capture", "key": "1234:5678:99", "area_id": "route_1"}
BEFORE = {"links": [], "area_states": {}}
AFTER = {"links": [{"a": "1234:5678:99"}], "area_states": {"route_1": "pending_a"}}
COMMANDS = {"a": [{"cmd": "box_mon", "key": "1234:5678:99"}],
            "b": [{"cmd": "hud_show", "text": "Waiting for a catch é"}]}


def open_journal(path, **kwargs):
    return ProtocolJournal(path, run_id=RUN, contract_hash=CONTRACT, **kwargs)


def commit(journal, **changes):
    arguments = {"expected_revision": 0, "state": AFTER, "commands": COMMANDS, "result": {"ack": "ACK"}}
    arguments.update(changes)
    return journal.commit("a", OP, REQUEST, **arguments)


@pytest.fixture
def journal(tmp_path):
    instance = open_journal(tmp_path / "protocol.sqlite3")
    assert instance.bootstrap(BEFORE).state == BEFORE
    yield instance
    instance.close()


def test_state_event_and_both_outboxes_survive_reopen(tmp_path):
    path = tmp_path / "protocol.sqlite3"
    first = open_journal(path)
    first.bootstrap(BEFORE)
    receipt = commit(first)
    first.close()
    second = open_journal(path)
    try:
        assert second.bootstrap({"wrong": "legacy file"}).state == AFTER
        assert second.snapshot().revision == 1
        assert second.event("a", OP, REQUEST) == receipt
        assert second.pending("a")[0]["key"] == REQUEST["key"]
        assert second.pending("b")[0]["text"] == COMMANDS["b"][0]["text"]
        assert tuple(second.pending(p)[0]["command_id"] for p in ("a", "b")) == receipt.command_ids
        assert second._db.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert second._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        second.close()


def test_duplicate_semantic_operation_replays_without_state_or_command_duplication(journal):
    receipt = commit(journal)
    assert commit(journal, state={"incorrect": "would corrupt state"}) == receipt
    assert journal.snapshot().state == AFTER and journal.snapshot().revision == 1
    assert len(journal.pending("a")) == len(journal.pending("b")) == 1
    with pytest.raises(JournalError, match="reused"):
        journal.event("a", OP, {**REQUEST, "key": "ABCD:5678:99"})
    assert journal.snapshot().state == AFTER


def test_stale_state_revision_cannot_overwrite_another_server_transition(journal):
    commit(journal)
    with pytest.raises(RevisionConflict):
        journal.commit("b", "4" * 32, {"event": "faint"}, expected_revision=0,
                       state=BEFORE, commands={"a": [], "b": []}, result={"ack": "ACK"})
    assert journal.snapshot().state == AFTER
    assert journal.event("b", "4" * 32, {"event": "faint"}) is None


def test_independent_connections_cannot_commit_against_the_same_old_state(tmp_path):
    path = tmp_path / "writers.sqlite3"
    first, second = open_journal(path), open_journal(path)
    try:
        first.bootstrap(BEFORE)
        old_revision = second.snapshot().revision
        commit(first)
        with pytest.raises(RevisionConflict):
            second.commit("b", "4" * 32, {"event": "no_catch"}, expected_revision=old_revision,
                          state=BEFORE, commands={"a": [], "b": []}, result={"ack": "ACK"})
        assert first.snapshot() == second.snapshot()
    finally:
        first.close()
        second.close()


def test_uncertain_return_after_commit_is_resolved_by_lookup_without_reapplying(journal):
    connection = journal._db
    class CommitThenFail:
        def __getattr__(self, name):
            return getattr(connection, name)

        def commit(self):
            connection.commit()
            raise OSError("injected failure after durable commit")
    journal._db = CommitThenFail()
    with pytest.raises(OSError, match="after durable"):
        commit(journal)
    journal._db = connection
    receipt = journal.event("a", OP, REQUEST)
    assert receipt is not None and journal.snapshot().state == AFTER
    assert commit(journal) == receipt
    assert len(journal.pending("a")) == len(journal.pending("b")) == 1


def test_a_consumed_client_nonce_cannot_be_reused_after_restart_or_by_another_player(tmp_path):
    path = tmp_path / "sessions.sqlite3"
    first = open_journal(path)
    first.bootstrap(BEFORE)
    session_id = first.register_session("a", "5" * 32, "6" * 32)
    first.close()
    second = open_journal(path)
    try:
        for player in ("a", "b"):
            with pytest.raises(JournalError, match="already used"):
                second.register_session(player, "5" * 32, "7" * 32)
        assert second.register_session("a", "8" * 32, "7" * 32) != session_id
        assert second.snapshot().state == BEFORE and second.snapshot().revision == 0
        assert not second.pending("a") and not second.pending("b")
    finally:
        second.close()


@pytest.mark.parametrize("table", ["events", "commands"])
def test_a_database_failure_after_state_update_rolls_back_everything(journal, table):
    journal._db.execute(f"CREATE TEMP TRIGGER fail_write BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected write failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        commit(journal)
    assert journal.snapshot().state == BEFORE and journal.snapshot().revision == 0
    assert journal.event("a", OP, REQUEST) is None
    assert journal.pending("a") == journal.pending("b") == []


@pytest.mark.parametrize("phase", ["before_event", "before_command", "before_commit", "after_commit"])
def test_process_death_leaves_either_the_complete_old_or_complete_new_transaction(tmp_path, phase):
    path = tmp_path / "crash.sqlite3"
    initial = open_journal(path)
    initial.bootstrap(BEFORE)
    initial.close()
    code = """
import os,sys
from server.protocol_journal import ProtocolJournal
from tests.unit.test_protocol_journal import RUN,CONTRACT,OP,REQUEST,AFTER,COMMANDS
j=ProtocolJournal(sys.argv[1],run_id=RUN,contract_hash=CONTRACT)
phase=sys.argv[2]
def crash(sql):
    markers={'before_event':'INSERT INTO events','before_command':'INSERT INTO commands','before_commit':'COMMIT'}
    if phase in markers and sql.startswith(markers[phase]): os._exit(71)
j._db.set_trace_callback(crash)
j.commit('a',OP,REQUEST,expected_revision=0,state=AFTER,commands=COMMANDS,result={'ack':'ACK'})
os._exit(72)
"""
    process = subprocess.run([sys.executable, "-c", code, str(path), phase], cwd=ROOT,
                             capture_output=True, text=True, timeout=15)
    assert process.returncode == (72 if phase == "after_commit" else 71), process.stderr
    recovered = open_journal(path)
    try:
        committed = phase == "after_commit"
        assert recovered.snapshot().state == (AFTER if committed else BEFORE)
        assert recovered.snapshot().revision == int(committed)
        assert (recovered.event("a", OP, REQUEST) is not None) == committed
        assert len(recovered.pending("a")) == len(recovered.pending("b")) == int(committed)
    finally:
        recovered.close()


@pytest.mark.parametrize("outcome", ["ACK", "NACK"])
def test_explicit_receipts_are_durable_and_cannot_be_changed_afterward(tmp_path, outcome):
    path = tmp_path / "ack.sqlite3"
    first = open_journal(path)
    first.bootstrap(BEFORE)
    identifier = commit(first).command_ids[0]
    proof = {"validated_by": "unit coordinator", "observed_key": REQUEST["key"], "result": outcome}
    assert first.acknowledge("a", identifier, outcome, proof)
    assert not first.acknowledge("a", identifier, outcome, proof)
    with pytest.raises(JournalError, match="conflicting"):
        first.acknowledge("a", identifier, outcome, {**proof, "observed_key": "other"})
    first.close()
    second = open_journal(path)
    try:
        assert second.pending("a") == [] and len(second.pending("b")) == 1
        assert not second.acknowledge("a", identifier, outcome, proof)
    finally:
        second.close()


def test_wrong_player_unknown_token_and_empty_receipt_cannot_acknowledge_a_command(journal):
    identifier = commit(journal).command_ids[0]
    for player, token, receipt in (("b", identifier, {"proof": "wrong owner"}),
                                    ("a", "0" * 32, {"proof": "unknown"}), ("a", identifier, {})):
        with pytest.raises(JournalError):
            journal.acknowledge(player, token, "ACK", receipt)
    assert len(journal.pending("a")) == 1


def test_reading_or_sending_a_command_never_acknowledges_it(journal):
    commit(journal)
    first = journal.pending("a")
    assert first == journal.pending("a") == journal.pending("a")
    assert journal.snapshot().revision == 1


def test_outbox_bound_refuses_the_whole_transition_before_mutation(tmp_path):
    instance = open_journal(tmp_path / "bounded.sqlite3", max_pending=1)
    try:
        instance.bootstrap(BEFORE)
        with pytest.raises(JournalError, match="outbox is full"):
            commit(instance)
        assert instance.snapshot().state == BEFORE
        assert instance.event("a", OP, REQUEST) is None
        assert instance.pending("a") == instance.pending("b") == []
    finally:
        instance.close()


def test_delivery_bounds_preserve_fifo_and_do_not_skip_an_unacknowledged_head(journal):
    commands = {"a": [{"cmd": "hud_show", "text": str(i) * 700} for i in range(5)], "b": []}
    commit(journal, commands=commands)
    page = journal.pending("a", max_bytes=4600)
    assert [row["text"][0] for row in page] == ["0", "1"]
    assert journal.pending("a", max_bytes=4600) == page
    journal.acknowledge("a", page[0]["command_id"], "ACK", {"validated_by": "UI receipt test"})
    assert [row["text"][0] for row in journal.pending("a", max_bytes=4600)] == ["1", "2"]
    assert len(journal.pending("a", limit=1)) == 1


@pytest.mark.parametrize("value", [{"bad": float("nan")}, {"bad": 2**53}, {1: "not a string key"},
                                  {"bad": "\ud800"}, {"bad": (1, 2)}, {"bad": "x" * (1024 * 1024 + 1)}])
def test_invalid_json_never_changes_state_or_outboxes(journal, value):
    with pytest.raises(JournalError):
        commit(journal, state=value)
    assert journal.snapshot().state == BEFORE
    assert journal.pending("a") == []


def test_state_corruption_requires_recovery_and_is_never_treated_as_empty(journal):
    journal._db.execute("UPDATE snapshot SET body=?", (json.dumps({"wrong": "state"}),))
    with pytest.raises(JournalError, match="checksum"):
        journal.snapshot()
    with pytest.raises(JournalError, match="checksum"):
        commit(journal)


def test_database_binding_cannot_cross_runs_or_contracts(tmp_path):
    path = tmp_path / "bound.sqlite3"
    first = open_journal(path)
    first.bootstrap(BEFORE)
    first.close()
    for run_id, contract_hash in (("4" * 32, CONTRACT), (RUN, "5" * 64)):
        with pytest.raises(JournalError, match="different run"):
            ProtocolJournal(path, run_id=run_id, contract_hash=contract_hash)
    good = open_journal(path)
    assert good.snapshot().state == BEFORE
    good.close()


def test_unrelated_database_is_not_migrated_or_overwritten(tmp_path):
    path = tmp_path / "other.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE user_data(value TEXT)")
        db.execute("INSERT INTO user_data VALUES ('preserve')")
    original = path.read_bytes()
    with pytest.raises(JournalError, match="unsupported"):
        open_journal(path)
    assert path.read_bytes() == original
