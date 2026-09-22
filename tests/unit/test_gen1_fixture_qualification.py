"""Gen 1 binds shared orchestration without replacing its independent byte oracle.

Synthetic temporary inputs exercise the seam, not legal-save or boot semantics.
Committed fixtures are never written and no emulator callback is installed.
"""
import hashlib

import pytest

from tools import gen1_fixtures as fixtures


@pytest.fixture
def bound(tmp_path, monkeypatch):
    directory = tmp_path / "synthetic-inputs"
    directory.mkdir()
    save, rom = directory / "red_town.SaveRAM", tmp_path / "test-rom.bin"
    save.write_bytes(b"model save bytes")
    rom.write_bytes(b"model ROM bytes")
    monkeypatch.setattr(fixtures, "FIXTURES", str(directory))
    monkeypatch.setattr(fixtures, "DUMP", {"red": str(rom)})
    monkeypatch.setattr(fixtures.codec, "decode_party", lambda _: [{"species": 153, "level": 5, "exp": 135}])
    seen = []

    def oracle(sram, image, notes=None):
        seen.append((sram, image))
        if notes is not None:
            notes.append("model oracle control")
        return []

    monkeypatch.setattr(fixtures, "qualify", oracle)
    return save, rom, seen


def test_gen1_static_report_invokes_game_oracle_and_binds_actual_bytes(bound):
    save, rom, seen = bound
    report = fixtures.qualification_report()
    assert report["passed"] and report["scope"] == "static"
    assert report["required_stages"] == ["qualify"]
    assert seen == [(save.read_bytes(), rom.read_bytes())]
    row = report["fixtures"][0]
    assert row["artifacts"]["fixture"]["sha256"] == hashlib.sha256(b"model save bytes").hexdigest()
    assert row["artifacts"]["rom"]["sha256"] == hashlib.sha256(b"model ROM bytes").hexdigest()
    assert {"codec_source", "rom_reader_source", "qualification_source", "rom_symbols"} <= row["artifacts"].keys()
    assert row["stages"][0]["notes"] == ["model oracle control"]


def test_cli_lines_remain_compatible_and_missing_rom_refuses(bound, capsys):
    _, rom, _ = bound
    assert fixtures.qualify_all() == 0
    assert capsys.readouterr().out.strip() == "red_town: OK party=[(153, 5, 135)]"
    rom.unlink()
    assert fixtures.qualify_all() == 1
    assert capsys.readouterr().out.strip() == "red_town: NO-ROM"


def test_game_oracle_failure_cannot_be_overridden_by_shared_runner(bound, monkeypatch):
    monkeypatch.setattr(fixtures, "qualify", lambda *args: ["main checksum does not validate"])
    report = fixtures.qualification_report()
    assert not report["passed"] and "main checksum" in str(report)
    with pytest.raises(ValueError, match="only game"):
        fixtures.qualification_report(stage_callbacks={"qualify": lambda _: True})


def test_full_scope_needs_live_stages_and_static_success_cannot_fill_them(bound):
    _, _, seen = bound
    report = fixtures.qualification_report(scope="full")
    assert not report["passed"] and seen == []
    assert all(stage in str(report["errors"]) for stage in ("boot", "resave", "post_oracle"))


def test_empty_inventory_is_not_a_success(bound, capsys):
    save, _, _ = bound
    save.unlink()
    assert fixtures.qualify_all() == 1
    assert "empty" in capsys.readouterr().out


def test_legacy_diagnostic_never_qualifies_bad_bytes(bound, monkeypatch, capsys):
    monkeypatch.setattr(fixtures, "LEGACY", {"red_town"})
    monkeypatch.setattr(fixtures, "qualify", lambda *args: ["slot 0: exp 0 is not level 5 on curve 0"])
    assert fixtures.qualify_all() == 1
    assert capsys.readouterr().out.startswith("red_town: LEGACY ")


def test_native_size_oracle_remains_gen1_owned():
    assert fixtures.qualify(b"", b"") == ["SaveRAM is 0 bytes, not 32768"]


def test_unknown_title_is_reported_as_missing_rom(bound):
    save, _, _ = bound
    other = save.with_name("unknown_town.SaveRAM")
    save.rename(other)
    report = fixtures.qualification_report()
    assert not report["passed"]
    assert report["fixtures"][0]["missing_artifact"] == "rom"


def test_stale_oracle_cache_cannot_masquerade_as_current_source_provenance(bound, monkeypatch):
    old = {"stale_control": True}
    monkeypatch.setattr(fixtures.scan, "_SYMS_CACHE", old)

    def oracle(*args):
        return ["stale symbol data used"] if fixtures.scan._SYMS_CACHE is old else []

    monkeypatch.setattr(fixtures, "qualify", oracle)
    assert fixtures.qualification_report()["passed"]
    assert fixtures.scan._SYMS_CACHE is old


def test_oracle_cache_is_restored_when_independent_oracle_raises(bound, monkeypatch):
    old = {"caller_owned": True}
    monkeypatch.setattr(fixtures.scan, "_PUREGB_PACK_CACHE", old)

    def broken(*args):
        raise ValueError("independent oracle failed")

    monkeypatch.setattr(fixtures, "qualify", broken)
    assert not fixtures.qualification_report()["passed"]
    assert fixtures.scan._PUREGB_PACK_CACHE is old
