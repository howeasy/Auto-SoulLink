"""G1 a--n authoring/replay and opt-in serial PHYSICAL collection.

Offline: python -m pytest tests/live/test_gen4_probe_gates.py -m 'not live' -q
Live (coordinator's one lane): SLINK_LIVE=1 python -m pytest this_file -m live -q -rs
Committed data/gen4/scenarios/<title>.json selects baseline and row-i saves.
SLINK_GEN4_PROBE_SCENARIO can select another committed inventory file; SLINK_GEN4_ROW_O supplies faint evidence.
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
import sys
import time
import uuid
from pathlib import Path, PurePosixPath

import pytest

from tests.unit.test_gen4_evidence import model_surface  # noqa: F401
from tools import gen4_evidence, gen4_pins
from tools.gen4_fixtures import lane_root, replace_with_retry

pytestmark = pytest.mark.usefixtures("model_surface")

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "lua/tests/probe_gen4_hooks.lua"
ROWS = tuple("abcdefghijklmn")
ROW_RE = re.compile(r"^PROBE ([a-o]) (PASS|FAIL|OPEN) (\{.*\})$")
TITLE_PACK = {"heartgold": "gen4_hgss", "soulsilver": "gen4_hgss", "heartgold_hge": "gen4_hge"}
CORE = "BizHawk.Emulation.Cores.Consoles.Nintendo.NDS.NDS"
MODEL_CUT = {"script_sha256": "1" * 64, "profile_sha256": "2" * 64, "source_head": "cut"}
MODEL_CUT.update(receipt_kind="probe", script="model.lua",
                 module_sha256={"lua/tests/probe_gen4_hooks.lua": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(), "reads": "bound"})
MODEL_CUT["surface_sha256"] = gen4_evidence.surface_hash("probe", MODEL_CUT["module_sha256"])


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


StaleReceiptError = gen4_evidence.StaleEvidenceError


def committed_cut(title, *, script=SCRIPT, profile=None, source_head=None):
    if profile is not None and Path(profile).resolve() != (REPO / "data/games" / TITLE_PACK[title] / "profile.json").resolve():
        raise StaleReceiptError("STALE profile: not the declared title pack")
    relative = Path(script).relative_to(REPO).as_posix()
    kind = next((k for k, path in gen4_evidence.SCRIPTS.items() if path == relative), None)
    if kind is None:
        raise StaleReceiptError(f"STALE unsupported receipt script: {relative}")
    cut = gen4_evidence.snapshot(kind, title, repo=REPO)
    cut["rom_sha1"] = gen4_pins.ROM_SPECS[title][0]
    return cut


def bind_cut(payload, expected_cut, *, title=None, rom_sha1=None):
    gen4_evidence.bind(payload, expected_cut, title=title or expected_cut["title"], rom_sha1=rom_sha1 or expected_cut["rom_sha1"])


def parse_receipt(text: str, *, title: str, rom_sha1: str, run_id: str | None = None, expected_cut=None) -> dict:
    """No stale neighbour, duplicate row, wrong artifact, MODEL-as-PHYSICAL or tail accepted."""
    lines = text.splitlines()
    automatic_cut = expected_cut is None
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
        row_cut = committed_cut(title, script=REPO / gen4_evidence.SCRIPTS["faint"]) if automatic_cut and row == "o" and payload.get("producer") == "C1-8" else expected_cut
        bind_cut(payload, row_cut, title=title, rom_sha1=rom_sha1)
        if row_cut["receipt_kind"] == "probe":
            bind_scenarios(payload, title, required=row_cut.get("script") != "model.lua")
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
    rows = parse_receipt(path.read_text(encoding="utf-8"), title=title, rom_sha1=sha1, expected_cut=expected_cut)
    assert "o" in rows, "present C1-8 input contains no row o"
    status, payload = rows["o"]
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
    assert bundle["schema"] == "gen4-perf-bundle-v1" and bundle["producer"] == "gen4-PERF", "wrong PERF producer/schema"
    assert bundle["level"] == "PHYSICAL" and bundle["title"] == title and bundle["rom_sha1"] == rom_sha1, "wrong PERF artifact/evidence"
    observation = bundle.get("observation")
    if observation is None:
        return None, bundle.get("reason", "gen4-PERF required samples absent")

    def bind(sample):
        bind_cut(sample, expected_cut, title=title, rom_sha1=rom_sha1)
        assert sample["producer"] == "gen4-PERF" and sample["result"] == "PASS" and sample["level"] == "PHYSICAL", "incomplete PERF sample/floor"
        assert sample["title"] == title and sample["rom_sha1"] == rom_sha1, "PERF sample/floor binding mismatch"
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
                   "throttle_config": {"Unthrottled": False, "ClockThrottle": True, "SpeedPercent": 100, "FrameSkip": 0, "AutoMinimizeSkipping": False, "VSyncThrottle": False, "SuperHawkThrottle": False},
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
              "box_target": 2, "box_original": 1, "box_without_dirty": 2, "box_cold_reload": 2,
              "box_without_dirty_cold_reload": 2, "cold_reload": 9, "save_completed": True,
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
                           # orchestration MODELs reuse this block as each phase case's measurement: it is a
                           # valid closing-frame case so the aggregate's battle_close requirement is met
                           "close_boundary_required": True, "oracle_frames": [7], "seen_frames": [7],
                           "oracle_steps": [1], "seen_steps": [1],
                           "close_boundaries": [{"frame": 7, "pending": 1, "predicate_before": True, "predicate_after": False,
                                                 "producer_frames": [7], "producer_steps": [1], "fall_step_id": 1,
                                                 "seam": "pre_close"}],
                           "cases": [{"phase": name, "first_expected": 1, "first_seen": 1, "last_expected": 1, "last_seen": 1,
                                      "peak": 3, "live_after_close": 0, "second_drain": 0,
                                      "max_cost": 0.001, "restored_fps": 200, "baseline_fps": 200}
                                     for name in ("battle", "pc", "reset")] + [
                               {"phase": "battle_close", "first_expected": 1, "first_seen": 1, "last_expected": 1, "last_seen": 1,
                                "peak": 3, "live_after_close": 0, "second_drain": 0,
                                "max_cost": 0.001, "restored_fps": 200, "baseline_fps": 200,
                                "close_boundary_required": True, "oracle_frames": [7], "seen_frames": [7],
                                "oracle_steps": [1], "seen_steps": [1],
                                "close_boundaries": [{"frame": 7, "pending": 1, "predicate_before": True, "predicate_after": False,
                                                      "producer_frames": [7], "producer_steps": [1], "fall_step_id": 1,
                                                      "seam": "pre_close"}]}],
                           "max_cost": 0.001, "restored_fps": 200, "baseline_fps": 200}},
    }


NEGATIVES = {
    "a": ("negative_hits", 1), "b": ("active_fault", False), "c": ("quiet_changes", 1),
    "d": ("host_hits", 1), "e": ("reloaded", 1), "f": ("sustained", {"zero": {"requested_rate": 300, "frames": 3000}}),
    "g": ("bogus_refused", False), "h": ("signature_rejected", False),
    "i": ("box_cold_reload", 1), "j": ("patched_hash", "1" * 32),
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


def test_owner_census_two_frames_allowed_three_red_and_revert(api):
    value = examples()["c"]
    value["changes"][0]["frame"] = value["causes"][0]["frame"] + 2
    assert api.evaluate("c", to_lua(api._runtime, value)) == "PASS"
    value["changes"][0]["frame"] += 1
    assert api.evaluate("c", to_lua(api._runtime, value))[0] == "FAIL"
    value["changes"][0]["frame"] -= 1
    assert api.evaluate("c", to_lua(api._runtime, value)) == "PASS"


def test_owner_box_persistence_flag_observational_reload_loss_red(api):
    value = examples()["i"]
    value.update(box_without_dirty=value["box_target"], box_cold_reload=value["box_target"],
                 box_without_dirty_cold_reload=value["box_target"], dirty_flag_observations={"set": 0, "not_set": 0})
    assert api.evaluate("i", to_lua(api._runtime, value)) == "PASS"
    value["box_cold_reload"] = value["box_original"]
    assert api.evaluate("i", to_lua(api._runtime, value))[0] == "FAIL"
    value["box_cold_reload"] = value["box_target"]
    assert api.evaluate("i", to_lua(api._runtime, value)) == "PASS"


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


def test_pc_facing_boot_stops_title_inputs_when_field_live(api):
    r = api._runtime
    r.execute('''FRAME=0; BUSY=0; IDLE_INPUTS=0
        live=function() return FRAME>=120 end
        idle=function() return live() and BUSY==0 end
        step=function(buttons)
            if live() and (buttons.A or buttons.Start) then BUSY=80; IDLE_INPUTS=IDLE_INPUTS+1 end
            if BUSY>0 then BUSY=BUSY-1 end
            FRAME=FRAME+1
        end
        frame=function() return FRAME end''')
    result = api.boot("persistence", 500, r.globals().idle, r.globals().live, r.globals().step, r.globals().frame)
    assert result.overworld and r.globals().IDLE_INPUTS == 0
    assert result.boot_inputs.A > 0 and result.boot_inputs.Start > 0
    assert result.boot_frame < 500
    assert result.first_field_live_frame == 120


def test_a_live_field_with_no_idle_stalls_the_boot_instead_of_overworld(api):
    """F3 (OMP cx-b86e97a1): with the field live but never idle, the boot stays bounded and reports
    overworld=false at the limit, never claiming the overworld and never hanging."""
    r = api._runtime
    r.execute('''FRAME=0; INPUTS=0
        live=function() return FRAME>=1 end
        idle=function() return false end
        step=function(buttons) INPUTS=INPUTS+1; FRAME=FRAME+1 end
        frame=function() return FRAME end''')
    result = api.boot("persistence", 50, r.globals().idle, r.globals().live, r.globals().step, r.globals().frame)
    assert result.first_field_live_frame == 1
    assert result.overworld is False
    assert result.boot_frame == 50 and r.globals().INPUTS == 50
    assert result.other_boot_buttons == 0


def test_inputs_keep_flowing_until_the_field_is_live_and_idle_still_wins(api):
    """The mirror case: idle() is reachable before the field gate closes, so A/Start keep flowing up to the
    live frame, then stop, and the boot still completes."""
    r = api._runtime
    r.execute('''FRAME=0; LAST_INPUT=-1
        live=function() return FRAME>=140 end
        idle=function() return FRAME>=100 end
        step=function(buttons)
            if buttons.A or buttons.Start then LAST_INPUT=FRAME end
            FRAME=FRAME+1
        end
        frame=function() return FRAME end''')
    result = api.boot("persistence", 500, r.globals().idle, r.globals().live, r.globals().step, r.globals().frame)
    assert result.overworld is True
    assert 100 < r.globals().LAST_INPUT < 140
    assert result.boot_frame > 140
    assert result.boot_inputs.A > 0 and result.boot_inputs.Start > 0


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


def test_rtc_sampling_aligns_boot_977_979_without_relaxing_bytes_or_frames(api):
    """Captured hge failure: boot completion varies, the RTC observation frame must not."""
    r = api._runtime
    title = to_lua(r, {"profile": {"rtc": {"symbol": "rtc", "date_off": 0, "date_size": 4,
                      "time_off": 4, "time_size": 4, "source": "MODEL RTC slice"}},
                      "symbols": {"rtc": {"address": 100, "size": 8}}})
    def sample(start, value="pinned", stride=1):
        state = {"frame": start, "reads": []}
        def step(buttons):
            assert len(buttons) == 0
            state["frame"] += stride
        def read(address, size):
            state["reads"].append(state["frame"])
            return value
        if api.sample_rtc is None:  # Old producer: reads immediately after the boot predicate.
            result = {"first": read(100, 4) + read(104, 4), "frame_first": state["frame"]}
        else:
            result = from_lua(api.sample_rtc(title, 1200, step, lambda: state["frame"], read))
        return result, state
    first, a = sample(977)
    second, b = sample(979)
    assert first["frame_first"] == second["frame_first"] == 1200
    assert a["reads"] == b["reads"] == [1200, 1200]
    observation = {**first, "second": second["first"], "frame_second": second["frame_first"], "unpinned": "wallclock"}
    assert api.evaluate("k", to_lua(r, observation)) == "PASS"
    wrong = {**observation, "second": "different RTC bytes"}
    assert api.evaluate("k", to_lua(r, wrong))[0] == "FAIL"
    wrong = {**observation, "frame_second": 1201}
    assert api.evaluate("k", to_lua(r, wrong))[0] == "FAIL"
    assert api.evaluate("k", to_lua(r, observation)) == "PASS"
    with pytest.raises(Exception, match="RTC sample frame advance"):
        sample(1199, stride=2)
    ok, why = r.eval("function(fn, ...) return pcall(fn, ...) end")(
        api.sample_rtc, title, 1200, lambda _: None, lambda: 1201, lambda *args: "unused")
    assert not ok and "already passed" in why["open"]


@pytest.mark.parametrize("phase", ["battle", "pc", "reset"])
def test_phase_zero_expected_cannot_hide_in_sum_red_revert(api, phase):
    original = examples()["n"]
    assert api.evaluate("n", to_lua(api._runtime, original)) == "PASS"
    bad = copy.deepcopy(original)
    case = next(c for c in bad["physical"]["cases"] if c["phase"] == phase)
    case.update(first_expected=0, first_seen=0, last_expected=0, last_seen=0)
    assert api.evaluate("n", to_lua(api._runtime, bad))[0] == "FAIL"
    assert api.evaluate("n", to_lua(api._runtime, original)) == "PASS"


def test_missing_cpu_histograms_are_a_named_open_not_a_lua_error(api):
    # PHYSICAL hge/SS at 108c025d: the route never reached a battle, and row m crashed indexing nil histograms.
    bad = copy.deepcopy(examples()["m"])
    del bad["histograms"]
    assert api.evaluate("m", to_lua(api._runtime, bad)) == ("OPEN", "m:CPU histograms")
    assert api.evaluate("m", to_lua(api._runtime, examples()["m"])) == "PASS"


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
    "nonmonotonic", "nonmonotonic_floor", "monotonic_missing", "monotonic_floor_missing", "execution_mode", "throttle_config", "throttle_vsync",
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
    elif fault == "throttle_vsync":
        sample["throttle_config"]["VSyncThrottle"] = True
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
    "result", "producer", "level", "title", "rom_sha1",
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
    assert {case["name"] for case in runnable} == {"battle", "reset"} and reasons == ["pc: native box slot absent"]
    result, rows = finish_rows(api, examples(), {"n": ("OPEN", {"reason": reasons[0]})}, ("PASS", {}))
    assert result == "OPEN" and rows["n"][0] == "OPEN"
    malformed = copy.deepcopy(cases)
    malformed[0]["producer_site"] = "unselected"
    with pytest.raises(AssertionError, match="producer observer"):
        phase_case_plan(malformed, [])
    assert phase_case_plan(cases, []) == (cases, [])
    assert phase_case_plan([], [])[1] == ["battle: required phase case absent", "pc: required phase case absent", "reset: required phase case absent"]


def test_known_runtime_bridges_resolve_unknown_recipe_stays_open():
    legs, reasons = resolve_pack_route(["gen4_routes:battle_settled", "gen4_pc:reach_pc_terminal"], {})
    assert not reasons and [leg["bridge"] for leg in legs] == ["gen4_routes:battle_settled", "gen4_pc:reach_pc_terminal"]
    legs, reasons = resolve_pack_route(["unknown_walk"], {})
    assert not legs and reasons


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



@pytest.mark.parametrize("finish", [True, False])
def test_recipe_telemetry_is_sparse_and_survives_the_unchanged_bound(api, finish):
    r = api._runtime
    state = {"frames": 0, "samples": []}
    leg = {"name": "fight_until_enemy_faints", "max_frames": 95,
           "steps": [{"press": ["A"], "hold_frames": 2, "then_wait_frames": 13}],
           "until": {"symbol": "sFieldSysPtr", "deref": [], "offset": 4, "zero": True}}
    def step(buttons):
        state["frames"] += 1
    def ready(predicate):
        return finish and state["frames"] >= 65
    def observe():
        state["samples"].append(state["frames"])
        return to_lua(r, {"value": max(0, 65 - state["frames"]), "enemy_hp": max(0, 65 - state["frames"]),
                          "our_hp": 20, "turn_count": state["frames"] // 30})
    journal = r.table()
    if finish:
        assert api.play_recipe(to_lua(r, leg), step, ready, observe, journal) == 65
    else:
        with pytest.raises(Exception, match="until predicate not reached"):
            api.play_recipe(to_lua(r, leg), step, ready, observe, journal)
    assert len(journal) == 1
    record = from_lua(journal[1])
    assert record["frames_used"] == (65 if finish else 95)
    assert record["outcome"] == ("until_met" if finish else "bound")
    assert state["samples"] == ([0, 30, 60, 65] if finish else [0, 30, 60, 90, 95])
    assert record["samples"][len(record["samples"])]["final"] is True


def test_fight_trace_reads_the_pack_predicate_source_and_our_hp(api):
    r = api._runtime
    artifact = json.loads((REPO / "data/games/gen4_hgss/profile.json").read_text())["titles"]["heartgold"]
    artifact["symbols"]["sFieldSysPtr"]["address"] = 100
    b = artifact["profile"]["battle"]
    leg = {**artifact["route_legs"]["fight_until_enemy_faints"], "name": "fight_until_enemy_faints"}
    words = {100: 200, 200: 300, 304: 400, 412: 12, 428: 500, 548: 600,
             600 + b["mons_off"] + b["hp_off"]: 20,
             600 + b["mons_off"] + b["mon_size"] + b["hp_off"]: 17,
             500 + b["outcome_off"]: 0}
    # battler 0 / 1 identity: aligned u32 reads, so each field is masked out of a word whose neighbours are junk
    for slot, (species, level, moves, pp) in enumerate([(0x1FA, 7, (33, 45, 0, 0), (35, 40, 0, 0)), (0x10, 5, (10, 28, 0, 0), (35, 15, 0, 0))]):
        mon = 600 + b["mons_off"] + slot * b["mon_size"]
        words[mon + b["species_off"]] = 0x1234 << 16 | species
        words[mon + b["level_off"]] = 0xAB << 16 | 0x05 << 8 | level
        words[mon + b["moves_off"]], words[mon + b["moves_off"] + 4] = moves[1] << 16 | moves[0], moves[3] << 16 | moves[2]
        words[mon + b["pp_off"]] = pp[3] << 24 | pp[2] << 16 | pp[1] << 8 | pp[0]
    sample = from_lua(api.recipe_sample(to_lua(r, artifact), lambda addr: words.get(addr, 0), to_lua(r, leg)))
    assert sample["value"] == sample["enemy_hp"] == 17 and sample["our_hp"] == 20
    assert sample["battle_active"] is True and sample["battle_outcome"] == 0
    assert sample["turn_count_available"] is False
    assert (sample["our_species"], sample["our_level"], list(sample["our_moves"].values()), list(sample["our_pp"].values())) == (0x1FA, 7, [33, 45, 0, 0], [35, 40, 0, 0])
    assert (sample["enemy_species"], sample["enemy_level"], list(sample["enemy_moves"].values()), list(sample["enemy_pp"].values())) == (0x10, 5, [10, 28, 0, 0], [35, 15, 0, 0])
    words[600 + b["mons_off"] + b["mon_size"] + b["hp_off"]] = 0
    assert api.predicate(to_lua(r, artifact), lambda addr: words.get(addr, 0), to_lua(r, leg["until"])) is True
    words[548] = 0
    missing = from_lua(api.recipe_sample(to_lua(r, artifact), lambda addr: words.get(addr, 0), to_lua(r, leg)))
    assert missing["value_available"] is False and missing.get("enemy_hp") is None

def test_synth_identity_survives_native_party_to_box_deposit():
    from types import SimpleNamespace

    party, boxed = [{"pid": 1}, {"pid": 2}], []
    decoded = SimpleNamespace(party=lambda: party, boxes=lambda: [{"mons": dict(enumerate(boxed))}])
    assert synth_identity_present(decoded, 2)
    boxed.append(party.pop())
    assert synth_identity_present(decoded, 2)
    assert not synth_identity_present(decoded, 99)
    party.append(boxed.pop())
    assert synth_identity_present(decoded, 2)


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


def test_planner_synth_admits_lead_level_baseline_without_pc_input(tmp_path):
    # PHYSICAL Q at 080b3a22: launch_probe called synth_setup(save) with the default party2 kind, so every
    # committed *_lead12 baseline (kind lead_level) was refused before the emulator started.
    from tools import gen4_routes as routes
    save = tmp_path / "lead.SaveRAM"
    save.write_bytes(b"lead12-bytes")
    side = Path(str(save) + ".synth.json")
    for kind, expected_pc in (("lead_level", False), ("party2", True)):
        extra = {"otid": 9} if kind == "party2" else {}  # real lead_level sidecars carry no otid
        side.write_text(json.dumps({"schema": routes.SYNTH_SCHEMA, "kind": kind, "src_sha1": "1" * 40,
                                    "out_sha1": digest(save, "sha1"), "new_pid": 7, **extra}))
        meta = planner_synth(routes, save)
        assert (meta is not None) is expected_pc and (meta is None or meta["setup"] == "SYNTH")
    side.unlink()
    assert planner_synth(routes, save) is None
    # old call shape refuses the lead_level sidecar (the PHYSICAL failure); keep it red
    side.write_text(json.dumps({"schema": routes.SYNTH_SCHEMA, "kind": "lead_level", "src_sha1": "1" * 40,
                                "out_sha1": digest(save, "sha1"), "new_pid": 7}))
    with pytest.raises(routes.RouteError, match="setup_mismatch"):
        routes.synth_setup(save)


def test_diag_bridge_replace_retries_sharing_violation():
    # PHYSICAL ss1-q-10031638: WinError 5 replacing bridge-response.tmp; the diag bridge must reuse the
    # shared retry the probe harness already had.
    source = (REPO / "tools/gen4_diag.py").read_text(encoding="utf-8")
    assert "g4.replace_with_retry(temp, target)" in source and "os.replace(temp, target)" not in source


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


@pytest.mark.parametrize("start_frame", [None, 977, 979, 1025, 1035])
@pytest.mark.parametrize("revert_rtc", [False, True])
def test_probe_fake_io_terminal_receipt_without_console(api, start_frame, revert_rtc, tmp_path, monkeypatch):
    """Execute the actual entry point against absent field prerequisites, not just its oracle."""
    r = api._runtime
    json_api = r.execute((REPO / "lua/json_codec.lua").read_text(encoding="utf-8"))
    cfg = {"profile": "pack.json", "title": "heartgold", "mode": "rtc-repeat", "rom_sha1": "2" * 40,
           "rom_md5": "1" * 32, "run_id": "fake", "boot_frames": 1, "requested_rate": 300,
           "code_sha256": MODEL_CUT["script_sha256"], "profile_sha256": MODEL_CUT["profile_sha256"], "source_head": "cut",
           "module_sha256": MODEL_CUT["module_sha256"], "surface_sha256": MODEL_CUT["surface_sha256"], "receipt_kind": MODEL_CUT["receipt_kind"]}
    for prefix, purpose in (("scenario", "baseline"), ("row_i_scenario", "row_i"), ("pc_case_scenario", "pc_case")):
        relative = f"data/gen4/scenarios/{purpose}.json"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": "gen4-probe-scenario-v3", "title": "heartgold", "purpose": purpose}))
        cfg[prefix + "_path"], cfg[prefix + "_sha256"] = relative, digest(path)
    pack = {"schema": "gen4-profile-v1", "titles": {"heartgold": {"rom": {"sha1": cfg["rom_sha1"], "md5": cfg["rom_md5"]},
            "symbols": {"sRTCWork": {"address": 100}, "sFieldSysPtr": {"address": 200}, "sSaveDataPtr": {"address": 300}},
            "sites": {}, "profile": {}, "overlays": {}, "overlay_table": {}}}}
    if start_frame is not None:
        cfg["rtc_sample_frame"] = 1200
        title = pack["titles"]["heartgold"]
        title["symbols"]["sRTCWork"]["size"] = 8
        title["profile"]["rtc"] = {"symbol": "sRTCWork", "date_off": 0, "date_size": 4,
                                    "time_off": 4, "time_size": 4, "source": "MODEL packed RTC"}
    r.globals().START_FRAME = start_frame or 0
    r.globals().FAKE_CFG, r.globals().FAKE_PACK = json.dumps(cfg), json.dumps(pack)
    r.globals().FAKE_JSON = json_api
    r.execute('''
        SLINK_GEN4_PROBE_TEST=false; SLINK_ROOT="fake-root"; WRITES={}; FRAME=START_FRAME
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
        emu={getregisters=function() return {} end,getregister=function(name) if name=="ARM9 r15" then return 0 end; error("bogus") end,
            frameadvance=function() FRAME=FRAME+1 end,
            framecount=function() return FRAME end,limitframerate=function() end}
        client={exit=function() EXITED=true end,speedmode=function() end}
        gameinfo={getromhash=function() return string.rep("1",32) end}
        event={}; joypad={set=function() end}
        console={log=function() error("console traffic forbidden") end}
    ''')
    source = SCRIPT.read_text(encoding="utf-8")
    if revert_rtc:
        call = "return M.sample_rtc(title,cfg.rtc_sample_frame,step,emu.framecount,bytes)"
        assert source.count(call) == 1
        source = source.replace(call, "local rtc=M.rtc_slice(title); return {first=bytes(rtc.date_address,rtc.date_size)"
                                "..bytes(rtc.time_address,rtc.time_size),frame_first=emu.framecount()}")
    r.execute(source)
    assert list(r.globals().WRITES.values()) == ["receipt.txt"]
    assert r.globals().EXITED
    import sys
    with monkeypatch.context() as changed:
        changed.setattr(sys.modules[__name__], "REPO", tmp_path)
        rows = parse_receipt(r.globals().TERMINAL, title="heartgold", rom_sha1="2" * 40, run_id="fake", expected_cut=MODEL_CUT)
    for _, payload in rows.values():
        for key in ("scenario_path", "scenario_sha256", "row_i_scenario_path", "row_i_scenario_sha256", "pc_case_scenario_path", "pc_case_scenario_sha256"):
            assert payload[key] == cfg[key]
    assert set(rows) == set(ROWS) and rows["l"][0] == "OPEN"
    if start_frame is not None:
        assert rows["k"][1]["observation"]["frame_first"] == (start_frame if revert_rtc else 1200)
        assert rows["k"][1]["observation"]["first"] == "00" * 8


@pytest.mark.parametrize("guard", ["residency", "full_pin", "last_drain", "close_fault"])
def test_reverted_semantic_guard_is_detected(api, guard):
    from lupa import LuaRuntime

    source = SCRIPT.read_text(encoding="utf-8")
    replacements = {
        "residency": ('if site.image~="arm9" and not resident(site.overlay_id) then return nil end', ''),
        "full_pin": ('check(actual==site.register_hex:lower(),', 'check(true,'),
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
@pytest.mark.parametrize("field", ("script_sha256", "profile_sha256", "module_sha256", "surface_sha256"))
def test_every_row_stale_cut_red_revert(row, field):
    def consume(text):
        return parse_receipt(text, title="heartgold", rom_sha1="2" * 40, expected_cut=MODEL_CUT)

    assert consume(receipt(row))[row][0] == "PASS"
    with pytest.raises(StaleReceiptError, match=f"STALE {field}"):
        consume(receipt(row, **{field: "old"}))
    assert consume(receipt(row))[row][0] == "PASS"


@pytest.mark.parametrize("field", ("script_sha256", "profile_sha256", "module_sha256", "surface_sha256"))
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
                          frames_requested=3000)
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


def test_all_row_consumers_ignore_informational_head():
    for row in "abcdefghijklmno":
        assert parse_receipt(receipt(row, source_head="docs-only-moved"), title="heartgold", rom_sha1="2" * 40,
                             expected_cut=MODEL_CUT)[row][0] == "PASS"


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
    assert row_o(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT)[0] == "PASS"
    path.write_text(receipt("o", source_head="cut", producer="C1-8", oracle="independent", negative_control="red"))
    assert finish_rows(api, examples(), {}, row_o(path, "heartgold", "2" * 40, "cut", expected_cut=MODEL_CUT))[0] == "PASS"


def fixture_module():
    input_file(REPO / "tools/gen4_fixtures.py", "C1-4 fixture module")
    module = importlib.import_module("tools.gen4_fixtures")
    for name in ("write_nds_run_config", "stage_rom", "stage_save"):
        if not hasattr(module, name):
            pytest.skip(f"OPEN C1-4 function absent: tools.gen4_fixtures.{name}")
    return module


def planner_synth(routes, save):
    """The PC bridge's SYNTH disclosure: only a party2 sidecar enables PC legs; any other declared SYNTH kind
    (lead_level baselines) is validated by its own kind and gives the planner no PC input."""
    if save_setup(save)["setup"] != "SYNTH":
        return None
    # save_setup above already bound the sidecar to these bytes; lead_level sidecars carry no otid, so only a
    # party2 sidecar goes through the route tool's PC-input validation.
    kind = json.loads(Path(str(save) + ".synth.json").read_bytes()).get("kind")
    return routes.synth_setup(save, "party2") if kind == "party2" else None


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


# Each shakedown negative control, the row it must turn red and a needle from that row's own check string
# (probe_gen4_hooks.lua). rtc-repeat is absent on purpose: it must PASS and feed row k's repeat comparison.
CONTROL_REDS = {
    "patched-rom": {"j": "ROM hash differs"},
    "rtc-unpinned": {"c": "unpinned core settings"},
    "no-buttons": {"l": "buttons-only CONTINUE failed"},
}
assert set(CONTROL_REDS) == {"patched-rom", "rtc-unpinned", "no-buttons"}


def control_red_failures(collected: dict) -> list:
    """[(case, row, status, reason)] for every control that did not FAIL its targeted row with its own reason."""
    assert set(CONTROL_REDS) == {"patched-rom", "rtc-unpinned", "no-buttons"}
    out = []
    for case, want in CONTROL_REDS.items():
        for row, needle in want.items():
            status, payload = collected.get(case, {}).get(row, ("OPEN", {"reason": "control row absent"}))
            reason = str(payload.get("reason", ""))
            if status != "FAIL" or needle not in reason:
                out.append((case, row, status, reason))
    return out


def publish_control_evidence(batch, collected, rows):
    missed = control_red_failures(collected)
    evidence = {"missed": missed, "cases": {case: {row: {"status": status, "reason": payload.get("reason")}
                for row, (status, payload) in values.items()} for case, values in collected.items()}}
    (batch / "control-reds.json").write_text(json.dumps(evidence), encoding="utf-8")
    for case, row, status, reason in missed:
        rows[row] = ("FAIL", {**rows.get(row, (None, {}))[1],
                              "reason": f"control {case} did not produce its targeted red: {status}: {reason}"})
    return missed


def publish_combined(batch, rows, metadata):
    statuses = [status for status, _ in rows.values()]
    result = "FAIL" if "FAIL" in statuses else "OPEN" if "OPEN" in statuses else "PASS"
    lines = [f"PROBE {row} {status} {json.dumps({**metadata, **payload}, sort_keys=True)}"
             for row, (status, payload) in rows.items()]
    lines.append(f"RESULT: {result}")
    (batch / "combined.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def publish_aborted_attempt(batch, api, collected, observations, errors, external, metadata, stage, failure_row, exc):
    """Keep partial evidence when any producer, oracle or final check aborts."""
    detail = {"stage": stage, "type": type(exc).__name__, "reason": str(exc)}
    partial = dict(errors)
    partial[failure_row] = ("FAIL", {"reason": f"{stage}: {exc}", "attempt_failure": detail})
    _, rows = finish_rows(api, observations, partial, external)
    if failure_row == "o":
        rows["o"] = partial["o"]
    publish_control_evidence(batch, collected, rows)
    # The metadata is the attempted cut, even if a final rebind detects drift.
    # Such a receipt remains STALE to consumers; never relabel it to current bytes.
    for row, (_, payload) in rows.items():
        if row != "o":
            payload.update(metadata, attempt_failure=detail)
            if row == "i":
                payload.update(metadata.get("row_i_setup", {}), scenario_role="row_i")
    publish_combined(batch, rows, {})


def test_a_control_that_does_not_go_red_fails_the_shakedown():
    """OMP cx-8adf1fc7 S4: a control receipt whose targeted row PASSes, or FAILs for another reason, must fire."""
    good = {case: {row: ("FAIL", {"reason": '[string "main"]:11: ' + needle}) for row, needle in want.items()}
            for case, want in CONTROL_REDS.items()}
    assert control_red_failures(good) == []
    for case, want in CONTROL_REDS.items():
        for row in want:
            for bad in (("PASS", {"observation": {}}), ("FAIL", {"reason": "some unrelated failure"})):
                broke = {c: dict(rows) for c, rows in good.items()}
                broke[case][row] = bad
                assert control_red_failures(broke) == [(case, row, bad[0], bad[1].get("reason", ""))], (case, row)


def test_control_misfire_published_before_assert_never_pass(tmp_path):
    collected = {case: {row: ("FAIL", {"reason": needle}) for row, needle in want.items()}
                 for case, want in CONTROL_REDS.items()}
    collected["patched-rom"]["j"] = ("PASS", {"reason": "unchanged hash"})
    rows = {row: ("PASS", {"observation": {"retained": True}}) for row in "abcdefghijklmno"}
    missed = publish_control_evidence(tmp_path, collected, rows)
    result = publish_combined(tmp_path, rows, dict(MODEL_CUT, title="heartgold", rom_sha1="2" * 40, level="PHYSICAL"))
    assert result == "FAIL" and (tmp_path / "control-reds.json").is_file()
    text = (tmp_path / "combined.txt").read_text()
    assert "PROBE j FAIL" in text and text.endswith("RESULT: FAIL\n")
    assert rows["j"][1]["observation"] == {"retained": True}
    with pytest.raises(AssertionError, match=str(tmp_path).replace("\\", r"\\")):
        assert not missed, f"control(s) did not produce their targeted red in {tmp_path}: {missed}"


def synth_identity_present(decoded, new_pid):
    return (any(mon["pid"] == new_pid for mon in decoded.party())
            or any(mon["pid"] == new_pid for box in decoded.boxes() for mon in box["mons"].values()))


def scenario_path(relative):
    """Scenario identity is repository-relative, confined to the committed inventory."""
    if not isinstance(relative, str):
        raise StaleReceiptError("STALE scenario path absent")
    parts = PurePosixPath(relative)
    if ("\\" in relative or ":" in relative or parts.is_absolute() or ".." in parts.parts
            or parts.parent.as_posix() != "data/gen4/scenarios" or parts.suffix != ".json"):
        raise StaleReceiptError(f"STALE scenario path outside inventory: {relative}")
    path = REPO / parts
    if path.resolve().parent != (REPO / "data/gen4/scenarios").resolve():
        raise StaleReceiptError(f"STALE scenario path escapes inventory: {relative}")
    return path


def bind_scenarios(payload, title, *, required=True):
    """Re-read scenario bytes at consumption; HEAD movement alone is irrelevant."""
    for prefix, purpose in (("scenario", "baseline"), ("row_i_scenario", "row_i"), ("pc_case_scenario", "pc_case")):
        relative, sha = payload.get(prefix + "_path"), payload.get(prefix + "_sha256")
        if relative is None and sha is None and not required:
            continue  # Explicit hypothetical MODEL receipt, not a production consumer.
        path = scenario_path(relative)
        if not path.is_file() or digest(path) != sha:
            raise StaleReceiptError(f"STALE scenario hash/absent: {relative}")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if (doc.get("schema"), doc.get("title"), doc.get("purpose")) != ("gen4-probe-scenario-v3", title, purpose):
            raise StaleReceiptError(f"STALE scenario title/purpose/schema: {relative}")
        if required and purpose == "baseline":
            for link in ("row_i_scenario", "pc_case_scenario"):
                if doc.get(link) != payload.get(link + "_path"):
                    raise StaleReceiptError(f"STALE scenario {link} linkage")


def load_scenario(relative, title, purpose, *, committed=True):
    path = input_file(scenario_path(relative), f"{title} {purpose} scenario")
    if committed:
        try:
            blob = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=REPO, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            raise StaleReceiptError(f"STALE uncommitted scenario: {relative}") from exc
        if path.read_bytes().replace(b"\r\n", b"\n") != blob.replace(b"\r\n", b"\n"):
            raise StaleReceiptError(f"STALE uncommitted scenario: {relative}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert (doc.get("schema"), doc.get("title"), doc.get("purpose")) == ("gen4-probe-scenario-v3", title, purpose), "wrong scenario schema/title/purpose"
    allowed = {"schema", "title", "purpose", "save", "row_i_scenario", "pc_case_scenario", "provenance"}
    assert not doc.keys() - allowed, "scenario runtime overrides forbidden (pack routes and phases are authoritative)"
    spec = doc["save"]
    assert isinstance(spec, dict) and not spec.keys() - {"path", "sha256", "sidecar_sha256", "setup"}, "wrong scenario save schema"
    relative_save = spec["path"]
    assert isinstance(relative_save, str) and "\\" not in relative_save and ":" not in relative_save, "save must be lane-relative"
    part = PurePosixPath(relative_save)
    assert not part.is_absolute() and ".." not in part.parts, "save must be lane-relative"
    root = lane_root().resolve()
    save = (root / part).resolve()
    assert save.is_relative_to(root), "save escapes lane root"
    input_file(save, f"{title} {purpose} save")
    assert digest(save) == spec["sha256"], f"present scenario save hash mismatch: {save}"
    assert spec.get("setup") in {"NATIVE", "SYNTH"}, "explicit save.setup required"
    if purpose in {"row_i", "pc_case"}:
        assert spec["setup"] == "SYNTH", "per-case fixture must explicitly disclose SYNTH"
        side = input_file(save.with_name(save.name + ".synth.json"), f"{purpose} SYNTH ancestry sidecar")
        assert digest(side) == spec.get("sidecar_sha256"), "present scenario sidecar hash mismatch"
    elif purpose=="baseline":
        baseline_setup(doc,save)
    return doc, save, digest(path)


def baseline_setup(doc, save):
    """Explicit O-33 declaration; NATIVE binds the reviewed native inventory.

    Bytes alone cannot identify a synthesis after its sidecar is deleted. Native
    admission therefore requires the original title scenario's approved hash,
    rather than treating absence of a sidecar as evidence of native ancestry.
    """
    spec = doc["save"]
    assert digest(save) == spec["sha256"], "baseline save hash mismatch"
    assert spec.get("setup") in {"NATIVE", "SYNTH"}, "explicit save.setup required"
    side = Path(str(save) + ".synth.json")
    declared = spec.get("sidecar_sha256")
    if spec["setup"] == "NATIVE":
        assert declared is None and not side.exists(), "NATIVE scenario carries SYNTH ancestry"
        title = doc.get("title")
        assert title in TITLE_PACK, "NATIVE title required"
        native = json.loads(
            (REPO / f"data/gen4/scenarios/{title}.json").read_text(encoding="utf-8")
        )
        assert native["save"]["setup"] == "NATIVE" and spec["sha256"] == native["save"]["sha256"], (
            "NATIVE save differs from reviewed native inventory"
        )
        return {"setup": "NATIVE"}
    assert isinstance(declared, str) and side.is_file(), "SYNTH baseline sidecar absent"
    assert digest(side) == declared, "SYNTH baseline scenario sidecar hash mismatch"
    setup = save_setup(save)
    assert setup["setup"] == "SYNTH" and setup["sidecar_sha256"] == declared, (
        "SYNTH baseline disclosure mismatch"
    )
    return setup

def scenario_input(title):
    relative = os.environ.get("SLINK_GEN4_PROBE_SCENARIO", f"data/gen4/scenarios/{title}.json")
    doc, save, sha = load_scenario(relative, title, "baseline")
    row_i = doc["row_i_scenario"]
    _, boxed, boxed_sha = load_scenario(row_i, title, "row_i")
    pc_case = doc["pc_case_scenario"]
    _, pc_save, pc_sha = load_scenario(pc_case, title, "pc_case")
    return {"scenario_path": relative, "scenario_sha256": sha,
            "row_i_scenario_path": row_i, "row_i_scenario_sha256": boxed_sha,
            "pc_case_scenario_path": pc_case, "pc_case_scenario_sha256": pc_sha,
            "scenario_save": save.as_posix(), "row_i_save": boxed.as_posix(), "pc_case_save": pc_save.as_posix()}


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
    bridges = {"gen4_routes:battle_settled", "gen4_pc:reach_pc_terminal", "boot_continue_to_overworld",
               "pc_open_storage", "pc_deposit_first_party_mon", "pc_withdraw_box_mon", "pc_exit_app"}
    buttons = {"A", "B", "X", "Y", "Start", "Select", "Up", "Down", "Left", "Right", "L", "R"}
    for leg in route:
        if isinstance(leg, dict):  # Existing explicit frame/button scenario compatibility.
            frames, press = leg.get("frames"), leg.get("buttons", [])
            assert isinstance(frames, int) and not isinstance(frames, bool) and 0 < frames <= 12000, "invalid frame bound"
            assert isinstance(press, list) and all(isinstance(b, str) and b in buttons for b in press), "unsupported button input"
            resolved.append(copy.deepcopy(leg))
            continue
        assert isinstance(leg, str) and leg, "malformed route leg"
        if leg in bridges:
            resolved.append({"bridge": leg, "max_frames": 12000, "source": ["tools/gen4_routes.py + lua/tests/gen4_route_play.lua"]})
            continue
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
    return resolved, reasons


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
    return resolved_cases, reasons


def launch_probe(module, title, source, save, profile, base, case, lane, cfg):
    assert_harness_functions()
    bind_scenarios(cfg, title)
    expected_cut = committed_cut(title, profile=profile, source_head=cfg["source_head"])
    bind_cut({"script_sha256": cfg["code_sha256"], "profile_sha256": cfg["profile_sha256"],
              "source_head": cfg["source_head"], "module_sha256": cfg["module_sha256"],
              "surface_sha256": cfg["surface_sha256"], "receipt_kind": cfg["receipt_kind"],
              "title": title, "rom_sha1": cfg["rom_sha1"]}, expected_cut)
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
    cfg["bridge_request"], cfg["bridge_response"], cfg["bridge_lane"] = (lane / "bridge-request.json").as_posix(), (lane / "bridge-response.json").as_posix(), lane.as_posix()
    from tools import gen4_routes as routes
    game = {"heartgold": "HG", "soulsilver": "SS", "heartgold_hge": "hge"}[title]
    synth = planner_synth(routes, save)
    planner = routes.BridgePlanner(source, game, synth)
    bridge_seen = None
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
            bridge_request = Path(cfg["bridge_request"])
            if bridge_request.is_file():
                try:
                    pending = json.loads(bridge_request.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pending = None  # The producer may still be finishing this one transaction.
                if pending and pending["id"] != bridge_seen:
                    bridge_seen = pending["id"]
                    try:
                        answer = {"id": bridge_seen, "route": planner.plan(pending)}
                    except (routes.RomAbsent, FileNotFoundError) as exc:
                        answer = {"id": bridge_seen, "open": str(exc)}
                    except routes.RouteError as exc:
                        answer = {"id": bridge_seen, "error": str(exc)}
                    temp = Path(cfg["bridge_response"]).with_suffix(".tmp")
                    temp.write_text(json.dumps(answer), encoding="utf-8")
                    replace_with_retry(temp, cfg["bridge_response"])
            if request.is_file() and not response.is_file():
                inventory = {"foreign_pids": [pid for pid in emulator_pids() if pid != proc.pid],
                             "checked_at_utc": datetime.datetime.now(datetime.UTC).isoformat()}
                temp = response.with_suffix(".tmp")
                temp.write_text(json.dumps(inventory), encoding="utf-8")
                replace_with_retry(temp, response)
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


def internal_census_loads(title, artifact):
    """hge bypasses the vanilla loader for its early expansion and async loads."""
    if title != "heartgold_hge":
        return []
    sites = artifact["sites"]
    entries = []
    for site_id, argument, source in (
        ("hge_load_arm9_expansion", {"id": 129}, "constant overlay 129"),
        ("load_overlay_noinit_async", {"id_register": "ARM9 r1", "ids": [130, 131]}, "overlay ID in r1"),
    ):
        assert site_id in sites, f"hge census pack site absent: {site_id}"
        entries.append({"symbol": sites[site_id]["symbol"], **argument, "region": 0,
                        "source": f"pack:{site_id} ({source})"})
    assert len(entries) + 2 <= 4, "census hook budget"
    return entries


def phase_settle_policy(title, artifact):
    # Owner accepted these uncensored PHYSICAL frame deltas. Overall diagnostic
    # FAIL was ClockThrottle true->false (native executor pacing), not a pin or
    # publication failure. Frame differences use emulated counters, independent
    # of host throttling. No historical verdict is relabelled as PASS.
    measurements = {
        "heartgold_hge": (
            "cb2dc435196d09c8c9209bf037240ed834f4cea1",
            "d2-hge-10031339",
            "93769b54c053e6d90ddd7750a48e57e68a763b119c7f6741ac332c5e950e7e4d",
            1,
        ),
        "soulsilver": (
            "f8dc38ea20c17541a43b58c5e6d18c1732c7e582",
            "d2-ss-10031344",
            "89fa7570c4b3d29a7b60f584d2080e9bc238a24455c3365d70f851d23ca645ab",
            11,
        ),
    }
    if title in measurements:
        sha, lane, receipt_sha, expected_max = measurements[title]
        assert artifact["rom"]["sha1"] == sha, "settle measurement ROM changed"
        receipt = REPO / f"tests/fixtures/gen4/{lane}_observation.json"
        assert digest(receipt) == receipt_sha, "settle observation hash mismatch"
        observation = json.loads(receipt.read_bytes())
        assert observation["qualified"] is False and observation["status"] == "OBSERVED", (
            "wrong settle observation"
        )
        epochs = observation["settle"]["epochs"]
        assert {e["site"] for e in epochs} == set(observation["settle"]["sites"]), (
            "incomplete settle epochs"
        )
        for e in epochs:
            assert e["left_censored"] is False and e["status"] == "SETTLED", (
                "censored or unfinished settle epoch"
            )
            assert e["delta"] == e["pin_frame"] - e["active_frame"] >= 0, (
                "settle delta disagrees with frames"
            )
        maximum = max(e["delta"] for e in epochs)
        assert maximum == expected_max, "settle measured maximum changed"
        return {
            "max_frames": maximum + 5,
            "measured_max": maximum,
            "margin": 5,
            "units": "emulator frames",
            "receipt": str(receipt),
            "receipt_sha256": receipt_sha,
            "epochs": epochs,
            "physical_lane": str(lane_root() / lane),
            "diagnostic_verdict": "FAIL ClockThrottle audit",
            "note": "owner accepted uncensored frame deltas; max+5; not row-n closure alone",
        }
    if title != "heartgold":
        return None
    assert artifact["rom"]["sha1"] == "4fcded0e2713dc03929845de631d0932ea2b5a37", (
        "settle measurement ROM changed"
    )
    return {
        "max_frames": 16,
        "measured_max": 11,
        "margin": 5,
        "units": "emulator frames",
        "receipt": str(lane_root() / "g1-settle-HG-1144-serial/settle.json"),
        "receipt_sha256": "ddf1dc69d852f30988aba4c0b8af61697ec6307e0b6d4371fe29188e9f1e5d38",
        "state_sha256": "86efe700aed2d8e2737330c98bb2881891daeb1004382be43a1577e349ffb627",
        "note": "serial PHYSICAL diagnostic: faint 10, start 11; add 5 frames scheduling margin; never qualifies row n alone",
    }

def phase_image_pins(source, artifact, title):
    generator = importlib.import_module("tools.gen_gen4_pack")
    images = generator.load_images(source, raw_arm9=title == "heartgold_hge")
    result = {}
    for case in artifact.get("phase_cases", []):
        for site_id in case["sites"]:
            site = artifact["sites"][site_id]
            if site_id not in result:
                result[site_id] = {image: images.read(image, site["address"], site["extent"]).hex()
                                   for image in images.collisions(site["image"], site["address"], site["extent"])}
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
    occupied = [(box, slot, m) for box, data in enumerate(decoded.boxes()) for slot, m in data["mons"].items()]
    if not occupied:
        specs["box_open"] = "i: played fixture needs an existing occupied PC slot for persistence"
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
    samples, written_battery, save_driver_cases, box_batteries, dirty_observations = {}, None, {}, {}, {}
    route_legs = {}
    for case in ("party-write", "no-write", "box-write", "box-no-dirty"):
        if case not in specs:
            continue
        rows, battery = launch_probe(module, title, source, save, profile, base, case, batch / case,
                                     {**cfg, "persistence": specs[case]})
        status, payload = rows["i"]
        if status == "FAIL":
            raise AssertionError(f"persistence instrumentation FAIL: {batch / case}: {payload}")
        observation = payload.get("observation")
        if observation and observation.get("route_legs"):
            route_legs[case] = observation["route_legs"]
        if not observation or observation.get("save_finish_hits", 0) < 1:
            return None, payload.get("reason", f"i: {case} native-save evidence absent")
        trace = observation.get("save_driver_trace")
        if trace is None:
            return None, f"i: {case} save-driver state trace absent"
        assert save_driver_complete(trace), f"{case}: native save-driver active-to-idle transition absent"
        save_driver_cases[case] = trace
        dirty_observations[case] = {"before": observation.get("modified_before"), "after_save": observation.get("modified"),
                                    "requested": specs[case].get("dirty")}
        result = codec.parse_save(battery.read_bytes(), decoded.profile)
        assert codec.counter_newer(result.counter, decoded.counter) > 0, f"{case}: no newer coherent native save bank"
        if case.startswith("box"):
            box_batteries[case] = battery
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
    box_reloaded = {}
    for case, battery in box_batteries.items():
        cold_cfg = dict(cfg, save_witness=source_witness(codec, codec.parse_save(battery.read_bytes(), decoded.profile)),
                        cold_readback=specs[case])
        cold, _ = launch_probe(module, title, source, battery, profile, base, "cold-reload",
                               batch / f"cold-reload-{case}", cold_cfg)
        raw = cold["i"][1].get("observation", {}).get("runtime_hex")
        if not raw:
            return None, f"i: {case} cold RAM box readback absent"
        mon = codec.decode_box_mon(bytes.fromhex(raw), decoded.profile)
        assert mon["key"] == specs["box_key"], "cold box identity drift"
        box_reloaded[case] = mon["friendship"]
    return {"written": samples["party-write"], "no_write": samples["no-write"], "original": specs["original"],
            "target": specs["target"], "box_dirty": samples.get("box-write"), "box_without_dirty": samples.get("box-no-dirty"),
            "box_original": specs.get("box_original"), "box_target": specs.get("box_target"), "cold_reload": reloaded["hp"],
            "box_open": specs.get("box_open"),
            "box_cold_reload": box_reloaded.get("box-write"), "box_without_dirty_cold_reload": box_reloaded.get("box-no-dirty"),
            "dirty_flag_observations": dirty_observations, "route_legs": route_legs,
            "save_driver_cases": save_driver_cases,
            "save_completed": len(save_driver_cases) == 4 and all(save_driver_complete(trace) for trace in save_driver_cases.values()),
            "oracle": "save-driver active-to-idle state reads + server.adapters.gen4_codec.parse_save + independent cold RAM PK4 decode"}, None
def phase_case_input(case, cfg, baseline, codec, profile):
    """A PC deposit never inherits the native one-mon baseline or row-i boxed descendant."""
    if case.get("phase") == "pc" and case.get("fixture_role") != "pc_case":
        return None, None, "pc: dedicated pc_case fixture_role absent"
    if case.get("fixture_role") != "pc_case":
        return baseline, cfg, None
    value = cfg.get("pc_case_save")
    if not value or not Path(value).is_file():
        return None, None, "pc: dedicated hash-bound pc_case party2 fixture absent"
    save = Path(value)
    setup = save_setup(save)
    assert setup["setup"] == "SYNTH", "pc_case must disclose its party2 sidecar"
    decoded = codec.parse_save(save.read_bytes(), profile)
    assert len(decoded.party()) >= 2, "pc_case requires at least two party mons for native deposit"
    assert synth_identity_present(decoded, setup["new_pid"]), "pc_case SYNTH identity absent"
    return save, {**cfg, **setup, "scenario_role": "pc_case", "save_witness": source_witness(codec, decoded)}, None


def finish_phase_n(observations, errors, collected, reasons, model, *, api):
    """Grade phase evidence independently of the baseline's unarmed n row."""
    measured, failures, opens = [], [], list(reasons)
    prior = errors.get("n")
    if prior and prior[0] == "FAIL":
        failures.append("baseline n: " + str(prior[1].get("reason")))
    for name, rows in sorted(collected.items()):
        if not name.startswith("phase-"):
            continue
        status, payload = rows["n"]
        physical = (payload.get("observation") or {}).get("physical")
        if status == "FAIL":
            failures.append(f"{name}: {payload.get('reason') or 'phase n FAIL'}")
        elif status == "OPEN":
            opens.append(f"{name}: {payload.get('reason') or 'phase n OPEN'}")
        if physical is None:
            if status == "PASS":
                failures.append(f"{name}: PASS lacks physical phase measurement")
            continue
        outcome = api.evaluate_n_case(to_lua(api._runtime, physical))
        case_status, why = outcome if isinstance(outcome, tuple) else (outcome, None)
        if case_status == "FAIL":
            failures.append(f"{name}: {why}")
        elif case_status == "OPEN":
            opens.append(f"{name}: {why}")
        measured.append(physical)
        opens.extend(physical.get("bridge_gaps", []))
    observation = {"model": copy.deepcopy(model)}
    if measured:
        observation["physical"] = {
            "first_expected": sum(p["first_expected"] for p in measured),
            "first_seen": sum(p["first_seen"] for p in measured),
            "last_expected": sum(p["last_expected"] for p in measured),
            "last_seen": sum(p["last_seen"] for p in measured),
            "static_pc": any(p["static_pc"] for p in measured),
            "reset": any(p["reset"] for p in measured),
            "peak": max(p["peak"] for p in measured),
            "live_after_close": sum(p["live_after_close"] for p in measured),
            "max_cost": max(p["max_cost"] for p in measured),
            "pending_at_close": sum(p["pending_at_close"] for p in measured),
            "second_drain": sum(p["second_drain"] for p in measured),
            "baseline_fps": 1,
            "restored_fps": min(p["restored_fps"] / p["baseline_fps"] for p in measured),
            "cases": measured,
        }
    else:
        opens.append("n: no physical phase measurements collected")
    observations["n"] = observation
    if failures:
        errors["n"] = (
            "FAIL",
            {
                "reason": "n: " + "; ".join(failures),
                "open_reasons": opens,
                "observation": observation,
            },
        )
    elif opens:
        errors["n"] = ("OPEN", {"reason": "n: " + "; ".join(opens), "observation": observation})
    else:
        errors.pop("n", None)

