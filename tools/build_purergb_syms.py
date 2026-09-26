"""
tools/build_purergb_syms.py — M0/P1: locked, verified canonical pureRGB build

Drives `make` (via w64devkit) + RGBDS against the pinned pureRGB commit in
data/purergb_sources.lock.json, sha1-verifies all three ROM outputs against
the lock, and — only on a full match — publishes .sym/.map files to
data/purergb/ plus a build_provenance.json record. On any mismatch it raises
and writes nothing: a locked build is either exactly reproduced or it does
not count.

Why `make` instead of driving rgbasm/rgblink directly (contrast with
tools/build_pret_syms.py): pureRGB's Makefile compiles ~200 graphics/audio
assets and three ROM variants from one source tree with per-target rgbasm
flags: reimplementing that dependency graph would just be a worse Makefile.
`make` needs GNU make + a C compiler for its own tools/ (pkmncompress etc),
which is what w64devkit provides on Windows.

Usage:
    python tools/build_purergb_syms.py                      # clone + build fresh
    python tools/build_purergb_syms.py --repo-dir PATH       # reuse an existing clone
    python tools/build_purergb_syms.py --rgbds-bin PATH      # skip RGBDS auto-install
    python tools/build_purergb_syms.py --w64devkit-bin PATH  # skip w64devkit auto-install
    python tools/build_purergb_syms.py --check               # build + compare, publish nothing

Output: data/purergb/{pokered,pokeblue,pokegreen}.{sym,map}
        data/purergb/build_provenance.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import platform
import subprocess
import sys
import zlib
from datetime import UTC, datetime

from _build_tools_bootstrap import ensure_rgbds, ensure_w64devkit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
LOCK_PATH = DATA_DIR / "purergb_sources.lock.json"
PURERGB_CACHE = REPO_ROOT / ".cache" / "purergb"
OUT_DIR = DATA_DIR / "purergb"
PROVENANCE_PATH = OUT_DIR / "build_provenance.json"

PROVENANCE_SCHEMA = "purergb-build-provenance-v1"

RGBDS_BINARIES = ("rgbasm", "rgblink", "rgbfix", "rgbgfx")
DEVKIT_BINARIES = ("make", "gcc")


def load_lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _write_json(path: pathlib.Path, data: dict) -> None:
    """Write `data` as pretty JSON, atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


def verify_source(repo_dir: pathlib.Path | None, lock: dict) -> pathlib.Path:
    """Clone (or reuse) the pureRGB repo and check out the locked commit.
    Refuses a dirty tree — `git status --porcelain` already excludes the
    gitignored build outputs (roms, .sym/.map, .o, compiled gfx), so any
    line it reports is real, non-build dirt."""
    url = lock["source"]["url"]
    commit = lock["source"]["commit"]
    repo = repo_dir if repo_dir is not None else PURERGB_CACHE

    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        print(f"[purergb] git clone {url} -> {repo}", file=sys.stderr)
        subprocess.run(["git", "clone", url, str(repo)], check=True)

    status = _git(repo, "status", "--porcelain").stdout
    if status.strip():
        raise RuntimeError(
            f"{repo} has uncommitted changes (build outputs are gitignored, so this "
            f"is real dirt) — refusing to build from a dirty tree:\n{status}"
        )

    _git(repo, "checkout", commit)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if head != commit:
        raise RuntimeError(f"checked out HEAD {head} != locked commit {commit}")
    return repo


def _binary_name(name: str) -> str:
    return f"{name}.exe" if platform.system() == "Windows" else name


