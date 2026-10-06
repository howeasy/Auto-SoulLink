"""The special-entry probe's oracle (tools/polished_live/trade_port_probe.py) on SYNTHETIC traces: a good trace passes,
every single defect fails with its own reason, and a clean-ROM trace (original routines, no gates) is rejected.
No emulator. docs/polished/TRADE.md s13."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "trade_port_probe", Path(__file__).resolve().parents[2] / "tools/polished_live/trade_port_probe.py")
P = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(P)


def _ev(kind, **kw):
    e = {"kind": kind, "frame": 0, "pc": 0, "sp": 0xC0DC, "bank": 0x25, "room": 1, "var": 0, "sbank": 0x24,
         "spos": 0x761B, "vblank": 0, "link": 0, "running": 1, "stack": 0, "x": 5, "y": 3}
    e.update(kw)
    return e


def _number(events):
    for i, e in enumerate(events, 1):
        e["ord"] = i
        e["frame"] = 100 + 10 * i
    return events


def good_trace():
    return _number([
        _ev("gsb", spos=0x7616),
        _ev("wait_gate", bank=0x7E, pc=0x4400, sp=0xC0D0, stk="98260314"),
        _ev("wait_ret", bank=0x7E, var=1, sp=0xC0D0),
        _ev("gsb", spos=0x761B),
        _ev("try_quicksave", bank=0x0A),
        _ev("quicksave_ret", bank=0x0A, var=1),
        _ev("timeout_gate", bank=0x7E, spos=0x762C, var=1, sp=0xC0D0, stk="98260314"),
        _ev("stub", bank=0x7E, sp=0xC0CE),
        _ev("timeout_ret", bank=0x7E, sbank=0x2D, spos=0x7595, sp=0xC0D0),
        _ev("gsb", sbank=0x2D, spos=0x7595),
        _ev("endtext", sbank=0x2D, spos=0x7596),
        _ev("final", running=0, sbank=0x2D, spos=0x7596),
        _ev("move_start", running=0, x=5, y=3),
        _ev("move_end", running=0, x=5, y=4),
    ])


def clean_trace():
    return _number([
        _ev("gsb", spos=0x7616),
        _ev("orig_wait", bank=0x0A),
        _ev("orig_wait_done", bank=0x0A),
        _ev("final", running=0),
        _ev("move_start", running=0, x=5, y=3),
        _ev("move_end", running=0, x=5, y=4),
    ])


def _without(trace, kind):
    return _number([e for e in trace if e["kind"] != kind])


def _mut(trace, kind, **kw):
    out = copy.deepcopy(trace)
    next(e for e in out if e["kind"] == kind).update(kw)
    return out


def _dup(trace, kind):
    out = copy.deepcopy(trace)
    i = next(i for i, e in enumerate(out) if e["kind"] == kind)
    out.insert(i + 1, copy.deepcopy(out[i]))
    return _number(out)


def _inject(trace, event, before):
    out = copy.deepcopy(trace)
    i = next(i for i, e in enumerate(out) if e["kind"] == before)
    out.insert(i, event)
    return _number(out)


def test_good_trace_passes():
    ok, why = P.evaluate_positive(good_trace())
    assert ok, why


DEFECTS = [
    ("missing wait gate", lambda t: _without(t, "wait_gate"), "missing wait gate entry"),
    ("wait gate twice", lambda t: _dup(t, "wait_gate"), "wait gate entry hit 2 times"),
    ("wrong room", lambda t: _mut(t, "wait_gate", room=2), "wrong room"),
    ("original wait executed", lambda t: _inject(t, _ev("orig_wait", bank=0x0A), "wait_ret"),
     "original Special_WaitForLinkedFriend executed"),
    ("hScriptVar not 1", lambda t: _mut(t, "wait_ret", var=0), "wait gate returned hScriptVar 0 != 1"),
    ("stub missing", lambda t: _without(t, "stub"), "missing SlinkTradeEntry stub entry"),
    ("redirect cursor wrong at return", lambda t: _mut(t, "timeout_ret", spos=0x7596), "redirect cursor"),
    ("redirect not read by interpreter",
     lambda t: _number([e for e in t if not (e["kind"] == "gsb" and e["sbank"] == 0x2D)]), "redirect cursor"),
    ("endtext never hit", lambda t: _without(t, "endtext"), "Script_endtext never hit"),
    ("player did not move", lambda t: _mut(t, "move_end", y=3), "player did not move"),
    ("script stack not empty", lambda t: _mut(t, "final", stack=1), "wScriptStackSize 1 != 0"),
    ("original timeout executed", lambda t: _inject(t, _ev("orig_timeout", bank=0x0A), "timeout_ret"),
     "original Special_CheckLinkTimeout executed"),
    ("vblank mode left set", lambda t: _mut(t, "final", vblank=3), "hVBlank 3 != 0"),
    ("link mode left set", lambda t: _mut(t, "final", link=1), "wLinkMode 1 != 0"),
    ("script still running", lambda t: _mut(t, "final", running=1), "wScriptRunning 1 != 0"),
    ("gate return address wrong", lambda t: _mut(t, "wait_gate", stk="00000314"), "not _ReturnFarCall"),
    ("stub not called from the gate", lambda t: _mut(t, "stub", sp=0xC0D0), "not called from the gate"),
    ("wait gate wrong cursor", lambda t: _mut(t, "wait_gate", spos=0x7000), "wait gate script cursor"),
    ("unbalanced stack at return", lambda t: _mut(t, "wait_ret", sp=0xC0D2), "stack unbalanced"),
    ("quick-save var 0", lambda t: _mut(t, "quicksave_ret", var=0), "quick-save returned hScriptVar 0 != 1"),
    ("quick-save changed the room", lambda t: _mut(t, "quicksave_ret", room=0), "quick-save left wChosenCableClubRoom"),
    ("PerformLinkChecks entered", lambda t: _inject(t, _ev("perform_link_checks", bank=0x0A), "endtext"),
     "PerformLinkChecks executed"),
    ("room entry read", lambda t: _inject(t, _ev("gsb", spos=0x770E), "endtext"), "link room entry"),
    ("events out of order", lambda t: _number([t[i] for i in (0, 2, 1) + tuple(range(3, len(t)))]), "out of order"),
]


@pytest.mark.parametrize(("name", "mutate", "needle"), DEFECTS, ids=[d[0] for d in DEFECTS])
def test_single_defect_is_rejected_with_its_reason(name, mutate, needle):
    ok, why = P.evaluate_positive(mutate(good_trace()))
    assert not ok, name
    assert any(needle in r for r in why), (needle, why)


def test_clean_rom_trace_is_rejected_by_the_positive_oracle():
    ok, why = P.evaluate_positive(clean_trace())
    assert not ok
    for needle in ("missing wait gate entry", "missing SlinkTradeEntry stub entry", "redirect cursor",
                   "original Special_WaitForLinkedFriend executed"):
        assert any(needle in r for r in why), (needle, why)


def test_clean_control_passes_only_when_the_oracle_rejects_and_the_original_wait_ran():
    ok, notes = P.evaluate_clean(clean_trace())
    assert ok, notes
    ok, why = P.evaluate_clean(good_trace())          # a gated trace is not a clean-ROM trace
    assert not ok and any("original wait entry" in r for r in why)
    slow = _mut(clean_trace(), "orig_wait_done", frame=100 + 20 + P.ORIG_WAIT_BUDGET + 5)
    assert not P.evaluate_clean(slow)[0]


def _battle_trace():
    return _number([
        _ev("gsb", spos=0x7616),
        _ev("wait_gate", bank=0x7E, room=2),
        _ev("orig_wait", bank=0x0A, room=2),
        _ev("orig_wait_done", bank=0x0A, room=2),
        _ev("final", running=0),
    ])


def _battle_with(**kw):
    t = _battle_trace()
    t[3]["frame"] = t[2]["frame"] + kw.pop("span", 513)
    return t


def test_battle_control():
    assert P.evaluate_battle(_battle_with())[0]
    ok, why = P.evaluate_battle(_battle_with(span=P.ORIG_WAIT_BUDGET + 1))
    assert not ok and any("timeout" in r for r in why)
    ok, why = P.evaluate_battle(_mut(_battle_trace(), "wait_gate", room=1))
    assert not ok and any("chosen room 1 != 2" in r for r in why)
    ok, why = P.evaluate_battle(_without(_battle_trace(), "orig_wait"))
    assert not ok and any("original Special_WaitForLinkedFriend entry" in r for r in why)
    ok, why = P.evaluate_battle(_inject(_battle_trace(), _ev("stub", bank=0x7E), "final"))
    assert not ok and any("stub" in r for r in why)


def _decline_trace():
    return _number([
        _ev("gsb", spos=0x7616),
        _ev("wait_gate", bank=0x7E),
        _ev("wait_ret", bank=0x7E, var=1),
        _ev("answer", btn="B", which=2),
        _ev("gsb", spos=0x7689),
        _ev("wait_exit", bank=0x0A),
        _ev("final", running=0),
    ])


def test_decline_control():
    assert P.evaluate_decline(_decline_trace())[0]
    for kind, needle in (("try_quicksave", "Special_TryQuickSave"), ("timeout_gate", "timeout gate"),
                         ("stub", "stub")):
        ok, why = P.evaluate_decline(_inject(_decline_trace(), _ev(kind, bank=0x7E), "final"))
        assert not ok and any(needle in r for r in why), (kind, why)
    ok, why = P.evaluate_decline(_mut(_decline_trace(), "answer", btn="A"))
    assert not ok and any("answered with B" in r for r in why)
    ok, why = P.evaluate_decline(_without(_decline_trace(), "wait_exit"))
    assert not ok and any("WaitForOtherPlayerToExit" in r for r in why)
