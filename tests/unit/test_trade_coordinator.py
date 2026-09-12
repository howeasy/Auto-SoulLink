"""Real SQLite + shared identities + RBY result rules; synthetic host evidence."""
import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from itertools import product

import pytest

from server.gen1_party_codec import PartyCodec
from server.identity_registry import IdentityContext, IdentityRegistry, IdentityWitness, MigrationWitness
from server.protocol_journal import JournalError, ProtocolJournal
from server.save_identity import SaveIdentity
from server.trade_coordinator import (NAMESPACE, PreparedTrade, TradeCoordinator,
                                      TradeParticipant, TradeProposal, TradeVerification)
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_trade_result import rules as result_rules

RUN, CONTRACT = "1"*32, "2"*64
TITLES = ("red", "blue", "yellow")


def context_from(document):
    data = copy.deepcopy(document)
    data["save_identity"] = SaveIdentity(**data["save_identity"])
    return IdentityContext(**data)


class Policy:
    """Admission/host/save fixtures are deliberate model inputs, not live proof."""
    def __init__(self, variants, contexts):
        self.variants, self.contexts = variants, contexts
        self.rules = {p: result_rules(v) for p, v in variants.items()}
        self.owners = {p: object() for p in ("a", "b")}
        self.control = object()
        self.recovery = False
        self.allow_commit = True
        self.fail_finalize = False

    def authorize(self, action, player, owner, state, trade):
        valid = owner is (self.owners[player] if player else self.control)
        if trade and trade["recovery_required"] and not self.recovery:
            return valid and action in {"interrupt", "trade_cancel"}
        return valid

    def offer(self, player, payload, state):
        if payload != {"link": state["rules"]["link_id"]} or not state["rules"]["alive"]:
            raise JournalError("linked pair is not alive/eligible")
        entries = []
        for p in ("a", "b"):
            raw = bytes.fromhex(state["rules"]["parties"][p][0])
            mon = self.rules[p].codec.validate_blob(raw)
            if not mon.hp:
                raise JournalError("fainted offer")
            entries.append(TradeParticipant(self.contexts[p], state["rules"]["owners"][p], mon.key, 0, mon.sha256,
                {"schema": "rby-fixture-party-v1", "party": state["rules"]["parties"][p]}))
        return TradeProposal(state["rules"]["link_id"], *entries)

    def prompt(self, trade, player):
        return {"schema": "fixture-prompt-v1", "link_id": trade["proposal"]["link_id"]}

    def decision(self, trade, player, command, receipt):
        if type(receipt.get("accepted")) is not bool or receipt.get("native_prompt") is not True:
            raise JournalError("unverified native decision")
        return receipt["accepted"], receipt

    def prepare(self, trade, player):
        return {"schema": "fixture-prepare-v1", "snapshot": trade["proposal"]["participants"][player]["snapshot"]}

    def ready(self, trade, player, command, receipt):
        part = trade["proposal"]["participants"][player]
        if receipt.get("snapshot") != part["snapshot"] or receipt.get("held") is not True:
            raise JournalError("moved party or missing hold")
        return PreparedTrade(trade["proposal_digest"], part["context"]["context_generation"],
                             part["evidence_digest"], receipt)

    def commit(self, trade, state, authority):
        if not self.allow_commit:
            raise JournalError("fresh paired commit authority unavailable")
        return {"schema": "fixture-quorum-v1", "prepared": sorted(trade["ready"])}

    def applied(self, trade, player, command, receipt):
        if (receipt.get("native_complete") is not True or receipt.get("command_id") != command["command_id"]
                or receipt.get("prepared_digest") != command["body"]["payload"]["prepared_digest"]):
            raise JournalError("operation-bound native completion absent")
        return receipt

    def verified(self, trade, player, command, receipt):
        if receipt.get("saved") is not True:
            raise JournalError("save-file proof unavailable")
        if receipt.get("after") != trade["applied"][player]["after"]:
            raise JournalError("verification poststate changed")
        peer = "b" if player == "a" else "a"
        sender = trade["proposal"]["participants"][peer]
        receiver = trade["proposal"]["participants"][player]
        before = [bytes.fromhex(raw) for raw in receiver["snapshot"]["party"]]
        incoming = bytes.fromhex(sender["snapshot"]["party"][sender["slot"]])
        after = [bytes.fromhex(raw) for raw in receipt["after"]]
        self.rules[player].verify_party(before, receiver["slot"], incoming, after,
            expected_key=receiver["key"], incoming_key=sender["key"], boxed_keys=())
        received = self.rules[player].codec.validate_blob(after[-1])
        witness = MigrationWitness(sender["member_id"], context_from(sender["context"]),
            sender["key"], sender["evidence_digest"],
            IdentityWitness(context_from(receiver["context"]), received.key, received.sha256, 1))
        return TradeVerification(witness, {"schema": "fixture-native-v1", "command_id": command["command_id"]},
                                 {"schema": "fixture-save-v1", "sha256": hashlib.sha256(after[-1]).hexdigest()})

    def auxiliary(self, trade, player, command, receipt):
        if receipt.get("no_effect") is not True:
            raise JournalError("verified retirement/closure required")
        return receipt

    def finalize(self, rules, trade, migrations):
        if self.fail_finalize:
            raise JournalError("injected rule migration failure")
        rules["owners"] = {w.after.context.player: w.member_id for w in migrations}
        rules["parties"] = {p: trade["applied"][p]["after"] for p in ("a", "b")}
        rules["link_commits"] += 1
        return rules


