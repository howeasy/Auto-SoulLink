"""Pinned expansion reference build. ROMs and outputs stay in ignored .cache.

--check is offline integrity checking, never a reproducibility/runtime claim.
--host hgbox builds on the pinned Linux host and copies results into local .cache.
Every build uses a clean dedicated clone; an output directory must be new.
Native Windows builds are unsupported; see the X0 feasibility evidence.
Owner sign-off in the lock is provenance, not build identity, and is excluded from
the lock digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "data/gen3_exp_sources.lock.json"
CACHE = ROOT / ".cache/expansion"
OUTPUTS = ROOT / ".cache/expansion-output"
ARTIFACTS = tuple(f"pokeemerald.{ext}" for ext in ("gba", "elf", "map", "sym"))
SCHEMA = "gen3-expansion-build-v1"
# Owner sign-off records a reviewer's opinion about a toolchain; it is not an input to
# the build.  Hashing it made --check fail the moment anyone signed off, which
# invalidated every receipt on disk.  `expected_rom` is likewise an assertion about the
# build's output, so re-pinning it must not invalidate receipts either.
SIGNOFF_COMPILER_FIELDS = ("status", "approved_by", "approved_at")
UNHASHED_LOCK_KEYS = ("signoff", "expected_rom")


def digest(path: Path, algorithm: str = "sha256") -> str:
    return hashlib.new(algorithm, path.read_bytes()).hexdigest()


def _compiler_identity(compiler: dict) -> dict:
    return {k: v for k, v in compiler.items() if k not in SIGNOFF_COMPILER_FIELDS}


def _identity(lock: dict) -> dict:
    return {**{k: v for k, v in lock.items() if k not in UNHASHED_LOCK_KEYS},
            "compiler": _compiler_identity(lock["compiler"])}


def lock_digest(lock: dict) -> str:
    """Digest the build's inputs, not its provenance metadata or output assertions."""
    return hashlib.sha256(json.dumps(_identity(lock), sort_keys=True).encode()).hexdigest()


def _lock_digest_matches(lock: dict, record: dict) -> bool:
    return record.get("lock_sha256") == lock_digest(lock)


def load_lock(path: Path = LOCK_PATH) -> dict:
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("schema_version") != 1 or lock.get("build") != "reference":
        raise ValueError("unsupported expansion lock schema/build")
    source = lock["source"]
    if (source["url"] != "https://github.com/rh-hideout/pokeemerald-expansion.git"
            or not re.fullmatch(r"expansion/\d+\.\d+\.\d+", source["tag"])
            or not re.fullmatch(r"[0-9a-f]{40}", source["commit"])):
        raise ValueError("invalid source URL/tag/commit")
    compiler = lock["compiler"]
    if (compiler["status"] not in {"provisional", "approved"}
            or not compiler["path"] or not compiler["version"]
            or not re.fullmatch(r"[0-9a-f]{64}", compiler["sha256"])):
        raise ValueError("invalid compiler identity")
    if not lock["config_headers"]:
        raise ValueError("empty config header manifest")
    for name, sha in lock["config_headers"].items():
        if (not re.fullmatch(r"include/config/[A-Za-z0-9_]+\.h", name)
                or not re.fullmatch(r"[0-9a-f]{64}", sha)):
            raise ValueError("invalid config header path/hash")
    expected_rom = lock.get("expected_rom")
    if (not isinstance(expected_rom, dict) or set(expected_rom) != {"sha1", "md5", "size"}
            or not re.fullmatch(r"[0-9a-f]{40}", expected_rom["sha1"])
            or not re.fullmatch(r"[0-9a-f]{32}", expected_rom["md5"])
            or not isinstance(expected_rom["size"], int) or expected_rom["size"] < 1):
        raise ValueError("invalid expected_rom")
    if (compiler["host"] != "Linux" or compiler["ssh_alias"] != "hgbox"
            or lock["host_patches"] != []
            or not lock["host_toolchain"]["packages"]):
        raise ValueError("unsupported host or source patches")
    if lock["make_variables"] != {
        "BUILD": "emerald", "DEBUG": "0", "RELEASE": "0", "LTO": "0", "TEST": "0",
    } or lock["make_targets"] != ["all", "syms"]:
        raise ValueError("unsupported make flags/targets")
    return lock