# MODEL replays may replace collaborators; production launch may not.
def assert_harness_functions():
    for name, original, code in _HARNESS_FUNCTIONS:
        assert globals()[name] is original and original.__code__ is code, f"in-process harness override forbidden: {name}"


_HARNESS_FUNCTIONS = tuple((name, value, value.__code__) for name, value in tuple(globals().items())
                           if getattr(value, "__module__", None) == __name__ and hasattr(value, "__code__")
                           and not name.startswith("test_"))


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="OPEN G1 physical probe requires SLINK_LIVE=1; one owned emulator lane")
@pytest.mark.parametrize("title", TITLE_PACK)
def test_gen4_hook_probe(api, title):
    if os.environ.get("SLINK_LIVE") == "1":
        assert_harness_functions()
    supplied = scenario_input(title)
    module = fixture_module()
    pins = importlib.import_module("tools.gen4_pins")
    source = Path(os.environ.get("SLINK_GEN4_" + title.upper(), pins.default_locations().roms[title]))
    input_file(source, f"{title} ROM")
    profile = input_file(REPO / "data/games" / TITLE_PACK[title] / "profile.json", f"C1-2 {title} profile")
    save_env = "SLINK_GEN4_" + title.upper() + "_SAVE"
    save_path = supplied.pop("scenario_save", os.environ.get(save_env))
    if not save_path:
        pytest.skip(f"OPEN populated played save: {save_env} unset")
    save = input_file(Path(save_path), f"{title} played save")
    row_i_save = input_file(Path(supplied.pop("row_i_save", save)), f"{title} boxed row-i save")
    base = input_file(Path(os.environ.get("SLINK_BIZHAWK_CONFIG", "E:/Howard/Bizhawk/config.ini")), "BizHawk base config")
    pack = json.loads(profile.read_text(encoding="utf-8"))
    assert pack["schema"] == "gen4-profile-v1", "wrong profile schema"
    rom_sha1, rom_md5 = digest(source, "sha1"), digest(source, "md5")
    artifact = pack["titles"][title]
    assert artifact["rom"]["sha1"] == rom_sha1 and artifact["rom"]["md5"] == rom_md5, "present ROM/profile mismatch"
    cut = committed_cut(title, profile=profile)
    source_head = cut["source_head"]
    cfg = {"title": title, "rom_sha1": rom_sha1, "rom_md5": rom_md5, "jit": False, "use_real_time": False,
           "requested_rate": 300, "initial_time": "2010-01-01T12:00:00", "sample_frames": 600,
           "boot_frames": 6000, "phase_max": max(artifact["phases"][name]["cap"] for name in ("battle", "pc")),
           # aa45 PHYSICAL combined receipts: HG g1cprobeHG-1201 1035/1035;
           # SS g1cprobeSS-1227 1025/1025; hge g1cprobeHGE-1215 977/979.
           # Fixed frame = measured maximum 1035 + 165 frames of boot margin.
           "rtc_sample_frame": 1200,
           "qualify_performance": os.environ.get("SLINK_GEN4_PROBE_QUALIFY") == "1",
           **supplied}
    assert cfg["requested_rate"] == 300, "development route must request 300%"
    assert cfg["sample_frames"] >= 120 and cfg["boot_frames"] > 0, "invalid sample windows"
    cfg["code_sha256"], cfg["profile_sha256"], cfg["source_head"] = cut["script_sha256"], cut["profile_sha256"], source_head
    cfg["module_sha256"], cfg["surface_sha256"], cfg["receipt_kind"] = cut["module_sha256"], cut["surface_sha256"], cut["receipt_kind"]
    codec = codec_module()
    decoded = codec.parse_save(save.read_bytes(), "hge" if title == "heartgold_hge" else "hgss")
    cfg["save_witness"] = source_witness(codec, decoded)
    cfg["internal_loads"] = internal_census_loads(title, artifact)
    cfg["census_image_bytes"] = census_file_pins(source, artifact, title, cfg.get("internal_loads", ()))
    cfg["phase_settle"] = phase_settle_policy(title, artifact)
    cfg["phase_image_pins"] = phase_image_pins(source, artifact, title)
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
    cfg["route"] += cfg["persistence_route"]  # Native SAVE also supplies row m's save-phase histogram.
    scenario_doc,scenario_save,_=load_scenario(supplied['scenario_path'],title,'baseline')
    assert scenario_save.resolve()==save.resolve(),'baseline scenario file differs from supplied save'
    cfg.update(baseline_setup(scenario_doc,save))
    if os.environ.get("SLINK_GEN4_PROBE_SKIP_PERF_REASON"):
        cfg["skip_perf_reason"] = os.environ["SLINK_GEN4_PROBE_SKIP_PERF_REASON"]
    root = Path(os.environ.get("SLINK_GEN4_PROBE_RUNS", str(lane_root() / "probe-gates")))
    assert " " not in str(root.resolve()) and "google drive" not in str(root.resolve()).lower(), "short non-Drive lane root required"
    batch = root / (title + "-" + uuid.uuid4().hex[:12])
    batch.mkdir(parents=True, exist_ok=False)
    before_save = digest(save)
    before_row_i_save = digest(row_i_save)
    pc_save = Path(cfg["pc_case_save"]) if cfg.get("pc_case_save") else None
    before_pc_save = digest(pc_save) if pc_save and pc_save.is_file() else None
    observations, errors, collected = {}, {}, {}
    required_o = ("OPEN", {"reason": "row o consumer not reached"})
    stage, failure_row = "baseline", "a"
    attempt_metadata = {"schema": "gen4-probe-row-v1", "title": title, "rom_sha1": rom_sha1,
                        "source_head": source_head, "level": "PHYSICAL", "run_id": batch.name,
                        "script_sha256": cut["script_sha256"], "profile_sha256": cut["profile_sha256"],
                        "requested_rate": 300, "module_sha256": cut["module_sha256"],
                        "surface_sha256": cut["surface_sha256"], "receipt_kind": cut["receipt_kind"],
                        **save_setup(save), **supplied, "row_i_setup": save_setup(row_i_save),
                        "pc_case_setup": save_setup(pc_save) if before_pc_save else {"setup": "OPEN pc_case absent"}}
    try:
        for case in ("baseline", "rtc-repeat", "rtc-unpinned", "no-buttons", "patched-rom"):
            stage, failure_row = case, next(iter(CONTROL_REDS.get(case, {"a": ""})))
            try:
                rows, battery = launch_probe(module, title, source, save, profile, base, case, batch / case, cfg)
            except AssertionError as exc:
                if case not in CONTROL_REDS:
                    raise
                rows = {row: ("OPEN", {"reason": f"control attempt lacks complete bound observation: {exc}"}) for row in ROWS}
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
        stage, failure_row = "persistence", "i"
        boxed_decoded = codec.parse_save(row_i_save.read_bytes(), decoded.profile)
        persistence_cfg = {**cfg, **save_setup(row_i_save), "scenario_role": "row_i",
                           "save_witness": source_witness(codec, boxed_decoded)}
        if persistence_cfg["setup"] == "SYNTH":
            assert synth_identity_present(boxed_decoded, persistence_cfg["new_pid"]), "row-i SYNTH identity absent"
        persistence, reason = persistence_rows(module, codec, boxed_decoded, title, source, row_i_save,
                                               profile, artifact, base, batch, persistence_cfg)
        if persistence is not None:
            observations["i"] = persistence
            errors.pop("i", None)
        else:
            errors["i"] = ("OPEN", {"reason": reason})
        if cfg.get("phase_cases") or cfg.get("phase_cases_blocked"):
            stage, failure_row = "phase plan", "n"
            runnable, reasons = phase_case_plan(cfg.get("phase_cases", []), cfg["phase_cases_blocked"], recipes)
            for index, case in enumerate(runnable):
                stage = f"phase-{index} ({case['name']})"
                if cfg.get("phase_settle") is None:
                    collected[f"phase-{index}"] = {"n": ("OPEN", {
                        "reason": f"no measured overlay settle policy for {title}"})}
                    continue
                case_save, case_cfg, missing = phase_case_input(case, cfg, save, codec, decoded.profile)
                if missing:
                    collected[f"phase-{index}"] = {"n": ("OPEN", {"reason": missing})}
                    continue
                rows, _ = launch_probe(module, title, source, case_save, profile, base, f"phase-{index}", batch / f"phase-{index}",
                                       {**case_cfg, "phase_case": case, "route": case["route"]})
                collected[f"phase-{index}"] = rows
            baseline_model = (observations.get("n") or {}).get("model")
            if baseline_model is None:
                registry = api._runtime.execute((REPO / "lua/hook_registry.lua").read_text(encoding="utf-8"))
                baseline_model = from_lua(api.phase_controls(registry))
            finish_phase_n(observations, errors, collected, reasons, baseline_model, api=api)
        performance = os.environ.get("SLINK_GEN4_PERF_RECEIPT")
        if performance:
            stage, failure_row = "PERF consumer", "f"
            observed_perf, perf_reason = perf_f(performance.format(title=title), title, rom_sha1, source_head)
            if observed_perf is not None:
                observations["f"] = observed_perf
                errors.pop("f", None)
            else:
                errors["f"] = ("OPEN", {"reason": perf_reason})
        external = os.environ.get("SLINK_GEN4_ROW_O")
        stage, failure_row = "row o consumer", "o"
        required_o = row_o(Path(external.format(title=title)) if external else None, title, rom_sha1, source_head)
        stage, failure_row = "final evaluation / surface check", "a"
        result, rows = finish_rows(api, observations, errors, required_o)
        committed_cut(title, profile=profile, source_head=source_head)
        missed = publish_control_evidence(batch, collected, rows)
        for row, (status, payload) in rows.items():
            if row == "o":
                continue  # Preserve the C1-8 producer's independently bound surface.
            payload = {**payload, "schema": "gen4-probe-row-v1", "title": title, "rom_sha1": rom_sha1,
                       "source_head": source_head, "level": "PHYSICAL", "run_id": batch.name,
                       "script_sha256": digest(SCRIPT), "profile_sha256": digest(profile), "requested_rate": 300}
            payload.update(module_sha256=cut["module_sha256"], surface_sha256=cut["surface_sha256"], receipt_kind=cut["receipt_kind"])
            payload.update(supplied, scenario_role="row_i" if row == "i" else "baseline")
            if row == "n":
                payload["pc_case_setup"] = attempt_metadata["pc_case_setup"]
            payload.update(save_setup(row_i_save if row == "i" else save))
            rows[row] = (status, payload)
        stage, failure_row = "original-save check", "i"
        assert digest(save) == before_save and digest(row_i_save) == before_row_i_save and (before_pc_save is None or digest(pc_save) == before_pc_save), "original save was modified"
        result = publish_combined(batch, rows, {})
        assert not missed, f"control(s) did not produce their targeted red in {batch}: {missed}"
        assert result != "FAIL", f"G1 FAIL; preserved receipt {batch / 'combined.txt'}"
        if result == "OPEN":
            missing = "; ".join(f"{row}: {payload.get('reason')}" for row, (status, payload) in rows.items() if status == "OPEN")
            pytest.skip(f"OPEN G1 {title}: {missing}; receipt {batch / 'combined.txt'}")
    finally:
        failure = sys.exc_info()[1]
        try:
            unchanged = digest(save) == before_save and digest(row_i_save) == before_row_i_save and (before_pc_save is None or digest(pc_save) == before_pc_save)
        except OSError:
            unchanged = False
        if not unchanged:
            stage, failure_row = "original-save check", "i"
            failure = AssertionError("original save was modified")
        if failure is not None and (not (batch / "combined.txt").exists() or not unchanged):
            publish_aborted_attempt(batch, api, collected, observations, errors, required_o,
                                    attempt_metadata, stage, failure_row, failure)
        assert unchanged, "original save was modified"

