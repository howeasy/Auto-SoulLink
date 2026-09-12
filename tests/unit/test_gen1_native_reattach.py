"""The start-of-script native reattach read: overlay word, lease and CPU under the held bounded
owner, before any frame. It reads and reports; the server classifies. An APPLY-armed overlay
is reported armed with no frame advanced; an unheld host or a changed artifact refuses."""
import json

import pytest

from server.gen1_cartridge_profiles import companion_profiles
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401


@pytest.fixture
def probe(runtime):  # noqa: F811
    start(runtime)
    manifest = companion_profiles()["yellow"]["manifest"]
    runtime.globals().manifest_json = json.dumps(manifest)
    runtime.execute("""
        manifest=assert(JSON.decode(manifest_json));fg=manifest.foreground
        bus={};frame=4242;advanced=0;hash=manifest.final_sha1;held=true;stop=true
        memory={read_u8=function(a,d)return bus[a] or 0 end,
            bytesToHex=function(t)local o={};for i,v in ipairs(t)do o[i]=string.format('%02X',v)end;return table.concat(o)end}
        gameinfo={getromhash=function()return hash end}
        emu={framecount=function()return frame end,frameadvance=function()advanced=advanced+1;frame=frame+1 end,
            getregister=function(k)return k=='PC' and 0x0040 or k=='SP' and 0xDFF7 or 0 end}
        host={status=function()return {held=held,physical_stop_verified=stop}end}
        lease={schema='gen1-native-trade-lease-v1',phase='idle'}
        bus[manifest.ram.hLoadedROMBank]=1
        function overlay(bytes)for i,v in ipairs(bytes)do bus[fg.overlay+i-1]=v end end
        function read()return require('gen1_native_reattach').read({host=host,memory=memory,manifest=manifest,lease=function()return lease end})end
    """)
    return runtime


def test_an_apply_armed_overlay_is_reported_armed_with_no_frame_run(probe):
    probe.execute("""
        overlay({0x53,0x4c,0x54,0x31,1,5,7,6,0,0,0,0,0xA1,0xB2,0xC3,0xD4})
        lease={schema='gen1-native-trade-lease-v1',phase='armed',command_id=string.rep('c',32),intent_digest=string.rep('d',64),
            intent={token_hex='A1B2C3D4'}}
        local r=read()
        assert(r.schema=='rby-native-reattach-read-v1' and r.frame==4242 and advanced==0)
        assert(r.published==true and r.armed==true and r.done==false and r.phase==5 and r.token_hex=='A1B2C3D4')
        assert(r.lease.phase=='armed' and r.lease.token_hex=='A1B2C3D4' and r.lease.receipt==false and r.pc==0x40 and r.sp==0xDFF7 and r.bank==1)
        assert(r.overlay_hex=='534C54310105070600000000A1B2C3D4')
    """)


@pytest.mark.parametrize("shape", ["tiles", "done", "released", "consumed"])
def test_other_overlay_shapes_are_reported_not_armed(probe, shape):
    probe.execute({
        "tiles": "overlay({0x2A,0x2B,0x2C,0x2C,0x23,0x23,0x23,0x23,0x23,0x23,0x23,0x23,0x23,0x23,0x23,0x23})",
        "done": "overlay({0x53,0x4c,0x54,0x31,1,7,6,6,0,0,0,0,1,2,3,4})",
        "released": "overlay({0x53,0x4c,0x54,0x31,1,8,6,6,0,0,0,0,1,2,3,4})",
        "consumed": "overlay({0x53,0x4c,0x54,0x31,1,5,6,6,0,0,0,0,1,2,3,4})",  # generation already completed
    }[shape])
    probe.execute("""
        local r=read();assert(r.armed==false and advanced==0)
        if r.published then assert(r.phase~=nil) else assert(r.phase==JSON.null and r.token_hex==JSON.null) end
    """)
    if shape == "done":
        probe.execute("assert(read().done==true)")


@pytest.mark.parametrize("fault", ["unheld", "unverified_stop", "artifact", "lease_missing", "lease_schema"])
def test_the_read_refuses_without_the_held_owner_or_with_a_changed_context(probe, fault):
    probe.execute({
        "unheld": "held=false",
        "unverified_stop": "stop=false",
        "artifact": "hash=string.rep('f',40)",
        "lease_missing": "lease=nil",
        "lease_schema": "lease={schema='other',phase='idle'}",
    }[fault])
    probe.execute("assert(not pcall(read));assert(advanced==0)")
