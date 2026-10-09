"""The native palette restore oracle stays strict after clock-input normalization."""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def oracle():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    panel = lua.execute((ROOT / "lua/tests/gen2_panel_gate.lua").read_text(encoding="utf-8"))
    return lua, panel


def snapshot(lua):
    return lua.table_from({
        "bgp1": list(range(64)), "bgp2": list(range(64)),
        "obp1": list(range(64)), "obp2": list(range(64)),
        "attr": [i % 256 for i in range(2048)],
    }, recursive=True)


@pytest.mark.parametrize("field,index", [("bgp1", 1), ("bgp1", 64), ("bgp2", 1), ("attr", 2048)])
def test_native_restoration_rejects_corruption_at_buffer_boundaries(oracle, field, index):
    lua, panel = oracle
    before, after = snapshot(lua), snapshot(lua)
    assert panel.same(before, after) is True
    after[field][index] ^= 1
    assert panel.same(before, after) == f"{field}[{index - 1}]"
