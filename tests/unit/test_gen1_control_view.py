"""Control-turn optimization must preserve detached views and later corruption checks."""

import secrets

import pytest

from server.gen1_run_config import create_runtime
from server.protocol_journal import JournalError
from tests.unit.observation_fixture import setup
from tests.unit.test_gen1_sessions import contract


def test_control_view_is_detached_invalidates_on_commit_and_does_not_escape_turn(
    tmp_path, monkeypatch
):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        from server import gen1_initial_save_runtime as saves

        original = saves.verify_journal
        checks = []

        def counted(*args):
            checks.append(True)
            return original(*args)

        monkeypatch.setattr(saves, "verify_journal", counted)

        def turn(player, message):
            first = runtime.state()
            first.rules.pokeballs_obtained["a"] = True
            assert not runtime.state().rules.pokeballs_obtained["a"]
            assert len(checks) == 1
            state = runtime.state()
            document = state.document()
            document["components"]["explicit-control-view-fixture"] = {"value": 1}
            runtime.journal.commit(
                "a",
                secrets.token_hex(16),
                {"event": "control-view-fixture"},
                expected_revision=state.journal_revision,
                state=document,
                commands={"a": [], "b": []},
                result={"ack": "ACK"},
            )
            assert (
                runtime.state().document()["components"]["explicit-control-view-fixture"]["value"]
                == 1
            )
            assert len(checks) == 2
            return {"fixture": True}

        monkeypatch.setattr(runtime, "_control_checked", turn)
        assert runtime._control("a", {}) == {"fixture": True, "pending_delivery": False}
        assert runtime._control_state_cache is None and not runtime._control_cache_active
        runtime.journal._db.execute(
            "UPDATE records SET digest=? WHERE namespace=?", ("0" * 64, saves.COMPONENT)
        )
        with pytest.raises(JournalError):
            runtime.state()
    finally:
        runtime.close()


def test_failed_control_cannot_leave_a_cached_view(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)

        def fail(player, message):
            runtime.state()
            raise JournalError("fixture failure")

        monkeypatch.setattr(runtime, "_control_checked", fail)
        with pytest.raises(JournalError):
            runtime._control("a", {})
        assert runtime._control_state_cache is None and not runtime._control_cache_active
    finally:
        runtime.close()
