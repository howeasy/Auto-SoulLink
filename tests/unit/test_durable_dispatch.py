import sqlite3

import pytest

from server.durable_dispatch import DurableDispatcher
from server.gen1_staged_state import StagedGen1State
from server.protocol import SessionGate
from server.protocol_journal import JournalError, ProtocolJournal
from server.state import LinkStatus
from tests.unit.test_gen1_staged_state import A, B, populated


def validator(player, event, state):
    if event.get("event") != "faint" or event.get("key") not in (A, B):
        raise JournalError("test event policy refused")


def receipt_validator(player, command, event, state):
    if (player != "b" or command["body"].get("cmd") != "force_faint" or event.get("outcome") != "ACK"
            or event.get("receipt") != {"key": B, "party_hp": 0}):
        raise JournalError("physical readback differs")
    return [{"event": "faint", "key": B}]


def setup(tmp_path):
    journal = ProtocolJournal(tmp_path / "journal.sqlite3", contract_hash="a" * 64)
    journal.bootstrap(StagedGen1State.from_live(populated(tmp_path), {"retired_pairs": []}).document())
    dispatcher = DurableDispatcher(journal, data_dir=tmp_path, staged_type=StagedGen1State,
                                   validate_event=validator, validate_receipt=receipt_validator)
    return journal, dispatcher


def test_rule_transition_and_cross_player_commands_are_durable_and_replay_once(tmp_path):
    journal, dispatcher = setup(tmp_path)
    try:
        operation = "1" * 32
        event = {"event": "faint", "key": A}
        result = dispatcher.dispatch("a", operation, event)
        assert result.revision == 1 and result.replayed is False
        assert dispatcher.state().links[0].status == LinkStatus.DEAD
        pending = journal.pending("b")
        assert any(command["cmd"] == "force_faint" and command["key"] == B for command in pending)
        dispatcher.validate_event = lambda *_: pytest.fail("retry repeated the rule transition")
        replay = dispatcher.dispatch("a", operation, event)
        assert replay.replayed and replay.revision == 1 and journal.pending("b") == pending
        assert not (tmp_path / "links.json").exists()
    finally:
        journal.close()


def test_rule_exception_or_sql_failure_exposes_neither_partial_state_nor_commands(tmp_path):
    journal, dispatcher = setup(tmp_path)
    try:
        before = journal.snapshot()
        def reject_after_mutating_clone(player, event, state):
            state.links[0].a.nickname = "changed clone"
            state.queued_commands["b"].append({"cmd": "force_faint", "key": B})
            raise ValueError("injected rule error")
        dispatcher.validate_event = reject_after_mutating_clone
        with pytest.raises(ValueError, match="injected"):
            dispatcher.dispatch("a", "1" * 32, {"event": "faint", "key": A})
        assert journal.snapshot() == before and not journal.pending("b")
        dispatcher.validate_event = validator
        journal._db.execute("CREATE TEMP TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected');END")
        with pytest.raises(sqlite3.IntegrityError):
            dispatcher.dispatch("a", "1" * 32, {"event": "faint", "key": A})
        assert journal.snapshot() == before and not journal.pending("b")
    finally:
        journal.close()


def test_command_receipt_and_followup_state_are_one_atomic_transition(tmp_path):
    journal, dispatcher = setup(tmp_path)
    try:
        dispatcher.dispatch("a", "1" * 32, {"event": "faint", "key": A})
        command = next(c for c in journal.pending("b") if c["cmd"] == "force_faint")
        event = {"event": "command_ack", "command_id": command["command_id"],
                 "command_sequence": command["command_sequence"], "outcome": "ACK", "receipt": {"key": B, "party_hp": 0}}
        bad = {**event, "receipt": {"key": B, "party_hp": 1}}
        with pytest.raises(JournalError, match="physical"):
            dispatcher.dispatch("b", "2" * 32, bad)
        assert journal.command("b", command["command_id"])["outcome"] is None
        journal._db.execute("CREATE TEMP TRIGGER fail_receipt BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected');END")
        with pytest.raises(sqlite3.IntegrityError):
            dispatcher.dispatch("b", "2" * 32, event)
        assert journal.command("b", command["command_id"])["outcome"] is None
        assert journal.snapshot().revision == 1
        journal._db.execute("DROP TRIGGER fail_receipt")
        dispatcher.dispatch("b", "2" * 32, event)
        assert journal.command("b", command["command_id"])["outcome"] == "ACK"
        assert journal.snapshot().revision == 2
        assert dispatcher.dispatch("b", "2" * 32, event).replayed
        assert journal.snapshot().revision == 2
    finally:
        journal.close()


def test_v2_operation_survives_new_session_and_server_restart_without_repeating_rules(tmp_path):
    journal, dispatcher = setup(tmp_path)
    def gate_for(journal):
        return SessionGate(protocol="test-durable-v2", hello_validator=lambda *args: {"game": "test"},
                           durable_ids=True, nonce_registry=journal.register_session)
    def hello(gate, nonce):
        owner = object()
        gate.admit({}, "a", {"event": "hello", "player": "a", "protocol": "test-durable-v2",
                   "client_nonce": nonce, "operation_id": nonce, "seq": 0}, owner)
        return owner
    def envelope(gate, sequence):
        return {"event": "faint", "key": A, "player": "a", "protocol": "test-durable-v2",
                "admission_epoch": gate.epoch, "session_id": gate.sessions["a"].session_id,
                "seq": sequence, "operation_id": "f" * 32}
    first_gate = gate_for(journal)
    owner = hello(first_gate, "1" * 32)
    request = envelope(first_gate, 1)
    first_gate.accept("a", request, owner)
    dispatcher.dispatch("a", request["operation_id"], {"event": "faint", "key": A})
    old_epoch, run_id = first_gate.epoch, journal.run_id
    journal.close()
    journal, dispatcher = setup(tmp_path)
    try:
        assert journal.run_id == run_id
        second_gate = gate_for(journal)
        owner = hello(second_gate, "2" * 32)
        retry = envelope(second_gate, 1)
        assert second_gate.epoch != old_epoch and retry["operation_id"] == request["operation_id"]
        second_gate.accept("a", retry, owner)
        assert dispatcher.dispatch("a", retry["operation_id"], {"event": "faint", "key": A}).replayed
        assert journal.snapshot().revision == 1
        with pytest.raises(JournalError, match="already used"):
            hello(second_gate, "1" * 32)
    finally:
        journal.close()
