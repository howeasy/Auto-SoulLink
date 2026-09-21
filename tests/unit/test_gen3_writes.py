"""Write-window contract independent of any game address."""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def world():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        frame=7; safe=true; output={}; receipts={}
        deps={frame=function() return frame end,
            log=function(r) receipts[#receipts+1]=r end,
            io={write_u8=function(a,v) output[#output+1]={a,v} end},
            safety={snapshot=function() return {} end,
                check=function() return safe, 'unsafe checkpoint' end}}
        allow=function(a,n) return a>=100 and a+n<=104 end
    """)
    module = lua.execute((ROOT / "lua/gen3/writes.lua").read_text(encoding="utf-8"))
    lua.globals().w = module.new(lua.globals().deps)
    return lua


def test_unarmed_has_no_writes_or_logs(world):
    with pytest.raises(lupa.LuaError, match="no armed"):
        world.execute("w:write_u16(100, 0)")
    assert len(world.globals().output) == len(world.globals().receipts) == 0


@pytest.mark.parametrize("statement", ["w:write_u32(101, 1)", "w:write_bytes(100,{1,256})",
                                       "w:write_bytes(100,{[1]=1,[3]=3})"])
def test_validate_entire_payload_and_range_before_first_byte(world, statement):
    world.execute("w:arm('overworld',allow)")
    with pytest.raises(lupa.LuaError):
        world.execute(statement)
    assert len(world.globals().output) == len(world.globals().receipts) == 0


def test_little_endian_provenance(world):
    world.execute("w:arm('overworld',allow); w:write_u32(100,16909060)")
    g = world.globals()
    assert [g.output[i][2] for i in range(1, 5)] == [4, 3, 2, 1]
    r = g.receipts[1]
    assert (r.reason, r.address, r.len, r.frame) == ("overworld", 100, 4, 7)
    assert len(g.w.log) == 1


@pytest.mark.parametrize("change", ["frame=8", "safe=false", "w:disarm()"])
def test_revalidate_every_write(world, change):
    world.execute("w:arm('overworld',allow); w:write_u16(100,1)")
    world.execute(change)
    with pytest.raises(lupa.LuaError):
        world.execute("w:write_u16(102,2)")
    assert len(world.globals().output) == 2
    assert len(world.globals().receipts) == 1


def test_failed_rearm_revokes_old_window(world):
    world.execute("w:arm('overworld',allow); safe=false")
    with pytest.raises(lupa.LuaError):
        world.execute("w:arm('native',allow)")
    with pytest.raises(lupa.LuaError, match="no armed"):
        world.execute("w:write_u16(100,0)")


@pytest.mark.parametrize("reason", ["overworld", "battle_faint", "battle_commit", "native", "memorial_rename"])
def test_reason_vocabulary(world, reason):
    world.globals().w.arm(world.globals().w, reason, world.globals().allow)
