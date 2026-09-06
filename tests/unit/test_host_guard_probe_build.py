"""Adversarial offline build boundaries; modeled subprocesses never start a host."""
import json
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_host_guard_build import package
from tools import build_host_guard as guard, build_host_guard_probes as probes

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def selected(tmp_path):
    repo, host, framework, compiler = (tmp_path / name for name in ("repo", "host", "framework", "compiler"))
    for relative in ("host/QuarantineGuard.cs", "tools/build_host_guard.py", *probes.PROBE_SOURCES):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    host.mkdir()
    (host / "EmuHawk.exe").write_bytes(b"modeled host reference")
    framework.mkdir()
    for name in guard.FRAMEWORK_NAMES:
        (framework / name).write_bytes(name.encode())
    expected = package(compiler)
    lock = {"schema": "slink-host-guard-toolchain-v1", "compiler_package": expected,
            "host_references": {"EmuHawk.exe": guard.fingerprint(host / "EmuHawk.exe")["sha256"]}}
    lock_path = repo / "host/toolchain.lock.json"
    lock_path.write_text(json.dumps(lock))
    candidate = tmp_path / "guard"
    candidate.mkdir()
    artifact = candidate / "SLink.QuarantineGuard.dll"
    artifact.write_bytes(b"modeled selected guard")
    refs = [host / "EmuHawk.exe", *[framework / name for name in guard.FRAMEWORK_NAMES]]
    manifest = {"schema": "slink-host-quarantine-build-v1", "entry_type": "SLink.Host.QuarantineGuard",
                "quarantine_only": True, "production_selected": False, "release_ready": False,
                "source_inputs": [guard.fingerprint(repo / name) for name in
                                  ("host/QuarantineGuard.cs", "host/toolchain.lock.json", "tools/build_host_guard.py")],
                "compiler_inputs": guard.verify_toolchain(compiler, expected),
                "reference_inputs": [guard.fingerprint(path) for path in refs], "artifact": guard.fingerprint(artifact),
                "command": [str(compiler / "csc.exe"), "/nologo", "/noconfig", "/target:library", "/langversion:5",
                            "/optimize+", "/deterministic+", "/debug-", "/warnaserror+", "/out:" + str(artifact),
                            "/pathmap:" + str(repo) + "=/_/SoulLink",
                            *["/reference:" + str(path) for path in refs], str(repo / "host/QuarantineGuard.cs")]}
    path = candidate / "manifest.json"
    path.write_text(json.dumps(manifest))
    return repo, path, tmp_path / "probes"


@pytest.fixture
def modeled_processes(monkeypatch):
    calls = []

    def run(command, **options):
        calls.append((command, options))
        if Path(command[0]).name == "csc.exe":
            target = Path(next(arg[5:] for arg in command if arg.startswith("/out:")))
            target.write_bytes((target.name + " modeled output").encode())
            return subprocess.CompletedProcess(command, 0, "compiled\n", "")
        assert Path(command[0]).name == "GuardProtocolSmoke.exe"
        return subprocess.CompletedProcess(command, 0, json.dumps({"checks": 22, "scope": probes.SMOKE_SCOPE}), "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls, run


def test_build_compiles_two_sources_then_runs_only_unarmed_smoke(selected, modeled_processes):
    repo, source_manifest, output = selected
    calls, _ = modeled_processes
    path = probes.build(*selected)
    result = json.loads(path.read_text())
    assert [Path(command[0]).name for command, _ in calls] == ["csc.exe", "csc.exe", "GuardProtocolSmoke.exe"]
    original = json.loads(source_manifest.read_text())
    assert calls[2][0][1:] == [str(Path(original["reference_inputs"][0]["path"]).parent), original["artifact"]["path"]]
    assert calls[0][0][-1] == str(repo / "tests/host/GuardProtocolSmoke.cs")
    assert calls[1][0][-1] == str(repo / "tests/host/QuarantineLoader.cs")
    assert [options["timeout"] for _, options in calls] == [60, 60, 30]
    assert all(options["cwd"] == output and options.get("shell", False) is False for _, options in calls)
    assert result["quarantine_only"] and result["input_fingerprints_rechecked"]
    assert not any(result[key] for key in ("emulator_launched", "routing_proved", "production_selected", "release_ready"))
    inputs = {Path(item["path"]) for item in result["source_inputs"]}
    assert {Path(probes.__file__).resolve(), repo / "tools/build_host_guard.py", *[repo / name for name in probes.PROBE_SOURCES]} <= inputs
    for item in result["artifacts"] + result["logs"] + [result["execution"], result["guard_manifest"]]:
        assert guard.fingerprint(Path(item["path"])) == item


@pytest.mark.parametrize("change", ["scope", "schema", "command", "executable", "source_missing", "reference_missing",
                                    "compiler_missing", "duplicate", "artifact_path"])
def test_altered_manifest_refuses_before_any_execution_or_output(selected, monkeypatch, change):
    repo, path, output = selected
    manifest = json.loads(path.read_text())
    if change == "scope":
        manifest["production_selected"] = True
    elif change == "schema":
        manifest["schema"] = "unknown"
    elif change == "command":
        manifest["command"].insert(1, "/analyzer:foreign.dll")
    elif change == "executable":
        manifest["command"][0] = str(repo / "foreign.exe")
    elif change == "source_missing":
        manifest["source_inputs"].pop()
    elif change == "reference_missing":
        manifest["reference_inputs"].pop()
    elif change == "compiler_missing":
        manifest["compiler_inputs"].pop()
    elif change == "duplicate":
        manifest["source_inputs"].append(manifest["source_inputs"][0])
    elif change == "artifact_path":
        other = repo / "elsewhere.dll"
        other.write_bytes(Path(manifest["artifact"]["path"]).read_bytes())
        manifest["artifact"] = guard.fingerprint(other)
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("must refuse before process execution"))
    with pytest.raises(ValueError):
        probes.build(*selected)
    assert not output.exists()


