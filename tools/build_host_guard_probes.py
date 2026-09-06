"""Build/run offline quarantine protocol probes from a verified guard build.

No download, installation or emulator launch. Only the pinned compiler and the
freshly compiled unarmed protocol executable run; the loader DLL is not run.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from tools import build_host_guard as guard_builder

PROBE_SOURCES = ("tests/host/GuardProtocolSmoke.cs", "tests/host/QuarantineLoader.cs")
SMOKE_SCOPE = "compiled unarmed protocol; no emulator or routing proof"
COMMON_OPTIONS = ["/nologo", "/noconfig", "/langversion:5", "/optimize+",
                  "/deterministic+", "/debug-", "/warnaserror+"]


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_pairs)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object: " + str(path))
    return value


def _checked_fingerprints(rows, label: str) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise ValueError(label + " must be a nonempty fingerprint list")
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"path", "sha256", "size_bytes"}
                or not isinstance(row["path"], str) or not Path(row["path"]).is_absolute()
                or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                or type(row["size_bytes"]) is not int or row["size_bytes"] < 0):
            raise ValueError("invalid " + label + " fingerprint")
        path = Path(row["path"]).resolve()
        if path in seen:
            raise ValueError("duplicate " + label + " input")
        seen.add(path)
        if guard_builder.fingerprint(path) != row:
            raise ValueError(label + " fingerprint mismatch: " + str(path))
    return rows


def _command(compiler: Path, repo: Path, refs: list[Path], source: Path, target: Path, kind: str) -> list[str]:
    # Match the reviewed builder's option order; no caller-supplied flags survive.
    return [str(compiler), *COMMON_OPTIONS[:2], "/target:" + kind, *COMMON_OPTIONS[2:],
            "/out:" + str(target), "/pathmap:" + str(repo) + "=/_/SoulLink",
            *["/reference:" + str(path) for path in refs], str(source)]


def _validate_guard(repo: Path, path: Path) -> dict:
    manifest_identity = guard_builder.fingerprint(path)
    manifest = _read_object(path)
    if (manifest.get("schema") != "slink-host-quarantine-build-v1"
            or manifest.get("entry_type") != "SLink.Host.QuarantineGuard"
            or manifest.get("quarantine_only") is not True
            or manifest.get("production_selected") is not False
            or manifest.get("release_ready") is not False):
        raise ValueError("unsupported guard build schema or scope")
    sources = _checked_fingerprints(manifest.get("source_inputs"), "guard source")
    compiler_inputs = _checked_fingerprints(manifest.get("compiler_inputs"), "compiler")
    reference_inputs = _checked_fingerprints(manifest.get("reference_inputs"), "reference")
    artifact = _checked_fingerprints([manifest.get("artifact")], "guard artifact")[0]
    required_sources = {repo / name for name in ("host/QuarantineGuard.cs", "host/toolchain.lock.json", "tools/build_host_guard.py")}
    if {Path(row["path"]) for row in sources} != required_sources:
        raise ValueError("guard source closure must contain this repository's guard, lock and builder")
    if (repo / "tools/build_host_guard.py").read_bytes() != Path(guard_builder.__file__).read_bytes():
        raise ValueError("selected guard builder differs from the executing verifier")
    lock = _read_object(repo / "host/toolchain.lock.json")
    if lock.get("schema") != "slink-host-guard-toolchain-v1":
        raise ValueError("unsupported guard toolchain lock")
    command = manifest.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
        raise ValueError("invalid guard compiler command")
    compiler = Path(command[0])
    if not compiler.is_absolute() or compiler.name != "csc.exe":
        raise ValueError("guard compiler command does not select csc.exe")
    compiler = compiler.resolve()
    verified_compiler = guard_builder.verify_toolchain(compiler.parent, lock["compiler_package"])
    if compiler_inputs != verified_compiler or compiler not in {Path(row["path"]) for row in verified_compiler}:
        raise ValueError("compiler input closure differs from the pinned package")
    host_entries = [Path(row["path"]) for row in reference_inputs if Path(row["path"]).name == "EmuHawk.exe"]
    if len(host_entries) != 1:
        raise ValueError("exactly one pinned EmuHawk reference is required")
    host = host_entries[0].parent
    host_pins = lock.get("host_references")
    if not isinstance(host_pins, dict) or "EmuHawk.exe" not in host_pins:
        raise ValueError("host reference pins missing")
    refs = []
    for relative, digest in host_pins.items():
        if not isinstance(relative, str):
            raise ValueError("invalid host reference path")
        ref = (host / relative).resolve()
        if not ref.is_relative_to(host) or guard_builder.fingerprint(ref)["sha256"] != digest:
            raise ValueError("host reference differs from lock: " + relative)
        refs.append(ref)
    if len(reference_inputs) != len(refs) + len(guard_builder.FRAMEWORK_NAMES):
        raise ValueError("unexpected reference input count")
    framework = Path(reference_inputs[len(refs)]["path"]).parent
    refs.extend(framework / name for name in guard_builder.FRAMEWORK_NAMES)
    if refs != [Path(row["path"]) for row in reference_inputs]:
        raise ValueError("reference closure differs from locked host and selected framework")
    target = Path(artifact["path"])
    if target != path.parent / "SLink.QuarantineGuard.dll":
        raise ValueError("guard artifact must be beside its manifest")
    expected_command = _command(compiler, repo, refs, repo / "host/QuarantineGuard.cs", target, "library")
    if command != expected_command:
        raise ValueError("guard compiler command differs from reviewed builder shape")
    protected = [manifest_identity, *sources, *compiler_inputs, *reference_inputs, artifact]
    _recheck(protected)
    return {"guard_manifest": manifest_identity, "guard_artifact": artifact, "source_inputs": sources,
            "compiler_inputs": compiler_inputs, "reference_inputs": reference_inputs,
            "compiler": compiler, "refs": refs, "host": host, "protected": protected}


def _recheck(rows: list[dict]) -> None:
    for row in rows:
        if guard_builder.fingerprint(Path(row["path"])) != row:
            raise ValueError("input changed during probe build/run: " + row["path"])


def _json_write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(repo: Path, guard_manifest: Path, output: Path) -> Path:
    repo, guard_manifest, output = (p.resolve() for p in (repo, guard_manifest, output))
    if output.exists():
        raise ValueError("output already exists; preserve earlier probe build")
    selected = _validate_guard(repo, guard_manifest)
    probe_sources = [repo / name for name in PROBE_SOURCES]
    extra_inputs = [guard_builder.fingerprint(Path(__file__)), *[guard_builder.fingerprint(path) for path in probe_sources]]
    protected = [*selected["protected"], *extra_inputs]
    _recheck(protected)
    output.mkdir(parents=True, exist_ok=False)
    evidence = {"schema": "slink-host-quarantine-probe-execution-v1", "scope": SMOKE_SCOPE,
                "success": False, "emulator_launched": False, "routing_proved": False,
                "production_selected": False, "release_ready": False, "steps": []}
    evidence_path = output / "execution.json"
    artifacts, logs = [], []

    def execute(label: str, command: list[str], timeout: int) -> subprocess.CompletedProcess:
        _recheck(protected)
        try:
            result = subprocess.run(command, cwd=output, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            def text(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            step = {"label": label, "command": command, "timed_out": True,
                    "stdout": text(exc.stdout), "stderr": text(exc.stderr)}
            evidence["steps"].append(step)
            _json_write(evidence_path, evidence)
            raise RuntimeError(label + " timed out; see " + str(evidence_path)) from exc
        log = output / (label + ".log")
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        log_identity = guard_builder.fingerprint(log)
        logs.append(log_identity)
        protected.append(log_identity)
        evidence["steps"].append({"label": label, "command": command, "returncode": result.returncode,
                                  "timed_out": False, "stdout": result.stdout, "stderr": result.stderr})
        _json_write(evidence_path, evidence)
        _recheck(protected)
        if result.returncode != 0:
            raise RuntimeError(label + " failed; see " + str(log))
        return result

    try:
        for source, name, kind, label in zip(probe_sources,
                ("GuardProtocolSmoke.exe", "SLink.QuarantineProbe.dll"), ("exe", "library"),
                ("compile_smoke", "compile_loader"), strict=True):
            target = output / name
            command = _command(selected["compiler"], repo, selected["refs"], source, target, kind)
            execute(label, command, 60)
            if not target.is_file() or target.resolve().parent != output:
                raise RuntimeError("compiler did not create expected artifact: " + name)
            identity = guard_builder.fingerprint(target)
            artifacts.append(identity)
            protected.append(identity)
        smoke = execute("unarmed_smoke", [str(output / "GuardProtocolSmoke.exe"), str(selected["host"]),
                                          selected["guard_artifact"]["path"]], 30)
        result = json.loads(smoke.stdout.strip(), object_pairs_hook=_object_pairs)
        if (not isinstance(result, dict) or type(result.get("checks")) is not int
                or result["checks"] < 22 or result.get("scope") != SMOKE_SCOPE):
            raise ValueError("unarmed smoke result does not prove at least 22 scoped checks")
        _recheck(protected)
        evidence.update(success=True, smoke_result=result, input_fingerprints_rechecked=True)
        _json_write(evidence_path, evidence)
        manifest = {"schema": "slink-host-quarantine-probes-v1", "scope": SMOKE_SCOPE,
                    "quarantine_only": True, "production_selected": False, "release_ready": False,
                    "emulator_launched": False, "routing_proved": False,
                    "guard_manifest": selected["guard_manifest"], "guard_artifact": selected["guard_artifact"],
                    "source_inputs": [*selected["source_inputs"], *extra_inputs],
                    "compiler_inputs": selected["compiler_inputs"], "reference_inputs": selected["reference_inputs"],
                    "artifacts": artifacts, "logs": logs, "execution": guard_builder.fingerprint(evidence_path),
                    "steps": evidence["steps"], "smoke_result": result, "input_fingerprints_rechecked": True}
        path = output / "manifest.json"
        _json_write(path, manifest)
        return path
    except Exception as exc:
        evidence.update(success=False, failure=type(exc).__name__ + ": " + str(exc))
        _json_write(evidence_path, evidence)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "guard-manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(build(args.repo, args.guard_manifest, args.output))


if __name__ == "__main__":
    main()
