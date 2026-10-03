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


# ── F5: a NO-WRITE half may leave its battery as the harness seeded it ───────────────────────────────────
# reconnect_gen3 (A) and active_end_gen3 (B) expect the cartridge NOT to rewrite its battery, so an untouched
# seed (mtime before the launch) is their legitimate input; every half that must save still needs a fresh file.
# Found by scenario config (`no_save`), pinned by name below: a new no-write row must be decided here. Each half also records WHAT
# proves "nothing wrote": its oracle reads the battery and compares bytes (SEED_BYTES), or no oracle reads it and the declared-no_save
# gate in check_save_witness_gen3 (a no_save half that dumped a save FAILS) is the whole proof (NO_SAVE_GATE).
SEED_BYTES, NO_SAVE_GATE = "seed-bytes compared by the oracle", "declared-no_save gate in check_save_witness_gen3"
NO_WRITE_COMPANION_ROWS = {
    ("active_end_gen3", "fr", "b"): SEED_BYTES, ("active_end_gen3", "lg", "b"): SEED_BYTES,
    ("center_controls_gen3", "fr", "b"): NO_SAVE_GATE, ("center_controls_gen3", "lg", "b"): NO_SAVE_GATE,
    ("reconnect_gen3", "fr", "a"): SEED_BYTES, ("reconnect_gen3", "em", "a"): SEED_BYTES,
    ("save_then_write_gen3", "fr", "b"): NO_SAVE_GATE, ("save_then_write_gen3", "lg", "b"): NO_SAVE_GATE,
}


def test_the_frlgc_plans_no_write_halves_are_exactly_the_decided_set():
    import re

    found = set()
    for row in gen3_final_cut.build_plan_frlgc("c" * 40, "L:/lane", "L:/master"):
        m = re.fullmatch(r"frlgc_(.+)_(fr|lg|em)_as_a_companion", row.id)
        if m and duo.SCENARIOS[m[1]].get("no_save"):
            found |= {(m[1], m[2], side) for side in duo.SCENARIOS[m[1]]["no_save"]}
    assert found == set(NO_WRITE_COMPANION_ROWS), (
        "a frlgc row gained or lost a no_save half: decide whether _gen3_flushed's no-write exemption applies "
        f"(new {sorted(found - set(NO_WRITE_COMPANION_ROWS))}, gone {sorted(set(NO_WRITE_COMPANION_ROWS) - found)})")


def test_each_no_write_half_records_the_proof_that_really_backs_it():
    """The recorded proof kind is checked against the code: a SEED_BYTES half's oracle reads that side's battery; a NO_SAVE_GATE half
    is read by NO oracle, so the declared-no_save gate is all there is (and it must still refuse a no_save half that dumped)."""
    import inspect

    for (scenario, _orient, side), proof in NO_WRITE_COMPANION_ROWS.items():
        oracle = inspect.getsource(getattr(duo.DuoRun, duo.SCENARIOS[scenario]["oracle"]))
        reads = f'_gen3_flushed("{side}")' in oracle or f'_gen3_saved("{side}")' in oracle
        if proof == SEED_BYTES:
            assert reads, (scenario, side, "recorded as byte-compared but its oracle never reads that battery")
        else:
            assert proof == NO_SAVE_GATE and not reads, (scenario, side, "recorded as gate-only but its oracle reads it")
    gate = inspect.getsource(duo.DuoRun.check_save_witness_gen3)
    assert "declared no_save, but its final receipt dumped" in gate


@pytest.mark.parametrize("scenario, side", [("reconnect_gen3", "a"), ("active_end_gen3", "b")])
def test_a_no_write_half_accepts_its_untouched_seed_but_a_saving_half_never_does(tmp_path, monkeypatch, scenario, side):
    run = _run(tmp_path, monkeypatch, "firered", COMPANION, "slink_FireRed.gba")
    run.cfg = dict(duo.SCENARIOS[scenario])
    other = "b" if side == "a" else "a"
    run._launch_times = {"a": 1000.0, "b": 1000.0}
    run._gen3_battery_path = lambda inst: str(tmp_path / "sav" / f"slink FireRed {inst}.SaveRAM")
    for inst in ("a", "b"):
        Path(run._gen3_battery_path(inst)).write_bytes(b"SEEDED-" + inst.encode())
        os.utime(run._gen3_battery_path(inst), (900, 900))                    # written before the launch, never touched
    assert side in run.cfg["no_save"] and other not in run.cfg["no_save"]
    assert run._gen3_flushed(side) == b"SEEDED-" + side.encode()              # the no-write half: the seed IS the answer
    with pytest.raises(RuntimeError, match="no fresh flushed battery"):
        run._gen3_flushed(other)                                              # a half that must save: loud
    os.remove(run._gen3_battery_path(side))
    with pytest.raises(RuntimeError, match="no fresh flushed battery"):
        run._gen3_flushed(side)                                               # but a missing file is still no oracle input
