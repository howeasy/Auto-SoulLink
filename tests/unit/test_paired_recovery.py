import copy
import itertools

import pytest

from server.paired_liveness import PairedLiveness
from server.paired_recovery import RecoveryBarrier, VerifiedReconciliation
from server.protocol_journal import JournalError, ProtocolJournal


def epochs():
    sequence = itertools.count(1)
    return lambda: f"{next(sequence):032x}"


def barrier():
    result = RecoveryBarrier("a" * 64, new_epoch=epochs())
    for player, code in (("a", "b"), ("b", "c")):
        result.bind(player, code * 64, code * 32)
    return result


def proof(state, player):
    doc = state.document()
    return VerifiedReconciliation(player, doc["epoch"], **doc["bindings"][player],
                                  history_digest=doc["history_digest"], checkpoint_digest="f" * 64)


def ready(state):
    for player in ("a", "b"):
        state.reconcile(player, proof(state, player))
    return state.ticket()


def test_resume_requires_both_trusted_proofs_for_same_epoch_and_history():
    state = barrier()
    assert state.ticket() is None
    state.reconcile("a", proof(state, "a"))
    assert state.ticket() is None
    with pytest.raises(JournalError, match="trusted"):
        state.reconcile("b", vars(proof(state, "b")))
    state.reconcile("b", proof(state, "b"))
    assert state.ticket() is not None
    assert state.status()["paired_reconciled"] is True


@pytest.mark.parametrize("change", ["history", "binding", "context", "obligation", "disconnect", "reset"])
def test_every_relevant_change_revokes_both_proofs_and_old_ticket(change):
    state = barrier()
    old = ready(state)
    old_proofs = {p: proof(state, p) for p in ("a", "b")}
    if change == "history":
        state.set_history("d" * 64)
    elif change == "binding":
        state.bind("a", "d" * 64, "b" * 32)
    elif change == "context":
        state.bind("a", "b" * 64, "d" * 32)
    elif change == "obligation":
        state.set_blockers({"e" * 32: "native mutation readback uncertain"})
    else:
        state.invalidate(change)
    assert state.ticket() is None
    assert state.document()["epoch"] != old["epoch"]
    for player in ("a", "b"):
        with pytest.raises(JournalError):
            state.reconcile(player, old_proofs[player])
    assert not any(state.document()["proofs"].values())


def test_pending_obligation_removal_still_requires_fresh_paired_reconciliation():
    state = barrier()
    ready(state)
    state.set_blockers({"e" * 32: "death pending against logical member"})
    with pytest.raises(JournalError, match="pending obligations"):
        state.reconcile("a", proof(state, "a"))
    state.set_blockers({})
    assert state.ticket() is None
    assert ready(state)


def test_noops_preserve_epoch_and_detached_results_cannot_change_authority():
    state = barrier()
    ticket = ready(state)
    assert state.bind("a", "b" * 64, "b" * 32) is False
    assert state.set_history("a" * 64) is False
    assert state.set_blockers({}) is False
    state.reconcile("a", proof(state, "a"))
    detached = state.document()
    detached["bindings"]["a"] = None
    status = state.status()
    status["pending_obligations"]["d" * 32] = "injected"
    assert state.ticket() == ticket


def test_conflicting_proof_cannot_silently_replace_one_half():
    state = barrier()
    state.reconcile("a", proof(state, "a"))
    changed = vars(proof(state, "a")) | {"checkpoint_digest": "e" * 64}
    before = state.document()
    with pytest.raises(JournalError, match="conflicting"):
        state.reconcile("a", VerifiedReconciliation(**changed))
    assert state.document() == before


def test_one_player_proof_or_identical_physical_binding_cannot_supply_both_halves():
    state = barrier()
    state.reconcile("a", proof(state, "a"))
    with pytest.raises(JournalError, match="other player"):
        state.reconcile("b", proof(state, "a"))
    with pytest.raises(JournalError, match="distinct"):
        state.bind("b", "b" * 64, "b" * 32)
    assert state.ticket() is None
    document = state.document()
    document["bindings"]["b"] = dict(document["bindings"]["a"])
    with pytest.raises(JournalError, match="distinct"):
        RecoveryBarrier.restore(document)


@pytest.mark.parametrize("damage", ["schema", "missing_player", "proof_epoch", "proof_identity", "blocked_proof", "unknown"])
def test_restore_refuses_partial_coerced_and_conflicting_recovery_state(damage):
    state = barrier()
    ready(state)
    doc = state.document()
    if damage == "schema":
        doc["schema"] = "old"
    elif damage == "missing_player":
        del doc["bindings"]["b"]
    elif damage == "proof_epoch":
        doc["proofs"]["a"]["epoch"] = "0" * 32
    elif damage == "proof_identity":
        doc["proofs"]["b"]["binding_digest"] = "e" * 64
    elif damage == "blocked_proof":
        doc["blockers"] = {"d" * 32: "unresolved"}
    else:
        doc["coerced"] = True
    with pytest.raises(JournalError):
        RecoveryBarrier.restore(doc)


