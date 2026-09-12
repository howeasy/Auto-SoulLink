"""Non-linked archive kernels on synthetic points; no new live engine claim."""

import copy
import hashlib
import json

import pytest

from server.gen1_full_save import image, layout
from server.gen1_initial_observation import inventory
from server.gen1_memorial_policy import BOX_SIZE, box_image
from server.gen1_party_codec import PartyCodec
from server.gen1_retirement import (
    expected,
    prepare,
    prepend_box,
    remove_box,
    verify_receipt,
    wire_payload,
)
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_memorial import fixture, load_point
from tests.unit.test_gen1_memorial_policy import full_grave
from tests.unit.test_gen1_party_codec import ROOT, make_blob


def point(variant="yellow", *, where="party", count=3, slot=1, old_box=2):
    before, key, identity = fixture(
        variant,
        count=count,
        slot=slot if where == "party" else 0,
        current=11 if where == "grave" else 0,
    )
    if where == "party":
        raw = bytearray.fromhex(before["fields"]["party"])
        raw[8 + 44 * slot + 1 : 8 + 44 * slot + 3] = b"\0\1"
        before["fields"]["party"] = raw.hex().upper()
        birth = None
    else:
        raw = bytearray(make_blob(PartyCodec(variant), dv=0x7777))
        raw[3] = raw[33]
        key = PartyCodec(variant).validate_blob(bytes(raw)).key
        boxed = bytes(raw[:33] + raw[44:])
        base = bytearray(BOX_SIZE)
        base[1] = 255
        if where == "grave":
            before_box = bytes(base)
            after_box = prepend_box(before_box, boxed)
            birth = {"before": before_box.hex().upper(), "after": after_box.hex().upper()}
        else:
            base[0] = old_box + 1
            base[old_box + 2] = 255
            for index in range(old_box + 1):
                value = (
                    boxed if index == slot else make_blob(PartyCodec(variant), dv=0x8000 + index)
                )
                if index != slot:
                    item = bytearray(value[:33])
                    item[3] = value[33]
                    value = bytes(item) + value[44:]
                base[1 + index] = value[0]
                for start, data in (
                    (22 + 33 * index, value[:33]),
                    (682 + 11 * index, value[33:44]),
                    (902 + 11 * index, value[44:55]),
                ):
                    base[start : start + len(data)] = data
            after_box = bytes(base)
            birth = None
        before["fields"]["box"] = after_box.hex().upper()
    before["cart_hex"] = image(before).hex().upper()
    return before, key, identity, birth


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("where", ["party", "box", "grave"])
def test_retirement_preserves_every_key_and_archives_exact_target_at_zero_hp(variant, where):
    before, key, identity, birth = point(variant, where=where)
    original = copy.deepcopy(before)
    after = expected(before, key, identity=identity, birth_box=birth)
    assert (
        before == original
        and after["save_status"] == 2
        and after["cart_hex"] == image(after).hex().upper()
    )
    old = inventory(before, identity)
    new = inventory(after, identity)
    assert {r["key"] for r in old["members"]} == {r["key"] for r in new["members"]}
    archived = next(r for r in new["members"] if r["key"] == key)
    assert archived["location"] == "box" and archived["box"] == 11
    assert bytes.fromhex(archived["box_blob_hex"])[1:3] == b"\0\0"
    assert new["party_count"] == old["party_count"] - (where == "party")


@pytest.mark.parametrize("slot", range(20))
def test_current_box_compaction_matches_source_capacity_shifts_and_keeps_other_members(slot):
    before, key, identity, _ = point(where="box", count=6, slot=slot, old_box=19)
    raw = bytearray.fromhex(before["fields"]["box"])
    raw[22 + 33 * slot + 1 : 22 + 33 * slot + 3] = b"\0\0"
    compact = remove_box(bytes(raw), slot)
    assert compact[0] == 19 and compact[20] == 255
    if slot == 19:
        assert compact[682 + 11 * 19] == 255
        assert compact[22:682] == raw[22:682] and compact[902:] == raw[902:]
    else:
        for base, stride in ((682, 11), (22, 33), (902, 11)):
            assert (
                compact[base + slot * stride : base + 19 * stride]
                == raw[base + (slot + 1) * stride : base + 20 * stride]
            )
            assert (
                compact[base + 19 * stride : base + 20 * stride]
                == raw[base + 19 * stride : base + 20 * stride]
            )
    after = expected(before, key, identity=identity)
    assert after["fields"]["box"] == compact.hex().upper()
    assert len(inventory(after, identity)["members"]) == len(inventory(before, identity)["members"])


def test_owned_active_grave_birth_extends_its_exact_reserved_bytes():
    before, key, identity, birth = point(where="grave")
    # An owned empty grave is allowed; the live gift's after-image alone is not ownership.
    reserved = hashlib.sha256(bytes.fromhex(birth["before"])).hexdigest()
    after = expected(before, key, identity=identity, reserved_digest=reserved, birth_box=birth)
    assert box_image(after, 11)[0] == 1 and box_image(after, 11)[23:25] == b"\0\0"
    with pytest.raises(JournalError):
        expected(before, key, identity=identity, reserved_digest=reserved)


