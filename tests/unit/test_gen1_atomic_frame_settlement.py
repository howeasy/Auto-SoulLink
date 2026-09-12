"""Compound source/inventory settlement uses one actual journal transaction."""

import copy
import secrets
import sqlite3

import pytest

from server.execution_window import SCHEMA, VerifiedExecutionWindow
from server.frame_progress import RECEIPT
from server.gen1_frame_journal import enroll, grant, returned, verify_journal
from server.gen1_frame_runtime import COMPONENT, verified_held_frame
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import digest
from server.protocol_journal import JournalError
from server.state import LinkStatus
from tests.unit.test_gen1_frame_journal import setup
from tests.unit.test_gen1_faint_runtime import signal_batch
from tests.unit.test_gen1_starter_settlement import source_and_checkpoint
from tests.unit.test_gen1_sessions import contract


def window(runtime, player, frames=20):
    document = runtime.state().document()
    operation = secrets.token_hex(16)
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    evidence = {"schema": "explicit-unit-frame-policy"}
    scope = {
        "operation_id": operation,
        "operation_digest": digest({"event": "frame_grant", "evidence": evidence}),
        "context_generation": binding["context_generation"],
        "binding_digest": binding["binding_digest"],
        "phase": "ordinary",
    }
    proof = VerifiedExecutionWindow(scope, digest(evidence), frames, 1000, digest(document))
    request = {
        "event": "frame_grant",
        "evidence": evidence,
        "window": {"schema": SCHEMA, "challenge": operation, "scope": scope},
    }
    grant(runtime, player, operation, request, proof)


def frame(runtime, player, inventory, engine):
    pending = runtime.state().document()["components"][COMPONENT][player]["ledger"]["pending"]
    bundle = {"inventory": inventory, "engine_signals": engine}
    return {
        "event": "frame_complete",
        "bundle": bundle,
        "receipt": {
            "schema": RECEIPT,
            "sequence": pending["sequence"],
            "scope": pending["scope"],
            "before": pending["before"],
            "after": inventory["frame"],
            "steps": inventory["frame"] - pending["before"],
            "observations_digest": digest(bundle),
        },
    }


def starters(runtime):
    setup(runtime)
    for player in ("a", "b"):
        enroll(runtime, player, secrets.token_hex(16))
    for player in ("a", "b"):
        initial = runtime.state().document()["components"]["gen1-initial-observations"][player]
        source, checkpoint = source_and_checkpoint(
            runtime, player, initial["observation"], initial["operation_id"]
        )
        window(runtime, player)
        message = frame(runtime, player, checkpoint["observation"], source)
        returned(runtime, player, secrets.token_hex(16), message, settle_observations=True)


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_starter_sources_inventory_and_identity_close_in_one_frame_commit(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        starters(runtime)
        stage = runtime.state()
        assert len(stage.rules.links) == 1 and stage.rules.links[0].status == LinkStatus.ALIVE
        for player in ("a", "b"):
            assert verified_held_frame(stage.document(), player, 110)
            entry = stage.document()["components"]["gen1-inventory-observations"][player]
            source = stage.document()["components"]["gen1-engine-signals"][player]
            assert entry["operation_id"] == source["operation_id"]
            event = runtime.journal.event_snapshot(player, entry["operation_id"])
            assert event.request["event"] == "frame_complete"
            assert event.result["observations_settled"] and event.result[
                "inventory_transition_digest"
            ] == digest(entry)
        assert runtime.state().barrier.ticket() is None  # No general execution permission inferred.
        window(
            runtime, "a"
        )  # Closed settlement, rather than only a receipt, allows a next private grant.
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert len(runtime.state().rules.links) == 1
        verify_journal(runtime, runtime.state().document())
    finally:
        runtime.close()


def test_faint_and_same_frame_inventory_publish_peer_command_atomically(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(runtime)
        window(runtime, "a")
        signal = signal_batch(runtime, "a")
        inventory = copy.deepcopy(
            runtime.state().document()["components"]["gen1-inventory-observations"]["a"][
                "observation"
            ]
        )
        inventory["frame"] = 122
        inventory["source"]["fields"]["party"] = signal["signals"][-1]["point"]["party_hex"]
        message = frame(runtime, "a", inventory, signal)
        operation = secrets.token_hex(16)
        returned(runtime, "a", operation, message, settle_observations=True)
        assert runtime.state().rules.links[0].status == LinkStatus.DEAD
        pending = runtime.journal.pending("b")
        assert len(pending) == 1 and pending[0]["cmd"] == "force_faint"
        assert runtime.journal.event_snapshot("a", operation).command_ids == (
            pending[0]["command_id"],
        )
        assert verified_held_frame(runtime.state().document(), "a", 122)
    finally:
        runtime.close()


def test_inventory_failure_rolls_back_source_rule_and_command_proposals(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(runtime)
        window(runtime, "a")
        signal = signal_batch(runtime, "a")
        inventory = copy.deepcopy(
            runtime.state().document()["components"]["gen1-inventory-observations"]["a"][
                "observation"
            ]
        )
        inventory["frame"] = 122
        inventory["source"]["fields"]["party"] = signal["signals"][-1]["point"]["party_hex"]
        from server import gen1_inventory_observation as inventory_module

        actual = inventory_module.stage_observation

        def refuse_after_staging(*args, **kwargs):
            result = actual(*args, **kwargs)
            assert args[1].rules.links[0].status == LinkStatus.DEAD
            assert result["entry"]["transition"]["party_hp_zero"]
            raise JournalError("injected inventory validation failure after source staging")

        monkeypatch.setattr(inventory_module, "stage_observation", refuse_after_staging)
        message = frame(runtime, "a", inventory, signal)
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            returned(runtime, "a", secrets.token_hex(16), message, settle_observations=True)
        assert runtime.journal.snapshot() == before and not runtime.journal.pending_ids("b")
        assert runtime.state().rules.links[0].status == LinkStatus.ALIVE
    finally:
        runtime.close()


def test_sql_failure_rolls_back_frame_sources_inventory_and_commands_together(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(runtime)
        window(runtime, "a")
        signal = signal_batch(runtime, "a")
        inventory = copy.deepcopy(
            runtime.state().document()["components"]["gen1-inventory-observations"]["a"][
                "observation"
            ]
        )
        inventory["frame"] = 122
        inventory["source"]["fields"]["party"] = signal["signals"][-1]["point"]["party_hex"]
        message = frame(runtime, "a", inventory, signal)
        before = runtime.journal.snapshot()
        runtime.journal._db.execute(
            "CREATE TRIGGER fail_frame_sources BEFORE INSERT ON commands BEGIN SELECT RAISE(ABORT,'fixture'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            returned(runtime, "a", secrets.token_hex(16), message, settle_observations=True)
        assert runtime.journal.snapshot() == before and not runtime.journal.pending_ids("b")
    finally:
        runtime.close()
