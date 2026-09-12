import json

import pytest

from server.gen1_bootstrap_receipt import DATA
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401


@pytest.fixture
def probe(runtime):  # noqa: F811
    start(runtime)
    runtime.globals().data_json = json.dumps(DATA)
    runtime.execute("""
        package.loaded.gen1_bootstrap_sites=assert(JSON.decode(data_json))
        profile=JSON.decode(data_json).titles.yellow
        rom={};bus={};hooks={};frame=100;pc=0;sp=0xDFFE;held=true
        scope={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
        hash=profile.clean_sha1
        memory={read_u8=function(a,d)return (d=='ROM' and rom[a] or bus[a])or 0 end}
        gameinfo={getromhash=function()return hash end}
        emu={framecount=function()return frame end,getregister=function(k)return k=='PC' and pc or sp end}
        event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,
            unregisterbyid=function(name)hooks[name]=nil end}
        for _,site in pairs(profile.sites)do
            for i=1,#site.expected_hex,2 do
                local v=tonumber(site.expected_hex:sub(i,i+1),16)
                rom[site.rom_offset+(i-1)/2]=v;bus[site.address+(i-1)/2]=v
            end
        end
        function create()return require('gen1_bootstrap_observer').new({variant='yellow',final_sha1=hash,
            owned=function()return scope end,held=function()return held end})end
        probe=create()
        function fire(kind)
            local site=profile.sites[kind];pc=site.address;bus[profile.bank_address]=site.bank
            hooks['slink-bootstrap-'..kind]()
        end
    """)
    return runtime


def test_bootstrap_hooks_only_publish_complete_detached_witness(probe):
    probe.execute("""
        assert(probe.peek()==nil);fire('begin');assert(probe.peek()==nil)
        frame=900;fire('end');local result=probe.peek()
        assert(result.begin.frame==100 and result['end'].frame==900)
        result.begin.frame=2;assert(probe.peek().begin.frame==100)
        probe.close();assert(next(hooks)==nil);assert(not pcall(probe.peek))
    """)


@pytest.mark.parametrize(
    "fault",
    [
        "return_only",
        "overlap",
        "restart",
        "same_frame",
        "stack",
        "context",
        "rom",
        "instruction",
        "unheld",
    ],
)
def test_bootstrap_observer_refuses_lost_ownership_or_invalid_call_sequence(probe, fault):
    code = {
        "return_only": "fire('end')",
        "overlap": "fire('begin');fire('begin')",
        "restart": "fire('begin');frame=900;fire('end');fire('begin')",
        "same_frame": "fire('begin');fire('end')",
        "stack": "fire('begin');sp=sp-2;frame=900;fire('end')",
        "context": "scope.context_generation='changed'",
        "rom": "hash=string.rep('f',40)",
        "instruction": "bus[profile.sites.begin.address]=0;fire('begin')",
        "unheld": "held=false",
    }[fault]
    probe.execute(code + ";assert(not pcall(probe.peek))")
