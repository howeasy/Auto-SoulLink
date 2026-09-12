"""gen1_native_host: the native runtime's host inside the composed free-service client. One
hold_mux owner vote over the entry's single actuator; a short-lived bounded stepper is layered
on it only while armed; unarmed it is truthfully not bounded and cannot step."""
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lua():
    value = LuaRuntime(unpack_returned_tuples=True)
    value.globals().package.path = (ROOT / "lua/?.lua").as_posix() + ";" + value.globals().package.path
    value.execute("""
        physical=false;frame=500;created={};closed={}
        emu={framecount=function()return frame end}
        actuator={set_held=function(value)physical=value;return true end,verify=function()return true end,
            status=function()return {owner_id='inst',held=physical,physical_stop_verified=physical,failed=false,closed=false,process_id=7}end,
            yield_held=function()return true end}
        mux=require('hold_mux').new({owners={'startup','writer','native'},host=actuator})
        -- Modeled bounded owner: records what it was given, steps by releasing/re-holding the injected adapter.
        Bounded={new=function(options)
            local shared=options.host.status()
            assert(shared.owner_id==options.owner_id and shared.held==true and shared.physical_stop_verified==true,'injected actuator must be held')
            local expected=frame;local steps=0;local failed=nil
            local owner={}
            function owner.step_one(scope)
                local ok,result=pcall(function()
                    assert(frame==expected,'bounded frame requires its unchanged held context')
                    assert(options.authorize(scope,{frame=frame})==true,'per-step authority is absent')
                    assert(options.host.set_held(false,'one frame'))
                    if not physical then frame=frame+1 end          -- the core advances only when nothing holds
                    assert(options.host.set_held(true,'frame done'))
                    assert(frame==expected+1,'bounded frame did not advance')
                    expected=frame;steps=steps+1;return {before=frame-1,after=frame}
                end)
                if not ok then failed=failed or tostring(result);return false,failed end   -- stop(): latched, never released
                return true,result
            end
            function owner.set_held(value,why)if value~=true then return false,'no unbounded release'end;return options.host.set_held(true,why)end
            function owner.yield_held()return options.host.yield_held()end
            function owner.close(reason)closed[#closed+1]=reason or 'closed';failed=failed or 'closed';return true end
            function owner.status()return {schema='slink-bounded-execution-status-v1',failed=failed,steps=steps,host=options.host.status(),
                expected_frame=expected,single_frame_only=true,frame_callbacks_suppressed=true,load_state_invalidation=true,
                owner_exit_invalidation=true,frame_rate={numerator=262144,denominator=4389},armed=true}end
            created[#created+1]=owner;return owner
        end}
        authorized=true
        host=require('gen1_native_host').new({adapter=mux:adapter('native'),owner_id='inst',expected_host={},
            authorize=function()return authorized end,bounded=Bounded})
    """)
    return value


def test_unarmed_host_is_truthfully_unbounded_and_cannot_step(lua):
    lua.execute("""
        local s=host.status()
        assert(s.single_frame_only==false and s.frame_callbacks_suppressed==false and s.armed==false and s.host.held==false)
        local ok,why=host.step_one({});assert(not ok and why:find('not armed'))
        assert(#created==0 and physical==false)
    """)


def test_arm_layers_a_fresh_bounded_owner_that_steps_exactly_one_frame_per_authorized_step(lua):
    lua.execute("""
        assert(host.arm('trade'))
        assert(#created==1 and physical==true and host.status().armed==true and host.status().host.held==true)
        assert(host.step_one({phase='native_trade_commit'}));assert(frame==501 and host.status().steps==1 and physical==true)
        assert(host.step_one({}));assert(frame==502)
        authorized=false
        local ok,why=host.step_one({});assert(not ok and tostring(why):find('authority'))
        assert(host.disarm('done'))
        assert(physical==false and #closed==1 and host.armed()==false and host.status().armed==false)
        -- A later arm is a NEW stepper at the current frame, never the closed one.
        frame=900;assert(host.arm('again'));assert(#created==2 and created[2].status().expected_frame==900)
        assert(host.disarm())
    """)


def test_a_step_while_another_owner_holds_cannot_advance_and_fails_closed(lua):
    lua.execute("""
        assert(mux:set('writer',true,'held write'))
        assert(host.arm('trade'))
        local ok,why=host.step_one({});assert(not ok and why:find('did not advance'))
        assert(frame==500 and physical==true and host.status().failed~=nil)   -- writer still holds, nothing ran
        assert(host.disarm())
        assert(physical==true and mux:held('writer'))                          -- only the native vote was released
    """)


def test_arm_refuses_a_double_arm_and_leaves_no_vote_when_the_owner_cannot_be_built(lua):
    lua.execute("""
        assert(host.arm('trade'))
        local ok=pcall(host.arm,'twice');assert(not ok)
        assert(host.disarm())
        Bounded.new=function()error('host conflict',0)end
        local built,why=pcall(host.arm,'broken');assert(not built and tostring(why):find('host conflict'))
        assert(physical==false and host.armed()==false)
    """)