@pytest.mark.parametrize("failure", ("baseline", "persistence", "phase-launch", "phase-observation", "row-o", "surface", "original-save", "row-i-original-save", "graded-no-settle", "phase-row-n-fail", "aggregate-baseline-open"))
@pytest.mark.parametrize("title", TITLE_PACK)
def test_every_attempt_failure_publishes_before_raise(api, monkeypatch, tmp_path, failure, title, baseline_synth=False):
    """Replay the real orchestration boundary without launching an emulator."""
    import sys
    from types import SimpleNamespace
    module = sys.modules[__name__]
    registry_text = (REPO / "lua/hook_registry.lua").read_text()
    (tmp_path / "lua").mkdir()
    (tmp_path / "lua/hook_registry.lua").write_text(registry_text)
    source, save, base = (tmp_path / name for name in ("rom.nds", "played.sav", "config.ini"))
    boxed = tmp_path / "boxed.sav"
    for path in (source, save, boxed, base):
        path.write_bytes(b"fixture")
    profile = tmp_path / "data/games" / TITLE_PACK[title] / "profile.json"
    profile.parent.mkdir(parents=True)
    artifact = {"rom": {"sha1": digest(source, "sha1"), "md5": digest(source, "md5")},
                "phases": {"battle": {"cap": 2}, "pc": {"cap": 2}},
                "phase_cases": [{"name": "battle"}], "route_legs": {},
                "sites": {"hge_load_arm9_expansion": {"symbol": "load_arm9_expansion"},
                          "load_overlay_noinit_async": {"symbol": "LoadOverlayNoInitAsync"}}}
    profile.write_text(json.dumps({"schema": "gen4-profile-v1", "titles": {title: artifact}}))
    native_inventory = tmp_path / f'data/gen4/scenarios/{title}.json'
    native_inventory.parent.mkdir(parents=True)
    native_inventory.write_text(json.dumps({'save':{'setup':'NATIVE','sha256':digest(save)}}))
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setenv("SLINK_GEN4_" + title.upper(), str(source))
    monkeypatch.setenv("SLINK_GEN4_" + title.upper() + "_SAVE", str(save))
    monkeypatch.setenv("SLINK_BIZHAWK_CONFIG", str(base))
    monkeypatch.setenv("SLINK_GEN4_PROBE_RUNS", str(tmp_path / "runs"))
    monkeypatch.delenv("SLINK_GEN4_PERF_RECEIPT", raising=False)
    monkeypatch.setattr(module, "fixture_module", lambda: object())
    monkeypatch.setattr(module, "scenario_input", lambda title: {"scenario_path":"MODEL-scenario.json","scenario_save": str(save), "row_i_save": str(boxed)})
    monkeypatch.setattr(module,"load_scenario",lambda *args,**kwargs: ({'title':title,'save':{'setup':'NATIVE','sha256':digest(save)}},save,'MODEL'))
    monkeypatch.setattr(module, "codec_module", lambda: SimpleNamespace(
        parse_save=lambda *args: SimpleNamespace(profile="hgss",party=lambda: [{"pid":2}], boxes=lambda: [])))
    monkeypatch.setattr(module, "source_witness", lambda *args: {})
    def census_pins(source, artifact, title, internal_loads):
        assert internal_loads == internal_census_loads(title, artifact)
        return {}
    monkeypatch.setattr(module, "census_file_pins", census_pins)
    monkeypatch.setattr(module, "phase_settle_policy", lambda *args: None if failure == "graded-no-settle" else {})
    monkeypatch.setattr(module, "phase_image_pins", lambda *args: {})
    monkeypatch.setattr(module, "save_setup", lambda path: {"setup": "NATIVE"})
    if baseline_synth:
        side=Path(str(save)+'.synth.json')
        side.write_text(json.dumps({'src_sha1':'0'*40,'out_sha1':digest(save,'sha1'),'new_pid':1}))
        declared={'title':title,'save':{'setup':'SYNTH','sha256':digest(save),'sidecar_sha256':digest(side)}}
        boxed_side=Path(str(boxed)+'.synth.json')
        boxed_side.write_text(json.dumps({'src_sha1':'0'*40,'out_sha1':digest(boxed,'sha1'),'new_pid':2}))
        real_save_setup=next(r[1] for r in _HARNESS_FUNCTIONS if r[0]=='save_setup')
        monkeypatch.setattr(module,'load_scenario',lambda *args,**kwargs:(declared,save,'MODEL'))
        monkeypatch.setattr(module,'save_setup',lambda path:real_save_setup(path))
    monkeypatch.setattr(module, "phase_case_plan", lambda *args: ([{"name": "battle", "route": []}], []))
    cut_calls = 0
    def cut(*args, **kwargs):
        nonlocal cut_calls
        cut_calls += 1
        if failure == "surface" and cut_calls > 1:
            raise AssertionError("STALE changed surface")
        return MODEL_CUT
    monkeypatch.setattr(module, "committed_cut", cut)
    good = examples()
    external_calls = []
    def launch(*args):
        case = args[6]
        assert args[-1]["internal_loads"] == internal_census_loads(title, artifact)
        assert args[-1]["rtc_sample_frame"] == 1200
        if failure == "baseline" and case == "baseline":
            raise AssertionError("terminal receipt absent")
        if failure == "phase-launch" and case.startswith("phase-"):
            raise PermissionError("bridge response replace denied")
        rows = {row: ("PASS", {"observation": copy.deepcopy(value)}) for row, value in good.items()}
        if case in CONTROL_REDS:
            for row, needle in CONTROL_REDS[case].items():
                rows[row] = ("FAIL", {"reason": needle, "observation": copy.deepcopy(good[row])})
        if case == "patched-rom":
            rows["j"][1]["observation"]["hash"] = "3" * 40
        if case == "rtc-unpinned":
            rows["k"][1]["observation"]["first"] = "wallclock"
        if case == "no-buttons":
            rows["l"][1]["observation"]["overworld"] = False
        if failure == "phase-observation" and case.startswith("phase-"):
            rows["n"] = ("FAIL", {"reason": "route until predicate not reached", "observation": {}})
        if case == "baseline" and failure in {"graded-no-settle", "phase-row-n-fail", "aggregate-baseline-open"}:
            rows["n"] = ("OPEN", {"reason": "n:normal-input phase case absent"})
        if case.startswith("phase-") and failure == "phase-row-n-fail":
            rows["n"] = ("FAIL", {"reason": "deliberate phase n failure", "observation": copy.deepcopy(good["n"])})
        if case.startswith("phase-") and failure == "graded-no-settle":
            rows["n"] = ("OPEN", {"reason": "no measured overlay settle policy", "observation": {}})
        if failure == "original-save":
            save.write_bytes(b"modified")
        return rows, save
    monkeypatch.setattr(module, "launch_probe", launch)
    def persistence(*args):
        assert args[5] == boxed, "row i must use its separate boxed descendant"
        if failure == "row-i-original-save":
            boxed.write_bytes(b"modified")
        if failure == "persistence":
            raise AssertionError("cold RAM identity drift")
        return copy.deepcopy(good["i"]), None
    monkeypatch.setattr(module, "persistence_rows", persistence)
    def external(*args):
        external_calls.append(True)
        if failure == "row-o":
            raise AssertionError("present row-o receipt is wrong")
        return ("PASS", {"reason": "MODEL external row"})
    monkeypatch.setattr(module, "row_o", external)
    if failure == "aggregate-baseline-open":
        test_gen4_hook_probe(api, title)
    else:
        exception = pytest.skip.Exception if failure == "graded-no-settle" else (AssertionError, PermissionError)
        with pytest.raises(exception):
            test_gen4_hook_probe(api, title)
    batch, = (tmp_path / "runs").iterdir()
    assert (batch / "control-reds.json").is_file(), failure
    combined = (batch / "combined.txt").read_text()
    expected = "PASS" if failure == "aggregate-baseline-open" else "OPEN" if failure == "graded-no-settle" else "FAIL"
    assert combined.rstrip().endswith("RESULT: " + expected), failure
    rows = [ROW_RE.fullmatch(line) for line in combined.splitlines()[:-1]]
    assert all(rows) and {m[1] for m in rows} == set("abcdefghijklmno")
    written = {m[1]: (m[2], json.loads(m[3])) for m in rows}
    if baseline_synth:
        assert all(payload.get('setup')=='SYNTH' and payload.get('sidecar_sha256')==digest(boxed_side if row=='i' else side)
                   for row,(_,payload) in written.items() if row in set(ROWS))
    if failure in {"graded-no-settle", "phase-row-n-fail", "aggregate-baseline-open"}:
        assert external_calls and written["o"][0] == "PASS"
        assert written["i"][0] == "PASS" and written["k"][0] == "PASS"
        assert written["n"][0] == expected
        if failure == "graded-no-settle":
            assert "no measured overlay settle policy for " + title in written["n"][1]["reason"]
            # Reintroduce the former title-abort behavior in memory, then revert it.
            import inspect
            source_text = inspect.getsource(test_gen4_hook_probe)
            source_text = source_text[source_text.index("def test_gen4_hook_probe") :]
            source_text = source_text.replace('if cfg.get("phase_settle") is None:', 'if False:')
            needle = '                collected[f"phase-{index}"] = rows'
            source_text = source_text.replace(needle, needle + '\n                assert (rows["n"][1].get("observation") or {}).get("physical") is not None, "old phase abort"')
            namespace = dict(globals())
            exec(source_text, namespace)
            before_calls = len(external_calls)
            monkeypatch.setenv("SLINK_GEN4_PROBE_RUNS", str(tmp_path / "mutant-runs"))
            with pytest.raises(AssertionError, match="old phase abort"):
                namespace["test_gen4_hook_probe"](api, title)
            assert len(external_calls) == before_calls  # red: row o was never reached
            monkeypatch.setenv("SLINK_GEN4_PROBE_RUNS", str(tmp_path / "reverted-runs"))
            with pytest.raises(pytest.skip.Exception):
                test_gen4_hook_probe(api, title)
            assert len(external_calls) == before_calls + 1
        elif failure == "aggregate-baseline-open":
            assert written["n"][1]["observation"]["physical"]["cases"]
        else:
            assert "phase-0" in written["n"][1]["reason"]
    elif failure == "phase-observation":
        assert written["n"][0] == "FAIL" and external_calls
    else:
        assert any("attempt_failure" in json.loads(m[3]) for m in rows), failure

