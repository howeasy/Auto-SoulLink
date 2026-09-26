"""tools/mkstates.py's --saveram destination naming (card G5-SMALL-FIXES).

BizHawk keys a GBA SaveRAM file off the ROM's own filename: extension dropped, underscores
shown as spaces (tools/gen3_fixtures.py's `saveram_name`, already proven against a physical
"gen3_slink_RR.gba" -> "gen3 slink RR.SaveRAM" boot-check). mkstates.py's own SAVERAM_DST had
drifted to "slink_RR.SaveRAM" (an underscore BizHawk never reads for ROM_REL
"patch/build/slink_RR.gba"), so a battery save copied there under --saveram never reached the
boot: BizHawk looked for "slink RR.SaveRAM" and found nothing. No emulator here — just the
filename derivation and the copy tools/mkstates.py does before it launches one.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen3_fixtures  # noqa: E402
import mkstates  # noqa: E402


def test_saveram_dst_matches_bizhawks_derived_name():
    """The destination mkstates.py seeds must be the SAME name gen3_fixtures.saveram_name (the
    already-proven helper) derives for ROM_REL, not a separately hard-coded guess."""
    derived = gen3_fixtures.saveram_name(mkstates.ROM_REL)
    assert derived == mkstates.SAVERAM_DST
    assert mkstates.SAVERAM_DST == "slink RR.SaveRAM", (
        "BizHawk replaces underscores with spaces in the ROM basename")


def test_saveram_override_lands_on_bizhawks_actual_filename(tmp_path, monkeypatch):
    """--saveram must actually take effect: the chosen battery ends up under the name BizHawk
    will look for when it boots ROM_REL, not a name only mkstates.py itself ever reads."""
    save_dir = tmp_path / "SaveRAM"
    save_dir.mkdir()
    src = tmp_path / "my_override.SaveRAM"
    src.write_bytes(b"\x2a" * 10)

    monkeypatch.setattr(mkstates, "SAVERAM_DIR", str(save_dir))
    monkeypatch.setattr(mkstates, "SAVERAM_OVERRIDE", str(src))
    monkeypatch.setattr(mkstates, "_run_mkstate", lambda *a, **k: True)

    assert mkstates.build_town(timeout=1) is True

    dest = save_dir / "slink RR.SaveRAM"
    assert dest.exists(), sorted(os.listdir(save_dir))
    assert dest.read_bytes() == src.read_bytes()


def test_override_backs_up_the_players_real_save_before_overwriting(tmp_path, monkeypatch):
    """SAVERAM_DST is the player's own battery save: --saveram must not destroy it."""
    save_dir = tmp_path / "SaveRAM"
    save_dir.mkdir()
    real = save_dir / "slink RR.SaveRAM"
    real.write_bytes(b"\x11" * 10)
    src = tmp_path / "fixture.SaveRAM"
    src.write_bytes(b"\x22" * 10)
    monkeypatch.setattr(mkstates, "SAVERAM_DIR", str(save_dir))
    monkeypatch.setattr(mkstates, "SAVERAM_OVERRIDE", str(src))
    monkeypatch.setattr(mkstates, "_run_mkstate", lambda *a, **k: True)

    assert mkstates.build_battle(timeout=1) is True
    assert real.read_bytes() == src.read_bytes()
    baks = [p for p in save_dir.iterdir() if ".mkstates-bak-" in p.name]
    assert len(baks) == 1 and baks[0].read_bytes() == b"\x11" * 10


def test_default_discovery_finds_the_players_own_save(tmp_path, monkeypatch):
    """With no --saveram, the player's "slink RR.SaveRAM" is a candidate (236ee593 had excluded it
    once SAVERAM_DST became the real name), and it boots in place with no copy."""
    save_dir = tmp_path / "SaveRAM"
    save_dir.mkdir()
    real = save_dir / "slink RR.SaveRAM"
    real.write_bytes(b"\x33" * 0x20000)
    monkeypatch.setattr(mkstates, "SAVERAM_DIR", str(save_dir))
    monkeypatch.setattr(mkstates, "SAVERAM_OVERRIDE", None)
    monkeypatch.setattr(mkstates, "_run_mkstate", lambda *a, **k: True)

    assert mkstates.find_saveram() == str(real)
    assert mkstates.build_town(timeout=1) is True
    assert real.read_bytes() == b"\x33" * 0x20000
    assert not [p for p in save_dir.iterdir() if ".mkstates-bak-" in p.name]
