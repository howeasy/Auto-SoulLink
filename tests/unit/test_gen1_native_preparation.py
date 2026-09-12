"""Durable both-peer preparation: what NativeTradePolicy.ready verified rides the trade_ready commit,
so a reopened runtime reads the full checkpoint back instead of "no cache, recovery required"."""

import copy
from types import SimpleNamespace

import pytest

from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_native_policy import NativeTradePolicy
from server.gen1_native_preparation import COMPONENT, stored, verify_journal
from server.gen1_trade_preparation import preparation_payload, verify_preparation
from server.protocol import digest
from server.protocol_journal import JournalError
from server.trade_coordinator import NAMESPACE
from tests.unit.test_gen1_runtime_trade import TradeCase
from tests.unit.test_gen1_trade_preparation import checkpoint


def prepared_pair(tmp_path):
    """A paired trade taken through both readies, with the native policy cache populated the way
    NativeTradePolicy.ready fills it (the coordinator's composition hook retains it)."""
    value = TradeCase(tmp_path)
    value.admit("a"); value.admit("b"); value.control("a"); value.control("b")
    manifests = {p: companion_profiles()[v]["manifest"] for p, v in value.variants.items()}
    for p in manifests:
        value.policy.rules[p].rom_sha1 = manifests[p]["final_sha1"]
    fixture = SimpleNamespace(policy=value.policy, contexts=value.policy.contexts,
                              original={"rules": {"parties": {p: [raw.hex().upper()] for p, raw in value.blobs.items()}}})
    points = {p: checkpoint(fixture, p) for p in ("a", "b")}
    value.policy.prepare = lambda trade, p: preparation_payload(trade, p, rules=value.policy.rules, checkpoints=points)
    value.policy.ready = lambda trade, p, command, receipt: verify_preparation(command, receipt, rules=value.policy.rules[p])
    value.offer(); value.accept(); value.trade_control("prepare")
    value.policy.prepared = {"transaction_id": value.tx, "players": {}}
    for p in ("a", "b"):
        value.policy.prepared["players"][p] = {"checkpoint": copy.deepcopy(points[p]),
                                              "save": {"schema": "stub-save-stage", "player": p},
                                              "prompt": {"schema": "stub-prompt-stage", "player": p}}
        command = value.command(p, "native_trade_prepare")
        value.event(p, "trade_ready", command, {"schema": "rby-native-ready-v1", "command_id": command["command_id"],
            "command_sequence": command["command_sequence"], "transaction_id": value.tx,
            "proposal_digest": command["proposal_digest"], "context_generation": value.policy.contexts[p].context_generation,
            "checkpoint": points[p]})
    return value, points


def test_ready_evidence_is_retained_in_the_trade_commit_and_read_back_after_reopen(tmp_path):
    value, points = prepared_pair(tmp_path)
    tx = value.tx
    try:
        document = value.runtime.state().document()
        for p in ("a", "b"):
            entry = stored(document, tx, p)
            assert entry["checkpoint"] == points[p] and entry["checkpoint_digest"] == digest(points[p])
            assert entry["save"] == {"schema": "stub-save-stage", "player": p}
            assert entry["command_id"] == value.runtime.journal.command(p, entry["command_id"])["command_id"]
            trade = value.runtime.journal.record(NAMESPACE, tx).value
            assert trade["ready"][p]["details"]["checkpoint_digest"] == entry["checkpoint_digest"]
        verify_journal(value.runtime.journal, value.runtime.state())
        # COMMIT persists; a reopen then interrupts the trade (recovery required) but must keep
        # the evidence: pre-COMMIT the reopen cancels the trade and the evidence is dropped with it.
        value.trade_control("commit")
    finally:
        value.close()
    # Reopen: a fresh policy with an empty cache reads the committed evidence back, digest-checked.
    value.open()
    try:
        trade = value.runtime.journal.record(NAMESPACE, tx).value
        assert trade["phase"] == "commit_persisted" and trade["recovery_required"] is True
        policy = NativeTradePolicy()
        policy.runtime = value.runtime
        assert policy.prepared == {}
        for p in ("a", "b"):
            assert policy.checkpoint(trade, p) == points[p]
        assert policy.prepared["transaction_id"] == tx and set(policy.prepared["players"]) == {"a", "b"}
        assert policy.commit(trade, value.runtime.state().document(), policy.control)["prepared"] == {
            p: digest(points[p]) for p in ("a", "b")}
        verify_journal(value.runtime.journal, value.runtime.state())
    finally:
        value.close()


def test_a_pre_commit_reopen_cancels_the_trade_and_drops_its_evidence(tmp_path):
    value, _points = prepared_pair(tmp_path)
    tx = value.tx
    value.close()
    value.open()
    try:
        assert value.runtime.journal.record(NAMESPACE, tx).value["phase"] == "cancelled"
        # The cancellation issued abort commands; their provenance stays until they close.
        assert all(value.runtime.journal.pending_ids(p) for p in ("a", "b"))
        assert stored(value.runtime.state().document(), tx, "a") is not None
        verify_journal(value.runtime.journal, value.runtime.state())
        value.admit("a"); value.admit("b"); value.control("a"); value.control("b")
        value.closure("a"); value.closure("b")
        assert stored(value.runtime.state().document(), tx, "a") is None
        assert COMPONENT not in value.runtime.state().document()["components"]
        verify_journal(value.runtime.journal, value.runtime.state())
    finally:
        value.close()


