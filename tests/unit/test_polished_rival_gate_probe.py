"""Read-only rival gate oracle/runner tests: synthetic traces and ROMs, no emulator.

Lua tests also execute the read-only driver against mocked emulator APIs. Native
callback-PC semantics remain OPEN until an owner-authorized played run produces evidence.
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
    row.setdefault("qualified", row["bank"] == P.BANK and row["pc"] == addr)
    return row


def complete(events):
    counts = {name: {"total": 0, "qualified": 0, "wrong_pc": 0,
                     "wrong_banks": {}, "wrong_bank_samples": 0} for name in P.HOOKS}
    for row in events:
        if row.get("kind") not in counts:
            continue
        c = counts[row["kind"]]
        c["total"] += 1
        if row["bank"] != P.BANK:
            bank = str(row["bank"])
            c["wrong_banks"][bank] = c["wrong_banks"].get(bank, 0) + 1
            c["wrong_bank_samples"] += 1
        elif row["pc"] == P.HOOKS[row["kind"]]:
            c["qualified"] += 1
        else:
            c["wrong_pc"] += 1
    rows = copy.deepcopy(events) + [{"kind": "final", "completed": True,
                                     "guest_writes": 0, "cpu_changes": 0, "driver_errors": 0,
                                     "hook_hits": sum(c["total"] for c in counts.values()),
                                     "wrong_bank_sample_limit": 16, "hook_counts": counts}]
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


@pytest.mark.parametrize("rom", [synthetic_rom(b"\x22\x8b\xd2\xfa\x0c\xd1"), b"", synthetic_rom()[:247776]],
                         ids=["wrong-site-bytes", "empty", "truncated"])  # ids: ROM images overflow pytest's env var
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


def _lua_value(value):
    """Match the production encoder's empty-table-as-array representation."""
    if not hasattr(value, "items"):
        return value
    items = dict(value.items())
    if set(items) == set(range(1, len(items) + 1)):
        return [_lua_value(items[i]) for i in range(1, len(items) + 1)]
    return {key: _lua_value(item) for key, item in items.items()}


MOCK_DRIVER = r"""
local frame, bank, pc = 0, 15, 0x47DD
local hooks = {}
output, finished, recording_ok = nil, false, nil
os.getenv = function() return "mock" end
emu = {
    framecount = function() return frame end,
    getregister = function(name) return name == "PC" and pc or 0xC0DC end,
}
client = {speedmode = function() end}
local gate_offset = 15 * 0x4000 + 0x47DD - 0x4000
local gate_bytes = {0x21, 0x8B, 0xD2, 0xFA, 0x0C, 0xD1}
memory = {read_u8 = function(addr)
    return gate_bytes[addr - gate_offset + 1] or 0
end}
local L = {
    RUN = "mock",
    slurp = function() return "config" end,
    bus = function() return bank end,
    rw = function(name)
        if name == "wBattleMode" then return 2 end
        if name == "wOTPartyCount" then return 3 end
        return 0
    end,
    hex = function(bytes)
        local out = {}
        for _, byte in ipairs(bytes) do out[#out + 1] = string.format("%02x", byte) end
        return table.concat(out)
    end,
    hook_at = function(name, expected_bank, addr, callback)
        assert(expected_bank == 15)
        hooks[#hooks + 1] = {addr = addr, callback = callback}
    end,
    check = function(_, ok) recording_ok = ok end,
    finish = function() finished = true end,
}
L.json = {
    decode = function() return {steps = {}, frames = 1, trace_cap = mock_cap} end,
    encode = function(trace)
        if encoder_mode == "nil" then return nil end
        if encoder_mode == "throw" then error('encoder "failed"\nagain', 0) end
        return encode_trace(trace)
    end,
}
L.frame = function()
    frame = frame + 1
    for _, hook in ipairs(hooks) do
        for i = 1, wrong_callbacks do
            bank, pc = (i % 2 == 0 and 16 or 17), 0x1234
            hook.callback(false)
        end
        bank, pc = 15, hook.addr
        hook.callback(true)
    end
    if wrong_pc then
        bank, pc = 15, 0x47E0
        hooks[1].callback(true)
    end
    if frame_error then error('driver "failed"\nagain', 0) end
end
dofile = function() return L end
io.open = function()
    return {
        write = function(self, text)
            assert(type(text) == "string", "write must receive JSON text")
            output = text
            return self
        end,
        close = function() end,
    }
end
"""