def test_journal_commits_recovery_with_rule_state_and_both_outboxes(tmp_path):
    state = barrier()
    journal = ProtocolJournal(tmp_path / "recovery.db", run_id="a" * 32, contract_hash="b" * 64)
    journal.bootstrap({"rules": {"death": False}, "recovery": state.document()})
    state.set_blockers({"e" * 32: "partner physical death pending"})
    payload = {"event": "faint", "logical_member_id": "f" * 32}
    snapshot = {"rules": {"death": True}, "recovery": state.document()}
    journal.commit("a", "d" * 32, payload, expected_revision=0, state=snapshot,
                   commands={"a": [{"cmd": "notice"}], "b": [{"cmd": "force_faint"}]}, result={"ack": "ACK"})
    journal.close()
    journal = ProtocolJournal(tmp_path / "recovery.db", run_id="a" * 32, contract_hash="b" * 64)
    assert journal.snapshot().state == snapshot
    restored = RecoveryBarrier.restore(journal.snapshot().state["recovery"])
    assert restored.ticket() is None
    assert restored.status()["pending_obligations"] == {"e" * 32: "partner physical death pending"}
    assert journal.pending("a")[0]["cmd"] == "notice"
    assert journal.pending("b")[0]["cmd"] == "force_faint"
    journal.close()


def test_new_server_has_no_liveness_even_when_durable_reconciliation_is_complete():
    state = barrier()
    ready(state)
    restored = RecoveryBarrier.restore(state.document())
    assert restored.ticket() == state.ticket()
    assert PairedLiveness().status()["paired_live"] is False


def live_pair():
    clock = [0.0]
    live = PairedLiveness(clock=lambda: clock[0], new_nonce=epochs())
    for player in ("a", "b"):
        live.open(player, player * 32)
        challenge = live.challenge(player, player * 32)
        assert live.answer(player, player * 32, challenge["challenge"])
    return live, clock


@pytest.mark.parametrize("age,expected", [(0, True), (1.999, True), (2, False), (20, False)])
def test_watchdog_uses_monotonic_wall_time_at_exact_timeout(age, expected):
    live, clock = live_pair()
    clock[0] = age
    assert live.status()["paired_live"] is expected


def test_late_or_duplicate_answers_never_renew_an_old_roundtrip():
    live, clock = live_pair()
    clock[0] = 0.1
    challenge = live.challenge("a", "a" * 32)
    clock[0] = 1.9
    assert live.answer("a", "a" * 32, challenge["challenge"])
    assert not live.answer("a", "a" * 32, challenge["challenge"])
    clock[0] = 2.11
    assert live.status()["players"]["a"]["live"] is False
    with pytest.raises(JournalError, match="expired"):
        live.challenge("a", "a" * 32)
    live.open("a", "c" * 32)
    challenge = live.challenge("a", "c" * 32)
    clock[0] = 4.2
    assert not live.answer("a", "c" * 32, challenge["challenge"])


def test_answer_after_liveness_gap_cannot_hide_timeout_from_coordinator():
    live, clock = live_pair()
    clock[0] = 1.0
    answer = live.challenge("a", "a" * 32)
    clock[0] = 2.1
    # Request itself is still young, but prior execution lease already expired.
    assert not live.answer("a", "a" * 32, answer["challenge"])
    assert live.status()["players"]["a"]["requires_readmission"]
    with pytest.raises(JournalError, match="newly admitted"):
        live.open("a", "a" * 32)


def test_old_connection_cannot_close_or_renew_replacement_session():
    live, clock = live_pair()
    old = live.challenge("a", "a" * 32)
    live.open("a", "c" * 32)
    assert not live.close("a", "a" * 32)
    assert not live.answer("a", "a" * 32, old["challenge"])
    assert live.status()["paired_live"] is False
    new = live.challenge("a", "c" * 32)
    assert live.answer("a", "c" * 32, new["challenge"])
    assert live.status()["paired_live"] is True
    assert live.close("b", "b" * 32)
    assert live.status()["paired_live"] is False


@pytest.mark.parametrize("bad", [-1, float("inf"), float("nan"), True, "later"])
def test_bad_or_reversed_clock_revokes_all_liveness(bad):
    live, clock = live_pair()
    clock[0] = 1
    live.status()
    clock[0] = bad
    with pytest.raises(JournalError, match="clock"):
        live.status()
    clock[0] = 2
    assert not live.status()["paired_live"]


def test_failed_nonce_or_malformed_updates_do_not_change_staged_recovery():
    state = barrier()
    ready(state)
    before = copy.deepcopy(state.document())
    state._new_epoch = lambda: before["epoch"]
    with pytest.raises(JournalError, match="repeated"):
        state.set_history("d" * 64)
    assert state.document() == before
    with pytest.raises(JournalError):
        state.set_blockers({"bad-id": "reason"})
    assert state.document() == before


def test_throwing_clock_clears_prior_session_authority():
    live, clock = live_pair()
    def failed_clock():
        raise RuntimeError("host clock unavailable")
    live.clock = failed_clock
    with pytest.raises(JournalError, match="clock failed"):
        live.status()
    live.clock = lambda: clock[0]
    assert not live.status()["paired_live"]
