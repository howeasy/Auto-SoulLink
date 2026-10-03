"""Offline checks of the physical Gen 1 gate's receipt and START-menu assertions."""
from __future__ import annotations

from pathlib import Path

import lupa
import pytest

from tests.live import test_gen1_new_gates as gates
from tests.unit.test_gen1_purergb_client import PROFILE
from tests.unit.test_gen1_purergb_overlay import _syms

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("rom", ["red_patched", "blue_patched", "purered_overlay", "yellow"])
@pytest.mark.parametrize("trade_poll", [False, True])
def test_lab_gate_rejects_trade_pickups_during_a_no_trade_route(monkeypatch, rom, trade_poll):
    import run_gb_gate

    kinds = (["battle_begin", "wild_begin", "battle_end", "starter_begin", "add_party_mon",
              "starter_end", "battle_begin", "add_party_mon"] if rom == "yellow" else
             ["starter_begin", "add_party_mon", "starter_end", "battle_begin", "add_party_mon"])
    kinds += ["battle_loop_head"] * 3 + ["battle_faint"]
    if trade_poll:
        kinds.append("trade_service")
    kinds.append("battle_end")
    text = "SIGNALS " + " ".join(f"{kind}@1" for kind in kinds) + "\nPARTY_RAW 00\n"
    monkeypatch.setattr(run_gb_gate, "run_gate", lambda *args, **kwargs: (True, "model", text))
    monkeypatch.setattr(gates, "_skip_if_dump_absent", lambda _rom: None)
    monkeypatch.setattr(gates.codec, "decode_party", lambda _raw: [
        {"level": 5, "exp": 125 if rom == "yellow" else 135},
    ])
    if trade_poll:
        with pytest.raises(AssertionError, match="trade_service"):
            gates.test_new_game_lab_route_emits_the_engine_sequence(rom, None, monkeypatch)
    else:
        gates.test_new_game_lab_route_emits_the_engine_sequence(rom, None, monkeypatch)


@pytest.mark.parametrize("companion", [False, True])
@pytest.mark.parametrize("pokedex", [False, True])
def test_apex_gate_reads_the_live_start_shape(companion, pokedex):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    facts = lua.eval("dofile")((ROOT / "lua/tests/gen1_pure_facts.lua").as_posix())
    ram = PROFILE["purered"]["ram"]
    event_flags = _syms("purered", "overlay")["wEventFlags"][1]
    expected_max = 5 + int(companion) + int(pokedex)
    bit = int(facts.EVENT.GOT_POKEDEX)
    bus = {ram["wMaxMenuItem"]: expected_max,
           event_flags + bit // 8: (1 << (bit % 8)) if pokedex else 0}
    checks, logs = [], []

    def check(label, ok, detail=None):
        if str(label).endswith(": START menu open"):
            checks.append(bool(ok))
            raise RuntimeError("stop after observing START shape")

    mon = lua.table(dvs=lua.table(raw=0x1234), ot_id=1, species=1)
    client = lua.table(start=lambda _self: None, frame_end=lambda _self: None,
                       send_hello=lambda _self: None, trade_patch_present=lambda _self: companion,
                       writes_enabled=True, player="a")
    t = lua.table(ROOT=ROOT.as_posix(), title="purered", facts=facts, client=client,
                  parts=lua.table(profile=lua.table(ram=lua.table_from(ram)),
                                  reads=lua.table(read_party=lambda: lua.table(mon), key=lambda _mon: "key"),
                                  json=lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix())),
                  sent=lua.table(), replies=lua.table(), check=check, log=lambda s: logs.append(str(s)),
                  step=lambda _buttons=None: None, finish=lambda: None, overworld_ok=lambda: True)
    lua.globals().SLINK_ROOT = ROOT.as_posix()
    lua.globals().memory = lua.table(read_u8=lambda addr, dom: bus.get(int(addr) + (0xC000 if dom == "WRAM" else 0), 0),
                                     write_u8=lambda addr, value, _dom: bus.__setitem__(int(addr), int(value)))
    lua.globals().gameinfo = lua.table(getromhash=lambda: "ab" * 20)
    lua.globals().gate_stub = t
    lua.execute("""
        local original = dofile
        dofile = function(path)
            if path:match("/gen1_gate.lua$") then return {start=function() return gate_stub end} end
            return original(path)
        end
    """)
    lua.eval("dofile")((ROOT / "lua/tests/test_gen1_apex_gate.lua").as_posix())
    assert checks == [True], logs
    assert any("START_SHAPE" in line and f"expected_max={expected_max}" in line
               and f"observed_max={expected_max}" in line
               and f"pokedex={str(pokedex).lower()}" in line
               and f"companion={str(companion).lower()}" in line
               and f"item_row={2 if pokedex else 1}" in line for line in logs), logs
