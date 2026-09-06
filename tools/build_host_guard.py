"""Build the inactive quarantine tool with explicit pinned local dependencies.

No package download, emulator launch, tool installation or host configuration
mutation. The selected output directory must be new. All compiler package bytes
and extracted compiler/runtime files are verified before code is executed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

FRAMEWORK_NAMES = ("mscorlib.dll", "System.dll", "System.Core.dll", "System.Drawing.dll", "System.Windows.Forms.dll")


def fingerprint(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def verify_toolchain(directory: Path, expected: dict) -> list[dict]:
    package = directory / "toolset.nupkg"
    raw = package.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected["sha256"] or base64.b64encode(hashlib.sha512(raw).digest()).decode() != expected["sha512_base64"]:
        raise ValueError("compiler package does not match pinned NuGet bytes")
    selected = [fingerprint(package)]
    with zipfile.ZipFile(package) as archive:
        members = archive.infolist()
        names = [entry.filename for entry in members]
        if len(names) != len(set(names)):
            raise ValueError("duplicate compiler package entry")
        for entry in members:
            if entry.is_dir() or not entry.filename.startswith("tasks/net472/"):
                continue
            relative = Path(entry.filename).relative_to("tasks/net472")
            path = (directory / relative).resolve()
            if not path.is_relative_to(directory.resolve()) or path.read_bytes() != archive.read(entry):
                raise ValueError("extracted compiler bytes differ: " + str(relative))
            selected.append(fingerprint(path))
    if not any(Path(item["path"]).name == "csc.exe" for item in selected):
        raise ValueError("compiler executable missing from package")
    return selected


def build(repo: Path, host: Path, toolchain: Path, framework: Path, output: Path) -> Path:
    repo, host, toolchain, framework, output = (p.resolve() for p in (repo, host, toolchain, framework, output))
    if output.exists():
        raise ValueError("output already exists; preserve earlier candidate")
    lock_path = repo / "host/toolchain.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("schema") != "slink-host-guard-toolchain-v1":
        raise ValueError("unknown host toolchain contract")
    compiler_inputs = verify_toolchain(toolchain, lock["compiler_package"])
    refs = []
    for relative, digest in lock["host_references"].items():
        path = (host / relative).resolve()
        if not path.is_relative_to(host) or fingerprint(path)["sha256"] != digest:
            raise ValueError("host reference differs: " + relative)
        refs.append(path)
    refs += [framework / name for name in FRAMEWORK_NAMES]
    reference_inputs = [fingerprint(path) for path in refs]
    source = repo / "host/QuarantineGuard.cs"
    inputs = [fingerprint(source), fingerprint(lock_path), fingerprint(repo / "tools/build_host_guard.py")]
    output.mkdir(parents=True, exist_ok=False)
    target = output / "SLink.QuarantineGuard.dll"
    options = ["/nologo", "/noconfig", "/target:library", "/langversion:5", "/optimize+",
               "/deterministic+", "/debug-", "/warnaserror+", "/out:" + str(target),
               "/pathmap:" + str(repo) + "=/_/SoulLink"]
    command = [str(toolchain / "csc.exe"), *options, *["/reference:" + str(path) for path in refs], str(source)]
    result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=60)
    (output / "build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0 or not target.is_file():
        raise RuntimeError("quarantine compiler failed; see " + str(output / "build.log"))
    for item in compiler_inputs + reference_inputs + inputs:
        if fingerprint(Path(item["path"])) != item:
            raise ValueError("build input changed while compiling: " + item["path"])
    manifest = {"schema": "slink-host-quarantine-build-v1", "entry_type": "SLink.Host.QuarantineGuard",
                "quarantine_only": True, "production_selected": False, "release_ready": False,
                "source_inputs": inputs, "compiler_inputs": compiler_inputs,
                "reference_inputs": reference_inputs, "command": command, "artifact": fingerprint(target)}
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "host", "toolchain", "framework", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    options = parser.parse_args()
    print(build(**vars(options)))


if __name__ == "__main__":
    main()