def _sha256(path: pathlib.Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _lf(data: bytes) -> bytes:
    """rgbds on Windows writes CRLF; the repo pins .sym/.map as LF (.gitattributes).

    The --check comparison, the published bytes and the provenance hashes must all be taken
    on LF or a Windows rebuild reports drift against its own committed output and stamps
    CRLF hashes into build_provenance.json — the bug c411b2f3 had to repair by hand.
    build_purergb_overlay.py:135-138 normalises for the same reason.
    """
    return data.replace(b"\r\n", b"\n")


def _toolchain_record(rgbds_bin: pathlib.Path, devkit_bin: pathlib.Path, lock: dict) -> dict:
    return {
        "rgbds": {
            "version": lock["rgbds_version"],
            "binaries": {
                name: _sha256(rgbds_bin / _binary_name(name)) for name in RGBDS_BINARIES
            },
        },
        "w64devkit": {
            "version": lock["w64devkit_version"],
            "binaries": {
                name: _sha256(devkit_bin / _binary_name(name)) for name in DEVKIT_BINARIES
            },
        },
    }


def _rom_facts(data: bytes, sha1: str) -> dict:
    return {
        "sha1": sha1,
        "md5": hashlib.md5(data).hexdigest(),
        "header_crc": data[0x14E:0x150].hex().upper(),
        "crc32": format(zlib.crc32(data), "08X"),
        "title": data[0x134:0x143].rstrip(b"\x00").decode("ascii", "replace"),
    }


def build_rom_syms(
    *,
    repo_dir: pathlib.Path | None = None,
    rgbds_bin: pathlib.Path | None = None,
    w64devkit_bin: pathlib.Path | None = None,
    check: bool = False,
) -> int:
    lock = load_lock()
    repo = verify_source(repo_dir, lock)

    rgbds_bin = rgbds_bin or ensure_rgbds(lock["rgbds_version"])
    devkit_bin = w64devkit_bin or ensure_w64devkit()

    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(rgbds_bin), str(devkit_bin), env.get("PATH", "")])

    # Windows CreateProcess does not do a PATH search + PATHEXT resolution the way a
    # shell does, so argv[0] needs the exact binary path; everything make shells out
    # to (rgbasm, rgblink, sh, gcc, ...) still resolves through `env["PATH"]` above.
    make_exe = str(devkit_bin / _binary_name("make"))
    cmd = [make_exe, "-j4", *lock["make_targets"]]
    print(f"[purergb] {' '.join(cmd)}  (cwd={repo})", file=sys.stderr)
    result = subprocess.run(cmd, cwd=str(repo), env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"make failed with exit code {result.returncode}")

    mismatches: list[str] = []
    rom_facts: dict[str, dict] = {}
    for key, spec in lock["outputs"].items():
        rom_path = repo / spec["filename"]
        if not rom_path.exists():
            mismatches.append(f"{key}: {rom_path} was not produced by the build")
            continue
        data = rom_path.read_bytes()
        sha1 = hashlib.sha1(data).hexdigest()
        if sha1 != spec["sha1"]:
            mismatches.append(f"{key}: sha1 {sha1} != locked {spec['sha1']}")
            continue
        rom_facts[key] = _rom_facts(data, sha1)

    if mismatches:
        raise RuntimeError(
            "build does not match data/purergb_sources.lock.json — publishing nothing:\n"
            + "\n".join(mismatches)
        )
    print("[purergb] all three ROM sha1s match the lock", file=sys.stderr)

    sym_files = {
        f"{key}.{ext}": repo / f"{key}.{ext}" for key in lock["outputs"] for ext in ("sym", "map")
    }

    if check:
        drift = [
            name
            for name, src in sym_files.items()
            if not (OUT_DIR / name).exists()
            or _lf((OUT_DIR / name).read_bytes()) != _lf(src.read_bytes())
        ]
        if drift:
            print(f"[purergb] --check: drift from committed data/purergb/: {drift}", file=sys.stderr)
            return 1
        print(
            "[purergb] --check: build reproduces the committed .sym/.map byte-for-byte",
            file=sys.stderr,
        )
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    symbol_hashes: dict[str, str] = {}
    for name, src in sym_files.items():
        data = _lf(src.read_bytes())
        (OUT_DIR / name).write_bytes(data)
        symbol_hashes[name] = hashlib.sha256(data).hexdigest()

    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": lock["source"],
        "toolchain": _toolchain_record(rgbds_bin, devkit_bin, lock),
        "command": " ".join(["make", "-j4", *lock["make_targets"]]),
        "roms": rom_facts,
        "symbols": symbol_hashes,
    }
    _write_json(PROVENANCE_PATH, provenance)
    print(
        f"[purergb] published {len(sym_files)} sym/map files + provenance -> {OUT_DIR}",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=pathlib.Path, default=None,
                        help="reuse an existing pureRGB clone instead of cloning into .cache/purergb/")
    parser.add_argument("--rgbds-bin", type=pathlib.Path, default=None,
                        help="dir containing rgbasm/rgblink/rgbfix/rgbgfx (skips auto-install)")
    parser.add_argument("--w64devkit-bin", type=pathlib.Path, default=None,
                        help="dir containing make/gcc (skips auto-install)")
    parser.add_argument("--check", action="store_true",
                        help="build and compare against the lock + committed data/purergb/, "
                             "write nothing, exit non-zero on any drift")
    args = parser.parse_args()

    try:
        return build_rom_syms(
            repo_dir=args.repo_dir,
            rgbds_bin=args.rgbds_bin,
            w64devkit_bin=args.w64devkit_bin,
            check=args.check,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
