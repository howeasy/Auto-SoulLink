"""Real preparation/codec/journal logic, with explicit modeled cartridge bytes."""
import copy
import hashlib
import json
from itertools import product

import pytest
from lupa.lua54 import LuaRuntime

from server.gen1_trade_preparation import (
    SCHEMA, SYMBOLS, boxed_keys, preparation_payload, validate_checkpoint, verify_preparation,
)
from server.protocol import digest
from server.protocol_journal import JournalError
from server.trade_coordinator import NAMESPACE
from tests.unit.test_gen1_trade_rules import snapshot
from tests.unit.test_trade_coordinator import Run


def checkpoint(run, player):
    rules = run.policy.rules[player]
    mon = rules.codec.validate_blob(bytes.fromhex(run.original["rules"]["parties"][player][0]))
    observed = snapshot(mon, run.contexts[player]);observed["variant"] = rules.variant
    raw = mon.raw
    storage = bytearray(404)
    storage[:3] = bytes((1, raw[0], 255))
    storage[8:52], storage[272:283], storage[338:349] = raw[:44], raw[44:55], raw[55:]
    name = bytes((0x92, 0x80, 0x8C, 0x84)) + b"\x50"*7  # SAME
    cart = bytearray(0x8000)
    sym = SYMBOLS["pokeyellow" if rules.variant == "yellow" else "pokered"]
    start, end = sym["sGameData"]-0x8000, sym["sMainDataCheckSum"]-0x8000
    player_id = sym["sMainData"]-0x8000+sym["wPlayerID"]-sym["wMainDataStart"]
    cart[start:start+11] = name
    cart[player_id:player_id+2] = bytes.fromhex(observed["save_id"])
    cart[end] = (255-sum(cart[start:end])) % 256
    for index in range(12):
        cart[(2+index//6)*0x2000+(index % 6)*1122+1] = 255
    active = bytearray(1122);active[1] = 255
    return {"schema": SCHEMA, "final_sha1": rules.rom_sha1, "party": observed,
        "party_storage_hex": storage.hex().upper(), "name_hex": name.hex().upper(), "map": 1,
        "current_box": 128, "active_box_hex": active.hex().upper(), "cart_hex": cart.hex().upper()}


def setup(run):
    run.offer();run.accept()
    # status is intentionally a projection; the stored record is authoritative.
    trade = run.journal.record(NAMESPACE, run.tx).value
    checkpoints = {p: checkpoint(run, p) for p in ("a", "b")}
    payload = preparation_payload(trade, "a", rules=run.policy.rules, checkpoints=checkpoints)
    command = {"command_id": "e"*32, "command_sequence": 3, "body": {
        "cmd": "native_trade_prepare", "player": "a", "transaction_id": run.tx,
        "proposal_digest": trade["proposal_digest"], "payload": payload}}
    receipt = {"schema": "rby-native-ready-v1", "command_id": command["command_id"], "command_sequence": 3,
        "transaction_id": run.tx, "proposal_digest": trade["proposal_digest"],
        "context_generation": run.contexts["a"].context_generation, "checkpoint": checkpoints["a"]}
    return trade, checkpoints, command, receipt


@pytest.fixture
def case(tmp_path):
    run = Run(tmp_path, ("yellow", "yellow"), identical=True)
    yield run, setup(run)
    run.journal.close()


@pytest.mark.parametrize("variants", list(product(("red", "blue", "yellow"), repeat=2)))
def test_every_pair_prepares_actual_names_and_exact_recipient_evolution(tmp_path, variants):
    run = Run(tmp_path, variants, evolution=True)
    try:
        _, checkpoints, command, receipt = setup(run)
        prepared = verify_preparation(command, receipt, rules=run.policy.rules["a"])
        assert prepared.details["evolved_species"] == 149  # received Kadabra
        assert prepared.details["peer_name_hex"] == checkpoints["b"]["name_hex"]
        assert prepared.details["checkpoint_digest"] == digest(checkpoints["a"])
        assert prepared.details["boxed_keys"] == []
        assert prepared.evidence_digest == run.policy.rules["a"].codec.validate_blob(
            bytes.fromhex(checkpoints["a"]["party"]["party"][0])).sha256
    finally:
        run.journal.close()


@pytest.mark.parametrize("change", ["command", "sequence_bool", "context", "transaction", "party", "storage",
    "hash", "checksum", "save_name", "name_length", "active_count", "active_terminator", "box_flag",
    "box_bool", "omitted_cart", "extra", "evolution"])
def test_changed_or_incomplete_preparation_cannot_produce_ready(case, change):
    run, (_, _, command, original) = case
    receipt = copy.deepcopy(original);point = receipt["checkpoint"]
    if change == "command": receipt["command_id"] = "f"*32
    elif change == "sequence_bool": receipt["command_sequence"] = True
    elif change == "context": receipt["context_generation"] = "f"*32
    elif change == "transaction": receipt["transaction_id"] = "f"*32
    elif change == "party": point["party"]["party"][0] = "00"*66
    elif change == "storage": point["party_storage_hex"] = "00"*404
    elif change == "hash": point["final_sha1"] = "f"*40
    elif change == "checksum": point["cart_hex"] = "00"*0x8000
    elif change == "save_name": point["name_hex"] = "80"+point["name_hex"][2:]
    elif change == "name_length": point["name_hex"] += "50"
    elif change == "active_count": point["active_box_hex"] = "15"+point["active_box_hex"][2:]
    elif change == "active_terminator": point["active_box_hex"] = "0000"+point["active_box_hex"][4:]
    elif change == "box_flag": point["current_box"] = 140
    elif change == "box_bool": point["current_box"] = True
    elif change == "omitted_cart": del point["cart_hex"]
    elif change == "extra": point["held"] = True
    elif change == "evolution": command["body"]["payload"]["evolved_species"] = 1
    with pytest.raises((JournalError, ValueError)):
        verify_preparation(command, receipt, rules=run.policy.rules["a"])


def put_box(point, raw, *, index=None):
    box = bytearray(1122);box[:3] = bytes((1, raw[0], 255));box[22:55] = raw[:33]
    if index is None:point["active_box_hex"] = box.hex().upper()
    else:
        cart = bytearray.fromhex(point["cart_hex"])
        offset = (2+index//6)*0x2000+(index % 6)*1122
        cart[offset:offset+1122] = box
        point["cart_hex"] = cart.hex().upper()


@pytest.mark.parametrize("index", [None, 1, 11])
def test_active_other_and_memorial_box_collisions_are_independently_refused(case, index):
    run, (_, _, command, receipt) = case
    raw = bytes.fromhex(receipt["checkpoint"]["party"]["party"][0])
    put_box(receipt["checkpoint"], raw, index=index)
    with pytest.raises(ValueError, match="duplicate party or boxed key"):
        verify_preparation(command, receipt, rules=run.policy.rules["a"])


def test_stale_active_sram_and_uninitialized_inactive_boxes_are_not_live_inventory(case):
    run, (trade, _, _, receipt) = case
    point = receipt["checkpoint"];raw = bytes.fromhex(point["party"]["party"][0])
    put_box(point, raw, index=0)
    assert not validate_checkpoint(point, rules=run.policy.rules["a"], participant=trade["proposal"]["participants"]["a"])
    point["current_box"] = 0
    put_box(point, raw, index=11)
    assert not boxed_keys(point, run.policy.rules["a"].codec)


@pytest.mark.parametrize("change", ["none", "box", "save", "context"])
def test_lua_preparation_uses_durable_intent_and_readback_without_writes(case, change):
    run, (_, _, command, expected) = case
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    lua = LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals();g.root = root.as_posix()
    g.checkpoint_json = json.dumps(expected["checkpoint"]);g.command_json = json.dumps(command)
    g.context = expected["context_generation"]
    g.hash_text = lambda text: hashlib.sha256(text.encode()).hexdigest()
    lua.execute('''
        package.path=root..'/lua/?.lua;'..package.path
        JSON=require('json_codec');Prep=require('gen1_trade_preparation')
        point=assert(JSON.decode(checkpoint_json));command=assert(JSON.decode(command_json));writes=0;authorized=true
        manifest={schema='gen1-native-trade-build-v1',variant='yellow',test_probe=JSON.null,
            final_sha1=point.final_sha1,readback={party={address=0xD162}},ram={wPlayerName=0xD157,wCurMap=0xD35D}}
        local ranges={{0xD162,point.party_storage_hex},{0xD157,point.name_hex},{0xDA7F,point.active_box_hex}}
        memory={getmemorydomainlist=function()return {'System Bus','CartRAM'}end,read_u8=function(a,d)
            if d=='CartRAM'then return tonumber(point.cart_hex:sub(a*2+1,a*2+2),16)end
            if a==mem.CURRENT_BOX_NUM_ADDR then return point.current_box end
            if a==manifest.ram.wCurMap then return point.map end
            for _,r in ipairs(ranges)do
                if a>=r[1] and (a-r[1])*2<#r[2]then return tonumber(r[2]:sub((a-r[1])*2+1,(a-r[1])*2+2),16)end
            end
            return 0
        end,write_u8=function()writes=writes+1;error('preparation wrote RAM')end}
        mem=require('memory_gb');mem.initProfile(require('games.gen1_rby'),'yellow')
        -- Only the physical host checkpoint is modeled; all party/box readers are real.
        mem.isPartyWriteSafe=function()return true end
        gameinfo={getromhash=function()return point.final_sha1 end}
        disk=nil
        backend={read=function()return disk,disk and nil or 'missing'end,
            replace=function(text)disk=text;return true end,sha256=function(text)return hash_text(text)end}
        Journal=require('client_journal');Store=require('state_store');n=0
        store=assert(Store.open(backend,{run='fixture'},Journal.initial()))
        journal=assert(Journal.open(store,function()n=n+1;return string.format('%032x',n)end,require('gen1_trade_events')))
        poll=assert(journal:append({event='tick'}));assert(journal:accept_response(poll,JSON.array({command})))
        adapter=Prep.new({memory=mem,manifest=manifest,player='a',context_generation=function()return context end,
            sha256=backend.sha256,authorize=function()return authorized end})
        executor=require('command_executor').new(journal,adapter)
        function step()local ok,result=executor:step(command.command_id);return ok,JSON.encode(result)end
    ''')
    g.authorized = False
    ok, result = g.step();assert not ok and json.loads(result)["phase"] == "prepare"
    g.authorized = True
    if change != "none":
        lua.execute('''
            intent=adapter.prepare(command.body,{command_id=command.command_id,command_sequence=command.command_sequence})
            assert(journal:prepare_command(command.command_id,intent))
        ''')
        if change == "box":g.point.current_box = 129
        elif change == "save":g.point.cart_hex = "FF"+g.point.cart_hex[2:]
        else:g.context = "f"*32
        ok, result = g.step()
        assert not ok and json.loads(result)["phase"] == "classify"
        assert not lua.eval("journal:get_command(command.command_id).outcome")
        assert json.loads(lua.eval("JSON.encode(journal:pending_events())")) == []
        assert g.writes == 0
        return
    ok, result = g.step();assert ok, result
    receipt = json.loads(result)["receipt"]
    assert receipt == expected
    assert verify_preparation(command, receipt, rules=run.policy.rules["a"])
    assert g.writes == 0
    assert json.loads(lua.eval("JSON.encode(journal:pending_events())"))[0]["payload"]["event"] == "trade_ready"
    ok, result = g.step();assert ok and json.loads(result)["replayed"]
