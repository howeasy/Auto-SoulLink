"""P2A-2C, client half of run-boundary resume: a launch carrying `resume` constructs the CONTINUE
observer (never the New Game bootstrap observer), hands it the required digest with an injected
sha256, lets the free loop enroll on the initial ack alone, and fails loudly the moment the
observer reports that the loaded save is not the predecessor's. Without `resume` the entry is
unchanged: bootstrap observer, no continue observer, bootstrap ack still gates the loop."""
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]

RESUME = {"from_run": "c" * 32, "required_digest": "d" * 64, "projection": "cartram-0498-8000-v1"}


def launch(**changes):
    value = {"schema": "slink-gen1-launch-v1", "protocol": "slink-gen1-durable-v1", "mode": "free_service",
             "run_id": "a" * 32, "player": "a", "host": "localhost", "port": 9000, "initial_observations": True,
             "cartridge": {"variant": "yellow", "final_rom_sha1": "e" * 40}}
    value.update(changes)
    return value


HARNESS = r"""
    package.path=root..'/lua/?.lua;'..package.path
    JSON=require('json_codec');physical=false;nonce=0;frame=100;built={};witness={complete=true,failed=nil};loop_built=false
    gameinfo={getromhash=function()return string.rep('e',40)end}
    emu={framecount=function()return frame end,yield=function()end,frameadvance=function()error('startup advanced a frame')end}
    gui={drawText=function()end,drawBox=function()end,clearGraphics=function()end}
    event={onloadstate=function()return 'load-hook'end,unregisterbyid=function()end}
    console={log=function()end}
    package.loaded['memory_gb']={initProfile=function()end,isPartyWriteSafe=function()return true end,
        readPlayerId=function()return 0 end,readPlayerName=function()return 'SAME'end,read_u8=function()return 1 end}
    package.loaded['games.gen1_rby']={}
    package.loaded['gen1_runtime_profiles']={metadata=function(_,cartridge)return cartridge end}
    package.loaded['platform_identity']={new_nonce=function()nonce=nonce+1;return string.format('%032x',nonce)end}
    local host={set_held=function(value)physical=value;return true end,verify=function()return true end,
        status=function()return {held=physical,physical_stop_verified=physical}end,yield_held=function()return true end}
    package.loaded['platform_execution']={supported_profile=function()return {}end,new=function()return host end}
    package.loaded['platform_clock']={new=function()return function()return 0 end end}
    -- The injected sha256 comes from the .NET host: model the three types the entry imports.
    hashed=nil
    luanet={load_assembly=function()end,import_type=function(name)
        if name=='System.IO.Path'then return {GetFullPath=function(value)return value end,GetDirectoryName=function()return 'tmp'end}end
        if name=='System.Security.Cryptography.SHA256'then return {Create=function()return {ComputeHash=function(_,bytes)hashed=bytes;return 'raw'end,Dispose=function()end}end}end
        if name=='System.BitConverter'then return {ToString=function()return 'DE-AD'end}end
        if name=='System.Text.UTF8Encoding'then return function()return {GetBytes=function(_,text)return text end}end end
        error('unexpected type '..name)
    end}
    baseline={initial_inventory={phase='acknowledged',operation_id=string.rep('9',32)},observation_sequence=0}
    local store={read=function()return {observation=baseline}end,close=function()end,backend={sha256=function()return string.rep('f',64)end}}
    package.loaded['platform_storage']={new=function()return {}end}
    package.loaded['state_store']={open=function()return store end}
    package.loaded['connector']={}
    local journal={store=store,hud_state=function()return nil end,pending_commands=function()return {}end,pending_events=function()return {}end}
    package.loaded['client_journal']={initial=function()return {}end,open=function()return journal end}
    package.loaded['gen1_bootstrap_observer']={new=function(o)built.bootstrap=o;return {close=function()end,status=function()return{}end}end}
    package.loaded['gen1_continue_observer']={new=function(o)built.continue=o;return {close=function()end,status=function()return witness end,
        peek=function()return witness.complete and {schema='rby-continue-receipt-v1'}or nil end}end}
    package.loaded['gen1_initial_observation']={new=function(o)built.observation=o
        return {signals={status=function()return{}end},step=function()end,close=function()end}end}
    package.loaded['gen1_held_faint']={new=function()return {handles=function()return false end,ready=function()return false end,
        pending=function()return false end,operations={request=function()end,accept=function()return true end,
            authorize_apply=function()return false end,revoke=function()end,status=function()return{}end},adapter={}}end}
    package.loaded['gen1_acquisition_observers']={new=function()return {close=function()end}end}
    package.loaded['battle_force_authority']={service=function()return {revoke=function()return true end,close=function()return true end,status=function()return{}end}end}
    package.loaded['gen1_runtime']={unwrap=function(v)return v end,new=function()
        return {step=function()return true end,has_service_lease=function()return true end,is_bound=function()return true end,
            observe=function()return {1}end,status=function()return {}end,revoke=function()end}end}
    package.loaded['gen1_observation_loop']={new=function(ctx)loop_built=true;return {tick=function()end,continuity=function()return nil end,status=function()return {}end}end}
    function start(launch_json)
        service=assert(require('gen1_client_entry').start(assert(JSON.decode(launch_json)),{root=root,storage_root='tmp'}))
        return service
    end
"""


