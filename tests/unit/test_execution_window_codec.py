import pytest
from server.execution_window import SCHEMA,VerifiedExecutionWindow,command_scope,issue


def values():
    command={"command_id":"a"*32,"command_sequence":7,"body":{"cmd":"native_trade_commit","player":"a","seq":13}}
    binding={"context_generation":"b"*32,"binding_digest":"c"*64}
    scope=command_scope(command,binding,phase="native_trade_commit")
    return command,binding,scope


def test_stored_body_and_sequence_are_bound_without_losing_inner_reserved_fields():
    command,binding,scope=values()
    assert scope!=command_scope(command|{"command_sequence":8},binding,phase="native_trade_commit")
    assert scope!=command_scope(command|{"body":command["body"]|{"seq":14}},binding,phase="native_trade_commit")


def test_issued_proof_is_detached_and_cannot_be_retargeted():
    _,_,scope=values();proof=VerifiedExecutionWindow(scope,"d"*64,30,1000)
    request={"schema":SCHEMA,"challenge":"e"*32,"scope":scope.copy()}
    scope["phase"]="other"
    response=issue(request,proof)
    assert response["scope"]["phase"]=="native_trade_commit"
    response["scope"]["phase"]="other"
    assert issue(request,proof)["scope"]["phase"]=="native_trade_commit"
    with pytest.raises(ValueError):issue(request|{"scope":scope},proof)
    with pytest.raises(ValueError):issue(request,{"verified":True})


@pytest.mark.parametrize("frames,ttl",[(0,1000),(601,1000),(True,1000),(30,0),(30,2001),(30,True)])
def test_no_unbounded_or_boolean_budget(frames,ttl):
    with pytest.raises(ValueError):VerifiedExecutionWindow(values()[2],"d"*64,frames,ttl)
