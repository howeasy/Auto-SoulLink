"""Within-read validation reuse never becomes a mutable state or authority cache."""

import copy

import pytest

from server import gen1_initial_observation, gen1_inventory_observation
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol_journal import JournalError, _encode
from tests.unit.test_gen1_initial_save_runtime import setup
from tests.unit.test_gen1_sessions import contract


def test_validation_view_is_detached_and_mutation_fails_closed(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        stage = runtime.state()
        before = stage.document()
        stage._begin_validation_document()
        shared = stage.document()
        assert shared is stage.document() and shared is not before
        shared["schema"] = "forged"
        with pytest.raises(JournalError, match="mutated its detached state view"):
            stage._end_validation_document()
        assert stage.document() == before
        assert stage.document() is not stage.document()

        stage._begin_validation_document()
        stage.component["schema"] = "forged"
        with pytest.raises(JournalError, match="mutated its detached state view"):
            stage._end_validation_document()
        assert runtime.state().document() == before
    finally:
        runtime.close()


def test_journal_validator_cannot_mutate_shared_view_or_publish_authority(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("red", "blue"), free_service=True)
    try:
        original = gen1_inventory_observation.verify_journal
        revision = runtime.journal.snapshot().revision
        observed = []

        def mutating(journal, stage):
            original(journal, stage)
            observed.append(stage)
            stage.document()["components"]["gen1-runtime"]["schema"] = "forged"

        with monkeypatch.context() as patch:
            patch.setattr(gen1_inventory_observation, "verify_journal", mutating)
            with pytest.raises(JournalError, match="mutated its detached state view"):
                runtime.state()
        assert observed and observed[0]._validation_document is None
        assert runtime.journal.snapshot().revision == revision
        assert runtime.state().document()["components"]["gen1-runtime"]["schema"] != "forged"
    finally:
        runtime.close()


def test_failed_restore_discards_its_partial_validation_view(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("red", "blue"), free_service=True)
    try:
        original = gen1_initial_observation.verify_state
        observed = []

        def failing(stage):
            original(stage)
            observed.append(stage)
            raise JournalError("injected restore failure")

        with monkeypatch.context() as patch:
            patch.setattr(gen1_initial_observation, "verify_state", failing)
            with pytest.raises(JournalError, match="injected restore failure"):
                runtime.state()
        assert observed and observed[0]._validation_document is None
        assert runtime.state().document()["schema"] != "forged"
    finally:
        runtime.close()


def test_corrupt_observation_source_still_refuses_exact_state_read(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        setup(runtime)
        snapshot = runtime.journal.snapshot()
        changed = copy.deepcopy(snapshot.state)
        changed["components"]["gen1-initial-observations"]["a"]["observation"]["source"]["fields"]["party"] = "00"
        body, checksum = _encode(changed)
        runtime.journal._db.execute("UPDATE snapshot SET body=?,digest=? WHERE singleton=1", (body, checksum))
        with pytest.raises(JournalError):
            runtime.state()
    finally:
        runtime.close()


def test_reopen_starts_a_fresh_fully_audited_validation_view(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"), free_service=True)
    before = runtime.state().document()
    runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        stage = reopened.state()
        assert stage.document()["components"]["gen1-runtime"]["schema"] == before["components"]["gen1-runtime"]["schema"]
        assert getattr(stage, "_validation_document", None) is None
    finally:
        reopened.close()