def test_declared_synth_baseline_orchestration_discloses_receipts(api,monkeypatch,tmp_path):
    test_every_attempt_failure_publishes_before_raise(api,monkeypatch,tmp_path,'graded-no-settle','heartgold',baseline_synth=True)


def test_hge_internal_census_config_covers_pinned_loaders_red_revert():
    artifact = json.loads((REPO / "data/games/gen4_hge/profile.json").read_text())["titles"]["heartgold_hge"]
    entries = internal_census_loads("heartgold_hge", artifact)
    assert len(entries) + 2 <= 4
    assert entries == [
        {"symbol": artifact["sites"]["hge_load_arm9_expansion"]["symbol"], "id": 129, "region": 0,
         "source": "pack:hge_load_arm9_expansion (constant overlay 129)"},
        {"symbol": artifact["sites"]["load_overlay_noinit_async"]["symbol"], "id_register": "ARM9 r1", "ids": [130, 131], "region": 0,
         "source": "pack:load_overlay_noinit_async (overlay ID in r1)"},
    ]
    assert internal_census_loads("heartgold", artifact) == []
    for missing in ("hge_load_arm9_expansion", "load_overlay_noinit_async"):
        broken = copy.deepcopy(artifact)
        del broken["sites"][missing]
        with pytest.raises(AssertionError, match=missing):
            internal_census_loads("heartgold_hge", broken)
        assert internal_census_loads("heartgold_hge", artifact) == entries


