"""P1 capability receipts only; no savestate, server or production client.

Run serially on the coordinator's emulator lane. A PASS certifies the required
probe rows, not a safe write checkpoint or the informational instruction budget.
"""
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import run_gate as gate_runner  # noqa: E402

SCRIPT = "lua/tests/probe_gen3_hooks.lua"
REQUIRED = {"a", "b-base", "d", "e", "g"}
ROW = re.compile(r"^PROBE (\S+) (PASS|FAIL|OPEN)(?: |$)")
ROMS = [
    ("rr", REPO / "patch/build/slink_RR.gba", "radical_red"),
    ("fr", Path("E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba"), "vanilla"),
    ("emerald", Path("E:/Google Drive/SLink/Pokemon - Emerald Version (USA, Europe).gba"), "emerald"),
]
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="P1 hook probes require SLINK_LIVE=1 (spawns EmuHawk)"),
]


@pytest.mark.parametrize("name,source,variant", ROMS, ids=["rr", "fr", "emerald"])
def test_gen3_hook_probe(name, source, variant, monkeypatch):
    for prerequisite in (Path(gate_runner.EMUHAWK), Path(gate_runner.BIZHAWK_CONFIG), source):
        if not prerequisite.is_file():
            pytest.skip(f"probe prerequisite missing: {prerequisite}")
    build = REPO / "patch/build"
    build.mkdir(parents=True, exist_ok=True)
    # run_gate's EmuHawk argv needs a space-free repo-relative ROM path.
    rom = "patch/build/slink_RR.gba"
    if name in ("fr", "emerald"):
        rom = f"patch/build/probe_gen3_{name}.gba"
        shutil.copyfile(source, REPO / rom)
    if name == "emerald":
        # BizHawk's gamedb knows this dump: redirect its battery to a per-run dir instead of the
        # developer's GBA SaveRAM folder (tools/gen3_fixtures.py RUN_DIR; SLINK_GEN3_FIXTURE_RUNS).
        import gen3_fixtures
        run_dir = gen3_fixtures.RUN_DIR / "probe_hooks_emerald"
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        cfg = run_dir / "config.ini"
        gen3_fixtures.write_gba_run_config(gate_runner.BIZHAWK_CONFIG, str(cfg), str(run_dir))
        monkeypatch.setattr(gate_runner, "BIZHAWK_CONFIG", str(cfg))
    monkeypatch.setenv("SLINK_PROBE_VARIANT", variant)
    archive = build / f"probe_gen3_hooks_{name}.txt"
    archive.unlink(missing_ok=True)
    passed, result_path, text = gate_runner.run_gate(SCRIPT, rom=rom, timeout=300, quiet=True)
    archive.write_text(text, encoding="utf-8")  # preserve failed/OPEN evidence too
    assert result_path is not None, f"no probe receipt; archived at {archive}"
    lines = text.splitlines()
    assert passed and lines and lines[-1] == "RESULT: PASS", text[-6000:]
    rows = {}
    for line in lines:
        match = ROW.match(line)
        if match:
            row, status = match.groups()
            assert row not in rows, f"duplicate receipt row: {row}"
            rows[row] = status
    assert rows.keys() >= REQUIRED, f"missing required rows: {REQUIRED - rows.keys()}"
    assert all(rows[row] == "PASS" for row in REQUIRED), rows
    assert {"a-return", "b-interior", "c", "f"} <= rows.keys(), rows
    assert f"BIND variant={variant} " in text, "wrong profile receipt"
    assert "COUNTERS callback_errors=0 dropped=0" in lines, "incomplete callback evidence"
