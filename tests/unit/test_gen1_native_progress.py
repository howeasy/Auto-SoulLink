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
def durable(request):
    """The verified-file fixture with its COMMIT window journaled durably and the live cache emptied,
    i.e. the state a reopened runtime is in when the verified receipt arrives."""
    policy, trade, command, receipt = request.getfixturevalue("evidence")
    run = policy.runtime
    execution = policy.execution
    run.free_service = True
    run.native_trade = True
    run.verify_operation_execution = execution
    case = request.getfixturevalue("case")
    _value, _policy, _command, window = case
    execution.observed.clear()  # the evidence fixture stubs a live window; use a really verified one
    proof = verify(case, window)
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