@pytest.fixture
def lua():
    value = LuaRuntime(unpack_returned_tuples=True)
    value.globals().root = ROOT.as_posix()
    value.execute(HARNESS)
    return value


def test_resume_launch_builds_the_continue_observer_with_the_required_digest_and_injected_sha256(lua):
    lua.globals().launch_json = json.dumps(launch(resume=RESUME))
    lua.execute(r'''
        start(launch_json);assert(service:step())
        assert(built.bootstrap==nil and built.continue~=nil,'resume witnesses CONTINUE, not New Game')
        assert(built.continue.required_digest==string.rep('d',64) and built.continue.projection=='cartram-0498-8000-v1')
        assert(built.continue.sha256('ABCD')=='dead' and hashed=='ABCD','sha256 hashes the projection text through the host')
        assert(built.observation.continue_observer~=nil and built.observation.bootstrap==nil)
        assert(loop_built,'the free loop enrolls on the initial ack alone; no bootstrap ack exists in resume mode')
        local s=service:status();assert(s.resume.from_run==string.rep('c',32) and s.continue_observer~=nil and s.bootstrap==nil)
    ''')


def test_without_resume_the_entry_is_unchanged(lua):
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json);assert(service:step())
        assert(built.bootstrap~=nil and built.continue==nil and built.observation.bootstrap~=nil and built.observation.continue_observer==nil)
        assert(not loop_built,'without the bootstrap ack the loop stays unbuilt, as today')
        baseline.bootstrap={phase='acknowledged'};assert(service:step());assert(loop_built)
        local s=service:status();assert(s.resume==nil and s.continue_observer==nil)
    ''')


def test_a_failed_continue_witness_fails_the_client_before_enrollment(lua):
    lua.globals().launch_json = json.dumps(launch(resume=RESUME))
    lua.execute(r'''
        witness={complete=false,failed='resumed save differs from the required predecessor witness'}
        start(launch_json)
        local ok,why=service:step()
        assert(ok==false and tostring(why):find('resumed save differs') and service.phase=='failed' and service.runtime==nil)
    ''')


@pytest.mark.parametrize("fault", ["from_run", "digest", "projection", "extra", "not_table", "no_observations"])
def test_a_malformed_resume_contract_is_refused_at_launch(lua, fault):
    resume = dict(RESUME)
    if fault == "from_run":
        resume["from_run"] = ""
    elif fault == "digest":
        resume["required_digest"] = "D" * 64
    elif fault == "projection":
        resume["projection"] = "cartram-0000-8000-v1"
    elif fault == "extra":
        resume["frame"] = 1
    elif fault == "not_table":
        resume = "c" * 32
    value = launch(resume=resume)
    if fault == "no_observations":
        del value["initial_observations"]
        value["mode"] = "held_service"
    lua.globals().launch_json = json.dumps(value)
    lua.execute("local ok,why=pcall(start,launch_json);assert(not ok and tostring(why):find('resume'),tostring(why))")
