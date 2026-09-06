"""Compiler/input boundaries, not emulator routing or compiled guard evidence."""
import base64
import hashlib
import json
import subprocess
import zipfile

import pytest

from tools.build_host_guard import FRAMEWORK_NAMES, build, verify_toolchain


def package(folder, entries=None):
    folder.mkdir()
    entries = entries or {"tasks/net472/csc.exe": b"modeled compiler", "tasks/net472/compiler.dll": b"modeled dependency"}
    path = folder / "toolset.nupkg"
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    for name, value in entries.items():
        target = folder / name.removeprefix("tasks/net472/")
        if ".." not in target.parts:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "sha512_base64": base64.b64encode(hashlib.sha512(raw).digest()).decode()}


def test_verified_archive_does_not_cover_changed_extracted_compiler(tmp_path):
    root = tmp_path / "compiler"
    expected = package(root)
    assert len(verify_toolchain(root, expected)) == 3
    (root / "compiler.dll").write_bytes(b"changed")
    with pytest.raises(ValueError, match="extracted compiler"):
        verify_toolchain(root, expected)


def test_wrong_package_hash_refuses_before_opening_archive(tmp_path):
    root = tmp_path / "compiler"
    expected = package(root)
    expected["sha512_base64"] = "untrusted"
    with pytest.raises(ValueError, match="pinned NuGet"):
        verify_toolchain(root, expected)


def test_package_member_cannot_escape_toolchain(tmp_path):
    root = tmp_path / "compiler"
    expected = package(root, {"tasks/net472/../outside.dll": b"bad"})
    with pytest.raises(ValueError, match="extracted compiler"):
        verify_toolchain(root, expected)


def fixture(tmp_path):
    repo, host, framework = (tmp_path / name for name in ("repo", "host", "framework"))
    (repo / "host").mkdir(parents=True)
    (repo / "tools").mkdir()
    (repo / "tools/build_host_guard.py").write_text("modeled builder")
    host.mkdir()
    framework.mkdir()
    (repo / "host/QuarantineGuard.cs").write_text("modeled source")
    (host / "EmuHawk.exe").write_bytes(b"host reference")
    for name in FRAMEWORK_NAMES:
        (framework / name).write_bytes(name.encode())
    compiler = tmp_path / "compiler"
    expected = package(compiler)
    lock = {"schema": "slink-host-guard-toolchain-v1", "compiler_package": expected,
            "host_references": {"EmuHawk.exe": hashlib.sha256(b"host reference").hexdigest()}}
    (repo / "host/toolchain.lock.json").write_text(json.dumps(lock))
    return repo, host, compiler, framework, tmp_path / "output"


def test_existing_output_never_overwritten(tmp_path, monkeypatch):
    args = fixture(tmp_path)
    args[-1].mkdir()
    keep = args[-1] / "marker"
    keep.write_text("keep")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("compiler must not run"))
    with pytest.raises(ValueError, match="already exists"):
        build(*args)
    assert keep.read_text() == "keep"


def test_changed_host_reference_is_rejected_before_output_creation(tmp_path, monkeypatch):
    args = fixture(tmp_path)
    (args[1] / "EmuHawk.exe").write_bytes(b"different host")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("compiler must not run"))
    with pytest.raises(ValueError, match="host reference differs"):
        build(*args)
    assert not args[-1].exists()


def test_input_change_during_compilation_cannot_publish_manifest(tmp_path, monkeypatch):
    args = fixture(tmp_path)

    def compile_model(command, **kwargs):
        (args[-1] / "SLink.QuarantineGuard.dll").write_bytes(b"modeled output")
        (args[0] / "host/QuarantineGuard.cs").write_text("changed during compile")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", compile_model)
    with pytest.raises(ValueError, match="input changed"):
        build(*args)
    assert not (args[-1] / "manifest.json").exists()
    assert (args[-1] / "build.log").exists()
