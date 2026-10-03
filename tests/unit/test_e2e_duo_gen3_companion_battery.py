"""R2: a companion (patched) FR/LG/Emerald cartridge is filed by BizHawk under its FILENAME-derived SaveRAM name, not the gamedb
name of the clean dump. The battery path follows the resolved ROM, and a stale seed can never stand in for the emulator's save.
No emulator is started: the 'emulator write' is a file the test creates after the recorded launch time."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import e2e_duo as duo  # noqa: E402
from tools import gen3_final_cut  # noqa: E402

CLEAN, COMPANION = b"clean-dump" * 8, b"patched-companion" * 8
SEED = b"SEED-under-the-clean-gamedb-name"


def _run(tmp_path, monkeypatch, title, rom_bytes, rom_name):
    rom = tmp_path / rom_name
    rom.write_bytes(rom_bytes)
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg = dict(duo.GAMES["gen3_frlg"]), dict(duo.SCENARIOS["faint_cmd_gen3"])
    run._saveram_dir = lambda inst: str(tmp_path / "sav")
    (tmp_path / "sav").mkdir(exist_ok=True)
    monkeypatch.setattr(run, "_gen3_title", lambda inst: title)
    monkeypatch.setattr(run, "_gen3_rom", lambda inst: str(rom))
    monkeypatch.setattr(gen3_final_cut, "rom_pins", lambda tree, **kw: {title: hashlib.sha1(CLEAN).hexdigest()})
    run._launch_times = {"a": 1000.0}
    return run


@pytest.mark.parametrize("title,label", [("firered", "FireRed"), ("leafgreen", "LeafGreen"), ("emerald", "Emerald")])
def test_a_companion_cartridge_gets_the_filename_derived_battery_a_clean_one_the_gamedb_name(tmp_path, monkeypatch, title, label):
    run = _run(tmp_path, monkeypatch, title, COMPANION, f"slink_{label}.gba")
    assert os.path.basename(run._gen3_battery_path("a")) == f"slink {label}.SaveRAM"          # positive: companion
    (tmp_path / "c").mkdir()
    clean = _run(tmp_path / "c", monkeypatch, title, CLEAN, "gen3_dump.gba")
    assert os.path.basename(clean._gen3_battery_path("a")) == duo.GEN3_TITLES[title]["saveram"]  # negative control: clean kept


def test_a_stale_seed_is_never_the_companion_oracle_input(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, "firered", COMPANION, "slink_FireRed.gba")
    sav = tmp_path / "sav"
    clean_seed = sav / duo.GEN3_TITLES["firered"]["saveram"]          # the OLD (wrong) name a pre-fix run seeded
    clean_seed.write_bytes(SEED)
    seed = Path(run._gen3_battery_path("a"))
    seed.write_bytes(b"DERIVED-seed")
    for p in (clean_seed, seed):
        os.utime(p, (900, 900))                                       # written before the launch
    with pytest.raises(RuntimeError, match="no fresh flushed battery"):
        run._gen3_flushed("a")                                        # only seeds exist: loud, not an oracle input
    clean_seed.unlink()
    other = sav / "somewhere else.SaveRAM"                            # the emulator filed its save under another name
    other.write_bytes(b"EMULATOR")
    os.utime(other, (1001, 1001))
    with pytest.raises(RuntimeError, match="no fresh flushed battery"):
        run._gen3_flushed("a")                                        # no 'any other *.SaveRAM' fallback for a companion
    seed.write_bytes(b"EMULATOR-WROTE-THE-DERIVED-NAME")
    os.utime(seed, (1001, 1001))
    assert run._gen3_flushed("a") == b"EMULATOR-WROTE-THE-DERIVED-NAME"      # known positive


def test_a_clean_cartridge_keeps_the_gamedb_name_and_the_old_flush_rule(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, "firered", CLEAN, "gen3_dump.gba")
    seeded = Path(run._gen3_battery_path("a"))
    seeded.write_bytes(b"flushed-by-emuhawk")
    os.utime(seeded, (900, 900))
    assert run._gen3_flushed("a") == b"flushed-by-emuhawk"            # unchanged: no freshness requirement on clean rows
