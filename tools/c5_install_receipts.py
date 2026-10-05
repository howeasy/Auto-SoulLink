#!/usr/bin/env python3
"""Install the C-5 receipt packet into the tree, pinned by its own manifest (G2-C5-WIRE).

    tools/c5_runner.py run                 # ~20 min, needs EmuHawk; the coordinator runs that at freeze
    tools/c5_install_receipts.py --dry-run # what would be installed, from which digest
    tools/c5_install_receipts.py           # install

`tools/c5_runner.py run` writes each PASS cell under `<lane>/out/<digest12>/receipts/c5/`:
a `*.manifest.json` per cell plus the `duo_*_result.txt` receipts that manifest pins by file name.
This copies that packet into `tests/fixtures/gen2/receipts/c5/` and writes `install.json` pinning
every installed byte by sha256, so `tools/verify_gen2_release.py --release-evidence` can judge it
without the lane.

Three refusals, all RED, none a skip:

  * the source packet does not exist (nothing was run, or the digest moved);
  * the packet's own `code_digest` is not the CURRENT production code digest -- evidence earned on
    other production code is not evidence for this tree, so installing it would only move the
    staleness from one error to another;
  * a manifest pins a receipt the packet does not contain, or names a cell this release does not
    require (an install must not smuggle in extra or foreign cells).

The install is atomic-ish: files are written into a temp dir beside the destination and moved into
place only after every source byte has been read and hashed, so a failure part-way leaves the
previous packet (or none) rather than a half one.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import c5_runner  # noqa: E402
import gen2_code_digest as code_digest  # noqa: E402
import verify_gen2_release as verifier  # noqa: E402

SCHEMA = verifier.C5_INSTALL_SCHEMA
DEFAULT_LANE = Path(os.environ.get("SLINK_C5_ROOT", "F:/slink-work/lanes/g2r-live"))


class InstallError(RuntimeError):
    """A refusal. The message is the RED line; it is never downgraded to a warning."""


def source_dir(lane: Path, digest: str) -> Path:
    return lane / "out" / digest[:12] / "receipts" / "c5"


def collect(folder: Path) -> dict[str, Path]:
    """Every file the packet installs: each manifest, plus each receipt that manifest pins by name.

    `_c5_manifest_errors` resolves a pinned receipt as `folder / Path(rel).name`, so the installed
    packet is flat and the name is the identity. Collecting exactly the pinned set (plus the
    manifests) is what keeps an install reproducible and free of runner scratch files.
    """
    if not folder.is_dir():
        raise InstallError(f"{folder}: no C-5 packet; run `tools/c5_runner.py run` first")
    manifests = sorted(folder.glob("*.manifest.json"))
    if not manifests:
        raise InstallError(f"{folder}: no *.manifest.json; nothing PASSed, so there is nothing to install")
    files: dict[str, Path] = {}
    for manifest in manifests:
        files[manifest.name] = manifest
        try:
            pinned = json.loads(manifest.read_text(encoding="utf-8")).get("receipts") or {}
        except (OSError, ValueError) as exc:
            raise InstallError(f"{manifest.name}: unreadable manifest ({exc})") from exc
        for rel in pinned:
            name = Path(str(rel)).name
            if name in files:
                continue
            source = folder / name
            if not source.is_file():
                raise InstallError(f"{manifest.name}: pins {name}, which the packet does not contain")
            files[name] = source
    return files


def plan(lane: Path, dest: Path, digest: str) -> dict:
    """The whole install, validated but not performed. Returns the manifest that would be written."""
    folder = source_dir(lane, digest)
    if not folder.is_dir():
        raise InstallError(f"{folder}: no C-5 packet at this code digest; run `tools/c5_runner.py run` first")
    summary = folder.parent.parent / "summary.json"   # folder = out/<d12>/receipts/c5
    if summary.is_file():
        try:
            recorded = json.loads(summary.read_text(encoding="utf-8")).get("code_digest")
        except (OSError, ValueError) as exc:
            raise InstallError(f"{summary}: unreadable ({exc})") from exc
        if recorded != digest:
            raise InstallError(f"STALE: {summary} records code digest {str(recorded)[:12]}, the current "
                               f"production digest is {digest[:12]}; re-run tools/c5_runner.py run "
                               "(it needs EmuHawk) before installing")
    files = collect(folder)
    # c5_runner writes the manifest as cid.replace("/", "__"), so the file name is not a cell id:
    # map it back before comparing against C5_CELLS, or every real cell reads as foreign.
    cells = sorted(name[:-len(".manifest.json")].replace("__", "/")
                   for name in files if name.endswith(".manifest.json"))
    unknown = [cell for cell in cells if cell not in verifier.C5_CELLS]
    if unknown:
        raise InstallError(f"the packet carries cell(s) this release does not require: {unknown}; "
                           f"required cells are {sorted(verifier.C5_CELLS)}")
    pins = {name: c5_runner.lf_sha256(path) for name, path in sorted(files.items())}
    return {"schema": SCHEMA, "code_digest": digest, "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": str(folder).replace("\\", "/"), "cells": cells, "files": pins}


def install(lane: Path, dest: Path, digest: str, *, dry_run: bool = False) -> dict:
    manifest = plan(lane, dest, digest)
    if dry_run:
        return manifest
    dest.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".c5-install-", dir=str(dest.parent)))
    try:
        for name, path in sorted(collect(source_dir(lane, digest)).items()):
            shutil.copy2(path, staging / name)
        (staging / verifier.C5_INSTALL_MANIFEST).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        # Replace only what the manifest pins, plus the manifest itself: an old packet's leftovers
        # are removed so a retired cell cannot survive as an unreferenced file.
        wanted = set(manifest["files"]) | {verifier.C5_INSTALL_MANIFEST}
        for existing in dest.iterdir():
            if existing.is_file() and existing.name not in wanted:
                existing.unlink()
        for name in sorted(wanted):
            shutil.move(str(staging / name), str(dest / name))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lane", type=Path, default=DEFAULT_LANE, help="the c5_runner lane root")
    ap.add_argument("--dest", type=Path, default=None,
                    help=f"install destination (default: {verifier.C5_RECEIPTS})")
    ap.add_argument("--dry-run", action="store_true", help="report the plan, write nothing")
    args = ap.parse_args(argv)
    dest = args.dest or (ROOT / verifier.C5_RECEIPTS)
    try:
        digest = code_digest.head_digest(ROOT)
    except (OSError, Exception) as exc:  # git failures raise several types
        print(f"RED  cannot compute the current production code digest: {exc}", file=sys.stderr)
        return 1
    try:
        manifest = install(args.lane, dest, digest, dry_run=args.dry_run)
    except InstallError as exc:
        print(f"RED  {exc}", file=sys.stderr)
        return 1
    verb = "would install" if args.dry_run else "installed"
    print(f"C-5: {verb} {len(manifest['cells'])} cell(s), {len(manifest['files'])} file(s) at code digest "
          f"{digest[:12]}")
    print(f"C-5: source {manifest['source']}")
    for name, sha in manifest["files"].items():
        print(f"  {sha[:12]}  {name}")
    if not args.dry_run:
        print(f"C-5: manifest {verifier.C5_INSTALL_MANIFEST} in {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
