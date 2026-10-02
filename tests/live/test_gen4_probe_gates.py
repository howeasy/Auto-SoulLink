"""G1 a--n authoring/replay and opt-in serial PHYSICAL collection.

Offline: python -m pytest tests/live/test_gen4_probe_gates.py -m 'not live' -q
Live (coordinator's one lane): SLINK_LIVE=1 python -m pytest this_file -m live -q -rs
Set SLINK_GEN4_<TITLE>_SAVE, SLINK_GEN4_PROBE_SCENARIO, SLINK_GEN4_ROW_O.
Absent files are named skips/OPEN; malformed or mismatched present inputs fail.
No offline test launches an emulator. A partial probe never closes G1.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import importlib
import json
import os
import re
import shutil
import struct
import subprocess
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "lua/tests/probe_gen4_hooks.lua"
ROWS = tuple("abcdefghijklmn")
ROW_RE = re.compile(r"^PROBE ([a-o]) (PASS|FAIL|OPEN) (\{.*\})$")
TITLE_PACK = {"heartgold": "gen4_hgss", "soulsilver": "gen4_hgss", "heartgold_hge": "gen4_hge"}
CORE = "BizHawk.Emulation.Cores.Consoles.Nintendo.NDS.NDS"
MODEL_CUT = {"script_sha256": "1" * 64, "profile_sha256": "2" * 64, "source_head": "cut"}


def digest(path: Path, algorithm="sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def input_file(path: Path, name: str) -> Path:
    if not path.is_file():
        pytest.skip(f"OPEN {name}: absent input {path}")
    return path


class StaleReceiptError(AssertionError):
    """Present evidence from another source/script/profile cut cannot qualify."""


def committed_cut(title, *, script=SCRIPT, profile=None, source_head=None):
    profile = profile or REPO / "data/games" / TITLE_PACK[title] / "profile.json"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if source_head is not None and head != source_head:
        raise StaleReceiptError("STALE source_head: committed cut moved")
    cut = {"source_head": head}
    for key, path in (("script_sha256", script), ("profile_sha256", profile)):
        path = Path(path)
        relative = path.relative_to(REPO).as_posix()
        blob = subprocess.check_output(["git", "show", f"{head}:{relative}"], cwd=REPO)
        if path.read_bytes().replace(b"\r\n", b"\n") != blob.replace(b"\r\n", b"\n"):
            raise StaleReceiptError(f"STALE {key}: uncommitted file {relative}")
        cut[key] = digest(path)
    return cut


def bind_cut(payload, expected_cut):
    for key in ("script_sha256", "profile_sha256", "source_head"):
        if payload.get(key) != expected_cut[key]:
            raise StaleReceiptError(f"STALE {key}: receipt differs from committed cut")


def parse_receipt(text: str, *, title: str, rom_sha1: str, run_id: str | None = None, expected_cut=None) -> dict:
    """No stale neighbour, duplicate row, wrong artifact, MODEL-as-PHYSICAL or tail accepted."""
    lines = text.splitlines()
    expected_cut = expected_cut or committed_cut(title)
    assert lines and lines[-1] in {"RESULT: PASS", "RESULT: FAIL", "RESULT: OPEN"}, "missing terminal RESULT"
    assert sum(line.startswith("RESULT:") for line in lines) == 1, "multiple RESULT lines"
    rows = {}
    for line in lines[:-1]:
        match = ROW_RE.fullmatch(line)
        assert match, f"malformed receipt line: {line[:160]}"
        row, status, raw = match.groups()
        assert row not in rows, f"duplicate row {row}"
        payload = json.loads(raw)
        bind_cut(payload, expected_cut)
        assert payload["title"] == title and payload["rom_sha1"].lower() == rom_sha1.lower(), "wrong artifact binding"
        assert payload["level"] == "PHYSICAL", "MODEL evidence cannot close physical rows"
        if run_id is not None:
            assert payload["run_id"] == run_id, "stale/wrong-run receipt"
        rows[row] = (status, payload)
    statuses = [status for status, _ in rows.values()]
    expected = "FAIL" if "FAIL" in statuses else "OPEN" if "OPEN" in statuses else "PASS"
    assert lines[-1] == f"RESULT: {expected}", "terminal status contradicts row statuses"
    return rows


def row_o(path: Path | None, title: str, sha1: str, source_head: str, *, expected_cut=None) -> tuple[str, dict]:
    """C1-8 owns its mechanism/oracle. Consume its row, never synthesize success."""
    if path is None or not path.is_file():
        return "OPEN", {"reason": f"C1-8 row o receipt absent: {path or 'SLINK_GEN4_ROW_O'}"}
    expected_cut = expected_cut or committed_cut(title, script=REPO / "lua/tests/probe_gen4_battle_faint.lua", source_head=source_head)
    assert expected_cut["source_head"] == source_head, "row o expected cut mismatch"
    rows = parse_receipt(path.read_text(encoding="utf-8"), title=title, rom_sha1=sha1, expected_cut=expected_cut)
    assert "o" in rows, "present C1-8 input contains no row o"
    status, payload = rows["o"]
    assert payload.get("source_head") == source_head, "row o belongs to a different source cut"
    assert payload.get("producer") == "C1-8", "row o must identify its producer"
    if payload.get("setup") == "SYNTH":
        sidecar_hash = payload.get("sidecar_sha256") or payload.get("synth", {}).get("sidecar_sha256")
        assert isinstance(sidecar_hash, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sidecar_hash), "row o SYNTH requires sidecar hash disclosure"
    if status == "PASS":
        assert payload.get("oracle") and payload.get("negative_control"), "row o PASS lacks independent oracle/red control"
    return status, payload


def perf_f(path, title, rom_sha1, source_head, *, expected_cut=None):
    """Read gen4-PERF's bound observations; Lua f remains the sole pass authority."""
    if path is None or not Path(path).is_file():
        return None, "gen4-PERF bundle absent"
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    if expected_cut is None:
        committed_cut(title, source_head=source_head)  # The consuming f authority must also be committed.
        expected_cut = committed_cut(title, script=REPO / "lua/tests/perf_gen4.lua", source_head=source_head)
    assert expected_cut["source_head"] == source_head, "PERF expected cut mismatch"
    assert bundle["schema"] == "gen4-perf-bundle-v1" and bundle["producer"] == "gen4-PERF", "wrong PERF producer/schema"
    assert bundle["level"] == "PHYSICAL" and bundle["title"] == title and bundle["rom_sha1"] == rom_sha1, "wrong PERF artifact/evidence"
    if bundle.get("source_head") != source_head:
        raise StaleReceiptError("STALE source_head: PERF belongs to a different source cut")
    observation = bundle.get("observation")
    if observation is None:
        return None, bundle.get("reason", "gen4-PERF required samples absent")

    def bind(sample):
        bind_cut(sample, expected_cut)
        assert sample["producer"] == "gen4-PERF" and sample["result"] == "PASS" and sample["level"] == "PHYSICAL", "incomplete PERF sample/floor"
        assert sample["title"] == title and sample["rom_sha1"] == rom_sha1 and sample["source_head"] == source_head, "PERF sample/floor binding mismatch"
        assert not sample["concurrent_load"] and sample["ending_registered"] == 0, "PERF sample/floor concurrent load/retained hook"
        assert sample["module_sha256"]["lua/tests/probe_gen4_hooks.lua"] == digest(SCRIPT), "PERF uses a different f authority"

    sources = set()
    for name in ("zero", "one", "overworld_zero"):
        sample = observation["sustained"][name]
        bind(sample)
        bind(sample["floor"])
        assert sample["floor"]["module_sha256"] == sample["module_sha256"], "PERF floor uses different workload modules"
        sources.add(sample["clock_source"])
        sample["frames"] = sample["frames_requested"]
    assert len(sources) == 1, "mixed PERF clock sources"
    return observation, None


def finish_rows(api, observations: dict, errors: dict, external_o: tuple[str, dict]) -> tuple[str, dict]:
    rows = {}
    for row in ROWS:
        if row in errors:
            rows[row] = errors[row]
            continue
        outcome = api.evaluate(row, to_lua(api._runtime, observations.get(row)))
        status, reason = outcome if isinstance(outcome, tuple) else (outcome, None)
        rows[row] = (status, {"observation": observations.get(row), "reason": reason})
    rows["o"] = external_o
    statuses = [s for s, _ in rows.values()]
    return ("FAIL" if "FAIL" in statuses else "OPEN" if "OPEN" in statuses else "PASS"), rows


class LuaProbe:
    """Keep the Lua runtime attached without modifying the returned Lua table."""
    def __init__(self, runtime, api):
        self._runtime = runtime
        self._api = api

    def __getattr__(self, key):
        return self._api[key]


