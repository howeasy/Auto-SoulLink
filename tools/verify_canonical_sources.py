"""Fail-closed, offline validation of pinned sources and complete R/B/Y build evidence.

Run tools/build_pret_syms.py --canonical --rom-dir <legal-dump-directory> first.
No missing dependency, source drift, changed symbol, or missing title is a skip.
This verifies build provenance; live emulator behavior remains a separate gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

try:
    from . import build_pret_syms as build
except ImportError:
    import build_pret_syms as build


def verify(*, rom_dir: pathlib.Path | None = None) -> dict:
    root = build.REPO_ROOT
    errors: list[str] = []
    passed: list[str] = []

    def check(label, condition):
        (passed if condition else errors).append(label)

    def file_hash(label, path, expected, algorithm="sha256"):
        if not path.is_file():
            errors.append(f"{label}: missing {path}")
            return False
        actual = hashlib.new(algorithm, path.read_bytes()).hexdigest()
        check(label, actual == expected)
        return actual == expected

    lock = build.load_lock()
    provenance = json.loads(build.PROVENANCE_FILE.read_text(encoding="utf-8"))
    memory = json.loads(build.OUT_FILE.read_text(encoding="utf-8"))
    rom_symbols = json.loads(build.ROM_SYMS_OUT.read_text(encoding="utf-8"))
    check("provenance schema", provenance.get("schema_version") == 1)
    file_hash("source lock hash", build.LOCK_FILE, provenance.get("source_lock_sha256"))
    required_artifacts = {"data/pret_syms.json", "data/pret_rom_syms.json"}
    artifacts = provenance.get("artifacts", {})
    check("complete generated artifact inventory", set(artifacts) == required_artifacts)
    for path in sorted(required_artifacts):
        file_hash(f"generated artifact hash: {path}", root / path, artifacts.get(path))
    sources = provenance.get("sources", {})
    check("complete source inventory", set(sources) == set(lock["sources"]) == set(memory))
    for name, pin in lock["sources"].items():
        record = sources.get(name, {})
        repo = build.PRET_CACHE / name
        try:
            build.verify_source(repo, pin["commit"])
            check(f"source pin and clean checkout: {name}", True)
            check(f"source tree: {name}", build.git_output(repo, "rev-parse", "HEAD^{tree}") == record.get("tree"))
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            errors.append(f"source pin and clean checkout: {name}: {exc}")
        check(f"recorded source commit: {name}", record.get("commit") == pin["commit"])
        expected_path = f".cache/pret-build/{name}/{name}.sym"
        check(f"raw memory symbol path: {name}", record.get("raw_memory_symbols_path") == expected_path)
        path = root / expected_path
        file_hash(f"raw memory symbol hash: {name}", path, record.get("raw_memory_symbols_sha256"))
        check(f"memory table digest: {name}", build.symbols_digest(memory.get(name, {})) == record.get("memory_symbols_sha256"))
        if path.is_file():
            check(f"source-derived memory symbols: {name}", build._parse_sym(path) == memory.get(name))

    expected_roms = lock["clean_roms"]
    records = provenance.get("roms", {})
    check("all three canonical ROMs present", set(records) == set(expected_roms) == set(rom_symbols)
          and set(expected_roms) == {"pokered", "pokeblue", "pokeyellow"})
    rom_dir = rom_dir if rom_dir is not None else root
    for name, pin in expected_roms.items():
        record = records.get(name, {})
        source = pin["source"]
        expected_commit = lock["sources"][source]["commit"]
        expected_rom_path = f".cache/pret/{source}/{name}.gbc"
        expected_sym_path = f".cache/pret/{source}/{name}.sym"
        check(f"full local build evidence: {name}", record.get("build_mode") == "full-local")
        check(f"ROM source binding: {name}", record.get("source") == source and record.get("source_commit") == expected_commit)
        check(f"built ROM path: {name}", record.get("built_rom_path") == expected_rom_path)
        check(f"raw ROM symbol path: {name}", record.get("raw_symbols_path") == expected_sym_path)
        file_hash(f"legal clean ROM SHA1: {name}", rom_dir / pin["filename"], pin["sha1"], "sha1")
        file_hash(f"full built ROM SHA1: {name}", root / expected_rom_path, pin["sha1"], "sha1")
        check(f"recorded canonical hashes: {name}", record.get("built_rom_sha1") == record.get("clean_rom_sha1") == pin["sha1"])
        try:
            check(f"source roms.sha1: {name}", build._expected_rom_sha1(build.PRET_CACHE / source).get(name) == pin["sha1"])
        except OSError as exc:
            errors.append(f"source roms.sha1: {name}: {exc}")
        sym_path = root / expected_sym_path
        file_hash(f"full raw symbol artifact hash: {name}", sym_path, record.get("raw_symbols_sha256"))
        table = rom_symbols.get(name, {})
        check(f"ROM symbol SHA1 binding: {name}", table.get("rom_sha1") == pin["sha1"])
        check(f"ROM symbol table digest: {name}", build.symbols_digest(table.get("symbols", {})) == record.get("rom_symbols_sha256"))
        check(f"full-build memory table digest: {name}", build.symbols_digest(memory.get(source, {})) == record.get("memory_symbols_sha256"))
        if sym_path.is_file():
            check(f"full-build memory agreement: {name}", build._parse_sym(sym_path) == memory.get(source))
            check(f"full-build ROM symbol agreement: {name}", build._parse_rom_sym(sym_path.read_text(encoding="utf-8")) == table.get("symbols"))

    tools = provenance.get("toolchain", {})
    expected_tools = {"rgbasm", "rgblink", "rgbfix", "rgbgfx", "make", "gcc", "sh"}
    check("complete build toolchain inventory", set(tools) == expected_tools)
    for name in sorted(expected_tools):
        record = tools.get(name, {})
        relative = record.get("path", "")
        if not relative:
            errors.append(f"missing toolchain record: {name}")
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            errors.append(f"invalid toolchain record path: {name}")
            continue
        if "/" not in relative:
            found = shutil.which(relative)
            if found:
                path = pathlib.Path(found)
        file_hash(f"toolchain binary hash: {name}", path, record.get("sha256"))
        check(f"recorded toolchain version: {name}", bool(record.get("version")))
        if name.startswith("rgb"):
            check(f"pinned RGBDS version: {name}", record.get("version") == f"{name} {lock['rgbds_version']}")
    return {"schema_version": 1, "status": "pass" if not errors else "fail",
            "checks_passed": len(passed), "failures": errors, "checks": passed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom-dir", type=pathlib.Path, default=build.REPO_ROOT)
    parser.add_argument("--json", action="store_true", help="print machine-readable evidence")
    args = parser.parse_args(argv)
    try:
        report = verify(rom_dir=args.rom_dir)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        report = {"schema_version": 1, "status": "fail", "checks_passed": 0,
                  "checks": [], "failures": [f"Missing or malformed canonical evidence: {exc}"]}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Canonical sources: {report['status'].upper()} ({report['checks_passed']} checks passed)")
        for failure in report["failures"]:
            print(f"FAIL: {failure}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
