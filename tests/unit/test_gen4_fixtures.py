"""tools/gen4_fixtures.py: synthetic inputs only (no emulator, no game data required).

Absent real inputs skip by name; present-but-wrong inputs fail (tests/TESTING.md)."""

import binascii
import copy
import hashlib
import json
import struct
from pathlib import Path

import pytest

from tools import gen4_fixtures as g4

HG = "4fcded0e2713dc03929845de631d0932ea2b5a37"
SS = "f8dc38ea20c17541a43b58c5e6d18c1732c7e582"
HGE = "cb2dc435196d09c8c9209bf037240ed834f4cea1"
REAL_HG_SAVE = Path("E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM")


def _base():
    return {
        "PathEntries": {"Paths": [
            {"Type": "Save RAM", "Path": "./SaveRAM", "System": "NDS"},
            {"Type": "Save RAM", "Path": "./SaveRAM", "System": "GBA"},
            {"Type": "Savestates", "Path": "./State", "System": "NDS"},
            {"Type": "Screenshots", "Path": "./Screenshots", "System": "NDS"},
        ]},
        "CoreSyncSettings": {g4.NDS_CORE: {
            "EnableJIT": True, "UseRealTime": True, "InitialTime": "2010-01-01T00:00:00",
            "SkipFirmware": True, "UseRealBIOS": False}},
        "Rewind": {"Enabled": True},
        "SoundEnabled": True, "SoundVolume": 13,
    }


def _cfg(tmp_path, base=None, **kw):
    out = tmp_path / "run.ini"
    kw.setdefault("initial_time", "2010-06-01T12:00:00")
    kw.setdefault("lane_saveram_dir", tmp_path / "SaveRAM")
    return g4.write_nds_run_config(base if base is not None else _base(), out, **kw), out


def test_config_missing_nds_saveram_entry_raises(tmp_path):
    base = _base()
    base["PathEntries"]["Paths"] = [e for e in base["PathEntries"]["Paths"] if e["System"] != "NDS"]
    with pytest.raises(g4.FixtureError, match="NDS 'Save RAM'"):
        _cfg(tmp_path, base)
    assert not (tmp_path / "run.ini").exists()


def test_config_missing_savestates_entry_raises(tmp_path):
    base = _base()
    base["PathEntries"]["Paths"] = [e for e in base["PathEntries"]["Paths"]
                                    if e["Type"] != "Savestates"]
    with pytest.raises(g4.FixtureError, match="Savestates"):
        _cfg(tmp_path, base)


def test_config_missing_sync_settings_raises(tmp_path):
    base = _base()
    del base["CoreSyncSettings"][g4.NDS_CORE]
    with pytest.raises(g4.FixtureError, match="CoreSyncSettings"):
        _cfg(tmp_path, base)


def test_config_pins_written_json(tmp_path):
    _, out = _cfg(tmp_path)
    cfg = json.loads(out.read_text(encoding="utf-8"))
    sync = cfg["CoreSyncSettings"][g4.NDS_CORE]
    assert sync["EnableJIT"] is False and sync["UseRealTime"] is False
    assert sync["InitialTime"] == "2010-06-01T12:00:00"
    assert sync["SkipFirmware"] is True and sync["UseRealBIOS"] is False
    nds, gba, state, shots = cfg["PathEntries"]["Paths"]
    assert nds["Path"] == (tmp_path / "SaveRAM").as_posix()
    assert gba["Path"] == "./SaveRAM"  # only NDS is redirected
    # the shared ./NDS/State holds the owner's QuickSave slots: never write there
    assert state["Path"] == (tmp_path / "State").as_posix()
    assert shots["Path"] == (tmp_path / "Screenshots").as_posix()
    assert cfg["Rewind"]["Enabled"] is False
    assert cfg["SoundEnabled"] is False and cfg["SoundVolume"] == 0
    assert (tmp_path / "SaveRAM").is_dir()


