"""Shared suspension retains interruption records and always revokes sessions."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from server.durable_runtime import DurableRuntime
from server.identity_registry import IdentityRegistry
from server.paired_recovery import RecoveryBarrier, VerifiedReconciliation
from server.protocol import SessionGate
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


class PortableStage:
    """Only the generation document binding is modeled; lifecycle objects are real."""

    @classmethod
    def restore(cls, document, *, data_dir):
        stage = cls()
        stage.component = copy.deepcopy(document["component"])
        stage.identities = IdentityRegistry.restore(document["identities"], run_id="1" * 32)
        stage.barrier = RecoveryBarrier.restore(document["barrier"])
        return stage

    def document(self):
        return {"component": self.component, "identities": self.identities.document(),
                "barrier": self.barrier.document()}


def open_portable_runtime(tmp_path, *, initialize=False):
    contract = {"schema": "test-suspension-contract"}
    initial = {"component": {"contract": contract},
               "identities": IdentityRegistry("1" * 32).document(),
               "barrier": RecoveryBarrier("a" * 64).document()}
    return DurableRuntime(
        tmp_path / "lifecycle.sqlite3", contract=contract, data_dir=tmp_path,
        protocol="test-suspension", hold_event="test_hold", stage_type=PortableStage,
        new_session_gate=lambda **options: SessionGate(
            protocol="test-suspension", durable_ids=True, hello_validator=lambda *args: {}, **options),
        validate_event=lambda *args: None, validate_receipt=lambda *args: None,
        verify_reconciliation=lambda *args: None, clock=lambda: 10,
        initial_state=initial if initialize else None, run_id="1" * 32,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [JournalError, RuntimeError])
@pytest.mark.parametrize("entry", ["process", "connection"])
async def test_hook_failure_latches_runtime_closes_connection_and_reopen_revokes_ticket(
    tmp_path, error_type, entry,
):
    runtime = open_portable_runtime(tmp_path, initialize=True)
    try:
        stage = runtime.state()
        for player, code in (("a", "b"), ("b", "c")):
            stage.barrier.bind(player, code * 64, code * 32)
        for player in ("a", "b"):
            document = stage.barrier.document()
            stage.barrier.reconcile(player, VerifiedReconciliation(
                player, document["epoch"], **document["bindings"][player],
                history_digest=document["history_digest"], checkpoint_digest="f" * 64))
        runtime._commit_system(stage, "test_reconciled")
        before = runtime.journal.snapshot()
        ticket = runtime.state().barrier.ticket()
        assert ticket is not None

        def fail(reason):
            raise error_type("injected suspension callback")

        runtime._before_suspend = fail
        runtime._control_seen["a"] = 0  # Expired heartbeat reaches the hook through process().
        message = {"protocol": runtime.protocol, "player": "a", "event": "hello"}
        if entry == "process":
            with pytest.raises(error_type, match="injected suspension callback"):
                runtime.process(message, object())
        else:
            finished = asyncio.Event()

            async def connected(reader, writer):
                try:
                    await runtime.handle_client(reader, writer)
                finally:
                    finished.set()

            server = await asyncio.start_server(connected, "127.0.0.1", 0)
            try:
                port = server.sockets[0].getsockname()[1]
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                try:
                    writer.write(json.dumps(message).encode() + b"\n")
                    await writer.drain()
                    reply = json.loads(await asyncio.wait_for(reader.readline(), 3))
                    assert reply["ack"] == "NACK"
                    assert reply["admission"]["state"] == "contract_pending"
                    assert reply["commands"] == []
                    assert await asyncio.wait_for(reader.read(), 3) == b""
                    await asyncio.wait_for(finished.wait(), 3)
                finally:
                    writer.close()
                    await writer.wait_closed()
            finally:
                server.close()
                await server.wait_closed()

        assert runtime._failed == "could not persist durable suspension"
        assert runtime.gate.sessions == runtime._control_seen == runtime._control_challenges == {}
        assert runtime.journal.snapshot() == before  # The failed hook could not invalidate disk state.
        assert runtime.state().barrier.ticket() == ticket
        with pytest.raises(JournalError, match="requires reopen"):
            runtime.process(message, object())
    finally:
        runtime.close()
    reopened = open_portable_runtime(tmp_path)
    try:
        assert reopened._failed is None
        assert reopened.state().barrier.ticket() is None
        assert reopened.state().barrier.document()["epoch"] != ticket["epoch"]
        assert reopened.journal.snapshot().revision == before.revision + 1
        assert reopened.gate.sessions == {}
    finally:
        reopened.close()