@pytest.mark.parametrize(
    "fault",
    [
        "last-party",
        "unknown-key",
        "unowned-grave",
        "wrong-birth",
        "wrong-reservation",
        "saved-checksum",
    ],
)
def test_unsafe_retirement_refuses_without_mutation(fault):
    before, key, identity, birth = point(
        where="grave"
        if fault in ("unowned-grave", "wrong-birth", "wrong-reservation")
        else "party",
        count=1 if fault == "last-party" else 3,
        slot=0 if fault == "last-party" else 1,
    )
    reserved = None
    if fault == "unknown-key":
        key = "0000:0000:00"
    elif fault == "unowned-grave":
        raw = bytearray.fromhex(birth["before"])
        raw[-1] = 0x80
        birth["before"] = raw.hex().upper()
    elif fault == "wrong-birth":
        birth["after"] = "00" + birth["after"][2:]
    elif fault == "wrong-reservation":
        reserved = "f" * 64
    elif fault == "saved-checksum":
        cart = bytearray.fromhex(before["cart_hex"])
        cart[layout("yellow")["checksum"]] ^= 1
        before["cart_hex"] = cart.hex().upper()
    original = copy.deepcopy(before)
    with pytest.raises(JournalError):
        expected(before, key, identity=identity, reserved_digest=reserved, birth_box=birth)
    assert before == original


def test_full_owned_grave_rotates_without_deleting_older_archive():
    before, key, identity = full_grave("yellow")
    original = box_image(before, 11)
    after = expected(
        before, key, identity=identity, reserved_digest=hashlib.sha256(original).hexdigest()
    )
    assert original in [box_image(after, index) for index in range(1, 11)]
    assert box_image(after, 11)[0] == 1


@pytest.mark.parametrize("where", ["party", "box", "grave"])
@pytest.mark.parametrize("interrupted", [False, True])
def test_actual_lua_retirement_wrapper_preserves_partial_image_until_new_permission_and_file_proof(
    where, interrupted
):
    from lupa.lua54 import LuaError

    before, key, identity, birth = point(where=where)
    prepared = prepare(
        before,
        key,
        identity=identity,
        context_generation="c" * 32,
        final_sha1="f" * 40,
        frame=100,
        birth_box=birth,
    )
    body = {
        "cmd": "acquisition_retire",
        "acquisition_id": "b" * 32,
        "key": key,
        "reason": "typed retirement fixture",
        "payload": wire_payload(prepared),
    }
    lua, mem = load_point(before)
    g = lua.globals()
    g.mem = mem
    g.root = ROOT.as_posix()
    g.body_json = json.dumps(body)
    g.sha_text = lambda text: hashlib.sha256(text.encode()).hexdigest()
    g.sha_bytes = lambda text: hashlib.sha256(bytes.fromhex(text)).hexdigest()
    g.bus[layout("yellow")["status"]] = before["save_status"]
    g.interrupted = interrupted
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');Canonical=require('journal_document');Full=require('gen1_full_save')
        emu={framecount=function()return 100 end};gameinfo={getromhash=function()return string.rep('f',40)end}
        permitted=true;files=0;failed=false
        package.loaded.platform_saveram={new=function(options)
            assert(options.authorize());return {flush=function(_,hex)
                assert(options.authorize());files=files+1
                return {schema='slink-saveram-file-v1',path='owned/a/SaveRAM/game.sav',sha256=sha_bytes(hex),byte_length=#hex/2,
                    host_profile='bizhawk-2.11.1-gambatte-exclusive-hold-v1',frame=100,flushed=true,readback=true}
            end}
        end}
        local write=memory.write_u8
        memory.write_u8=function(...)
            if interrupted and writes==10 and not failed then failed=true;error('interrupted retirement')end
            return write(...)
        end
        writer=require('gen1_held_retirement').new({memory=mem,variant='yellow',safe=function()return true end,
            permitted=function()return permitted end,owned=function()return {context_generation=string.rep('c',32)}end,
            sha=function(value)return sha_text(assert(Canonical.encode(value)))end})
        body=assert(JSON.decode(body_json));intent=writer.prepare(body);completed=writer.apply(body,intent)
    """)
    if not g.completed:
        lua.execute("permitted=false")
        writes = g.writes
        assert lua.execute("return writer.apply(body,intent)") is False and g.writes == writes
        lua.execute("permitted=true;assert(writer.apply(body,intent))")
    assert json.loads(lua.eval('JSON.encode(Full.capture(mem,"yellow"))')) == prepared["after"]
    lua.execute("permitted=false")
    with pytest.raises(LuaError):
        lua.execute(
            "writer.receipt(body,intent,Full.capture(mem,'yellow'),{command_id=string.rep('a',32),command_sequence=1})"
        )
    assert g.files == 0
    lua.execute(
        "permitted=true;receipt=writer.receipt(body,intent,Full.capture(mem,'yellow'),{command_id=string.rep('a',32),command_sequence=1})"
    )
    receipt = json.loads(lua.eval("JSON.encode(receipt)"))
    result = verify_receipt(
        {"command_id": "a" * 32, "command_sequence": 1, "body": body},
        receipt,
        prepared,
        identity=identity,
    )
    assert result["after_digest"] == digest(prepared["after"]) and g.files == 1
