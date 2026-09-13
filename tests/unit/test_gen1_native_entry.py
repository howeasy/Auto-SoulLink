"""The composed native free-service entry: a native manifest is accepted only on the free-service
client; before every pre-begin free frame the entry reads the physical arming state from source-
grounded bytes (published overlay word, or the word saved on the stack mid-routine) and, on either,
builds and holds the host BEFORE that frame; a cold boot free-runs however late the script starts;
the loop is constructed only when the read is clean and the server granted the lease with nothing
pending; a pending native command is serviced in bounded slices under the native vote with the core
held throughout; a failed step latches. Modeled runtime/native service, real hold_mux,
gen1_native_host and gen1_native_reattach."""
import hashlib
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "data/games/gen1_rby/companion_profiles.json").read_text())["profiles"]["yellow"]["manifest"]
SHA1 = MANIFEST["final_sha1"]
ARMED = [0x53, 0x4C, 0x54, 0x31, 1, 5, 7, 6, 0, 0, 0, 0, 0xA1, 0xB2, 0xC3, 0xD4]
TILES = [0x2A, 0x2B, 0x2C, 0x2C] + [0x23] * 12


def launch(**changes):
    value = {"schema": "slink-gen1-launch-v1", "protocol": "slink-gen1-durable-v1", "mode": "free_service",
             "run_id": "a" * 32, "player": "a", "host": "localhost", "port": 9000, "initial_observations": True,
             "cartridge": {"variant": "yellow", "final_rom_sha1": SHA1}, "native_manifest": MANIFEST}
    value.update(changes)
    return value


