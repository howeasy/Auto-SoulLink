"""Real native service/adapters and journal, modeled platform ownership and TCP.

These tests qualify composition and permission routing, not cartridge animation.
The existing live native-runtime gates remain the engine proof.
"""

import hashlib
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lua():
    value = LuaRuntime(unpack_returned_tuples=True)
    value.globals().root = ROOT.as_posix()
    value.globals().sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    value.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');Canonical=require('journal_document')
        nonce_count=0;clock_created=0;host_created=0;runtime_created=0;pumps=0;steps=0;now=1
        function nonce()nonce_count=nonce_count+1;return string.format('%032x',nonce_count)end
        package.loaded.platform_identity={new_nonce=nonce}
        package.loaded.platform_clock={new=function()clock_created=clock_created+1;return function()return now end end}
        context={context_generation=string.rep('c',32),physical_instance=string.rep('d',32),
            save_identity={ot_id='1234',trainer_name='RED'}}
        memory={read_u8=function()return 0 end,write_u8=function()error('no cartridge writes in composition test')end}
        gameinfo={getromhash=function()return string.rep('f',40)end}
        emu={framecount=function()return 100+steps end,getregister=function()return 0 end}
        hooks=0;unregistered=0
        local function hook()hooks=hooks+1;return 'hook-'..hooks end
        event={on_bus_exec=hook,onloadstate=hook,onexit=hook,unregisterbyid=function()unregistered=unregistered+1 end}
        mem={readPlayerId=function()return 0x1234 end,readPlayerName=function()return 'RED'end,
            isPartyWriteSafe=function()return true end,bytesToHex=function()return ''end}
        host_state={host={owner_id=context.physical_instance,physical_stop_verified=true,
            capability_id='fixture',process_id=1,held=true,host_blocked=true,lease_owned=true,user_paused=false},
            frame_rate={numerator=60,denominator=1},single_frame_only=true,frame_callbacks_suppressed=true,
            load_state_invalidation=true,owner_exit_invalidation=true,steps=0,expected_frame=100}
        arms=0;yields=0;disarms=0;is_armed=false
        shared_host={status=function()return host_state end,
            armed=function()return is_armed end,failure=function()return host_failure end,
            arm=function()arms=arms+1;is_armed=true;return true end,
            yield_held=function()yields=yields+1;return true end,
            disarm=function()assert(not host_failure);disarms=disarms+1;is_armed=false;return true end,
            step_one=function(scope)
                if step_failure then host_failure='modeled step failure';return false,host_failure end
                assert(native.authorize_step(scope));steps=steps+1;host_state.steps=steps;host_state.expected_frame=100+steps;return true
            end}
        package.loaded.platform_execution={supported_profile=function()return {}end}
        package.loaded.platform_bounded_execution={new=function(options)
            host_created=host_created+1;host_authorize=options.authorize
            host_state.host.owner_id=options.owner_id;return shared_host
        end}
        disks={};opened={};closed={}
        package.loaded.platform_storage={new=function(path)
            assert(not opened[path] or closed[path],'duplicate platform journal lease')
            opened[path]=(opened[path]or 0)+1;closed[path]=false
            return {sha256=function(text)return sha(text)end,read=function()if disks[path]then return disks[path]end;return nil,'missing'end,
                replace=function(text)disks[path]=text;return true end,close=function()closed[path]=true end}
        end}
        package.loaded.connector={pump=function()pumps=pumps+1 end}
        local Runtime=require('gen1_runtime')
        Runtime.new=function(options)
            runtime_created=runtime_created+1;runtime_options=options
            return {step=function()return true end,status=function()return {fixture=true}end,
                revoke=function()runtime_revoked=true end}
        end
        Service=require('gen1_native_runtime')
        manifest=assert(JSON.decode(JSON.encode(require('gen1_companion_profiles').profiles.yellow.manifest)))
        manifest.final_sha1=string.rep('f',40)
        Store=require('state_store');Journal=require('client_journal')
        Storage=require('platform_storage')
        shared_store=assert(Store.open(Storage.new('owner/journal.json'),{fixture=true},Journal.initial()))
        journal=assert(Journal.open(shared_store,nil,Service.journal_options((require('gen1_initial_observation')))))
        options={embedded=true,memory=mem,manifest=manifest,variant='yellow',player='a',run_id=string.rep('a',32),
            storage_directory='owner/native',context=context,read_context=function()return context end,
            clock=function()return now end,host=shared_host,journal=journal,
            read_runtime_status=function()return outer_status or {}end,
            observe=function(events,baseline)return journal:append_many(events,baseline)end}
        function construct()native=Service.new(options);return native end
        function command(kind)
            local origin=assert(journal:append({event='fixture'}));id=string.rep('e',32)
            local body={cmd=kind,player='a',transaction_id=string.rep('a',32)}
            assert(journal:accept_response(origin,JSON.array({{command_id=id,command_sequence=1,body={cmd=kind,body=body}}})))
            assert(journal:prepare_command(id,{schema='explicit-window-fixture'}))
            return body
        end
        function arm()
            body=command('native_trade_commit')
            native.native.frames_pending=function()return true end
            native.native.window_evidence=function()return {schema='explicit-native-window-fixture'}end
            native:after_service()
            local request=assert(native.operations.request({binding_digest=string.rep('b',64)},{admitted=true,held=true}))
            local packet={schema='slink-operation-execution-window-v1',challenge=request.window.challenge,
                scope=request.window.scope,frames=3,ttl_ms=1000,proof_digest=sha(assert(Canonical.encode(request.evidence)))}
            assert(native.operations.accept(JSON.object(packet)));return request.window.scope
        end
        function set_phase(kind,phase)
            local store=assert(native[kind..'_store']);local state=assert(store:read())
            state.phase=phase;assert(store:commit(state))
        end
        function shared_pump()pumps=pumps+1;return true end
    """)
    return value


def test_embedded_constructor_reuses_owner_clock_context_and_journal_without_transport(lua):
    lua.execute("construct()")
    g = lua.globals()
    assert g.host_created == g.runtime_created == g.clock_created == g.nonce_count == 0
    assert lua.eval(
        "native.host==shared_host and native.journal==journal and native.command_store==shared_store"
    )
    assert g.opened["owner/journal.json"] == 1
    assert g.opened["owner/native/journal.json"] is None
    assert all(
        g.opened[f"owner/native/{name}.json"] == 1 for name in ("native", "prompt", "preparation")
    )
    assert g.native.step(g.native)[0] is False and g.pumps == g.steps == 0
    assert g.native.frame_scope() is None
    assert g.native.handles(lua.table_from({"cmd": "native_trade_commit"}))
    assert not g.native.handles(lua.table_from({"cmd": "force_faint"}))
    lua.execute(
        "native.update_control({binding_digest=string.rep('b',64)},{admitted=true,held=true})"
    )
    assert g.native.binding["binding_digest"] == "b" * 64
    assert g.native.current is None and g.native.frame_scope() is None


@pytest.mark.parametrize(
    "field", ["context", "read_context", "clock", "host", "journal", "read_runtime_status"]
)
def test_missing_injection_dependency_refuses_before_acquiring_any_second_owner(lua, field):
    lua.globals().options[field] = None
    with pytest.raises(LuaError, match="existing owner"):
        lua.globals().construct()
    assert lua.globals().host_created == lua.globals().runtime_created == 0
    assert lua.globals().opened["owner/native/native.json"] is None


def test_standalone_uses_the_exported_callbacks_and_owns_its_command_store(lua):
    lua.execute(
        "options.embedded=false;options.host=nil;options.journal=nil;options.read_runtime_status=nil;construct()"
    )
    g = lua.globals()
    assert g.host_created == g.runtime_created == 1
    assert lua.eval(
        "host_authorize==native.authorize_step and runtime_options.operation_execution==native.operations and runtime_options.executor_adapter==native.executor_adapter and runtime_options.operation_ready==native.ready"
    )
    assert g.opened["owner/native/journal.json"] == 1
    assert g.native.step(g.native) is True and g.pumps == 1 and g.steps == 0
    g.native.close(g.native)
    assert g.runtime_revoked and g.closed["owner/native/journal.json"]
    assert not g.closed["owner/journal.json"]


def test_embedded_close_never_revokes_outer_runtime_or_closes_shared_journal(lua):
    lua.execute("construct();native:close()")
    g = lua.globals()
    assert g.runtime_revoked is None and not g.closed["owner/journal.json"]
    assert all(
        g.closed[f"owner/native/{name}.json"] for name in ("native", "prompt", "preparation")
    )
    assert lua.execute("return journal:append({event='owner-still-open'})")


def test_shared_owner_consumes_only_live_native_scope_and_preserves_rate_pause_and_budget(lua):
    lua.execute("construct();scope=arm()")
    g = lua.globals()
    assert g.native.step_native(g.native) is True and g.steps == 1
    assert g.native.step_native(g.native) is False and g.steps == 1  # No unbounded catch-up.
    lua.execute("now=1.02;host_state.host.user_paused=true")
    assert g.native.step_native(g.native) is False
    lua.execute("host_state.host.user_paused=false")
    assert g.native.step_native(g.native) is True and g.steps == 2
    lua.execute("now=1.04")
    assert g.native.step_native(g.native) is True and g.steps == 3
    lua.execute("now=1.06")
    assert g.native.step_native(g.native) is False and g.steps == 3


def test_embedded_window_waits_for_the_native_vote_before_requesting_control(lua):
    """A command delivered during an ordinary tick cannot send unbounded evidence."""
    lua.execute("""
        construct();body=command('native_trade_commit')
        native.native.frames_pending=function()return true end
        native.native.window_evidence=function()return {schema='explicit-native-window-fixture'}end
        native:after_service()
        host_state.host.held=false;host_state.host.host_blocked=false
        host_state.single_frame_only=false;host_state.frame_callbacks_suppressed=false
        host_state.load_state_invalidation=false;host_state.owner_exit_invalidation=false
        early=native.operations.request({binding_digest=string.rep('b',64)},{admitted=true,held=false})
    """)
    assert lua.globals().early is None
    assert lua.globals().native.pending_request is None
    lua.execute("""
        host_state.host.held=true;host_state.host.host_blocked=true
        host_state.single_frame_only=true;host_state.frame_callbacks_suppressed=true
        host_state.load_state_invalidation=true;host_state.owner_exit_invalidation=true
        ready=native.operations.request({binding_digest=string.rep('b',64)},{admitted=true,held=true})
    """)
    assert lua.globals().ready["evidence"]["host"]["held"] is True
    assert lua.globals().ready["evidence"]["host"]["bounded"] is True


@pytest.mark.parametrize("fault", ["scope", "stale_service", "expired", "context", "revoked"])
def test_external_owner_cannot_spend_a_changed_stale_or_revoked_native_authority(lua, fault):
    lua.execute("construct();scope=arm()")
    if fault == "scope":
        lua.execute("scope.operation_id=string.rep('a',32)")
    elif fault == "stale_service":
        lua.execute("now=1.3")
    elif fault == "expired":
        lua.execute("now=2.1;native:after_service()")
    elif fault == "context":
        lua.execute("context.context_generation=string.rep('a',32)")
        with pytest.raises(LuaError, match="context changed"):
            lua.execute("return native.authorize_step(scope)")
        assert lua.globals().steps == 0
        return
    else:
        lua.execute("native.operations.revoke('outer connection lost')")
    assert lua.execute("return native.authorize_step(scope)") is False
    assert lua.globals().steps == 0


def test_composed_journal_retains_ordinary_observation_and_native_typed_completion(lua):
    lua.execute("""
        local event={event='initial_observation',payload={schema='explicit-observation-fixture'}}
        local baseline=shared_store:read().observation
        baseline.initial_inventory={payload=event,phase='queued'}
        local operation=assert(journal:append(event,baseline));assert(journal:accept_response(operation,JSON.array()))
        assert(shared_store:read().observation.initial_inventory.phase=='acknowledged')
        command('native_trade_abort')
        assert(journal:complete_command(id,'ACK',{schema='explicit-native-abort-receipt'}))
    """)
    assert lua.execute("return journal:pending_events()[1].payload.event") == "trade_ack"


def test_ambiguous_observation_projection_refuses_without_committing(lua):
    lua.execute("""
        local callbacks=Service.journal_options({completion_event=function(entry,outcome,receipt)
            return {event='another-claim',command_id=entry.command_id,command_sequence=entry.command_sequence,receipt=receipt}
        end})
        journal=assert(Journal.open(shared_store,nil,callbacks));command('native_trade_abort')
        before=disks['owner/journal.json']
        completed,reason=journal:complete_command(id,'ACK',{schema='explicit-native-abort-receipt'})
    """)
    assert lua.globals().completed is False
    assert "multiple journal projections" in lua.globals().reason
    assert lua.globals().disks["owner/journal.json"] == lua.globals().before


def test_embedded_lifecycle_releases_idle_owner_after_exactly_one_shared_pump(lua):
    lua.execute("construct();assert(not native:pending());native:hold();native:hold();native:service_slice(shared_pump)")
    g = lua.globals()
    assert g.arms == g.pumps == g.disarms == 1
    assert g.steps == g.yields == 0 and not g.is_armed
    assert g.native.metrics.services == 1 and g.native.last_service == g.now
    assert g.host_created == g.runtime_created == g.clock_created == 0


@pytest.mark.parametrize("method", ["pending", "hold", "service_slice"])
def test_embedded_lifecycle_methods_refuse_standalone_use(lua, method):
    lua.execute("options.embedded=false;options.host=nil;options.journal=nil;construct()")
    with pytest.raises(LuaError, match="embedded"):
        lua.execute(f"native:{method}(shared_pump)")
    assert lua.globals().pumps == lua.globals().arms == lua.globals().disarms == 0


@pytest.mark.parametrize("kind,phase,terminal", [
    ("native", "armed", "released"), ("native", "complete", "released"), ("native", "releasing", "released"),
    ("prompt", "complete", "closed"), ("prompt", "closing", "closed"),
    ("receptionist", "active", "complete"), ("receptionist", "unknown", "complete"),
])
def test_embedded_lifecycle_holds_after_command_ack_and_prune_until_local_lease_terminal(lua, kind, phase, terminal):
    lua.globals().lease_kind = kind
    lua.globals().lease_phase = phase
    lua.globals().terminal_phase = terminal
    lua.execute("""
        options.receptionist=true;construct();command('native_trade_abort');set_phase(lease_kind,lease_phase)
        assert(journal:complete_command(id,'ACK',{schema='explicit-native-abort-receipt'}))
        assert(native:pending());native:hold()
        native:service_slice(function()
            pumps=pumps+1
            assert(journal:accept_response(journal:pending_events()[1].operation_id,JSON.array()))
            assert(#shared_store:read().inbox==0 and #journal:pending_commands()==0)
            return true
        end)
    """)
    g = lua.globals()
    assert g.is_armed and g.disarms == g.steps == 0 and g.yields == g.pumps == 1
    lua.execute("set_phase(lease_kind,terminal_phase);assert(not native:pending());native:service_slice(shared_pump)")
    assert not g.is_armed and g.disarms == 1 and g.pumps == 2


@pytest.mark.parametrize("kind", ["native", "prompt", "receptionist"])
def test_embedded_lifecycle_unreadable_lease_holds_without_frames(lua, kind):
    lua.globals().lease_kind = kind
    lua.execute("options.receptionist=true;construct();native[lease_kind..'_store']:close();assert(native:pending());native:hold()")
    if kind == "receptionist":
        # The existing native pump itself reads this store before the shared pump.
        with pytest.raises(LuaError):
            lua.execute("native:service_slice(shared_pump)")
    else:
        lua.execute("native:service_slice(shared_pump)")
    g = lua.globals()
    assert g.is_armed and g.disarms == g.steps == 0
    assert g.yields == g.pumps == (0 if kind == "receptionist" else 1)


def test_embedded_lifecycle_failed_host_short_circuits_and_never_rearms(lua):
    lua.execute("construct();host_failure='latched';shared_store:close();assert(native:pending());native:hold()")
    g = lua.globals()
    assert g.arms == g.disarms == g.pumps == g.steps == 0


def test_embedded_lifecycle_selects_only_oldest_journal_command(lua):
    lua.execute("""
        construct();command('force_faint')
        local origin=assert(journal:append({event='fixture'}))
        assert(journal:accept_response(origin,JSON.array({{command_id=string.rep('f',32),command_sequence=2,
            body={cmd='native_trade_abort',body={cmd='native_trade_abort',player='a'}}}})))
        assert(not native:pending())
        assert(journal:complete_command(id,'ACK',{schema='ordinary-fixture'}))
        assert(native:pending())
        native:hold();native:service_slice(shared_pump)
    """)
    g = lua.globals()
    assert g.is_armed and g.yields == 1 and g.disarms == g.steps == 0


def test_embedded_lifecycle_detects_receptionist_query_from_modeled_memory(lua):
    lua.execute("""
        construct();assert(not native:pending())
        local ram=manifest.ram;local ui=manifest.receptionist;local overlay=manifest.foreground.overlay
        local bytes={0x53,0x4c,0x54,0x31,1,1,2,0,0,0,0,0,0,0,0,0}
        emu.getregister=function(name)return name=='PC' and 0x40 or 0xc100 end
        memory.read_u8=function(address)
            if address==ram.hLoadedROMBank then return ui.entry.bank end
            if address==0xc102 then return ui.query_return%256 end
            if address==0xc103 then return math.floor(ui.query_return/256) end
            return bytes[address-overlay+1] or 0
        end
        mem.bytesToHex=function(values)local out={};for _,v in ipairs(values)do out[#out+1]=string.format('%02X',v)end;return table.concat(out)end
        assert(native:pending());native:hold();native:service_slice(shared_pump)
        bytes[8]=bytes[7];assert(not native:pending());native:service_slice(shared_pump)
    """)
    g = lua.globals()
    assert g.yields == g.disarms == 1 and g.pumps == 2 and g.steps == 0


@pytest.mark.parametrize("fault", ["failed_host", "pump", "step"])
def test_embedded_lifecycle_failure_never_releases_the_owner(lua, fault):
    lua.execute("construct();scope=arm();native:hold()")
    if fault == "failed_host":
        lua.execute("host_failure='latched';native:hold();native:service_slice(shared_pump)")
    else:
        if fault == "step":
            lua.execute("step_failure=true")
        pump = "function()pumps=pumps+1;return false,'pump failed'end" if fault == "pump" else "shared_pump"
        with pytest.raises(LuaError):
            lua.execute(f"native:service_slice({pump})")
    g = lua.globals()
    assert g.is_armed and g.disarms == g.steps == 0 and g.arms == g.pumps == 1
    if fault != "pump":
        lua.execute("assert(native:pending());native:service_slice(shared_pump)")
        assert g.disarms == 0 and g.yields >= 1


def test_embedded_lifecycle_orders_native_pump_clock_shared_pump_and_one_authorized_frame(lua):
    lua.execute("""
        construct();scope=arm();native:hold()
        -- The frame-accounting adapter observes the native pump; the host observes
        -- the resulting authorized frame. Keep the real lifecycle methods intact.
        native.frame_accounting={pump=function()native_pumped=true;now=1.1 end}
        native:service_slice(function()
            assert(native_pumped);pumps=pumps+1;now=1.15
            return true
        end)
    """)
    g = lua.globals()
    assert g.pumps == g.steps == 1 and g.yields == g.disarms == 0
    assert g.native.last_service == 1.15
    assert g.native.metrics.service_seconds == pytest.approx(0.05)
