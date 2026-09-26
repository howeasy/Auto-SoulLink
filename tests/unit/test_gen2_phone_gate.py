"""P4.5d: the pure verdict of lua/tests/gen2_phone_gate.lua under lupa, and the facts
tests/live/test_gen2_phone_gate.phone_facts derives (call texts, ROBBED, the census SRAM offsets)."""
from __future__ import annotations

import pathlib
import sys

import lupa
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = (REPO / "lua" / "tests" / "gen2_phone_gate.lua").as_posix()
sys.path.insert(0, str(REPO))


def gate():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    return lua, lua.eval(f'dofile("{GATE}")')


def good(lua, **over):
    c = {"id": 2, "posted": 100, "acked": 101, "armed_id": 2, "step_at": 400,
         "slink_ring": lua.table_from({"frame": 440, "caller": 0}), "screen_caller": True, "screen_text": True,
         "after_armed": 0, "after_id": 0}
    c.update(over)
    return lua.table_from(c)


def test_ring_case_verdict():
    lua, P = gate()
    assert P.problem(good(lua)) is None
    assert "before the qualifying step" in P.problem(good(lua, early_ring=300))
    assert "must read 0" in P.problem(good(lua, id_visible=lua.table_from([200, 9])))
    assert "never rang" in P.problem(good(lua, slink_ring=None))
    assert "before the step" in P.problem(good(lua, slink_ring=lua.table_from({"frame": 399, "caller": 0})))
    assert "frames after the step" in P.problem(good(lua, slink_ring=lua.table_from({"frame": 400 + 241, "caller": 0})))
    assert "PHONE_00" in P.problem(good(lua, slink_ring=lua.table_from({"frame": 440, "caller": 3})))
    assert "ARMED read" in P.problem(good(lua, armed_id=0))
    assert "not 0/0" in P.problem(good(lua, after_armed=2))
    assert "never acknowledged" in P.problem(good(lua, acked=None))


def test_phone_facts():
    from tests.live.test_gen2_phone_gate import phone_facts, text_needles
    assert text_needles('SlinkPhoneFallenText::\n\ttext "…Hello? <PLAYER>?"\nSlinkPhoneDeadZoneText::\n'
                        '\ttext "<PLAYER>? Can you"\nSlinkPhoneFirstLinkText::\n\ttext "Hey, <PLAYER>!"') == {
        "1": "Hello?", "2": "? Can you", "3": "Hey,"}
    for title in ("crystal", "gold", "silver"):
        try:
            f = phone_facts(title)
        except Exception as exc:  # noqa: BLE001 - the pinned build is a local input
            pytest.skip(f"pinned build unavailable: {exc}")
        assert f["robbed"] == 2 and set(f["texts"]) == {"1", "2", "3"}
        assert f["ram"]["wSpecialPhoneCallID"]["bank"] == 1
        assert f["sites"]["ClearUnusedMapBuffer"]["bank"] == 0   # PHONE-NAMES v2: the wipe hook, ROM0


def test_v2_named_record_is_the_shipped_binder_record():
    """The gate compares the ring-time stage with Phone.record over its own P.NAMED (max-length names)."""
    lua, P = gate()
    assert P.SCHEMA == "gen2-phone-gate-v2"
    phone = lua.eval(f'dofile("{(REPO / "lua/gen2/phone.lua").as_posix()}")')
    encode = lua.eval(f'dofile("{(REPO / "lua/gen2/trade_overlay.lua").as_posix()}")').encode_name
    charmap = lua.eval(f'dofile("{(REPO / "data/games/gen2_crystal/charmap.lua").as_posix()}")')
    rec = [phone.record(1, P.NAMED, encode, charmap)[i] for i in range(1, 25)]
    assert rec[0:3] == [1, 16, 19] and rec[10] == 0x50 and rec[21] == 0x50 and rec[23] == 0xA6
    assert 0x50 not in rec[3:10] and 0x50 not in rec[11:21]   # 7 and 10 glyphs: the maxima
