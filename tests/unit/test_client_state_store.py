import hashlib
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    assert lua.eval("_VERSION") == "Lua 5.4", "shared client fixture must match the admitted BizHawk Lua ABI"
    lua.globals().root = ROOT.as_posix()
    lua.globals().hash_text = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
    lua.execute("""
        package.path=root..'/lua/?.lua;'..package.path
        JSON=require('json_codec');Store=require('state_store')
        disk=nil;mode='ok';writes=0;closed=0;read_error=nil
        backend={read=function()
            if read_error then return nil,read_error end
            if disk then return disk end; return nil,'missing' end,
          replace=function(text)
            writes=writes+1
            if mode=='before' then return false,'before publication' end
            disk=mode=='corrupt' and 'corrupt' or text
            if mode=='after' then return false,'uncertain after publication' end
            return true end,
          sha256=function(text) return hash_text(text) end,
          close=function()closed=closed+1 end}
        binding={run_id='run',player='a',save_id='0000',rom='hash'}
        initial={outbox=JSON.array(),inbox=JSON.array()}
        function open_store() return Store.open(backend,binding,initial) end
    """)
    return lua


def opened(lua):
    result = lua.globals().open_store()
    assert not isinstance(result, tuple), result
    lua.globals().store = result
    return result


def test_publish_readback_reopen_and_detached_reads(runtime):
    lua = runtime
    store = opened(lua)
    assert store.read(store)[1] == 0
    payload = lua.eval("{outbox=JSON.array({{operation_id='one',event='capture'}}),inbox=JSON.array()}")
    assert store.commit(store, payload) is True
    payload.outbox[1].event = "changed by caller"
    current, revision = store.read(store)
    assert revision == 1 and current.outbox[1].event == "capture"
    current.outbox[1].event = "changed reader copy"
    assert store.read(store)[0].outbox[1].event == "capture"
    store.close(store)
    again = opened(lua)
    assert again.read(again)[1] == 1
    assert again.read(again)[0].outbox[1].event == "capture"
    assert json.loads(lua.globals().disk)["document"]["payload"]["inbox"] == []


def test_revision_token_changes_only_on_commits_and_refuses_faulted_or_closed_owner(runtime):
    lua=runtime
    store=opened(lua)
    assert store.revision(store)==0
    payload,revision=store.read(store)
    payload['foreign']='detached'
    assert store.revision(store)==revision==0
    assert store.commit(store,payload) is True and store.revision(store)==1
    lua.globals().mode='after'
    assert store.commit(store,lua.eval('{new=true}'))[0] is False
    assert store.revision(store)[0] is None
    store.close(store)
    lua.globals().mode='ok'
    reopened=opened(lua)
    assert reopened.revision(reopened)==2
    reopened.close(reopened)
    assert reopened.revision(reopened)[0] is None


@pytest.mark.parametrize("mode,committed", [("before", False), ("after", True)])
def test_uncertain_publication_latches_until_reopen(runtime, mode, committed):
    lua = runtime
    store = opened(lua)
    before = lua.globals().disk
    lua.globals().mode = mode
    accepted, reason = store.commit(store, lua.eval("{value='new'}"))
    assert accepted is False and reason
    count = lua.globals().writes
    assert store.commit(store, lua.eval("{value='must not overwrite'}"))[0] is False
    assert lua.globals().writes == count
    assert (lua.globals().disk != before) is committed
    lua.globals().mode = "ok"
    store.close(store)
    again = opened(lua)
    assert again.read(again)[1] == int(committed)


@pytest.mark.parametrize("change", ["checksum", "binding", "extra", "corrupt", "unreadable"])
def test_invalid_or_unreadable_state_never_becomes_an_empty_outbox(runtime, change):
    lua = runtime
    opened(lua)
    if change == "checksum":
        doc = json.loads(lua.globals().disk)
        doc["document"]["payload"]["outbox"] = [{"lost": "event"}]
        lua.globals().disk = json.dumps(doc)
    elif change == "binding":
        lua.globals().binding.player = "b"
    elif change == "extra":
        doc = json.loads(lua.globals().disk)
        doc["unexpected"] = True
        lua.globals().disk = json.dumps(doc)
    elif change == "corrupt":
        lua.globals().disk = "not-json"
    else:
        lua.globals().read_error = "access denied"
    count, before = lua.globals().writes, lua.globals().disk
    result, reason = lua.globals().open_store()
    assert result is None and reason
    assert lua.globals().writes == count and lua.globals().disk == before