def run(argv, cwd: Path, env: dict, deadline: float, source: str | None = None) -> str:
    """Bound the whole run; kill only this command's process tree on timeout."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("expansion deadline expired")
    argv = [str(x) for x in argv]
    argv[0] = shutil.which(argv[0], path=env.get("PATH", "")) or argv[0]
    print(f"[expansion] {argv!r}", flush=True)
    process = subprocess.Popen(
        [str(x) for x in argv], cwd=cwd, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", start_new_session=os.name != "nt",
    )
    try:
        output, _ = process.communicate(source, timeout=remaining)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate(timeout=15)
        print(output[-12000:], flush=True)
        raise
    if process.returncode:
        log = ROOT / ".cache" / f"expansion-failure-{time.time_ns()}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(output, encoding="utf-8")
        raise ValueError(f"command failed ({process.returncode}): {argv!r}\n{output[-12000:]}")
    return output.strip()


def output_path(path: Path) -> Path:
    result = path.resolve()
    if (OUTPUTS.resolve() != ROOT.resolve() / ".cache/expansion-output"
            or not result.is_relative_to(OUTPUTS.resolve()) or result == OUTPUTS.resolve()):
        raise ValueError(f"output must be beneath {OUTPUTS}")
    return result


def preflight(lock: dict, cwd: Path, env: dict, deadline: float) -> dict:
    names = ("bash", "make", "gcc", "g++", "perl", "pkg-config", "git")
    missing = [name for name in names if not shutil.which(name, path=env.get("PATH", ""))]
    if missing:
        raise ValueError("missing host tools: " + ", ".join(missing)
                         + "; libpng and zlib development headers/libraries also required")
    compiler = Path(lock["compiler"]["path"])
    if not compiler.is_file() or digest(compiler) != lock["compiler"]["sha256"]:
        raise ValueError("pinned ARM compiler missing or sha256 mismatch")
    version = run([compiler, "--version"], cwd, env, deadline)
    if version != lock["compiler"]["version"]:
        raise ValueError("ARM compiler version mismatch")
    host = lock["host_toolchain"]
    if Path("/etc/os-release").read_text() != host["distro"]:
        raise ValueError("Linux distribution differs from lock")
    for name, expected in host["packages"].items():
        actual = run(["dpkg-query", "-W", "-f=${Version}", name], cwd, env, deadline)
        if actual != expected:
            raise ValueError(f"host package version mismatch: {name}")
    for name, identity in host["tools"].items():
        if (digest(Path(identity["path"])) != identity["sha256"]
                or run([identity["path"], "--version"], cwd, env, deadline) != identity["version"]):
            raise ValueError(f"host tool identity mismatch: {name}")
    versions = {name: run([shutil.which(name, path=env["PATH"]), "--version"],
                          cwd, env, deadline) for name in names}
    versions["arm-none-eabi-gcc"] = version
    versions["host_binaries"] = {
        name: {"path": shutil.which(name, path=env["PATH"]),
               "sha256": digest(Path(shutil.which(name, path=env["PATH"])))} for name in names}
    versions["python3"] = run(["bash", "-c", "python3 --version"], cwd, env, deadline)
    try:
        run(["pkg-config", "--exists", "libpng", "zlib"], cwd, env, deadline)
        # Reference both libraries so link resolution is exercised, not just headers.
        probe = cwd / "host-png-probe.exe"
        run(["gcc", "-x", "c", "-", "-o", probe, "-lpng", "-lz"], cwd, env, deadline,
            '#include <png.h>\n#include <zlib.h>\n'
            'int main(void){return !png_access_version_number() || !zlibVersion();}\n')
        run([probe], cwd, env, deadline)
        probe.unlink()
    except ValueError as error:
        raise ValueError(f"missing/unusable libpng or zlib (pkg-config, headers, link): {error}") from error
    return versions


def checkout(lock: dict, env: dict, deadline: float) -> Path:
    source = lock["source"]
    target = CACHE / source["commit"]
    if target.resolve() != ROOT.resolve() / ".cache/expansion" / source["commit"]:
        raise ValueError("redirected source cache refused")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        run(["git", "clone", "--depth", "1", "--branch", source["tag"],
             "--single-branch", "--config", "core.autocrlf=false", source["url"], target],
            ROOT, env, deadline)
    if not (target / ".git").is_dir() or (target / ".git").is_symlink():
        raise ValueError("source cache is not a dedicated clone")
    prefix = ["git", "-C", target]
    top = run(prefix + ["rev-parse", "--show-toplevel"], ROOT, env, deadline)
    if Path(top).resolve() != target.resolve():
        raise ValueError("source cache git root mismatch")
    for ref in ("HEAD", source["tag"] + "^{commit}"):
        if run(prefix + ["rev-parse", ref], ROOT, env, deadline) != source["commit"]:
            raise ValueError("source commit/tag mismatch")
    if run(prefix + ["status", "--porcelain"], ROOT, env, deadline):
        raise ValueError("source has changes; refusing to discard them")
    # Only ignored build outputs in this verified, dedicated clone are removed.
    run(prefix + ["clean", "-fdX"], ROOT, env, deadline)
    actual = {p.relative_to(target).as_posix(): digest(p)
              for p in sorted((target / "include/config").glob("*.h"))}
    if actual != lock["config_headers"]:
        raise ValueError("config header inventory/hash mismatch")
    return target


def make_receipt(lock: dict, out: Path, versions: dict, elapsed: float) -> dict:
    rom = out / "pokeemerald.gba"
    return {
        "schema": SCHEMA, "lock_sha256": lock_digest(lock), "source": lock["source"],
        "compiler": lock["compiler"], "make_variables": lock["make_variables"],
        "make_targets": lock["make_targets"], "tool_versions": versions,
        "generated": datetime.now(UTC).isoformat(), "host": platform.platform(),
        "elapsed_seconds": elapsed,
        "files": {name: {"sha256": digest(out / name), "size": (out / name).stat().st_size}
                  for name in ARTIFACTS},
        "rom": {"sha1": digest(rom, "sha1"), "md5": digest(rom, "md5"),
                "size": rom.stat().st_size},
    }


def check_output(lock: dict, out: Path, strict: bool = False) -> None:
    receipt = out / "receipt.json"
    if not receipt.is_file():
        raise ValueError("missing build receipt (UNVERIFIED)")
    record = json.loads(receipt.read_text(encoding="utf-8"))
    recorded = record.get("compiler")
    if (record.get("schema") != SCHEMA
            or not _lock_digest_matches(lock, record)
            or any(record.get(key) != lock[key]
                   for key in ("source", "make_variables", "make_targets"))
            or not isinstance(recorded, dict)
            or _compiler_identity(recorded) != _identity(lock)["compiler"]
            or set(record.get("files") or {}) != set(ARTIFACTS)
            or not record.get("tool_versions") or not record.get("generated")
            or not isinstance(record.get("files"), dict)
            or not record.get("host")):
        raise ValueError("receipt does not match lock/schema")
    for name in ARTIFACTS:
        path = out / name
        if (not path.is_file() or not path.stat().st_size
                or record["files"][name] != {"sha256": digest(path), "size": path.stat().st_size}):
            raise ValueError(f"missing/empty/changed artifact: {name}")
    rom = out / "pokeemerald.gba"
    actual = {"sha1": digest(rom, "sha1"), "md5": digest(rom, "md5"), "size": rom.stat().st_size}
    if record["rom"] != actual:
        raise ValueError("ROM receipt mismatch")
    if lock["expected_rom"] != actual:
        raise ValueError(f"ROM differs from the lock's expected_rom: {actual}")
    builder = record["tool_versions"].get("builder_sha256")
    if builder and builder != digest(Path(__file__)):
        message = f"receipt was written by a different build_expansion.py: {builder}"
        if strict:
            raise ValueError(message)
        print(f"WARNING: {message}", flush=True)


def remote_build(lock: dict, args, out: Path) -> None:
    """Each remote invocation has its own fresh directory; never delete user data."""
    if args.host != lock["compiler"]["ssh_alias"]:
        raise ValueError("host alias differs from lock")
    if out.exists():
        raise ValueError("output already exists; choose a new directory")
    relative = f"slink-exp/{lock['source']['commit']}/{uuid.uuid4().hex}"
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", args.host]
    env = os.environ.copy()
    deadline = time.monotonic() + args.timeout_minutes * 60 + 120
    # Only generated fixed-format paths are interpolated into remote shell code.
    run(ssh + [f"mkdir -p ~/{relative}/tools ~/{relative}/data"], ROOT, env, deadline)
    run(["scp", "-q", str(Path(__file__)), f"{args.host}:{relative}/tools/build_expansion.py"],
        ROOT, env, deadline)
    run(["scp", "-q", str(LOCK_PATH), f"{args.host}:{relative}/data/gen3_exp_sources.lock.json"],
        ROOT, env, deadline)
    command = (f"cd ~/{relative} && timeout --signal=TERM --kill-after=15s "
               f"{int(args.timeout_minutes * 60 + 30)}s python3 tools/build_expansion.py "
               f"--linux-worker --jobs {args.jobs} --timeout-minutes {args.timeout_minutes}")
    print(f"[expansion] remote directory: ~/{relative}", flush=True)
    run(ssh + [command], ROOT, env, deadline)
    remote_out = f"{relative}/.cache/expansion-output/reference"
    out.mkdir(parents=True)
    for name in ARTIFACTS:
        run(["scp", "-q", f"{args.host}:{remote_out}/{name}", str(out / name)], ROOT, env, deadline)
    # Transfer receipt last. A failed transfer cannot leave a valid completion marker.
    run(["scp", "-q", f"{args.host}:{remote_out}/receipt.json", str(out / "receipt.json")],
        ROOT, env, deadline)
    check_output(lock, out, strict=args.strict)
    print(f"PASS: copied and verified {out}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", choices=["reference"], default="reference")
    parser.add_argument("--output", type=Path, default=OUTPUTS / "reference")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="fail rather than warn when the receipt's builder_sha256 differs")
    parser.add_argument("--host", choices=["hgbox"])
    parser.add_argument("--linux-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--jobs", type=int, default=12)
    parser.add_argument("--timeout-minutes", type=float, default=40)
    args = parser.parse_args()
    try:
        lock = load_lock()
        out = output_path(args.output)
        if args.check:
            check_output(lock, out, strict=args.strict)
            print("PASS: offline lock/receipt/artifact integrity; no rebuild performed")
            return 0
        if args.jobs < 1 or args.timeout_minutes <= 0:
            raise ValueError("jobs and timeout must be positive")
        if args.host:
            if args.preflight:
                raise ValueError("remote --preflight is not supported; --host performs a build")
            remote_build(lock, args, out)
            return 0
        if not args.linux_worker or platform.system() != "Linux":
            raise ValueError("native Windows builds unsupported; use --host hgbox")
        start = time.monotonic()
        deadline = start + args.timeout_minutes * 60
        env = os.environ.copy()
        env["PATH"] = "/usr/bin:/bin"
        for key in ("CC", "CXX", "CFLAGS", "CPPFLAGS", "LDFLAGS", "MAKEFLAGS", "DEVKITARM",
                    "CPATH", "LIBRARY_PATH", "PKG_CONFIG_PATH", "GCC_EXEC_PREFIX",
                    "COMPILER_PATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"):
            env.pop(key, None)
        scratch = ROOT / ".cache/expansion-preflight"
        scratch.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(scratch)
        versions = preflight(lock, scratch, env, deadline)
        if args.preflight:
            print("PASS: host preflight; expansion build not attempted")
            return 0
        if out.exists():
            raise ValueError("output already exists; choose a new directory")
        source = checkout(lock, env, deadline)
        argv = ["make", f"-j{args.jobs}"] + [f"{k}={v}" for k, v in lock["make_variables"].items()]
        versions["make_argv"] = argv + lock["make_targets"]
        versions["builder_sha256"] = digest(Path(__file__))
        versions["working_directory"] = str(ROOT)
        run(argv + lock["make_targets"], source, env, deadline)
        for name in ARTIFACTS:
            if not (source / name).is_file() or not (source / name).stat().st_size:
                raise ValueError(f"build omitted {name}")
        out.mkdir(parents=True)
        for name in ARTIFACTS:
            shutil.copyfile(source / name, out / name)
        receipt = make_receipt(lock, out, versions, time.monotonic() - start)
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        check_output(lock, out)
        print(f"PASS: {out}; ROM sha1={receipt['rom']['sha1']}")
        return 0
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired, TimeoutError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