def test_internal_funnel_filters_vanilla_duplicate_and_omission_stays_red(api):
    entry = {"id_register": "ARM9 r1", "ids": [130, 131]}
    causes = [{"id": 42, "region": 0, "kind": "load", "frame": 10, "source": "vanilla loader"}]
    for overlay in (42, 130, 131):
        value = api.internal_load_id(to_lua(api._runtime, entry), lambda name, value=overlay: value)
        if value is not None:
            causes.append({"id": value, "region": 0, "kind": "load", "frame": 10, "source": "internal loader"})
    assert [v["id"] for v in causes] == [42, 130, 131]
    x = copy.deepcopy(examples()["c"])
    x["changes"] = [{**cause, "frame": 11} for cause in causes]
    x["causes"] = causes
    assert api.evaluate("c", to_lua(api._runtime, x)) == "PASS"
    broken = copy.deepcopy(x)
    broken["causes"].pop(0)
    assert api.evaluate("c", to_lua(api._runtime, broken))[0] == "FAIL"
    assert api.evaluate("c", to_lua(api._runtime, x)) == "PASS"
    duplicate = copy.deepcopy(x)
    duplicate["causes"].append(copy.deepcopy(causes[0]))
    outcome = api.evaluate("c", to_lua(api._runtime, duplicate))
    assert outcome[0] == "FAIL" and "omitted cause" in outcome[1]