def test_config_never_mutates_base(tmp_path):
    base = _base()
    snap = copy.deepcopy(base)
    _cfg(tmp_path, base)
    assert base == snap
    # a path base: bytes unchanged, and writing over it is refused
    p = tmp_path / "config.ini"
    p.write_text(json.dumps(base), encoding="utf-8-sig")
    before = p.read_bytes()
    g4.write_nds_run_config(p, tmp_path / "out.ini", initial_time="2010-01-01T00:00:00",
                            lane_saveram_dir=tmp_path / "S")
    assert p.read_bytes() == before
    with pytest.raises(g4.FixtureError, match="overwrite"):
        g4.write_nds_run_config(p, p, initial_time="2010-01-01T00:00:00",
                                lane_saveram_dir=tmp_path / "S")


def test_config_bad_initial_time_and_long_path_refused(tmp_path):
    with pytest.raises(g4.FixtureError, match="ISO"):
        _cfg(tmp_path, initial_time="yesterday")
    with pytest.raises(g4.FixtureError, match="MAX_PATH"):
        _cfg(tmp_path, lane_saveram_dir="C:/" + "d" * 200)


def test_long_saveram_path_boundary():
    name = "Pokemon - HeartGold Version (USA).SaveRAM"
    # the autosave .bak sibling is the longest file: it is what must fit
    base_len = len("/Pokemon - HeartGold Version (USA)") + len(".AutoSaveRAM.SaveRAM.bak")
    g4.check_saveram_path("C:/" + "d" * (g4.MAX_PATH_GUARD - 1 - 3 - base_len), name)
    with pytest.raises(g4.FixtureError):
        g4.check_saveram_path("C:/" + "d" * (g4.MAX_PATH_GUARD - 3 - base_len), name)


def _lock_and_rom(tmp_path, data=b"synthetic rom"):
    rom = tmp_path / "src" / "game.nds"
    rom.parent.mkdir()
    rom.write_bytes(data)
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"artifacts": {"heartgold": {
        "role": "rom", "sha1": hashlib.sha1(b"synthetic rom").hexdigest()}}}))
    return rom, lock


def test_stage_rom_ok_wrong_hash_and_absent(tmp_path):
    rom, lock = _lock_and_rom(tmp_path)
    lane = tmp_path / "lane"
    dst = g4.stage_rom(rom, lane, lock)
    assert dst == lane / "rom" / "game.nds" and dst.read_bytes() == b"synthetic rom"

    bad = tmp_path / "src" / "tampered.nds"
    bad.write_bytes(b"synthetic rom!")  # one byte off the pinned image
    with pytest.raises(g4.FixtureError, match="not a pinned"):
        g4.stage_rom(bad, tmp_path / "lane2", lock)
    assert not (tmp_path / "lane2").exists()

    missing = tmp_path / "nope" / "absent.nds"
    with pytest.raises(g4.RomAbsent, match="absent.nds"):
        g4.stage_rom(missing, lane, lock)


def test_lock_rom_table_matches_naming_table():
    pinned = g4.locked_roms()  # the real committed lock
    assert pinned[HG] == "heartgold" and pinned[SS] == "soulsilver" and pinned[HGE] == "heartgold_hge"
    assert set(g4.GAMEDB_SAVERAM) <= set(pinned) and HGE not in g4.GAMEDB_SAVERAM


def test_saveram_naming_gamedb_vs_basename():
    assert g4.saveram_name(HG) == "Pokemon - HeartGold Version (USA).SaveRAM"
    assert g4.saveram_name(SS) == "Pokemon - SoulSilver Version (USA).SaveRAM"
    assert g4.saveram_name(HGE, "test.nds") == "test.SaveRAM"
    assert g4.saveram_name(HGE, "my hge build.nds") == "my hge build.SaveRAM"
    with pytest.raises(g4.FixtureError, match="rom_basename"):
        g4.saveram_name(HGE)


