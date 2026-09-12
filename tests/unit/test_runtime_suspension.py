"""Shared suspension retains interruption records and always revokes sessions."""

import asyncio
import copy
import json
import logging
from types import SimpleNamespace

import pytest

from server.durable_runtime import TIMEOUT, DurableRuntime
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
    runtime._revoke_service = lambda reason: order.append("service")
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
        assert order == ["service", "notice"]
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
        assert order == (["service", "notice", "barrier"] if mode == "default" else
                         ["service", "notice", "hook"] if mode == "hook_failure" else
                         ["service", "notice", "hook", "barrier"])
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
        stage.rules = SimpleNamespace()
        return stage

    def admit(self, player, metadata, binding):
        self.component["admissions"][player] = {"metadata": copy.deepcopy(metadata)}
        self.barrier.bind(player, **binding)

    def handle_event(self, player, request, **options):
        assert request["event"] == "hello"  # No cartridge rule behavior is modeled here.
        return []

    def take_commands(self, player, immediate):
        return {"a": [], "b": []}

    def document(self):
        return {"component": self.component, "identities": self.identities.document(),
                "barrier": self.barrier.document()}


def open_portable_runtime(tmp_path, *, initialize=False, clock=lambda: 10):
    contract = {"schema": "test-suspension-contract"}
    initial = {"component": {"contract": contract, "admissions": {"a": None, "b": None}},
               "identities": IdentityRegistry("1" * 32).document(),
               "barrier": RecoveryBarrier("a" * 64).document()}
    return DurableRuntime(
        tmp_path / "lifecycle.sqlite3", contract=contract, data_dir=tmp_path,
        protocol="test-suspension", hold_event="test_hold", stage_type=PortableStage,
        new_session_gate=lambda **options: SessionGate(
            protocol="test-suspension", durable_ids=True,
            hello_validator=lambda *args: {"save_identity": {"ot_id": "0000", "trainer_name": "TEST"}},
            **options),
        validate_event=lambda *args: None, validate_receipt=lambda *args: None,
        verify_reconciliation=lambda *args: None, clock=clock,
        initial_state=initial if initialize else None, run_id="1" * 32,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [JournalError, RuntimeError])
@pytest.mark.parametrize("entry", ["process", "connection"])
async def test_hook_failure_latches_runtime_closes_connection_and_reopen_revokes_ticket(
    tmp_path, error_type, entry, caplog,
):
    caplog.set_level(logging.ERROR, logger="server.durable_runtime")
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
                    assert reply["admission"]["reason"] == "injected suspension callback"
                    assert reply["commands"] == []
                    assert await asyncio.wait_for(reader.read(), 3) == b""
                    await asyncio.wait_for(finished.wait(), 3)
                    finished.clear()
                    retry_reader, retry_writer = await asyncio.open_connection("127.0.0.1", port)
                    try:
                        retry_writer.write(json.dumps(message).encode() + b"\n")
                        await retry_writer.drain()
                        retry = json.loads(await asyncio.wait_for(retry_reader.readline(), 3))
                        assert retry["admission"]["state"] == "contract_pending"
                        assert "requires reopen" in retry["admission"]["reason"]
                        assert retry["commands"] == []
                        assert await asyncio.wait_for(retry_reader.read(), 3) == b""
                        await asyncio.wait_for(finished.wait(), 3)
                    finally:
                        retry_writer.close()
                        await retry_writer.wait_closed()
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
        errors = [record for record in caplog.records if record.name == "server.durable_runtime"]
        assert len(errors) == int(entry == "connection" and error_type is RuntimeError)
        if errors:
            assert errors[0].exc_info[0] is RuntimeError
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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hook_failure", "commit", "barrier_failure"])
async def test_admitted_writer_is_held_before_hook_and_revoked_at_exact_deadline(tmp_path, mode):
    now = [0.0]
    runtime = open_portable_runtime(tmp_path, initialize=True, clock=lambda: now[0])
    written = []
    finished = asyncio.Event()

    async def connected(reader, writer):
        # Observe actual queued socket bytes, preserving StreamWriter's real transport.
        write = writer.write

        def observe(data):
            written.append(json.loads(data))
            write(data)

        writer.write = observe
        try:
            await runtime.handle_client(reader, writer)
        finally:
            finished.set()

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        try:
            hello = {"protocol": runtime.protocol, "player": "a", "event": "hello", "seq": 0,
                     "client_nonce": "4" * 32, "operation_id": "4" * 32,
                     "context_generation": "5" * 32}
            writer.write(json.dumps(hello).encode() + b"\n")
            await writer.drain()
            admitted = json.loads(await asyncio.wait_for(reader.readline(), 3))
            assert admitted["admission"]["state"] == "admitted"
            assert set(runtime.gate.sessions) == set(runtime._control_challenges) == set(runtime._writers) == {"a"}
            with pytest.raises(JournalError, match="close runtime connections"):
                runtime.close()

            # A real control challenge before expiry proves the admitted owner is usable.
            now[0] = TIMEOUT - 0.001
            control = {**hello, "event": "control", "seq": 1, "operation_id": "6" * 32,
                       "session_id": admitted["session_id"], "admission_epoch": admitted["admission_epoch"],
                       "control": {**admitted["admission"]["control_binding"], "challenge": "6" * 32}}
            writer.write(json.dumps(control).encode() + b"\n")
            await writer.drain()
            assert json.loads(await asyncio.wait_for(reader.readline(), 3))["ack"] == "ACK"
            assert runtime._control_challenges["a"] == {"6" * 32}
            before = runtime.journal.snapshot()
            epoch = runtime.state().barrier.document()["epoch"]

            def hook(reason):
                assert runtime._writers and runtime.gate.sessions and runtime._control_challenges
                assert written[-1]["event"] == "test_hold"
                if mode == "hook_failure":
                    raise JournalError("injected admitted hook failure")
                stage = runtime.state()
                stage.component["interruption"] = reason
                runtime._commit_system(stage, "test_interruption")
                if mode == "barrier_failure":
                    runtime.journal._db.execute("""CREATE TRIGGER fail_suspension BEFORE INSERT ON events
                        WHEN NEW.request = '{"event":"runtime_suspended"}'
                        BEGIN SELECT RAISE(ABORT, 'injected suspension publication'); END""")

            runtime._before_suspend = hook
            now[0] += TIMEOUT  # Exact >= boundary, measured from the accepted control heartbeat.
            writer.write(json.dumps({**control, "seq": 2, "operation_id": "7" * 32}).encode() + b"\n")
            await writer.drain()
            notice = json.loads(await asyncio.wait_for(reader.readline(), 3))
            assert notice["event"] == "test_hold"
            refused = json.loads(await asyncio.wait_for(reader.readline(), 3))
            assert refused["ack"] == "NACK" and refused["commands"] == []
            assert await asyncio.wait_for(reader.read(), 3) == b""
            await asyncio.wait_for(finished.wait(), 3)
            assert runtime.gate.sessions == runtime._control_seen == runtime._control_challenges == runtime._writers == {}
            after = runtime.journal.snapshot()
            assert after.revision == before.revision + {"hook_failure": 0, "commit": 2, "barrier_failure": 1}[mode]
            assert ("interruption" in after.state["component"]) == (mode != "hook_failure")
            assert (runtime.state().barrier.document()["epoch"] != epoch) == (mode == "commit")
            assert (runtime._failed is None) == (mode == "commit")
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()
        runtime.close()
