"""Actual entry/runtime/router/journals; deterministic platform and transport only.

Modeled memory is source-shaped, not an emulator or vanilla-animation qualification.
The connector deliberately withholds replies; routing calls are inspected at the
real entry's runtime boundary, while journal publication/ACK uses actual modules.
"""

import hashlib
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from server.gen1_initial_save import wire_payload
from tests.unit.test_gen1_initial_observation import source
from tests.unit.test_gen1_memorial import fixture

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def entry():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.globals().sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    lua.globals().initial_json = json.dumps(source("yellow"))
    lua.globals().party_json = json.dumps(fixture("yellow", count=2)[0])
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');Canonical=require('journal_document')
        print=function()end;console={log=function()end}
        bus={};rom={};cart={};writes=0;frame=100;now=1;pc=0x40;sp=0xDFF0
        function bytes(domain)return domain=='ROM'and rom or domain=='CartRAM'and cart or bus end
        memory={getmemorydomainlist=function()return {'ROM','System Bus','CartRAM'}end,
            read_u8=function(a,d)return bytes(d)[a]or 0 end,
            write_u8=function(a,v,d)writes=writes+1;bytes(d)[a]=v end,
            read_u16_le=function(a,d)return (bytes(d)[a]or 0)+256*(bytes(d)[a+1]or 0)end,
            write_u16_le=function(a,v,d)writes=writes+1;bytes(d)[a]=v%256;bytes(d)[a+1]=math.floor(v/256)end}
        emu={framecount=function()return frame end,getregister=function(n)return n=='PC'and pc or sp end}
        gameinfo={getromhash=function()return string.rep('f',40)end}
        nonce_count=0;clock_created=0;host_created=0;runtime_created=0;hooks={};removed=0
        function nonce()nonce_count=nonce_count+1;return string.format('12345678%024x',nonce_count)end
        event={on_bus_exec=function(fn,a,name)assert(not hooks[name]);hooks[name]={fn=fn,address=a};return name end,
            onloadstate=function(fn,name)assert(not hooks[name]);hooks[name]={fn=fn};return name end,
            onexit=function(fn,name)assert(not hooks[name]);hooks[name]={fn=fn};return name end,
            unregisterbyid=function(id)assert(hooks[id]);hooks[id]=nil;removed=removed+1 end}
        package.loaded.platform_identity={new_nonce=nonce}
        package.loaded.platform_clock={new=function()clock_created=clock_created+1;return function()return now end end}
        package.loaded.platform_execution={supported_profile=function()return {}end}
        package.loaded.platform_bounded_execution={new=function(options)
            host_created=host_created+1;assert(host_created==1);host_options=options
            host_state={host={owner_id=options.owner_id,capability_id='fixture',process_id=1,
                physical_stop_verified=true,held=true,host_blocked=true,lease_owned=true,user_paused=false,failed=false,closed=false},
                frame_rate={numerator=60,denominator=1},single_frame_only=true,frame_callbacks_suppressed=true,
                load_state_invalidation=true,owner_exit_invalidation=true,steps=0,expected_frame=100}
            return {status=function()return host_state end,set_held=function(value)assert(value);return true end,
                yield_held=function()return true end,step_one=function(scope)
                    assert(options.authorize(scope,{frame=frame}),'unpermitted bounded step')
                    frame=frame+1;host_state.steps=host_state.steps+1;host_state.expected_frame=frame;return true end}
        end}
        disks={};opened={};closed={}
        package.loaded.platform_storage={new=function(path)
            assert(not opened[path],'duplicate journal lease');opened[path]=1
            return {sha256=function(text)return sha(text)end,read=function()return disks[path],not disks[path]and 'missing'or nil end,
                replace=function(text)disks[path]=text;return true end,close=function()closed[path]=true end}
        end}
        saveram_options={}
        package.loaded.platform_saveram={new=function(options)
            saveram_options[#saveram_options+1]=options
            return {prepare=function()return true end,flush=function()error('no modeled file receipt')end}
        end}
        luanet={load_assembly=function()end,import_type=function(name)
            assert(name=='System.IO.Path');return {GetFullPath=function(p)return p end,
                GetDirectoryName=function(p)return p:match('^(.*)/[^/]+$')end}
        end}
        sent={};connected=false
        transport={init=function()connected=true end,connected=function()return connected end,pump=function()end,
            send=function(raw)sent[#sent+1]=JSON.decode(raw);return true end,receive=function()return nil end,
            disconnect=function()connected=false end,queue_status=function()return {
                send_lines=0,send_bytes=0,send_offset=0,receive_lines=0,receive_bytes=0,
                partial_receive_bytes=0,pending_receive_bytes=0,ready_receive_bytes=0}end}
        package.loaded.connector=transport
        function put(a,hex,d)for i=1,#hex,2 do bytes(d)[a+(i-1)/2]=tonumber(hex:sub(i,i+1),16)end end
        function anchors(value)
            if type(value)~='table'then return end
            if value.rom_offset and value.expected_hex then put(value.rom_offset,value.expected_hex,'ROM')end
            if value.record_rom_offset and value.record_hex then put(value.record_rom_offset,value.record_hex,'ROM')end
            for _,child in pairs(value)do if type(child)=='table'then anchors(child)end end
        end
        for _,name in ipairs({'gen1_bootstrap_sites','gen1_capture_sites','gen1_grant_sites',
            'gen1_static_sites','gen1_npc_exchange_sites','gen1_engine_signal_data','gen1_evolution_sites',
            'gen1_wild_encounter_sites','gen1_identity_sites'})do
            anchors(require(name).titles.yellow)
        end
        local names=require('gen1_identity_sites').titles.yellow
        for _,name in pairs(names.names)do put(names.sites.borrow_begin.bank*0x4000+name.address-0x4000,name.hex,'ROM')end
        mem=require('memory_gb');mem.initProfile(require('games.gen1_rby'),'yellow')
        function load_point(text)
            local point=JSON.decode(text);local layout=require('gen1_full_save_layout').yellow
            for name,r in pairs(layout.regions)do put(r.address,point.fields[name])end
            put(0,point.cart_hex,'CartRAM');bus[layout.status]=point.save_status
        end
        function overworld()
            local p=mem.profile.write_safe;pc=p.irq_vector
            local function instruction(a,op,target)put(a,string.format('%02X%02X%02X',op,target%256,math.floor(target/256)),'ROM')end
            instruction(p.irq_vector,0xC3,p.vblank_entry)
            put(p.delay_frame,string.format('3E01E0%02X76F0%02XA7',p.vblank_flag%256,p.vblank_flag%256),'ROM')
            instruction(p.overworld_loop,0xCD,p.delay_frame);instruction(p.overworld_loop_less_delay,0xCD,p.delay_frame)
            bus[mem.profile.BATTLE_FLAG_ADDR]=0;bus[mem.profile.JOY_IGNORE_ADDR]=0;bus[mem.profile.FONT_LOADED_ADDR]=0
            bus[p.link_state]=p.link_none;bus[p.serial_status]=p.disconnected_serial;bus[p.entering_cable_club]=0
            if p.printer_open then bus[p.printer_open]=0 end
            bus[sp]=(p.delay_frame+5)%256;bus[sp+1]=math.floor((p.delay_frame+5)/256)
            bus[sp+2]=(p.overworld_loop+3)%256;bus[sp+3]=math.floor((p.overworld_loop+3)/256)
            bus[p.vblank_flag]=1;bus[0xFF47]=0xE4
            assert(mem.isPartyWriteSafe())
        end
        load_point(initial_json);overworld()
        manifest=JSON.decode(JSON.encode(require('gen1_companion_profiles').profiles.yellow.manifest));manifest.final_sha1=string.rep('f',40)
        cartridge={variant='yellow',final_rom_sha1=manifest.final_sha1,content_profile_schema='gen1-rby-scanned-companion-content-v1',
            content_profile_hash=string.rep('e',64),patch_version=3,party_codec='gen1-rby-party-v1',capabilities={panel=false,sfx=false,pc_trade=true}}
        -- Instrument constructors without replacing their behavior.
        local Runtime=require('gen1_runtime');local construct=Runtime.new
        Runtime.new=function(options)runtime_created=runtime_created+1;runtime_options=options;return construct(options)end
        launch={schema='slink-gen1-launch-v1',protocol='slink-gen1-durable-v1',mode='held_service',run_id=string.rep('a',32),
            player='a',host='fixture',port=1234,cartridge=cartridge,initial_observations=true,ordinary_frames=true,native_manifest=manifest}
        service=require('gen1_client_entry').start(launch,{root=root,storage_root='fixture',saveram_directory='fixture/SaveRAM'})
        assert(service:step());assert(service.runtime)
        journal=service.native.journal;operations=runtime_options.operation_execution
        context=runtime_options.read_context()
        binding={binding_digest=string.rep('b',64),context_generation=context.context_generation,
            session_id=string.rep('c',32),admission_epoch=string.rep('d',32)}
        control={admitted=true,held=true}
        function acknowledge()
            local event=assert(journal:pending_events()[1]);assert(journal:accept_response(event.operation_id,JSON.array()));return event
        end
        function enroll()
            service.runtime:revoke('modeled manual server boundary')
            assert(service.observer:step(true));acknowledge()
            local data=service.store:read();data.observation.bootstrap={phase='acknowledged'};assert(service.store:commit(data))
            service.observer:step(true)
        end
        function grant(count)
            local request=assert(operations.request(binding,control));local packet={schema=request.window.schema,
                challenge=request.window.challenge,scope=request.window.scope,frames=count or 2,ttl_ms=1000,
                proof_digest=sha(Canonical.encode(request.evidence))}
            assert(operations.accept(JSON.object(packet),binding));return request,packet
        end
        function tick()now=now+.02;return service.frames:step(true)end
        function queue(body)
            local op=assert(journal:append({event='sync'}));id=nonce()
            assert(journal:accept_response(op,JSON.array({{command_id=id,command_sequence=1,body={cmd=body.cmd,body=body}}})))
            return {command_id=id,command_sequence=1}
        end
        function party()
            local initial=JSON.decode(initial_json);load_point(party_json)
            put(mem.PLAYER_NAME_ADDR,initial.fields.name);bus[mem.PLAYER_ID_ADDR]=0;bus[mem.PLAYER_ID_ADDR+1]=0
            overworld()
        end
        function query()
            pc=0x40;bus[manifest.ram.hLoadedROMBank]=manifest.receptionist.entry.bank
            local caller=manifest.receptionist.query_return;bus[sp+2]=caller%256;bus[sp+3]=math.floor(caller/256)
            put(manifest.foreground.overlay,'534C5431010101000000000000000000')
            assert(not mem.isPartyWriteSafe());assert(require('gen1_receptionist_client').query(mem,manifest))
        end
        function prepare_native()
            party();enroll();grant(1);assert(tick());acknowledge()
            query();operations.request(binding,control);assert(operations.accept(nil,binding))
            local before=writes;service.native:pump_native();assert(writes==before)
            local event=acknowledge();assert(event.payload.event=='receptionist_entered')
            native_body={cmd='native_receptionist',player='a',eligible_mask=1,payload=event.payload.payload}
            identity=queue(native_body)
            operations.request(binding,control);assert(operations.accept(nil,binding))
            intent=runtime_options.executor_adapter.prepare(native_body,identity)
            assert(journal:prepare_command(id,intent))
            local request=grant(3);assert(request.evidence.schema=='rby-native-window-evidence-v1')
            assert(request.evidence.accounting==JSON.null)
            assert(operations.authorize_apply(native_body,intent,identity,control))
            runtime_options.executor_adapter.apply(native_body,intent,identity)
            return request
        end
        function finish_native()
            service.native:after_service();assert(service.native:step_native())
            hooks['slink-receptionist-runtime-a-after_query'].fn()
            now=now+.02;service.native:after_service();assert(service.native:step_native())
            hooks['slink-receptionist-runtime-a-menus_restored'].fn();overworld()
            local phase,observed=runtime_options.executor_adapter.classify(native_body,intent,identity)
            assert(phase=='after')
            local receipt=runtime_options.executor_adapter.receipt(native_body,intent,observed,identity)
            assert(journal:complete_command(id,'ACK',receipt));acknowledge();service.native:after_service()
        end
    """)
    return lua


def test_real_entry_constructs_one_host_clock_runtime_and_shared_journal(entry):
    entry.execute("""
        assert(host_created==1 and clock_created==1 and runtime_created==1)
        assert(service.native.host==service.bounded and service.native.journal==runtime_options.journal)
        assert(service.native.command_store==service.store and service.clock==runtime_options.clock)
        assert(service.runtime:status({summary=true}).request.kind=='hello')
        assert(#sent==1 and sent[1].event=='hello' and writes==0)
    """)


def test_real_ordinary_range_closes_before_the_entry_routes_held_commands(entry):
    entry.execute("""
        enroll();local request=grant(2);assert(request.window.scope.phase=='ordinary')
        assert(tick());assert(tick());assert(frame==102)
        assert(service.frames:blocks_commands())
        assert(operations.authorize_apply({cmd='initial_save'}, {}, {}, control)==false)
        acknowledge();assert(not service.frames:blocks_commands())
        local next_request=grant(1);assert(next_request.evidence.sequence==2)
    """)


def test_close_unregisters_hooks_closes_all_stores_and_preserves_owned_hold(entry):
    entry.execute("""
        enroll();service:close();assert(next(hooks)==nil and removed>0)
        for path in pairs(opened)do assert(closed[path],path)end
        assert(host_state.host.held and host_state.host.physical_stop_verified)
    """)


def test_initial_save_uses_held_permit_and_rejects_native_frame_credit(entry):
    entry.execute("before=require('gen1_full_save').capture(mem,'yellow')")
    before = json.loads(entry.eval("JSON.encode(before)"))
    after = {
        **before,
        "cart_hex": entry.eval("require('gen1_full_save').image(mem,before)"),
        "save_status": 2,
    }
    payload = wire_payload(
        {
            "schema": "rby-initial-save-prepared-v1",
            "before": before,
            "after": after,
            "context_generation": entry.globals().context["context_generation"],
            "final_sha1": "f" * 40,
            "frame": 100,
        }
    )
    entry.globals().payload_json = json.dumps(payload)
    entry.execute("""
        service.runtime:revoke('manual modeled server boundary')
        local body={cmd='initial_save',payload=JSON.decode(payload_json)};local who=queue(body)
        operations.request(binding,control);assert(operations.accept(nil,binding))
        assert(runtime_options.operation_ready(body,nil,control))
        local intent=runtime_options.executor_adapter.prepare(body,who);assert(journal:prepare_command(id,intent))
        local request=assert(operations.request(binding,control))
        assert(request.evidence.schema=='rby-held-initial-save-evidence-v1'and request.window.scope.phase=='initial_save')
        assert(request.evidence.accounting==nil and saveram_options[1].directory=='fixture/SaveRAM')
        local packet={schema='slink-operation-execution-window-v1',challenge=request.window.challenge,
            scope=request.window.scope,frames=3,ttl_ms=1000,proof_digest=sha(Canonical.encode(request.evidence))}
        assert(operations.accept(JSON.object(packet),binding)==false)
        assert(operations.authorize_apply(body,intent,who,control)==false and writes==0)
    """)


def test_native_loan_typed_return_handoff_and_ordinary_reentry_share_the_real_owner(entry):
    entry.execute("""
        prepare_native();assert(service.frames:status().native_borrowed)
        assert(operations.authorize_apply({cmd='initial_save'}, {}, {}, control)==false)
        finish_native();assert(frame==103 and service.frames:status().native_borrowed)
        assert(service.frames:request(binding,control)==nil)
        local n=service.runtime:status({summary=true}).pending_events
        service.native:pump_native();assert(service.runtime:status({summary=true}).pending_events==n+1)
        assert(acknowledge().payload.event=='native_frame_return')
        local request=assert(operations.request(binding,control));assert(request.window.schema=='rby-native-handoff-query-v1')
        local response=request.evidence;response.ready=true;assert(operations.accept(response,binding))
        service.native:pump_native();assert(acknowledge().payload.event=='native_frame_handoff')
        assert(not service.frames:status().native_borrowed)
        assert(service.frames:status().frame==103)
        local progress=service.frame_store:read().progress
        assert(progress.acquisition_source.frame==103 and progress.inventory_frame==103)
        local ordinary=grant(1);assert(ordinary.window.scope.phase=='ordinary'and ordinary.evidence.boundary.frame==103)
        assert(tick()and frame==104)
        assert(host_created==1 and runtime_created==1 and clock_created==1)
    """)


def test_native_receptionist_offer_updates_outer_runtime_publication_fairness(entry):
    entry.execute("""
        prepare_native()
        local overlay=manifest.foreground.overlay;local caller=manifest.receptionist.offer_return
        bus[sp+2]=caller%256;bus[sp+3]=math.floor(caller/256)
        bus[overlay+5]=2;bus[overlay+6]=2;bus[overlay+8]=255;bus[overlay+9]=0
        local count=service.runtime:status({summary=true}).pending_events
        service.native:pump_native()
        local pending=journal:pending_events();assert(#pending==1 and pending[1].payload.event=='trade_offer')
        assert(service.runtime:status({summary=true}).pending_events==count+1,
            'native offer bypassed the shared runtime event counter')
    """)


def test_entry_routes_native_renewal_at_actual_response_boundary_without_ordinary_adoption(entry):
    entry.execute("""
        prepare_native();service.native:after_service();assert(service.native:step_native())
        local request=assert(operations.request(binding,control))
        assert(request.evidence.host.frame==102 and request.evidence.accounting.host.frame==101)
        now=now+.02;service.native:after_service();assert(service.native:step_native())
        local packet={schema=request.window.schema,scope=request.window.scope,challenge=request.window.challenge,
            frames=2,ttl_ms=1000,proof_digest=sha(Canonical.encode(request.evidence))}
        assert(operations.accept(JSON.object(packet),binding))
        local data=service.store:read()
        assert(data.observation.native_frame_accounting.acceptance.host.frame==103)
        assert(data.observation.frame_progress.frame==101 and service.frames:status().native_borrowed)
        assert(service.frames:request(binding,control)==nil)
        assert(not host_options.authorize({phase='ordinary'},{frame=103}))
    """)
