"""RBY exact readback agrees across Lua/Python and drives the real memory writer."""
import copy
import json

import pytest
from lupa import LuaRuntime

from server.gen1_command_receipts import (
    RECEIPT_SCHEMA,
    RECEIPT_SCHEMAS,
    SCHEMA,
    Gen1ReceiptPolicy,
    validate_party_snapshot,
    verify_force_faint,
    verify_force_faint_receipt,
)
from server.gen1_party_codec import PartyCodec
from server.protocol_journal import JournalError
from tests.unit.test_client_journal import accepted, start
from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_gen1_party_codec import ROOT, make_blob

IDENTITY = {"ot_id": "F00D", "trainer_name": "ASH"}


def snapshot(variant, count=3, battle=0, active=0):
    codec = PartyCodec(variant)
    blobs = [make_blob(codec, dv=0x1000 + i) for i in range(count)]
    return {"schema": SCHEMA, "variant": variant, "save_id": IDENTITY["ot_id"], "save_name": IDENTITY["trainer_name"],
            "party_count": count, "party": [blob.hex().upper() for blob in blobs],
            "species_list": [blob[0] for blob in blobs] + [255], "battle_flag": battle,
            "active_slot": active if battle else None, "battle_hp": 10 if battle else None}


def command_for(before, slot):
    mon = PartyCodec(before["variant"]).validate_blob(bytes.fromhex(before["party"][slot]))
    return {"cmd": "force_faint", "key": mon.key}


@pytest.fixture(scope="module")
def receipt_lua():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_ROOT = ROOT.as_posix()
    lua.execute("""
        package.path=SLINK_ROOT..'/lua/?.lua;'..package.path
        JSON=require('json_codec');Receipts=require('gen1_command_receipts')
        function expected(command,before)
            local after,slot=Receipts.force_faint_expected(assert(JSON.decode(command)),assert(JSON.decode(before)))
            if not after then return nil,slot end
            return assert(JSON.encode(after)),slot
        end
        function validate(text,variant)return Receipts.validate_snapshot(assert(JSON.decode(text)),variant)end
    """)
    return lua


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("count", range(1, 7))
@pytest.mark.parametrize("battle", [0, 1, 2])
def test_every_party_count_target_and_battler_has_exact_cross_language_readback(receipt_lua, variant, count, battle):
    for active in range(count) if battle else [0]:
        before = snapshot(variant, count, battle, active)
        for slot in range(count):
            command = command_for(before, slot)
            encoded, actual_slot = receipt_lua.globals().expected(json.dumps(command), json.dumps(before))
            assert encoded is not None, actual_slot
            after = json.loads(encoded)
            assert actual_slot == slot
            assert verify_force_faint(command, before, after, variant=variant, identity=IDENTITY) == {
                "key": command["key"], "slot": slot}
            for index, (old, new) in enumerate(zip(before["party"], after["party"], strict=True)):
                changed = [i for i, pair in enumerate(zip(bytes.fromhex(old), bytes.fromhex(new), strict=True))
                           if pair[0] != pair[1]]
                assert changed == ([2] if index == slot else [])
            assert after["battle_hp"] == (0 if battle and slot == active else before["battle_hp"])


@pytest.mark.parametrize("change", ["missing_list", "extra", "count_bool", "count_zero", "lower_hex", "short_blob",
                                   "duplicate", "terminator", "battle_bool", "active_range", "battle_hp", "null",
                                   "empty_name", "name_control", "save_id", "bad_variant"])
def test_invalid_snapshots_refused_by_both_readback_implementations(receipt_lua, change):
    before = snapshot("yellow", battle=1)
    if change == "missing_list":
        del before["species_list"]
    elif change == "extra":
        before["assert_success"] = True
    elif change == "count_bool":
        before["party_count"] = True
    elif change == "count_zero":
        before["party_count"] = 0
    elif change == "lower_hex":
        before["party"][0] = before["party"][0].lower()
    elif change == "short_blob":
        before["party"][0] = before["party"][0][:-2]
    elif change == "duplicate":
        before["party"][1] = before["party"][0]
    elif change == "terminator":
        before["species_list"][-1] = 0
    elif change == "battle_bool":
        before["battle_flag"] = True
    elif change == "active_range":
        before["active_slot"] = before["party_count"]
    elif change == "battle_hp":
        before["battle_hp"] = 1000
    elif change == "null":
        before["battle_flag"] = 0
    elif change == "empty_name":
        before["save_name"] = ""
    elif change == "name_control":
        before["save_name"] = "ASH\n"
    elif change == "save_id":
        before["save_id"] = "f00d"
    else:
        before["variant"] = "red_ap"
    with pytest.raises(JournalError):
        validate_party_snapshot(before, variant="yellow")
    result = receipt_lua.globals().validate(json.dumps(before), "yellow")
    assert isinstance(result, tuple) and result[0] is None


