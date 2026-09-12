"""Full RBY rules/coordinator/recovery/TCP; native and host evidence are fixtures."""

import asyncio
import copy
import hashlib
import sqlite3
from itertools import product

import pytest

from server.gen1_admission import cartridge_metadata
from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_command_receipts import Gen1ReceiptPolicy
from server.gen1_runtime import Gen1Runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_trade_recovery import transactions
from server.gen1_trade_rules import Gen1TradeRules
from server.identity_registry import IdentityContext, IdentityRegistry, IdentityWitness
from server.protocol import ProtocolError, canonical_json, decode_frame
from server.protocol_journal import JournalError
from server.save_identity import SaveIdentity
from server.trade_coordinator import NAMESPACE
from tests.unit.test_gen1_runtime_server import RUN_ID, RuntimeCase
from tests.unit.test_gen1_trade_rules import snapshot
from tests.unit.test_trade_coordinator import Policy


class FullRulePolicy(Policy):
    def __init__(self, case, contexts):
        super().__init__(case.variants, contexts)
        self.case = case
        self.binding = Gen1TradeRules(self.rules, data_dir=case.path)

    def observed(self, player, raw):
        result = snapshot(self.rules[player].codec.validate_blob(raw), self.contexts[player])
        result["variant"] = self.variants[player]
        return result

    def offer(self, player, payload, state):
        if payload != {"key": self.case.keys[player]}:
            raise JournalError("fixture receptionist selection differs")
        return self.binding.proposal(
            state["rules"],
            IdentityRegistry.restore(state["identities"], run_id=RUN_ID),
            player=player,
            key=payload["key"],
            contexts=self.contexts,
            snapshots={p: self.observed(p, raw) for p, raw in self.case.blobs.items()},
        )

    def finalize(self, rules, trade, migrations):
        native = copy.deepcopy(trade)
        for p in ("a", "b"):
            native["applied"][p]["after"] = {
                "party": self.observed(p, bytes.fromhex(trade["applied"][p]["after"][0]))
            }
        return self.binding.finalize(rules, native, migrations)


