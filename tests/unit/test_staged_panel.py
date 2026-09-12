"""Reusable publication protocol; no game, character set or frame authority."""

from pathlib import Path

import pytest
from lupa import LuaRuntime


@pytest.fixture
def panel():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = Path(__file__).resolve().parents[2].as_posix()
    lua.execute("""
        package.path=root..'/lua/?.lua;'..package.path
        bus={state=1,page=0,pages=0,generation=0,transfers=7,lease=0};writes={};available=true;fault=nil
        painter=function(rows,page)
            assert(bus.generation%2==1 and bus.transfers==0)
            painted=page
            if fault=='throw' then error('paint failed')end
            if fault=='lost' then available=false end
            if fault=='page' then bus.page=page+1 end
        end
        panel=require('staged_panel').new({page_rows=18,lease_frames=180,
            read=function(name)return bus[name]end,
            write=function(name,value)bus[name]=value;writes[#writes+1]={name=name,value=value}end,
            available=function()return available end,
            paint=function(...)return painter(...)end})
        rows={};for i=1,36 do rows[i]='line'end
    """)
    return lua


@pytest.mark.parametrize("prior,final", [(0, 2), (254, 0), (255, 2)])
def test_odd_generation_covers_paint_and_even_generation_precedes_staged(panel, prior, final):
    panel.globals().bus.generation = prior
    assert panel.eval("panel:stage(rows)")
    writes = list(panel.globals().writes.values())
    assert writes[0].name == "generation" and writes[0].value % 2 == 1
    assert writes[-2].name == "generation" and writes[-2].value == final
    assert writes[-1].name == "state" and writes[-1].value == 2
    assert panel.globals().bus.pages == 2 and panel.globals().bus.lease == 180
    assert not panel.eval("panel:stage(rows)")


@pytest.mark.parametrize("fault", ["throw", "lost", "page"])
def test_interrupted_or_changed_publication_never_becomes_staged(panel, fault):
    panel.globals().fault = fault
    if fault == "throw":
        with pytest.raises(Exception, match="paint failed"):
            panel.eval("panel:stage(rows)")
    else:
        assert not panel.eval("panel:stage(rows)")
    assert panel.globals().bus.generation % 2 == 1 and panel.globals().bus.state == 1


def test_only_owned_current_generation_can_refresh_or_revoke_lease(panel):
    assert not panel.eval("panel:maintain(true)")
    assert panel.eval("panel:stage(rows)")
    panel.globals().bus.lease = 3
    assert panel.eval("panel:maintain(true)") and panel.globals().bus.lease == 180
    assert panel.eval("panel:maintain(false)") and panel.globals().bus.lease == 0
    panel.globals().bus.generation = 4
    assert not panel.eval("panel:maintain(true)") and panel.globals().bus.lease == 0


def test_closed_or_unavailable_panel_never_writes(panel):
    panel.globals().bus.state = 0
    assert not panel.eval("panel:stage(rows)")
    panel.globals().bus.state = 1
    panel.globals().available = False
    assert not panel.eval("panel:stage(rows)") and len(panel.globals().writes) == 0
