"""Owned native window policy against actual journals; cartridge observations are modeled."""
import copy
from types import SimpleNamespace

import pytest

from server.execution_window import command_scope
from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_native_execution import NativeExecutionPolicy, SCHEMA
from server.gen1_trade_preparation import preparation_payload, verify_preparation
from server.protocol import digest
from server.protocol_journal import JournalError
from server.trade_coordinator import NAMESPACE
from tests.unit.test_gen1_runtime_trade import TradeCase
from tests.unit.test_gen1_trade_preparation import checkpoint


@pytest.fixture
def case(tmp_path):
    value=TradeCase(tmp_path);value.admit("a");value.admit("b")
    manifests={p:companion_profiles()[v]["manifest"] for p,v in value.variants.items()}
    for p in manifests:value.policy.rules[p].rom_sha1=manifests[p]["final_sha1"]
    fixture=SimpleNamespace(policy=value.policy,contexts=value.policy.contexts,
        original={"rules":{"parties":{p:[raw.hex().upper()] for p,raw in value.blobs.items()}}})
    points={p:checkpoint(fixture,p) for p in ("a","b")}
    value.policy.prepare=lambda trade,p:preparation_payload(trade,p,rules=value.policy.rules,checkpoints=points)
    value.policy.ready=lambda trade,p,command,receipt:verify_preparation(command,receipt,rules=value.policy.rules[p])
    value.offer();value.accept();value.trade_control("prepare")
    for p in ("a","b"):
        command=value.command(p,"native_trade_prepare")
        value.event(p,"trade_ready",command,{"schema":"rby-native-ready-v1","command_id":command["command_id"],
            "command_sequence":command["command_sequence"],"transaction_id":value.tx,
            "proposal_digest":command["proposal_digest"],"context_generation":value.policy.contexts[p].context_generation,
            "checkpoint":points[p]})
    value.trade_control("commit")
    policy=NativeExecutionPolicy(rules=value.policy.rules,manifests=manifests);policy.bind(value.runtime)
    command=value.runtime.journal.command("a",value.command("a","native_trade_commit")["command_id"])
    body=command["body"];payload=body["payload"];point=points["a"]
    own=payload["proposal"]["participants"]["a"];peer=payload["proposal"]["participants"]["b"]
    region=manifests["a"]["readback"]["save"]
    before={"party":point["party"],"party_storage_hex":point["party_storage_hex"],"map":point["map"],
        "save_region_hex":point["cart_hex"][region["address"]*2:(region["address"]+region["length"])*2],
        "dex_hex":"00"*38,"save_name_hex":point["name_hex"],"pikachu_hex":"0000"}
    intent={"schema":"gen1-native-trade-intent-v1","command_id":command["command_id"],
        "command_sequence":command["command_sequence"],"body_digest":digest(body),
        "context_generation":own["context"]["context_generation"],"before":before,
        "request":{"slot":own["slot"],"incoming":peer["snapshot"]["party"][peer["slot"]],
            "peer_name_hex":payload["prepared"]["details"]["peer_name_hex"],"expected_key":own["key"],
            "incoming_key":peer["key"],"evolved_species":payload["prepared"]["details"]["evolved_species"]},
        "token_hex":"12ABCDEF","generation":7,"union_hex":"00"*16}
    evidence={"schema":SCHEMA,"command_id":command["command_id"],"command_sequence":command["command_sequence"],
        "context_generation":own["context"]["context_generation"],"final_sha1":manifests["a"]["final_sha1"],
        "host":{"owner_id":own["context"]["physical_instance"],"capability_id":"bizhawk-2.11.1-gambatte-exclusive-hold-v1",
            "process_id":123,"frame":100,"steps":0,"held":True,"bounded":True,"failed":False},
        "native":{"phase":"before","intent":intent,"checkpoint":point}}
    yield value,policy,command,evidence
    value.close()


def verify(case,evidence=None):
    value,policy,command,original=case
    return policy("a",command,evidence if evidence is not None else original,value.runtime.state().document(),
        value.runtime.gate.sessions["a"].metadata["control_binding"])