class Run:
    def __init__(self, tmp_path, variants=("red", "blue"), *, identical=False, evolution=False):
        self.path = tmp_path / "coordinator.sqlite3"
        self.now = 1_000_000
        self.sequence = 100
        self.variants = dict(zip(("a", "b"), variants, strict=True))
        self.contexts = {p: IdentityContext(p, "gen1_rby", SaveIdentity("0000", "SAME"),
            hashlib.sha256(v.encode()).hexdigest(), p*32, ("3" if p == "a" else "4")*32)
            for p, v in self.variants.items()}
        registry = IdentityRegistry(RUN)
        members, parties = {}, {}
        for p in ("a", "b"):
            registry.bind_context(self.contexts[p])
            codec = PartyCodec(self.variants[p])
            species = (147 if p == "a" else 38) if evolution else 153
            raw = make_blob(codec, species=species, dv=0x1000 if identical or p == "a" else 0x2000)
            mon = codec.validate_blob(raw)
            members[p] = registry.acquire(self.op(), self.op(), IdentityWitness(self.contexts[p], mon.key, mon.sha256, 1))["member_id"]
            parties[p] = [raw.hex().upper()]
        self.link = registry.create_link("a", self.op(), list(members.values()))["link_id"]
        self.journal = ProtocolJournal(self.path, run_id=RUN, contract_hash=CONTRACT)
        self.policy = Policy(self.variants, self.contexts)
        self.service = self.coordinator()
        self.journal.bootstrap(self.service.initial_state(
            {"link_id": self.link, "alive": True, "owners": members, "parties": parties, "link_commits": 0},
            registry.document(), components={"unrelated": {"preserve": True}}))
        self.original = self.journal.snapshot().state

    def op(self):
        self.sequence += 1
        return f"{self.sequence:032x}"

    def coordinator(self):
        return TradeCoordinator(self.journal, self.policy, clock=lambda: self.now, new_id=self.op)

    def reopen(self):
        self.journal.close()
        self.journal = ProtocolJournal(self.path, run_id=RUN, contract_hash=CONTRACT)
        self.service = self.coordinator()

    def command(self, player, name):
        return next(c for c in self.journal.pending(player) if c["cmd"] == name)

    def event(self, player, event, command, receipt, *, operation=None):
        message = {"event": event, "transaction_id": self.tx, "command_id": command["command_id"],
                   "command_sequence": command["command_sequence"], "receipt": receipt}
        op = operation or self.op()
        return self.service.handle(player, op, message, owner=self.policy.owners[player]), op, message

    def offer(self, initiator="a"):
        op = self.op()
        msg = {"event": "trade_offer", "payload": {"link": self.link}}
        result = self.service.handle(initiator, op, msg, owner=self.policy.owners[initiator])
        self.tx, self.initiator = result["transaction_id"], initiator
        return op, msg

    def accept(self, accepted=True):
        peer = "b" if self.initiator == "a" else "a"
        return self.event(peer, "trade_decision", self.command(peer, "native_trade_prompt"),
            {"schema": "fixture-decision-v1", "accepted": accepted, "native_prompt": True})

    def control(self, action, *, details=None, operation=None):
        return self.service.control(action, self.tx, operation or self.op(), authority=self.policy.control, details=details)

    def ready(self, player):
        command = self.command(player, "native_trade_prepare")
        return self.event(player, "trade_ready", command, {"schema": "fixture-ready-v1",
            "snapshot": command["payload"]["snapshot"], "held": True})

    def committed(self):
        self.offer();self.accept();self.control("prepare");self.ready("a");self.ready("b");self.control("commit")

    def apply(self, player):
        command = self.command(player, "native_trade_commit")
        tx = self.journal.record(NAMESPACE, self.tx).value
        peer = "b" if player == "a" else "a"
        incoming = bytes.fromhex(tx["proposal"]["participants"][peer]["snapshot"]["party"][0])
        outcome = self.policy.rules[player].outcomes(incoming)[0]
        after = [outcome.blob.hex().upper()]
        self.event(player, "trade_applied", command, {"schema": "fixture-applied-v1", "after": after,
            "native_complete": True, "command_id": command["command_id"],
            "prepared_digest": command["payload"]["prepared_digest"]})
        return command, after

    def verify(self, player, command, after):
        return self.event(player, "trade_verified", command, {"schema": "fixture-verified-v1", "after": after, "saved": True})