def test_full_pin_failure_identifies_site_image_and_bytes(api):
    artifact = json.loads((REPO / "data/games/gen4_hgss/profile.json").read_text())["titles"]["heartgold"]
    site = {**artifact["sites"]["battle_start_ov12"], "id": "battle_start_ov12"}
    wrong = "00" * site["extent"]
    with pytest.raises(Exception, match="full registration pin mismatch.*battle_start_ov12.*ov12.*actual=" + wrong):
        api.validate_site(to_lua(api._runtime, artifact), to_lua(api._runtime, site), lambda *args: wrong, lambda _: True)
    assert api.validate_site(to_lua(api._runtime, artifact), to_lua(api._runtime, site),
                             lambda *args: site["register_hex"], lambda _: True) is not None


def test_async_active_bss_waits_for_pin_then_rechecks_red_revert(api):
    artifact = json.loads((REPO / "data/games/gen4_hgss/profile.json").read_text())["titles"]["heartgold"]
    site = {**artifact["sites"]["battle_start_ov12"], "id": "battle_start_ov12"}
    bss = "000400fc0010000422262225000a0006"  # PHYSICAL HG phase-0 / serial settle diagnostic.
    expected = site["register_hex"]
    state = to_lua(api._runtime, {"current": {}, "samples": []})
    frame, active, actual = 100, True, bss
    policy = {"max_frames": 16, "measured_max": 11, "margin": 5}
    def ready():
        if api.phase_sites_ready is None:  # Replay the old arm path before introducing the fix.
            api.validate_site(to_lua(api._runtime, artifact), to_lua(api._runtime, site), lambda *args: actual, lambda _: active)
            return True
        return api.phase_sites_ready(to_lua(api._runtime, [site]), lambda *args: actual, lambda _: active,
                                     frame, state, to_lua(api._runtime, policy),
                                     to_lua(api._runtime, {site["id"]: {"ov74": "11" * site["extent"]}}))
    assert ready() is False  # No registration while the table is active but field BSS remains.
    frame = 110
    assert ready() is False
    frame, actual = 111, expected
    assert ready() is True
    samples = from_lua(state)["samples"]
    assert samples[1]["table_active_frame"] == 100 and samples[1]["settle_frames"] == 11
    actual = bss
    with pytest.raises(Exception, match="confirmed site changed.*battle_start_ov12"):
        ready()
    actual = expected
    assert ready() is True
    active = False
    assert ready() is False
    active, actual, frame = True, bss, 200
    assert ready() is False  # A new residency generation gets a fresh, bounded wait.
    frame = 216
    with pytest.raises(Exception, match="settle deadline.*battle_start_ov12.*actual=" + bss):
        ready()
    actual = expected
    assert ready() is True  # Matching exactly at the deadline is allowed.
    active = False
    assert ready() is False
    active, actual, frame = True, "11" * site["extent"], 300
    with pytest.raises(Exception, match="wrong-image match.*ov74"):
        ready()  # A known wrong image is never treated as loading.