def armed(evidence,sequence=None,frames=15):
    result=copy.deepcopy(evidence)
    result["native"]={"phase":"armed","intent_digest":digest(evidence["native"]["intent"]),
        "sequence":sequence if sequence is not None else ["service","InternalClockTradeAnim"]}
    result["host"]["frame"]+=frames;result["host"]["steps"]+=frames
    return result


def test_native_before_and_original_prefix_get_finite_scoped_windows_without_journal_mutation(case):
    value,_,command,evidence=case;before=value.runtime.journal.snapshot()
    proof=verify(case)
    assert proof.frames==60 and proof.ttl_ms==1000 and proof.proof_digest==digest(evidence)
    assert dict(proof.scope)==command_scope(command,value.runtime.gate.sessions["a"].metadata["control_binding"],phase="native_trade_commit")
    assert verify(case,armed(evidence)).frames==60
    assert value.runtime.journal.snapshot()==before and value.runtime.state().barrier.ticket() is None


@pytest.mark.parametrize("change",["held","bounded","failed","owner","process_bool","frame_bool","artifact",
    "context","command","sequence_bool","checkpoint","body_digest","token","generation","incoming","save_region"])
def test_unverified_or_changed_before_evidence_cannot_grant_native_frames(case,change):
    evidence=copy.deepcopy(case[3]);host=evidence["host"];intent=evidence["native"]["intent"]
    if change in {"held","bounded"}:host[change]=False
    elif change=="failed":host["failed"]=True
    elif change=="owner":host["owner_id"]="e"*32
    elif change=="process_bool":host["process_id"]=True
    elif change=="frame_bool":host["frame"]=True
    elif change=="artifact":evidence["final_sha1"]="f"*40
    elif change=="context":evidence["context_generation"]="f"*32
    elif change=="command":evidence["command_id"]="f"*32
    elif change=="sequence_bool":evidence["command_sequence"]=True
    elif change=="checkpoint":evidence["native"]["checkpoint"]["current_box"]=129
    elif change=="body_digest":intent["body_digest"]="f"*64
    elif change=="token":intent["token_hex"]="00000000"
    elif change=="generation":intent["generation"]=0
    elif change=="incoming":intent["request"]["incoming"]="00"*66
    else:intent["before"]["save_region_hex"]="FF"+intent["before"]["save_region_hex"][2:]
    before=case[0].runtime.journal.snapshot()
    with pytest.raises((JournalError,ValueError)):verify(case,evidence)
    assert case[0].runtime.journal.snapshot()==before


def test_armed_command_requires_an_initial_verified_window_in_this_binding(case):
    with pytest.raises(JournalError,match="initial"):verify(case,armed(case[3]))


@pytest.mark.parametrize("change",["pid","rewind","unowned_frame","intent","prefix","regression","back_to_before"])
def test_native_renewal_refuses_context_or_execution_discontinuity(case,change):
    verify(case);value=armed(case[3]);verify(case,value)
    if change=="pid":value["host"]["process_id"]+=1
    elif change=="rewind":value["host"]["frame"]-=1;value["host"]["steps"]-=1
    elif change=="unowned_frame":value["host"]["frame"]+=1
    elif change=="intent":value["native"]["intent_digest"]="f"*64
    elif change=="prefix":value["native"]["sequence"]=["service","SavePartyAndDexData"]
    elif change=="regression":value["native"]["sequence"]=["service"]
    else:value=copy.deepcopy(case[3]);value["host"]["frame"]+=15;value["host"]["steps"]+=15
    with pytest.raises(JournalError):verify(case,value)


def test_reopen_interruption_and_operation_ceiling_never_grant_recovery_frames(case):
    verify(case)
    assert verify(case,armed(case[3],frames=60000)) is None
    value=case[0];value.runtime.disconnect("a",value.owners["a"])
    assert value.runtime.journal.record(NAMESPACE,value.tx).value["recovery_required"]
