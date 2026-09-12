"""Semantic evidence resolves to its containing event: an observation batch or a native handoff."""

import copy
import secrets

import pytest

from server import gen1_engine_signal_runtime as engine
from server.event_reference import make
from server.gen1_observation_provenance import observation_bundle, semantic_receipt, stage_origin
from server.gen1_run_config import create_runtime
from server.protocol import digest
from server.protocol_journal import EventReceipt, JournalError
from tests.unit.observation_fixture import ledger, observe, setup
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_starter_settlement import source_and_checkpoint


def starter(runtime, player="a"):
    initial = runtime.state().document()["components"]["gen1-initial-observations"][player]
    return source_and_checkpoint(runtime, player, initial["observation"], initial["operation_id"])


@pytest.fixture
def batched(tmp_path):
    """One observation batch carrying a starter source and its checkpoint for player a."""
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        source, stable = starter(runtime)
        operation, request, result = observe(runtime, "a", inventory=stable["observation"], signals=source)
        yield runtime, operation, request, result
    finally:
        runtime.close()


def entries(runtime):
    components = runtime.state().document()["components"]
    return components["gen1-engine-signals"]["a"], components["gen1-inventory-observations"]["a"]


def test_batched_semantics_resolve_the_outer_observation_revision_and_digests(batched):
    runtime, operation, request, result = batched
    outer = runtime.journal.event_snapshot("a", operation)
    engine_entry, inventory_entry = entries(runtime)
    assert engine_entry["operation_id"] == inventory_entry["operation_id"] == operation
    assert "frame_origin" not in engine_entry and "frame_origin" not in inventory_entry
    for entry, kind, field in [
        (engine_entry, "engine_signals", "engine_evidence_digest"),
        (inventory_entry, "inventory_observation", "inventory_transition_digest"),
    ]:
        view = semantic_receipt(runtime.journal, "a", entry, kind)
        expected = EventReceipt(outer.revision, {"ack": "ACK", field: digest(entry), "ordinary_execution": False},
                                outer.command_ids)
        assert view == expected and result[field] == digest(entry)


@pytest.mark.parametrize("fault", ["changed-entry", "changed-observation", "foreign-player"])
def test_outer_observation_must_contain_the_exact_semantic_evidence(batched, fault):
    runtime, operation, request, _ = batched
    engine_entry, inventory_entry = entries(runtime)
    if fault == "foreign-player":
        assert semantic_receipt(runtime.journal, "b", engine_entry, "engine_signals") is None
        return
    if fault == "changed-entry":
        entry, kind = engine_entry, "engine_signals"
        entry["transactions"] = [{"forged": True}]
    else:
        entry, kind = copy.deepcopy(inventory_entry), "inventory_observation"
        entry["observation"]["frame"] += 1
    with pytest.raises(JournalError, match="free-run observation differs"):
        semantic_receipt(runtime.journal, "a", entry, kind)


def test_standalone_receipt_lookup_keeps_legacy_replay_semantics(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        source, _ = starter(runtime)
        stage = runtime.state()
        document = stage.document()
        operation = secrets.token_hex(16)
        value = engine.stage_observation(runtime, stage, document, "a", operation,
                                         {"event": "engine_signals", "payload": source})
        semantic = {"event": "engine_signals", "payload": value["entry"]["payload"]}
        expected = runtime.journal.commit("a", operation, semantic, expected_revision=stage.journal_revision,
                                          state=document, commands=value["commands"], result=value["result"])
        assert semantic_receipt(runtime.journal, "a", value["entry"], "engine_signals") == expected
        with pytest.raises(JournalError, match="reused"):
            runtime.journal.event("a", operation, {"event": "changed"})
    finally:
        runtime.close()


def test_frame_accounted_player_needs_a_native_handoff_origin(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        ledger(runtime)
        source, stable = starter(runtime)
        stage = runtime.state()
        document = stage.document()
        request = {"event": "engine_signals", "payload": source}
        with pytest.raises(JournalError, match="compound frame origin"):
            engine.stage_observation(runtime, stage, document, "a", secrets.token_hex(16), request)
        with pytest.raises(JournalError, match="frame-accounted player"):
            observe(runtime, "a", signals=source, frame=105)
        operation = secrets.token_hex(16)
        outer = {"event": "observation", "signals": source}
        with pytest.raises(JournalError, match="native frame handoff event required"):
            stage_origin(document, "a", operation, request, frame_origin=make("a", operation, outer), frame_request=outer)
        handoff = {"event": "native_frame_handoff", "payload": {
            "schema": "rby-native-frame-return-v1", "inventory": stable["observation"],
            "host": {"frame": stable["observation"]["frame"]}, "native_checkpoint": {"party": {}}}}
        bundle = observation_bundle(handoff)
        assert bundle["inventory"] == stable["observation"] and bundle["engine_signals"] is None
        handoff["payload"]["host"]["frame"] += 1
        with pytest.raises(JournalError, match="held source checkpoint"):
            observation_bundle(handoff)
    finally:
        runtime.close()
