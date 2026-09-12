"""Initial SaveGameData kernel: synthetic held points and actual Lua image writer.

The SaveRAM host is modeled; these tests do not establish runtime permission or
moving-engine/visual correctness.
"""

import copy
import hashlib
import json

import pytest
from lupa.lua54 import LuaError

from server.gen1_bootstrap_receipt import DATA
from server.gen1_full_save import layout
from server.gen1_initial_save import expected, prepare, verify_receipt, wire_payload
from server.gen1_save_delta import recover_point, wire_payload as arbitrary_delta
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_initial_observation import source
from tests.unit.test_gen1_memorial import load_point
from tests.unit.test_gen1_party_codec import ROOT

IDENTITY = {"ot_id": "0000", "trainer_name": "SAME"}
CONTEXT = "c" * 32
ROM = "f" * 40


def prepared(variant):
    return prepare(
        source(variant), identity=IDENTITY, context_generation=CONTEXT, final_sha1=ROM, frame=100
    )


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_initial_save_copies_only_source_fields_and_checksum_without_mutating_wram(variant):
    before = source(variant)
    original = copy.deepcopy(before)
    after = expected(before, identity=IDENTITY)
    info = layout(variant)
    cart = bytes.fromhex(after["cart_hex"])
    assert before == original and after["fields"] == before["fields"] and after["save_status"] == 2
    assert cart[: info["start"]] == bytes.fromhex(before["cart_hex"])[: info["start"]]
    assert cart[info["end"] + 1 :] == bytes.fromhex(before["cart_hex"])[info["end"] + 1 :]
    for name, region in info["regions"].items():
        assert cart[region["target"] : region["target"] + region["length"]] == bytes.fromhex(
            before["fields"][name]
        )
    assert (sum(cart[info["start"] : info["end"]]) + cart[info["checksum"]]) % 256 == 255
    assert set(wire_payload(prepared(variant))["changes"]) == {"cart"}


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("fault", ["party", "box", "seen", "owned", "current_box", "identity"])
def test_pre_starter_guard_does_not_adopt_existing_monster_history(variant, fault):
    before = source(variant)
    identity = IDENTITY
    if fault == "identity":
        identity = {"ot_id": "0001", "trainer_name": "SAME"}
    else:
        info = layout(variant)
        field = DATA["titles"][variant]["fields"][fault]
        owner, region = next(
            (name, row)
            for name, row in info["regions"].items()
            if row["address"] <= field["address"] < row["address"] + row["length"]
        )
        raw = bytearray.fromhex(before["fields"][owner])
        raw[field["address"] - region["address"]] = 1
        before["fields"][owner] = raw.hex().upper()
    with pytest.raises(JournalError):
        expected(before, identity=identity)


