"""Remote file proof checks; upstream native execution readback is an explicit fixture."""
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.gen1_native_policy import NativeTradePolicy
from server.gen1_trade_preparation import SYMBOLS
from server.protocol_journal import JournalError
from server.trade_coordinator import NAMESPACE
from tests.unit.test_gen1_native_execution import case  # noqa: F401


@pytest.fixture
def evidence(case,monkeypatch):  # noqa: F811
    run,execution,command,window=case
    policy=NativeTradePolicy();run.runtime.trade.policy.policy=policy
    point=window["native"]["checkpoint"]
    policy.configure(execution,read_checkpoints=lambda:{"a":point})
    policy.prepared={"transaction_id":run.tx,"players":{"a":copy.deepcopy(point)}}
    trade=run.runtime.journal.record(NAMESPACE,run.tx).value
    image=bytes.fromhex(point["cart_hex"])
    region=execution.manifests["a"]["readback"]["save"]
    native={"schema":"explicit-verified-native-fixture-v1","command_id":command["command_id"],
        "transaction_id":run.tx,"proposal_digest":command["body"]["proposal_digest"],
        "after":{"save_region_hex":image[region["address"]:region["address"]+region["length"]].hex().upper()}}
    trade["applied"]={"a":copy.deepcopy(native)}
    binding=run.runtime.gate.sessions["a"].metadata["control_binding"]
    execution.observed[("a",command["command_id"],binding["binding_digest"]) ]={"frame":100}
    peer=trade["proposal"]["participants"]["b"]
    mon=execution.rules["a"].codec.validate_blob(bytes.fromhex(peer["snapshot"]["party"][peer["slot"]]))
    def verified_native(issued,receipt,**options):
        assert issued==command and receipt==native
        return SimpleNamespace(received_key=mon.key,received_digest=mon.sha256)
    monkeypatch.setattr("server.gen1_native_policy.verify_native_trade_receipt",verified_native)
    receipt={"schema":"rby-file-backed-v1","native":copy.deepcopy(native),"save_image_hex":image.hex().upper(),
        "file":{"schema":"slink-saveram-file-v1","path":r"Z:\Partner Computer\SaveRAM\remote.SaveRAM",
            "sha256":hashlib.sha256(image).hexdigest(),"byte_length":len(image),
            "host_profile":"bizhawk-2.11.1-gambatte-exclusive-hold-v1","frame":150,"flushed":True,"readback":True}}
    return policy,trade,command,receipt


def test_remote_path_is_opaque_and_full_image_hash_matches_verified_native_result(evidence,monkeypatch):
    policy,trade,command,receipt=evidence
    def forbidden(*args):raise AssertionError("server tried to open the remote client path")
    monkeypatch.setattr(Path,"read_bytes",forbidden)
    proof=policy.verified(trade,"a",command,receipt)
    assert proof.save_receipt==receipt["file"]


@pytest.mark.parametrize("change",["hash","image_size","hash_size","frame_bool","old_frame","future_frame",
    "flushed","readback","profile","empty_path","path_control","extra","cache","hall_of_fame","inactive_box","main_save"])
def test_file_corruption_or_wrong_context_cannot_verify_a_trade(evidence,change):
    policy,trade,command,receipt=evidence
    file=receipt["file"]
    if change=="hash":file["sha256"]="f"*64
    elif change=="image_size":receipt["save_image_hex"]=receipt["save_image_hex"][:-2]
    elif change=="hash_size":file["byte_length"]=True
    elif change=="frame_bool":file["frame"]=True
    elif change=="old_frame":file["frame"]=99
    elif change=="future_frame":file["frame"]=221
    elif change in {"flushed","readback"}:file[change]=False
    elif change=="profile":file["host_profile"]="unverified"
    elif change=="empty_path":file["path"]=""
    elif change=="path_control":file["path"]+="\n"
    elif change=="extra":receipt["success"]=True
    elif change=="cache":policy.prepared["players"]["a"]["current_box"]+=1
    else:
        raw=bytearray.fromhex(receipt["save_image_hex"])
        index=(SYMBOLS["pokeyellow"]["sHallOfFame"]-0xA000 if change=="hall_of_fame" else
            0x4000 if change=="inactive_box" else policy.manifests["a"]["readback"]["save"]["address"])
        raw[index]^=1
        receipt["save_image_hex"]=raw.hex().upper();file["sha256"]=hashlib.sha256(raw).hexdigest()
    with pytest.raises(JournalError):policy.verified(trade,"a",command,receipt)


def test_only_known_sprite_workspace_can_change_outside_canonical_save_region(evidence):
    policy,trade,command,receipt=evidence
    raw=bytearray.fromhex(receipt["save_image_hex"])
    raw[SYMBOLS["pokeyellow"]["sSpriteBuffer0"]-0xA000]^=1
    receipt["save_image_hex"]=raw.hex().upper();receipt["file"]["sha256"]=hashlib.sha256(raw).hexdigest()
    assert policy.verified(trade,"a",command,receipt)
