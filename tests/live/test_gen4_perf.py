"""gen4-PERF: offline harness checks and serial, opt-in private NDS measurement.

Live command (ONLY after lane grant): SLINK_LIVE=1 python -m pytest this_file -m live -q -rs
Titles default HG then hge. Save and <PHASE>_STATE env inputs are required;
SLINK_GEN4_<TITLE>_ROM defaults through gen4_pins.
PERF PASS means complete measurement, NOT 1x qualification. Row f is the authority.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import time
import uuid
from functools import cache
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.live import test_gen4_probe_gates as gates
from tools import gen4_evidence, gen4_fixtures, gen4_pins

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "lua/tests/perf_gen4.lua"
MODULES = (
    "lua/gen4/reads.lua",
    "lua/gen4/pk4.lua",
    "lua/gen4/safety.lua",
    "lua/json_codec.lua",
    "lua/tests/probe_gen4_hooks.lua",
    "lua/socket.lua",
)
NATIVE_NUMERATOR = 33513982
NATIVE_DENOMINATOR = 560190  # 6 * 355 * 263; upstream MelonDS.cs DefaultFps*.
NATIVE_PERIOD = NATIVE_DENOMINATOR / NATIVE_NUMERATOR


def native_statistics(times):
    stats = statistics_of(times)
    longest, run, pairs = 0, 0, 0
    for value in times:
        if value > NATIVE_PERIOD:
            run += 1
            longest = max(longest, run)
            if run == 2:
                pairs += 1
        else:
            run = 0
    return {
        **stats,
        "native_fps": NATIVE_NUMERATOR / NATIVE_DENOMINATOR,
        "native_period": NATIVE_PERIOD,
        "drift_seconds": stats["elapsed_seconds"] - len(times) * NATIVE_PERIOD,
        "over_1_5_native": sum(t > 1.5 * NATIVE_PERIOD for t in times),
        "over_2_native": sum(t > 2 * NATIVE_PERIOD for t in times),
        "longest_consecutive_late": longest,
        "late_runs_at_least_two": pairs,
    }


def sha(path):
    return gates.digest(Path(path))


def required_input(title, suffix, description):
    key = f"SLINK_GEN4_{title.upper()}_{suffix}"
    value = os.environ.get(key)
    if not value:
        pytest.skip(f"OPEN {description}: required env input {key} absent")
    return gates.input_file(Path(value), description)


def statistics_of(times):
    assert times and all(
        isinstance(t, (int, float)) and not isinstance(t, bool) and 0 < t < float("inf")
        for t in times
    ), "bad intervals"
    values = sorted(times)
    n = len(values)
    return {
        "frames": n,
        "p50": values[(n + 1) // 2 - 1],
        "p99": values[(99 * n + 99) // 100 - 1],
        "max": values[-1],
        "over_budget": sum(t > 1 / 60 for t in times),
        "elapsed_seconds": sum(times),
        "fps": n / sum(times),
    }


def read_record(path, *, title, rom_sha1, run_id=None):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[0].startswith("PERF ") and lines[1].startswith("RESULT: "), (
        "bad PERF receipt grammar"
    )
    _, status, raw = lines[0].split(" ", 2)
    assert status in {"PASS", "FAIL", "OPEN"} and lines[1] == f"RESULT: {status}", (
        "contradictory terminal status"
    )
    data = json.loads(raw)
    assert (
        data["schema"] == "gen4-perf-v1"
        and data["producer"] == "gen4-PERF"
        and data["level"] == "PHYSICAL"
    ), "wrong producer/evidence"
    assert data["title"] == title and data["rom_sha1"] == rom_sha1 and data["result"] == status, (
        "wrong artifact/status"
    )
    if run_id is not None:
        assert data["run_id"] == run_id, "stale/wrong-run receipt"
    if status == "PASS":
        derived = statistics_of(data["frame_times"])
        assert derived["frames"] == data["frames_requested"], "missing timing frames"
        for key in ("p50", "p99", "max", "fps", "elapsed_seconds"):
            assert derived[key] == pytest.approx(data["stats"][key]), f"forged {key}"
        assert derived["over_budget"] == data["stats"]["over_budget"], "forged deadline count"
        assert data["ending_registered"] == 0, "unremoved callback"
        assert (
            data["clock_calibration"]["backward_steps"] == 0
            and data["clock_calibration"]["minimum_positive_increment"] <= 0.0001
        ), "unreliable clock"
    return data


def trial_matrix(phase):
    result = []
    cases = {
        "none": [],
        "exec_never": [{"kind": "exec", "site": "never_executed"}],
        "exec_hot": [{"kind": "exec", "site": "OS_DisableInterrupts"}],
        "exec_two_addresses": [
            {"kind": "exec", "site": "never_executed"},
            {"kind": "exec", "site": "blackout"},
        ],
        "exec_same_address_twice": [{"kind": "exec", "site": "never_executed"}] * 2,
        "read": [{"kind": "read"}],
        "write": [{"kind": "write"}],
        "full_load": [],
    }
    for jit in (False, True):
        for name, hooks in cases.items():
            result.append(
                {
                    "scenario": f"unthrottled_{name}_jit{int(jit)}",
                    "hooks": hooks,
                    "rate": 300,
                    "frames": 600,
                    "workload": name == "full_load",
                    "jit_requested": jit,
                }
            )
    result += [
        {
            "scenario": "floor_1x",
            "hooks": [],
            "rate": 100,
            "frames": 3000,
            "workload": False,
            "jit_requested": False,
        },
        {
            "scenario": "zero_full_1x",
            "hooks": [],
            "rate": 100,
            "frames": 3000,
            "workload": True,
            "jit_requested": False,
        },
    ]
    if phase == "battle":
        result.append(
            {
                "scenario": "one_pending_full_1x",
                "hooks": [{"kind": "exec", "site": "d7_seam"}],
                "rate": 100,
                "frames": 3000,
                "workload": True,
                "jit_requested": False,
                "on_demand": True,
            }
        )
    return result


def site_inventory(title, rom):
    sites = copy.deepcopy(title["sites"])
    diagnostics = title.get("diagnostic_sites", {})
    if isinstance(diagnostics, list):
        diagnostics = {row["symbol"]: row for row in diagnostics}
    for name, site in diagnostics.items():
        sites[name] = copy.deepcopy(site)
        sites[site["symbol"]] = copy.deepcopy(site)
    for name, site in sites.items():
        site["id"] = name
    # Reuse C1-8's independent ROM command-table resolution, including hge cmd9.
    from tests.live import test_gen4_battle_faint as faint

    # C1-8's resolver also reads these images. Share one run-local cached read
    # for resolution and full-pin extraction, then restore its original reader.
    images = cache(faint.rom_images)
    with patch.object(faint, "rom_images", images):
        seam = faint.seam_overrides(title["perf_title"], rom)["ufce"]
        ov12, _ = images(rom)
    raw = ov12.data[seam["addr"] - ov12.ramAddress : seam["addr"] - ov12.ramAddress + 16]
    assert len(raw) == 16 and int.from_bytes(raw[:4], "little") == seam["pin"], (
        "D7 dispatch pin disagreement"
    )
    sites["d7_seam"] = {
        "id": "d7_seam",
        "symbol": seam["name"],
        "address": seam["addr"],
        "image": "ov12",
        "overlay_id": 12,
        "mode": "thumb",
        "phase": "probe",
        "extent": 16,
        "register_hex": raw.hex(),
        "fire_hex": f"{seam['pin']:08x}",
    }
    descriptor = {
        "address": seam["addr"],
        "size": 16,
        "image": "ov12",
        "mode": "thumb",
        "section": ".text",
    }
    return sites, {
        "name": seam["name"],
        "descriptor": descriptor,
        "source": "C1-8 ROM dispatch resolution",
        "command": seam["cmd"],
    }


def committed_surface(title):
    """Freeze the perf evidence surface ONCE, before any trial runs (gen4_evidence.snapshot refuses an
    uncommitted dependency). The row f consumer binds the full kind surface, not this workload list;
    MODULES stays as a subset invariant (OMP cx-ea9abdbc)."""
    surface = gen4_evidence.snapshot("perf", title, repo=REPO)
    missing = sorted(set(MODULES) - set(surface["module_sha256"]))
    assert not missing, f"perf workload module outside the evidence surface: {missing}"
    return surface


def launch_trial(title_name, source, save, state, profile, base, trial, lane, surface, inventory):
    assert not lane.exists(), "stale lane"
    lane.mkdir(parents=True)
    rom = gen4_fixtures.stage_rom(source, lane)
    rom.rename(rom.parent / "perf.nds")
    rom = rom.parent / "perf.nds"
    battery = gen4_fixtures.stage_save(
        save, lane, gates.digest(source, "sha1"), rom_basename=rom.name
    )
    copied_state = lane / "input.State"
    shutil.copyfile(state, copied_state)
    settings = gen4_fixtures.write_nds_run_config(
        base,
        lane / "config.ini",
        initial_time="2010-01-01T12:00:00",
        lane_saveram_dir=battery.parent,
        saveram_name_hint=battery.name,
        pace_1x=trial["rate"] == 100,
    )
    settings["CoreSyncSettings"][gates.CORE]["EnableJIT"] = trial["jit_requested"]
    (lane / "config.ini").write_text(json.dumps(settings), encoding="utf-8")
    title, sites, seam = inventory
    cfg = {
        **trial,
        "schema": "gen4-perf-config-v1",
        "title": title_name,
        "rom_sha1": gates.digest(source, "sha1"),
        "profile": profile.as_posix(),
        "phase": trial["phase"],
        "state_path": copied_state.as_posix(),
        "run_id": lane.parent.name + "/" + lane.name,
        "warmup_frames": 120,
        "sites": sites,
        "seam_symbol": seam,
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "script_sha256": sha(SCRIPT),
        "profile_sha256": sha(profile),
        "module_sha256": surface["module_sha256"],
        "surface_sha256": surface["surface_sha256"],
        "receipt_kind": surface["receipt_kind"],
        "state_sha256": sha(copied_state),
        "config_sha256": sha(lane / "config.ini"),
        "throttle_config": {
            # .get: unpaced (rate 300) trials do not require the pacing keys (OMP cx-6632cac3 F4)
            key: settings.get(key, "<absent>")
            for key in (
                "Unthrottled",
                "ClockThrottle",
                "SpeedPercent",
                "FrameSkip",
                "AutoMinimizeSkipping",
                "VSyncThrottle",
                "SuperHawkThrottle",
            )
        },
    }
    cfg["distinct_addresses"] = len(
        {
            sites[h["site"]]["address"]
            if h["kind"] == "exec"
            else title["symbols"]["gSystem"]["address"]
            + title["profile"]["system"]["vblank_counter_off"]
            for h in trial["hooks"]
            if h.get("site") in sites or h["kind"] != "exec"
        }
    )
    (lane / "perf.json").write_text(json.dumps(cfg), encoding="utf-8")
    shutil.copyfile(SCRIPT, lane / "perf.lua")
    out = lane / "receipt.txt"
    env = dict(
        os.environ,
        SLINK_ROOT=REPO.as_posix(),
        SLINK_GEN4_PERF_CONFIG=(lane / "perf.json").as_posix(),
        SLINK_GEN4_PERF_OUT=out.as_posix(),
    )
    emulator = gates.input_file(
        Path(os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe")), "EmuHawk"
    )
    before = sha(save)
    proc = subprocess.Popen(
        [
            str(emulator),
            f"--config={(lane / 'config.ini').as_posix()}",
            f"--lua={(lane / 'perf.lua').as_posix()}",
            rom.as_posix(),
        ],
        cwd=lane,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    foreign, deadline = set(), time.monotonic() + 360
    try:
        next_check = 0
        while proc.poll() is None and time.monotonic() < deadline:
            if time.monotonic() >= next_check:
                foreign.update(pid for pid in gates.emulator_pids() if pid != proc.pid)
                next_check = time.monotonic() + 5
            if out.is_file() and "\nRESULT:" in out.read_text(encoding="utf-8"):
                break
            time.sleep(0.25)
        assert out.is_file(), f"no perf receipt: {lane}"
        data = read_record(out, title=title_name, rom_sha1=cfg["rom_sha1"], run_id=cfg["run_id"])
        assert data["script_sha256"] == sha(SCRIPT) and data["profile_sha256"] == sha(profile), (
            "moving measurement cut"
        )
        assert data["module_sha256"] == surface["module_sha256"], "workload source changed during measurement"
        assert data["surface_sha256"] == surface["surface_sha256"], "PERF sample lost its evidence surface"
        assert data["receipt_kind"] == "perf", "PERF sample carries the wrong receipt kind"
        data["foreign_pids"] = sorted(foreign)
        data["concurrent_load"] = bool(foreign)
        data["pid"] = proc.pid
        data["session_id"] = lane.parent.name
        if data["result"] == "PASS":
            data["native_stats"] = native_statistics(data["frame_times"])
        (lane / "verified.json").write_text(json.dumps(data), encoding="utf-8")
        proc.wait(timeout=10)
        return data
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        assert sha(save) == before, "input save changed"


def assemble_f(records, title, rom_sha1):
    chosen = {}
    for phase, scenario, slot in (
        ("battle", "zero_full_1x", "zero"),
        ("battle", "one_pending_full_1x", "one"),
        ("overworld", "zero_full_1x", "overworld_zero"),
    ):
        rows = [r for r in records if r["phase"] == phase and r["scenario"] == scenario]
        if len(rows) != 1 or rows[0]["result"] != "PASS":
            return None, f"required sustained record absent/OPEN: {phase}/{scenario}"
        row = rows[0]
        assert row["title"] == title and row["rom_sha1"] == rom_sha1, "wrong sustained artifact"
        if row["concurrent_load"]:
            return None, f"concurrent load in {phase}/{scenario}: {row['foreign_pids']}"
        chosen[slot] = row
        row["frames"] = row["frames_requested"]
        floors = [r for r in records if r["phase"] == phase and r["scenario"] == "floor_1x" and r["result"] == "PASS"]
        if len(floors) != 1 or floors[0]["concurrent_load"]:
            return None, f"same-session bare floor absent/concurrent: {phase}"
        row["floor"] = floors[0]
    return {"sustained": chosen}, None


@pytest.fixture
def perf_api():
    from lupa import LuaRuntime

    r = LuaRuntime(unpack_returned_tuples=True)
    r.globals().SLINK_GEN4_PERF_TEST = True
    return r, r.execute(SCRIPT.read_text(encoding="utf-8"))


def test_stats_single_slow_frame_not_hidden_by_average(perf_api):
    r, api = perf_api
    values = [1 / 60] * 3000
    values[-1] = 0.02
    actual = gates.from_lua(api.stats(gates.to_lua(r, values)))
    expected = statistics_of(values)
    assert actual == pytest.approx(expected) and expected["over_budget"] == 1
    assert expected["p99"] == 1 / 60 and expected["max"] == 0.02


def test_sampler_wall_intervals_include_work(perf_api):
    r, api = perf_api
    r.execute(
        "T=0; clock=function() return T end; work=function() T=T+.002 end; advance=function() T=T+.014 end"
    )
    times, work = api.sample(r.globals().clock, r.globals().advance, r.globals().work, 3)
    assert list(times.values()) == pytest.approx([0.016] * 3)
    assert list(work.values()) == pytest.approx([0.002] * 3)


def test_matrix_has_required_comparisons():
    matrix = trial_matrix("battle")
    assert len(matrix) == 19
    assert {
        row["jit_requested"] for row in matrix if row["scenario"].startswith("unthrottled_none")
    } == {True, False}
    assert any(row["scenario"].startswith("unthrottled_exec_two_addresses") for row in matrix)
    assert any(row["scenario"].startswith("unthrottled_exec_same_address_twice") for row in matrix)
    assert len([r for r in matrix if r["rate"] == 100 and r["workload"]]) == 2
    assert not any(r.get("on_demand") for r in trial_matrix("overworld"))


@pytest.mark.parametrize("suffix", ["SAVE", "BATTLE_STATE", "OVERWORLD_STATE"])
def test_required_native_inputs_absent_open_present_checked(monkeypatch, tmp_path, suffix):
    key = f"SLINK_GEN4_HEARTGOLD_{suffix}"
    monkeypatch.delenv(key, raising=False)
    with pytest.raises(pytest.skip.Exception, match=key):
        required_input("heartgold", suffix, "perf input")
    path = tmp_path / suffix
    monkeypatch.setenv(key, str(path))
    with pytest.raises(pytest.skip.Exception, match="absent input"):
        required_input("heartgold", suffix, "perf input")
    path.write_bytes(b"supplied")
    assert required_input("heartgold", suffix, "perf input") == path


def test_rom_images_cached_within_run_restored_and_refreshed_next_run(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tests.live import test_gen4_battle_faint as faint

    calls = []

    def images(path):
        calls.append(path)
        raw = bytes([len(calls)]) * 16
        return SimpleNamespace(ramAddress=0x1000, data=raw), None

    def seams(title, path):
        overlay, _ = faint.rom_images(path)
        return {"ufce": {"addr": 0x1000, "pin": int.from_bytes(overlay.data[:4], "little"),
                         "cmd": 11, "name": "MODEL seam"}}

    monkeypatch.setattr(faint, "rom_images", images)
    monkeypatch.setattr(faint, "seam_overrides", seams)
    title = {"sites": {}, "perf_title": "heartgold"}
    first, _ = site_inventory(title, tmp_path / "rom.nds")
    assert len(calls) == 1 and faint.rom_images is images
    second, _ = site_inventory(title, tmp_path / "rom.nds")
    assert len(calls) == 2 and faint.rom_images is images
    assert first["d7_seam"]["register_hex"] != second["d7_seam"]["register_hex"]


def test_clock_rejects_coarse_and_backward(perf_api):
    r, api = perf_api
    r.execute("T=0; fine=function() T=T+.000001; return T end")
    assert api.calibrate(r.globals().fine)["minimum_positive_increment"] <= 0.0001
    r.execute("T=0; coarse=function() T=T+.001; return T end")
    # OPEN is represented by an error table, never silently os.clock fallback.
    ok, reason = r.eval("function(f,c) local ok,e=pcall(f,c); return ok,e end")(
        api.calibrate, r.globals().coarse
    )
    assert not ok and "resolution" in reason["open"]
    r.execute("T=1; backward=function() T=T-.001; return T end")
    with pytest.raises(Exception, match="clock moved backward"):
        api.calibrate(r.globals().backward)


def test_workload_calls_real_module_surface_and_counts(perf_api):
    r, api = perf_api
    r.execute("""
        reads={save_data=function() return 100 end,
            party=function() return {{key="PID:OTID",hp=20,level=5,moves={1,2,3,4}}} end,
            battle=function() return {mons={{hp=20},{hp=13}}} end}
        safety={new=function() return {checkpoint=function() return false,"task_running" end} end}
        json={encode=function() return string.rep("x",500) end}
    """)
    work, counts, audit = api.workload(
        r.globals().reads,
        r.table(),
        r.globals().safety,
        r.globals().json,
        gates.to_lua(r, {"perf_title": "MODEL", "rom": {"sha1": "x"}}),
        r.table(),
        "battle",
    )
    for _ in range(3):
        work()
    assert (
        counts["pointer_chain"]
        == counts["party_diff"]
        == counts["json_encode"]
        == counts["safety"]
        == 3
    )
    assert counts["battle_mons_hp"] == 6 and audit()["hello_bytes"] == 500
    r.execute("reads.party=function() return nil,'checksum' end")
    with pytest.raises(Exception, match="checksum"):
        work()


def perf_example():
    times = [1 / 60] * 3000
    return {
        "schema": "gen4-perf-v1",
        "producer": "gen4-PERF",
        "level": "PHYSICAL",
        "result": "PASS",
        "title": "heartgold",
        "rom_sha1": "a" * 40,
        "run_id": "current",
        "frames_requested": 3000,
        "frame_times": times,
        "stats": statistics_of(times),
        "ending_registered": 0,
        "clock_calibration": {"backward_steps": 0, "minimum_positive_increment": 0.000001},
    }


@pytest.mark.parametrize(
    "fault", ["wrong_rom", "stale", "model", "forged_p99", "missing_frame", "retained_hook"]
)
def test_perf_receipt_red_and_revert(tmp_path, fault):
    path = tmp_path / "receipt.txt"
    original = perf_example()

    def write(record):
        path.write_text("PERF PASS " + json.dumps(record) + "\nRESULT: PASS\n")

    write(original)
    assert (
        read_record(path, title="heartgold", rom_sha1="a" * 40, run_id="current")["result"]
        == "PASS"
    )
    bad = copy.deepcopy(original)
    if fault == "wrong_rom":
        bad["rom_sha1"] = "b" * 40
    elif fault == "stale":
        bad["run_id"] = "old"
    elif fault == "model":
        bad["level"] = "MODEL"
    elif fault == "forged_p99":
        bad["stats"]["p99"] = 0.01
    elif fault == "missing_frame":
        bad["frame_times"].pop()
    else:
        bad["ending_registered"] = 1
    write(bad)
    with pytest.raises(AssertionError):
        read_record(path, title="heartgold", rom_sha1="a" * 40, run_id="current")
    write(original)
    assert (
        read_record(path, title="heartgold", rom_sha1="a" * 40, run_id="current")["result"]
        == "PASS"
    )


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("SLINK_LIVE") != "1",
    reason="gen4-PERF needs explicit emulator lane and SLINK_LIVE=1",
)
@pytest.mark.parametrize("title", ["heartgold", "heartgold_hge"])
def test_live_perf(title):
    source = gates.input_file(
        Path(
            os.environ.get(
                f"SLINK_GEN4_{title.upper()}_ROM", gen4_pins.default_locations().roms[title]
            )
        ),
        "perf ROM",
    )
    save = required_input(title, "SAVE", "perf native save")
    assert gates.save_setup(save)["setup"] == "NATIVE", "PERF uses naturally played native inputs"
    profile = gates.input_file(
        REPO / "data/games" / gates.TITLE_PACK[title] / "profile.json", "perf profile"
    )
    base = gates.input_file(
        Path(os.environ.get("SLINK_BIZHAWK_CONFIG", "E:/Howard/Bizhawk/config.ini")), "base config"
    )
    surface = committed_surface(title)
    packed_title = json.loads(profile.read_text(encoding="utf-8"))["titles"][title]
    packed_title["perf_title"] = title
    sites, seam = site_inventory(packed_title, source)
    inventory = packed_title, sites, seam
    root = Path(os.environ.get("SLINK_GEN4_PERF_RUNS", "C:/slink/g4/perf")) / (
        title + "-" + uuid.uuid4().hex[:12]
    )
    records = []
    for phase in ("overworld", "battle"):
        if os.environ.get("SLINK_GEN4_PERF_PHASE") and phase != os.environ["SLINK_GEN4_PERF_PHASE"]:
            continue
        state = required_input(title, f"{phase.upper()}_STATE", "perf state")
        for trial in trial_matrix(phase):
            if os.environ.get("SLINK_GEN4_PERF_JIT_ONLY") == "1" and not trial["jit_requested"]:
                continue
            if os.environ.get("SLINK_GEN4_PERF_SKIP_JIT") == "1" and trial["jit_requested"]:
                continue
            if os.environ.get("SLINK_GEN4_PERF_SUSTAINED_ONLY") == "1" and trial["rate"] != 100:
                continue
            if (
                os.environ.get("SLINK_GEN4_PERF_ONLY")
                and trial["scenario"] != os.environ["SLINK_GEN4_PERF_ONLY"]
            ):
                continue
            trial = {
                **trial,
                "phase": phase,
                "cold_boot": os.environ.get("SLINK_GEN4_PERF_COLD_BOOT") == "1",
            }
            if trial["jit_requested"]:
                if phase == "overworld":
                    trial["cold_boot"] = True
                else:
                    records.append(
                        {
                            "phase": phase,
                            "scenario": trial["scenario"],
                            "result": "OPEN",
                            "title": title,
                            "rom_sha1": gates.digest(source, "sha1"),
                            "reason": "JIT-enabled battle state not matched; interpreter-state trial produced no receipt",
                        }
                    )
                    continue
            records.append(
                launch_trial(
                    title,
                    source,
                    save,
                    state,
                    profile,
                    base,
                    trial,
                    root / (phase + "_" + trial["scenario"]),
                    surface,
                    inventory,
                )
            )
            if "clock" in (records[-1].get("reason") or "").lower():
                (root / "blocked_clock.json").write_text(json.dumps(records[-1]), encoding="utf-8")
                pytest.skip(f"OPEN clock prerequisite; no unchanged follow-up trial: {root}")
    observation, why = assemble_f(records, title, gates.digest(source, "sha1"))
    summary = {
        "schema": "gen4-perf-bundle-v1",
        "producer": "gen4-PERF",
        "level": "PHYSICAL",
        "title": title,
        "rom_sha1": gates.digest(source, "sha1"),
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "observation": observation,
        "reason": why,
        "records": records,
    }
    (root / "bundle.json").write_text(json.dumps(summary), encoding="utf-8")
    print(f"PERF receipts: {root}")
    if observation is None:
        pytest.skip(f"OPEN sustained performance: {why}; {root}")
    # Reuse exactly the f authority, never a separate relaxed FPS threshold.
    from lupa import LuaRuntime

    r = LuaRuntime(unpack_returned_tuples=True)
    r.globals().SLINK_GEN4_PROBE_TEST = True
    api = r.execute(gates.SCRIPT.read_text(encoding="utf-8"))
    outcome = api.evaluate("f", gates.to_lua(r, observation))
    status, reason = outcome if isinstance(outcome, tuple) else (outcome, None)
    assert status == "PASS", f"f {status}: {reason}; floor distributions retained in {root}"