class TradeCase(RuntimeCase):
    def __init__(self, path, variants=("yellow", "yellow"), *, clean_players=()):
        self.clean_players = set(clean_players)
        super().__init__(path, variants)

    def open(self, initial=False):
        if initial:
            companions = companion_profiles()
            for player, variant in self.variants.items():
                if player not in self.clean_players:
                    self.contract["players"][player] = cartridge_metadata(companions[variant])
            contexts = {
                p: IdentityContext(
                    p,
                    "gen1_rby",
                    SaveIdentity("0000", "SAME"),
                    hashlib.sha256(v.encode()).hexdigest(),
                    p * 32,
                    ("1" if p == "a" else "2") * 32,
                )
                for p, v in self.variants.items()
            }
            self.policy = FullRulePolicy(self, contexts)
            registry = IdentityRegistry(RUN_ID)
            members = []
            for p, context in contexts.items():
                registry.bind_context(context)
                mon = self.policy.rules[p].codec.validate_blob(self.blobs[p])
                members.append(
                    registry.acquire(
                        self.token(), self.token(), IdentityWitness(context, mon.key, mon.sha256, 1)
                    )["member_id"]
                )
            registry.create_link("a", self.token(), members)
            self.rules["core"]["rules"]["pc_trade_npc"] = True
            self.initial = Gen1RuntimeState.initial(
                self.rules, registry.document(), self.contract, data_dir=self.path
            )
        self.runtime = Gen1Runtime(
            self.path / "gen1.sqlite3",
            contract=self.contract,
            data_dir=self.path,
            run_id=RUN_ID,
            initial_state=self.initial if initial else None,
            clock=lambda: self.time,
            validate_event=self.validate_event,
            validate_receipt=Gen1ReceiptPolicy(self.variants),
            verify_reconciliation=self.verify_reconciliation,
            trade_policy=self.policy,
            trade_clock=lambda: 1_000_000,
        )

    def admit(self, player):
        result = super().admit(player)
        self.policy.owners[player] = self.owners[player]
        return result

    def offer(self, player="a"):
        message, response = self.send(
            player, {"event": "trade_offer", "payload": {"key": self.keys[player]}}
        )
        self.tx = self.runtime.journal.snapshot().state["active_trade"]
        self.initiator = player
        return message, response

    def command(self, player, name):
        return next(row for row in self.runtime.journal.pending(player) if row["cmd"] == name)

    def event(self, player, event, command, receipt):
        return self.send(
            player,
            {
                "event": event,
                "transaction_id": self.tx,
                "command_id": command["command_id"],
                "command_sequence": command["command_sequence"],
                "receipt": receipt,
            },
        )

    def trade_control(self, action):
        return self.runtime.trade_control(
            action, self.tx, self.token(), authority=self.policy.control
        )

    def accept(self, yes=True):
        peer = "b" if self.initiator == "a" else "a"
        self.event(
            peer,
            "trade_decision",
            self.command(peer, "native_trade_prompt"),
            {"schema": "fixture-decision-v1", "accepted": yes, "native_prompt": True},
        )

    def ready(self, player):
        command = self.command(player, "native_trade_prepare")
        return self.event(
            player,
            "trade_ready",
            command,
            {
                "schema": "fixture-ready-v1",
                "held": True,
                "snapshot": command["payload"]["snapshot"],
            },
        )

    def apply_verify(self, player):
        command = self.command(player, "native_trade_commit")
        peer = "b" if player == "a" else "a"
        after = [self.policy.rules[player].outcomes(self.blobs[peer])[0].blob.hex().upper()]
        self.event(
            player,
            "trade_applied",
            command,
            {
                "schema": "fixture-applied-v1",
                "after": after,
                "native_complete": True,
                "command_id": command["command_id"],
                "prepared_digest": command["payload"]["prepared_digest"],
            },
        )
        assert self.runtime.journal.command(player, command["command_id"])["outcome"] is None
        self.event(
            player,
            "trade_verified",
            command,
            {"schema": "fixture-verified-v1", "after": after, "saved": True},
        )

    def committed(self):
        self.offer()
        self.accept()
        self.trade_control("prepare")
        self.ready("a")
        self.ready("b")
        self.trade_control("commit")

    def closure(self, player):
        for command in list(self.runtime.journal.pending(player)):
            self.event(
                player, "trade_ack", command, {"schema": "fixture-closure-v1", "no_effect": True}
            )


@pytest.fixture
def case(tmp_path):
    value = TradeCase(tmp_path)
    value.admit("a")
    value.admit("b")
    yield value
    value.close()


@pytest.mark.parametrize("variants", list(product(("red", "blue", "yellow"), repeat=2)))
@pytest.mark.parametrize("initiator", ["a", "b"])
def test_all_ordered_pairs_atomically_follow_trade_through_both_native_closures(
    tmp_path, variants, initiator
):
    case = TradeCase(tmp_path, variants)
    try:
        case.admit("a")
        case.admit("b")
        proof = {"schema": "explicit-test-host-proof-v1"}
        case.control("a", proof)
        case.control("b", proof)
        assert case.runtime.state().barrier.ticket() is not None
        original = case.runtime.journal.snapshot().state
        request, reply = case.offer(initiator)
        assert case.runtime.process(request, case.owners[initiator]) == reply
        assert not case.runtime.state().barrier.document()["blockers"]
        assert case.runtime.state().barrier.ticket() is None
        case.control("a", proof)
        case.control("b", proof)
        assert case.runtime.state().barrier.ticket() is not None  # offered partner can reach prompt
        case.accept()
        assert case.tx in case.runtime.state().barrier.document()["blockers"]
        case.trade_control("prepare")
        case.ready("a")
        case.ready("b")
        case.trade_control("commit")
        for p in ("a", "b"):
            wire = case.send(p, {"event": "sync"})[1]["commands"][0]
            assert wire["body"] == case.runtime.journal.command(p, wire["command_id"])["body"]
        case.apply_verify("a")
        assert case.runtime.journal.snapshot().state["identities"] == original["identities"]
        pending = {p: case.runtime.journal.pending(p) for p in ("a", "b")}
        case.close()
        case.open()
        # The reopen is now a durable interruption. Only this explicit modeled
        # recovery policy permits the remaining receipt/delivery in this test.
        case.policy.recovery = True
        case.admit("b")
        case.admit("a")
        assert {p: case.runtime.journal.pending(p) for p in ("a", "b")} == pending
        case.apply_verify("b")
        case.trade_control("finalize")
        stage = case.runtime.state()
        assert stage.document()["active_trade"] is None
        assert stage.document()["identities"] != original["identities"]
        assert (
            stage.rules.document()["core"]["area_states"]
            == original["rules"]["core"]["area_states"]
        )
        assert case.tx in stage.barrier.document()["blockers"]
        case.closure("a")
        assert case.tx in case.runtime.state().barrier.document()["blockers"]
        case.closure("b")
        assert not transactions(case.runtime.state().document())
        assert case.runtime.state().barrier.ticket() is None
        case.control("a", proof)
        case.control("b", proof)
        assert case.runtime.state().barrier.ticket() is not None
    finally:
        case.close()


