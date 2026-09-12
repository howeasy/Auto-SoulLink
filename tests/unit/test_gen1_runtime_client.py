"""Actual Lua Gen1/shared pump and Python runtime; modeled held host/transport."""

import json

import pytest

from server.gen1_party_codec import PartyCodec
from server.protocol import canonical_json, decode_frame
from server.state import LinkStatus
from tests.unit.test_client_state_store import runtime as lua_store
from tests.unit.test_gen1_runtime_server import RuntimeCase

HARNESS = r"""
    package.path=root..'/data/games/gen1_rby/?.lua;'..package.path
    local data=assert(JSON.decode(client_input))
    Journal=require('client_journal');Runtime=require('gen1_runtime')
    gameinfo={getromhash=function()return data.cartridge.final_rom_sha1 end}
    context=data.context
    initial=Journal.initial();store=assert(open_store())
    ids=0
    journal=assert(Journal.open(store,function()ids=ids+1;return data.id_prefix..string.format('%030x',ids)end))
    incoming={};outgoing={};connected=false;held=true;frames=0;applied=0;nonce=0;t=0
    transport={
        init=function(host,port,options)assert(options.discard_on_disconnect);connected=true;incoming={};outgoing={}end,
        connected=function()return connected end,
        pump=function()end,
        send=function(line)outgoing[#outgoing+1]=line;return true end,
        receive=function()return table.remove(incoming,1)end,
        disconnect=function()connected=false;incoming={};outgoing={}end,
        queue_status=function()return {send_lines=0,send_bytes=0,send_offset=0,receive_lines=0,receive_bytes=0,
            partial_receive_bytes=0,pending_receive_bytes=0,ready_receive_bytes=0}end,
    }
    options={player=data.player,variant=data.variant,run_id=data.run_id,server_host='127.0.0.1',server_port=9000,
        journal=journal,transport=transport,clock=function()return t end,
        host={set_held=function(value)held=value;return true end},
        read_context=function()return context end,
        operation_ready=function()return false,'physical operations are outside this held interoperability case'end,
        executor_adapter={prepare=function()error('unexpected prepare')end,classify=function()error('unexpected classify')end,
            apply=function()applied=applied+1;error('unexpected effect')end,receipt=function()error('unexpected receipt')end},
        new_nonce=function()nonce=nonce+1;return data.nonce_prefix..string.format('%030x',nonce)end,
    }
    runtime=assert(Runtime.new(options))
    function step()return runtime:step()end
    function pop()return table.remove(outgoing,1)end
    function push(raw)incoming[#incoming+1]=raw end
    function observe(raw)return runtime:observe(assert(JSON.decode(raw)),{schema='test-baseline-v1',hp=0})end
    function state_json()local state=assert(store:read());return assert(JSON.encode(state))end
    function status_json()return assert(JSON.encode(runtime:status()))end
"""


