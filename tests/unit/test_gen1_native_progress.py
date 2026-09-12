"""After a reopen the live window cache is gone; verification reads the exact durable window
record instead, and refuses when it is missing, wrong or belongs to another command."""

import copy
import secrets

import pytest

from server.execution_window import issue
from server.gen1_native_frame_accounting import persist_grant
from server.gen1_native_progress import durable_progress, progress_for
from server.gen1_native_windows import COMPONENT
from server.protocol_journal import JournalError
from tests.unit.test_gen1_native_execution import (
    case,  # noqa: F401  (pytest fixtures, resolved by name)
    verify,
)
from tests.unit.test_gen1_native_policy import evidence  # noqa: F401
from tests.unit.test_gen1_native_windows import request_for


@pytest.fixture
def durable(request, monkeypatch):
    from server import gen1_native_progress as progress_module
    monkeypatch.setattr(progress_module, "enrolled_process", lambda document, player: 123)
    """The verified-file fixture with its COMMIT window journaled durably and the live cache emptied,
    i.e. the state a reopened runtime is in when the verified receipt arrives."""
    policy, trade, command, receipt = request.getfixturevalue("evidence")
    run = policy.runtime
    execution = policy.execution
    run.free_service = True
    run.native_trade = True
    run.verify_operation_execution = execution
    base = request.getfixturevalue("case")
    _value, _policy, _command, window = base
    execution.observed.clear()  # the evidence fixture stubs a live window; use a really verified one
    proof = verify(base, window)
    grant_request = request_for(proof)
    persist_grant(run, "a", grant_request, issue(grant_request, proof), window)
    execution.observed.clear()
    execution.published.clear()
    return policy, trade, command, receipt, run


def test_a_reopened_runtime_verifies_from_the_durable_window(durable):
    policy, trade, command, receipt, run = durable
    binding = run.gate.sessions["a"].metadata["control_binding"]
    progress = progress_for(policy.execution, "a", command["command_id"], binding)
    assert progress["durable"] is True and progress["frame"] == 100 and progress["armed"] is False
    proof = policy.verified(trade, "a", command, receipt)
    assert proof.save_receipt == receipt["file"]
    # Replay: the same receipt verifies to the same proof; nothing is granted or mutated.
    assert policy.verified(trade, "a", command, receipt).save_receipt == proof.save_receipt
    assert policy.execution.observed == {} and COMPONENT in run.state().document()["components"]


@pytest.mark.parametrize("fault", ["missing", "other_command", "incomplete", "not_selected", "frame_outside"])
def test_wrong_or_missing_durable_windows_refuse(durable, fault):
    policy, trade, command, receipt, run = durable
    document = run.state().document()
    if fault == "missing":
        run.journal_windows_backup = document["components"].pop(COMPONENT)
        run.state = lambda document=document: type("S", (), {"document": staticmethod(lambda: document)})()
        with pytest.raises(JournalError, match="outside the owned native frame window"):
            policy.verified(trade, "a", command, receipt)
    elif fault == "other_command":
        windows = document["components"][COMPONENT]["a"]
        entry = windows.pop(command["command_id"])
        windows[secrets.token_hex(16)] = entry
        run.state = lambda document=document: type("S", (), {"document": staticmethod(lambda: document)})()
        with pytest.raises(JournalError, match="outside the owned native frame window"):
            policy.verified(trade, "a", command, receipt)
    elif fault == "incomplete":
        entry = document["components"][COMPONENT]["a"][command["command_id"]]
        entry["scope"] = {**entry["scope"], "operation_id": secrets.token_hex(16)}
        run.state = lambda document=document: type("S", (), {"document": staticmethod(lambda: document)})()
        with pytest.raises(JournalError, match="incomplete"):
            policy.verified(trade, "a", command, receipt)
    elif fault == "not_selected":
        run.native_trade = False
        assert durable_progress(run, "a", command["command_id"]) is None
        with pytest.raises(JournalError, match="outside the owned native frame window"):
            policy.verified(trade, "a", command, receipt)
    elif fault == "frame_outside":
        bad = copy.deepcopy(receipt)
        bad["file"]["frame"] = 100 + 121  # past the 120-frame flush window of the durable progress
        with pytest.raises(JournalError):
            policy.verified(trade, "a", command, bad)


# ── a real reopen: new runtime object, fresh admission and control binding ─────────────────

def test_the_previously_issued_receipt_verifies_after_a_real_reopen_with_a_fresh_binding(request, monkeypatch):
    """Close the runtime, open it again (new Gen1Runtime on the same journal), admit both players
    afresh (new session ids, epoch and control binding), bind a new execution policy: the durable
    window still bounds the receipt that was produced inside it, and only that one."""
    from server import gen1_native_progress as progress_module
    from server.gen1_native_execution import NativeExecutionPolicy
    from server.gen1_native_policy import NativeTradePolicy
    from server.trade_coordinator import NAMESPACE

    policy, trade, command, receipt, run = request.getfixturevalue("durable")
    execution = policy.execution
    rules, manifests = execution.rules, execution.manifests
    native = receipt["native"]
    base = request.getfixturevalue("case")
    value = base[0]
    old_binding = run.gate.sessions["a"].metadata["control_binding"]
    monkeypatch.setattr(progress_module, "enrolled_process", lambda document, player: 123)
    value.close()
    value.open()
    reopened = value.runtime
    value.admit("a"); value.admit("b"); value.control("a"); value.control("b")
    new_binding = reopened.gate.sessions["a"].metadata["control_binding"]
    assert new_binding["binding_digest"] != old_binding["binding_digest"]
    reopened.free_service = True
    reopened.native_trade = True
    fresh_execution = NativeExecutionPolicy(rules=rules, manifests=manifests)
    fresh_execution.bind(reopened)
    assert fresh_execution.observed == {}
    fresh = NativeTradePolicy()
    fresh.runtime = reopened
    fresh.execution = fresh_execution
    fresh.rules, fresh.manifests = rules, manifests
    fresh.prepared = policy.prepared  # preparation cache as gen1_native_preparation restores it
    trade = reopened.journal.record(NAMESPACE, trade["id"]).value
    assert trade["recovery_required"] is True
    trade["applied"] = {"a": copy.deepcopy(native)}
    proof = fresh.verified(trade, "a", command, receipt)
    assert proof.save_receipt == receipt["file"]
    # A NEW flush after the reconnect (frame past the durable window) is not authorized by it.
    later = copy.deepcopy(receipt)
    later["file"]["frame"] = 100 + 121
    with pytest.raises(JournalError):
        fresh.verified(trade, "a", command, later)
    # A receipt that is not the journaled applied receipt is refused before any window is consulted.
    foreign = copy.deepcopy(receipt)
    foreign["native"] = {**native, "after": {**native["after"], "save_region_hex": "00" * 4}}
    with pytest.raises(JournalError, match="complete native and file-image evidence"):
        fresh.verified(trade, "a", command, foreign)
    # A different emulator process (enrollment host) gets no window from the durable record.
    monkeypatch.setattr(progress_module, "enrolled_process", lambda document, player: 999)
    with pytest.raises(JournalError, match="outside the owned native frame window"):
        fresh.verified(trade, "a", command, receipt)
    value.close()
