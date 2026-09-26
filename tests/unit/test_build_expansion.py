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
    record = build.make_receipt(lock, tmp_path, {"gcc": "synthetic"}, 1.0)
    (tmp_path / "receipt.json").write_text(json.dumps(record))
    return lock, record


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
        lock["compiler"]["status"] = "approved"
    elif mutation == "rom":
        record["rom"]["sha1"] = "0" * 40
    elif mutation == "empty":
        (tmp_path / "pokeemerald.map").write_bytes(b"")
    else:
        record["files"]["unexpected"] = {}
    (tmp_path / "receipt.json").write_text(json.dumps(record))
    with pytest.raises(ValueError):
        build.check_output(lock, tmp_path)


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
    synthetic(out)
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