def client(case, player):
    lua = lua_store.__wrapped__()
    report = case.hello(player)
    lua.globals().client_input = json.dumps(
        {
            "player": player,
            "run_id": case.runtime.journal.run_id,
            "variant": case.variants[player],
            "cartridge": case.contract["players"][player],
            "context": {
                "context_generation": report["context_generation"],
                **report["gen1_metadata"],
            },
            "id_prefix": "aa" if player == "a" else "bb",
            "nonce_prefix": "cc" if player == "a" else "dd",
        }
    )
    lua.execute(HARNESS)
    return lua


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_paired_lua_durable_delivery_matches_python_journal_without_any_frames(tmp_path, variants):
    case = RuntimeCase(tmp_path, variants)
    clients = {p: client(case, p) for p in ("a", "b")}
    owners = {p: object() for p in clients}
    sent = []
    tick = 0

    def exchange(count):
        nonlocal tick
        for _ in range(count):
            tick += 1
            case.time = 10 + tick * 0.05
            for p, lua in clients.items():
                g = lua.globals()
                g.t = tick * 0.05
                assert g.step() is True
                while (line := g.pop()) is not None:
                    message = decode_frame(line.encode())
                    response = case.runtime.process(message, owners[p])
                    sent.append((p, message, response))
                    g.push(canonical_json(response))
                assert g.held is True and g.applied == g.frames == 0

    try:
        original_rules = case.runtime.journal.snapshot().state["rules"]
        exchange(8)
        assert case.runtime.journal.snapshot().state["rules"] == original_rules
        ids = (
            clients["a"].globals().observe(json.dumps([{"event": "faint", "key": case.keys["a"]}]))
        )
        operation = ids[1]
        before = json.loads(clients["a"].globals().state_json())
        assert (
            before["outbox"][-1]["operation_id"] == operation and before["observation"]["hp"] == 0
        )
        semantic_start = len(sent)
        exchange(8)
        faint_index = next(index for index, (p, message, _response) in enumerate(sent)
                           if index >= semantic_start and p == "a" and message["event"] == "faint")
        assert not any(p == "a" and message["event"] == "sync" for p, message, _ in sent[faint_index + 1:])
        exchange(6)
        assert case.runtime.rule_state().links[0].status == LinkStatus.DEAD
        received = json.loads(clients["b"].globals().state_json())
        commands = [row for row in received["inbox"] if row["body"]["cmd"] == "force_faint"]
        assert len(commands) == 1 and "outcome" not in commands[0]
        record = case.runtime.journal.command("b", commands[0]["command_id"])
        assert commands[0]["body"]["body"] == record["body"] and record["outcome"] is None
        after = json.loads(clients["a"].globals().state_json())
        assert not any(row["operation_id"] == operation for row in after["outbox"])
        assert after["observation"] == before["observation"]
        assert len([m for p, m, _ in sent if m.get("event") == "faint"]) == 1
        assert all("party" not in m for _, m, _ in sent if m["event"] == "hello")
        # An already-observed after-state may produce a validated receipt under
        # the hold. The physical observation here is a deliberate test fixture.
        mon = PartyCodec(case.variants["b"]).validate_blob(case.blobs["b"])
        before = {
            "schema": "gen1-party-readback-v1",
            "variant": case.variants["b"],
            "save_id": "0000",
            "save_name": "SAME",
            "party_count": 1,
            "party": [mon.raw.hex().upper()],
            "species_list": [mon.species_index, 255],
            "battle_flag": 0,
            "active_slot": None,
            "battle_hp": None,
        }
        after = json.loads(json.dumps(before))
        raw = bytearray(mon.raw)
        raw[1:3] = b"\0\0"
        after["party"] = [raw.hex().upper()]
        proof = {"schema": "gen1-force-faint-receipt-v1", "before": before, "after": after}
        lua = clients["b"]
        lua.globals().receipt_json = json.dumps(proof)
        lua.execute("""
            options.operation_ready=function(body)return body.cmd=='force_faint' end
            options.executor_adapter.prepare=function()return {schema='observed-after-fixture-v1'}end
            options.executor_adapter.classify=function()return 'after',assert(JSON.decode(receipt_json))end
            options.executor_adapter.receipt=function(_,_,observation)return observation end
        """)
        exchange(14)
        assert any(p == "a" and message["event"] == "sync" for p, message, _ in sent[semantic_start:])
        assert case.runtime.journal.command("b", commands[0]["command_id"])["outcome"] == "ACK"
        client_state = json.loads(lua.globals().state_json())
        assert client_state["command_floor"] >= commands[0]["command_sequence"]
        assert not any(
            row["command_id"] == commands[0]["command_id"] for row in client_state["inbox"]
        )
        assert all(c.globals().held and c.globals().applied == 0 for c in clients.values())
    finally:
        case.close()


def test_exact_body_unwrap_keeps_inner_reserved_fields_and_refuses_mismatches(tmp_path):
    case = RuntimeCase(tmp_path)
    try:
        lua = client(case, "b")
        lua.globals().wrapped = json.dumps(
            {
                "cmd": "native_trade_commit",
                "body": {
                    "cmd": "native_trade_commit",
                    "player": "b",
                    "seq": 17,
                    "operation_id": "inner",
                    "protocol": "inner",
                },
            }
        )
        body = lua.eval("JSON.encode(Runtime.unwrap(assert(JSON.decode(wrapped)),'b'))")
        assert json.loads(body) == json.loads(lua.globals().wrapped)["body"]
        assert (
            lua.eval("pcall(function()Runtime.unwrap({cmd='one',body={cmd='two'}},'b')end)")[0]
            is False
        )
        assert (
            lua.eval(
                "pcall(function()Runtime.unwrap({cmd='one',body={cmd='one',player='a'}},'b')end)"
            )[0]
            is False
        )
    finally:
        case.close()