@pytest.fixture
def lua():
    value = LuaRuntime(unpack_returned_tuples=True)
    value.globals().root = ROOT.as_posix()
    value.globals().sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    value.execute(r'''
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');physical=false;pending=1;loop_built=false;startup_write=false;clock=0;nonce=0
        frame=0;advances=0;write_safe=true;bus={};lease={schema='gen1-native-trade-lease-v1',phase='idle'}
        native_commands={};runtime_steps=0;native_pumps=0;native_steps=0;stepper_authorize=true;observed={}
        -- The server's acknowledgement of a published event, as client_journal delivers it to the entry's callback.
        function acknowledge(verdict,class,read_digest)
            local event=observed[1]
            return journal_callbacks.acknowledge_event(event,string.rep('e',32),{observation_sequence=0},
                {schema='rby-native-reattach-result-v1',operation_id=string.rep('e',32),verdict=verdict,class=class,read_digest=read_digest or service.reattach_read_digest})
        end
        function overlay(bytes)for i,v in ipairs(bytes)do bus[MANIFEST.foreground.overlay+i-1]=v end end
        gameinfo={getromhash=function()return SHA1 end}
        sp=0xDFF7
        emu={framecount=function()return frame end,yield=function()error('script yielded before the hold')end,
            frameadvance=function()assert(not physical,'frame advanced under a hold');advances=advances+1;frame=frame+1 end,
            getregister=function(k)return k=='PC' and 0x40 or k=='SP' and sp or 0 end}
        -- A saved overlay word on the stack exactly as save_overlay_on_stack leaves it (pairs pushed: 31 54 4C 53 ascending).
        -- Pushed near the top of the fixed Stack section by the service; the CPU has since nested deeper (SP 0xDF10)
        -- and, at this frame boundary, vcopy has even borrowed SP as a pointer: the section scan finds it regardless.
        function stack_word()sp=0x8800;local saved={0x53,0x4C,0x54,0x31,1,5,7,6,0,0,0,0,0xA1,0xB2,0xC3,0xD4}
            local a=0xDFE0;for pair=8,1,-1 do bus[a]=saved[2*pair];bus[a+1]=saved[2*pair-1];a=a+2 end end
        -- BizHawk's global memory API (gen1_native_reattach reads the bus through it).
        memory={read_u8=function(a,d)if bus[a]~=nil then return bus[a]end;return (a>=0xC000 and a<0xE000) and 0 or 1 end}
        event={onloadstate=function(fn)return 'load-hook'end,onexit=function()return 'exit-hook'end,unregisterbyid=function()end}
        console={log=function()end}
        package.loaded['memory_gb']={initProfile=function()end,isPartyWriteSafe=function()return write_safe end,
            readPlayerId=function()return 0x1234 end,readPlayerName=function()return 'YELLOW'end,
            read_u8=function(a)if bus[a]~=nil then return bus[a]end;return (a>=0xC000 and a<0xE000) and 0 or 1 end,
            bytesToHex=function(t)local o={};for i,v in ipairs(t)do o[i]=string.format('%02X',v)end;return table.concat(o)end}
        package.loaded['games.gen1_rby']={}
        package.loaded['gen1_runtime_profiles']={metadata=function(_,cartridge)return cartridge end}
        package.loaded['platform_identity']={new_nonce=function()nonce=nonce+1;return string.format('%032x',nonce)end}
        local host={set_held=function(value)physical=value;return true end,verify=function()return true end,
            status=function()return {owner_id=string.format('%032x',2),held=physical,physical_stop_verified=physical,failed=false,closed=false,
                process_id=7,capability_id='fixture',host_blocked=physical,lease_owned=true,user_paused=false}end,
            yield_held=function()assert(physical);return true end}
        package.loaded['platform_execution']={supported_profile=function()return {}end,new=function()return host end}
        -- Modeled bounded owner (as tests/unit/test_gen1_native_host.py): steps by releasing/re-holding the injected adapter.
        package.loaded['platform_bounded_execution']={new=function(options)
            local shared=options.host.status();assert(shared.held==true and shared.physical_stop_verified==true,'injected actuator must be held')
            local expected=frame;local steps=0;local failed=nil;local owner={}
            function owner.step_one(scope)
                local ok,result=pcall(function()
                    assert(frame==expected,'bounded frame requires its unchanged held context')
                    assert(options.authorize(scope,{frame=frame})==true,'per-step authority is absent')
                    assert(options.host.set_held(false,'one frame'));if not physical then frame=frame+1 end
                    assert(options.host.set_held(true,'frame done'));assert(frame==expected+1,'bounded frame did not advance')
                    expected=frame;steps=steps+1;return {before=frame-1,after=frame}
                end)
                if not ok then failed=failed or tostring(result);return false,failed end
                return true,result
            end
            function owner.set_held(value,why)if value~=true then return false,'no unbounded release'end;return options.host.set_held(true,why)end
            function owner.yield_held()return options.host.yield_held()end
            function owner.close()failed=failed or 'closed';return true end
            function owner.status()return {schema='slink-bounded-execution-status-v1',failed=failed,steps=steps,host=options.host.status(),
                expected_frame=expected,single_frame_only=true,frame_callbacks_suppressed=true,load_state_invalidation=true,
                owner_exit_invalidation=true,frame_rate={numerator=262144,denominator=4389},armed=true}end
            return owner
        end}
        package.loaded['platform_clock']={new=function()return function()return clock end end}
        luanet={load_assembly=function()end,import_type=function(name)
            if name=='System.IO.Path'then return {GetFullPath=function(value)return value end,GetDirectoryName=function()return 'tmp'end}end
            error('unexpected type '..name)
        end}
        local baseline={initial_inventory={phase='acknowledged',operation_id=string.rep('9',32)},bootstrap={phase='acknowledged'},
            observation_sequence=1,observation_cursor={sequence=1,operation_id=string.rep('8',32),frame=100}}
        local store={read=function()return {observation=baseline}end,close=function()end,backend={sha256=function(text)return sha(text)end}}
        package.loaded['platform_storage']={new=function()return {}end}
        package.loaded['state_store']={open=function()return store end}
        package.loaded['connector']={}
        local journal={store=store,hud_state=function()return nil end,
            pending_commands=function()
                local rows={};if pending==1 then rows[#rows+1]={command_id='initial',body={cmd='initial_save'}}end
                for _,c in ipairs(native_commands)do rows[#rows+1]=c end;return rows end,
            pending_events=function()return {}end}
        package.loaded['client_journal']={initial=function()return {}end,open=function(_,_,callbacks)journal_callbacks=callbacks;return journal end}
        package.loaded['gen1_bootstrap_observer']={new=function()return {close=function()end,status=function()return{}end}end}
        local observer={signals={status=function()return{}end},step=function()end,close=function()end}
        package.loaded['gen1_initial_observation']={new=function()return observer end,capture=function()return{frame=100}end}
        local operations={request=function()end,accept=function()return true end,authorize_apply=function()return false end,
            revoke=function()end,status=function()return{}end}
        package.loaded['gen1_held_faint']={new=function()return {operations=operations,ready=function()return false end,
            handles=function(body)return body.cmd=='initial_save' or body.cmd=='force_faint' end,
            pending=function()return pending==1 end,adapter={prepare=function()end,classify=function()end,apply=function()end,receipt=function()end}}end}
        package.loaded['gen1_acquisition_observers']={new=function()return {close=function()end}end}
        package.loaded['battle_force_authority']={service=function()return {revoke=function()return true end,close=function()return true end,status=function()return{}end}end}
        package.loaded['gen1_receptionist_client']={query=function()return nil end}
        package.loaded['gen1_runtime']={unwrap=function(value)return value end,new=function(options)
            runtime_options=options
            return {step=function()
                    runtime_steps=runtime_steps+1
                    if pending==1 then assert(physical and options.operation_held(),'startup command lacks the startup hold');startup_write=true;pending=0 end
                    return true end,
                has_service_lease=function()return true end,is_bound=function()return true end,
                observe=function(_,events,baseline)for _,e in ipairs(events)do observed[#observed+1]=e end;observed_baseline=baseline;return {#observed}end,
                status=function()return{}end,revoke=function()end}
        end}
        -- Modeled native service: the embedded interface gen1_native_runtime exposes.
        package.loaded['gen1_native_runtime']={journal_options=function(observation)return observation end,
            new=function(options)
                native_options=options
                local s=options.host.status()
                assert(options.embedded==true and s.host.physical_stop_verified and s.single_frame_only,'native service needs a held bounded owner at construction')
                return {journal=options.journal,native_store={read=function()return lease end},
                    handles=function(body)return body.cmd=='native_trade_commit'end,
                    executor_adapter={},ready=function()return false end,operations=operations,update_control=function()end,
                    authorize_step=function()return stepper_authorize end,
                    pump_native=function()native_pumps=native_pumps+1 end,after_service=function()end,
                    step_native=function()
                        if #native_commands==0 then return false end
                        assert(options.host.step_one({phase='native_trade_commit'}));native_steps=native_steps+1
                        if native_steps>=3 then table.remove(native_commands,1)end    -- the routine completes after three frames
                        return true end,
                    status=function()return {embedded=true}end,close=function()end}
            end}
        package.loaded['gen1_observation_loop']={new=function(ctx)
            assert(startup_write and pending==0 and physical,'loop constructed before startup command settled')
            loop_built=true;loop_ctx=ctx
            return {tick=function()assert(not physical,'loop ticked under a hold');if ctx.writer:pending()then ctx.writer:service()end end,
                continuity=function()return nil,'not needed'end}
        end}
        function start(launch_json)
            service=assert(require('gen1_client_entry').start(assert(JSON.decode(launch_json)),{root=root,storage_root='tmp'}))
            return service
        end
    ''')
    value.globals().MANIFEST = value.eval("JSON.decode(...)", json.dumps(MANIFEST)) if False else None
    value.execute("MANIFEST=JSON.decode([[" + json.dumps(MANIFEST) + "]]);SHA1='" + SHA1 + "'")
    return value


