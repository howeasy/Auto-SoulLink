"""An observation never commits after its installed decoder inputs change."""

import copy
import secrets

import pytest

from server import gen1_initial_observation, gen1_observation_runtime
from server.gen1_initial_save_runtime import (
    COMPONENT as INITIAL_SAVE,
    record_key as initial_save_key,
)
from server.gen1_run_config import create_runtime
from server.protocol_journal import JournalError, _encode
from tests.unit.test_gen1_initial_save_runtime import setup
from tests.unit.test_gen1_observation_runtime import batch, checkpoint, enrolled
from tests.unit.test_gen1_sessions import contract


def test_dependency_change_after_staging_refuses_before_any_commit(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        _, initial, _ = enrolled(runtime, "a")
        request = batch(runtime, "a", 1, frame=130, inventory=checkpoint(initial, 130))
        before = runtime.journal.snapshot()
        pending = {p: runtime.journal.pending_ids(p) for p in ("a", "b")}
        original_dependencies = gen1_initial_observation.inventory_dependencies
        original_stage = gen1_observation_runtime.stage_observation
        current = {"version": 0}

        def dependencies():
            return {**copy.deepcopy(original_dependencies()), "test_version": current["version"]}

        def stage_then_change(*args, **kwargs):
            staged = original_stage(*args, **kwargs)
            current["version"] = 1
            return staged

        with monkeypatch.context() as patch:
            patch.setattr(gen1_initial_observation, "inventory_dependencies", dependencies)
            patch.setattr(gen1_observation_runtime, "stage_observation", stage_then_change)
            with pytest.raises(JournalError, match="dependencies changed before commit"):
                gen1_observation_runtime.record(runtime, "a", secrets.token_hex(16), request)
            assert gen1_initial_observation.scoped_inventory_dependencies()["test_version"] == 1
        assert runtime.journal.snapshot() == before
        assert {p: runtime.journal.pending_ids(p) for p in ("a", "b")} == pending
    finally:
        runtime.close()


def test_replay_returns_exact_committed_result_without_a_stale_scope(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("red", "blue"), free_service=True)
    try:
        _, initial, _ = enrolled(runtime, "a")
        request = batch(runtime, "a", 1, frame=130, inventory=checkpoint(initial, 130))
        operation = secrets.token_hex(16)
        first = gen1_observation_runtime.record(runtime, "a", operation, request)
        snapshot = runtime.journal.snapshot()
        with monkeypatch.context() as patch:
            patch.setattr(gen1_initial_observation, "inventory_dependencies",
                          lambda: (_ for _ in ()).throw(AssertionError("replay consulted decoder scope")))
            assert gen1_observation_runtime.record(runtime, "a", operation, request) == first
        assert runtime.journal.snapshot() == snapshot
        assert gen1_initial_observation.scoped_inventory_dependencies() == gen1_initial_observation.inventory_dependencies()
    finally:
        runtime.close()


def test_dependency_scope_returns_detached_values_and_refuses_nesting():
    with gen1_initial_observation.inventory_dependency_scope():
        one = gen1_initial_observation.scoped_inventory_dependencies()
        one["layouts"]["yellow"] = "caller mutated copy"
        assert gen1_initial_observation.scoped_inventory_dependencies()["layouts"]["yellow"] != "caller mutated copy"
        with pytest.raises(JournalError, match="nested"):
            with gen1_initial_observation.inventory_dependency_scope():
                pass
    assert gen1_initial_observation.scoped_inventory_dependencies() == gen1_initial_observation.inventory_dependencies()


def test_valid_same_revision_record_swap_cannot_authorize_gen1_state(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        setup(runtime)
        journal = runtime.journal
        snapshot = journal.snapshot()
        key = initial_save_key("a")
        original = journal.record(INITIAL_SAVE, key)
        forged = copy.deepcopy(original.value)
        # Both operations are well-shaped, committed enrollment origins; only
        # the atomic record is substituted, never the unchanged aggregate.
        origin_player = forged["origin"]["player"]
        alternatives = [snapshot.state["components"]["gen1-initial-observations"][origin_player]["operation_id"],
                        snapshot.state["components"]["gen1-new-game-bootstrap"][origin_player]["operation_id"]]
        forged["origin"]["operation_id"] = next(value for value in alternatives
                                                  if value != forged["origin"]["operation_id"])
        body, checksum = _encode(forged)
        journal._db.execute("UPDATE records SET body=?,digest=? WHERE namespace=? AND record_key=?",
                            (body, checksum, INITIAL_SAVE, key))
        assert journal.snapshot() == snapshot and journal.record(INITIAL_SAVE, key).revision == original.revision
        assert journal.record(INITIAL_SAVE, key).value == forged, "cache must not return stale original bytes"
        with pytest.raises(JournalError, match="initial-save component differs from its atomic record"):
            runtime.state()
    finally:
        runtime.close()