@pytest.fixture
def run(tmp_path):
    value = Run(tmp_path)
    yield value
    value.journal.close()


@pytest.mark.parametrize("variants", list(product(TITLES, repeat=2)))
@pytest.mark.parametrize("initiator", ["a", "b"])
def test_every_ordered_pair_and_initiator_commits_only_after_both_verified(tmp_path, variants, initiator):
    run = Run(tmp_path, variants, identical=variants == ("yellow", "yellow"), evolution=variants != ("yellow", "yellow"))
    try:
        run.offer(initiator);run.accept();run.control("prepare")
        run.ready("b")
        assert run.service.status(run.tx)["phase"] == "preparing"
        assert not any(c["cmd"] == "native_trade_commit" for p in ("a", "b") for c in run.journal.pending(p))
        run.ready("a")
        assert run.service.status(run.tx)["phase"] == "both_prepared"
        run.control("commit")
        assert run.service.status(run.tx)["phase"] == "commit_persisted"
        for p in ("a", "b"):
            command = run.command(p, "native_trade_commit")
            assert run.service.authorize_delivery(p, command["command_id"], owner=run.policy.owners[p])["body"]["transaction_id"] == run.tx
            run.control("dispatched", details={"player": p, "command_id": command["command_id"], "command_sequence": command["command_sequence"]})
        a_command, a_after = run.apply("a");run.verify("a", a_command, a_after)
        assert run.journal.snapshot().state["identities"] == run.original["identities"]
        assert run.journal.snapshot().state["rules"]["owners"] == run.original["rules"]["owners"]
        run.reopen()
        b_command, b_after = run.apply("b");run.verify("b", b_command, b_after)
        assert run.service.status(run.tx)["phase"] == "both_verified"
        assert run.journal.snapshot().state["identities"] == run.original["identities"]
        op = run.op()
        run.control("finalize", operation=op)
        final = run.journal.snapshot()
        assert final.state["rules"]["link_commits"] == 1 and final.state["active_trade"] is None
        assert final.state["rules"]["owners"] == {p: run.original["rules"]["owners"]["b" if p == "a" else "a"] for p in ("a", "b")}
        restored = IdentityRegistry.restore(final.state["identities"], run_id=RUN)
        assert restored.document()["links"][run.link]["members"] == run.original["identities"]["links"][run.link]["members"]
        assert final.state["components"] == run.original["components"]
        run.reopen()
        run.control("finalize", operation=op)
        assert run.journal.snapshot() == final
        assert all([c["cmd"] for c in run.journal.pending(p)] == ["native_trade_release"] for p in ("a", "b"))
        history = run.journal.record(NAMESPACE, run.tx).value["history"]
        assert [entry["phase"] for entry in history] == [
            "offered", "accepted", "preparing", "both_prepared", "commit_persisted",
            "commit_dispatched", "both_applied", "both_verified", "link_committed"]
    finally:
        run.journal.close()


def test_offer_retry_and_simultaneous_offer_do_not_create_another_transaction(run):
    op, message = run.offer()
    before = run.journal.snapshot()
    assert run.service.handle("a", op, message, owner=run.policy.owners["a"])["transaction_id"] == run.tx
    assert run.journal.snapshot() == before
    with pytest.raises(JournalError, match="already active"):
        run.service.handle("b", run.op(), message, owner=run.policy.owners["b"])
    assert run.journal.snapshot() == before