@pytest.mark.parametrize("change", ["target_hp", "benched_hp", "name_padding", "order", "mirror", "active", "battle",
                                   "save_id", "save_name", "missing_key"])
def test_valid_blobs_cannot_hide_incomplete_or_unrelated_physical_changes(receipt_lua, change):
    before = snapshot("yellow", battle=1, active=0)
    command = command_for(before, 0)
    encoded, _ = receipt_lua.globals().expected(json.dumps(command), json.dumps(before))
    after = json.loads(encoded)
    if change == "target_hp":
        after["party"][0] = before["party"][0]
    elif change in ("benched_hp", "name_padding"):
        raw = bytearray.fromhex(after["party"][1])
        raw[2 if change == "benched_hp" else 54] ^= 1
        after["party"][1] = raw.hex().upper()
    elif change == "order":
        after["party"][1], after["party"][2] = after["party"][2], after["party"][1]
    elif change == "mirror":
        after["battle_hp"] = 10
    elif change == "active":
        after["active_slot"] = 1
    elif change == "battle":
        after["battle_flag"] = 2
    elif change == "save_id":
        after["save_id"] = "BEEF"
    elif change == "save_name":
        after["save_name"] = "GARY"
    else:
        command["key"] = "FFFF:FFFF:99"
    # The records themselves are legal; the transaction proof must catch the discrepancy.
    validate_party_snapshot(after, variant="yellow")
    with pytest.raises(JournalError):
        verify_force_faint(command, before, after, variant="yellow", identity=IDENTITY)


def fainted(before, slot):
    after = copy.deepcopy(before)
    raw = bytearray.fromhex(after["party"][slot])
    raw[1:3] = b"\0\0"
    after["party"][slot] = raw.hex().upper()
    return after


def test_death_receipts_name_the_command_they_close():
    """Both engine death commands are the same overworld party write; the receipt schema says which
    obligation it closes, and a receipt of the other kind is refused for that command."""
    from server.state import DEATH_COMMANDS

    assert set(RECEIPT_SCHEMAS) == set(DEATH_COMMANDS) and RECEIPT_SCHEMAS["force_faint"] == RECEIPT_SCHEMA
    before = snapshot("red")
    after = fainted(before, 1)
    command = command_for(before, 1)
    for cmd, schema in RECEIPT_SCHEMAS.items():
        body = {**command, "cmd": cmd}
        receipt = {"schema": schema, "before": before, "after": after}
        assert verify_force_faint_receipt(body, receipt, variant="red", identity=IDENTITY) == {"key": command["key"], "slot": 1}
        other = next(value for value in RECEIPT_SCHEMAS.values() if value != schema)
        with pytest.raises(JournalError, match="versioned force-faint receipt"):
            verify_force_faint_receipt(body, {**receipt, "schema": other}, variant="red", identity=IDENTITY)
    with pytest.raises(JournalError):
        verify_force_faint_receipt({**command, "cmd": "memorialize"}, {"schema": RECEIPT_SCHEMA, "before": before, "after": after},
                                   variant="red", identity=IDENTITY)


def test_receipt_policy_accepts_exactly_the_executor_shapes():
    from types import SimpleNamespace

    policy = Gen1ReceiptPolicy({"a": "red", "b": "yellow"})
    state = SimpleNamespace(player_identity={"b": dict(IDENTITY)})
    before = snapshot("yellow")
    after = fainted(before, 0)
    command = command_for(before, 0)

    def ack(body, receipt, outcome="ACK"):
        journal_command = {"command_id": "a" * 32, "command_sequence": 1, "body": body}
        event = {"event": "command_ack", "command_id": "a" * 32, "command_sequence": 1, "outcome": outcome, "receipt": receipt}
        return policy("b", journal_command, event, state)

    for cmd, schema in RECEIPT_SCHEMAS.items():
        body = {**command, "cmd": cmd, "nickname": "", "death_id": "d" * 32}
        assert ack(body, {"schema": schema, "before": before, "after": after}) == []
        other = next(value for value in RECEIPT_SCHEMAS.values() if value != schema)
        with pytest.raises(JournalError):
            ack(body, {"schema": other, "before": before, "after": after})
        with pytest.raises(JournalError, match="explicit physical ACK"):
            ack(body, {"schema": schema, "before": before, "after": after}, outcome="NACK")
    with pytest.raises(JournalError, match="no verified RBY receipt policy"):
        ack({"cmd": "memorialize", "key": command["key"], "death_id": "d" * 32}, {"schema": RECEIPT_SCHEMA, "before": before, "after": after})


