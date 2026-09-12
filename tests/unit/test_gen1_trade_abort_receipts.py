"""Pre-COMMIT retirement requires idle or independently verified prompt closure."""
import copy
from types import SimpleNamespace

import pytest

from server.gen1_trade_abort_receipts import verify_abort
from server.protocol import digest
from server.protocol_journal import JournalError
from server.trade_coordinator import NAMESPACE
from tests.unit.test_gen1_prompt_execution import case, verify  # noqa: F401
from tests.unit.test_gen1_trade_preparation import checkpoint


@pytest.fixture
def aborted(case):  # noqa: F811
    run,execution,prompt,window=case
    verify(case);intent=window["native"]["intent"]
    receipt={"schema":"rby-native-prompt-v1","command_id":prompt["command_id"],"command_sequence":prompt["command_sequence"],
        "transaction_id":run.tx,"proposal_digest":prompt["body"]["proposal_digest"],
        "context_generation":window["context_generation"],"final_sha1":window["final_sha1"],"result":1,
        "token_hex":intent["token_hex"],"generation":intent["generation"],"before":intent["before"],"after":intent["before"],
        "sequence":["service","prompt","choice"],"counts":{"service":1,"prompt":1,"choice":1}}
    run.event("b","trade_decision",run.command("b","native_trade_prompt"),receipt)
    commands={p:run.runtime.journal.command(p,run.command(p,"native_trade_abort")["command_id"]) for p in ("a","b")}
    closing=copy.deepcopy(window)
    closing.update(command_id=commands["b"]["command_id"],command_sequence=commands["b"]["command_sequence"],
        native={"phase":"prompt_before","prompt_command_id":prompt["command_id"],
            "prompt_intent_digest":digest(intent),"receipt":receipt})
    assert verify(case,closing,commands["b"])
    model=SimpleNamespace(policy=run.policy,contexts=run.policy.contexts,
        original={"rules":{"parties":{p:[raw.hex().upper()] for p,raw in run.blobs.items()}}})
    proofs={}
    for p,command in commands.items():
        proofs[p]={"schema":"rby-trade-abort-v1" if p=="a" else "rby-prompt-closure-v1",
            "command_id":command["command_id"],"command_sequence":command["command_sequence"],
            "transaction_id":run.tx,"proposal_digest":command["body"]["proposal_digest"],
            "context_generation":run.policy.contexts[p].context_generation,"final_sha1":execution.manifests[p]["final_sha1"]}
    proofs["a"]["checkpoint"]=checkpoint(model,"a")
    proofs["b"].update(prompt_command_id=prompt["command_id"],after=receipt["after"])
    policy=SimpleNamespace(runtime=run.runtime,execution=execution,manifests=execution.manifests,rules=execution.rules)
    trade=run.runtime.journal.record(NAMESPACE,run.tx).value
    return policy,trade,commands,proofs


def test_declined_trade_can_retire_both_exact_obligations(aborted):
    policy,trade,commands,proofs=aborted
    for p in ("a","b"):assert verify_abort(policy,trade,p,commands[p],proofs[p])==proofs[p]


@pytest.mark.parametrize("change",["command","sequence","context","receipt","no_window","postcommit"])
def test_incomplete_or_foreign_prompt_return_cannot_retire_abort(aborted,change):
    policy,trade,commands,proofs=aborted
    receipt=proofs["b"]
    if change=="command":receipt["command_id"]="f"*32
    elif change=="sequence":receipt["command_sequence"]=True
    elif change=="context":receipt["context_generation"]="f"*32
    elif change=="receipt":receipt["after"]["map"]+=1
    elif change=="no_window":policy.execution.observed.clear()
    else:trade["phase"]="commit_persisted"
    with pytest.raises(JournalError):verify_abort(policy,trade,"b",commands["b"],receipt)


def test_prompt_owner_cannot_claim_an_idle_no_effect_abort(aborted):
    policy,trade,commands,proofs=aborted
    forged=copy.deepcopy(proofs["b"])
    del forged["prompt_command_id"];del forged["after"]
    forged.update(schema="rby-trade-abort-v1",checkpoint=proofs["a"]["checkpoint"])
    with pytest.raises(JournalError,match="native closure"):
        verify_abort(policy,trade,"b",commands["b"],forged)
