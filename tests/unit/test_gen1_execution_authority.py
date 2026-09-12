"""Actual journal/session binding; cartridge verification is an explicit fixture."""
import copy
import pytest

from server.execution_window import SCHEMA,VerifiedExecutionWindow,command_scope
from server.protocol import ProtocolError,digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_runtime_server import RuntimeCase


@pytest.fixture
def case(tmp_path):
    value=RuntimeCase(tmp_path)
    value.admit("a");value.admit("b")
    value.control("a")  # One owner alone stays held; b's request below completes the service lease.
    value.send("a",{"event":"faint","key":value.keys["a"]})
    yield value
    value.close()


def verifier(player,command,evidence,state,binding):
    if evidence!={"schema":"explicit-physical-execution-fixture-v1"}:return None
    return VerifiedExecutionWindow(command_scope(command,binding,phase=command["body"]["cmd"]),
        digest(evidence),30,1000,state_digest=digest(state))


def request(case):
    command=case.runtime.journal.command("b",case.runtime.journal.pending_ids("b")[0])
    binding=case.runtime.gate.sessions["b"].metadata["control_binding"]
    nonce=case.token()
    return case.envelope("b",{"event":"control","control":{**binding,"challenge":nonce},
        "operation_execution":{"window":{"schema":SCHEMA,"challenge":case.token(),
            "scope":command_scope(command,binding,phase=command["body"]["cmd"])},
            "evidence":{"schema":"explicit-physical-execution-fixture-v1"}}},nonce)


def test_no_default_operation_issuer_exists(case):
    before=case.runtime.journal.snapshot()
    with pytest.raises(ProtocolError,match="not configured"):
        case.runtime.process(request(case),case.owners["b"])
    assert case.runtime.journal.snapshot()==before


def test_typed_current_proof_grants_only_the_exact_command_and_keeps_barrier_held(case):
    case.runtime.verify_operation_execution=verifier
    message=request(case);before=case.runtime.journal.snapshot()
    response=case.runtime.process(message,case.owners["b"])
    assert response["control"]["authority"]=="service"
    assert response["operation_execution"]["scope"]==message["operation_execution"]["window"]["scope"]
    assert response["operation_execution"]["frames"]==30
    assert case.runtime.journal.snapshot()==before
    assert case.runtime.state().barrier.ticket() is None
    with pytest.raises(ProtocolError):case.runtime.process(message,case.owners["b"])


def test_foreign_connection_and_changed_request_scope_do_not_get_a_grant(case):
    case.runtime.verify_operation_execution=verifier
    with pytest.raises(ProtocolError):case.runtime.process(request(case),object())
    message=request(case);message["operation_execution"]["window"]["scope"]["operation_digest"]="f"*64
    with pytest.raises(ValueError):case.runtime.process(message,case.owners["b"])


@pytest.mark.parametrize("kind",["flag","stale_state","wrong_body","denied"])
def test_generation_verifier_cannot_return_a_success_flag_or_stale_proof(case,kind):
    def checked(*args):
        result=verifier(*args)
        if kind=="flag":return True
        if kind=="denied":return None
        scope=dict(result.scope)
        if kind=="wrong_body":scope["operation_digest"]="f"*64
        return VerifiedExecutionWindow(scope,result.proof_digest,result.frames,result.ttl_ms,
            state_digest="f"*64 if kind=="stale_state" else result.state_digest)
    case.runtime.verify_operation_execution=checked
    if kind=="denied":
        response=case.runtime.process(request(case),case.owners["b"])
        assert response["operation_execution"] is None and response["control"]["authority"]=="service"
    else:
        with pytest.raises(JournalError):case.runtime.process(request(case),case.owners["b"])


@pytest.mark.parametrize("kind",["slow","context","journal"])
def test_authority_is_rechecked_after_generation_verification(case,kind):
    def changed(*args):
        result=verifier(*args)
        if kind=="slow":case.time+=2
        elif kind=="context":case.runtime.gate.sessions["a"].metadata["control_binding"]["context_generation"]="f"*32
        else:case.runtime._commit_system(case.runtime.state(),"fixture_verification_mutation")
        return result
    case.runtime.verify_operation_execution=changed
    with pytest.raises(JournalError,match="changed during"):
        case.runtime.process(request(case),case.owners["b"])