def test_stage_save_names_copies_and_leaves_source(tmp_path):
    src = tmp_path / "owner.sav"
    src.write_bytes(b"\x01\x02" * 100)
    before = src.read_bytes()
    lane = tmp_path / "lane"
    hg = g4.stage_save(src, lane, HG)
    assert hg == lane / "SaveRAM" / "Pokemon - HeartGold Version (USA).SaveRAM"
    hge = g4.stage_save(src, lane, HGE, rom_basename="hge.nds")
    assert hge.name == "hge.SaveRAM"
    assert hg.read_bytes() == hge.read_bytes() == before == src.read_bytes()
    with pytest.raises(g4.RomAbsent, match="gone.sav"):
        g4.stage_save(tmp_path / "gone.sav", lane, HG)


def test_stage_save_refuses_long_lane(tmp_path):
    src = tmp_path / "s.sav"
    src.write_bytes(b"x")
    with pytest.raises(g4.FixtureError, match="MAX_PATH"):
        g4.stage_save(src, Path("C:/" + "d" * 220), HG)


def _footer_block(size=0x100, *, count, name=b"\x01" * 16, tid=1, sid=2, corrupt=False):
    block = bytearray(size)
    block[0x64:0x74] = name
    struct.pack_into("<I", block, 0x64 + 0x10, tid | (sid << 16))
    crc = binascii.crc_hqx(bytes(block[:size - 0x10]), 0xFFFF)
    struct.pack_into("<IIIHH", block, size - 0x10, count, size, 0x20060623, 0,
                     crc ^ 1 if corrupt else crc)
    return bytes(block)


def _save(path, *blocks):
    img = bytearray(b"\xff" * 0x80000)
    for bank, block in zip((0, 0x40000), blocks, strict=False):
        if block:
            img[bank:bank + len(block)] = block
    path.write_bytes(bytes(img))
    return path


def test_identity_parser_newest_bank_and_crc(tmp_path):
    old = _footer_block(count=1, tid=10, sid=20)
    new = _footer_block(count=2, tid=30, sid=40)
    ident = g4.hgss_identity(_save(tmp_path / "a", old, new).read_bytes())
    assert (ident["tid"], ident["sid"], ident["count"]) == (30, 40, 2)
    # newer bank has a bad CRC -> falls back to the valid one
    bad = _footer_block(count=3, tid=50, sid=60, corrupt=True)
    assert g4.hgss_identity(_save(tmp_path / "b", old, bad).read_bytes())["tid"] == 10
    with pytest.raises(g4.FixtureError, match="no valid"):
        g4.hgss_identity(_save(tmp_path / "c", bad).read_bytes())


def test_duo_identical_trainer_refused_distinct_accepted(tmp_path):
    a = _save(tmp_path / "a.sav", None, _footer_block(count=1, name=b"A" * 16, tid=5, sid=6))
    same = _save(tmp_path / "b.sav", None, _footer_block(count=7, name=b"A" * 16, tid=5, sid=6))
    with pytest.raises(g4.FixtureError, match="one trainer"):
        g4.check_duo_inputs(a, same)
    for other in (_footer_block(count=1, name=b"B" * 16, tid=5, sid=6),   # other OT
                  _footer_block(count=1, name=b"A" * 16, tid=9, sid=6),   # other TID
                  _footer_block(count=1, name=b"A" * 16, tid=5, sid=9)):  # other SID
        b = _save(tmp_path / "c.sav", None, other)
        x, y = g4.check_duo_inputs(a, b)
        assert x["tid"] == 5
    with pytest.raises(g4.RomAbsent, match="nope.sav"):
        g4.check_duo_inputs(a, tmp_path / "nope.sav")
    # same OT name, different bytes after the 0xFFFF terminator: still one trainer
    n1 = bytes.fromhex("4100" * 3 + "ffff" + "11" * 8)
    n2 = bytes.fromhex("4100" * 3 + "ffff" + "22" * 8)
    t1 = _save(tmp_path / "t1.sav", None, _footer_block(count=1, name=n1, tid=5, sid=6))
    t2 = _save(tmp_path / "t2.sav", None, _footer_block(count=1, name=n2, tid=5, sid=6))
    with pytest.raises(g4.FixtureError, match="one trainer"):
        g4.check_duo_inputs(t1, t2)