def test_gen1_wrapper_cannot_be_retargeted_and_preserves_journal_on_hold(tmp_path):
    case = RuntimeCase(tmp_path)
    try:
        lua = client(case, "a")
        lua.execute(
            "options.protocol='other';options.hold_event='other_hold';Runtime.PROTOCOL='other';t=0.1;assert(step())"
        )
        hello = json.loads(lua.globals().pop())
        assert hello["protocol"] == "slink-gen1-durable-v1"
        lua.globals().events_json = json.dumps([{"event": "trade_request"}])
        result = lua.eval("runtime:observe(assert(JSON.decode(events_json)),{})")
        assert result[0] is None
        assert json.loads(lua.globals().state_json())["outbox"] == []
    finally:
        case.close()


def test_free_service_completes_startup_held_command_before_constructing_loop():
    lua = lua_store.__wrapped__()
    lua.globals().launch_json = json.dumps({
        "schema": "slink-gen1-launch-v1", "protocol": "slink-gen1-durable-v1",
        "mode": "free_service", "run_id": "a" * 32, "player": "a",
        "host": "localhost", "port": 9000, "initial_observations": True,
        "cartridge": {"variant": "yellow", "final_rom_sha1": "e" * 40},
    })
    lua.execute(r'''
        package.path=root..'/lua/?.lua;'..package.path
        JSON=require('json_codec');physical=false;pending=1;event_pending=0;loop_built=false;startup_write=false;clock=0;nonce=0;frame=100
        write_safe=true;continuity_fault=nil;captures=0
        gameinfo={getromhash=function()return string.rep('e',40)end}
        emu={framecount=function()return frame end,yield=function()end,frameadvance=function()error('startup advanced a frame')end}
        event={onloadstate=function(fn)load_callback=fn;return 'load-hook'end,unregisterbyid=function()end}
        console={log=function()end}
        package.loaded['memory_gb']={initProfile=function()end,isPartyWriteSafe=function()return write_safe end,
            readPlayerId=function()return 0 end,readPlayerName=function()return 'SAME'end,read_u8=function()return 1 end}
        package.loaded['games.gen1_rby']={}
        package.loaded['gen1_runtime_profiles']={metadata=function(_,cartridge)return cartridge end}
        package.loaded['platform_identity']={new_nonce=function()nonce=nonce+1;return string.format('%032x',nonce)end}
        local host={set_held=function(value)physical=value;return true end,
            status=function()return {held=physical,physical_stop_verified=physical}end,
            yield_held=function()assert(physical);return true end}
        package.loaded['platform_execution']={supported_profile=function()return {}end,new=function()return host end}
        package.loaded['platform_clock']={new=function()return function()return clock end end}
        luanet={load_assembly=function()end,import_type=function(name)
            if name=='System.IO.Path'then return {GetFullPath=function(value)return value end,
                GetDirectoryName=function()return 'tmp'end}end
            error('unexpected type '..name)
        end}
        local baseline={initial_inventory={phase='acknowledged',operation_id=string.rep('9',32)},bootstrap={phase='acknowledged'},
            observation_sequence=1,observation_cursor={sequence=1,operation_id=string.rep('8',32),frame=100}}
        local store={read=function()return {observation=baseline}end,close=function()end}
        package.loaded['platform_storage']={new=function()return {}end}
        package.loaded['state_store']={open=function()return store end}
        package.loaded['connector']={}
        local journal={hud_state=function()return nil end,
            pending_commands=function()return pending==1 and {{command_id='initial'}}or{}end,
            pending_events=function()return event_pending==1 and {{operation_id=string.rep('5',32)}}or{}end}
        package.loaded['client_journal']={initial=function()return {}end,open=function()return journal end}
        package.loaded['gen1_bootstrap_observer']={new=function()return {close=function()end,status=function()return{}end}end}
        local observer={signals={status=function()return{}end},step=function()end,close=function()end}
        package.loaded['gen1_initial_observation']={new=function()return observer end,capture=function()captures=captures+1;return{frame=100}end}
        local operations={request=function()end,accept=function()return true end,authorize_apply=function()return false end,
            revoke=function()end,status=function()return{}end}
        package.loaded['gen1_held_faint']={new=function()return {operations=operations,ready=function()return false end,
            handles=function(body)return body.cmd~='hud_notice'and body.cmd~='hud_state'end,
            pending=function()return pending==1 end,adapter={prepare=function()end,classify=function()end,
                apply=function()end,receipt=function()end}}end}
        package.loaded['gen1_acquisition_observers']={new=function()return {close=function()end}end}
        package.loaded['battle_force_authority']={service=function()return {revoke=function()return true end,
            close=function()return true end,status=function()return{}end}end}
        package.loaded['gen1_runtime']={unwrap=function(value)return value end,new=function(options)
            runtime_options=options
            return {step=function()
                    if pending==1 then
                        assert(not loop_built and physical and options.operation_held(),'startup command lacks the startup hold')
                        startup_write=true;pending=0
                    end
                    return true
                end,
                has_service_lease=function()return true end,is_bound=function()return true end,
                observe=function()return {1}end,status=function()return{}end,revoke=function()end}
        end}
        package.loaded['gen1_observation_loop']={new=function()
            assert(startup_write and pending==0 and physical,'loop constructed before startup command settled')
            loop_built=true;return {tick=function()end,continuity=function()
                if continuity_fault then return nil,continuity_fault end
                return {cursor=baseline.observation_cursor,
                idle={acquisition_open=false,acquisition_pending=0,engine_pending=0,instruction_open=false,
                    instruction_armed=false,battle=0,source_frame=100}}end}
        end}
        service=assert(require('gen1_client_entry').start(assert(JSON.decode(launch_json)),{root=root,storage_root='tmp'}))
        assert(service:step())
        assert(startup_write and loop_built and service.loop~=nil and not physical)
        assert(runtime_options.on_service_authority({},{required=true,proofs={a=false,b=false}})and not physical)
        assert(runtime_options.on_revoke('connector disconnected'))
        assert(physical and service.holds:held('lifecycle'))
        local recovery={service_epoch=string.rep('7',32),refusals={}}
        local binding={binding_digest=string.rep('6',64)}
        event_pending=1;assert(runtime_options.service_continuity(recovery,binding)==nil);event_pending=0
        pending=1;assert(runtime_options.service_continuity(recovery,binding)==nil);pending=0
        write_safe=false;assert(runtime_options.service_continuity(recovery,binding)==nil and service.phase~='failed');write_safe=true
        continuity_fault='battle state prohibits service continuity'
        assert(runtime_options.service_continuity(recovery,binding)==nil and service.phase~='failed')
        continuity_fault=nil
        continuity=assert(runtime_options.service_continuity(recovery,binding))
        assert(captures==1)
        assert(runtime_options.service_continuity(recovery,binding).cursor.sequence==1 and captures==1)
        local next_recovery={service_epoch=string.rep('8',32),refusals={}}
        assert(runtime_options.service_continuity(next_recovery,binding).service_epoch==next_recovery.service_epoch and captures==2)
        assert(runtime_options.service_continuity(next_recovery,binding).cursor.sequence==1 and captures==2)
        clock=10
        recovery.refusals.a='server refused fixture proof'
        assert(runtime_options.service_continuity(recovery,binding)==nil and captures==2)
        assert(runtime_options.service_continuity(recovery,binding)==nil and captures==2)
        clock=11.99;assert(runtime_options.service_continuity(recovery,binding)==nil and captures==2)
        clock=12;assert(runtime_options.service_continuity(recovery,binding).service_epoch==recovery.service_epoch and captures==3)
        recovery.refusals.a=nil
        assert(continuity.schema=='rby-free-service-continuity-v1'and continuity.service_epoch==recovery.service_epoch
            and continuity.initial_operation_id==string.rep('9',32)and continuity.cursor.sequence==1)
        local safe=pcall(runtime_options.on_service_authority,{},{required=true,proofs={a=true,b=false}})
        assert(not safe and physical and service.holds:held('lifecycle'))
        assert(runtime_options.on_service_authority({},{required=false,proofs={a=true,b=true}}))
        assert(not physical and not service.holds:held('lifecycle'))
        assert(runtime_options.on_revoke('connector disconnected'))
        load_callback()
        assert(physical and runtime_options.service_continuity(recovery,binding)==nil)
        frame=99;assert(service:step()==false and physical)
    ''')
