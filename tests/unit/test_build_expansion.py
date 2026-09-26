"""Offline falsifiers for expansion build provenance and dependency admission."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_expansion", ROOT / "tools/build_expansion.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_lock():
    lock = build.load_lock()
    assert lock["source"]["commit"] == "e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7"
    assert lock["compiler"]["status"] == "provisional"
    assert len(lock["config_headers"]) > 10
    assert lock["expected_rom"] == {
        "sha1": "28877d733492299599f2b8fff50493109d72653c",
        "md5": "83bde8deeaa27453b12545b9cfffe3a6",
        "size": 33554432,
    }


@pytest.mark.parametrize("field,value", [("commit", "abc"), ("tag", "master")])
def test_bad_source(field, value, tmp_path):
    lock = build.load_lock()
    lock["source"][field] = value
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        build.load_lock(path)


def synthetic(tmp_path):
    lock = build.load_lock()
    for name in build.ARTIFACTS:
        (tmp_path / name).write_bytes(b"synthetic " + name.encode())
    rom = tmp_path / "pokeemerald.gba"
    lock["expected_rom"] = {"sha1": build.digest(rom, "sha1"), "md5": build.digest(rom, "md5"),
                            "size": rom.stat().st_size}
    record = build.make_receipt(lock, tmp_path, {"gcc": "synthetic"}, 1.0)
    (tmp_path / "receipt.json").write_text(json.dumps(record))
    return lock, record


def receipt_of(tmp_path):
    """Re-parse the receipt. make_receipt embeds the lock's own source/compiler
    dicts, so mutating a parsed record would silently mutate the lock too."""
    return json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))


def test_check_synthetic(tmp_path):
    lock, _ = synthetic(tmp_path)
    build.check_output(lock, tmp_path)


@pytest.mark.parametrize("mutation", ["missing", "corrupt", "lock", "rom", "empty", "extra"])
def test_check_refuses_tampering(tmp_path, mutation):
    lock, record = synthetic(tmp_path)
    if mutation == "missing":
        (tmp_path / "pokeemerald.sym").unlink()
    elif mutation == "corrupt":
        (tmp_path / "pokeemerald.elf").write_bytes(b"different")
    elif mutation == "lock":
        lock = copy.deepcopy(lock)
        lock["make_variables"]["LTO"] = "1"
    elif mutation == "rom":
        record["rom"]["sha1"] = "0" * 40
    elif mutation == "empty":
        (tmp_path / "pokeemerald.map").write_bytes(b"")
    else:
        record["files"]["unexpected"] = {}
    (tmp_path / "receipt.json").write_text(json.dumps(record))
    with pytest.raises(ValueError):
        build.check_output(lock, tmp_path)


def flip_byte(path):
    """Same-length bit flip: the size arm cannot see it, only the hash arm can."""
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))
    assert path.stat().st_size == len(data)


@pytest.mark.parametrize("name", ["pokeemerald.gba", "pokeemerald.sym"])
def test_check_refuses_same_length_byte_flip(tmp_path, name):
    lock, _ = synthetic(tmp_path)
    flip_byte(tmp_path / name)
    with pytest.raises(ValueError):
        build.check_output(lock, tmp_path)


def test_check_refuses_foreign_source_commit(tmp_path):
    lock, _ = synthetic(tmp_path)
    record = receipt_of(tmp_path)
    record["source"]["commit"] = "0123456789abcdef0123456789abcdef01234567"
    (tmp_path / "receipt.json").write_text(json.dumps(record))
    with pytest.raises(ValueError):
        build.check_output(lock, tmp_path)


def test_check_allows_owner_signoff(tmp_path):
    lock, _ = synthetic(tmp_path)
    record = receipt_of(tmp_path)
    lock["compiler"]["status"] = "approved"
    lock["compiler"]["approved_by"] = "reviewer"
    lock["compiler"]["approved_at"] = "2026-09-26T00:00:00+00:00"
    build.check_output(lock, tmp_path)
    assert record["compiler"]["status"] == "provisional"
    assert build.lock_digest(lock) == receipt_of(tmp_path)["lock_sha256"]


def test_check_refuses_expected_rom_mismatch(tmp_path):
    lock, record = synthetic(tmp_path)
    lock["expected_rom"]["sha1"] = "0" * 40
    (tmp_path / "receipt.json").write_text(json.dumps(record))
    # The digest is untouched, so this can only fail on the ROM comparison itself.
    assert build.lock_digest(lock) == record["lock_sha256"]
    with pytest.raises(ValueError, match="expected_rom"):
        build.check_output(lock, tmp_path)


def test_check_builder_sha256_warns_by_default(tmp_path, capsys):
    lock, _ = synthetic(tmp_path)
    record = receipt_of(tmp_path)
    record["tool_versions"]["builder_sha256"] = "0" * 64
    (tmp_path / "receipt.json").write_text(json.dumps(record))
    build.check_output(lock, tmp_path)
    assert "WARNING" in capsys.readouterr().out


def test_check_builder_sha256_raises_under_strict(tmp_path):
    lock, _ = synthetic(tmp_path)
    record = receipt_of(tmp_path)
    record["tool_versions"]["builder_sha256"] = "0" * 64
    (tmp_path / "receipt.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="build_expansion.py"):
        build.check_output(lock, tmp_path, strict=True)


@pytest.mark.parametrize("name", ["linux1", "linux2"])
def test_shipped_receipts_still_validate(name):
    out = ROOT / ".cache/expansion-output" / name
    if not (out / "receipt.json").is_file():
        pytest.skip(f"no local {name} build output present")
    build.check_output(build.load_lock(), out)


def test_check_missing_receipt(tmp_path):
    with pytest.raises(ValueError, match="receipt"):
        build.check_output(build.load_lock(), tmp_path)


def test_preflight_names_missing_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(build.shutil, "which", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="pkg-config.*libpng.*zlib"):
        build.preflight(build.load_lock(), tmp_path, {"PATH": ""}, 10)


def test_output_refuses_outside_cache(tmp_path):
    with pytest.raises(ValueError, match="output"):
        build.output_path(tmp_path)


def test_check_cli_is_offline(tmp_path, monkeypatch, capsys):
    out = tmp_path / ".cache/expansion-output/synthetic"
    out.mkdir(parents=True)
    lock, _ = synthetic(out)
    # main() reloads the lock from disk; the synthetic ROM pins its own expected_rom.
    monkeypatch.setattr(build, "load_lock", lambda: lock)
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "OUTPUTS", out.parent)
    monkeypatch.setattr(build.sys, "argv", ["build_expansion.py", "--check", "--output", str(out)])

    def forbidden(*args, **kwargs):
        pytest.fail("offline --check attempted a subprocess")

    monkeypatch.setattr(build, "run", forbidden)
    assert build.main() == 0
    assert "no rebuild performed" in capsys.readouterr().out


@pytest.mark.parametrize("field,value", [("host_patches", ["unexpected"]), ("schema_version", 2)])
def test_reject_unsupported_recipe(field, value, tmp_path):
    lock = build.load_lock()
    lock[field] = value
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        build.load_lock(path)


@pytest.mark.parametrize("field,value", [("sha1", "abc"), ("md5", "zz"), ("size", 0)])
def test_reject_malformed_expected_rom(field, value, tmp_path):
    lock = build.load_lock()
    lock["expected_rom"][field] = value
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="expected_rom"):
        build.load_lock(path)