def test_identity_on_real_hg_save():
    if not REAL_HG_SAVE.exists():
        pytest.skip(f"owner HG battery save absent: {REAL_HG_SAVE}")
    ident = g4.hgss_identity(REAL_HG_SAVE.read_bytes())  # present: must parse
    assert (ident["tid"], ident["sid"]) == (26310, 29888)  # docs/gen4/research/offline_measurements.md


def test_our_emuhawk_pids_scopes_to_lane():
    procs = [
        {"ProcessId": 1, "CommandLine": '"EmuHawk.exe" --config=C:\\slink\\g4\\a\\bizhawk.ini C:\\slink\\g4\\a\\rom\\x.nds'},
        {"ProcessId": 2, "CommandLine": '"EmuHawk.exe" --config=C:/slink/g4/ab/bizhawk.ini'},
        {"ProcessId": 3, "CommandLine": None},
        {"ProcessId": 4, "CommandLine": '"EmuHawk.exe" gba.gba'},
    ]
    assert g4.our_emuhawk_pids(procs, "C:/slink/g4/a") == [1]
    assert g4.our_emuhawk_pids(procs, Path("C:/slink/g4/ab")) == [2]
    with pytest.raises(ValueError):
        g4.our_emuhawk_pids(procs, "")


def test_cli_exit_codes(tmp_path, capsys):
    root = str(tmp_path / "root")
    assert g4.main(["stage", "--lane", "t", "--rom", str(tmp_path / "absent.nds"),
                    "--lane-root", root]) == 2
    assert "absent.nds" in capsys.readouterr().err
    junk = tmp_path / "junk.nds"
    junk.write_bytes(b"not a rom")
    assert g4.main(["stage", "--lane", "t", "--rom", str(junk), "--lane-root", root]) == 1
    base = tmp_path / "config.ini"
    base.write_text(json.dumps(_base()), encoding="utf-8-sig")
    assert g4.main(["config", "--lane", "t", "--initial-time", "2010-01-01T12:00:00",
                    "--base", str(base), "--lane-root", root]) == 0
    assert (tmp_path / "root" / "t" / "bizhawk.ini").is_file()
    assert g4.main(["config", "--lane", "bad lane", "--initial-time", "2010-01-01T12:00:00",
                    "--base", str(base), "--lane-root", root]) == 1


def test_pace_1x_pins_real_time_pacing_and_refuses_missing_keys(tmp_path):
    base = _base()
    base.update(Unthrottled=True, ClockThrottle=False, SpeedPercent=300, FrameSkip=4, AutoMinimizeSkipping=True,
                VSyncThrottle=True, SuperHawkThrottle=True)
    unpaced, _ = _cfg(tmp_path, base)
    assert unpaced["Unthrottled"] is True and unpaced["FrameSkip"] == 4  # default leaves pacing alone
    paced, out = _cfg(tmp_path, base, pace_1x=True)
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    # literal, not derived from PACE_1X: dropping a key from the constant must go red (OMP cx-b6e028df P3)
    want = {"Unthrottled": False, "ClockThrottle": True, "SpeedPercent": 100, "FrameSkip": 0,
            "AutoMinimizeSkipping": False, "VSyncThrottle": False, "SuperHawkThrottle": False}
    assert want == g4.PACE_1X
    for cfg in (paced, on_disk):
        assert {k: cfg[k] for k in want} == want
    with pytest.raises(g4.FixtureError, match="pacing keys"):
        _cfg(tmp_path, _base(), pace_1x=True)
