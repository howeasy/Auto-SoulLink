"""Portable shared composition/obligation tests without cartridge or host policy."""

import copy
import sqlite3

import pytest

from server.identity_registry import IdentityContext, IdentityRegistry, IdentityWitness
from server.protocol_journal import JournalError, ProtocolJournal
from server.save_identity import SaveIdentity
from server.trade_coordinator import NAMESPACE, TradeCoordinator, TradeParticipant, TradeProposal


class OfferPolicy:
    def __init__(self, proposal):
        self.proposal = proposal
        self.owner = object()

    def authorize(self, action, player, authority, state, trade):
        return authority is self.owner

    def offer(self, *args):
        return self.proposal

    def prompt(self, *args):
        return {"schema": "test-prompt-v1"}

    def unqualified(self, *args):
        raise JournalError("physical policy is deliberately unavailable")

    decision = prepare = ready = commit = applied = verified = auxiliary = finalize = unqualified


@pytest.fixture
def source(tmp_path):
    registry = IdentityRegistry("1" * 32)
    participants = []
    for index, p in enumerate(("a", "b")):
        context = IdentityContext(
            p, "test", SaveIdentity("0000", "SAME"), p * 64, p * 32, str(index + 2) * 32
        )
        registry.bind_context(context)
        member = registry.acquire(
            f"{10 + index:032x}",
            f"{20 + index:032x}",
            IdentityWitness(context, "same-key", p * 64, 1),
        )["member_id"]
        participants.append(
            TradeParticipant(context, member, "same-key", 0, p * 64, {"schema": "test-party-v1"})
        )
    link = registry.create_link("a", "3" * 32, [part.member_id for part in participants])["link_id"]
    policy = OfferPolicy(TradeProposal(link, *participants))
    journal = ProtocolJournal(tmp_path / "journal.sqlite3", run_id="1" * 32, contract_hash="2" * 64)
    journal.bootstrap(
        TradeCoordinator.initial_state(
            {"preserve": 3}, registry.document(), components={"other": {"preserve": 4}}
        )
    )
    yield journal, policy
    journal.close()


def offer(source, callback):
    journal, policy = source
    coordinator = TradeCoordinator(
        journal, policy, clock=lambda: 1_000, new_id=lambda: "5" * 32, compose_components=callback
    )
    return coordinator.handle(
        "a", "4" * 32, {"event": "trade_offer", "payload": {}}, owner=policy.owner
    )


def test_detached_composition_cannot_replace_trade_rules_identities_or_commands(source):
    journal, _ = source
    before = journal.snapshot()
    calls = []

    def compose(state, trade, commands, acknowledgements):
        calls.append(trade["id"])
        components = state["components"]
        components["new"] = {"transaction": trade["id"], "phase": trade["phase"]}
        state["rules"].clear()
        state["identities"].clear()
        trade.clear()
        commands.clear()
        acknowledgements.append({"fake": True})
        return components

    result = offer(source, compose)
    after = journal.snapshot()
    assert after.revision == before.revision + 1
    assert (
        after.state["rules"] == before.state["rules"]
        and after.state["identities"] == before.state["identities"]
    )
    assert after.state["components"] == {
        "other": {"preserve": 4},
        "new": {"transaction": "5" * 32, "phase": "offered"},
    }
    assert journal.record(NAMESPACE, "5" * 32).revision == after.revision
    assert journal.pending("b")[0]["cmd"] == "native_trade_prompt"
    assert offer(source, compose) == result and calls == ["5" * 32]
    assert journal.snapshot() == after


@pytest.mark.parametrize("failure", ["exception", "invalid", "sql"])
def test_composition_and_persistence_failures_leave_no_partial_publication(source, failure):
    journal, _ = source
    before = journal.snapshot()

    def compose(state, trade, commands, acknowledgements):
        if failure == "exception":
            raise JournalError("injected")
        return [] if failure == "invalid" else {"new": {"trade": trade["id"]}}

    if failure == "sql":
        journal._db.execute(
            "CREATE TRIGGER fail_trade BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
    with pytest.raises((JournalError, sqlite3.DatabaseError)):
        offer(source, compose)
    assert journal.snapshot() == before
    assert journal.record(NAMESPACE, "5" * 32) is None
    assert journal.pending_ids("a") == journal.pending_ids("b") == ()


def test_complete_obligation_index_includes_commands_beyond_delivery_count_and_bytes(source):
    journal, _ = source
    before = journal.snapshot()
    journal.commit(
        "a",
        "6" * 32,
        {"event": "test-batch"},
        expected_revision=before.revision,
        state=before.state,
        commands={"a": [{"cmd": "fixture", "payload": "x" * 4000} for _ in range(130)], "b": []},
        result={"ack": "ACK"},
    )
    before = journal.snapshot()
    ids = journal.pending_ids("a")
    assert len(ids) == 130 and len(journal.pending("a")) == 128
    assert len(journal.pending("a", max_bytes=8192)) < 128
    assert len(set(ids)) == 130
    assert all(journal.command("a", identifier)["body"]["cmd"] == "fixture" for identifier in ids)
    detached = list(ids)
    detached.clear()
    assert journal.pending_ids("a") == ids and journal.snapshot() == before
    journal.acknowledge("a", ids[-1], "ACK", {"schema": "test-closure-v1"})
    assert journal.pending_ids("a") == ids[:-1]


def test_component_callback_is_optional_and_rejected_when_noncallable(source):
    journal, policy = source
    with pytest.raises(JournalError, match="callable"):
        TradeCoordinator(journal, policy, compose_components=True)
    original = copy.deepcopy(journal.snapshot().state["components"])
    offer(source, None)
    assert journal.snapshot().state["components"] == original
