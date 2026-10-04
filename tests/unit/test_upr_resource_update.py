"""tools/upr_resource_update.py: a resource-only jar update touches the ini and nothing else."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_upr_gen1_ini as gen  # noqa: E402
import upr_resource_update as uru  # noqa: E402

OLD_BLOCK = "[old overlay]\nCRCInHeader=0x1111\n"
NEW_BLOCK = "[new overlay]\nCRCInHeader=0x2222\n"


def _jar(path: Path, block: str) -> Path:
    ini = f"head\n{gen.FORK_BEGIN}\n{block}{gen.FORK_END}\ntail\n"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("com/dabomstew/Main.class", b"\xca\xfe\xba\xbe")
        zf.writestr(uru.INI_NAME, ini)
        zf.writestr("com/dabomstew/other.ini", "untouched\n")
    return path


@pytest.fixture
def rig(tmp_path, monkeypatch):
    entries = tmp_path / "entries.ini"
    entries.write_text(NEW_BLOCK, encoding="utf-8")
    allow = tmp_path / "upr_jars.json"
    allow.write_text(json.dumps({"old": "0" * 64}), encoding="utf-8")
    patches = tmp_path / "patch_upr"
    patches.mkdir()
    (patches / "0012-x.patch").write_text("x", encoding="utf-8")
    monkeypatch.setattr(uru, "ENTRIES", entries)
    monkeypatch.setattr(uru, "ALLOWLIST", allow)
    monkeypatch.setattr(uru, "PATCHES", patches)
    monkeypatch.setattr(uru, "ROOT", tmp_path)
    return tmp_path, allow, patches


def test_the_splice_replaces_only_the_marked_block(rig):
    tmp, *_ = rig
    old, new = uru.spliced_ini(_jar(tmp / "j.jar", OLD_BLOCK))
    assert OLD_BLOCK in old and NEW_BLOCK in new and OLD_BLOCK not in new
    assert new.startswith("head\n") and new.endswith("tail\n")


def test_check_passes_when_current_and_fails_when_stale(rig, monkeypatch, capsys):
    tmp, *_ = rig
    stale, current = _jar(tmp / "stale.jar", OLD_BLOCK), _jar(tmp / "cur.jar", NEW_BLOCK)
    monkeypatch.setattr(sys, "argv", ["x", "--jar", str(current), "--check"])
    assert uru.main() == 0
    monkeypatch.setattr(sys, "argv", ["x", "--jar", str(stale), "--check"])
    assert uru.main() == 1


def test_install_is_resource_only_keeps_the_old_jar_pins_the_new_one_and_numbers_the_patch(rig, monkeypatch):
    tmp, allow, patches = rig
    jar = _jar(tmp / "PokeRandoZX.jar", OLD_BLOCK)
    before = jar.read_bytes()
    monkeypatch.setattr(sys, "argv", ["x", "--jar", str(jar), "--install", "--label", "test update"])
    assert uru.main() == 0
    backups = list(tmp.glob("PokeRandoZX-pre0013-*.jar"))
    assert len(backups) == 1 and backups[0].read_bytes() == before                  # the previous jar is kept
    with zipfile.ZipFile(jar) as new, zipfile.ZipFile(backups[0]) as old:
        diff = [n for n in old.namelist() if old.read(n) != new.read(n)]
    assert diff == [uru.INI_NAME]                                                   # resource-only
    pins = json.loads(allow.read_text(encoding="utf-8"))
    import hashlib
    assert hashlib.sha256(jar.read_bytes()).hexdigest() in pins.values() and len(pins) == 2
    [patch] = patches.glob("0013-*.patch")
    assert "+CRCInHeader=0x2222" in patch.read_text(encoding="utf-8") and "-CRCInHeader=0x1111" in patch.read_text(encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", "--jar", str(jar), "--check"])
    assert uru.main() == 0                                                          # idempotent afterwards
