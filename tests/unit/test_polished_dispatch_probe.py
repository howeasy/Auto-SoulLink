"""D3 synthetic dispatcher measurements: no emulator; Lua 5.5 compile-only, no execution."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("dispatch_probe", REPO / "tools/polished_live/dispatch_probe.py")
P = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(P)


def symbols():
    rows = {"SlinkTradeDispatch": (0x7E, 0x4700), "SlinkTradePromptEntry": (0x7E, 0x4780),
            "NextOverworldFrame": (0x25, 0x5185), "NextOverworldFrame.gfx_done": (0x25, 0x51BC),
            "DelayFrame": (0, 0x0DA8), "HandleMap": (0x25, 0x5156),
            "OverworldLoop.loop": (0x25, 0x50D9), "hROMBank": (0, 0xFF87)}
    rows.update({s: (0, 0xC100 + i) for i, s in enumerate(P.FIELDS.values())})
    return rows


PINS = P.derive_contract(symbols())["pins"]


def image(mismatch=False, noise=False):
    stack = bytearray(28)
    for pin in PINS:
        stack[pin["offset"]] = pin["value"]
    if mismatch:
        stack[24] ^= 1
    if noise:
        stack[16] ^= 0xFF
    return stack.hex()


def hit(phase="idle", kind="dispatch", mismatch=False, **fields):
    addr = P.DISPATCH if kind == "dispatch" else P.PROMPT
    row = {"kind": kind, "phase": phase, "pc": addr, "hook_addr": addr, "sp": 0xC0D2,
           "bank": 0x7E, "matched": True, "qualified": True, "stack": image(mismatch),
           "svbk": 1, "script_mode": 0, "battle_mode": 0, "link_mode": 0, "paused": 0,
           "in_menu": 0, "vblank": 0, "map_status": 2, "step_flags": 0, "map_event_status": 0}
    row.update(fields)
    row["stack_match"] = P.stack_matches(bytes.fromhex(row["stack"]), PINS)
    row["engine_clean"] = P.engine_clean(row)
    row["context_accept"] = row["qualified"] and row["stack_match"] and row["engine_clean"]
    return row


def complete(events):
    rows = copy.deepcopy(events)
    rows.append({"kind": "final", "completed": True, "guest_writes": 0, "cpu_changes": 0,
                 "prompt_hits": sum(e.get("kind") == "prompt" and e.get("qualified") is True for e in rows),
                 "dispatch_hits": sum(e.get("kind") == "dispatch" and e.get("qualified") is True for e in rows),
                 "phase_frames": dict.fromkeys(P.REQUIRED_PHASES, 10), "elapsed": 40})
    for i, e in enumerate(rows, 1):
        e.update(ord=i, frame=100 + i)
    return rows


def good_trace():
    return complete([hit(), hit("walking", step_flags=0x20), hit("start_menu", in_menu=1),
                     hit("npc_talk", mismatch=True), hit("battle", battle_mode=1)])


def test_good_trace_passes():
    assert P.evaluate(good_trace(), PINS) == (True, [])
    assert P.verdict([]) == "PASS"


@pytest.mark.parametrize("phase", ["idle", "walking"], ids=["idle", "walking"])
def test_clean_positive_stack_mismatch_reports_full_image(phase):
    trace = good_trace()
    trace[0 if phase == "idle" else 1] = hit(phase, mismatch=True)
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert P.verdict(reasons) == "STACK_MISMATCH_IDLE"
    assert any(image(True) in r for r in reasons)


@pytest.mark.parametrize("phase", ["start_menu", "npc_talk", "battle"], ids=["start", "talk", "battle"])
def test_negative_clean_fingerprint_is_first_falsifier(phase):
    trace = good_trace()
    trace.insert(-1, hit(phase))
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert P.verdict(reasons) == "NEGATIVE_ACCEPTED"
    assert any(phase in r and image() in r for r in reasons)


@pytest.mark.parametrize("events", [[], [hit(bank=0x25, matched=False, qualified=False)]], ids=["zero", "wrong-bank-only"])
def test_zero_qualified_hits_are_open_not_pass(events):
    ok, reasons = P.evaluate(complete(events), PINS)
    assert not ok
    assert P.verdict(reasons) == "NO_HIT"


def test_wrong_bank_negative_is_not_counted_as_acceptance():
    trace = good_trace()
    trace.insert(-1, hit("npc_talk", bank=0x25, matched=False, qualified=False))
    assert P.evaluate(trace, PINS) == (True, [])
    assert sum(r["count"] for r in P.distribution(trace)) == 5


def test_mislabeled_bank_match_fails():
    trace = good_trace()
    trace.insert(-1, hit(bank=0x25))
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert P.verdict(reasons) == "FAIL"
    assert any("qualification" in r for r in reasons)


def test_next_instruction_pc_is_not_dispatch_entry_measurement():
    trace = good_trace()
    trace.insert(-1, hit(pc=P.DISPATCH + 2, qualified=False))
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert any(r.startswith("CALLBACK_PC:") for r in reasons)


@pytest.mark.parametrize("kind", ["overflow", "guest_write", "cpu_change", "driver_error"],
                         ids=["overflow", "write", "register", "driver-error"])
def test_incomplete_or_mutating_probe_fails(kind):
    trace = good_trace()
    trace.insert(-1, {"kind": kind})
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert P.verdict(reasons) == "FAIL"


def test_prompt_path_must_not_execute_without_published_lease():
    trace = complete([hit(), hit("walking"), hit(kind="prompt")])
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert any(r.startswith("PROMPT_ENTRY:") for r in reasons)


@pytest.mark.parametrize(("field", "value"), [
    ("svbk", 2), ("script_mode", 1), ("battle_mode", 1), ("link_mode", 1), ("paused", 1),
    ("in_menu", 1), ("vblank", 1), ("map_status", 0), ("step_flags", 0x20), ("map_event_status", 1),
], ids=["svbk", "script", "battle", "link", "paused", "menu", "vblank", "map", "midstep", "events"])
def test_each_engine_guard_refuses_negative_context(field, value):
    trace = good_trace()
    trace.insert(-1, hit("npc_talk", **{field: value}))
    assert P.evaluate(trace, PINS) == (True, [])


def test_unpinned_noise_and_masked_engine_bits_do_not_change_eligibility():
    trace = complete([hit(stack=image(noise=True), svbk=0xF9, step_flags=0xDF), hit("walking")])
    assert P.evaluate(trace, PINS) == (True, [])


def test_cannot_forge_lua_stack_match_boolean():
    trace = good_trace()
    trace[0]["stack_match"] = False
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert any("booleans" in r for r in reasons)


@pytest.mark.parametrize("trace", [None, {}, [None], ["dispatch"]], ids=["null", "object", "null-row", "string-row"])
def test_malformed_top_level_fails(trace):
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert P.verdict(reasons) == "FAIL"


@pytest.mark.parametrize(("field", "value"), [("stack", "00"), ("stack", "not hex"), ("phase", []),
                                               ("sp", None), ("svbk", None), ("battle_mode", False)],
                         ids=["short-stack", "bad-hex", "bad-phase", "missing-sp", "missing-guard", "bool-guard"])
def test_malformed_sample_fails_closed(field, value):
    trace = good_trace()
    trace[0][field] = value
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert any(r.startswith("MALFORMED:") for r in reasons)


def test_missing_final_or_missing_phase_cannot_pass():
    trace = good_trace()
    assert not P.evaluate(trace[:-1], PINS)[0]
    del trace[-1]["phase_frames"]["npc_talk"]
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert any(r.startswith("INCOMPLETE_PHASES:") for r in reasons)


def test_negatives_may_have_no_entry_but_must_have_played_frames():
    assert P.evaluate(complete([hit(), hit("walking")]), PINS) == (True, [])


def test_stack_distribution_counts_images_per_phase_and_sp():
    trace = complete([hit(), hit(), hit(stack=image(noise=True)), hit("walking")])
    rows = P.distribution(trace)
    assert len(rows) == 3
    assert next(r["count"] for r in rows if r["phase"] == "idle" and r["stack"] == image()) == 2


def test_pins_follow_symbols_instead_of_copied_stack_values():
    changed = symbols()
    changed["DelayFrame"] = (0, 0x1020)
    changed["NextOverworldFrame.gfx_done"] = (0x25, 0x5200)
    pins = {p["offset"]: p["value"] for p in P.derive_contract(changed)["pins"]}
    assert pins[12] == 0x23 and pins[13] == 0x10
    assert pins[14] == 0x06 and pins[15] == 0x52
    assert tuple(pins) == P.PIN_OFFSETS


def route_steps():
    return [{"phase": "setup", "frames": 2, "buttons": ["A"]},
            {"phase": "idle", "frames": 2, "buttons": []},
            {"phase": "walking", "frames": 2, "buttons": ["Up"]},
            {"phase": "start_menu", "frames": 2, "buttons": ["Start"]},
            {"phase": "npc_talk", "frames": 2, "buttons": ["A"]}]


def write_route(tmp_path, steps):
    path = tmp_path / "route.json"
    path.write_text(json.dumps({"steps": steps}), encoding="utf-8")
    return path


def test_route_accepts_phased_timed_native_input(tmp_path):
    steps = route_steps()
    assert P.parse_route(write_route(tmp_path, steps), 10) == steps


@pytest.mark.parametrize(("field", "value"), [("phase", "synth"), ("phase", []), ("frames", 0),
                                               ("frames", True), ("buttons", ["Reset"]),
                                               ("buttons", ["A", "A"]), ("buttons", [{}])],
                         ids=["unknown-phase", "list-phase", "zero-frames", "bool-frames", "reset", "duplicate", "object-button"])
def test_route_rejects_invalid_steps(tmp_path, field, value):
    steps = route_steps()
    steps[0][field] = value
    with pytest.raises(ValueError):
        P.parse_route(write_route(tmp_path, steps), 10)


def test_route_rejects_synthetic_fields_missing_phases_and_overrun(tmp_path):
    steps = route_steps()
    steps[0]["write"] = [0xC100, 1]
    with pytest.raises(ValueError, match="only phase"):
        P.parse_route(write_route(tmp_path, steps), 10)
    with pytest.raises(ValueError, match="missing required"):
        P.parse_route(write_route(tmp_path, route_steps()[:-1]), 10)
    with pytest.raises(ValueError, match="exceeds --frames"):
        P.parse_route(write_route(tmp_path, route_steps()), 9)


def test_route_labels_cannot_call_pressed_buttons_idle(tmp_path):
    steps = route_steps()
    steps[1]["buttons"] = ["A"]
    with pytest.raises(ValueError, match="release all"):
        P.parse_route(write_route(tmp_path, steps), 10)
    steps = route_steps()
    steps[2]["buttons"] = []
    with pytest.raises(ValueError, match="hold a direction"):
        P.parse_route(write_route(tmp_path, steps), 10)


def test_dry_run_is_read_only_and_not_measurement_pass(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "native.SaveRAM"
    fixture.write_bytes(b"fixture")
    route = write_route(tmp_path, route_steps())
    lane = tmp_path / "must-not-exist"
    monkeypatch.setattr(P, "WORK", lane)
    before_env, before_path = dict(os.environ), list(sys.path)
    before_files = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert P.main(["--fixture", str(fixture), "--route", str(route), "--frames", "10", "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True and plan["measurement_verdict"] is None
    assert not lane.exists()
    assert dict(os.environ) == before_env and sys.path == before_path
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before_files


@pytest.mark.parametrize("option", ["--frames", "--trace-cap", "--timeout"], ids=["frames", "cap", "timeout"])
def test_cli_rejects_nonpositive_bounds(tmp_path, option):
    fixture = tmp_path / "native.SaveRAM"
    fixture.write_bytes(b"fixture")
    route = write_route(tmp_path, route_steps())
    with pytest.raises(SystemExit) as exc:
        P.parse_args(["--fixture", str(fixture), "--route", str(route), option, "0"])
    assert exc.value.code == 2


def test_missing_result_and_late_result_fail_closed():
    assert P.recording_reasons("", 1, 600)
    text = "RESULT: PASS dispatch-probe recording (0 checks failed) frame 40"
    assert P.recording_reasons(text, 599, 600) == []
    assert P.recording_reasons(text, 600, 600)[0].startswith("DEADLINE:")


@pytest.mark.parametrize("offset", P.PIN_OFFSETS, ids=[f"sp{n}" for n in P.PIN_OFFSETS])
def test_each_of_nine_pinned_bytes_is_load_bearing(offset):
    stack = bytearray.fromhex(image())
    stack[offset] ^= 1
    trace = complete([hit(stack=stack.hex()), hit("walking")])
    ok, reasons = P.evaluate(trace, PINS)
    assert not ok
    assert P.verdict(reasons) == "STACK_MISMATCH_IDLE"


NOISE_OFFSETS = [n for n in range(28) if n not in P.PIN_OFFSETS]


@pytest.mark.parametrize("offset", NOISE_OFFSETS, ids=[f"noise{n}" for n in NOISE_OFFSETS])
def test_every_unpinned_byte_is_masked(offset):
    stack = bytearray.fromhex(image())
    stack[offset] ^= 0xFF
    assert P.evaluate(complete([hit(stack=stack.hex()), hit("walking")]), PINS) == (True, [])


@pytest.mark.parametrize("phase", ["start_menu", "npc_talk"], ids=["start", "talk"])
def test_negative_route_must_include_the_native_trigger(tmp_path, phase):
    steps = route_steps()
    next(s for s in steps if s["phase"] == phase)["buttons"] = []
    with pytest.raises(ValueError, match="native"):
        P.parse_route(write_route(tmp_path, steps), 10)


def test_corrupt_stack_cannot_break_distribution_reporting():
    trace = good_trace()
    trace[0]["stack"] = {}
    trace[1]["phase"] = []
    rows = P.distribution(trace)
    assert len(rows) == 3


def synthetic_rom():
    rom = bytearray(128 * 0x4000)
    offset = P.BANK * 0x4000 + P.DISPATCH - 0x4000
    rom[offset:offset + 5] = bytes((0xF8, 5, 0x7E, 0xFE, 0x25))
    rom[P.BANK * 0x4000 + P.PROMPT - 0x4000] = 0xC9
    return rom


def test_staged_entry_bytes_are_bank_qualified():
    rom = synthetic_rom()
    rom[P.DISPATCH:P.DISPATCH + 5] = b"wrong"
    P.check_rom(bytes(rom), P.derive_contract(symbols()))


@pytest.mark.parametrize("site", ["dispatch", "prompt"], ids=["dispatch", "prompt"])
def test_staged_entry_or_stub_drift_prevents_launch(site):
    rom = synthetic_rom()
    addr = P.DISPATCH if site == "dispatch" else P.PROMPT
    rom[P.BANK * 0x4000 + addr - 0x4000] ^= 1
    with pytest.raises(ValueError):
        P.check_rom(bytes(rom), P.derive_contract(symbols()))


def test_lua55_compiles_without_running_driver():
    from lupa.lua55 import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    load = lua.eval("function(source) local fn, err = load(source, '@dispatch_probe.lua'); return fn ~= nil, err end")
    source = (REPO / "tools/polished_live/dispatch_probe.lua").read_text(encoding="utf-8")
    ok, error = load(source)
    assert ok, error
