"""Harness wrappers retain actual arguments, return tuples and original failures."""

import pytest
from lupa.lua54 import LuaError

from tests.unit.test_client_state_store import runtime as runtime


def setup(lua):
    lua.execute('''
        now=0;frame=100;calls={send=0,pump=0,step=0,yield=0}
        emu={framecount=function()return frame end}
        local real_load=loadfile
        loadfile=function(path)
            if path==root..'/lua/gen1_runtime.lua'then return function()
                return {new=function(options)
                    saved_options=options
                    return {step=function(self,value)calls.step=calls.step+1;now=now+0.02;return false,'pending',value end}
                end}
            end end
            if path==root..'/lua/gen1_client_entry.lua'then return function()
                return {start=function(options)
                    return {clock=function()return now end,
                        step=function(self,value)now=now+0.15;return false,'held',value end,
                        status=function()now=now+0.01;return {held=true}end,
                        host={yield_held=function(...)calls.yield=calls.yield+1;now=now+0.03;return ... end}}
                end}
            end end
            return real_load(path)
        end
        probe=dofile(root..'/lua/tests/gen1_cold_timing.lua').install(root,JSON)
        transport={send=function(raw)calls.send=calls.send+1;sent=raw;now=now+0.01;return false,'original send refusal'end,
            receive=function()local result=queued;queued=nil;return result,'original receive extra'end,
            pump=function(value)calls.pump=calls.pump+1;now=now+0.005;return value end}
        service=require('gen1_runtime').new{clock=function()return now end,transport=transport,
            read_context=function()now=now+0.005;return {context='exact'}end}
        owner=require('gen1_client_entry').start({})
    ''')


def test_wire_observation_does_not_change_packet_delivery_or_return_tuple(runtime):
    setup(runtime)
    runtime.execute('''
        raw=assert(JSON.encode({event='control',operation_id='id',seq=1,
            operation_execution={window={scope={operation_id='grant',phase='ordinary'}}}}))
        local accepted,reason=transport.send(raw)
        assert(accepted==false and reason=='original send refusal'and sent==raw and calls.send==1)
        queued=assert(JSON.encode({operation_id='id',seq=1,ack='ACK'}))
        local received,extra=transport.receive();assert(received and extra=='original receive extra')
        local absent,again=transport.receive();assert(absent==nil and again=='original receive extra')
        assert(transport.pump('exact')=='exact'and calls.pump==1)
        local trace=probe.report();assert(#trace.wire==2)
        assert(trace.wire[1].grant_operation=='grant'and trace.wire[1].phase=='ordinary')
        assert(trace.wire[2].direction=='receive'and trace.wire[2].operation=='id')
        assert(not trace.truncated)
    ''')


def test_owner_wrappers_preserve_results_and_measure_harness_separately(runtime):
    setup(runtime)
    runtime.execute('''
        local ok,reason,value=owner:step(17);assert(ok==false and reason=='held'and value==17)
        assert(owner:status().held==true)
        assert(owner.host.yield_held('same')=='same')
        ok,reason,value=service:step(29);assert(ok==false and reason=='pending'and value==29)
        assert(saved_options.read_context().context=='exact')
        local trace=probe.report()
        assert(trace.costs.entry_step.calls==1 and #trace.slow_steps==1)
        assert(trace.costs.entry_status.calls==1 and trace.costs.held_yield_with_harness.calls==1)
        assert(trace.costs.runtime_step.calls==1 and trace.costs.read_context.calls==1)
    ''')


def test_original_context_errors_remain_errors(runtime):
    setup(runtime)
    runtime.execute("service=require('gen1_runtime').new{clock=function()return now end,transport=transport,read_context=function()error('original identity failure')end}")
    with pytest.raises(LuaError, match='original identity failure'):
        runtime.execute('saved_options.read_context()')
