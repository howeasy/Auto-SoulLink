"""Opt-in PHYSICAL Gen 2 panel palette diagnosis; never builds or writes palette RAM.

Creates one detached, private-cache lane, copies the leased instrumented gate and runner,
then boots the qualified overlay fixture with disclosed saved-clock staging.
The resulting PALETTE_PROBE rows retain full buffers and native PC/frame write evidence.
No diagnostic run installs release receipts. --sweep runs the ordinary final-sweep cells
in the explicitly leased lane root, rather than the shared gen2/fsN lanes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = "lua/tests/gen2_panel_gate.lua"
NATIVE = (
    "FinishExitMenu", "ReloadTilesetAndPalettes", "StartMenu.ReturnRedraw",
    "StartMenu.ReturnEnd2", "StartMenu.Reopen", "_TimeOfDayPals", "_UpdateTimePals",
    "UpdateTimeOfDayPal", "FillWhiteBGColor",
)
CLOCK = ("wTimeOfDay", "wCurTimeOfDay", "wTimeOfDayPal", "wTimeOfDayPalFlags",
         "hHours", "hMinutes", "hSeconds", "hCGBPalUpdate", "hInMenu", "hMenuReturn")

def worker(root: Path, out: Path, title: str, cycles: int, phase: int,
           elapsed: int | None, normalize: bool) -> int:
    sys.path[:0] = [str(root / "tools"), str(root)]
    import run_gb_gate

    from tests.live import test_gen2_new_gates as live, test_gen2_panel_gate as gate
    from tools import gen2_fixtures

    facts = gate.panel_facts(title, repo=root, sites=(*gate.SITES, *NATIVE), ram=(*gate.RAM, *CLOCK))
    symbols = {
        name: (int(bank, 16), int(addr, 16))
        for bank, addr, name in re.findall(
            r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)$",
            (root / f"data/gen2/{title}_slink.sym").read_text(), re.M,
        )
    }
    context = gate.gen2_source_data.load_context(title, root=root)
    provenance = json.loads((root / gate.PROVENANCE).read_text())
    output = provenance["outputs"][context.artifact]
    image = gate.ups_apply(context.rom, (root / output["ups"]["file"]).read_bytes())
    returns = {}
    for name, next_symbol in (
        ("Probe.FinishExitMenu.ret", "ReturnToMapWithSpeechTextbox"),
        ("Probe.FadeInFromWhite.ret", "FadeOutToWhite"),
        ("Probe.StartMenu.ReturnEnd2.ret", "StartMenu.GetInput"),
    ):
        bank, end = symbols[next_symbol]
        address = end - 1
        flat = address if bank == 0 else bank * 0x4000 + address - 0x4000
        assert image[flat] == 0xC9, f"{name}: native terminal instruction is not RET"
        facts["sites"][name] = {"symbol": name, "bank": bank, "addr": address,
                                "flat": flat, "hex": image[flat:flat + 3].hex()}
        returns[name] = True
    facts["probe"] = {
        "schema": "gen2-panel-palette-probe-v1", "phase": phase, "phase_mod": 64,
        "completion_sites": [*NATIVE, *returns], "returns": returns,
        "ram": {name: facts["ram"][name] for name in CLOCK},
        "rtc": {"RealTimeRTC": False, "InitialTime": 0,
                "SYNTH_saved_elapsed_seconds": elapsed, "normalize_base_time": normalize,
                "disclosure": "Only staged RTC trailer changed; all CartRAM bytes and immutable fixture retained"},
        "harness_writes": [],
    }
    spec = gen2_fixtures.BY_NAME[f"{title}_battle"]
    fixture = root / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
    staged = fixture.read_bytes()
    live.qualified_identity(spec.name, staged, repo=root, kind="overlay")
    qualification = json.loads(live.receipt_file(f"{spec.name}.qualification.json", "overlay", repo=root).read_text())
    env = live.inspect_env(spec, staged, repo=root, kind="overlay")
    env.update(SLINK_GEN2_PANEL_FACTS=json.dumps(facts),
               SLINK_GEN2_QUALIFICATION_ATTEMPT=qualification["attempt_id"],
               SLINK_GEN2_PANEL_PROBE="1", SLINK_GEN2_PANEL_PROBE_CYCLES=str(cycles))
    # StoreSaveRam ignores InitialTime in non-movie runs. Normalize only the staged emulator trailer.
    # Pinned native authority: gambatte-core d49b895 cartridge.cpp:547-588 (future timestamp clamp).
    original_plan = run_gb_gate.GENS["gen2"]["plan"]
    clock_info = {}
    original_stagers = run_gb_gate.GENS["gen2"]["fixture_stagers"]
    if not normalize:
        # Deliberately disable only this lane-local staging rule for the red control.
        run_gb_gate.GENS["gen2"]["fixture_stagers"] = {}

    def clock_plan(*args, **kwargs):
        plan = original_plan(*args, **kwargs)
        clocked = staged
        if elapsed is not None:
            base_time = int(time.time()) - elapsed
            clocked = staged[:0x8000] + base_time.to_bytes(8, "big") + staged[0x8008:]
        assert clocked[:0x8000] == staged[:0x8000], "CartRAM changed"
        clock_input = root / ".cache/gen2-fixtures/palette-probe/clock-input.SaveRAM"
        clock_input.parent.mkdir(parents=True, exist_ok=True)
        clock_input.write_bytes(clocked)
        plan["fixture"] = clock_input
        clock_info.update(original_tail=staged[-22:].hex(), staged_tail=clocked[-22:].hex(),
                          staged_sha256=hashlib.sha256(clocked).hexdigest(), cart_ram_equal=True)
        assert clocked[0x8008:] == staged[0x8008:], "saved RTC registers changed"
        return plan

    run_gb_gate.GENS["gen2"]["plan"] = clock_plan
    try:
        passed, path, text = run_gb_gate.run_gate(
            GATE, rom_key=f"{title}_overlay", target=spec.target, timeout=3600,
            saveram_dir=str(root / ".cache/gen2-fixtures/palette-probe" / spec.name),
            fixture_path=str(fixture), speed_percent=300, env_overrides=env,
        )
    finally:
        run_gb_gate.GENS["gen2"]["plan"] = original_plan
        run_gb_gate.GENS["gen2"]["fixture_stagers"] = original_stagers
    assert clock_info, "clock staging hook did not run"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.txt").write_text(text, encoding="utf-8", newline="\n")
    config = json.loads((root / f"patch/build/gate_cfg_gen2_panel_gate_{title}_overlay.ini").read_text())
    sync = config["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]
    assert sync["RealTimeRTC"] is False and sync["InitialTime"] == 0
    assert fixture.read_bytes() == staged, "immutable fixture changed"
    records = [json.loads(line.removeprefix("PALETTE_PROBE "))
               for line in text.splitlines() if line.startswith("PALETTE_PROBE ")]
    (out / "probe.json").write_text(json.dumps(records, indent=1) + "\n", encoding="utf-8", newline="\n")
    info = {"passed": passed, "result": str(path), "title": title, "phase": phase,
            "cycles": cycles, "rtc": sync, "fixture_sha256": hashlib.sha256(staged).hexdigest(),
            "facts": facts, "clock_staging": clock_info, "records": len(records)}
    (out / "run.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8", newline="\n")
    for record in records:
        print(record["label"], "restored=", record["restored"], "overworld=", record["to_overworld"],
              "phase=", record["phase"], "writes=", len(record["writes"]), "samples=", len(record["samples"]))
    print("PASS" if passed else "FAIL", out, flush=True)
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True, help="exclusive lane ROOT (one fs1 child)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--title", choices=("crystal", "gold", "silver"), default="crystal")
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--phase", type=int, choices=range(64), default=0)
    parser.add_argument("--load-elapsed-seconds", type=int, help="SYNTH host elapsed-time input; preserves all saved RTC registers")
    parser.add_argument("--no-normalize", action="store_true", help="lane-local red control: disable only panel base-time staging")
    parser.add_argument("--sha", default="HEAD")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--sweep", action="store_true", help="ordinary panel cell, no instrumentation")
    args = parser.parse_args()
    if args.load_elapsed_seconds is not None and not 0 <= args.load_elapsed_seconds <= 172800:
        parser.error("--load-elapsed-seconds must be in 0..172800")
    if args.worker:
        return worker(args.worker, args.out, args.title, args.cycles, args.phase,
                      args.load_elapsed_seconds, not args.no_normalize)
    sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
    from tools import gen2_final_sweep as sweep

    sweep.LANE_ROOT = args.lane
    if args.sweep:
        return sweep.main(["--lanes", "1", "--sha", args.sha, "--out", str(args.out),
                           "--only", f"gate/panel/{args.title}"])
    lane = sweep.make_lane(1, args.sha)
    shutil.copyfile(ROOT / GATE, lane / GATE)
    shutil.copyfile(ROOT / "tools/run_gb_gate.py", lane / "tools/run_gb_gate.py")
    args.out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTEST_ADDOPTS", None)
    try:
        with (args.out / "driver.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(lane),
                 "--lane", str(args.lane), "--out", str(args.out), "--title", args.title,
                 "--cycles", str(args.cycles), "--phase", str(args.phase),
                 *([] if args.load_elapsed_seconds is None else ["--load-elapsed-seconds", str(args.load_elapsed_seconds)]),
                 *(["--no-normalize"] if args.no_normalize else [])],
                cwd=lane, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=3900,
            )
        print((args.out / "driver.log").read_text(), flush=True)
        return result.returncode
    finally:
        # Private copied build/fixture trees only; sweep unlinks its three junctions before removal.
        sweep.drop_lane(lane)


if __name__ == "__main__":
    raise SystemExit(main())