def test_reattach_with_an_armed_overlay_holds_before_the_first_frame_reads_it_and_never_builds_the_loop(lua):
    lua.execute("frame=4242;write_safe=false;overlay(ARMED)".replace("ARMED", "{" + ",".join(map(str, ARMED)) + "}"))
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json)
        assert(service.native_physical()=='armed' and advances==0)
        assert(service:step())                                   -- the hold, the read and HELLO/control, no frame
        assert(physical==true and advances==0 and service.holds:held('startup') and service.reattach_required==true)
        local r=service.reattach_read;assert(r.armed==true and r.published==true and r.frame==4242)
        assert(service.reattach_verdict=='armed' and service.phase=='native_reattach_held')
        for _=1,5 do assert(service:step())end
        assert(not loop_built and physical==true and advances==0 and runtime_steps>=1)
        local s=service:status();assert(s.native_reattach.verdict=='armed' and s.native_reattach.required_before_first_frame==true)
    ''')


def test_an_early_reload_mid_routine_with_the_overlay_swapped_to_tiles_holds_before_the_first_frame(lua):
    """The service saved the armed word on the stack and put tiles in the overlay: a naive overlay
    check sees nothing, the stack does. Held at frame 10, before any free frame, however early."""
    lua.execute("frame=10;write_safe=false;overlay(TILES);stack_word()".replace("TILES", "{" + ",".join(map(str, TILES)) + "}"))
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json);assert(service.native_physical()=='mid_routine')
        assert(service:step())
        assert(physical==true and advances==0 and service.reattach_required==true and service.reattach_verdict=='mid_routine')
        for _=1,4 do assert(service:step())end;assert(not loop_built and physical and advances==0)
    ''')


