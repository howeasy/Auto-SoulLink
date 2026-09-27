"""Production ABI2 panel publication uses INFO's epoch/request/text layout."""
from lupa import lua54
from tests.unit import test_gen3_native as model
from tests.unit.test_gen3_native_trade import TradeNativeWorld


def test_v2_panel_publishes_bound_rows_without_touching_native_receipts(monkeypatch):
    monkeypatch.setattr(model,"lupa",lua54)
    w=TradeNativeWorld(capability=23)
    info=w.n["INFO"]
    w.put(info+6,42,2);w.put(info+12,41,2)
    result=w.native.link_panel(w.native,w.lua.table(rows=w.lua.table("Pairs alive|1/1","Dead zones|0")))
    assert result is True
    w.service()
    assert w.read(info,4)==0x12345678
    assert w.read(info+4,2)>0
    assert w.read(info+6,2)==42 and w.read(info+12,2)==41
    assert w.read(info+8,1)==2 and w.read(info+11,1)==1
    assert 0xfe in w.raw(info+32,32)
    before=w.raw(info,288)
    w.put(info+14,2)
    w.native.link_panel(w.native,w.lua.table(rows=w.lua.table("New data")))
    w.service()
    assert w.raw(info,14)==before[:14]
    assert w.raw(info+32,256)==before[32:]
    w.put(info+14,0);w.service()
    assert w.read(info+8,1)==1