def test_settle_trace_starts_before_caller_predicate_and_static_sites_never_wait(api):
    site = {"id": "probe", "image": "ov12", "overlay_id": 12, "address": 100, "extent": 4, "register_hex": "01020304"}
    state = to_lua(api._runtime, {"current": {}, "samples": []})
    policy = to_lua(api._runtime, {"max_frames": 16})
    pins = to_lua(api._runtime, {"probe": {"ov74": "ffffffff"}})
    def ready(frame, raw, wanted):
        return api.phase_sites_ready(to_lua(api._runtime, [site]), lambda *args: raw, lambda _: True,
                                     frame, state, policy, pins, wanted)
    assert ready(100, "00000000", False) is False
    assert ready(105, "01020304", False) is True
    assert ready(110, "01020304", True) is True
    assert from_lua(state)["samples"][1]["settle_frames"] == 5
    # Once the caller ends, stale/overwritten bytes cannot keep handles armed;
    # the monitor closes them because wanted is false, while polling continues.
    assert ready(120, "ffffffff", False) is False
    with pytest.raises(Exception, match="confirmed site changed"):
        ready(120, "ffffffff", True)
    site["image"] = "arm9"
    state = to_lua(api._runtime, {"current": {}, "samples": []})
    with pytest.raises(Exception, match="static pin mismatch"):
        ready(200, "00000000", True)


def test_settle_policy_is_measured_title_only_and_collision_pins_are_rom_bytes():
    for title, pack in TITLE_PACK.items():
        artifact = json.loads((REPO / "data/games" / pack / "profile.json").read_text())["titles"][title]
        policy = phase_settle_policy(title, artifact)
        assert policy["max_frames"] == policy["measured_max"] + policy["margin"] == (6 if title=='heartgold_hge' else 16)
        broken = copy.deepcopy(artifact)
        broken["rom"]["sha1"] = "0" * 40
        with pytest.raises(AssertionError, match="measurement ROM changed"):
            phase_settle_policy(title, broken)
        if title!='heartgold':
            continue  # preserve this existing HG collision FILE claim; other titles have separate pins
        rom = gen4_pins.default_locations().roms[title]
        if not rom.is_file():
            pytest.skip("OPEN optional HG ROM for collision FILE pins")
        pins = phase_image_pins(rom, artifact, title)
        assert set(pins["battle_start_ov12"]) == set(artifact["sites"]["battle_start_ov12"]["collides_with"])
        assert all(len(pin) == artifact["sites"]["battle_start_ov12"]["extent"] * 2
                   for pin in pins["battle_start_ov12"].values())


@pytest.mark.skipif(os.name != "nt", reason="Windows destination sharing contract")
def test_bridge_replace_retries_a_real_open_destination(tmp_path):
    import ctypes
    import threading
    from ctypes import wintypes
    source, destination = tmp_path / "response.tmp", tmp_path / "response.json"
    source.write_text("new complete response")
    destination.write_text("old response")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(str(destination), 0x80000000, 1, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    # Lua's rb reader permits reads but can prevent replacement until it closes.
    timer = threading.Timer(0.15, lambda: kernel.CloseHandle(handle))
    timer.start()
    try:
        replace = globals().get("replace_with_retry", lambda src, dst, **kw: src.replace(dst))
        replace(source, destination, attempts=20, delay=0.025)
    finally:
        timer.join()
    assert destination.read_text() == "new complete response"
    assert not source.exists()


def test_bridge_replace_bound_fails_loud_and_other_errors_do_not_retry(monkeypatch, tmp_path):
    calls = []
    def locked(*args):
        calls.append(args)
        raise PermissionError("destination remains open")
    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr(time, "sleep", lambda delay: None)
    with pytest.raises(PermissionError, match="destination remains open"):
        replace_with_retry(tmp_path / "source", tmp_path / "dest", attempts=3, delay=0)
    assert len(calls) == 3
    def missing(*args):
        calls.append(args)
        raise FileNotFoundError("source absent")
    calls.clear()
    monkeypatch.setattr(Path, "replace", missing)
    with pytest.raises(FileNotFoundError, match="source absent"):
        replace_with_retry(tmp_path / "source", tmp_path / "dest", attempts=3, delay=0)
    assert len(calls) == 1


@pytest.mark.parametrize("prefix,purpose", (("scenario", "baseline"), ("row_i_scenario", "row_i"), ("pc_case_scenario", "pc_case")))
def test_scenario_receipt_hash_red_and_revert(tmp_path, monkeypatch, prefix, purpose):
    """MODEL: same code/ROM receipt must refuse changed scenario bytes."""
    import sys
    monkeypatch.setattr(sys.modules[__name__], "REPO", tmp_path)
    scenario = tmp_path / "data/gen4/scenarios/hg.json"
    scenario.parent.mkdir(parents=True)
    original = json.dumps({"schema": "gen4-probe-scenario-v3", "title": "heartgold", "purpose": purpose}).encode()
    scenario.write_bytes(original)
    text = receipt(**{prefix + "_path": "data/gen4/scenarios/hg.json", prefix + "_sha256": digest(scenario)})
    def consume():
        return parse_receipt(text, title="heartgold", rom_sha1="2" * 40, expected_cut=MODEL_CUT)
    assert consume()["a"][0] == "PASS"
    scenario.write_bytes(original + b" ")
    with pytest.raises(StaleReceiptError, match="STALE scenario"):
        consume()
    scenario.write_bytes(original)
    assert consume()["a"][0] == "PASS"


@pytest.mark.parametrize("prefix", ("scenario", "row_i_scenario", "pc_case_scenario"))
def test_scenario_binding_requires_current_title_and_inventory(tmp_path, monkeypatch, prefix):
    import sys
    monkeypatch.setattr(sys.modules[__name__], "REPO", tmp_path)
    path = tmp_path / "data/gen4/scenarios/input.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": "gen4-probe-scenario-v3", "title": "heartgold",
                                "purpose": {"scenario": "baseline", "row_i_scenario": "row_i", "pc_case_scenario": "pc_case"}[prefix]}))
    good = {prefix + "_path": "data/gen4/scenarios/input.json", prefix + "_sha256": digest(path)}
    bind_scenarios(good, "heartgold", required=False)
    for patch, why in (({prefix + "_sha256": "0" * 64}, "hash"),
                       ({prefix + "_path": "../input.json"}, "outside"),
                       ({prefix + "_path": "C:/input.json"}, "outside")):
        with pytest.raises(StaleReceiptError, match="STALE scenario.*" + why):
            bind_scenarios({**good, **patch}, "heartgold", required=False)
        bind_scenarios(good, "heartgold", required=False)
    with pytest.raises(StaleReceiptError, match="title/purpose"):
        bind_scenarios(good, "soulsilver", required=False)
    with pytest.raises(StaleReceiptError, match="STALE scenario"):
        bind_scenarios({}, "heartgold")


@pytest.mark.parametrize("name", ("scenario_input", "load_scenario", "phase_case_plan", "resolve_pack_route", "launch_probe", "persistence_rows"))
def test_real_launch_refuses_in_process_harness_overrides(monkeypatch, tmp_path, name):
    import sys
    module = sys.modules[__name__]
    original_launch = launch_probe
    assert_harness_functions()
    with monkeypatch.context() as changed:
        changed.setattr(module, name, lambda *args: {})
        with pytest.raises(AssertionError, match="in-process harness override forbidden: " + name):
            original_launch(None, "heartgold", None, None, None, None, "baseline", tmp_path / "lane", {})
        assert not (tmp_path / "lane").exists()
        changed.setenv("SLINK_LIVE", "1")
        with pytest.raises(AssertionError, match="in-process harness override forbidden: " + name):
            test_gen4_hook_probe(None, "heartgold")
    assert_harness_functions()


@pytest.mark.parametrize("title", TITLE_PACK)
def test_committed_scenario_inputs_preserve_pack_routes_and_boxed_ancestry(title):
    baseline = f"data/gen4/scenarios/{title}.json"
    doc, save, sha = load_scenario(baseline, title, "baseline", committed=False)
    assert not {"route", "phase_cases", "phase_cases_blocked", "persistence_route"} & doc.keys()
    artifact = json.loads((REPO / "data/games" / TITLE_PACK[title] / "profile.json").read_text())["titles"][title]
    assert len(artifact["phase_cases"]) == 6
    route, why = resolve_pack_route(artifact["route"], artifact["route_legs"])
    assert route and not why
    _, boxed, boxed_sha = load_scenario(doc["row_i_scenario"], title, "row_i", committed=False)
    assert boxed != save and save_setup(save)["setup"] == "NATIVE"
    setup = save_setup(boxed)
    assert setup["setup"] == "SYNTH"
    codec = codec_module()
    decoded = codec.parse_save(boxed.read_bytes(), "hge" if title == "heartgold_hge" else "hgss")
    assert synth_identity_present(decoded, setup["new_pid"])
    assert len(decoded.party()) == 1 and any(b["mons"] for b in decoded.boxes())
    _, pc_save, pc_sha = load_scenario(doc["pc_case_scenario"], title, "pc_case", committed=False)
    assert pc_save != save and pc_save != boxed
    pc_decoded = codec.parse_save(pc_save.read_bytes(), decoded.profile)
    assert len(pc_decoded.party()) == 2 and save_setup(pc_save)["setup"] == "SYNTH"
    bind_scenarios({"scenario_path": baseline, "scenario_sha256": sha,
                    "row_i_scenario_path": doc["row_i_scenario"], "row_i_scenario_sha256": boxed_sha,
                    "pc_case_scenario_path": doc["pc_case_scenario"], "pc_case_scenario_sha256": pc_sha}, title)


def test_scenario_load_rejects_overrides_and_wrong_save_hash_then_reverts(tmp_path, monkeypatch):
    import sys
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "lane_root", lambda: tmp_path / "lane")
    save = tmp_path / "lane/saves/native.SaveRAM"
    save.parent.mkdir(parents=True)
    save.write_bytes(b"native model save")
    relative = "data/gen4/scenarios/heartgold.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    doc = {"schema": "gen4-probe-scenario-v3", "title": "heartgold", "purpose": "baseline",
           "save": {"setup":"NATIVE", "path": "saves/native.SaveRAM", "sha256": digest(save)}}
    def load(value):
        path.write_text(json.dumps(value))
        return load_scenario(relative, "heartgold", "baseline", committed=False)
    assert load(doc)[1] == save
    for patch, why in (({"route": []}, "runtime overrides"), ({"phase_cases": []}, "runtime overrides"),
                       ({"save": {"path": "saves/native.SaveRAM", "sha256": "0" * 64}}, "save hash mismatch"),
                       ({"save": {"path": "../outside.SaveRAM", "sha256": digest(save)}}, "lane-relative")):
        with pytest.raises(AssertionError, match=why):
            load({**doc, **patch})
        assert load(doc)[1] == save


def test_harness_in_place_code_replacement_is_refused_and_reverts(monkeypatch):
    with monkeypatch.context() as changed:
        changed.setattr(scenario_input, "__code__", (lambda *args: {}).__code__)
        with pytest.raises(AssertionError, match="override forbidden: scenario_input"):
            assert_harness_functions()
    assert_harness_functions()


BOUNDARY_REPLAY = r"""
local callbacks={}; local frame=0; local wanted=true; local state
local Registry=load(REGISTRY_TEXT)()
local binding={validate=function(s) return s end,
 register=function(s,cb) callbacks[s.id]=cb; return "boundary-"..s.id end,
 unregister=function() return true end,
 capture=function(s) return {id=s.id,frame=frame,step_id=state.step_id} end}
local composite=M.composite(Registry,binding)
local monitor; monitor,state=M.phase_monitor(composite,"battle_close",{{id="exit"}},"exit",
 function() return wanted end,function() return true end,function() return frame end)
monitor.before(); frame=1; callbacks.exit(); wanted=false; monitor.after()
monitor.before(); monitor.after(); monitor.finish()
return state,composite:live_handles()
"""


def test_closing_frame_monitor_preserves_pending_once_red_revert(api):
    r = api._runtime
    r.globals().M = api._api
    r.globals().REGISTRY_TEXT = (REPO / "lua/hook_registry.lua").read_text()
    state, retained = r.execute(BOUNDARY_REPLAY)
    assert state["pending_at_close"] == 1 and retained == 0 and state["second_drain"] == 0
    assert list(state["seen"].values()) == [1]
    boundary = state["close_boundaries"][1]
    assert boundary["frame"] == 1 and boundary["pending"] == 1 and boundary["seam"] == "pre_close"
    assert list(boundary["producer_frames"].values()) == [1]
    text = SCRIPT.read_text()
    for old, new, field, expected in (
        ("if wanted or not armed then", "if true then", "pending_at_close", 0),
        (
            "for _,e in ipairs(reg:drain()) do self.ready_events[#self.ready_events+1]=e end",
            "",
            "seen",
            0,
        ),
    ):
        assert text.count(old) == 1
        changed = r.execute(text.replace(old, new))
        r.globals().M = changed
        bad, _ = r.execute(BOUNDARY_REPLAY)
        assert (len(bad[field]) if field == "seen" else bad[field]) == expected
        r.globals().M = r.execute(text)
        good, retained = r.execute(BOUNDARY_REPLAY)
        assert good["pending_at_close"] == 1 and len(good["seen"]) == 1 and retained == 0