def test_a_slow_cold_launch_free_runs_the_boot_however_late_the_script_starts(lua):
    """Script attached at frame 9000 of a cold boot: overlay in tile shape, no saved word on the
    stack, not yet write-safe. Boot frames free-run; the host is built at the first write-safe
    visible frame; the clean read plus the server lease and empty obligations release the loop."""
    lua.execute("frame=9000;write_safe=false;overlay(TILES)".replace("TILES", "{" + ",".join(map(str, TILES)) + "}"))
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json);assert(physical==true)                           -- claimed and held before the first frame
        assert(service.native_physical()=='clean')
        for _=1,3 do assert(service:step());assert(not physical and service.booting);emu.frameadvance()end  -- one clean boot frame at a time
        assert(service.runtime==nil and advances==3)
        write_safe=true;assert(service:step())                              -- begin under the hold, read clean, read published
        assert(physical==true and service.reattach_required==false and service.reattach_read.armed==false and service.reattach_verdict=='clean')
        assert(#observed==1 and observed[1].event=='native_reattach' and observed[1].payload.physical=='clean')
        assert(observed_baseline.native_reattach.verdict=='pending' and observed_baseline.native_reattach.read_digest==service.reattach_read_digest)
        assert(service:step());assert(not loop_built and physical)          -- no server verdict yet: still held
        local b=acknowledge('released','clean',string.rep('0',64))            -- a verdict for another read never releases
        assert(b.native_reattach.class=='verdict_mismatch' and service.reattach_server.verdict=='held')
        assert(service:step());assert(not loop_built and physical)
        b=acknowledge('released','clean')                                    -- the exact verdict on this digest
        assert(b.native_reattach.verdict=='released' and service.reattach_server.read_digest==service.reattach_read_digest)
        assert(service:step());assert(loop_built and not physical)          -- lease + nothing pending: free again
        assert(service:step());assert(not physical)
    ''')


@pytest.mark.parametrize("state", ["armed_lease", "complete_lease", "pending_native_command"])
def test_a_fresh_boot_with_an_open_lease_or_pending_native_command_stays_held(lua, state):
    lua.execute("overlay(TILES)".replace("TILES", "{" + ",".join(map(str, TILES)) + "}"))
    lua.execute({"armed_lease": "lease.phase='armed'", "complete_lease": "lease.phase='complete'",
                 "pending_native_command": "native_commands={{command_id='c',body={cmd='native_trade_commit'}}}"}[state])
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json);assert(service.native_physical()=='clean')
        write_safe=false;assert(service:step());assert(service.runtime==nil and not physical)   -- boot frame released
        write_safe=true;assert(service:step())
        assert(physical==true and service.phase=='native_reattach_held' or service.reattach_verdict=='clean')
        for _=1,4 do assert(service:step())end;assert(not loop_built and physical)
    ''')