def client(variant, fail_after=-1):
    payload = prepared(variant)
    body = {"cmd": "initial_save", "payload": wire_payload(payload)}
    lua, mem = load_point(payload["before"])
    g = lua.globals()
    g.root, g.mem, g.variant = ROOT.as_posix(), mem, variant
    g.command_json = json.dumps(body)
    g.sha_text = lambda text: hashlib.sha256(text.encode()).hexdigest()
    g.fail_after = fail_after
    g.bus[layout(variant)["status"]] = payload["before"]["save_status"]
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');Canonical=require('journal_document');Full=require('gen1_full_save')
        writes=0;file_writes=0;permitted=true;failed_once=false;held=true
        emu={framecount=function()return 100 end};gameinfo={getromhash=function()return string.rep('f',40)end}
        package.loaded.platform_saveram={new=function(options)
            assert(options.authorize())
            return {flush=function(_,hex)
                assert(options.authorize());file_writes=file_writes+1
                return {schema='slink-saveram-file-v1',path='isolated/SaveRAM/game.sav',sha256=file_sha(hex),
                    byte_length=#hex/2,host_profile='bizhawk-2.11.1-gambatte-exclusive-hold-v1',
                    frame=100,flushed=true,readback=true}
            end}
        end}
        local original=memory.write_u8
        memory.write_u8=function(a,v,d)
            if writes==fail_after and not failed_once then failed_once=true;error('partial write fixture')end
            original(a,v,d)
        end
        writer=require('gen1_held_initial_save').new({memory=mem,variant=variant,
            safe=function()return held end,permitted=function()return permitted end,
            owned=function()return {context_generation=string.rep('c',32)}end,
            sha=function(value)return sha_text(assert(Canonical.encode(value)))end})
        body=assert(JSON.decode(command_json));intent=writer.prepare(body)
        identity={command_id=string.rep('a',32),command_sequence=1}
        function point_json()return assert(JSON.encode(Full.capture(mem,variant)))end
        function receipt_json()return assert(JSON.encode(writer.receipt(body,intent,Full.capture(mem,variant),identity)))end
    """)
    g.file_sha = lambda text: hashlib.sha256(bytes.fromhex(text)).hexdigest()
    return lua, payload, body


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("fail_after", [-1, 0, 1, 64, 1000])
def test_shared_lua_image_writer_recovers_partial_initial_save_and_requires_save_permission(
    variant, fail_after
):
    lua, payload, body = client(variant, fail_after)
    g = lua.globals()
    assert g.writes == 0 and g.file_writes == 0
    assert (
        lua.execute("return writer.phase(Full.capture(mem,variant),body.payload)") == "initial_save"
    )
    complete = lua.execute("return writer.apply(body,intent)")
    if not complete:
        current = json.loads(g.point_json())
        assert recover_point(current, body["payload"]) == payload["before"]
        if fail_after > 0:
            assert (
                lua.execute("return writer.phase(Full.capture(mem,variant),body.payload)")
                == "initial_save_repair"
            )
        g.permitted = False
        written = g.writes
        assert lua.execute("return writer.apply(body,intent)") is False and g.writes == written
        g.permitted = True  # Models the caller supplying a newly verified repair permit.
        assert lua.execute("return writer.apply(body,intent)") is True
    assert json.loads(g.point_json()) == payload["after"]
    assert (
        lua.execute("return writer.phase(Full.capture(mem,variant),body.payload)")
        == "initial_save_flush"
    )
    g.permitted = False
    with pytest.raises(LuaError):
        g.receipt_json()
    assert g.file_writes == 0
    g.permitted = True  # A separate consumed save permit belongs to the caller.
    receipt = json.loads(g.receipt_json())
    command = {"command_id": "a" * 32, "command_sequence": 1, "body": body}
    assert verify_receipt(
        command,
        receipt,
        payload["before"],
        identity=IDENTITY,
        context_generation=CONTEXT,
        final_sha1=ROM,
        frame=100,
    )["after_digest"] == digest(payload["after"])
    assert g.file_writes == 1


@pytest.mark.parametrize(
    "fault", ["cart", "wram", "context", "command", "delta_schema", "wram_delta"]
)
def test_initial_save_foreign_preimage_or_policy_never_writes(fault):
    lua, payload, _ = client("yellow")
    g = lua.globals()
    if fault == "cart":
        g.cart[10] = 0
    elif fault == "wram":
        g.bus[layout("yellow")["regions"]["name"]["address"]] = 0
    else:
        changes = {
            "context": "body.payload.context_generation=string.rep('a',32)",
            "command": "body.cmd='memorialize'",
            "delta_schema": "body.payload.schema='rby-memorial-delta-v1'",
            "wram_delta": "body.payload.changes.party=body.payload.changes.cart",
        }
        lua.execute(changes[fault] + ";intent.body_digest=sha_text(assert(Canonical.encode(body)))")
    with pytest.raises(LuaError):
        lua.execute("writer.apply(body,intent)")
    assert g.writes == 0 and g.file_writes == 0


def test_initial_save_rejects_a_self_consistent_delta_that_overwrites_unrelated_sram():
    lua, payload, _ = client("yellow")
    after = payload["after"]
    after["cart_hex"] = "00" + after["cart_hex"][2:]
    with pytest.raises(JournalError, match="source-defined"):
        wire_payload(payload)
    # The generic memorial-capable codec can describe broader storage changes.
    # The initial-save Lua wrapper must independently reject those changes.
    body = {
        "cmd": "initial_save",
        "payload": arbitrary_delta(payload, schema="rby-initial-save-delta-v1"),
    }
    lua.globals().malicious = json.dumps(body)
    lua.execute(
        "body=assert(JSON.decode(malicious));intent.body_digest=sha_text(assert(Canonical.encode(body)))"
    )
    with pytest.raises(LuaError, match="outside source-defined"):
        lua.execute("writer.apply(body,intent)")
    assert lua.globals().writes == 0 and lua.globals().file_writes == 0


@pytest.mark.parametrize(
    "fault", ["command", "sequence", "context", "file_hash", "file_frame", "poststate"]
)
def test_initial_save_receipt_requires_exact_command_image_and_file(fault):
    lua, payload, body = client("yellow")
    lua.execute("writer.apply(body,intent)")
    receipt = json.loads(lua.globals().receipt_json())
    if fault in ("command", "context"):
        receipt["command_id" if fault == "command" else "context_generation"] = "e" * 32
    elif fault == "sequence":
        receipt["command_sequence"] = True
    elif fault == "file_hash":
        receipt["file"]["sha256"] = "0" * 64
    elif fault == "file_frame":
        receipt["file"]["frame"] += 1
    else:
        receipt["after"]["save_status"] = 0
    with pytest.raises(JournalError):
        verify_receipt(
            {"command_id": "a" * 32, "command_sequence": 1, "body": body},
            receipt,
            payload["before"],
            identity=IDENTITY,
            context_generation=CONTEXT,
            final_sha1=ROM,
            frame=100,
        )
