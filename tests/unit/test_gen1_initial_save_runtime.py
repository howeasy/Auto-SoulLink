"""Real initial-save journal lifecycle with explicit synthetic physical/file proofs."""

import copy
import hashlib
import secrets
import sqlite3
from itertools import product

import pytest

from server.gen1_held_faint import verify
from server.gen1_initial_save_runtime import COMPONENT, original_command, prepared, record_key
from server.gen1_run_config import create_runtime, open_runtime
from server.held_write_permit import VerifiedHeldWrite
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_bootstrap_runtime import deliver, enroll, receipt
from tests.unit.test_gen1_held_faint import checkpoint
from tests.unit.test_gen1_initial_observation import admit
from tests.unit.test_gen1_sessions import contract


def setup(runtime):
    instant = runtime.clock()
    runtime.clock = lambda: instant
    enrolled = {p: enroll(runtime, p) for p in ("a", "b")}
    for player, (owner, initial) in enrolled.items():
        deliver(runtime, player, owner, receipt(runtime, player, initial))
    return {p: owner for p, (owner, _) in enrolled.items()}


def acknowledgement(runtime, player):
    document = runtime.state().document()
    entry = document["components"][COMPONENT][player]
    command = original_command(runtime.journal, player, entry)
    value = prepared(document, player)
    image = bytes.fromhex(value["after"]["cart_hex"])
    proof = {
        "schema": "rby-initial-save-receipt-v1",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "body_digest": digest(command["body"]),
        "context_generation": value["context_generation"],
        "final_sha1": value["final_sha1"],
        "before_digest": digest(value["before"]),
        "after": value["after"],
        "file": {
            "schema": "slink-saveram-file-v1",
            "path": f"synthetic/{player}/SaveRAM/game.sav",
            "sha256": hashlib.sha256(image).hexdigest(),
            "byte_length": len(image),
            "host_profile": "bizhawk-2.11.1-gambatte-exclusive-hold-v1",
            "frame": value["frame"],
            "flushed": True,
            "readback": True,
        },
    }
    return {
        "event": "command_ack",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "outcome": "ACK",
        "receipt": proof,
    }


def send_ack(runtime, player, owner, message, operation=None):
    session = runtime.gate.sessions[player]
    return runtime.process(
        {
            "protocol": runtime.protocol,
            "player": player,
            "session_id": session.session_id,
            "admission_epoch": runtime.gate.epoch,
            "seq": session.last_seq + 1,
            "operation_id": operation or secrets.token_hex(16),
            **message,
        },
        owner,
    )


def complete_initial_save(runtime, player, owner):
    """Fixture only: acknowledge a pending save with a synthetic exact file proof."""
    return send_ack(runtime, player, owner, acknowledgement(runtime, player))


def evidence(runtime, player, phase="initial_save"):
    document = runtime.state().document()
    entry = document["components"][COMPONENT][player]
    command = original_command(runtime.journal, player, entry)
    initial = document["components"]["gen1-initial-observations"][player]
    value = prepared(document, player)
    point = value["after" if phase == "initial_save_flush" else "before"]
    return command, {
        "schema": "rby-held-initial-save-evidence-v1",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "context_generation": value["context_generation"],
        "final_sha1": value["final_sha1"],
        "host": {**initial["observation"]["host"], "frame": value["frame"]},
        "checkpoint": checkpoint(point["variant"]),
        "current": copy.deepcopy(point),
        "phase": phase,
        "intent": {"schema": "rby-initial-save-intent-v1", "body_digest": digest(command["body"])},
    }