def run_mock_driver(*, encoder="normal", callbacks=7001, wrong_pc=False, cap=5, frame_error=False):
    from lupa.lua55 import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    globals_ = lua.globals()
    globals_.encoder_mode = encoder
    globals_.wrong_callbacks = callbacks
    globals_.wrong_pc = wrong_pc
    globals_.mock_cap = cap
    globals_.frame_error = frame_error
    globals_.encode_trace = lambda value: json.dumps(_lua_value(value))
    lua.execute(MOCK_DRIVER)
    lua.execute((REPO / "tools/polished_live/rival_gate_probe.lua").read_text(encoding="utf-8"))
    assert globals_.finished is True
    return json.loads(globals_.output), globals_.recording_ok


def test_wrong_bank_flood_preserves_qualified_rows_and_exact_callback_totals():
    trace, recorded = run_mock_driver()
    assert recorded is True
    final = trace[-1]
    assert final["wrong_bank_sample_limit"] == 16
    assert final["hook_hits"] == 3 * 7002
    for name in P.HOOKS:
        rows = [row for row in trace if row["kind"] == name]
        samples = [row for row in rows if row["matched"] is False]
        qualified = [row for row in rows if row["qualified"] is True]
        assert len(samples) == 16
        assert len(qualified) == 1
        assert qualified[0]["pc"] == P.HOOKS[name]
        assert qualified[0]["hook_addr"] == P.HOOKS[name] and qualified[0]["bank"] == P.BANK
        assert qualified[0]["mode"] == 2 and qualified[0]["cur_ot_mon"] == 0
        assert qualified[0]["site_bytes"] == "218bd2fa0cd1"
        assert final["hook_counts"][name] == {
            "total": 7002, "qualified": 1, "wrong_pc": 0,
            "wrong_banks": {"16": 3500, "17": 3501}, "wrong_bank_samples": 16,
        }
    assert P.evaluate(trace) == (True, [])


def test_wrong_pc_after_wrong_bank_flood_keeps_diagnostic_verdict():
    trace, recorded = run_mock_driver(wrong_pc=True)
    assert recorded is True
    bad = [row for row in trace if row["kind"] == "gate" and row["matched"] and not row["qualified"]]
    assert len(bad) == 1
    assert bad[0]["pc"] == P.NEXT
    assert bad[0]["cur_ot_mon"] == 0 and bad[0]["site_bytes"] == "218bd2fa0cd1"
    assert trace[-1]["hook_counts"]["gate"]["wrong_pc"] == 1
    ok, reasons = P.evaluate(trace)
    assert not ok and P.verdict(reasons) == "PC_IS_NEXT_INSTRUCTION"


def test_capacity_boundary_still_fails_and_counts_all_callbacks():
    trace, recorded = run_mock_driver(cap=1)
    assert recorded is True
    assert trace[-1]["hook_hits"] == 3 * 7002
    assert sum(row["kind"] == "overflow" for row in trace) == 1
    ok, reasons = P.evaluate(trace)
    assert not ok and any(reason.startswith("TRACE_OVERFLOW:") for reason in reasons)


@pytest.mark.parametrize("encoder", ["nil", "throw"])
def test_encoder_failure_emits_readable_independent_fallback_and_finishes(encoder):
    trace, recorded = run_mock_driver(encoder=encoder)
    assert recorded is False
    assert [row["kind"] for row in trace] == ["driver_error", "final"]
    assert trace[0]["error"]
    if encoder == "throw":
        assert trace[0]["error"] == 'encoder "failed"\nagain'
    final = trace[-1]
    assert final["completed"] is False and final["driver_errors"] == 1
    assert final["hook_hits"] == 3 * 7002
    assert final["wrong_bank_sample_limit"] == 16
    assert all(c["total"] == 7002 and c["wrong_bank_samples"] == 16 for c in final["hook_counts"].values())
    ok, reasons = P.evaluate(trace)
    assert not ok and any(reason.startswith("DRIVER_ERROR:") for reason in reasons)