def test_changed_file_or_failed_readback_stops_further_mutations(runtime):
    lua = runtime
    store = opened(lua)
    lua.globals().mode = "corrupt"
    assert store.commit(store, lua.eval("{value=1}"))[0] is False
    count = lua.globals().writes
    lua.globals().mode = "ok"
    assert store.commit(store, lua.eval("{value=2}"))[0] is False
    assert lua.globals().writes == count


def test_invalid_initial_or_replacement_payload_never_reaches_disk(runtime):
    lua = runtime
    lua.execute("initial=JSON.array()")
    assert lua.globals().open_store()[0] is None
    assert lua.globals().writes == 0
    lua.execute("initial={outbox=JSON.array()}")
    store = opened(lua)
    before = lua.globals().disk
    assert store.commit(store, lua.eval("JSON.array()"))[0] is False
    assert lua.globals().disk == before


def test_large_exact_readback_keeps_detached_state_and_reopen_revalidates(runtime):
    lua = runtime
    store = opened(lua)
    payload = lua.eval("JSON.object({blob=string.rep('A',74000),nested=JSON.array({1,2,3})})")
    assert store.commit(store, payload) is True
    wire = lua.globals().disk
    payload.blob = "changed outside store"
    assert store.read(store)[0].blob == "A" * 74000
    assert lua.globals().disk == wire
    store.close(store)
    reopened = opened(lua)
    assert reopened.read(reopened)[0].blob == "A" * 74000
    changed = json.loads(wire)
    changed["document"]["payload"]["blob"] = "corrupt"
    lua.globals().disk = json.dumps(changed)
    reopened.close(reopened)
    assert lua.globals().open_store()[0] is None, "reopen must check the file checksum afresh"


@pytest.mark.parametrize("expression", [
    "(function() local value={} value.self=value return value end)()",
    "JSON.object({blob=string.char(255)})",
    "JSON.object({bad=function()end})",
])
def test_invalid_large_commit_never_reaches_atomic_replace(runtime, expression):
    lua = runtime
    store = opened(lua)
    before, writes = lua.globals().disk, lua.globals().writes
    value = lua.eval(expression)
    assert store.commit(store, value)[0] is False
    assert lua.globals().disk == before and lua.globals().writes == writes
    store.close(store)
    again = opened(lua)
    assert len(again.read(again)[0].outbox) == 0


def test_read_copies_nested_validated_types_without_exposing_the_private_cache(runtime):
    lua=runtime
    lua.execute('''initial={empty_array=JSON.array(),empty_object=JSON.object(),
        nested=JSON.array({JSON.null,false,{unicode='é雪',number=9007199254740991}})}''')
    store=opened(lua)
    original=lua.globals().disk
    lua.execute('''
        local first=assert(store:read())
        assert(JSON.kind(first.empty_array)=='array' and JSON.kind(first.empty_object)=='object')
        assert(first.nested[1]==JSON.null and first.nested[2]==false and first.nested[3].unicode=='é雪')
        first.nested[3].unicode='changed';first.empty_array[1]='changed'
        -- Public fields cannot replace the validated cache or its wire preimage.
        store.document={payload={forged=true},revision=999};store.wire='forged'
        local second,revision=store:read()
        assert(revision==0 and second.nested[3].unicode=='é雪' and #second.empty_array==0)
        assert(second.nested[3].number==9007199254740991)
    ''')
    assert lua.globals().disk==original
    assert store.commit(store,lua.eval("{next=JSON.array({JSON.null})}")) is True
    assert store.read(store)[1]==1
