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