def bind_memory(lua, variant):
    lua.globals().SLINK_ROOT = ROOT.as_posix()
    lua.globals().variant = variant
    lua.execute("""
        bus={};physical_writes=0
        memory={getmemorydomainlist=function()return {'System Bus'}end,
            read_u8=function(a)return bus[a] or 0 end,
            write_u8=function(a,v)physical_writes=physical_writes+1;bus[a]=v%256 end}
        M=dofile(SLINK_ROOT..'/lua/memory_gb.lua')
        G=dofile(SLINK_ROOT..'/lua/games/gen1_rby.lua');M.initProfile(G,variant)
        Receipts=require('gen1_command_receipts')
        function readback()return assert(JSON.encode(assert(Receipts.party_snapshot(M,variant))))end
    """)
    before = snapshot(variant, battle=1, active=0)
    bus, mem = lua.globals().bus, lua.globals().M
    for slot, encoded in enumerate(before["party"]):
        raw = bytes.fromhex(encoded)
        for base, data in ((mem.PARTY_BASE_ADDR + slot * 44, raw[:44]),
                           (mem.PARTY_OT_NAMES_ADDR + slot * 11, raw[44:55]),
                           (mem.PARTY_NICKS_ADDR + slot * 11, raw[55:])):
            for offset, byte in enumerate(data):
                bus[base + offset] = byte
    bus[mem.PARTY_COUNT_ADDR] = 3
    for offset, byte in enumerate(before["species_list"]):
        bus[mem.PARTY_SPECIES_ADDR + offset] = byte
    bus[mem.PLAYER_ID_ADDR], bus[mem.PLAYER_ID_ADDR + 1] = 0xF0, 0x0D
    for offset, byte in enumerate([0x80, 0x92, 0x87] + [0x50] * 8):
        bus[mem.PLAYER_NAME_ADDR + offset] = byte
    bus[mem.BATTLE_FLAG_ADDR] = 1
    bus[0xCC2F] = 0
    bus[mem.BATTLE_MON_HP_ADDR], bus[mem.BATTLE_MON_HP_ADDR + 1] = 0, 10
    assert json.loads(lua.globals().readback()) == before
    return before


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("failure", [None, "before", "after", "partial", "identity", "unsafe"])
def test_real_memory_writer_intent_recovery_and_independent_server_receipt(runtime, variant, failure):  # noqa: F811
    lua = runtime
    start(lua)
    before = bind_memory(lua, variant)
    command = command_for(before, 0)
    command_id = "a" * 32
    event = lua.globals().append('{"event":"tick"}')
    assert accepted(lua.globals().accept(event, json.dumps([{
        "command_id": command_id, "command_sequence": 1, "body": command}])) )
    lua.globals().command_id = command_id
    lua.globals().fail_at = failure
    lua.execute("""
        allowed=true
        local native=M.forceFaint
        M.forceFaint=function(slot)
            if fail_at=='before' then error('before write') end
            if fail_at=='partial' then
                M.write_u16_be(M.PARTY_BASE_ADDR+slot*44+M.HP_OFFSET,0);error('missing battle mirror')
            end
            local result=native(slot)
            if fail_at=='after' then error('after actual write') end
            return result
        end
        adapter=require('gen1_force_faint_executor').new(M,variant,{ot_id='F00D',trainer_name='ASH'},
            function()return allowed,'test denies write context' end)
        Executor=require('command_executor');executor=Executor.new(journal,adapter)
        function run()return executor:step(command_id)end
    """)
    if failure == "identity":
        lua.globals().bus[lua.globals().M.PLAYER_ID_ADDR] = 0
    if failure == "unsafe":
        lua.globals().allowed = False
    ok, result = lua.globals().run()
    if failure:
        assert ok is False and result.retryable is True
        assert len(lua.globals().state().outbox) == 0
        lua.globals().reopen()
        lua.execute("executor=Executor.new(journal,adapter)")
        lua.globals().fail_at = None
        previous_writes = lua.globals().physical_writes
        ok, result = lua.globals().run()
        if failure in ("partial", "identity", "unsafe"):
            assert ok is False and lua.globals().physical_writes == previous_writes
            assert lua.globals().state().inbox[1].outcome is None
            return
        assert lua.globals().physical_writes == previous_writes + (4 if failure == "before" else 0)
    assert ok is True
    state = json.loads(lua.globals().disk)["document"]["payload"]
    receipt = state["inbox"][0]["receipt"]
    assert receipt["schema"] == RECEIPT_SCHEMA and receipt["after"] == json.loads(lua.globals().readback())
    assert verify_force_faint_receipt(command, receipt, variant=variant, identity=IDENTITY)["slot"] == 0
    snapshot_copy = copy.deepcopy(receipt)
    snapshot_copy["assert_success"] = True
    with pytest.raises(JournalError):
        verify_force_faint_receipt(command, snapshot_copy, variant=variant, identity=IDENTITY)