def test_offer_allows_verified_gameplay_but_acceptance_and_terminal_closure_own_parties(case):
    case.offer()
    # The event policy already independently accepted this observed faint.
    case.send("b", {"event": "faint", "key": case.keys["b"]})
    assert case.runtime.rule_state().links[0].status.value == "dead"


@pytest.mark.parametrize("phase", ["accepted", "terminal"])
def test_owned_party_observations_are_rejected_until_both_closures(case, phase):
    case.offer()
    case.accept(phase == "accepted")
    before = case.runtime.journal.snapshot()
    with pytest.raises(JournalError, match="owns parties"):
        case.send("a", {"event": "faint", "key": case.keys["a"]})
    assert case.runtime.journal.snapshot() == before


def test_decline_keeps_both_abort_obligations_and_refuses_another_offer(case):
    case.offer()
    case.accept(False)
    case.closure("a")
    with pytest.raises(JournalError, match="closure"):
        case.offer()
    assert case.tx in case.runtime.state().barrier.document()["blockers"]
    case.closure("b")
    case.offer()


@pytest.mark.parametrize("event", ["trade_control", "native_trade_release", "command_ack"])
def test_network_cannot_invoke_private_controls_or_generic_native_ack(case, event):
    case.committed()
    command = case.command("a", "native_trade_commit")
    before = case.runtime.journal.snapshot()
    with pytest.raises(ProtocolError, match="private|typed"):
        case.send(
            "a",
            {
                "event": event,
                "command_id": command["command_id"],
                "command_sequence": command["command_sequence"],
                "outcome": "ACK",
                "receipt": {"schema": "fake", "success": True},
            },
        )
    assert case.runtime.journal.snapshot() == before


@pytest.mark.parametrize("phase", ["prepare", "commit", "finalize"])
def test_failed_commit_rolls_back_recovery_with_trade_rules_and_outboxes(case, phase):
    case.offer()
    case.accept()
    if phase != "prepare":
        case.trade_control("prepare")
        case.ready("a")
        case.ready("b")
    if phase == "finalize":
        case.trade_control("commit")
        case.apply_verify("a")
        case.apply_verify("b")
    before = case.runtime.journal.snapshot()
    record = case.runtime.journal.record(NAMESPACE, case.tx)
    pending = {p: case.runtime.journal.pending(p) for p in ("a", "b")}
    case.runtime.journal._db.execute(
        "CREATE TRIGGER fail_trade BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'injected'); END"
    )
    with pytest.raises(sqlite3.DatabaseError):
        case.trade_control(phase)
    assert case.runtime.journal.snapshot() == before
    assert case.runtime.journal.record(NAMESPACE, case.tx) == record
    assert {p: case.runtime.journal.pending(p) for p in ("a", "b")} == pending
    assert case.runtime._failed and not case.runtime.gate.sessions
    case.runtime.state()  # restored recovery remains consistent after rollback