@pytest.mark.parametrize("case", ["decline", "cancel", "expiry", "late-accept", "disconnect"])
def test_precommit_termination_never_schedules_commit(run, case):
    run.offer()
    if case == "decline": run.accept(False)
    elif case == "cancel":
        run.service.handle("a", run.op(), {"event": "trade_cancel", "transaction_id": run.tx, "reason": "user"}, owner=run.policy.owners["a"])
    elif case == "disconnect": run.control("interrupt", details={"reason": "disconnect"})
    else:
        run.now += 300_000
        if case == "expiry": run.control("expire")
        else: run.accept()
    assert run.journal.snapshot().state["active_trade"] is None
    assert run.journal.snapshot().state["identities"] == run.original["identities"]
    assert not any(c["cmd"] == "native_trade_commit" for p in ("a", "b") for c in run.journal.pending(p))
    assert run.service.status(run.tx)["phase"] in {"cancelled", "declined", "expired"}


def test_ready_and_fresh_commit_authority_are_both_required(run):
    run.offer();run.accept();run.control("prepare");run.ready("a")
    with pytest.raises(JournalError, match="both current"):
        run.control("commit")
    run.ready("b");run.policy.allow_commit = False
    before = run.journal.snapshot()
    with pytest.raises(JournalError, match="fresh"):
        run.control("commit")
    assert run.journal.snapshot() == before


def test_one_sided_application_stays_forward_only_through_disconnect_and_reopen(run):
    run.committed()
    a_command, a_after = run.apply("a");run.verify("a", a_command, a_after)
    b_id = run.command("b", "native_trade_commit")["command_id"]
    run.control("interrupt", details={"reason": "connection_lost"})
    run.reopen()
    assert run.service.status(run.tx)["recovery_required"]
    with pytest.raises(JournalError, match="authority"):
        run.service.authorize_delivery("b", b_id, owner=run.policy.owners["b"])
    with pytest.raises(JournalError, match="forward-only"):
        run.service.handle("a", run.op(), {"event": "trade_cancel", "transaction_id": run.tx, "reason": "cancel"}, owner=run.policy.owners["a"])
    run.policy.recovery = True
    assert run.service.authorize_delivery("b", b_id, owner=run.policy.owners["b"])["command_id"] == b_id
    b_command, b_after = run.apply("b");run.verify("b", b_command, b_after)
    run.control("finalize")
    assert run.journal.snapshot().state["rules"]["link_commits"] == 1


