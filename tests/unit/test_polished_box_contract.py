"""Polished box commands through the REAL client (client contract; review cx-532590c0 ranks 1 and 6).

The executor (polished_overworld.lua O.boxes) reports a successful party_mon as `true, <metadata table>` and a full
party as `party full (n/m)`. lua/gen2/client.lua run_box reads the second value as the F1 settle-note STRING
(concatenated into a log line BEFORE sync_retrieve_done) and takes its deferred-retry path only for exactly
`party full`. So on the raw executor shape a successful withdraw never acked (the mon was in the party, the server
never heard) and a full party failed at once. O.client_boxes is the adapter compose_polished wraps the executor in.

Here: the composed Polished client over the real overlay ROM (the Rig of test_polished_write_path.py) withdraws a
planted boxed mon end to end; every property has a CONTROL that unwraps the adapter and reproduces the bug on the
real executor, and the adapter's own source is mutated (in process) to prove the assertions can fail.

Run: pytest tests/unit/test_polished_box_contract.py -v
"""
from __future__ import annotations

import contextlib
import pathlib

import pytest

lupa = pytest.importorskip("lupa")

from tests.unit.test_polished_withdraw_path import boxed, boxed_mon, options  # noqa: E402
from tests.unit.test_polished_write_path import Rig, key_of, party  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
OVERWORLD = (REPO / "lua/gen2/polished_overworld.lua").read_text(encoding="utf-8")
ENTRY = (REPO / "lua/gen2/entry.lua").read_text(encoding="utf-8")


def unwrap(rig):
    """CONTROL: hand the client the raw executor's withdraw (the shape before the adapter existed)."""
    boxes = rig.parts.overworld.boxes
    raw = rig.lua.eval("function(t) return getmetatable(t).__index end")(boxes)
    boxes["withdraw"] = raw.withdraw


def withdraw_scenario(party_size, *, wrapped=True):
    rig = Rig(party(party_size))
    options(rig)
    mon = boxed_mon()
    boxed(rig, mon)
    if not wrapped:
        unwrap(rig)
    key = key_of(mon)
    with contextlib.suppress(Exception):          # the unwrapped shape raises inside the client
        rig.send_command({"cmd": "party_mon", "key": key})
    return rig, key


def retry_lines(rig):
    return [line for line in rig.log["lines"].values() if "party full, retry" in line]


def test_a_successful_withdraw_acks_exactly_once_with_no_settle():
    rig, key = withdraw_scenario(3)
    assert [m["key"] for m in rig.sent("sync_retrieve_done")] == [key]
    assert rig.sent("sync_retrieve_failed") == []
    assert rig.count() == 4                                    # the mon really is in the party
    assert len(rig.client.settle) == 0                         # Polished keeps no durable backing copy to wait on
    assert rig.client.box_save_pending is True


def test_control_the_raw_executor_shape_moves_the_mon_but_never_acks():
    rig, key = withdraw_scenario(3, wrapped=False)
    assert rig.count() == 4                                    # memory moved ...
    assert rig.sent("sync_retrieve_done") == []                # ... and the server was never told (bug 1)


def test_a_full_party_retries_then_fails_with_the_client_reason():
    rig, key = withdraw_scenario(6)
    assert len(retry_lines(rig)) == 1                          # the deferred retry ran
    (failed,) = rig.sent("sync_retrieve_failed")
    assert failed["key"] == key and failed["reason"] == "party full"
    assert rig.sent("sync_retrieve_done") == [] and rig.count() == 6


def test_control_the_raw_full_party_reason_fails_at_once_with_no_retry():
    rig, key = withdraw_scenario(6, wrapped=False)
    assert retry_lines(rig) == []                              # bug 2 reproduced
    (failed,) = rig.sent("sync_retrieve_failed")
    assert failed["reason"].startswith("party full (")


def test_an_unknown_key_refusal_passes_through_verbatim():
    rig = Rig(party(3))
    options(rig)
    rig.send_command({"cmd": "party_mon", "key": "ABCDEF:1234:010:00"})
    (failed,) = rig.sent("sync_retrieve_failed")
    assert "not boxed" in failed["reason"] and rig.sent("sync_retrieve_done") == []


def test_compose_polished_wraps_the_executor_in_the_client_adapter_once():
    assert "local boxes = Overworld.client_boxes(Overworld.boxes({" in ENTRY
    assert "move_pp = move_pp}), deps.log)" in ENTRY
    assert ENTRY.count("Overworld.boxes(") == 1


# ── the adapter itself, no emulator: its source mutated in process ──────────────────────────────────
FAKE = """
local raw = {deposit = function() return true end, memorialize = function() return nil, "not composed" end,
             extra = function() return "passthrough" end}
raw.withdraw = function(key, opts) RESULT end
return raw
"""


def adapter(result, source=OVERWORLD):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    raw = lua.execute(FAKE.replace("RESULT", result))
    module = lua.eval("function(s) return assert(load(s, '=polished_overworld'))() end")(source)
    return lua, raw, module.client_boxes(raw, None)


def test_the_adapter_returns_a_bare_true_and_normalises_only_party_full():
    _, _, boxes = adapter('return true, {box = 1, durability = "VOLATILE_UNTIL_NATIVE_SAVE"}')
    assert boxes.withdraw("k") is True                         # exactly one value
    _, _, boxes = adapter('return nil, "party full (6/6)"')
    assert tuple(boxes.withdraw("k")) == (None, "party full")
    _, _, boxes = adapter('return nil, "key not boxed"')
    assert tuple(boxes.withdraw("k")) == (None, "key not boxed")


def test_everything_but_withdraw_passes_through_to_the_executor():
    lua, raw, boxes = adapter("return true")
    same = lua.eval("function(a, b) return rawequal(a, b) end")      # lupa proxies compare by proxy, not by function
    assert same(boxes.deposit, raw.deposit) and same(boxes.memorialize, raw.memorialize)
    assert boxes.extra() == "passthrough"


MUTANTS = {
    "success hands the metadata table back": (
        "            return true\n        end\n        why = tostring(why)",
        "            return true, why\n        end\n        why = tostring(why)"),
    "success hands back a settle string": (
        "            return true\n        end\n        why = tostring(why)",
        '            return true, "x"\n        end\n        why = tostring(why)'),
    "party-full normalisation removed": (
        '            why = "party full"\n', "            why = why\n"),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_each_adapter_mutant_goes_red(name):
    old, new = MUTANTS[name]
    assert OVERWORLD.count(old) == 1, f"mutant anchor missing: {name}"
    mutated = OVERWORLD.replace(old, new)
    if "success" in name:
        _, _, boxes = adapter('return true, {box = 1}', mutated)
        assert boxes.withdraw("k") is not True
    else:
        _, _, boxes = adapter('return nil, "party full (6/6)"', mutated)
        assert tuple(boxes.withdraw("k")) != (None, "party full")