def test_a_native_command_is_serviced_in_bounded_slices_under_the_native_vote_and_the_core_is_held_throughout(lua):
    lua.execute("overlay(TILES)".replace("TILES", "{" + ",".join(map(str, TILES)) + "}"))
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json)
        assert(service:step());acknowledge('released','clean');assert(service:step());assert(loop_built and not physical)
        native_commands={{command_id='c',body={cmd='native_trade_commit'}}}
        assert(service:step())                                   -- loop tick: writer pending -> arm at the boundary
        assert(physical==true and service.native_host.armed() and service.holds:held('native'))
        local before=frame
        for _=1,3 do assert(service:step())end                   -- held: bounded slices, one authorized frame each
        assert(native_steps==3 and frame==before+3 and #native_commands==0 and native_pumps>=3)
        assert(service:step())                                   -- complete: disarm, vote released
        assert(not physical and not service.native_host.armed() and service.native_host.failure()==nil)
        assert(service:step());assert(not physical)              -- free again
    ''')


def test_a_failed_native_step_latches_the_hold_and_the_loop_never_frees(lua):
    lua.execute("overlay(TILES)".replace("TILES", "{" + ",".join(map(str, TILES)) + "}"))
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json)
        assert(service:step());acknowledge('released','clean');assert(service:step());assert(loop_built)
        native_commands={{command_id='c',body={cmd='native_trade_commit'}}};stepper_authorize=false
        assert(service:step());assert(physical and service.native_host.armed())
        local ok=service:step()                                   -- the modeled service asserts its step; the host latched first
        assert(physical==true and service.native_host.failure()~=nil and service.phase=='failed')
        for _=1,3 do assert(service:step()==false)end
        assert(physical==true and advances==0 and service.holds:held('native') and service.holds:held('lifecycle'))
    ''')


@pytest.mark.parametrize("fault", ["held_service", "no_initial_observations", "other_variant", "other_rom"])
def test_native_manifest_is_refused_outside_the_free_service_client_or_for_another_cartridge(lua, fault):
    changes = {"held_service": {"mode": "held_service"}, "no_initial_observations": {"initial_observations": False},
               "other_variant": {"native_manifest": {**MANIFEST, "variant": "red"}},
               "other_rom": {"native_manifest": {**MANIFEST, "final_sha1": "f" * 40}}}[fault]
    lua.globals().launch_json = json.dumps(launch(**changes))
    with pytest.raises(LuaError, match="initial observation" if fault == "no_initial_observations" else "native launch requires"):
        lua.execute("start(launch_json)")


def test_a_failing_physical_read_before_begin_leaves_the_core_held(lua):
    """The host is claimed and held before the first frame; if the pre-frame read itself fails
    (here: the bus read raises), the entry fails with the hold in place and no frame runs."""
    lua.execute("frame=7;write_safe=false;overlay(TILES)".replace("TILES", "{" + ",".join(map(str, TILES)) + "}"))
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json);assert(physical==true)
        package.loaded['memory_gb'].read_u8=function()error('bus unavailable',0)end
        local ok,why=service:step();assert(ok==false and tostring(why):find('bus unavailable'))
        assert(physical==true and advances==0 and service.phase=='failed')
        assert(service:step()==false and physical==true)
    ''')


def test_a_cold_core_before_init_sets_the_stack_pointer_still_boots_one_clean_frame_at_a_time(lua):
    """Before home/init.asm `ld sp, wStack` the core reports SP=$FFFE; the section scan does not
    depend on SP, so a cold boot is clean and progresses under re-taken holds, never failing held."""
    lua.execute("frame=0;write_safe=false;sp=0xFFFE;overlay(TILES)".replace("TILES", "{" + ",".join(map(str, TILES)) + "}"))
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json);assert(physical==true and service.native_physical()=='clean')
        for _=1,4 do assert(service:step());assert(not physical and service.booting);emu.frameadvance()end
        assert(advances==4 and service.runtime==nil and service.phase~='failed')
        sp=0xDFF7;write_safe=true;assert(service:step());assert(physical and service.reattach_verdict=='clean')
    ''')


