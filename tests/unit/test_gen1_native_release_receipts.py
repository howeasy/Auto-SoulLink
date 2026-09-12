"""Typed closure binds the authoritative release to the persisted verified native result."""
import copy

import pytest

from server.gen1_native_trade_receipts import verify_native_release
from server.protocol_journal import JournalError


@pytest.fixture
def evidence():
    body = {"cmd": "native_trade_release", "player": "a", "transaction_id": "a"*32,
        "proposal_digest": "b"*64, "payload": {"schema": "paired-trade-release-v1", "finalization_event": "c"*32}}
    command = {"command_id": "d"*32, "command_sequence": 7, "body": body}
    native = {"command_id": "e"*32, "transaction_id": "a"*32, "proposal_digest": "b"*64,
        "context_generation": "f"*32, "final_sha1": "1"*40,
        "after": {"schema": "explicit-previously-verified-native-fixture", "party": ["actual result is verified upstream"]}}
    trade = {"id": "a"*32, "proposal_digest": "b"*64, "phase": "link_committed", "applied": {"a": native}}
    receipt = {"schema": "rby-native-release-receipt-v1", "command_id": "d"*32, "command_sequence": 7,
        "native_command_id": "e"*32, **{k:v for k,v in copy.deepcopy(native).items() if k != "command_id"}}
    return command, receipt, trade


def test_exact_finalized_native_closure_is_accepted_without_mutating_inputs(evidence):
    command, receipt, trade = evidence
    before = copy.deepcopy(evidence)
    assert verify_native_release(command, receipt, trade=trade) == receipt
    assert evidence == before


@pytest.mark.parametrize("field", ["command_id", "command_sequence", "native_command_id", "transaction_id",
    "proposal_digest", "context_generation", "final_sha1", "after", "schema", "extra", "not_finalized", "foreign_trade"])
def test_foreign_stale_incomplete_or_unfinalized_closure_is_refused(evidence, field):
    command, receipt, trade = evidence
    if field == "not_finalized":trade["phase"] = "both_verified"
    elif field == "foreign_trade":trade["id"] = "0"*32
    elif field == "command_sequence":receipt[field] = True
    elif field == "after":receipt[field]["party"] = []
    elif field == "extra":receipt["no_effect"] = True
    else:receipt[field] = "0"*len(receipt[field])
    with pytest.raises(JournalError):verify_native_release(command, receipt, trade=trade)
