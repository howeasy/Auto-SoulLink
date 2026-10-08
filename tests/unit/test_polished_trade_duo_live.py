"""Trade/cold-load judge falsifiers; no emulator launch."""
import copy
import inspect
from pathlib import Path

import pytest

from tools.polished_live import trade_duo_live as t


def evidence():
    if not t.FIXTURE.exists():
        pytest.skip("retained SYNTH receptionist save absent")
    a = t.FIXTURE.read_bytes()
    b, _ = t.duo._derive_save().derive_identity(a, name="TradeB", player_id=53699)
    before = {"a": a, "b": b}
    original = {r: t.party(s) for r, s in before.items()}
    wire, cold, link = {}, {}, {"status": "alive"}
    for r, other in (("a", "b"), ("b", "a")):
        key = original[other][0]["key"]
        wire[r] = [{"dir": "c2s", "msg": {"event": "hello", "party": original[r]}},
                   {"dir": "s2c", "msg": {"commands": [{"cmd": "apply_trade", "token": "t1"}]}},
                   {"dir": "c2s", "msg": {"event": "trade_done", "token": "t1", "new_key": key}}]
        cold[r] = {"party": original[r][1:]+[original[other][0]],
                   "trainer_name": t.duo.fixture_identity(before[r])["name"]}
        link[r] = {"key": key}
    return wire, before, cold, {"links": [link], "pending_trade": None}


def test_trade_and_cold_load_positive():
    assert t.judge(*evidence()) == ("PASS", [])


@pytest.mark.parametrize("fault", ["no-done", "uncertain", "old-cold", "dead", "pending", "faint"],
                         ids=["missing-side", "uncertain", "not-durable", "dead-link", "inflight", "false-faint"])
def test_judge_controls_fail(fault):
    wire, before, cold, state = copy.deepcopy(evidence())
    if fault == "no-done":
        wire["b"] = []
    elif fault == "uncertain":
        wire["a"][-1]["msg"]["uncertain"] = True
    elif fault == "old-cold":
        cold["b"]["party"] = t.party(before["b"])
    elif fault == "dead":
        state["links"][0]["status"] = "dead"
    elif fault == "pending":
        state["pending_trade"] = {"phase": "applying"}
    else:
        wire["a"].append({"dir": "c2s", "msg": {"event": "faint"}})
    assert t.judge(wire, before, cold, state)[0] == "FAIL"


def test_default_builder_remains_disabled_and_test_output_cannot_publish(tmp_path):
    from tools import build_polished_companion as build
    sig = inspect.signature(build.build)
    assert sig.parameters["test_trade_enable"].default is False
    assert sig.parameters["test_output"].default is None
    original = (build.UPS_PATH.read_bytes(), build.PROVENANCE_PATH.read_bytes())
    for args in ({"test_trade_enable": True}, {"test_output": build.OUT_DIR}, {"test_output": tmp_path, "check": True}):
        with pytest.raises(RuntimeError):
            build.build(**args)
    assert original == (build.UPS_PATH.read_bytes(), build.PROVENANCE_PATH.read_bytes())


def test_setup_is_one_link_from_real_save_keys(tmp_path):
    _, before, _, _ = evidence()
    events = t.seed_server(tmp_path, before)
    assert [e["msg"]["event"] for e in events] == ["hello", "capture", "hello", "capture"]
    for row in events:
        if row["msg"]["event"] == "capture":
            assert row["msg"]["key"] == t.party(before[row["player"]])[0]["key"]


def test_lua55_syntax():
    from lupa.lua55 import LuaRuntime
    lua = LuaRuntime()
    for name in ("tools/polished_live/trade_duo_live.lua", "lua/gen2/polished_trade.lua", "lua/gen2/client.lua"):
        assert lua.eval("function(s) return assert(load(s)) ~= nil end")((t.ROOT/Path(name)).read_text())


def test_symbol_contract_fits_real_json_decoder_and_full_sym_is_red_control():
    import json

    from lupa.lua55 import LuaRuntime

    from tools.build_gen2_companion import _symbols
    syms = _symbols(t.ROOT/"data/polished/polished_slink.sym")
    lua = LuaRuntime(unpack_returned_tuples=True)
    codec = lua.execute((t.ROOT/"lua/json_codec.lua").read_text())
    old, why = codec.decode(json.dumps(syms))
    assert old is None and "too many JSON values" in why
    decoded = codec.decode(json.dumps(t.probe_symbols(syms)))
    assert decoded.NoYesBox[2] == syms["NoYesBox"][1]


def compose_without_global_print():
    import json

    from tests.unit import test_polished_write_path as wp
    from tests.unit.test_polished_client import _entry, _pair
    lua = wp.lupa.LuaRuntime(unpack_returned_tuples=True)
    mem = lua.table_from(wp.sysbus(wp.party()))
    deps, _, log = lua.execute(wp.HARNESS.replace("ROOTDIR", json.dumps(wp.ROOT)))(wp.overlay()[1], mem, wp.seal_save(wp.Image()))
    deps.polished_trade_dev = True
    lua.globals().print = None  # MODEL of the live refusal: no Lua-function global print
    parts, why = _pair(_entry(lua).build(deps))
    assert parts and why is None
    assert parts.dev_polished_trade is not None, list(log.lines.values())


def test_composition_passes_explicit_logger_without_global_print():
    compose_without_global_print()