@pytest.mark.parametrize("fault", ["other_variant", "other_rom", "held_service"])
def test_a_native_launch_that_fails_validation_on_an_armed_core_leaves_it_held(lua, fault):
    """The actuator is claimed and held before launch validation can fail: a stale manifest, a
    changed ROM or the wrong mode on an APPLY-armed core exits with the hold in place."""
    lua.execute("frame=4242;write_safe=false;overlay(ARMED)".replace("ARMED", "{" + ",".join(map(str, ARMED)) + "}"))
    changes = {"other_variant": {"native_manifest": {**MANIFEST, "variant": "red"}},
               "other_rom": {"cartridge": {"variant": "yellow", "final_rom_sha1": "f" * 40}},
               "held_service": {"mode": "held_service"}}[fault]
    lua.globals().launch_json = json.dumps(launch(**changes))
    with pytest.raises(LuaError):
        lua.execute("start(launch_json)")
    lua.execute("assert(physical==true and advances==0);for _=1,3 do if not physical then emu.frameadvance()end end;assert(advances==0)")


def test_a_held_server_verdict_keeps_the_hold_and_the_published_read_digest_matches_the_server_digest(lua):
    lua.execute("overlay(TILES)".replace("TILES", "{" + ",".join(map(str, TILES)) + "}"))
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json);assert(service:step())
        assert(service.reattach_verdict=='clean' and #observed==1)
        acknowledge('held','pending_native_command')
        for _=1,3 do assert(service:step())end
        assert(not loop_built and physical and service.reattach_server.class=='pending_native_command' and service.phase~='failed')
        published=JSON.encode(observed[1].payload.read);read_digest=service.reattach_read_digest
    ''')
    from server.protocol import digest
    assert digest(json.loads(lua.globals().published)) == lua.globals().read_digest   # the server can match the client's digest exactly
    assert lua.globals().read_digest == lua.eval("service:status().native_reattach.read_digest")


def test_a_native_revoke_drops_the_remembered_verdict_at_once_and_holds_until_a_fresh_read_is_released(lua):
    """Invariant, not step order: hard_revoke (the runtime's on_revoke) clears reattach_server in the same
    call it takes the lifecycle hold, so loop_ready can never consult a pre-revoke release across a new
    admission; the loop frees again only after the republished read gets its own released verdict."""
    lua.execute("overlay(TILES)".replace("TILES", "{" + ",".join(map(str, TILES)) + "}"))
    lua.globals().launch_json = json.dumps(launch())
    lua.execute(r'''
        start(launch_json);assert(service:step())
        acknowledge('released','clean');assert(service:step());assert(loop_built and not physical)
        -- Revoke before any rebind: no releasable verdict survives the call itself, the lifecycle hold is on.
        assert(runtime_options.on_revoke('re-admission'))
        assert(service.reattach_server==nil and service.reattach_republish==true and service.holds:held('lifecycle'))
        -- The next step republishes under the hold (a new read, still pending) and stays held ...
        assert(service:step());assert(#observed==2 and observed[2].event=='native_reattach' and physical)
        assert(service.reattach_server==nil and service.reattach_republish==false)
        for _=1,3 do assert(service:step());assert(physical)end
        -- ... until the fresh read's own verdict arrives.
        local b=acknowledge('released','clean');assert(b.native_reattach.verdict=='released')
        assert(service.reattach_server.read_digest==service.reattach_read_digest)
    ''')