def test_pc_phase_fixture_absent_never_uses_baseline(tmp_path):
    baseline = tmp_path / "baseline.SaveRAM"
    baseline.write_bytes(b"not the party2 fixture")
    save, cfg, reason = phase_case_input(
        {"name": "pc", "fixture_role": "pc_case"}, {}, baseline, None, "hgss"
    )
    assert save is None and cfg is None and "pc_case" in reason
    import inspect

    text = inspect.getsource(phase_case_input)
    needle = 'return None, None, "pc: dedicated hash-bound pc_case party2 fixture absent"'
    namespace = dict(globals())
    exec(text.replace(needle, "return baseline, cfg, None"), namespace)
    bad_save, _, _ = namespace["phase_case_input"](
        {"name": "pc", "fixture_role": "pc_case"}, {}, baseline, None, "hgss"
    )
    assert bad_save == baseline  # falsifier detects the forbidden fallback
    assert (
        phase_case_input({"name": "pc", "fixture_role": "pc_case"}, {}, baseline, None, "hgss")[0]
        is None
    )


def test_static_pc_never_labels_an_overlay_as_arm9(api):
    r = api._runtime
    case = to_lua(r, {"name": "pc", "phase": "pc", "fixture_role": "pc_case"})
    assert api.static_pc(case, to_lua(r, {"image": "arm9"})) is True
    assert api.static_pc(case, to_lua(r, {"image": "ov129", "overlay_id": 129})) is False
    assert api.static_pc(case, to_lua(r, {"image": "arm9", "overlay_id": 129})) is False
    assert api.static_pc(case, to_lua(r, {"image": "arm9"})) is True


def test_aggregate_n_requires_a_witnessed_closing_frame_case(api):
    # OMP cx-3d38711e F5/F6: a summed pending_at_close from an unrelated case must not stand in for the oracle.
    r = api._runtime
    good = examples()["n"]
    assert api.evaluate("n", to_lua(r, good)) == "PASS"
    bad = copy.deepcopy(good)
    bad["physical"]["cases"] = [c for c in bad["physical"]["cases"] if not c.get("close_boundary_required")]
    status, why = api.evaluate("n", to_lua(r, bad))
    assert status == "FAIL" and "no closing-frame boundary case" in why


def test_battle_close_flag_fails_closed_on_the_lua_copy(api):
    # OMP cx-3d38711e F2/F3: the pack-to-Lua copy of close_boundary must never silently skip the oracle.
    r = api._runtime
    assert api.close_boundary_required(to_lua(r, {"name": "battle_close", "close_boundary": True})) is True
    assert api.close_boundary_required(to_lua(r, {"name": "battle", "phase": "battle"})) is False
    for case in ({"name": "battle_close"}, {"name": "battle_close", "close_boundary": "true"},
                 {"name": "battle_close", "close_boundary": 1}):
        ok, why = r.globals().pcall(api.close_boundary_required, to_lua(r, case))
        assert not ok and dict(why.items()).get("open") == "n:battle_close case without pack close_boundary"
    # the measurement copies the flag only through this function (no second derivation to drift)
    source = (REPO / "lua/tests/probe_gen4_hooks.lua").read_text(encoding="utf-8")
    assert source.count("close_boundary_required=M.close_boundary_required(case)") == 1
    assert len(re.findall(r"close_boundary_required=(?!=)", source)) == 1


def test_closing_frame_validator_requires_the_oracle_and_one_delivery(api):
    r = api._runtime
    good = examples()["n"]
    case = copy.deepcopy(good["physical"]["cases"][0])
    case.update(
        close_boundary_required=True,
        oracle_frames=[7],
        seen_frames=[7],
        oracle_steps=[1],
        seen_steps=[1],
        close_boundaries=[
            {
                "frame": 7,
                "pending": 1,
                "predicate_after": False,
                "producer_frames": [7],
                "producer_steps": [1], "fall_step_id": 1, "predicate_before": True,
                "seam": "pre_close",
            }
        ],
    )
    good["physical"]["cases"] = [case]
    assert api.evaluate("n", to_lua(r, good)) == "PASS"
    for patch in (
        {"close_boundaries": []},
        {"seen_frames": [7, 7]},
        {
            "close_boundaries": [
                {
                    "frame": 7,
                    "pending": 0,
                    "predicate_after": False,
                    "producer_frames": [7],
                    "seam": "pre_close",
                }
            ]
        },
        {
            "close_boundaries": [
                {
                    "frame": 7,
                    "pending": 1,
                    "predicate_after": True,
                    "producer_frames": [7],
                    "seam": "pre_close",
                }
            ]
        },
    ):
        bad = copy.deepcopy(good)
        bad["physical"]["cases"][0].update(patch)
        assert api.evaluate("n", to_lua(r, bad))[0] == "FAIL"
        assert api.evaluate("n", to_lua(r, good)) == "PASS"


@pytest.mark.parametrize("guard", ("deadline", "persistent_pin"))
def test_settle_guard_mutations_red_revert(api, guard):
    r = api._runtime
    source = SCRIPT.read_text()
    policy = to_lua(r, {"max_frames": 4})
    pins = to_lua(r, {"pin": {"ov74": "deadbeef"}})

    def replay(module):
        state = to_lua(r, {"current": {}, "samples": []})

        def ready(frame, raw):
            return module.phase_sites_ready(
                to_lua(
                    r,
                    [
                        {
                            "id": "pin",
                            "image": "ov12",
                            "overlay_id": 12,
                            "address": 100,
                            "extent": 4,
                            "register_hex": "01020304",
                        }
                    ],
                ),
                lambda *args: raw,
                lambda *args: True,
                frame,
                state,
                policy,
                pins,
            )

        assert ready(0, "00000000") is False
        if guard == "deadline":
            return lambda: ready(5, "00000000")
        assert ready(1, "01020304") is True
        return lambda: ready(2, "00000000")

    needle = (
        'check(elapsed<policy.max_frames,"settle deadline ("..policy.max_frames.." frames): "..detail)'
        if guard == "deadline"
        else 'check(not sample.pin_ready_frame,"confirmed site changed: "..detail)'
    )
    assert source.count(needle) == 1
    with pytest.raises(Exception, match="settle deadline|confirmed site changed"):
        replay(api)()
    mutant = r.execute(source.replace(needle, ""))
    assert replay(mutant)() is False  # fault silently deferred by the broken guard
    restored = r.execute(source)
    with pytest.raises(Exception, match="settle deadline|confirmed site changed"):
        replay(restored)()


def test_pc_case_missing_role_never_falls_back(tmp_path):
    baseline = tmp_path / "baseline.sav"
    baseline.write_bytes(b"baseline")
    save, _, reason = phase_case_input({"name": "pc", "phase": "pc"}, {}, baseline, None, "hgss")
    assert save is None and "fixture_role" in reason


@pytest.mark.parametrize("phase_status", ("PASS", "FAIL"))
def test_phase_n_aggregate_exists_without_baseline_observation(phase_status, api):
    good = examples()["n"]
    observations = {}
    errors = {"n": ("OPEN", {"reason": "baseline phase_case absent"})}
    collected = {
        "phase-0": {
            "n": (
                phase_status,
                {
                    "observation": good,
                    "reason": "deliberate phase FAIL" if phase_status == "FAIL" else None,
                },
            )
        }
    }
    finish_phase_n(observations, errors, collected, [], good["model"], api=api)
    assert observations["n"]["physical"]["cases"]
    if phase_status == "FAIL":
        assert errors["n"][0] == "FAIL" and "phase-0" in errors["n"][1]["reason"]
        assert errors["n"][1]["observation"]["physical"]["cases"]
    else:
        assert "n" not in errors


def test_phase_n_aggregation_mutations_and_open_reasons_revert(api):
    import inspect

    good = examples()["n"]
    source = inspect.getsource(finish_phase_n)
    rows = {"phase-0": {"n": ("FAIL", {"reason": "phase failed", "observation": good})}}
    reasons = ["withdraw caller remains OPEN"]

    def run(function):
        observations, errors = {}, {}
        function(observations, errors, rows, reasons, good["model"], api=api)
        return observations, errors

    observations, errors = run(finish_phase_n)
    assert observations["n"]["physical"]["cases"] and errors["n"][0] == "FAIL"
    assert reasons[0] in errors["n"][1]["open_reasons"]
    for old, new in (
        (
            "    measured, failures, opens = [], [], list(reasons)",
            '    if "n" not in observations: return\n    measured, failures, opens = [], [], list(reasons)',
        ),
        ('        if status == "FAIL":', "        if False:"),
    ):
        namespace = dict(globals())
        exec(source.replace(old, new), namespace)
        bad, bad_errors = run(namespace["finish_phase_n"])
        assert "n" not in bad or bad_errors["n"][0] != "FAIL"
        restored, restored_errors = run(finish_phase_n)
        assert restored["n"]["physical"]["cases"] and restored_errors["n"][0] == "FAIL"


def test_pc_family_alias_requires_fixture_and_can_be_static(api, tmp_path):
    baseline = tmp_path / "baseline.sav"
    baseline.write_bytes(b"baseline")
    case = {"name": "pc_deposit", "phase": "pc"}
    save, _, reason = phase_case_input(case, {}, baseline, None, "hgss")
    assert save is None and "fixture_role" in reason
    case["fixture_role"] = "pc_case"
    assert (
        api.static_pc(to_lua(api._runtime, case), to_lua(api._runtime, {"image": "arm9"})) is True
    )


@pytest.mark.parametrize("seam", ("pre_close", "finish"))
@pytest.mark.parametrize("increment_in_callback", (False, True))
def test_boundary_gate_handles_callback_frame_increment(api, seam, increment_in_callback):
    r = api._runtime
    r.globals().M = api._api
    r.globals().REGISTRY_TEXT = (REPO / "lua/hook_registry.lua").read_text()
    replay = BOUNDARY_REPLAY
    if increment_in_callback:
        replay = replay.replace(
            "return {id=s.id,frame=frame,step_id=state.step_id}",
            "local e={id=s.id,frame=frame,step_id=state.step_id}; frame=frame+1; return e",
        )
    if seam == "finish":
        replay = replay.replace(
            "monitor.before(); monitor.after(); monitor.finish()", "monitor.finish()"
        )
    state, retained = r.execute(replay)
    boundary = from_lua(state["close_boundaries"][1])
    assert boundary["seam"] == seam and retained == 0
    good = examples()["n"]
    case = copy.deepcopy(good["physical"]["cases"][0])
    case.update(
        close_boundary_required=True,
        close_boundaries=[boundary],
        oracle_frames=[1],
        seen_frames=[1],
        oracle_steps=[1],
        seen_steps=[1],
    )
    good["physical"]["cases"] = [case]
    assert api.evaluate("n", to_lua(r, good)) == "PASS"
    broken = copy.deepcopy(good)
    broken["physical"]["cases"][0]["close_boundaries"][0]["producer_frames"] = [2]
    assert (
        api.evaluate("n", to_lua(r, broken))[0] == "FAIL"
    )  # frame+1 cannot replace the recorded event
    assert api.evaluate("n", to_lua(r, good)) == "PASS"
    if seam == "finish":
        source = SCRIPT.read_text()
        mutant = r.execute(
            source.replace('(b.seam=="pre_close" or b.seam=="finish")', '(b.seam=="pre_close")')
        )
        assert mutant.evaluate("n", to_lua(r, good))[0] == "FAIL"
        restored = r.execute(source)
        assert restored.evaluate("n", to_lua(r, good)) == "PASS"


def test_n_case_scope_passes_battle_but_aggregate_requires_pc_reset(api):
    good = examples()["n"]
    physical = copy.deepcopy(good["physical"])
    physical.update(static_pc=False, reset=False, pending_at_close=0)
    assert api.evaluate_n_case(to_lua(api._runtime, physical)) == "PASS"
    good["physical"] = physical
    assert api.evaluate("n", to_lua(api._runtime, good))[0] == "FAIL"
    source = SCRIPT.read_text()
    mutation = source.replace(
        "local function validate_n_case(case)",
        'local function validate_n_case(case) check(case.static_pc and case.reset,"old aggregate coverage applied per case")',
        1,
    )
    assert mutation != source
    mutant = api._runtime.execute(mutation)
    assert mutant.evaluate_n_case(to_lua(api._runtime, physical))[0] == "FAIL"
    restored = api._runtime.execute(source)
    assert restored.evaluate_n_case(to_lua(api._runtime, physical)) == "PASS"


@pytest.mark.parametrize("patch", ({"peak": 5}, {"last_seen": 0}))
def test_n_case_invariant_failure_reaches_combined(api, patch):
    good = examples()["n"]
    physical = copy.deepcopy(good["physical"])
    physical.update(patch)
    observations, errors = {}, {}
    finish_phase_n(
        observations,
        errors,
        {"phase-0": {"n": ("PASS", {"observation": {"physical": physical}})}},
        [],
        good["model"],
        api=api,
    )
    assert errors["n"][0] == "FAIL"
    reverted = copy.deepcopy(good["physical"])
    observations, errors = {}, {}
    finish_phase_n(
        observations,
        errors,
        {"phase-0": {"n": ("PASS", {"observation": {"physical": reverted}})}},
        [],
        good["model"],
        api=api,
    )
    assert "n" not in errors


def test_all_a_n_setup_disclosure_control_red_revert(api, monkeypatch, tmp_path):
    import inspect
    import sys

    module = sys.modules[__name__]
    source = inspect.getsource(test_gen4_hook_probe)
    source = source[source.index("def test_gen4_hook_probe") :]
    needle = 'payload.update(save_setup(row_i_save if row == "i" else save))'
    assert source.count(needle) == 1
    mutant = source.replace(needle, 'if row != "n": ' + needle)
    namespace = dict(globals())
    exec(mutant, namespace)
    for name in ("good", "mutant", "revert"):
        run = tmp_path / name
        run.mkdir()
        with monkeypatch.context() as patch:
            if name == "mutant":
                patch.setattr(
                    module.test_gen4_hook_probe,
                    "__code__",
                    namespace["test_gen4_hook_probe"].__code__,
                )
                with pytest.raises(AssertionError):
                    test_every_attempt_failure_publishes_before_raise(
                        api, patch, run, "graded-no-settle", "heartgold", baseline_synth=True
                    )
            else:
                test_every_attempt_failure_publishes_before_raise(
                    api, patch, run, "graded-no-settle", "heartgold", baseline_synth=True
                )