def to_lua(runtime, value):
    if isinstance(value, dict):
        return runtime.table_from({k: to_lua(runtime, v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return runtime.table_from([to_lua(runtime, v) for v in value])
    return value


def from_lua(value):
    if hasattr(value, "items"):
        return {k: from_lua(v) for k, v in value.items()}
    return value


@pytest.fixture
def api():
    from lupa import LuaRuntime

    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().SLINK_GEN4_PROBE_TEST = True
    return LuaProbe(runtime, runtime.execute(SCRIPT.read_text(encoding="utf-8")))


def examples():
    """Hypothetical observations for red/revert oracle tests; never physical receipts."""
    return {
        "a": {"arm": {"frames": 10, "hits": 10, "badpc": 0, "badword": 0},
              "thumb": {"frames": 10, "hits": 10, "badpc": 0, "badword": 0}, "negative_hits": 0},
        "b": {"accepted": 1, "dropped": 1, "inactive_drop": True, "active_fault": True,
              "full_pin_reject": True, "callback_corrupt": 0},
        "c": {"jit": False, "use_real_time": False, "quiet_changes": 0,
              "table_transitions": [{"frame": 2, "before": "off", "after": "129 active"}],
              "changes": [{"frame": 2, "region": 0, "id": 129, "kind": "load"}],
              "causes": [{"frame": 1, "region": 0, "id": 129, "kind": "load", "source": "pinned internal entry"}]},
        "d": {"hits": 10, "timing": "before", "host_hits": 0, "wrong_hits": 0},
        "e": {"before": 10, "kept": 10, "removed": 0, "reloaded": 0},
        "f": {"fps": [208.6, 97.3, 79.7, 66.1, 57.9, 52.9], "sustained": {
            name: {"requested_rate": 100, "frames": 3000, "registered_hooks": hooks,
                   "requested_execution_mode": "paced_production_frameadvance",
                   "throttle_config": {"Unthrottled": False, "ClockThrottle": True, "SpeedPercent": 100, "FrameSkip": 0, "AutoMinimizeSkipping": False},
                   "timing_kind": "wall_frame_interval", "clock_source": "MODEL high-resolution wall clock",
                   "clock": {"monotonic_guaranteed": True},
                   "frame_times": [560190 / 33513982] * 3000,
                   "session_id": "MODEL session",
                   "floor": {"session_id": "MODEL session", "phase": "overworld" if name == "overworld_zero" else "battle",
                             "clock_source": "MODEL high-resolution wall clock", "requested_rate": 100,
                             "clock": {"monotonic_guaranteed": True},
                             "registered_hooks": 0, "instrumentation_floor": True, "frame_times": [560190 / 33513982] * 3000},
                   "load_counts": {**dict.fromkeys(("pointer_chain", "party_diff", "json_encode", "battle_attempts"), 3000), "battle_mons_hp": 0 if name == "overworld_zero" else 3000},
                   "phase": "overworld" if name == "overworld_zero" else "battle",
                   "ending_registered": 0, "on_demand": name == "one", "removed_after_fire": name == "one"}
            for name, hooks in (("zero", 0), ("one", 1), ("overworld_zero", 0))}},
        "g": {"domains": {"Main RAM": 4194304, "Shared WRAM": 32768, "ARM7 WRAM": 65536,
                          "SRAM": 524288, "Instruction TCM": 32768, "Data TCM": 16384, "ARM9 System Bus": 0},
                          "registers": {f"ARM9 r{i}": 0 for i in range(16)}, "bogus_refused": True, "raw_core_bogus_accepted": True},
        "h": {"pointer": 0x2200000, "field_save": 0x2200000, "signature": "23", "expected_signature": "23",
              "identity": "1234", "expected_identity": "1234", "invalid_rejected": True,
              "signature_rejected": True, "provenance_rejected": True},
        "i": {"written": 9, "target": 9, "original": 10, "no_write": 10, "box_dirty": 2,
              "box_target": 2, "box_original": 1, "box_without_dirty": 1, "cold_reload": 9, "save_completed": True,
              "save_driver_cases": {name: [{"driver": 100, "data": 200, "state": state, "frame": frame}
                                          for frame, state in enumerate((1, 2, 1))]
                                    for name in ("party-write", "no-write", "box-write", "box-no-dirty")}},
        "j": {"hash": "1" * 32, "sha1": "2" * 40, "md5": "1" * 32, "patched_hash": "3" * 40},
        "k": {"first": "pinned", "second": "pinned", "unpinned": "wallclock", "frame_first": 1035, "frame_second": 1035},
        "l": {"overworld": True, "no_buttons_overworld": False, "other_boot_buttons": 0, "boot_inputs": {"A": 3, "Start": 3}},
        "m": {"histograms": {p: {"123": 10} for p in ("overworld", "menu", "battle", "save")},
              "halt": 0x2001000, "idle_hits": 5, "save_same_as_idle": False},
        "n": {"model": {"last_event": 1, "second_drain": 0, "after_close": 0, "reset_event": 1,
                        "close_ok": False, "retained": 1, "fault": True, "rearm": False,
                        "failed_last": 1, "failed_second": 0, "partial_fault": True, "partial_retained": 1,
                        "fifth": False, "peak": 4},
              "physical": {"first_expected": 1, "first_seen": 1, "last_expected": 1, "last_seen": 1,
                           "static_pc": True, "reset": True, "peak": 3, "live_after_close": 0,
                           "pending_at_close": 1, "second_drain": 0,
                           "cases": [{"phase": name, "first_expected": 1, "first_seen": 1, "last_expected": 1, "last_seen": 1}
                                     for name in ("battle", "pc", "reset")],
                           "max_cost": 0.001, "restored_fps": 200, "baseline_fps": 200}},
    }


NEGATIVES = {
    "a": ("negative_hits", 1), "b": ("active_fault", False), "c": ("quiet_changes", 1),
    "d": ("host_hits", 1), "e": ("reloaded", 1), "f": ("sustained", {"zero": {"requested_rate": 300, "frames": 3000}}),
    "g": ("bogus_refused", False), "h": ("signature_rejected", False),
    "i": ("box_without_dirty", 2), "j": ("patched_hash", "1" * 32),
    "k": ("unpinned", "pinned"), "l": ("no_buttons_overworld", True),
    "m": ("save_same_as_idle", True), "n": ("physical", {"first_expected": 1, "first_seen": 0, "cases": []}),
}


@pytest.mark.parametrize("row", ROWS)
def test_row_red_and_revert(api, row):
    positive = examples()[row]
    assert api.evaluate(row, to_lua(api._runtime, positive)) == "PASS"
    negative = copy.deepcopy(positive)
    key, value = NEGATIVES[row]
    negative[key] = value
    assert api.evaluate(row, to_lua(api._runtime, negative))[0] == "FAIL"
    assert api.evaluate(row, to_lua(api._runtime, positive)) == "PASS"
    assert api.evaluate(row, None)[0] == "OPEN"


def test_registry_close_construction_reset_budget(api):
    registry = api._runtime.execute((REPO / "lua/hook_registry.lua").read_text(encoding="utf-8"))
    measured = from_lua(api.phase_controls(registry))
    assert measured["last_event"] == measured["reset_event"] == measured["failed_last"] == 1
    assert measured["second_drain"] == measured["failed_second"] == measured["after_close"] == 0
    assert measured["close_ok"] is False and measured["fault"] and not measured["rearm"]
    assert measured["retained"] == measured["partial_retained"] == 1 and measured["partial_fault"]
    assert measured["peak"] == 4 and not measured["fifth"]
    # Repeat after cleanup: leaked owner reservations would reject construction here.
    assert from_lua(api.phase_controls(registry)) == measured


def test_overlay_residency_unsigned_word_full_extent_controls(api):
    r = api._runtime
    site = {"id": "faint", "symbol": "BtlCmd_TryFaintMon", "address": 0x2200000,
            "image": "ov130", "overlay_id": 130, "extent": 8, "mode": "thumb",
            "register_hex": "ffffffff11223344", "fire_hex": "ffffffff"}
    title = {"symbols": {site["symbol"]: {"address": site["address"], "image": "ov130", "mode": "thumb"}},
             "overlays": {"130": {"ram": site["address"], "size": 8}}}
    yes, no = r.eval("function() return true end"), r.eval("function() return false end")
    assert api.capture(to_lua(r, site), site["address"], -1, 0, site["address"] + 4, yes)["word"] == 0xFFFFFFFF
    assert api.capture(to_lua(r, site), site["address"], 0, 0, 0, no) is None
    with pytest.raises(Exception, match="active owner fire pin mismatch"):
        api.capture(to_lua(r, site), site["address"], 0, 0, site["address"] + 4, yes)
    good_bytes = r.eval('function() return "ffffffff11223344" end')
    api.validate_site(to_lua(r, title), to_lua(r, site), good_bytes, yes)
    # First four bytes remain correct; corruption beyond callback width MUST reject.
    corrupt = dict(site, register_hex="ffffffff11223345")
    with pytest.raises(Exception, match="full registration pin mismatch"):
        api.validate_site(to_lua(r, title), to_lua(r, corrupt), good_bytes, yes)
    assert not api.valid_handle("00000000-0000-0000-0000-000000000000")
    assert api.valid_handle("12345678-0000-0000-0000-000000000000")


def test_census_omitted_internal_cause_goes_red(api):
    original = examples()["c"]
    assert api.census_ok(to_lua(api._runtime, original))
    negative = copy.deepcopy(original)
    negative["causes"] = []
    assert not api.census_ok(to_lua(api._runtime, negative))
    assert api.evaluate("c", to_lua(api._runtime, negative))[0] == "FAIL"
    assert api.census_ok(to_lua(api._runtime, original))


def test_cpu_distribution_control_is_not_window_length(api):
    r = api._runtime
    assert api.same_distribution(to_lua(r, {"halt": 50, "irq": 50}), to_lua(r, {"halt": 100, "irq": 100}))
    assert not api.same_distribution(to_lua(r, {"halt": 50, "irq": 50}), to_lua(r, {"halt": 10, "irq": 90}))


def test_host_write_control_changes_then_restores_and_can_be_red(api):
    r = api._runtime
    r.execute('''VALUE=16; WRITTEN={}; HOST_HITS=0
        reader=function() return VALUE end
        writer=function(_,v) WRITTEN[#WRITTEN+1]=v; VALUE=v end''')
    api.host_write_control(r.globals().reader, r.globals().writer, 100)
    assert list(r.globals().WRITTEN.values()) == [239, 16] and r.globals().VALUE == 16
    r.execute('''writer=function(_,v) VALUE=v; HOST_HITS=HOST_HITS+1 end''')
    api.host_write_control(r.globals().reader, r.globals().writer, 100)
    obs = examples()["d"]
    obs["host_hits"] = r.globals().HOST_HITS
    assert api.evaluate("d", to_lua(r, obs))[0] == "FAIL"


@pytest.mark.parametrize("fault", ["dropped_write", "wrong_readback", "read_error"])
def test_host_write_intermediate_readback_red_restore_revert(api, fault):
    r = api._runtime
    r.execute('''VALUE=16; EVENTS={}; READS=0; WRITES=0; FAULT=nil
        reader=function()
            READS=READS+1; EVENTS[#EVENTS+1]="read:"..VALUE
            if READS==2 and FAULT=="read_error" then error("intermediate read failed") end
            if READS==2 and FAULT=="wrong_readback" then return 0 end
            return VALUE
        end
        writer=function(_,v)
            WRITES=WRITES+1; EVENTS[#EVENTS+1]="write:"..v
            if not (WRITES==1 and FAULT=="dropped_write") then VALUE=v end
        end''')
    api.host_write_control(r.globals().reader, r.globals().writer, 100)
    assert list(r.globals().EVENTS.values()) == ["read:16", "write:239", "read:239", "write:16", "read:16"]
    r.execute("READS=0; WRITES=0")
    r.globals().FAULT = fault
    with pytest.raises(Exception, match="host write control failed"):
        api.host_write_control(r.globals().reader, r.globals().writer, 100)
    assert r.globals().VALUE == 16 and r.globals().WRITES == 2
    r.execute("FAULT=nil; READS=0; WRITES=0")
    api.host_write_control(r.globals().reader, r.globals().writer, 100)
    assert r.globals().VALUE == 16


def test_overlay_callback_counts_pc_corruption_red_revert(api):
    r = api._runtime
    site = {"id": "site", "image": "ov1", "overlay_id": 1, "address": 100, "mode": "thumb",
            "extent": 4, "register_hex": "01000000", "fire_hex": "00000001"}
    baseline = examples()["b"]
    assert api.evaluate("b", to_lua(r, baseline)) == "PASS"
    b = to_lua(r, baseline)
    api.observe_overlay(b, to_lua(r, site), 100, 1, 0, 108,
                        r.eval('function() return "01000000" end'), r.eval("function() return true end"))
    assert b.callback_corrupt == 1
    assert api.evaluate("b", b)[0] == "FAIL"
    b.callback_corrupt = 0
    api.observe_overlay(b, to_lua(r, site), 100, 1, 0, 104,
                        r.eval('function() return "01000000" end'), r.eval("function() return true end"))
    assert api.evaluate("b", b) == "PASS"


def test_boot_buttons_measured_red_revert(api):
    r = api._runtime
    audit = r.table()
    api.record_boot_input(audit, to_lua(r, {"A": True, "Start": True, "B": False}))
    assert api.other_boot_buttons(audit) == 0
    api.record_boot_input(audit, to_lua(r, {"B": True}))
    observed = examples()["l"]
    observed.update(boot_inputs=dict(audit.items()), other_boot_buttons=api.other_boot_buttons(audit))
    assert observed["other_boot_buttons"] == 1 and api.evaluate("l", to_lua(r, observed))[0] == "FAIL"
    observed["other_boot_buttons"] = 0  # Falsified aggregate cannot hide the measured B input.
    assert api.evaluate("l", to_lua(r, observed))[0] == "FAIL"
    assert api.evaluate("l", to_lua(r, examples()["l"])) == "PASS"


def test_core_bogus_register_fact_red_revert(api):
    original = examples()["g"]
    assert api.evaluate("g", to_lua(api._runtime, original)) == "PASS"
    bad = dict(original, raw_core_bogus_accepted=False)
    assert api.evaluate("g", to_lua(api._runtime, bad))[0] == "FAIL"
    assert api.evaluate("g", to_lua(api._runtime, original)) == "PASS"


def test_rtc_slice_pack_absent_open_wrong_fail_revert(api):
    r = api._runtime
    title = {"profile": {}, "symbols": {"sRTCWork": {"address": 100, "size": 88}}}
    call = r.eval("function(f,t) local ok,v=pcall(f,t); return ok,v end")
    ok, why = call(api.rtc_slice, to_lua(r, title))
    assert not ok and "profile.rtc" in why["open"]
    title["profile"]["rtc"] = {"symbol": "sRTCWork", "date_off": 16, "date_size": 16,
                               "time_off": 32, "time_size": 12, "source": "MODEL source"}
    good = from_lua(api.rtc_slice(to_lua(r, title)))
    assert good == {"date_address": 116, "date_size": 16, "time_address": 132, "time_size": 12}
    title["profile"]["rtc"]["time_size"] = 89
    with pytest.raises(Exception, match="RTC slice outside"):
        api.rtc_slice(to_lua(r, title))
    title["profile"]["rtc"]["time_size"] = 12
    assert from_lua(api.rtc_slice(to_lua(r, title))) == good


@pytest.mark.parametrize("phase", ["battle", "pc", "reset"])
def test_phase_zero_expected_cannot_hide_in_sum_red_revert(api, phase):
    original = examples()["n"]
    assert api.evaluate("n", to_lua(api._runtime, original)) == "PASS"
    bad = copy.deepcopy(original)
    case = next(c for c in bad["physical"]["cases"] if c["phase"] == phase)
    case.update(first_expected=0, first_seen=0, last_expected=0, last_seen=0)
    assert api.evaluate("n", to_lua(api._runtime, bad))[0] == "FAIL"
    assert api.evaluate("n", to_lua(api._runtime, original)) == "PASS"


@pytest.mark.parametrize("fault", ["no_active", "still_active", "pointer_changed", "backwards", "invalid_state"])
def test_save_completion_needs_driver_state_reads_red_revert(api, fault):
    original = examples()["i"]
    trace = original["save_driver_cases"]["party-write"]
    assert save_driver_complete(trace) and api.save_completed(to_lua(api._runtime, trace))
    bad = copy.deepcopy(original)
    trace = bad["save_driver_cases"]["party-write"]
    if fault == "no_active":
        trace[1]["state"] = 1
    elif fault == "still_active":
        trace[-1]["state"] = 2
    elif fault == "pointer_changed":
        trace[-1]["data"] = 201
    elif fault == "backwards":
        trace[-1]["frame"] = -1
    else:
        trace[1]["state"] = 2.5
    assert not save_driver_complete(trace) and not api.save_completed(to_lua(api._runtime, trace))
    assert api.evaluate("i", to_lua(api._runtime, bad))[0] == "FAIL"  # save_completed still claims True.
    assert api.evaluate("i", to_lua(api._runtime, original)) == "PASS"


def test_save_driver_witness_reads_packed_chain(api):
    r = api._runtime
    title = {"symbols": {"sFieldSysPtr": {"address": 100}},
             "profile": {"probe_field": {"save_driver": 8, "save_driver_data_off": 4, "save_state": 1}}}
    r.execute("MEM={[100]=1000,[1008]=2000,[2004]=3000,[3001]=2}; reader=function(a) return MEM[a] or 0 end")
    actual = from_lua(api.save_driver_witness(to_lua(r, title), r.globals().reader, r.globals().reader, 17))
    assert actual == {"driver": 2000, "data": 3000, "state": 2, "frame": 17}
    r.execute("MEM[2004]=0")
    assert api.save_driver_witness(to_lua(r, title), r.globals().reader, r.globals().reader, 18) is None
    r.execute("MEM[2004]=3000")
    assert from_lua(api.save_driver_witness(to_lua(r, title), r.globals().reader, r.globals().reader, 17)) == actual


def test_register_name_guard_refuses_before_read_and_masks_signed(api):
    r = api._runtime
    r.execute('CALLS=0; reader=function() CALLS=CALLS+1; return -1 end')
    names = to_lua(r, {"ARM9 r15": -1})
    with pytest.raises(Exception, match="unknown register name"):
        api.read_register(names, r.globals().reader, "ARM9 bogus")
    assert r.globals().CALLS == 0
    assert api.read_register(names, r.globals().reader, "ARM9 r15") == 0xFFFFFFFF


@pytest.mark.parametrize("fault", ["one_slow_frame", "load_missing", "retained_hook", "not_on_demand", "short_sample", "wrong_rate"])
def test_f_owner_sustained_deadline_and_load_red_revert(api, fault):
    r = api._runtime
    original = examples()["f"]
    assert api.evaluate("f", to_lua(r, original)) == "PASS"
    bad = copy.deepcopy(original)
    sample = bad["sustained"]["one"]
    if fault == "one_slow_frame":
        sample["frame_times"][-1] = 0.034  # Average/p99 still appear fine; max must catch it.
    elif fault == "load_missing":
        sample["load_counts"]["json_encode"] = 2999
    elif fault == "retained_hook":
        sample["ending_registered"] = 1
    elif fault == "not_on_demand":
        sample["on_demand"] = False
    elif fault == "short_sample":
        sample["frames"] = 2999
    else:
        sample["requested_rate"] = 300
    assert api.evaluate("f", to_lua(r, bad))[0] == "FAIL"
    assert api.evaluate("f", to_lua(r, original)) == "PASS"


def test_f_average_and_hook_curve_cannot_qualify(api):
    r = api._runtime
    old = {"fps": [208.6, 97.3, 79.7, 66.1, 57.9, 52.9], "phase_max": 3, "realtime": 60}
    assert api.evaluate("f", to_lua(r, old))[0] == "OPEN"
    # The curve is independent characterization: a differently shaped curve
    # must not invalidate otherwise complete sustained timing/load evidence.
    current = examples()["f"]
    current["fps"] = [200] * 6
    assert api.evaluate("f", to_lua(r, current)) == "PASS"


@pytest.mark.parametrize("fault", ["gap_34ms", "mean_59fps", "p99_floor_plus_1_5ms", "foreign_floor"])
def test_f_owner_native_cadence_floor_red_revert(api, fault):
    original = examples()["f"]
    r = api._runtime
    assert api.evaluate("f", to_lua(r, original)) == "PASS"
    bad = copy.deepcopy(original)
    sample = bad["sustained"]["one"]
    period = 560190 / 33513982
    if fault == "gap_34ms":
        sample["frame_times"][-1] = .034
    elif fault == "mean_59fps":
        sample["frame_times"] = [1 / 59] * 3000
    elif fault == "p99_floor_plus_1_5ms":
        sample["frame_times"] = [period - .0015 * 60 / 2940] * 2940 + [period + .0015] * 60
    else:
        sample["floor"]["session_id"] = "other"
    assert api.evaluate("f", to_lua(r, bad))[0] == "FAIL"
    assert api.evaluate("f", to_lua(r, original)) == "PASS"


@pytest.mark.parametrize("fault", [
    "nonmonotonic", "nonmonotonic_floor", "monotonic_missing", "monotonic_floor_missing", "execution_mode", "throttle_config",
    "frames_below_3000", "overworld_attempts", "overworld_hp_reads", "overworld_phase",
    "on_demand_removal", "sequence_length", "mean_300fps_fake_throttle",
])
def test_f_contract_clauses_red_revert(api, fault):
    original = examples()["f"]
    r = api._runtime
    assert api.evaluate("f", to_lua(r, original)) == "PASS"
    bad = copy.deepcopy(original)
    sample = bad["sustained"]["one"]
    if fault == "nonmonotonic":
        sample["clock"]["monotonic_guaranteed"] = False
    elif fault == "nonmonotonic_floor":
        sample["floor"]["clock"]["monotonic_guaranteed"] = False
    elif fault == "monotonic_missing":
        sample["clock"].pop("monotonic_guaranteed")
    elif fault == "monotonic_floor_missing":
        sample["floor"]["clock"].pop("monotonic_guaranteed")
    elif fault == "execution_mode":
        sample["requested_execution_mode"] = "script_frameadvance_capacity"
    elif fault == "throttle_config":
        sample["throttle_config"]["Unthrottled"] = True
    elif fault == "frames_below_3000":
        sample["frames"] = 2999
        sample["frame_times"].pop()  # Keep length consistent: minimum window must catch this.
    elif fault.startswith("overworld_"):
        sample = bad["sustained"]["overworld_zero"]
        if fault == "overworld_attempts":
            sample["load_counts"]["battle_attempts"] = 2999
        elif fault == "overworld_hp_reads":
            sample["load_counts"]["battle_mons_hp"] = 1
        else:
            sample["phase"] = "battle"
            sample["floor"]["phase"] = "battle"
    elif fault == "on_demand_removal":
        sample["removed_after_fire"] = False
    elif fault == "sequence_length":
        sample["frame_times"].pop()
    else:
        # All requested-rate/config claims remain 1x: measured wall time must reject 300fps.
        sample["frame_times"] = [1 / 300] * 3000
    assert api.evaluate("f", to_lua(r, bad))[0] == "FAIL"
    assert api.evaluate("f", to_lua(r, original)) == "PASS"


@pytest.mark.parametrize("fault", [
    "result", "producer", "level", "title", "rom_sha1", "source_head",
    "concurrent_load", "ending_registered", "module_sha256", "other_modules",
])
def test_perf_f_binds_floor_red_revert(tmp_path, fault):
    observation = examples()["f"]
    binding = {"producer": "gen4-PERF", "result": "PASS", "level": "PHYSICAL",
               "title": "heartgold", "rom_sha1": "a" * 40, "source_head": "cut",
               "concurrent_load": False, "ending_registered": 0,
               "module_sha256": {"lua/tests/probe_gen4_hooks.lua": digest(SCRIPT), "reads": "bound"}}
    binding.update(MODEL_CUT)
    for sample in observation["sustained"].values():
        sample.update(copy.deepcopy(binding), frames_requested=3000)
        sample["floor"].update(copy.deepcopy(binding), frames_requested=3000)
    bundle = {"schema": "gen4-perf-bundle-v1", "producer": "gen4-PERF", "level": "PHYSICAL",
              "title": "heartgold", "rom_sha1": "a" * 40, "source_head": "cut", "observation": observation}
    path = tmp_path / "bundle.json"

    def consume(value):
        path.write_text(json.dumps(value), encoding="utf-8")
        return perf_f(path, "heartgold", "a" * 40, "cut", expected_cut=MODEL_CUT)

    assert consume(bundle)[1] is None
    bad = copy.deepcopy(bundle)
    floor = bad["observation"]["sustained"]["one"]["floor"]
    if fault == "module_sha256":
        floor["module_sha256"]["lua/tests/probe_gen4_hooks.lua"] = "stale"
    elif fault == "other_modules":
        floor["module_sha256"]["reads"] = "different"
    else:
        floor[fault] = {"result": "FAIL", "producer": "other", "level": "MODEL", "title": "other",
                        "rom_sha1": "b" * 40, "source_head": "old", "concurrent_load": True,
                        "ending_registered": 1}[fault]
    with pytest.raises(AssertionError):
        consume(bad)
    assert consume(bundle)[1] is None


def phase_examples():
    return [{"name": name, "phase": "battle" if name == "reset" else name,
             "sites": ["producer"], "producer_site": "producer", "predicate": {"symbol": "sFieldSysPtr"},
             "source": "source:1", "route": [{"buttons": ["A"], "frames": 3}], "open": []}
            for name in ("battle", "pc", "reset")]


def test_phase_blocked_pc_open_active_wrong_fail_revert(api):
    cases = phase_examples()
    assert phase_case_plan(cases, []) == (cases, [])
    runnable, reasons = phase_case_plan([cases[0], cases[2]], [{"name": "pc", "blocked_reason": "native box slot absent"}])
    assert not runnable and reasons == ["pc: native box slot absent"]
    result, rows = finish_rows(api, examples(), {"n": ("OPEN", {"reason": reasons[0]})}, ("PASS", {}))
    assert result == "OPEN" and rows["n"][0] == "OPEN"
    malformed = copy.deepcopy(cases)
    malformed[0]["producer_site"] = "unselected"
    with pytest.raises(AssertionError, match="producer observer"):
        phase_case_plan(malformed, [])
    assert phase_case_plan(cases, []) == (cases, [])
    assert phase_case_plan([], [])[1] == ["battle: required phase case absent", "pc: required phase case absent", "reset: required phase case absent"]


def recipe_example():
    return {"steps": [{"press": ["A"], "hold_frames": 2, "then_wait_frames": 1}],
            "until": {"symbol": "sFieldSysPtr", "deref": [0, 4], "offset": 12, "value": 12},
            "max_frames": 6, "route_status": "recipe_source", "evidence": "SOURCE", "source": ["source:1"], "open": None}


def test_named_pack_recipe_missing_open_and_present_wrong_revert(api):
    recipe = recipe_example()
    resolved, reasons = resolve_pack_route(["fight"], {"fight": recipe})
    assert not reasons and resolved[0]["name"] == "fight"
    assert resolve_pack_route(["fight"], {}) == ([], ["button recipe absent for named route leg fight"])
    open_leg = dict(recipe, route_status="open", evidence="OPEN", steps=[], until=None, open="fixture absent")
    assert resolve_pack_route(["fight"], {"fight": open_leg}) == ([], ["fight: fixture absent"])
    wrong = copy.deepcopy(recipe)
    wrong["steps"][0]["press"] = ["Touch"]
    with pytest.raises(AssertionError, match="unsupported button"):
        resolve_pack_route(["fight"], {"fight": wrong})
    assert resolve_pack_route(["fight"], {"fight": recipe}) == (resolved, [])
    cases = phase_examples()
    for case in cases:
        case["route"] = ["fight"]
    runnable, reasons = phase_case_plan(cases, [], {"fight": recipe})
    assert not reasons and runnable[0]["route"] == resolved
    # Execute the actual bounded Lua interpreter, not a Python approximation.
    r = api._runtime
    r.execute('FRAMES=0; INPUTS={}; step=function(b) FRAMES=FRAMES+1; INPUTS[FRAMES]=b.A==true end')
    ready = r.eval("function() return FRAMES>=5 end")
    assert api.play_recipe(to_lua(r, resolved[0]), r.globals().step, ready) == 5
    assert list(r.globals().INPUTS.values()) == [True, True, False, True, True]
    with pytest.raises(Exception, match="until predicate not reached"):
        api.play_recipe(to_lua(r, resolved[0]), r.globals().step, r.eval("function() return false end"))


def test_recipe_predicate_chain_null_is_not_success(api):
    r = api._runtime
    title = to_lua(r, {"symbols": {"sFieldSysPtr": {"address": 100}}})
    r.execute('WORDS={[100]=200,[200]=300,[304]=400,[412]=12}; read=function(a) return WORDS[a] or 0 end')
    predicate = recipe_example()["until"]
    assert api.predicate(title, r.globals().read, to_lua(r, predicate))
    r.globals().WORDS[304] = 0
    assert not api.predicate(title, r.globals().read, to_lua(r, predicate))
    r.globals().WORDS[304] = 400
    assert api.predicate(title, r.globals().read, to_lua(r, predicate))
    reset = to_lua(r, {"symbol": "sFieldSysPtr", "deref": [], "offset": 0, "zero": True})
    assert not api.predicate(title, r.globals().read, reset)
    r.globals().WORDS[100] = 0
    assert api.predicate(title, r.globals().read, reset)
    # A null root must not satisfy a zero test on an unreachable nested field.
    assert not api.predicate(title, r.globals().read, to_lua(r, {**predicate, "value": None, "zero": True}))


def test_synth_sidecar_bound_hash_disclosure_and_wrong_revert(tmp_path):
    save = tmp_path / "copy.SaveRAM"
    save.write_bytes(b"model save")
    assert save_setup(save) == {"setup": "NATIVE"}
    sidecar = Path(str(save) + ".synth.json")
    meta = {"src_sha1": "a" * 40, "out_sha1": digest(save, "sha1"), "new_pid": 7}
    sidecar.write_text(json.dumps(meta))
    disclosed = save_setup(save)
    assert disclosed["setup"] == "SYNTH" and disclosed["sidecar_sha256"] == digest(sidecar)
    wrong = dict(meta, out_sha1="0" * 40)
    sidecar.write_text(json.dumps(wrong))
    with pytest.raises(AssertionError, match="output hash mismatch"):
        save_setup(save)
    sidecar.write_text(json.dumps(meta))
    assert save_setup(save) == disclosed


def test_row_o_requires_synth_disclosure(tmp_path):
    path = tmp_path / "o.txt"
    good = receipt("o", source_head="cut", producer="C1-8", oracle="independent", negative_control="red", setup="NATIVE")
    path.write_text(good)
    assert row_o(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT)[0] == "PASS"
    path.write_text(good.replace('"NATIVE"', '"SYNTH"'))
    with pytest.raises(AssertionError, match="sidecar hash"):
        row_o(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT)
    path.write_text(receipt("o", producer="C1-8", oracle="independent", negative_control="red",
                            setup="SYNTH", synth={"sidecar_sha256": "a" * 64}))
    assert row_o(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT)[0] == "PASS"
    path.write_text(good)
    assert row_o(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT)[0] == "PASS"


def test_probe_fake_io_terminal_receipt_without_console(api):
    """Execute the actual entry point against absent field prerequisites, not just its oracle."""
    r = api._runtime
    json_api = r.execute((REPO / "lua/json_codec.lua").read_text(encoding="utf-8"))
    cfg = {"profile": "pack.json", "title": "heartgold", "mode": "rtc-repeat", "rom_sha1": "2" * 40,
           "rom_md5": "1" * 32, "run_id": "fake", "boot_frames": 1, "requested_rate": 300,
           "code_sha256": MODEL_CUT["script_sha256"], "profile_sha256": MODEL_CUT["profile_sha256"], "source_head": "cut"}
    pack = {"schema": "gen4-profile-v1", "titles": {"heartgold": {"rom": {"sha1": cfg["rom_sha1"], "md5": cfg["rom_md5"]},
            "symbols": {"sRTCWork": {"address": 100}, "sFieldSysPtr": {"address": 200}, "sSaveDataPtr": {"address": 300}},
            "sites": {}, "profile": {}, "overlays": {}, "overlay_table": {}}}}
    r.globals().FAKE_CFG, r.globals().FAKE_PACK = json.dumps(cfg), json.dumps(pack)
    r.globals().FAKE_JSON = json_api
    r.execute('''
        SLINK_GEN4_PROBE_TEST=false; SLINK_ROOT="fake-root"; WRITES={}; FRAME=0
        os.getenv=function(key) if key=="SLINK_GEN4_PROBE_CONFIG" then return "cfg.json" end
            if key=="SLINK_GEN4_PROBE_OUT" then return "receipt.txt" end end
        dofile=function(path) if path:match("json_codec.lua$") then return FAKE_JSON end; error(path) end
        io.open=function(path,mode)
            if mode=="rb" then return {read=function() return path=="cfg.json" and FAKE_CFG or FAKE_PACK end,close=function() end} end
            WRITES[#WRITES+1]=path
            return {write=function(_,...) TERMINAL=table.concat({...}) end,close=function() end}
        end
        memory={getmemorydomainlist=function() return {} end,read_u32_le=function() return 1 end,
            read_bytes_as_array=function(_,n) local t={}; for i=1,n do t[i]=0 end; return t end}
        emu={getregisters=function() return {} end,getregister=function() error("bogus") end,
            framecount=function() return FRAME end,limitframerate=function() end}
        client={exit=function() EXITED=true end,speedmode=function() end}
        gameinfo={getromhash=function() return string.rep("1",32) end}
        event={}; joypad={set=function() end}
        console={log=function() error("console traffic forbidden") end}
    ''')
    r.execute(SCRIPT.read_text(encoding="utf-8"))
    assert list(r.globals().WRITES.values()) == ["receipt.txt"]
    assert r.globals().EXITED
    rows = parse_receipt(r.globals().TERMINAL, title="heartgold", rom_sha1="2" * 40, run_id="fake", expected_cut=MODEL_CUT)
    assert set(rows) == set(ROWS) and rows["l"][0] == "OPEN"


@pytest.mark.parametrize("guard", ["residency", "full_pin", "last_drain", "close_fault"])
def test_reverted_semantic_guard_is_detected(api, guard):
    from lupa import LuaRuntime

    source = SCRIPT.read_text(encoding="utf-8")
    replacements = {
        "residency": ('if site.image~="arm9" and not resident(site.overlay_id) then return nil end', ''),
        "full_pin": ('check(bytes(site.address,site.extent):lower()==site.register_hex:lower(), "full registration pin mismatch")', ''),
        "last_drain": ('for _,e in ipairs(reg:drain()) do self.ready_events[#self.ready_events+1]=e end', ''),
        "close_fault": ('self.failure="phase cleanup failed: "..phase', 'self.failure=nil'),
    }
    original, mutant = replacements[guard]
    assert source.count(original) == 1
    r = LuaRuntime(unpack_returned_tuples=True)
    r.globals().SLINK_GEN4_PROBE_TEST = True
    broken = r.execute(source.replace(original, mutant))
    if guard in {"last_drain", "close_fault"}:
        registry = r.execute((REPO / "lua/hook_registry.lua").read_text(encoding="utf-8"))
        measured = from_lua(broken.phase_controls(registry))
        assert measured["last_event"] != 1 if guard == "last_drain" else not measured["fault"]
    else:
        site = {"id": "x", "symbol": "s", "address": 100, "image": "ov1", "overlay_id": 1,
                "mode": "thumb", "extent": 8, "fire_hex": "04030201", "register_hex": "01020304ffffffff"}
        if guard == "residency":
            with pytest.raises(Exception, match="callback PC mismatch"):
                broken.capture(to_lua(r, site), 100, 0, 0, 0, r.eval("function() return false end"))
        else:
            title = {"symbols": {"s": {"address": 100, "image": "ov1", "mode": "thumb"}}, "overlays": {"1": {"ram": 100, "size": 8}}}
            # The mutant accepts corrupt bytes beyond the fire word; the original rejects.
            assert broken.validate_site(to_lua(r, title), to_lua(r, site), r.eval('function() return "0102030400000000" end'),
                                        r.eval("function() return true end"))
    assert api.evaluate("n", to_lua(api._runtime, examples()["n"])) == "PASS"


def receipt(row="a", status="PASS", **overrides):
    payload = {"title": "heartgold", "rom_sha1": "2" * 40, "level": "PHYSICAL", "run_id": "current", **MODEL_CUT, **overrides}
    return f"PROBE {row} {status} {json.dumps(payload)}\nRESULT: {status}\n"


@pytest.mark.parametrize("row", tuple("abcdefghijklmno"))
@pytest.mark.parametrize("field", tuple(MODEL_CUT))
def test_every_row_stale_cut_red_revert(row, field):
    def consume(text):
        return parse_receipt(text, title="heartgold", rom_sha1="2" * 40, expected_cut=MODEL_CUT)

    assert consume(receipt(row))[row][0] == "PASS"
    with pytest.raises(StaleReceiptError, match=f"STALE {field}"):
        consume(receipt(row, **{field: "old"}))
    assert consume(receipt(row))[row][0] == "PASS"


@pytest.mark.parametrize("field", tuple(MODEL_CUT))
def test_external_row_consumers_stale_cut_red_revert(tmp_path, field):
    path = tmp_path / "external.txt"

    def consume_o(value):
        path.write_text(value, encoding="utf-8")
        return row_o(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT)

    good = receipt("o", producer="C1-8", oracle="independent", negative_control="red")
    assert consume_o(good)[0] == "PASS"
    bad = receipt("o", producer="C1-8", oracle="independent", negative_control="red", **{field: "old"})
    with pytest.raises(StaleReceiptError, match=f"STALE {field}"):
        consume_o(bad)
    assert consume_o(good)[0] == "PASS"

    observation = examples()["f"]
    for sample in observation["sustained"].values():
        for record in (sample, sample["floor"]):
            record.update(MODEL_CUT, producer="gen4-PERF", result="PASS", level="PHYSICAL",
                          title="heartgold", rom_sha1="2" * 40, concurrent_load=False, ending_registered=0,
                          module_sha256={"lua/tests/probe_gen4_hooks.lua": digest(SCRIPT)}, frames_requested=3000)
    bundle = {"schema": "gen4-perf-bundle-v1", "producer": "gen4-PERF", "level": "PHYSICAL",
              "title": "heartgold", "rom_sha1": "2" * 40, "source_head": "cut", "observation": observation}

    def consume_f(value):
        path.write_text(json.dumps(value), encoding="utf-8")
        return perf_f(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT)

    assert consume_f(bundle)[1] is None
    bad = copy.deepcopy(bundle)
    bad["observation"]["sustained"]["one"][field] = "old"
    with pytest.raises(StaleReceiptError, match=f"STALE {field}"):
        consume_f(bad)
    assert consume_f(bundle)[1] is None


def test_committed_cut_refuses_working_file_or_head_drift(monkeypatch, tmp_path):
    script, profile = tmp_path / "probe.lua", tmp_path / "profile.json"
    script.write_bytes(b"return 1\r\n")
    profile.write_bytes(b"{}\n")
    blobs = {"probe.lua": b"return 1\n", "profile.json": b"{}\n"}
    monkeypatch.setattr(__import__(__name__, fromlist=["REPO"]), "REPO", tmp_path)

    def output(command, **kwargs):
        if command[1:3] == ["rev-parse", "HEAD"]:
            return "committed\n"
        assert command[:2] == ["git", "show"]
        assert command[2].startswith("committed:")
        return blobs[command[2].split(":", 1)[1]]

    monkeypatch.setattr(subprocess, "check_output", output)
    cut = committed_cut("heartgold", script=script, profile=profile)
    assert cut == {"source_head": "committed", "script_sha256": digest(script), "profile_sha256": digest(profile)}
    script.write_bytes(b"return 2\n")
    with pytest.raises(StaleReceiptError, match="STALE script_sha256"):
        committed_cut("heartgold", script=script, profile=profile)
    script.write_bytes(b"return 1\r\n")
    with pytest.raises(StaleReceiptError, match="STALE source_head"):
        committed_cut("heartgold", script=script, profile=profile, source_head="older")
    assert committed_cut("heartgold", script=script, profile=profile) == cut


@pytest.mark.parametrize("mutation", ["duplicate", "stale", "model", "wrong_rom", "tail", "false_pass"])
def test_receipt_rejection_controls(mutation):
    text = receipt()
    if mutation == "duplicate":
        text = text.splitlines()[0] + "\n" + text
    elif mutation == "stale":
        text = receipt(run_id="old")
    elif mutation == "model":
        text = receipt(level="MODEL")
    elif mutation == "wrong_rom":
        text = receipt(rom_sha1="0" * 40)
    elif mutation == "tail":
        text += "noise\n"
    else:
        text = receipt(status="OPEN").replace("RESULT: OPEN", "RESULT: PASS")
    with pytest.raises(AssertionError):
        parse_receipt(text, title="heartgold", rom_sha1="2" * 40, run_id="current", expected_cut=MODEL_CUT)
    assert "a" in parse_receipt(receipt(), title="heartgold", rom_sha1="2" * 40, run_id="current", expected_cut=MODEL_CUT)


def test_required_row_o_absent_open_present_wrong_fail(api, tmp_path):
    absent = row_o(None, "heartgold", "2" * 40, "cut")
    assert absent[0] == "OPEN"
    overall, rows = finish_rows(api, examples(), {}, absent)
    assert overall == "OPEN" and len(rows) == 15
    path = tmp_path / "o.txt"
    path.write_text(receipt("o", source_head="wrong", producer="C1-8", oracle="independent", negative_control="red"))
    with pytest.raises(StaleReceiptError, match="STALE source_head"):
        row_o(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT)
    path.write_text(receipt("o", source_head="cut", producer="C1-8", oracle="independent", negative_control="red"))
    assert finish_rows(api, examples(), {}, row_o(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT))[0] == "PASS"


def fixture_module():
    input_file(REPO / "tools/gen4_fixtures.py", "C1-4 fixture module")
    module = importlib.import_module("tools.gen4_fixtures")
    for name in ("write_nds_run_config", "stage_rom", "stage_save"):
        if not hasattr(module, name):
            pytest.skip(f"OPEN C1-4 function absent: tools.gen4_fixtures.{name}")
    return module


def save_setup(save):
    """Disclose permitted row-i synthesis; wrong present output binding is FAIL."""
    sidecar = Path(str(save) + ".synth.json")
    if not sidecar.exists():
        return {"setup": "NATIVE"}
    raw = sidecar.read_bytes()
    meta = json.loads(raw)
    assert isinstance(meta, dict), "SYNTH sidecar must be an object"
    for key in ("src_sha1", "out_sha1"):
        assert isinstance(meta.get(key), str) and re.fullmatch(r"[0-9a-fA-F]{40}", meta[key]), f"SYNTH invalid {key}"
    assert meta["out_sha1"].lower() == digest(save, "sha1"), "SYNTH sidecar output hash mismatch"
    pid = meta.get("new_pid")
    assert isinstance(pid, int) and not isinstance(pid, bool) and 0 <= pid <= 0xFFFFFFFF, "SYNTH invalid new_pid"
    return {"setup": "SYNTH", "sidecar_sha256": hashlib.sha256(raw).hexdigest(),
            "src_sha1": meta["src_sha1"].lower(), "out_sha1": meta["out_sha1"].lower(), "new_pid": pid}


def scenario_input(title):
    path = os.environ.get("SLINK_GEN4_PROBE_SCENARIO")
    if not path:
        return {}  # Missing routes stay OPEN in their rows; no guessed battle/save inputs.
    value = json.loads(input_file(Path(path), "normal-button scenario").read_text(encoding="utf-8"))
    assert value["schema"] == "gen4-probe-scenario-v1", "wrong scenario schema"
    return value["titles"].get(title, {})


def emulator_pids():
    command = "Get-CimInstance Win32_Process -Filter \"Name='EmuHawk.exe'\" | Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, timeout=15, check=True)
    values = json.loads(result.stdout) if result.stdout.strip() else []
    return values if isinstance(values, list) else [values]


def resolve_pack_route(route, recipes):
    """Convert pinned route_legs to bounded normal-button instructions for Lua."""
    assert isinstance(route, list) and isinstance(recipes, dict), "route/route_legs shape"
    resolved, reasons = [], []
    buttons = {"A", "B", "X", "Y", "Start", "Select", "Up", "Down", "Left", "Right", "L", "R"}
    for leg in route:
        if isinstance(leg, dict):  # Existing explicit frame/button scenario compatibility.
            frames, press = leg.get("frames"), leg.get("buttons", [])
            assert isinstance(frames, int) and not isinstance(frames, bool) and 0 < frames <= 12000, "invalid frame bound"
            assert isinstance(press, list) and all(isinstance(b, str) and b in buttons for b in press), "unsupported button input"
            resolved.append(copy.deepcopy(leg))
            continue
        assert isinstance(leg, str) and leg, "malformed route leg"
        recipe = recipes.get(leg)
        if recipe is None:
            reasons.append(f"button recipe absent for named route leg {leg}")
            continue
        assert isinstance(recipe, dict), f"{leg}: recipe must be an object"
        status = recipe.get("route_status")
        assert status in {"recipe_source", "open"}, f"{leg}: invalid route_status"
        assert recipe.get("evidence") in {"SOURCE", "FILE", "OPEN"}, f"{leg}: invalid recipe evidence"
        if status == "open":
            assert recipe.get("steps") == [] and recipe.get("until") is None, f"{leg}: malformed open recipe"
            assert isinstance(recipe.get("open"), str) and recipe["open"], f"{leg}: open recipe lacks reason"
            reasons.append(f"{leg}: {recipe['open']}")
            continue
        assert isinstance(recipe.get("source"), list) and recipe["source"], f"{leg}: source citation required"
        maximum, steps, predicate = recipe.get("max_frames"), recipe.get("steps"), recipe.get("until")
        assert isinstance(maximum, int) and not isinstance(maximum, bool) and 0 < maximum <= 12000, f"{leg}: invalid max_frames"
        assert isinstance(steps, list) and isinstance(predicate, dict), f"{leg}: steps/until required"
        assert isinstance(predicate.get("symbol"), str) and isinstance(predicate.get("deref", []), list), f"{leg}: invalid predicate"
        assert all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in predicate.get("deref", [])), f"{leg}: invalid dereference offsets"
        assert isinstance(predicate.get("offset"), int) and predicate["offset"] >= 0, f"{leg}: invalid target offset"
        tests = int("value" in predicate) + int(predicate.get("nonzero") is True) + int(predicate.get("zero") is True)
        assert tests == 1, f"{leg}: predicate needs exactly one comparison"
        if "value" in predicate:
            assert isinstance(predicate["value"], int) and not isinstance(predicate["value"], bool), f"{leg}: invalid predicate value"
        span = 0
        for step in steps:
            assert isinstance(step, dict), f"{leg}: malformed step"
            press = step.get("press")
            assert isinstance(press, list) and all(isinstance(b, str) and b in buttons for b in press), f"{leg}: unsupported button input"
            for key in ("hold_frames", "then_wait_frames"):
                value = step.get(key)
                assert isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"{leg}: invalid {key}"
                span += value
        assert span <= maximum, f"{leg}: steps exceed max_frames"
        resolved.append({"name": leg, "steps": copy.deepcopy(steps), "until": copy.deepcopy(predicate),
                         "max_frames": maximum, "source": copy.deepcopy(recipe["source"])})
    return ([] if reasons else resolved), reasons


def phase_case_plan(cases, blocked, recipes=None):
    """Validate present descriptors; missing fixtures/recipes/caller coverage stay OPEN.

    Pack route strings are leg references, not button recipes. Never send them to
    Lua's dictionary-based route player or treat them as observed execution.
    """
    assert isinstance(cases, list) and isinstance(blocked, list), "phase case inventories must be arrays"
    names, families, reasons = set(), set(), []
    for case in [*cases, *blocked]:
        assert isinstance(case, dict), "phase descriptor must be an object"
        name = case.get("name")
        assert isinstance(name, str) and re.fullmatch(r"[\w.-]+", name), "invalid phase case name"
        assert name not in names, f"duplicate active/blocked phase case {name}"
        names.add(name)
        families.add("reset" if name == "reset" else case.get("phase", name))
    for case in blocked:
        why = case.get("blocked_reason")
        assert isinstance(why, str) and why.strip(), f"blocked phase {case['name']} lacks a named reason"
        reasons.append(f"{case['name']}: {why}")
    for family in sorted({"battle", "pc", "reset"} - families):
        reasons.append(f"{family}: required phase case absent")
    resolved_cases = []
    for case in cases:
        name, sites = case["name"], case.get("sites")
        assert isinstance(sites, list) and 1 <= len(sites) <= 3, f"{name}: production sites must fit cap 3"
        assert all(isinstance(site, str) for site in sites) and len(set(sites)) == len(sites), f"{name}: duplicate/invalid site"
        assert case.get("producer_site") in sites, f"{name}: producer observer must match a selected site"
        assert isinstance(case.get("predicate"), dict) and isinstance(case.get("source"), str) and case["source"], f"{name}: predicate/source required"
        uncovered = case.get("open", [])
        assert isinstance(uncovered, list) and all(isinstance(why, str) for why in uncovered), f"{name}: invalid open-caller list"
        reasons.extend(f"{name}: {why}" for why in uncovered)
        route = case.get("route")
        if route is None or route == []:
            reasons.append(f"{name}: normal-button route absent")
            continue
        assert isinstance(route, list), f"{name}: route must be an array"
        resolved, route_reasons = resolve_pack_route(route, recipes or {})
        reasons.extend(f"{name}: {why}" for why in route_reasons)
        resolved_cases.append({**case, "route": resolved})
    return ([] if reasons else resolved_cases), reasons


def launch_probe(module, title, source, save, profile, base, case, lane, cfg):
    expected_cut = committed_cut(title, profile=profile, source_head=cfg["source_head"])
    bind_cut({"script_sha256": cfg["code_sha256"], "profile_sha256": cfg["profile_sha256"],
              "source_head": cfg["source_head"]}, expected_cut)
    """Fresh private directory; only this Popen's PID is ever stopped. Preserve failures."""
    assert not lane.exists(), f"refusing stale run directory {lane}"
    lane.mkdir(parents=True)
    staged = module.stage_rom(source, lane)
    rom = staged.parent / "probe.nds"
    staged.rename(rom)
    # Only the j control mutates a private copy; one header padding byte, not game data.
    if case == "patched-rom":
        raw = bytearray(rom.read_bytes())
        raw[-1] ^= 1
        rom.write_bytes(raw)
    battery = module.stage_save(save, lane, cfg["rom_sha1"], rom_basename=rom.name)
    config_path = lane / "config.ini"
    settings = module.write_nds_run_config(base, config_path, initial_time=cfg["initial_time"],
                                          lane_saveram_dir=battery.parent, saveram_name_hint=battery.name)
    if case == "rtc-unpinned":
        settings["CoreSyncSettings"][CORE]["UseRealTime"] = True
        config_path.write_text(json.dumps(settings), encoding="utf-8")
    mode = "persistence" if cfg.get("persistence") else "baseline" if case.startswith(("baseline", "phase-")) else case
    cfg = dict(cfg, mode=mode, profile=str(profile).replace("\\", "/"),
               run_id=lane.parent.name + "/" + lane.name, state_path=str(lane / "reload.State").replace("\\", "/"))
    request, response = lane / "perf-ready.txt", lane / "perf-processes.json"
    cfg["perf_request"], cfg["perf_response"] = str(request), str(response)
    cfg["jit"] = settings["CoreSyncSettings"][CORE]["EnableJIT"]
    cfg["use_real_time"] = settings["CoreSyncSettings"][CORE]["UseRealTime"]
    if case == "patched-rom":
        cfg["allow_hash_control"] = True
    cfg_path, out = lane / "probe.json", lane / "receipt.txt"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    shutil.copyfile(SCRIPT, lane / "probe.lua")
    env = dict(os.environ, SLINK_ROOT=str(REPO).replace("\\", "/"), SLINK_GEN4_PROBE_CONFIG=str(cfg_path),
               SLINK_GEN4_PROBE_OUT=str(out))
    emulator = os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe")
    input_file(Path(emulator), "EmuHawk")
    proc = subprocess.Popen([emulator, "--config=config.ini", "--lua=probe.lua", "rom/probe.nds"],
                            cwd=lane, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    deadline = time.monotonic() + int(os.environ.get("SLINK_GEN4_PROBE_TIMEOUT", "600"))
    try:
        while proc.poll() is None and time.monotonic() < deadline:
            if request.is_file() and not response.is_file():
                inventory = {"foreign_pids": [pid for pid in emulator_pids() if pid != proc.pid],
                             "checked_at_utc": datetime.datetime.now(datetime.UTC).isoformat()}
                temp = response.with_suffix(".tmp")
                temp.write_text(json.dumps(inventory), encoding="utf-8")
                temp.replace(response)
            if out.is_file():
                tail = out.read_text(encoding="utf-8").splitlines()[-1:]
                if tail and tail[0] in {"RESULT: PASS", "RESULT: FAIL", "RESULT: OPEN"}:
                    break
            time.sleep(0.25)
        assert out.is_file(), f"no terminal probe receipt in {lane}; exit={proc.poll()}"
        text = out.read_text(encoding="utf-8")
        committed_cut(title, profile=profile, source_head=cfg["source_head"])
        rows = parse_receipt(text, title=title, rom_sha1=cfg["rom_sha1"], run_id=cfg["run_id"], expected_cut=expected_cut)
        assert set(rows) == set(ROWS), f"missing a--n rows: {set(ROWS) - set(rows)}"
        for _, payload in rows.values():
            assert payload["script_sha256"] == digest(SCRIPT) and payload["profile_sha256"] == digest(profile), "wrong source/profile receipt"
            assert payload["callback_errors"] == 0, f"callback faults: {lane}"
        assert proc.poll() is not None or time.monotonic() < deadline, f"probe timed out: {lane}"
        # Let client.exit flush its battery. A forced termination is never durability evidence.
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail(f"EmuHawk did not exit gracefully after terminal receipt: {lane}")
        return rows, battery
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def codec_module():
    input_file(REPO / "server/adapters/gen4_codec.py", "C1-3 independent PYDEC codec")
    return importlib.import_module("server.adapters.gen4_codec")


def source_witness(codec, decoded):
    """Footer geometry and trainer bytes come from the independent source-save decoder."""
    footer = decoded.general[-decoded.profile.footer_size:]
    assert decoded.profile.footer_fields == ("count", "size", "magic", "slot", "crc"), "unhandled footer format"
    assert decoded.profile.player_off is not None, "PlayerProfile offset unavailable"
    start = decoded.profile.player_off + 4
    decoded.player()  # Exercise the independent decoder before using this witness.
    return {"signature_footer_offset": 4, "signature_hex": footer[4:-2].hex(),
            "identity_hex": decoded.general[start:start + 20].hex()}


def census_file_pins(source, artifact, title, internal_loads=()):
    generator = importlib.import_module("tools.gen_gen4_pack")
    images = generator.load_images(source, raw_arm9=title == "heartgold_hge")
    result = {}
    for name in ("HandleLoadOverlay", "UnloadOverlayByID", *(entry["symbol"] for entry in internal_loads)):
        site = next(s for s in artifact["sites"].values() if s["symbol"] == name)
        measured = images.read(site["image"], site["address"], site["extent"]).hex()
        assert measured == site["register_hex"], f"present declared-image FILE pin mismatch: {name}"
        assert int.from_bytes(bytes.fromhex(measured[:8]), "little") == int(site["fire_hex"], 16), "fire pin endian mismatch"
        result[name] = measured
    return result


def mutation_specs(codec, decoded, artifact, scenario):
    """Modify existing native records only; no new mon, flags, story or synthetic fixture."""
    p = artifact["profile"]
    if p.get("party_off") is None:
        return None, "i: pack party geometry is OPEN"
    party = decoded.party()
    if not party:
        return None, "i: played fixture has no party mon"
    index = scenario.get("party_slot", 0)
    assert 0 <= index < len(party), "wrong party slot"
    mon = party[index]
    assert mon["tail_plausible"] and mon["hp"] > 0, "wrong/invalid source party representation"
    if mon["hp"] <= 1:
        return None, "i: fixture needs a naturally healthy party mon (>1 HP)"
    offset = decoded.profile.party_off + 8 + index * codec.PARTY_MON_SIZE
    raw = decoded.general[offset:offset + codec.PARTY_MON_SIZE]
    plain = bytearray(codec.decrypt_party(raw))
    target = mon["hp"] - 1
    struct.pack_into("<H", plain, codec.TAIL_OFF + 6, target)
    after = codec.encrypt_party(bytes(plain))
    assert codec.decode_party_mon(after, decoded.profile)["hp"] == target
    assert raw[:codec.TAIL_OFF] == after[:codec.TAIL_OFF], "HP-only edit changed box checksum/body"

    def changes(before, after):
        return [{"offset": i, "value": b} for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]

    party_spec = {"operation": "party-write", "array_id": p["save"]["array_ids"]["party"],
                  "record_offset": p["party_off"]["mons_off"] + index * p["pkm"]["party_size"],
                  "flags_offset": 4, "before_hex": raw.hex(), "after_hex": after.hex(),
                  "write": True, "changes": changes(raw, after)}
    specs = {"party-write": party_spec, "no-write": dict(party_spec, operation="no-write", write=False, changes=[]),
             "slot": index, "key": mon["key"], "original": mon["hp"], "target": target}
    if p.get("pc", {}).get("box_modified_flag_off") is None:
        specs["box_open"] = "i: pack box modified geometry is OPEN"
        return specs, None
    occupied = [(box, slot, m) for box, data in enumerate(decoded.boxes()) for slot, m in data["mons"].items()]
    if not occupied:
        specs["box_open"] = "i: played fixture needs an existing occupied PC slot for modified-bit control"
        return specs, None
    box, slot, box_mon = occupied[0]
    pc_off = decoded.profile.boxes_off + box * decoded.profile.box_stride + slot * codec.BOX_MON_SIZE
    raw_box = decoded.pc[pc_off:pc_off + codec.BOX_MON_SIZE]
    box_plain = bytearray(codec.decrypt_box(raw_box))
    box_target = box_mon["friendship"] ^ 1
    box_plain[codec.HEADER_SIZE + 0xC] = box_target
    after_box = codec.encrypt_box(bytes(box_plain))
    assert codec.decode_box_mon(after_box, decoded.profile)["friendship"] == box_target
    box_spec = {"operation": "box-write", "array_id": p["save"]["array_ids"]["pcstorage"],
                "record_offset": p["pc"]["box_base"] + box * p["pc"]["box_stride"] + slot * p["pc"]["mon_stride"],
                "flags_offset": 4, "box": box, "before_hex": raw_box.hex(), "after_hex": after_box.hex(),
                "write": True, "dirty": True, "changes": changes(raw_box, after_box)}
    return {**specs, "box-write": box_spec, "box-no-dirty": dict(box_spec, operation="box-no-dirty", dirty=False),
            "box": box, "box_slot": slot, "box_key": box_mon["key"], "box_original": box_mon["friendship"],
            "box_target": box_target}, None


def save_driver_complete(trace):
    if not isinstance(trace, list) or len(trace) < 3:
        return False
    first = trace[0]
    if first.get("state") != 1 or first.get("driver", 0) <= 0 or first.get("data", 0) <= 0:
        return False
    previous, active = -1, False
    for row in trace:
        if (row.get("driver") != first["driver"] or row.get("data") != first["data"]
                or not isinstance(row.get("frame"), int) or isinstance(row["frame"], bool)
                or row["frame"] < 0 or row["frame"] < previous
                or not isinstance(row.get("state"), int) or isinstance(row["state"], bool)
                or not 1 <= row["state"] <= 7):
            return False
        previous = row["frame"]
        active |= 2 <= row["state"] <= 7
    return active and trace[-1]["state"] == 1 and trace[-1]["frame"] > first["frame"]


def persistence_rows(module, codec, decoded, title, source, save, profile, artifact, base, batch, cfg):
    if not cfg.get("persistence_route"):
        return None, "i: native SAVE normal-button route absent"
    specs, reason = mutation_specs(codec, decoded, artifact, cfg)
    if specs is None:
        return None, reason
    samples, written_battery, save_driver_cases = {}, None, {}
    for case in ("party-write", "no-write", "box-write", "box-no-dirty"):
        if case not in specs:
            continue
        rows, battery = launch_probe(module, title, source, save, profile, base, case, batch / case,
                                     {**cfg, "persistence": specs[case]})
        status, payload = rows["i"]
        if status == "FAIL":
            raise AssertionError(f"persistence instrumentation FAIL: {batch / case}: {payload}")
        observation = payload.get("observation")
        if not observation or observation.get("save_finish_hits", 0) < 1:
            return None, payload.get("reason", f"i: {case} native-save evidence absent")
        trace = observation.get("save_driver_trace")
        if trace is None:
            return None, f"i: {case} save-driver state trace absent"
        assert save_driver_complete(trace), f"{case}: native save-driver active-to-idle transition absent"
        save_driver_cases[case] = trace
        result = codec.parse_save(battery.read_bytes(), decoded.profile)
        assert codec.counter_newer(result.counter, decoded.counter) > 0, f"{case}: no newer coherent native save bank"
        if case.startswith("box"):
            mon = result.boxes()[specs["box"]]["mons"][specs["box_slot"]]
            assert mon["key"] == specs["box_key"], "box identity drift"
            samples[case] = mon["friendship"]
        else:
            mon = result.party()[specs["slot"]]
            assert mon["key"] == specs["key"], "party identity drift"
            samples[case] = mon["hp"]
            if case == "party-write":
                written_battery = battery
    assert written_battery is not None
    # Cold boot a second isolated emulator from the actual newly written battery.
    cold_cfg = dict(cfg, save_witness=source_witness(codec, codec.parse_save(written_battery.read_bytes(), decoded.profile)),
                    cold_readback=specs["party-write"])
    cold, _ = launch_probe(module, title, source, written_battery, profile, base, "cold-reload", batch / "cold-reload", cold_cfg)
    runtime = cold["i"][1].get("observation", {})
    if not runtime.get("runtime_hex"):
        return None, cold["i"][1].get("reason", "i: cold RAM party readback absent")
    reloaded = codec.decode_party_mon(bytes.fromhex(runtime["runtime_hex"]), decoded.profile)
    assert reloaded["key"] == specs["key"], "cold-reload identity drift"
    return {"written": samples["party-write"], "no_write": samples["no-write"], "original": specs["original"],
            "target": specs["target"], "box_dirty": samples.get("box-write"), "box_without_dirty": samples.get("box-no-dirty"),
            "box_original": specs.get("box_original"), "box_target": specs.get("box_target"), "cold_reload": reloaded["hp"],
            "box_open": specs.get("box_open"),
            "save_driver_cases": save_driver_cases,
            "save_completed": len(save_driver_cases) == 4 and all(save_driver_complete(trace) for trace in save_driver_cases.values()),
            "oracle": "save-driver active-to-idle state reads + server.adapters.gen4_codec.parse_save + independent cold RAM PK4 decode"}, None
@pytest.mark.live
@pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="OPEN G1 physical probe requires SLINK_LIVE=1; one owned emulator lane")
@pytest.mark.parametrize("title", TITLE_PACK)
def test_gen4_hook_probe(api, title):
    module = fixture_module()
    pins = importlib.import_module("tools.gen4_pins")
    source = Path(os.environ.get("SLINK_GEN4_" + title.upper(), pins.default_locations().roms[title]))
    input_file(source, f"{title} ROM")
    profile = input_file(REPO / "data/games" / TITLE_PACK[title] / "profile.json", f"C1-2 {title} profile")
    save_env = "SLINK_GEN4_" + title.upper() + "_SAVE"
    if not os.environ.get(save_env):
        pytest.skip(f"OPEN populated played save: {save_env} unset")
    save = input_file(Path(os.environ[save_env]), f"{title} played save")
    base = input_file(Path(os.environ.get("SLINK_BIZHAWK_CONFIG", "E:/Howard/Bizhawk/config.ini")), "BizHawk base config")
    pack = json.loads(profile.read_text(encoding="utf-8"))
    assert pack["schema"] == "gen4-profile-v1", "wrong profile schema"
    rom_sha1, rom_md5 = digest(source, "sha1"), digest(source, "md5")
    artifact = pack["titles"][title]
    assert artifact["rom"]["sha1"] == rom_sha1 and artifact["rom"]["md5"] == rom_md5, "present ROM/profile mismatch"
    cut = committed_cut(title, profile=profile)
    source_head = cut["source_head"]
    supplied = scenario_input(title)
    cfg = {"title": title, "rom_sha1": rom_sha1, "rom_md5": rom_md5, "jit": False, "use_real_time": False,
           "requested_rate": 300, "initial_time": "2010-01-01T12:00:00", "sample_frames": 600,
           "boot_frames": 6000, "phase_max": max(artifact["phases"][name]["cap"] for name in ("battle", "pc")),
           "qualify_performance": os.environ.get("SLINK_GEN4_PROBE_QUALIFY") == "1",
           **supplied}
    assert cfg["requested_rate"] == 300, "development route must request 300%"
    assert cfg["sample_frames"] >= 120 and cfg["boot_frames"] > 0, "invalid sample windows"
    cfg["code_sha256"], cfg["profile_sha256"], cfg["source_head"] = cut["script_sha256"], cut["profile_sha256"], source_head
    codec = codec_module()
    decoded = codec.parse_save(save.read_bytes(), "hge" if title == "heartgold_hge" else "hgss")
    cfg["save_witness"] = source_witness(codec, decoded)
    cfg["census_image_bytes"] = census_file_pins(source, artifact, title, cfg.get("internal_loads", ()))
    if "phase_cases" not in cfg and artifact.get("phase_cases"):
        cfg["phase_cases"] = artifact["phase_cases"]
    # Blockers are authoritative pack input, not an opt-out supplied by a scenario.
    cfg["phase_cases_blocked"] = artifact.get("phase_cases_blocked", [])
    assert cfg["phase_max"] == max(artifact["phases"][name]["cap"] for name in ("battle", "pc")) <= 3, "wrong production hook cap"
    recipes = artifact.get("route_legs", {})
    cfg["route_open_reasons"] = {}
    for key in ("route", "persistence_route"):
        cfg[key], why = resolve_pack_route(cfg.get(key, artifact.get(key, [])), recipes)
        cfg["route_open_reasons"][key] = why
    cfg.update(save_setup(save))
    if cfg["setup"] == "SYNTH":
        assert cfg["new_pid"] in {mon["pid"] for mon in decoded.party()}, "SYNTH sidecar new_pid absent from decoded party"
    if os.environ.get("SLINK_GEN4_PROBE_SKIP_PERF_REASON"):
        cfg["skip_perf_reason"] = os.environ["SLINK_GEN4_PROBE_SKIP_PERF_REASON"]
    root = Path(os.environ.get("SLINK_GEN4_PROBE_RUNS", "C:/slink/g4/probe-gates"))
    assert " " not in str(root.resolve()) and "google drive" not in str(root.resolve()).lower(), "short non-Drive lane root required"
    batch = root / (title + "-" + uuid.uuid4().hex[:12])
    batch.mkdir(parents=True, exist_ok=False)
    before_save = digest(save)
    observations, errors = {}, {}
    try:
        collected = {}
        for case in ("baseline", "rtc-repeat", "rtc-unpinned", "no-buttons", "patched-rom"):
            rows, battery = launch_probe(module, title, source, save, profile, base, case, batch / case, cfg)
            collected[case] = rows
        for row, (status, payload) in collected["baseline"].items():
            if payload.get("observation") is not None:
                observations[row] = payload["observation"]
            if status == "FAIL" or payload.get("observation") is None:
                errors[row] = (status, payload)
        if "j" in observations:
            observations["j"]["patched_hash"] = collected["patched-rom"]["j"][1].get("observation", {}).get("hash")
        if "k" in observations:
            repeat = collected["rtc-repeat"]["k"][1].get("observation", {})
            unpinned = collected["rtc-unpinned"]["k"][1].get("observation", {})
            observations["k"].update(second=repeat.get("first"), frame_second=repeat.get("frame_first"), unpinned=unpinned.get("first"))
        if "l" in observations:
            observations["l"]["no_buttons_overworld"] = collected["no-buttons"]["l"][1].get("observation", {}).get("overworld")
        persistence, reason = persistence_rows(module, codec, decoded, title, source, save, profile, artifact, base, batch, cfg)
        if persistence is not None:
            observations["i"] = persistence
            errors.pop("i", None)
        else:
            errors["i"] = ("OPEN", {"reason": reason})
        if cfg.get("phase_cases") or cfg.get("phase_cases_blocked"):
            runnable, reasons = phase_case_plan(cfg.get("phase_cases", []), cfg["phase_cases_blocked"], recipes)
            measured = []
            if reasons:
                errors["n"] = ("OPEN", {"reason": "n: " + "; ".join(reasons),
                                        "phase_cases": [case["name"] for case in cfg.get("phase_cases", [])],
                                        "phase_cases_blocked": cfg["phase_cases_blocked"]})
            for index, case in enumerate(runnable):
                rows, _ = launch_probe(module, title, source, save, profile, base, f"phase-{index}", batch / f"phase-{index}",
                                       {**cfg, "phase_case": case, "route": case["route"]})
                p = rows["n"][1].get("observation", {}).get("physical")
                assert p is not None, f"phase case lacks physical measurement: {case['name']}"
                measured.append(p)
            if "n" in observations and measured:
                observations["n"]["physical"] = {
                    "first_expected": sum(p["first_expected"] for p in measured), "first_seen": sum(p["first_seen"] for p in measured),
                    "last_expected": sum(p["last_expected"] for p in measured), "last_seen": sum(p["last_seen"] for p in measured),
                    "static_pc": any(p["static_pc"] for p in measured), "reset": any(p["reset"] for p in measured),
                    "peak": max(p["peak"] for p in measured), "live_after_close": sum(p["live_after_close"] for p in measured),
                    "max_cost": max(p["max_cost"] for p in measured),
                    "pending_at_close": sum(p["pending_at_close"] for p in measured),
                    "second_drain": sum(p["second_drain"] for p in measured),
                    "baseline_fps": 1, "restored_fps": min(p["restored_fps"] / p["baseline_fps"] for p in measured),
                    "cases": measured,
                }
                errors.pop("n", None)
        performance = os.environ.get("SLINK_GEN4_PERF_RECEIPT")
        if performance:
            observed_perf, perf_reason = perf_f(performance.format(title=title), title, rom_sha1, source_head)
            if observed_perf is not None:
                observations["f"] = observed_perf
                errors.pop("f", None)
            else:
                errors["f"] = ("OPEN", {"reason": perf_reason})
        external = os.environ.get("SLINK_GEN4_ROW_O")
        required_o = row_o(Path(external.format(title=title)) if external else None, title, rom_sha1, source_head)
        result, rows = finish_rows(api, observations, errors, required_o)
        committed_cut(title, profile=profile, source_head=source_head)
        text = []
        for row, (status, payload) in rows.items():
            payload = {**payload, "schema": "gen4-probe-row-v1", "title": title, "rom_sha1": rom_sha1,
                       "source_head": source_head, "level": "PHYSICAL", "run_id": batch.name,
                       "script_sha256": digest(SCRIPT), "profile_sha256": digest(profile), "requested_rate": 300}
            if row != "o":
                payload.update(save_setup(save))
            text.append(f"PROBE {row} {status} {json.dumps(payload, sort_keys=True)}")
        text.append(f"RESULT: {result}")
        (batch / "combined.txt").write_text("\n".join(text) + "\n", encoding="utf-8")
        assert result != "FAIL", f"G1 FAIL; preserved receipt {batch / 'combined.txt'}"
        if result == "OPEN":
            missing = "; ".join(f"{row}: {payload.get('reason')}" for row, (status, payload) in rows.items() if status == "OPEN")
            pytest.skip(f"OPEN G1 {title}: {missing}; receipt {batch / 'combined.txt'}")
    finally:
        assert digest(save) == before_save, "original save was modified"
