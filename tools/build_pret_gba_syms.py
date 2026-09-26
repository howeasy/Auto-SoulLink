"""Build and hash-verify pret FRLG US 1.0 before publishing symbols.

Usage: python tools/build_pret_gba_syms.py [--check] [--timeout-minutes 40]
--check is an OFFLINE lock/receipt check, not a build or reproducibility proof.
The real build resets and cleans ONLY the two dedicated .cache/pret clones.
No ROM is published. A failed build never publishes new symbols or a receipt.

The pinned pokefirered INSTALL.md requires host gcc/g++, make, bash, perl,
ARM binutils and libpng development headers/libraries (including zlib).
Windows reuses ensure_w64devkit(), but that bundle alone is insufficient:
provide Git Bash with --bash, ARM binutils with --binutils-bin, and host-
compiler-compatible libpng/zlib via CPATH/LIBRARY_PATH (or an MSYS2 toolchain
via SLINK_W64DEVKIT_BIN). These dependencies are recorded, not version-pinned;
the locked ROM hashes are the final reproducibility gate. No modern compiler
or revision-1 target is used. On Unix supply the INSTALL.md system packages.

Source instructions at the exact lock commits:
https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/INSTALL.md
https://github.com/pret/agbcc/blob/da598c1d918402c42c0c0d7128ba14567f3175e9/build.sh
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
from datetime import UTC, datetime
from pathlib import Path

from _build_tools_bootstrap import W64DEVKIT_VERSION, ensure_w64devkit

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/pret"
LOCK_PATH = ROOT / "data/gen3_sources.lock.json"
OUT = ROOT / "data/gen3/pret"
SCHEMA = "gen3-pret-build-provenance-v1"
FILES = tuple(f"{name}.{ext}" for name in ("pokefirered", "pokeleafgreen")
              for ext in ("sym", "map"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_lock() -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock["schema_version"] != 1 or lock["w64devkit_version"] != W64DEVKIT_VERSION:
        raise ValueError("unsupported lock schema or w64devkit bootstrap version")
    for key in ("source", "agbcc"):
        if not re.fullmatch(r"[0-9a-f]{40}", lock[key]["commit"]):
            raise ValueError(f"invalid {key} commit")
    if lock["make_variables"] != {"GAME_REVISION": "0", "MODERN": "0"}:
        raise ValueError("only base revision 0 / agbcc builds are admitted")
    if set(lock["outputs"]) != {"pokefirered", "pokeleafgreen"}:
        raise ValueError("expected exactly FireRed and LeafGreen")
    for name, version in (("pokefirered", "FIRERED"), ("pokeleafgreen", "LEAFGREEN")):
        spec = lock["outputs"][name]
        if (spec["filename"] != f"{name}.gba" or spec["game_version"] != version
                or not re.fullmatch(r"[0-9a-f]{40}", spec["sha1"])):
            raise ValueError(f"invalid output specification: {name}")
    return lock


def check_receipt(lock: dict) -> None:
    receipt = OUT / "provenance.json"
    if not receipt.exists():
        if any((OUT / name).exists() for name in FILES):
            raise ValueError("symbol files exist without provenance")
        print("[gen3] lock valid; no published build (UNVERIFIED)", flush=True)
        return
    record = json.loads(receipt.read_text(encoding="utf-8"))
    if (record["schema"] != SCHEMA or record["source"] != lock["source"]
            or record["agbcc"] != lock["agbcc"] or set(record["files"]) != set(FILES)
            or record["roms"] != {s["filename"]: s["sha1"] for s in lock["outputs"].values()}
            or not record["host"] or not record["generated"] or not record["toolchain"]):
        raise ValueError("provenance does not match the lock/schema")
    for name in FILES:
        path = OUT / name
        if not path.is_file() or not path.stat().st_size or sha256(path) != record["files"][name]:
            raise ValueError(f"published file missing/empty/hash mismatch: {name}")
    print("[gen3] lock and published file hashes valid; no rebuild performed", flush=True)


def run(phase: str, argv: list[str], cwd: Path, env: dict, *, source: str | None = None) -> str:
    print(f"[gen3] {phase}: {argv!r} (cwd={cwd})", flush=True)
    result = subprocess.run(argv, cwd=cwd, env=env, input=source, text=True,
                            encoding="utf-8", errors="replace", stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        # Preserve the exact final output lines, with a named failing phase.
        print(result.stdout[-12000:], end="", flush=True)
        raise RuntimeError(f"{phase} failed (exit {result.returncode})")
    print(f"[gen3] {phase}: OK", flush=True)
    return result.stdout


def checkout(name: str, spec: dict, env: dict) -> Path:
    repo = CACHE / name
    # Reject redirected paths before reset/clean; never reset a parent worktree.
    if repo.resolve() != ROOT.resolve() / ".cache" / "pret" / name:
        raise RuntimeError(f"redirected cache path refused: {repo}")
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        run(f"clone {name}", ["git", "-c", "core.autocrlf=false", "clone",
                            "--no-checkout", spec["url"], str(repo)], ROOT, env)
    if not (repo / ".git").is_dir() or (repo / ".git").is_symlink():
        raise RuntimeError(f"not a dedicated clone: {repo}")
    prefix = ["git", "-C", str(repo)]
    top = run(f"verify {name} root", prefix + ["rev-parse", "--show-toplevel"], ROOT, env)
    if Path(top.strip()).resolve() != repo.resolve():
        raise RuntimeError(f"unexpected git root: {top}")
    run(f"fetch {name} pin", prefix + ["fetch", spec["url"], spec["commit"]], ROOT, env)
    run(f"reset {name}", prefix + ["-c", "core.autocrlf=false", "reset", "--hard",
                                  spec["commit"]], ROOT, env)
    run(f"clean {name}", prefix + ["clean", "-fdx"], ROOT, env)
    head = run(f"verify {name} HEAD", prefix + ["rev-parse", "HEAD"], ROOT, env).strip()
    if head != spec["commit"]:
        raise RuntimeError(f"{name}: HEAD {head} != {spec['commit']}")
    return repo


def build(args: argparse.Namespace) -> None:
    lock = load_lock()
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Prevent caller make flags from silently changing the selected build.
    for name in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "GNUMAKEFLAGS"):
        env.pop(name, None)
    repo = checkout("pokefirered", lock["source"], env)
    agbcc = checkout("agbcc", lock["agbcc"], env)
    dirs = []
    if platform.system() == "Windows":
        print("[gen3] bootstrap w64devkit", flush=True)
        dirs.append(str(ensure_w64devkit()))
        # Git for Windows keeps bash/perl in usr/bin, not its PATH-facing cmd/.
        git = shutil.which("git")
        if git:
            git_usr = Path(git).resolve().parents[1] / "usr/bin"
            if (git_usr / "bash.exe").is_file():
                dirs.append(str(git_usr))
    if args.bash:
        dirs.insert(0, str(Path(args.bash).resolve().parent))
    if args.binutils_bin:
        dirs.insert(0, str(Path(args.binutils_bin).resolve()))
    elif env.get("DEVKITARM"):
        dirs.insert(0, str(Path(env["DEVKITARM"]) / "bin"))
    env.pop("DEVKITARM", None)  # All ARM utilities now resolve through PATH.
    env["PATH"] = os.pathsep.join([*dirs, env.get("PATH", "")])
    env["CC"], env["CXX"] = "gcc", "g++"
    names = ("bash", "make", "gcc", "g++", "perl", "arm-none-eabi-as",
             "arm-none-eabi-ar", "arm-none-eabi-ld", "arm-none-eabi-objcopy",
             "arm-none-eabi-objdump")
    binaries = {name: shutil.which(name, path=env["PATH"]) for name in names}
    if args.bash:
        binaries["bash"] = str(Path(args.bash).resolve())
    missing = [name for name, path in binaries.items() if not path or not Path(path).is_file()]
    if missing:
        raise RuntimeError("tool preflight: missing " + ", ".join(missing)
                           + "; w64devkit alone lacks ARM binutils and libpng/zlib; see --help")
    toolchain = {}
    for name, path in binaries.items():
        version = run(f"version {name}", [path, "--version"], agbcc, env)
        toolchain[name] = {"path": path, "sha256": sha256(Path(path)), "version": version.strip()}
    run("libpng/zlib link preflight", [binaries["gcc"], "-x", "c", "-", "-o",
        ".slink-png-check.exe", "-lpng", "-lz"], agbcc, env,
        source="#include <png.h>\n#include <zlib.h>\n"
               "int main(void) { return !png_access_version_number() || !zlibVersion(); }\n")
    # Relative install path is essential: upstream install.sh does not quote $1.
    run("build agbcc", [binaries["bash"], "./build.sh"], agbcc, env)
    run("install agbcc", [binaries["bash"], "./install.sh", "../pokefirered"], agbcc, env)
    installed = repo / "tools/agbcc"
    toolchain["agbcc_installed"] = {
        path.relative_to(installed).as_posix(): sha256(path)
        for path in sorted(installed.rglob("*")) if path.is_file()
    }
    if not toolchain["agbcc_installed"]:
        raise RuntimeError("agbcc install produced no files")
    commands = []
    for name, spec in lock["outputs"].items():
        # Separate invocations: the Makefile derives ROM/SYM from GAME_VERSION.
        argv = [binaries["make"], f"-j{args.jobs}", f"GAME_VERSION={spec['game_version']}",
                "GAME_REVISION=0", "GAME_LANGUAGE=ENGLISH", "MODERN=0", "COMPARE=0",
                "DINFO=0", "NODEP=0", spec["filename"], f"{name}.sym"]
        commands.append(argv)
        run(f"build {name}", argv, repo, env)
    roms = {}
    for spec in lock["outputs"].values():
        actual = hashlib.sha1((repo / spec["filename"]).read_bytes()).hexdigest()
        if actual != spec["sha1"]:
            raise RuntimeError(f"ROM verification: {spec['filename']} {actual} != {spec['sha1']}")
        roms[spec["filename"]] = actual
    # Read every output before touching the publish directory.
    payloads = {name: (repo / name).read_bytes() for name in FILES}
    if not all(payloads.values()):
        raise RuntimeError("empty symbol/map output")
    record = {
        "schema": SCHEMA, "generated": datetime.now(UTC).isoformat(),
        "host": {"system": platform.platform(), "machine": platform.machine(),
                 "node": platform.node(), "python": platform.python_version()},
        "source": lock["source"], "agbcc": lock["agbcc"], "toolchain": toolchain,
        "commands": commands, "roms": roms,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    # Receipt last: interruption cannot make a partial set pass --check.
    receipt = OUT / "provenance.json"
    receipt.unlink(missing_ok=True)
    for name, data in payloads.items():
        (OUT / name).write_bytes(data)
    receipt.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    check_receipt(lock)
    print("[gen3] published four symbol/map files and provenance; both ROM hashes match", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="offline lock/receipt validation only")
    parser.add_argument("--bash", help="path to bash executable (Git Bash or MSYS2 on Windows)")
    parser.add_argument("--binutils-bin", help="directory containing arm-none-eabi-* utilities")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout-minutes", type=float, default=40)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.jobs < 1 or not 0 < args.timeout_minutes <= 40:
        parser.error("jobs must be positive; timeout must be > 0 and <= 40 minutes")
    try:
        if args.check:
            check_receipt(load_lock())
        elif args.worker:
            build(args)
        else:
            # Bound everything, including bootstrap downloads and compiler descendants.
            cmd = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
            child = subprocess.Popen(cmd, start_new_session=os.name != "nt")
            try:
                return child.wait(timeout=args.timeout_minutes * 60)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], check=False)
                else:
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                raise RuntimeError("build stopped: time budget exhausted or interrupted") from None
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