def test_raw_journal_ack_cannot_silently_erase_a_recovery_obligation(case):
    case.offer()
    case.accept(False)
    command = case.command("a", "native_trade_abort")
    case.runtime.journal.acknowledge(
        "a", command["command_id"], "ACK", {"schema": "uncoordinated-ack"}
    )
    with pytest.raises(JournalError, match="record/outboxes"):
        case.runtime.state()


def test_owned_delivery_rejects_changed_physical_context_without_reapplying(case):
    case.committed()
    case.runtime.gate.sessions["a"].metadata["control_binding"]["context_generation"] = "f" * 32
    before = case.runtime.journal.snapshot()
    with pytest.raises(JournalError, match="authority"):
        case.send("b", {"event": "sync"})
    # sync may be journaled; it may not change transaction/identities/outbox obligations.
    assert case.runtime.journal.snapshot().state == before.state
    assert case.command("a", "native_trade_commit")


def test_native_outbox_requires_explicit_trade_policy(tmp_path):
    case = RuntimeCase(tmp_path)
    try:
        case.admit("a")
        before = case.runtime.journal.snapshot()
        with pytest.raises(ProtocolError, match="not configured"):
            case.send("a", {"event": "trade_offer", "payload": {"key": case.keys["a"]}})
        assert case.runtime.journal.snapshot() == before
    finally:
        case.close()


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue")])
def test_actual_tcp_routes_offer_and_decision_into_atomic_recovery(tmp_path, variants):
    async def exercise():
        case = TradeCase(tmp_path, variants)
        service = await asyncio.start_server(case.runtime.handle_client, "127.0.0.1", 0)
        clients = {}
        try:
            for p in ("a", "b"):
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", service.sockets[0].getsockname()[1]
                )
                clients[p] = reader, writer
                writer.write((canonical_json(case.hello(p)) + "\n").encode())
                await writer.drain()
                assert decode_frame(await reader.readline())["ack"] == "ACK"
                case.policy.owners[p] = case.runtime.gate.sessions[p].owner

            async def send(p, payload):
                reader, writer = clients[p]
                writer.write((canonical_json(case.envelope(p, payload)) + "\n").encode())
                await writer.drain()
                return decode_frame(await reader.readline())

            assert (await send("a", {"event": "trade_offer", "payload": {"key": case.keys["a"]}}))[
                "ack"
            ] == "ACK"
            command = (await send("b", {"event": "sync"}))["commands"][0]
            assert command["body"]["cmd"] == "native_trade_prompt"
            tx = command["body"]["transaction_id"]
            assert not case.runtime.state().barrier.document()["blockers"]
            response = await send(
                "b",
                {
                    "event": "trade_decision",
                    "transaction_id": tx,
                    "command_id": command["command_id"],
                    "command_sequence": command["command_sequence"],
                    "receipt": {
                        "schema": "fixture-decision-v1",
                        "accepted": True,
                        "native_prompt": True,
                    },
                },
            )
            assert response["ack"] == "ACK"
            assert case.runtime.journal.record(NAMESPACE, tx).value["phase"] == "accepted"
            assert tx in case.runtime.state().barrier.document()["blockers"]
            assert case.runtime.journal.command("b", command["command_id"])["outcome"] == "ACK"
        finally:
            for _, writer in clients.values():
                writer.close()
                await writer.wait_closed()
            for _ in range(100):
                if not case.runtime._writers:
                    break
                await asyncio.sleep(0.01)
            service.close()
            await service.wait_closed()
            case.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("clean_players", [("a",), ("b",), ("a", "b")])
def test_native_trade_refuses_any_unpatched_participant_despite_available_policy(
    tmp_path, clean_players
):
    case = TradeCase(tmp_path, clean_players=clean_players)
    try:
        case.admit("a")
        case.admit("b")
        before = case.runtime.journal.snapshot()
        with pytest.raises(JournalError, match="authority"):
            case.offer()
        assert case.runtime.journal.snapshot() == before
        assert not case.runtime.journal.pending_ids("a") and not case.runtime.journal.pending_ids(
            "b"
        )
    finally:
        case.close()
