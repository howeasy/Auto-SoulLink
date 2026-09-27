"""P1 capability receipts only; no savestate, server or production client.

Run serially on the coordinator's emulator lane. A PASS certifies the required
probe rows, not a safe write checkpoint or the informational instruction budget.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import run_gate as gate_runner  # noqa: E402

from tests.unit.test_gen3_write_checkpoint import census_rows  # noqa: E402

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
    if name == "fr":
        rom = f"patch/build/probe_gen3_{name}.gba"
        shutil.copyfile(source, REPO / rom)
    if name == "emerald":
        # BizHawk's gamedb knows this dump: redirect its battery to a per-run dir instead of the
        # developer's GBA SaveRAM folder (tools/gen3_fixtures.py RUN_DIR; SLINK_GEN3_FIXTURE_RUNS).
        # MINOR 9: reuse _prepare_run's rmtree/mkdir (handles Drive read-only dirs,
        # reference_worktree_readonly_attr) and its own ROM staging, instead of a hand-rolled
        # rmtree plus a second manual copy; seed=None cold-boots (no battery seeded), so the run
        # dir must be empty right after this call.
        import gen3_fixtures
        rom, run_dir, _battery = gen3_fixtures._prepare_run(
            "probe_hooks_emerald", str(source), seed=None, saveram_name_override=None)
        assert not any(run_dir.iterdir()), f"run dir not empty before launch: {run_dir}"
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


# ── E2-CENSUS-2 (cx-cb4fb1b8 MAJOR 2): the frame-end census's overworld-idle verdict needs a
# live row of its own, gated the same way as the hook probes above. ──────────────────────────
CENSUS_SCRIPT = "lua/tests/probe_gen3_frameend_census.lua"
EMERALD_ROM = next(source for _name, source, variant in ROMS if variant == "emerald")
EMERALD_FIXTURE = REPO / "tests/fixtures/gen3/emerald_town.sav"
EMERALD_CHECKPOINT = REPO / "data/games/gen3_emerald/write_checkpoint.json"


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                    reason="the census probe requires SLINK_LIVE=1 (spawns EmuHawk)")
def test_gen3_emerald_frameend_census(monkeypatch):
    """Confirms the checkpoint-clean arming and the pack-driven task geometry
    (probe_gen3_frameend_census.lua) against a real Emerald boot: the modal non-IRQ frame-end PC
    must be the pack's cpu.observed_pc, and idle frames must clear the 90% bar."""
    for prerequisite in (Path(gate_runner.EMUHAWK), Path(gate_runner.BIZHAWK_CONFIG),
                        EMERALD_ROM, EMERALD_FIXTURE):
        if not prerequisite.is_file():
            pytest.skip(f"census prerequisite missing: {prerequisite}")
    import gen3_fixtures
    rom_rel, run_dir, _battery = gen3_fixtures._prepare_run(
        "census_emerald", str(EMERALD_ROM), seed=EMERALD_FIXTURE.read_bytes(),
        saveram_name_override=None)
    passed, text = gen3_fixtures._launch(
        CENSUS_SCRIPT, rom_rel, run_dir, rr=False, timeout=300, title="emerald",
        extra_env={"SLINK_GEN3_CHECKPOINT": str(EMERALD_CHECKPOINT)})
    build = REPO / "patch/build"
    build.mkdir(parents=True, exist_ok=True)
    archive = build / "probe_gen3_frameend_census_emerald.txt"
    archive.write_text(text, encoding="utf-8")
    assert passed, text[-6000:]
    lines = text.splitlines()
    assert lines, "no census receipt"
    result_line = lines[-1]
    assert result_line.startswith("RESULT: PASS"), text[-4000:]
    match = re.search(r"overworld-idle=(\d+)/(\d+)", result_line)
    assert match, result_line
    idle, total = int(match[1]), int(match[2])
    assert total > 0 and idle >= 0.9 * total, f"idle {idle}/{total} below the 90% bar"

    cpu = json.loads(EMERALD_CHECKPOINT.read_text(encoding="utf-8"))["emerald"]["cpu"]
    rows = census_rows(str(archive.relative_to(REPO)))
    rom_pcs = {pc: c for pc, c in rows.items() if pc >= 0x08000000}
    assert rom_pcs, "no ROM-resident R15 sample in the final census summary"
    modal_pc = max(rom_pcs, key=rom_pcs.get)
    assert modal_pc == cpu["observed_pc"], (
        f"modal non-IRQ PC {modal_pc:#010x} != pack cpu.observed_pc {cpu['observed_pc']:#010x}")
