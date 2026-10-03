"""Production overlay trade may observe Entry, but cannot replace it."""

from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def test_trade_driver_has_no_entry_rewriting_interface():
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")((ROOT / "lua/tests/duo/gen2_trade.lua").as_posix())
    assert module.PATCHES is None
    assert module.patch_entry is None and module.harness is None
    assert module.SCOPE == "PHYSICAL_RECEIPTED"


def test_historical_override_receipt_is_never_a_production_witness():
    from tools.gen2_trade_oracles import check_trade_witness

    receipt = 'RECEIPT {"schema":"gen2-duo-trade-v1","admission_scope":"HARNESS_ONLY_OVERLAY"}'
    with pytest.raises(RuntimeError, match="historical HARNESS_ONLY_OVERLAY"):
        check_trade_witness({"a": receipt, "b": receipt})