@pytest.mark.parametrize("stage", ["prepare", "commit", "finalize"])
def test_sql_failure_keeps_trade_state_outboxes_and_ownership_together(run, stage):
    run.offer();run.accept()
    if stage != "prepare":
        run.control("prepare");run.ready("a");run.ready("b")
    if stage == "finalize":
        run.control("commit")
        for p in ("a", "b"):
            command, after = run.apply(p);run.verify(p, command, after)
    before = run.journal.snapshot()
    record = run.journal.record(NAMESPACE, run.tx)
    pending = {p: run.journal.pending(p) for p in ("a", "b")}
    run.journal._db.execute("CREATE TRIGGER fail_trade BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.DatabaseError):
        run.control(stage)
    assert run.journal.snapshot() == before and run.journal.record(NAMESPACE, run.tx) == record
    assert {p: run.journal.pending(p) for p in ("a", "b")} == pending


def test_invalid_native_or_save_evidence_never_advances_or_acks_commit(run):
    run.committed()
    command = run.command("a", "native_trade_commit")
    before = run.journal.snapshot()
    with pytest.raises(JournalError, match="native"):
        run.event("a", "trade_applied", command, {"schema": "fake", "native_complete": False})
    assert run.journal.snapshot() == before
    command, after = run.apply("a")
    with pytest.raises(JournalError, match="save-file"):
        run.event("a", "trade_verified", command, {"schema": "fake", "after": after, "saved": False})
    assert run.journal.command("a", command["command_id"])["outcome"] is None
    assert run.journal.snapshot().state["identities"] == run.original["identities"]


def test_wrong_owner_command_sequence_and_clock_are_rejected_before_mutation(run):
    run.offer()
    prompt = run.command("b", "native_trade_prompt")
    msg = {"event": "trade_decision", "transaction_id": run.tx, "command_id": prompt["command_id"],
           "command_sequence": prompt["command_sequence"], "receipt": {"schema": "decision", "accepted": True, "native_prompt": True}}
    before = run.journal.snapshot()
    with pytest.raises(JournalError, match="authority"):
        run.service.handle("b", run.op(), msg, owner=object())
    with pytest.raises(JournalError, match="sequence"):
        run.service.handle("b", run.op(), {**msg, "command_sequence": True}, owner=run.policy.owners["b"])
    run.now -= 1
    with pytest.raises(JournalError, match="clock"):
        run.service.handle("b", run.op(), msg, owner=run.policy.owners["b"])
    assert run.journal.snapshot() == before


def test_retired_prepare_requires_verified_no_effect_ack_and_cannot_restart_trade(run):
    run.offer();run.accept();run.control("prepare")
    command = run.command("a", "native_trade_prepare")
    with pytest.raises(JournalError, match="typed"):
        run.event("a", "trade_ack", command, {"schema": "retirement", "no_effect": True})
    run.control("interrupt", details={"reason": "disconnected_precommit"})
    with pytest.raises(JournalError, match="retired"):
        run.ready("a")
    run.event("a", "trade_ack", command, {"schema": "retirement", "no_effect": True})
    assert run.journal.command("a", command["command_id"])["outcome"] == "ACK"
    assert run.service.status(run.tx)["phase"] == "cancelled"
    assert run.journal.snapshot().state["identities"] == run.original["identities"]


def test_wrong_player_and_changed_command_body_never_enter_delivery_or_receipts(run):
    run.committed()
    original = run.command("a", "native_trade_commit")
    with pytest.raises(JournalError, match="wrong player"):
        run.service.authorize_delivery("b", original["command_id"], owner=run.policy.owners["b"])
    body = {key: value for key, value in original.items() if key not in {"command_id", "command_sequence"}}
    body["payload"]["prepared_digest"] = "f"*64
    snapshot = run.journal.snapshot()
    result = run.journal.commit("a", run.op(), {"event": "injected-unrelated-writer"},
        expected_revision=snapshot.revision, state=snapshot.state, commands={"a": [body], "b": []}, result={"test": True})
    with pytest.raises(JournalError, match="body differs"):
        run.service.authorize_delivery("a", result.command_ids[0], owner=run.policy.owners["a"])
    assert run.service.status(run.tx)["applied_players"] == []


def test_final_rule_failure_publishes_neither_identity_migration_nor_release(run):
    run.committed()
    for player in ("a", "b"):
        command, after = run.apply(player);run.verify(player, command, after)
    before = run.journal.snapshot()
    run.policy.fail_finalize = True
    with pytest.raises(JournalError, match="migration failure"):
        run.control("finalize")
    assert run.journal.snapshot() == before
    assert all(not run.journal.pending(p) for p in ("a", "b"))
    assert run.service.status(run.tx)["phase"] == "both_verified"


def test_persisted_status_reads_are_detached_and_cannot_renew_or_commit(run):
    run.committed()
    before = run.journal.snapshot()
    status = run.service.status(run.tx)
    status["phase"] = "link_committed"
    run.now += 1_000_000
    assert run.service.status(run.tx)["phase"] == "commit_persisted"
    assert run.journal.snapshot() == before


@pytest.mark.parametrize("moment", ["before", "after"])
def test_real_process_death_around_commit_preserves_both_outboxes_and_record_together(run, moment):
    run.offer();run.accept();run.control("prepare");run.ready("a");run.ready("b")
    before = run.journal.snapshot()
    transaction_id = run.tx
    run.journal.close()
    program = """
import os
from server.protocol_journal import ProtocolJournal
from server.trade_coordinator import TradeCoordinator
from tests.unit.test_trade_coordinator import Policy, context_from, RUN, CONTRACT
j=ProtocolJournal(PATH,run_id=RUN,contract_hash=CONTRACT)
state=j.snapshot().state
contexts={p:context_from(v) for p,v in state['identities']['contexts'].items()}
policy=Policy({'a':'red','b':'blue'},contexts)
real=j._db
class Die:
 def __getattr__(self,name):return getattr(real,name)
 def commit(self):
  if MOMENT=='before':os._exit(73)
  real.commit();os._exit(73)
j._db=Die()
TradeCoordinator(j,policy,clock=lambda:1000000).control('commit',TX,'f'*32,authority=policy.control)
"""
    prefix = f"PATH={str(run.path)!r}\nTX={transaction_id!r}\nMOMENT={moment!r}\n"
    result = subprocess.run([sys.executable, "-c", prefix+program], capture_output=True, text=True)
    assert result.returncode == 73, result.stderr
    run.journal = ProtocolJournal(run.path, run_id=RUN, contract_hash=CONTRACT)
    run.service = run.coordinator()
    if moment == "before":
        assert run.journal.snapshot() == before
        assert all(not run.journal.pending(p) for p in ("a", "b"))
        assert run.service.status(run.tx)["phase"] == "both_prepared"
    else:
        assert run.service.status(run.tx)["phase"] == "commit_persisted"
        assert all(len(run.journal.pending(p)) == 1 for p in ("a", "b"))
    run.control("commit", operation="f"*32)
    assert all(len(run.journal.pending(p)) == 1 for p in ("a", "b"))


def test_uncertain_finalize_return_replays_without_a_second_link_migration(run):
    run.committed()
    for p in ("a", "b"):
        cmd, after = run.apply(p);run.verify(p, cmd, after)
    real = run.journal._db
    class FailAfter:
        def __getattr__(self, name): return getattr(real, name)
        def commit(self):
            real.commit()
            raise OSError("uncertain return")
    run.journal._db = FailAfter()
    operation = run.op()
    with pytest.raises(OSError, match="uncertain"):
        run.control("finalize", operation=operation)
    run.journal._db = real
    saved = run.journal.snapshot()
    run.control("finalize", operation=operation)
    assert run.journal.snapshot() == saved and saved.state["rules"]["link_commits"] == 1
    assert all(len(run.journal.pending(p)) == 1 for p in ("a", "b"))


@pytest.mark.parametrize("wrong", ["proposal", "ready", "applied", "verified"])
def test_raw_booleans_cannot_replace_validated_phase_evidence(run, wrong):
    if wrong == "proposal":
        run.policy.offer = lambda *args: True
        with pytest.raises(JournalError, match="validated"):
            run.offer()
        assert run.journal.snapshot().state["active_trade"] is None
        return
    run.offer();run.accept();run.control("prepare")
    if wrong == "ready":
        run.policy.ready = lambda *args: True
        with pytest.raises(JournalError, match="prepared"):
            run.ready("a")
    else:
        run.ready("a");run.ready("b");run.control("commit")
        if wrong == "applied":
            run.policy.applied = lambda *args: True
            with pytest.raises(JournalError, match="evidence"):
                run.apply("a")
        else:
            command, after = run.apply("a")
            run.policy.verified = lambda *args: True
            with pytest.raises(JournalError, match="independent"):
                run.verify("a", command, after)
    assert run.journal.snapshot().state["identities"] == run.original["identities"]
    assert run.journal.snapshot().state["rules"]["link_commits"] == 0


def test_stale_ready_snapshot_and_changed_identity_context_cannot_commit(run):
    run.offer();run.accept();run.control("prepare")
    command = run.command("a", "native_trade_prepare")
    bad = copy.deepcopy(command["payload"]["snapshot"])
    bad["party"] = list(reversed(bad["party"])) + bad["party"]
    with pytest.raises(JournalError, match="moved"):
        run.event("a", "trade_ready", command, {"schema": "fixture-ready-v1", "snapshot": bad, "held": True})
    assert run.journal.command("a", command["command_id"])["outcome"] is None
    run.ready("a");run.ready("b")
    snapshot = run.journal.snapshot()
    registry = IdentityRegistry.restore(snapshot.state["identities"], run_id=RUN)
    previous = run.contexts["a"]
    changed = IdentityContext(previous.player, previous.game_id, previous.save_identity,
                              previous.binding_digest, "9"*32, previous.physical_instance)
    registry.bind_context(changed)
    state = snapshot.state
    state["identities"] = registry.document()
    run.journal.commit("a", run.op(), {"event": "validated-context-replacement"},
        expected_revision=snapshot.revision, state=state, commands={"a": [], "b": []}, result={"ack": "ACK"})
    before = run.journal.snapshot()
    with pytest.raises(JournalError, match="context"):
        run.control("commit")
    assert run.journal.snapshot() == before