def test_driver_failure_emits_final_with_preserved_totals_and_finishes():
    trace, recorded = run_mock_driver(frame_error=True)
    assert recorded is False
    assert trace[-1]["completed"] is False and trace[-1]["driver_errors"] == 1
    assert trace[-1]["hook_hits"] == 3 * 7002
    assert trace[-2]["error"] == 'driver "failed"\nagain'
    ok, reasons = P.evaluate(trace)
    assert not ok and any(reason.startswith("DRIVER_ERROR:") for reason in reasons)


@pytest.mark.parametrize("field", [
    "total", "qualified", "wrong_pc", "wrong_banks", "wrong_bank_samples",
])
def test_missing_individual_hook_counter_is_rejected(field):
    trace = good_trace()
    del trace[-1]["hook_counts"]["gate"][field]
    assert P.evaluate(trace)[0] is False


@pytest.mark.parametrize("field", ["total", "qualified", "wrong_pc", "wrong_bank_samples"])
@pytest.mark.parametrize("value", [True, -1, 1.5, 999])
def test_malformed_or_overstated_individual_hook_counter_is_rejected(field, value):
    trace = good_trace()
    trace[-1]["hook_counts"]["gate"][field] = value
    assert P.evaluate(trace)[0] is False


@pytest.mark.parametrize("field", ["hook_counts", "wrong_bank_sample_limit", "hook_hits"])
def test_missing_mandatory_final_counter_is_rejected(field):
    trace = good_trace()
    del trace[-1][field]
    assert P.evaluate(trace)[0] is False


def test_overstated_qualified_count_rejected_even_with_balanced_total():
    trace = good_trace()
    trace[-1]["hook_counts"]["gate"]["qualified"] += 1
    trace[-1]["hook_counts"]["gate"]["total"] += 1
    trace[-1]["hook_hits"] += 1
    assert P.evaluate(trace)[0] is False


def test_observed_wrong_bank_count_cannot_exceed_aggregate_claim():
    trace = complete([hit(bank=16, matched=False), hit()])
    trace[-1]["hook_counts"]["gate"]["wrong_banks"]["16"] = 0
    assert P.evaluate(trace)[0] is False


def test_empty_array_wrong_bank_map_matches_production_encoder():
    trace = good_trace()
    for counts in trace[-1]["hook_counts"].values():
        counts["wrong_banks"] = []
    assert P.evaluate(trace) == (True, [])


def test_optional_last_callback_wrong_pc_cannot_pass():
    ok, reasons = P.evaluate(complete([hit(), hit("last", pc=P.LAST + 1)]))
    assert not ok
    assert any(reason.startswith("LAST_PC_MISMATCH:") for reason in reasons)


@pytest.mark.parametrize("value", [True, -1, 1.5, 999])
def test_legacy_hook_hits_counter_must_match_callback_totals(value):
    trace = good_trace()
    trace[-1]["hook_hits"] = value
    assert P.evaluate(trace)[0] is False


@pytest.mark.parametrize("wrong_banks", [
    {"16": True}, {"16": -1}, {"16": 1.5}, {"16": 999}, {"0x10": 1}, [1],
])
def test_wrong_bank_map_rejects_invalid_or_inconsistent_counts(wrong_banks):
    trace = complete([hit(bank=16, matched=False), hit()])
    trace[-1]["hook_counts"]["gate"]["wrong_banks"] = wrong_banks
    assert P.evaluate(trace)[0] is False


def test_wrong_bank_retained_sample_count_cannot_be_overstated():
    trace = complete([hit(bank=16, matched=False), hit()])
    trace[-1]["hook_counts"]["gate"]["wrong_bank_samples"] = 2
    assert P.evaluate(trace)[0] is False


def test_wrong_pc_consumes_protected_capacity_without_losing_diagnostics():
    trace, recorded = run_mock_driver(wrong_pc=True, cap=4)
    assert recorded is True
    bad = [row for row in trace if row["kind"] == "gate" and row["matched"] and not row["qualified"]]
    assert len(bad) == 1 and bad[0]["pc"] == P.NEXT and bad[0]["mode"] == 2
    assert sum(row["kind"] == "overflow" for row in trace) == 1
    ok, reasons = P.evaluate(trace)
    assert not ok and P.verdict(reasons) == "PC_IS_NEXT_INSTRUCTION"
    assert any(reason.startswith("TRACE_OVERFLOW:") for reason in reasons)
