from pathlib import Path

from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def test_aggregate_actuation_is_idempotent_but_explicit_audit_reaches_the_host():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().package.path = (ROOT / "lua/?.lua").as_posix() + ";" + lua.globals().package.path
    lua.execute("""
        calls=0;audits=0;physical=false
        mux=require('hold_mux').new({owners={'startup','control','writer'},host={
            set_held=function(value)calls=calls+1;physical=value;return true end,
            verify=function()audits=audits+1;return true end}})
        assert(mux:set('startup',true,'startup'))
        assert(mux:set('control',true,'control'))
        assert(mux:set('control',true,'same control'))
        assert(mux:set('startup',false,'startup done'))
        assert(calls==1 and physical and mux:is_held())
        assert(mux:verify() and audits==1)
        assert(mux:set('control',false,'service released'))
        assert(calls==2 and not physical and not mux:is_held())
        assert(mux:set('writer',false,'already free') and calls==2)
    """)


def test_owner_adapter_reports_its_own_vote_over_the_actuator_status_and_yields_only_while_holding():
    """A layered owner (the bounded native stepper) takes a hold_mux owner adapter as its host:
    status() carries the actuator's physical readback with `held` = this owner's vote, and a held
    yield is refused unless this owner holds; releasing one owner never clears another's."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().package.path = (ROOT / "lua/?.lua").as_posix() + ";" + lua.globals().package.path
    lua.execute("""
        physical=false;yields=0
        mux=require('hold_mux').new({owners={'writer','native'},host={
            set_held=function(value)physical=value;return true end,
            verify=function()return true end,
            status=function()return {owner_id='inst',held=physical,physical_stop_verified=physical,failed=false,closed=false}end,
            yield_held=function()yields=yields+1;return true end}})
        native=mux:adapter('native')
        local s=native.status();assert(s.owner_id=='inst' and s.held==false and s.physical_stop_verified==false and s.aggregate_held==false)
        local ok,why=native.yield_held();assert(not ok and why:find('must hold'))
        assert(native.set_held(true,'native step pending'))
        s=native.status();assert(s.held==true and s.physical_stop_verified==true and s.aggregate_held==true and s.owner=='native')
        assert(native.yield_held() and yields==1)
        assert(mux:set('writer',true,'write'))
        assert(native.set_held(false,'one frame'))      -- releases only the native vote
        s=native.status();assert(s.held==false and s.aggregate_held==true and physical==true)
        assert(mux:set('writer',false,'done') and physical==false)
    """)