def test_a_tampered_retained_checkpoint_is_refused_not_used(tmp_path):
    value, points = prepared_pair(tmp_path)
    tx = value.tx
    try:
        document = value.runtime.state().document()
        document["components"][COMPONENT][tx]["a"]["checkpoint"]["current_box"] ^= 1

        class Forged:
            def document(self):
                return document

        with pytest.raises(JournalError):
            verify_journal(value.runtime.journal, Forged())
        policy = NativeTradePolicy()
        policy.runtime = SimpleNamespace(state=lambda: Forged())
        trade = value.runtime.journal.record(NAMESPACE, tx).value
        with pytest.raises(JournalError, match="recovery required"):
            policy.checkpoint(trade, "a")
    finally:
        value.close()


def test_a_cache_that_disagrees_with_the_acknowledged_proof_fails_the_ready_commit(tmp_path):
    value = TradeCase(tmp_path)
    value.admit("a"); value.admit("b"); value.control("a"); value.control("b")
    manifests = {p: companion_profiles()[v]["manifest"] for p, v in value.variants.items()}
    for p in manifests:
        value.policy.rules[p].rom_sha1 = manifests[p]["final_sha1"]
    fixture = SimpleNamespace(policy=value.policy, contexts=value.policy.contexts,
                              original={"rules": {"parties": {p: [raw.hex().upper()] for p, raw in value.blobs.items()}}})
    points = {p: checkpoint(fixture, p) for p in ("a", "b")}
    value.policy.prepare = lambda trade, p: preparation_payload(trade, p, rules=value.policy.rules, checkpoints=points)
    value.policy.ready = lambda trade, p, command, receipt: verify_preparation(command, receipt, rules=value.policy.rules[p])
    try:
        value.offer(); value.accept(); value.trade_control("prepare")
        wrong = copy.deepcopy(points["a"]); wrong["current_box"] ^= 1
        value.policy.prepared = {"transaction_id": value.tx, "players": {"a": {"checkpoint": wrong, "save": None, "prompt": None}}}
        command = value.command("a", "native_trade_prepare")
        before = value.runtime.journal.snapshot()
        with pytest.raises(JournalError):
            value.event("a", "trade_ready", command, {"schema": "rby-native-ready-v1", "command_id": command["command_id"],
                "command_sequence": command["command_sequence"], "transaction_id": value.tx,
                "proposal_digest": command["proposal_digest"], "context_generation": value.policy.contexts["a"].context_generation,
                "checkpoint": points["a"]})
        assert value.runtime.journal.snapshot() == before
        assert COMPONENT not in value.runtime.state().document()["components"]
    finally:
        value.close()


def test_a_ready_ack_without_its_verified_stages_cannot_commit(tmp_path):
    """A policy that carries a preparation cache is bound by it: no cache entry, no both_prepared."""
    value = TradeCase(tmp_path)
    value.admit("a"); value.admit("b"); value.control("a"); value.control("b")
    manifests = {p: companion_profiles()[v]["manifest"] for p, v in value.variants.items()}
    for p in manifests:
        value.policy.rules[p].rom_sha1 = manifests[p]["final_sha1"]
    fixture = SimpleNamespace(policy=value.policy, contexts=value.policy.contexts,
                              original={"rules": {"parties": {p: [raw.hex().upper()] for p, raw in value.blobs.items()}}})
    points = {p: checkpoint(fixture, p) for p in ("a", "b")}
    value.policy.prepare = lambda trade, p: preparation_payload(trade, p, rules=value.policy.rules, checkpoints=points)
    value.policy.ready = lambda trade, p, command, receipt: verify_preparation(command, receipt, rules=value.policy.rules[p])
    try:
        value.offer(); value.accept(); value.trade_control("prepare")
        value.policy.prepared = {}   # the cache a native policy would hold, empty
        command = value.command("a", "native_trade_prepare")
        before = value.runtime.journal.snapshot()
        with pytest.raises(JournalError, match="missing"):
            value.event("a", "trade_ready", command, {"schema": "rby-native-ready-v1", "command_id": command["command_id"],
                "command_sequence": command["command_sequence"], "transaction_id": value.tx,
                "proposal_digest": command["proposal_digest"], "context_generation": value.policy.contexts["a"].context_generation,
                "checkpoint": points["a"]})
        assert value.runtime.journal.snapshot() == before
        assert value.runtime.journal.record(NAMESPACE, value.tx).value["ready"] == {}
    finally:
        value.close()


def test_evidence_outlives_link_commit_until_the_releases_are_acknowledged(tmp_path):
    """link_committed is terminal for the coordinator, but the release commands it issues still
    need the preparation provenance; the evidence is dropped only when nothing is pending."""
    value, points = prepared_pair(tmp_path)
    tx = value.tx
    try:
        value.trade_control("commit")
        value.apply_verify("a"); value.apply_verify("b")
        value.trade_control("finalize")
        trade = value.runtime.journal.record(NAMESPACE, tx).value
        assert trade["phase"] == "link_committed"
        assert all(value.runtime.journal.pending_ids(p) for p in ("a", "b"))  # releases pending
        assert stored(value.runtime.state().document(), tx, "a")["checkpoint"] == points["a"]
        verify_journal(value.runtime.journal, value.runtime.state())
        value.closure("a")
        assert stored(value.runtime.state().document(), tx, "b") is not None  # b's release still pending
        value.closure("b")
        assert COMPONENT not in value.runtime.state().document()["components"]
        verify_journal(value.runtime.journal, value.runtime.state())
    finally:
        value.close()
