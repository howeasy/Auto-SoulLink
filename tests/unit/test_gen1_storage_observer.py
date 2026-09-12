"""The actual Lua storage observer reads unsafe contexts with zero writes/flushes."""

import hashlib
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError

from server.gen1_held_faint import PROFILES
from tests.unit.test_gen1_held_faint import checkpoint
from tests.unit.test_gen1_memorial import fixture, load_point


@pytest.mark.parametrize("field", ["BATTLE_FLAG_ADDR", "FONT_LOADED_ADDR"])
def test_unsafe_storage_read_keeps_actual_checkpoint_and_never_uses_write_predicate(field):
    point, key, _ = fixture("yellow", count=2, slot=0)
    lua, mem = load_point(point)
    g = lua.globals()
    g.mem = mem
    g.root = Path(__file__).resolve().parents[2].as_posix()
    raw = checkpoint("yellow")
    raw["system"][str(PROFILES["yellow"][field])] = 1
    g.profile_json = json.dumps(PROFILES["yellow"])
    g.checkpoint_json = json.dumps(raw)
    g.sha = lambda value: hashlib.sha256(value.encode()).hexdigest()
    lua.execute("""
      package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
      JSON=require('json_codec');Canonical=require('journal_document')
      mem.profile=assert(JSON.decode(profile_json));cp=assert(JSON.decode(checkpoint_json))
      for address,value in pairs(cp.system)do bus[tonumber(address)]=value end
      for address,value in pairs(cp.rom)do bus[tonumber(address)]=value end
      emu={framecount=function()return 100 end,getregister=function(name)return name=='PC' and cp.pc or cp.sp end}
      gameinfo={getromhash=function()return string.rep('f',40)end}
      writes=0; safe_calls=0; permits=0; flushes=0; held=true
      package.loaded.platform_saveram={new=function()flushes=flushes+1;error('read constructed save writer')end}
      writer=require('gen1_held_storage').new({memory=mem,variant='yellow',
        safe=function()safe_calls=safe_calls+1;return false end,
        permitted=function()permits=permits+1;return false end,
        owned=function()return {context_generation=string.rep('a',32)}end,
        host={status=function()return {physical_stop_verified=held,owner_id=string.rep('1',32),
          capability_id='bizhawk-2.11.1-gambatte-exclusive-hold-v1',process_id=10}end},
        sha=function(value)return sha(assert(Canonical.encode(value)))end})
      body={cmd='storage_observe',job_id=string.rep('b',32),key='fixture'}
      intent=writer.prepare(body);state,point=writer.classify(body,intent)
      receipt=writer.receipt(body,intent,point,{command_id=string.rep('c',32),command_sequence=1})
    """)
    assert g.state == "after"
    receipt = json.loads(lua.eval("JSON.encode(receipt)"))
    assert receipt["checkpoint"] == raw and receipt["schema"] == "rby-storage-observation-v1"
    assert g.writes == g.safe_calls == g.permits == g.flushes == 0
    lua.execute("held=false")
    with pytest.raises(LuaError, match="owned held storage read"):
        lua.execute("writer.prepare(body)")
