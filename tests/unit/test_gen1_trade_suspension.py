"""Actual server lifecycle/journal interruption; physical recovery is not modeled as success."""
import sqlite3

import pytest

from server.protocol_journal import JournalError
from server.trade_coordinator import NAMESPACE
from tests.unit.test_gen1_runtime_trade import case  # noqa: F401


def at_phase(case, phase):  # noqa: F811
    case.offer()
    if phase == "offered":return
    case.accept();case.trade_control("prepare")
    if phase == "preparing":return
    case.ready("a");case.ready("b")
    if phase == "both_prepared":return
    case.trade_control("commit")
    if phase == "one_verified":case.apply_verify("a")


@pytest.mark.parametrize("phase", ["offered", "preparing", "both_prepared", "commit_persisted", "one_verified"])
@pytest.mark.parametrize("trigger", ["disconnect", "reopen", "watchdog"])
def test_loss_of_runtime_authority_is_a_durable_trade_interruption(case, phase, trigger):  # noqa: F811
    at_phase(case, phase)
    before = case.runtime.journal.record(NAMESPACE, case.tx).value
    pending = {p:case.runtime.journal.pending(p) for p in ("a", "b")}
    identities = case.runtime.state().document()["identities"]
    if trigger == "disconnect":
        assert case.runtime.disconnect("a", case.owners["a"])
    elif trigger == "reopen":
        case.close();case.open()
    else:
        case.time += 3
        with pytest.raises(ValueError):case.control("a")
    after = case.runtime.journal.record(NAMESPACE, case.tx).value
    assert not case.runtime.gate.sessions
    assert case.runtime.state().barrier.ticket() is None
    assert case.runtime.state().document()["identities"] == identities
    if phase in {"commit_persisted", "one_verified"}:
        assert after["phase"] == before["phase"]
        assert after["recovery_required"] and after["interruption"]["reason"]
        assert after["applied"] == before["applied"] and after["verified"] == before["verified"]
        assert {p:case.runtime.journal.pending(p) for p in ("a", "b")} == pending
        # Restoring sockets is not physical recovery. The policy still refuses
        # stored native commands under replacement connection owners.
        case.admit("a");case.admit("b")
        with pytest.raises(JournalError, match="authority"):
            case.runtime.delivery_commands("b")
    else:
        assert after["phase"] == "cancelled"
        for player in ("a", "b"):
            queue = case.runtime.journal.pending(player)
            assert queue[:len(pending[player])] == pending[player]
            assert queue[-1]["cmd"] == "native_trade_abort"
    assert case.tx in case.runtime.state().barrier.document()["blockers"]


def test_unknown_disconnect_cannot_cancel_an_owned_offer(case):  # noqa: F811
    case.offer();before = case.runtime.journal.snapshot()
    assert case.runtime.disconnect("a", object()) is False
    assert case.runtime.journal.snapshot() == before


def test_interruption_failure_clears_owners_and_retains_atomic_prestate(case):  # noqa: F811
    case.committed();before = case.runtime.journal.snapshot()
    record = case.runtime.journal.record(NAMESPACE, case.tx)
    case.runtime.journal._db.execute(
        "CREATE TRIGGER refuse_interrupt BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.DatabaseError):case.runtime.disconnect("a", case.owners["a"])
    assert not case.runtime.gate.sessions and case.runtime._failed
    assert case.runtime.journal.snapshot() == before
    assert case.runtime.journal.record(NAMESPACE, case.tx) == record
    assert case.runtime.state().barrier.ticket() is None


def test_internal_suspension_capability_cannot_commit_or_deliver(case):  # noqa: F811
    at_phase(case, "both_prepared")
    before = case.runtime.journal.snapshot()
    with pytest.raises(JournalError, match="authority"):
        case.runtime.trade_control("commit", case.tx, case.token(), authority=case.runtime._suspension_authority)
    assert case.runtime.journal.snapshot() == before
