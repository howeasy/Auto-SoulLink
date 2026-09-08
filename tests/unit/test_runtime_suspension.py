"""Shared suspension retains interruption records and always revokes sessions."""

from types import SimpleNamespace

import pytest

from server.durable_runtime import DurableRuntime
from server.protocol_journal import JournalError, ProtocolJournal


@pytest.mark.parametrize("mode", ["default", "commit", "hook_failure", "barrier_failure"])
def test_suspension_orders_notice_hook_and_barrier_and_revokes_on_failure(tmp_path, mode):
    journal = ProtocolJournal(tmp_path / "runtime.sqlite3", run_id="1" * 32, contract_hash="2" * 64)
    journal.bootstrap({"components": {}, "barrier": {"reason": None}})
    runtime = object.__new__(DurableRuntime)
    runtime.journal = journal
    runtime._failed = None
    runtime.gate = SimpleNamespace(sessions={"a": object(), "b": object()})
    runtime._control_seen = {"a": 1, "b": 1}
    runtime._control_challenges = {"a": "challenge", "b": "challenge"}
    order = []
    runtime._notify_holds = lambda reason: order.append("notice")

    def state():
        snapshot = journal.snapshot()

        def invalidate(reason):
            order.append("barrier")
            if mode == "barrier_failure":
                raise JournalError("injected barrier failure")
            snapshot.state["barrier"]["reason"] = reason

        return SimpleNamespace(
            journal_revision=snapshot.revision,
            document=lambda: snapshot.state,
            barrier=SimpleNamespace(invalidate=invalidate),
        )

    runtime.state = state

    def before_suspend(reason):
        assert order == ["notice"]
        assert set(runtime.gate.sessions) == {"a", "b"}
        order.append("hook")
        if mode == "hook_failure":
            raise JournalError("injected hook failure")
        stage = state()
        stage.document()["components"]["interruption"] = reason
        runtime._commit_system(stage, "test_interruption")

    if mode != "default":
        runtime._before_suspend = before_suspend
    try:
        before = journal.snapshot()
        if mode in {"hook_failure", "barrier_failure"}:
            with pytest.raises(JournalError, match="injected"):
                runtime.suspend("peer disconnected")
            assert runtime._failed == "could not persist durable suspension"
        else:
            runtime.suspend("peer disconnected")
            assert runtime._failed is None
        assert runtime.gate.sessions == runtime._control_seen == runtime._control_challenges == {}
        after = journal.snapshot()
        assert order == (["notice", "barrier"] if mode == "default" else
                         ["notice", "hook"] if mode == "hook_failure" else
                         ["notice", "hook", "barrier"])
        interruption_written = mode in {"commit", "barrier_failure"}
        barrier_written = mode in {"default", "commit"}
        assert after.revision == before.revision + interruption_written + barrier_written
        assert after.state["components"] == (
            {"interruption": "peer disconnected"} if interruption_written else {})
        assert after.state["barrier"]["reason"] == ("peer disconnected" if barrier_written else None)
    finally:
        journal.close()