@pytest.mark.parametrize("variants", list(product(("red", "blue", "yellow"), repeat=2)))
def test_exact_initial_save_completes_once_without_releasing_any_hold(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        owners = setup(runtime)
        holds = runtime.state().barrier.document()["blockers"]
        for player in ("a", "b"):
            message = acknowledgement(runtime, player)
            operation = secrets.token_hex(16)
            send_ack(runtime, player, owners[player], message, operation)
            saved = runtime.journal.snapshot()
            send_ack(runtime, player, owners[player], message, operation)
            assert runtime.journal.snapshot() == saved
            assert not runtime.journal.pending_ids(player)
        assert runtime.state().barrier.document()["blockers"] == holds
        assert runtime.state().barrier.ticket() is None
        assert not runtime.state().document()["rules"]["core"]["links"]
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert all(
            row["receipt_operation"]
            for row in runtime.state().document()["components"][COMPONENT].values()
        )
    finally:
        runtime.close()


@pytest.mark.parametrize("first", ["a", "b"])
def test_early_bootstrap_defers_save_until_peer_initial_observation(tmp_path, first):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owner, initial = enroll(runtime, first)
        deliver(runtime, first, owner, receipt(runtime, first, initial))
        assert COMPONENT not in runtime.state().document()["components"]
        assert not any(runtime.journal.pending_ids(p) for p in ("a", "b"))
        peer = "b" if first == "a" else "a"
        peer_owner, peer_initial = enroll(runtime, peer)
        entry = runtime.state().document()["components"][COMPONENT][first]
        assert entry["origin"]["player"] == peer
        assert (
            entry["origin"]["operation_id"]
            == runtime.state().document()["components"]["gen1-initial-observations"][peer][
                "operation_id"
            ]
        )
        assert len(runtime.journal.pending_ids(first)) == 1 and not runtime.journal.pending_ids(
            peer
        )
        deliver(runtime, peer, peer_owner, receipt(runtime, peer, peer_initial))
        complete_initial_save(runtime, first, owner)
        complete_initial_save(runtime, peer, peer_owner)
    finally:
        runtime.close()


@pytest.mark.parametrize("phase", ["initial_save", "initial_save_repair", "initial_save_flush"])
def test_current_owned_command_gets_only_a_fixed_frame_single_use_write_permit(tmp_path, phase):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        command, value = evidence(runtime, "a", phase)
        if phase == "initial_save_repair":
            delta = command["body"]["payload"]["changes"]["cart"]
            run = delta["runs"][0]
            raw = bytearray.fromhex(value["current"]["cart_hex"])
            raw[run["offset"]] = bytes.fromhex(run["after"])[0]
            value["current"]["cart_hex"] = raw.hex().upper()
        proof = verify(
            "a",
            command,
            value,
            runtime.state().document(),
            runtime.gate.sessions["a"].metadata["control_binding"],
        )
        assert isinstance(proof, VerifiedHeldWrite) and proof.scope["phase"] == phase
        assert not hasattr(proof, "frames") and runtime.state().barrier.ticket() is None
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["frame", "host", "context", "phase", "preimage", "body"])
def test_changed_physical_or_command_scope_refuses_initial_write(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        command, value = evidence(runtime, "a")
        if fault == "frame":
            value["host"]["frame"] += 1
        elif fault == "host":
            value["host"]["owner_id"] = "f" * 32
        elif fault == "context":
            value["context_generation"] = "f" * 32
        elif fault == "phase":
            value["phase"] = "memorial_save"
        elif fault == "preimage":
            value["current"]["cart_hex"] = "00" + value["current"]["cart_hex"][2:]
        else:
            command["body"]["payload"]["before_digest"] = "0" * 64
        with pytest.raises(JournalError):
            verify(
                "a",
                command,
                value,
                runtime.state().document(),
                runtime.gate.sessions["a"].metadata["control_binding"],
            )
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["file", "after", "sequence", "context"])
def test_invalid_file_or_poststate_leaves_initial_save_pending(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("red", "yellow"))
    try:
        owners = setup(runtime)
        message = acknowledgement(runtime, "a")
        if fault == "file":
            message["receipt"]["file"]["sha256"] = "0" * 64
        elif fault == "after":
            message["receipt"]["after"]["save_status"] = 0
        elif fault == "sequence":
            message["command_sequence"] += 1
        else:
            message["receipt"]["context_generation"] = "f" * 32
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            send_ack(runtime, "a", owners["a"], message)
        assert runtime.journal.snapshot() == before and runtime.journal.pending_ids("a")
    finally:
        runtime.close()


def test_same_core_reconnect_preserves_initial_save_command_and_file_completion(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = setup(runtime)
        command, value = evidence(runtime, "a")
        old = runtime.gate.sessions["a"].metadata["control_binding"]
        runtime.disconnect("a", owners["a"])
        owner = admit(runtime, "a")
        assert runtime.gate.sessions["a"].metadata["control_binding"] != old
        assert isinstance(
            verify(
                "a",
                command,
                value,
                runtime.state().document(),
                runtime.gate.sessions["a"].metadata["control_binding"],
            ),
            VerifiedHeldWrite,
        )
        complete_initial_save(runtime, "a", owner)
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["record", "origin", "receipt_event"])
def test_missing_lifecycle_provenance_refuses_restore(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = setup(runtime)
        complete_initial_save(runtime, "a", owners["a"])
        entry = runtime.state().document()["components"][COMPONENT]["a"]
        if fault == "record":
            runtime.journal._db.execute(
                "DELETE FROM records WHERE namespace=? AND record_key=?",
                (COMPONENT, record_key("a")),
            )
        elif fault == "origin":
            runtime.journal._db.execute(
                "UPDATE events SET request_digest=? WHERE player=? AND operation_id=?",
                ("0" * 64, entry["origin"]["player"], entry["origin"]["operation_id"]),
            )
        else:
            runtime.journal._db.execute(
                "DELETE FROM events WHERE player=? AND operation_id=?",
                ("a", entry["receipt_operation"]),
            )
        with pytest.raises(JournalError):
            runtime.state()
    finally:
        runtime.close()


def test_sql_failure_rolls_back_image_receipt_and_ack_together(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = setup(runtime)
        before = runtime.journal.snapshot()
        runtime.journal._db.execute(
            "CREATE TRIGGER fail_initial_save BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'fixture'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            complete_initial_save(runtime, "a", owners["a"])
        assert runtime.journal.snapshot() == before
        assert runtime.journal.pending_ids("a")
        runtime.journal._db.execute("DROP TRIGGER fail_initial_save")
        runtime.close()
        runtime = open_runtime(tmp_path)
        owner = admit(runtime, "a")
        complete_initial_save(runtime, "a", owner)
        assert not runtime.journal.pending_ids("a")
    finally:
        runtime.close()