@pytest.mark.parametrize("category", ["source_inputs", "compiler_inputs", "reference_inputs", "artifact"])
def test_changed_recorded_input_refuses_before_execution(selected, monkeypatch, category):
    _, path, output = selected
    manifest = json.loads(path.read_text())
    row = manifest[category] if category == "artifact" else manifest[category][0]
    Path(row["path"]).write_bytes(b"altered bytes")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("changed input executed"))
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        probes.build(*selected)
    assert not output.exists()


def test_existing_output_is_preserved(selected, monkeypatch):
    selected[2].mkdir()
    marker = selected[2] / "keep"
    marker.write_text("original")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("existing output must refuse"))
    with pytest.raises(ValueError, match="already exists"):
        probes.build(*selected)
    assert marker.read_text() == "original"


@pytest.mark.parametrize("changed", ["probe_source", "guard_manifest", "guard_artifact", "compiled_smoke"])
def test_changes_between_steps_stop_before_smoke_and_preserve_failure(selected, modeled_processes, monkeypatch, changed):
    repo, manifest_path, output = selected
    calls, real_model = modeled_processes

    def run(command, **options):
        result = real_model(command, **options)
        if len(calls) == 2:
            if changed == "probe_source":
                path = repo / probes.PROBE_SOURCES[1]
            elif changed == "guard_manifest":
                path = manifest_path
            elif changed == "guard_artifact":
                path = Path(json.loads(manifest_path.read_text())["artifact"]["path"])
            else:
                path = output / "GuardProtocolSmoke.exe"
            path.write_bytes(b"changed between steps")
        return result

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="input changed"):
        probes.build(*selected)
    assert len(calls) == 2 and not (output / "manifest.json").exists()
    assert not json.loads((output / "execution.json").read_text())["success"]


@pytest.mark.parametrize("failure", ["compile_error", "compile_timeout", "smoke_error", "smoke_timeout", "smoke_json", "smoke_count", "smoke_scope"])
def test_process_failure_or_false_smoke_evidence_cannot_publish_success(selected, modeled_processes, monkeypatch, failure):
    _, _, output = selected
    calls, real_model = modeled_processes

    def run(command, **options):
        is_smoke = Path(command[0]).name == "GuardProtocolSmoke.exe"
        if failure == "compile_error" and not is_smoke or failure == "smoke_error" and is_smoke:
            return subprocess.CompletedProcess(command, 1, "", "modeled failure")
        if failure == "compile_timeout" and not is_smoke or failure == "smoke_timeout" and is_smoke:
            raise subprocess.TimeoutExpired(command, options["timeout"], output=b"partial stdout")
        result = real_model(command, **options)
        if is_smoke and failure.startswith("smoke_"):
            result.stdout = "not JSON" if failure == "smoke_json" else json.dumps({
                "checks": 1 if failure == "smoke_count" else 22,
                "scope": "routing proved" if failure == "smoke_scope" else probes.SMOKE_SCOPE})
        return result

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises((RuntimeError, ValueError)):
        probes.build(*selected)
    assert not (output / "manifest.json").exists()
    evidence = json.loads((output / "execution.json").read_text())
    assert not evidence["success"] and evidence["failure"]
    assert all(Path(command[0]).name != "EmuHawk.exe" for command, _ in calls)


def test_additional_scoped_smoke_checks_are_allowed(selected, modeled_processes, monkeypatch):
    _, real_model = modeled_processes

    def run(command, **options):
        result = real_model(command, **options)
        if Path(command[0]).name == "GuardProtocolSmoke.exe":
            result.stdout = json.dumps({"checks": 23, "scope": probes.SMOKE_SCOPE})
        return result

    monkeypatch.setattr(subprocess, "run", run)
    assert json.loads(probes.build(*selected).read_text())["smoke_result"]["checks"] == 23
