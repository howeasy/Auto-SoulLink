"""Recovery readiness is per report; it never reorders the durable outbox."""
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("first", ["release", "trade_done"])
def test_recovery_gate_holds_a_trade_head_but_not_an_earlier_release(first):
    lua = LuaRuntime()
    module = lua.execute((ROOT / "lua/owed_reports.lua").read_text())
    lua.globals().owed = module.new()
    lua.globals().first = first
    lua.execute('''
        sent={};ready=false
        owed.list={{event=first,fields={key="A"}},
                   {event="trade_done",fields={token="t"}},
                   {event="release",fields={key="B"}}}
        emit=function(event) sent[#sent+1]=event;owed:line_sent();return true end
        gate=function(event) return event=="release" or ready end
        owed:step(true,true,emit,gate)
    ''')
    assert list(lua.globals().sent.values()) == (["release"] if first == "release" else [])
    lua.execute("ready=true; owed:step(true,true,emit,gate)")
    assert list(lua.globals().sent.values()) == [first, "trade_done", "release"]
