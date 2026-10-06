"""Read-only rival gate oracle/runner tests: synthetic traces and ROMs, no emulator.

Lua is compiled using lupa's Lua 5.5 load, never executed. Live callback-PC semantics
remain OPEN until an owner-authorized played run produces bank-qualified evidence.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "rival_gate_probe", REPO / "tools/polished_live/rival_gate_probe.py")
P = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(P)


def hit(kind="gate", **fields):
    addr = P.HOOKS[kind]
    row = {"kind": kind, "hook_addr": addr, "pc": addr, "sp": 0xC0DC, "bank": 15,
           "matched": True, "mode": 2, "trainer_class": 9, "trainer_id": 1,
           "cur_ot_mon": 0, "cur_party_mon": 0, "ot_party_count": 3,
           "site_bytes": "218bd2fa0cd1", "hook_bytes": "218bd2fa0cd1"}
    row.update(fields)
    return row


def complete(events):
    rows = copy.deepcopy(events) + [{"kind": "final", "completed": True,
                                     "guest_writes": 0, "cpu_changes": 0}]
    for i, row in enumerate(rows, 1):
        row.update(ord=i, frame=100 + i)
    return rows


def good_trace():
    return complete([hit(), hit("next"), hit("last")])


def test_good_trace_passes():
    assert P.evaluate(good_trace()) == (True, [])
    assert P.verdict([]) == "PASS"


def test_gate_alone_satisfies_optional_sibling_hits():
    assert P.evaluate(complete([hit()])) == (True, [])


@pytest.mark.parametrize(("event", "reason"), [
    (hit(pc=0x47E0), "PC_IS_NEXT_INSTRUCTION"),
    (hit(pc=0x480D), "PC_OTHER"),
    (hit(pc=None), "PC_OTHER"),
    (hit(bank=0x10), "WRONG_BANK_HIT"),
    (hit(matched=False), "WRONG_BANK_HIT"),
    (hit(matched=1), "WRONG_BANK_HIT"),
    (hit(cur_ot_mon=1, cur_party_mon=0), "BAD_SELECTED_INDEX"),
    (hit(cur_ot_mon=3, cur_party_mon=3), "BAD_SELECTED_INDEX"),
    (hit(cur_ot_mon=-1, cur_party_mon=-1), "BAD_SELECTED_INDEX"),
    (hit(ot_party_count=0), "BAD_SELECTED_INDEX"),
    (hit(ot_party_count=7), "BAD_SELECTED_INDEX"),
    (hit(cur_ot_mon=None), "BAD_SELECTED_INDEX"),
    (hit(cur_ot_mon=False), "BAD_SELECTED_INDEX"),
    (hit(mode=1), "NOT_TRAINER_BATTLE"),
    (hit(site_bytes="228bd2fa0cd1"), "SITE_BYTES_MISMATCH"),
    (hit(site_bytes="218bd2"), "SITE_BYTES_MISMATCH"),
    (hit(site_bytes="not hex"), "SITE_BYTES_MISMATCH"),
    (hit(site_bytes=None), "SITE_BYTES_MISMATCH"),
    (hit(hook_addr=0x47E0), "HOOK_ADDRESS"),
])
def test_each_gate_defect_fails_with_specific_reason(event, reason):
    ok, reasons = P.evaluate(complete([event]))
    assert not ok
    assert any(r.startswith(reason + ":") for r in reasons), reasons


def test_every_qualified_gate_must_agree_not_just_first():
    ok, reasons = P.evaluate(complete([hit(), hit(pc=0x47E0)]))
    assert not ok
    assert P.verdict(reasons) == "PC_IS_NEXT_INSTRUCTION"
    assert any("0x47e0" in r for r in reasons)


def test_other_pc_verdict_carries_observed_value():
    ok, reasons = P.evaluate(complete([hit(pc=0x1234)]))
    assert not ok
    assert P.verdict(reasons) == "PC_OTHER"
    assert any("0x1234" in r for r in reasons)


@pytest.mark.parametrize("events", [[], [hit("last")], [hit("next"), hit("last")],
                                    [hit(bank=0x10, matched=False)]])
def test_zero_qualified_gate_hits_are_open_not_pass(events):
    ok, reasons = P.evaluate(complete(events))
    assert not ok
    assert P.verdict(reasons) == "NO_GATE_HIT"
    assert any("OPEN" in r for r in reasons)


def test_wrong_bank_callbacks_are_not_counted_or_pc_checked():
    trace = complete([hit(bank=0x10, matched=False, pc=0x1234), hit()])
    assert P.evaluate(trace) == (True, [])


def test_optional_next_callback_pc_must_be_own_address():
    ok, reasons = P.evaluate(complete([hit(), hit("next", pc=0x47E1)]))
    assert not ok
    assert any(r.startswith("NEXT_PC_MISMATCH:") for r in reasons)


@pytest.mark.parametrize(("kind", "reason"), [("guest_write", "GUEST_WRITE"),
                                               ("cpu_change", "CPU_CHANGE"),
                                               ("overflow", "TRACE_OVERFLOW"),
                                               ("driver_error", "DRIVER_ERROR")])
def test_mutation_and_censored_recordings_fail(kind, reason):
    ok, reasons = P.evaluate(complete([hit(), {"kind": kind}]))
    assert not ok
    assert any(r.startswith(reason + ":") for r in reasons)


def test_missing_final_cannot_pass_even_with_good_gate():
    ok, reasons = P.evaluate([hit()])
    assert not ok
    assert any(r.startswith("INCOMPLETE_TRACE:") for r in reasons)


@pytest.mark.parametrize("field", ["guest_writes", "cpu_changes"])
def test_mutation_counter_fails_even_if_event_is_missing(field):
    trace = good_trace()
    trace[-1][field] = 1
    ok, reasons = P.evaluate(trace)
    assert not ok
    assert any(r.startswith("PROBE_MUTATION:") for r in reasons)


@pytest.mark.parametrize("trace", [None, {}, [None], ["gate"]])
def test_malformed_trace_fails_closed(trace):
    assert P.evaluate(trace) == (False, ["INVALID_TRACE: expected a list of event objects"])


def route_file(tmp_path, data):
    path = tmp_path / "route.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_native_route_parsing_and_exact_frame_boundary(tmp_path):
    steps = [{"frames": 3, "buttons": []}, {"frames": 2, "buttons": ["Up", "A"]}]
    assert P.parse_route(route_file(tmp_path, {"steps": steps}), 5) == steps
    assert P.parse_route(None, 5) == []


@pytest.mark.parametrize("data", [
    [], {"steps": {}}, {"steps": [], "warp": [20, 1]},
    {"steps": [{"frames": 1, "buttons": [], "write": [0xD235, 9]}]},
    {"steps": [{"frames": 0, "buttons": []}]},
    {"steps": [{"frames": -1, "buttons": []}]},
    {"steps": [{"frames": True, "buttons": []}]},
    {"steps": [{"frames": 1.5, "buttons": []}]},
    {"steps": [{"frames": 1, "buttons": "A"}]},
    {"steps": [{"frames": 1, "buttons": ["Reset"]}]},
    {"steps": [{"frames": 1, "buttons": ["A", "A"]}]},
    {"steps": [{"frames": 1, "buttons": [{}]}]},
])
def test_route_rejects_invalid_or_synthetic_steps(tmp_path, data):
    with pytest.raises(ValueError):
        P.parse_route(route_file(tmp_path, data), 10)


def test_route_cannot_overrun_observation_bound(tmp_path):
    path = route_file(tmp_path, {"steps": [{"frames": 11, "buttons": []}]})
    with pytest.raises(ValueError, match="exceeds --frames"):
        P.parse_route(path, 10)


def test_argument_validation_accepts_played_fixture_and_route(tmp_path):
    fixture = tmp_path / "native.SaveRAM"
    fixture.write_bytes(b"native fixture")
    route = route_file(tmp_path, {"steps": [{"frames": 3, "buttons": ["Start"]}]})
    args = P.parse_args(["--setup", "played", "--fixture", str(fixture), "--route", str(route), "--frames", "3"])
    assert args.fixture == fixture
    assert args.steps == [{"frames": 3, "buttons": ["Start"]}]


@pytest.mark.parametrize("extra", [[], ["--setup", "synthetic"], ["--frames", "0"],
                                    ["--trace-cap", "0"], ["--timeout", "-1"]])
def test_arguments_reject_missing_setup_synthetic_or_unbounded_run(tmp_path, extra):
    fixture = tmp_path / "native.SaveRAM"
    fixture.write_bytes(b"fixture")
    prefix = [] if not extra else ["--setup", "played"]
    with pytest.raises(SystemExit) as exc:
        P.parse_args(prefix + ["--fixture", str(fixture)] + extra)
    assert exc.value.code == 2


def test_missing_fixture_is_argument_error(tmp_path):
    with pytest.raises(SystemExit) as exc:
        P.parse_args(["--setup", "played", "--fixture", str(tmp_path / "missing.SaveRAM")])
    assert exc.value.code == 2


def test_bad_route_is_argument_error(tmp_path):
    fixture = tmp_path / "native.SaveRAM"
    fixture.write_bytes(b"fixture")
    route = route_file(tmp_path, {"steps": [{"frames": 4, "buttons": []}]})
    with pytest.raises(SystemExit) as exc:
        P.parse_args(["--setup", "played", "--fixture", str(fixture), "--route", str(route), "--frames", "3"])
    assert exc.value.code == 2


def synthetic_rom(site=b"\x21\x8b\xd2\xfa\x0c\xd1"):
    rom = bytearray(16 * 0x4000)
    offset = 15 * 0x4000 + 0x47DD - 0x4000
    rom[offset:offset + len(site)] = site
    return bytes(rom)


def test_pinned_rom_site_is_bank_qualified():
    rom = bytearray(synthetic_rom())
    rom[0x47DD:0x47DD + 3] = b"bad"  # unqualified/raw-address access must not be used
    assert P.check_site_bytes(bytes(rom)) == "218bd2fa0cd1"


@pytest.mark.parametrize("rom", [synthetic_rom(b"\x22\x8b\xd2\xfa\x0c\xd1"), b"", synthetic_rom()[:247776]])
def test_staged_site_mismatch_or_truncation_prevents_launch(rom):
    with pytest.raises(ValueError, match="pinned prefix"):
        P.check_site_bytes(rom)


@pytest.mark.parametrize("text", ["", "crashed", "RESULT: FAIL rival-gate-probe recording (1 checks failed)",
                                   "RESULT: PASS another-probe", "RESULT: PASS rival-gate-probe recording x\nRESULT: PASS rival-gate-probe recording x"])
def test_missing_failed_or_ambiguous_result_fails_closed(text):
    assert P.recording_reasons(text)[0].startswith("INCOMPLETE_RECORDING:")


def test_successful_recording_marker_does_not_override_zero_hits():
    assert P.recording_reasons("RESULT: PASS rival-gate-probe recording (0 checks failed) frame 12000") == []
    ok, reasons = P.evaluate(complete([]))
    assert not ok
    assert P.verdict(reasons) == "NO_GATE_HIT"


@pytest.mark.parametrize("elapsed", [600, 601])
def test_late_successful_result_is_still_a_deadline_failure(elapsed):
    text = "RESULT: PASS rival-gate-probe recording (0 checks failed) frame 12000"
    reasons = P.recording_reasons(text, elapsed, 600)
    assert any(r.startswith("DEADLINE:") for r in reasons)


def test_result_before_deadline_is_eligible_for_oracle():
    text = "RESULT: PASS rival-gate-probe recording (0 checks failed) frame 12000"
    assert P.recording_reasons(text, 599, 600) == []


def test_lua55_loads_driver_without_executing_it():
    from lupa.lua55 import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    load = lua.eval("function(source) local fn, err = load(source, '@rival_gate_probe.lua'); return fn ~= nil, err end")
    source = (REPO / "tools/polished_live/rival_gate_probe.lua").read_text(encoding="utf-8")
    ok, error = load(source)
    assert ok, error
