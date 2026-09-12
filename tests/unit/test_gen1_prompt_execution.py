"""Owned prompt windows and acknowledged return; cartridge observations are modeled."""
import copy
import hashlib
from types import SimpleNamespace

import pytest

from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_native_execution import NativeExecutionPolicy, SCHEMA
from server.gen1_trade_preparation import preparation_payload
from server.gen1_trade_ui_receipts import verify_partner_prompt
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_runtime_trade import TradeCase
from tests.unit.test_gen1_trade_preparation import checkpoint


@pytest.fixture
def case(tmp_path):
    run=TradeCase(tmp_path);run.admit("a");run.admit("b")
    manifests={p:companion_profiles()[v]["manifest"] for p,v in run.variants.items()}
    for p in manifests:run.policy.rules[p].rom_sha1=manifests[p]["final_sha1"]
    model=SimpleNamespace(policy=run.policy,contexts=run.policy.contexts,
        original={"rules":{"parties":{p:[raw.hex().upper()] for p,raw in run.blobs.items()}}})
    points={p:checkpoint(model,p) for p in ("a","b")}
    run.policy.prompt=lambda trade,p:{"schema":"rby-native-prompt-v1","proposal":trade["proposal"]}
    run.policy.prepare=lambda trade,p:preparation_payload(trade,p,rules=run.policy.rules,checkpoints=points)
    run.policy.decision=lambda trade,p,command,receipt:(verify_partner_prompt(command,receipt,manifest=manifests[p]),receipt)
    run.offer()
    command=run.runtime.journal.command("b",run.command("b","native_trade_prompt")["command_id"])
    body=command["body"];own=body["payload"]["proposal"]["participants"]["b"]
    peer=body["payload"]["proposal"]["participants"]["a"];point=points["b"]
    before={"party":point["party"],"party_storage_hex":point["party_storage_hex"],"map":point["map"],
        "fields":dict.fromkeys(manifests["b"]["receptionist"]["partner_prompt"]["saved_fields"],0),
        "tiles_hex":"00"*360,"cart_digest":hashlib.sha256(point["cart_hex"].encode()).hexdigest()}
    intent={"schema":"rby-partner-prompt-intent-v1","command_id":command["command_id"],
        "command_sequence":command["command_sequence"],"body_digest":digest(body),
        "context_generation":own["context"]["context_generation"],"before":before,
        "request":{"slot":own["slot"],"incoming":peer["snapshot"]["party"][peer["slot"]]},
        "token_hex":"12ABCDEF","generation":7,"union_hex":"00"*16}
    evidence={"schema":SCHEMA,"command_id":command["command_id"],"command_sequence":command["command_sequence"],
        "context_generation":own["context"]["context_generation"],"final_sha1":manifests["b"]["final_sha1"],
        "host":{"owner_id":own["context"]["physical_instance"],"capability_id":"bizhawk-2.11.1-gambatte-exclusive-hold-v1",
            "process_id":123,"frame":100,"steps":0,"held":True,"bounded":True,"failed":False},
        "native":{"phase":"before","intent":intent,"checkpoint":point}}
    policy=NativeExecutionPolicy(rules=run.policy.rules,manifests=manifests);policy.bind(run.runtime)
    yield run,policy,command,evidence
    run.close()


def verify(case,evidence=None,command=None):
    run,policy,issued,original=case
    return policy("b",command or issued,evidence or original,run.runtime.state().document(),
        run.runtime.gate.sessions["b"].metadata["control_binding"])


def closure(case):
    run,_,command,evidence=case
    verify(case)
    intent=evidence["native"]["intent"]
    receipt={"schema":"rby-native-prompt-v1","command_id":command["command_id"],"command_sequence":command["command_sequence"],
        "transaction_id":run.tx,"proposal_digest":command["body"]["proposal_digest"],
        "context_generation":evidence["context_generation"],"final_sha1":evidence["final_sha1"],"result":0,
        "token_hex":intent["token_hex"],"generation":intent["generation"],"before":intent["before"],"after":intent["before"],
        "sequence":["service","prompt","choice"],"counts":{"service":1,"prompt":1,"choice":1}}
    run.event("b","trade_decision",run.command("b","native_trade_prompt"),receipt)
    run.trade_control("prepare")
    prepare=run.runtime.journal.command("b",run.command("b","native_trade_prepare")["command_id"])
    result=copy.deepcopy(evidence)
    result.update(command_id=prepare["command_id"],command_sequence=prepare["command_sequence"],
        native={"phase":"prompt_before","prompt_command_id":command["command_id"],
            "prompt_intent_digest":digest(intent),"receipt":receipt})
    return prepare,result


def test_original_prompt_prefix_and_exact_acknowledged_return_are_scoped(case):
    assert verify(case).frames==60
    evidence=copy.deepcopy(case[3]);evidence["native"]={"phase":"armed",
        "intent_digest":digest(case[3]["native"]["intent"]),"sequence":["service","prompt","choice"]}
    assert verify(case,evidence).frames==60
    # A separate case's closure helper starts before arming; return to a fresh
    # journal-backed prompt state is tested below, never rewinding this proof.


def test_prepare_can_only_close_the_exact_durably_acknowledged_prompt(case):
    command,evidence=closure(case)
    assert verify(case,evidence,command).scope["phase"]=="native_trade_prepare"
    evidence["native"]["phase"]="prompt_closing"
    assert verify(case,evidence,command).frames==60


@pytest.mark.parametrize("change",["incoming","view","cart","token","generation","body_digest","tiles","fields"])
def test_changed_prompt_intent_never_gets_initial_frames(case,change):
    evidence=copy.deepcopy(case[3]);intent=evidence["native"]["intent"]
    if change=="incoming":intent["request"]["incoming"]="00"*66
    elif change=="view":intent["before"]["map"]+=1
    elif change=="cart":intent["before"]["cart_digest"]="f"*64
    elif change=="token":intent["token_hex"]="00000000"
    elif change=="generation":intent["generation"]=True
    elif change=="body_digest":intent["body_digest"]="f"*64
    elif change=="tiles":intent["before"]["tiles_hex"]="00"
    else:intent["before"]["fields"]={}
    with pytest.raises(JournalError):verify(case,evidence)


@pytest.mark.parametrize("change",["old_intent","receipt","not_acknowledged","no_initial_window","wrong_prompt"])
def test_prompt_closure_refuses_unbound_or_fabricated_history(case,change):
    command,evidence=closure(case);run,policy,_,_=case
    if change=="old_intent":evidence["native"]["prompt_intent_digest"]="f"*64
    elif change=="receipt":evidence["native"]["receipt"]["result"]=1
    elif change=="no_initial_window":policy.observed.clear()
    elif change=="wrong_prompt":evidence["native"]["prompt_command_id"]="f"*32
    else:
        original=run.runtime.journal.command
        def pending(player,identifier):
            result=original(player,identifier)
            if result["body"]["cmd"]=="native_trade_prompt":result["outcome"]=None
            return result
        run.runtime.journal.command=pending
    with pytest.raises(JournalError):verify(case,evidence,command)
