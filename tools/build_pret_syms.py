"""Build pinned pret memory symbols and fully built, hash-verified R/B/Y ROM symbols.

The source lock is data/pret_sources.lock.json. Cached source drift is an error;
--update fetches only the locked commit. ROM symbols are never fetched from a moving
symbols branch. --rom-syms (or --canonical) invokes the source Makefiles, checks all
three complete binaries against legal local dumps, and publishes build provenance.

Usage: python tools/build_pret_syms.py --canonical --rom-dir <legal-ROM-directory>
GNU make, gcc and sh must be on PATH or in .cache/build-tools/w64devkit/bin.
RGBDS v1.0.1 satisfies the pinned sources' rgbdscheck.asm (>= 1.0.0).
No ROM bytes are published; outputs under data/ contain symbols/hashes only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

try:
    from ._build_tools_bootstrap import ensure_rgbds
except ImportError:
    from _build_tools_bootstrap import ensure_rgbds

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRET_CACHE = REPO_ROOT / ".cache" / "pret"
BUILD_DIR = REPO_ROOT / ".cache" / "pret-build"
DATA_DIR = REPO_ROOT / "data"
OUT_FILE = DATA_DIR / "pret_syms.json"
LOCK_FILE = DATA_DIR / "pret_sources.lock.json"
PROVENANCE_FILE = DATA_DIR / "pret_build_provenance.json"


def load_lock() -> dict:
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    if lock.get("schema_version") != 1:
        raise ValueError("Unsupported pret source lock schema")
    for name, spec in lock["sources"].items():
        if not re.fullmatch(r"[0-9a-f]{40}", spec["commit"]):
            raise ValueError(f"{name}: an exact 40-character source commit is required")
    return lock


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbols_digest(symbols: dict) -> str:
    return hashlib.sha256(json.dumps(symbols, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def git_output(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def verify_source(repo: pathlib.Path, commit: str) -> None:
    if git_output(repo, "rev-parse", "HEAD") != commit:
        raise RuntimeError(f"Source commit drift: {repo}; expected {commit}")
    if git_output(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError(f"Dirty canonical source checkout: {repo}")

# Each pret repo we want to build.
#   url:                git remote
#   variant_define:     -D flag passed to rgbasm (variant-specific ROM build flag).
#                       Doesn't affect WRAM section layout but pret requires it.
#   ram_files:          .asm files inside the repo that declare RAM sections.
#                       Used to filter layout.link to only sections our build can provide.
#   link_mode:          "dmg" → pass -d to rgblink (Game Boy flat 8KB WRAM).
#                       "cgb" → no flag (Game Boy Color banked WRAM).
PRET_REPOS = {
    "pokered": {
        "url": "https://github.com/pret/pokered.git",
        "variant_define": "_RED",
        "ram_files": ["ram/wram.asm", "ram/hram.asm", "ram/sram.asm", "ram/vram.asm"],
        "link_mode": "dmg",
        "preinclude": "includes.asm",
    },
    "pokeyellow": {
        "url": "https://github.com/pret/pokeyellow.git",
        "variant_define": None,
        "ram_files": ["ram/wram.asm", "ram/hram.asm", "ram/sram.asm", "ram/vram.asm"],
        "link_mode": "dmg",
        "preinclude": "includes.asm",
    },
    # Archipelago Red/Blue is built from Alchav's fork, NOT from pret — and the fork adds
    # ~121 lines of WRAM for AP item/event tracking, which shifts real addresses:
    # wCurMap +216, wPlayerID +216, wObtainedBadges +216, wEnemyMons -18, wBoxCount +11
    # (861 of 2171 shared symbols move). Cross-checked against AP's own client.py, which
    # reads CurrentMap at WRAM offset 0x1436 = bus 0xD436 — exactly what this build emits.
    # So an AP run needs its own profile; inheriting vanilla's addresses reads garbage.
    # The fork predates pret's includes.asm refactor, hence no preinclude.
    "alchav_pokered": {
        "url": "https://github.com/Alchav/pokered.git",
        "variant_define": "_RED",
        "ram_files": ["ram/wram.asm", "ram/hram.asm", "ram/sram.asm", "ram/vram.asm"],
        "link_mode": "dmg",
        "preinclude": None,
    },
    "pokecrystal": {
        "url": "https://github.com/pret/pokecrystal.git",
        "variant_define": None,
        "ram_files": ["ram/wram.asm", "ram/hram.asm", "ram/sram.asm", "ram/vram.asm"],
        "link_mode": "cgb",
        "preinclude": "includes.asm",
    },
    # Gold + Silver share a single pret repo (pokegold). One build produces
    # gold.sym; pokesilver_obj uses -D _SILVER but WRAM symbols are identical
    # since both games share the engine. Build once, the .sym is valid for both.
    "pokegold": {
        "url": "https://github.com/pret/pokegold.git",
        "variant_define": "_GOLD",
        "ram_files": ["ram/wram.asm", "ram/hram.asm", "ram/sram.asm", "ram/vram.asm"],
        "link_mode": "cgb",
        "preinclude": "includes.asm",
    },
}

# Layout-script section-name regex. Captures the quoted name only.
_SECTION_REF_RE = re.compile(r'^\s*"([^"]+)"\s*$')
_REGION_HEADER_RE = re.compile(r'^(WRAM[0X]?(?:\s+\$?[0-9A-Fa-f]+)?|VRAM(?:\s+\$?[0-9A-Fa-f]+)?|SRAM\s+\$?[0-9A-Fa-f]+|HRAM)\b')
_ROM_REGION_RE = re.compile(r'^(ROM[0X](?:\s+\$?[0-9A-Fa-f]+)?)\b')
# `org $...` directives — kept as-is (they pin section origins).
_ORG_RE = re.compile(r'^\s*org\s+\$[0-9A-Fa-f]+\s*$')


def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _clone_or_pull(name: str, url: str, *, update: bool) -> pathlib.Path:
    """Obtain the locked revision without resetting or cleaning an existing checkout."""
    pin = load_lock()["sources"][name]
    if url != pin["url"]:
        raise RuntimeError(f"{name}: source URL differs from lock")
    repo = PRET_CACHE / name
    if repo.exists():
        verify_source(repo, pin["commit"])
        if update:
            _git(repo, "fetch", "--depth=1", url, pin["commit"])
        return repo

    PRET_CACHE.mkdir(parents=True, exist_ok=True)
    print(f"[pret] fetch {name}@{pin['commit']}", file=sys.stderr)
    subprocess.run(
        ["git", "init", str(repo)],
        check=True,
        capture_output=True,
    )
    _git(repo, "remote", "add", "origin", url)
    _git(repo, "fetch", "--depth=1", "origin", pin["commit"])
    _git(repo, "checkout", "--detach", pin["commit"])
    verify_source(repo, pin["commit"])
    return repo


def _collect_section_names(repo: pathlib.Path, ram_files: list[str]) -> set[str]:
    """Scan the named ram/*.asm files for SECTION (UNION)? "name" declarations.
    Returns the set of section names that the assembled ram.o will provide."""
    pattern = re.compile(r'^\s*SECTION\s+(?:UNION\s+)?"([^"]+)"', re.MULTILINE)
    names: set[str] = set()
    for relpath in ram_files:
        path = repo / relpath
        if path.exists():
            names.update(pattern.findall(path.read_text(encoding="utf-8")))
    return names


def _build_trimmed_layout(repo: pathlib.Path, sections_in_o: set[str]) -> str:
    """Read repo/layout.link, return a version with:
    - All ROM* regions removed
    - Section references that aren't in `sections_in_o` removed
    - WRAM/VRAM/SRAM/HRAM regions kept
    The resulting layout still defines all memory regions our ram.o needs,
    so rgblink can resolve section addresses without needing ROM .o files."""
    layout_path = repo / "layout.link"
    out: list[str] = []
    in_rom_region = False

    for raw_line in layout_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        # Region headers (top-level, no leading whitespace)
        if line and not line[0].isspace():
            if _ROM_REGION_RE.match(stripped):
                in_rom_region = True
                continue
            if _REGION_HEADER_RE.match(stripped):
                in_rom_region = False
                out.append(line)
                continue
            # Unknown top-level → treat as ROM (drop)
            in_rom_region = True
            continue

        if in_rom_region:
            continue

        # Inside a kept (RAM-like) region
        if _ORG_RE.match(stripped):
            out.append(line)
            continue

        m = _SECTION_REF_RE.match(line)
        if m:
            section_name = m.group(1)
            if section_name in sections_in_o:
                out.append(line)
            # else: drop it — rgblink would error on the missing section
            continue

        # Comments / blanks
        if stripped.startswith(";") or not stripped:
            out.append(line)
            continue

        # Anything else — pass through conservatively
        out.append(line)

    return "\n".join(out) + "\n"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run subprocess, surfacing stderr on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(f"\n[ERROR] command failed: {' '.join(cmd)}", file=sys.stderr)
        if result.stdout:
            print(f"--- stdout ---\n{result.stdout}", file=sys.stderr)
        if result.stderr:
            print(f"--- stderr ---\n{result.stderr}", file=sys.stderr)
        result.check_returncode()
    return result


def _build_repo_syms(name: str, spec: dict, rgbds_bin: pathlib.Path, *, update: bool) -> pathlib.Path:
    """Build a single pret repo's .sym file. Returns path to the .sym output."""
    repo = _clone_or_pull(name, spec["url"], update=update)

    build = BUILD_DIR / name
    build.mkdir(parents=True, exist_ok=True)

    # Determine which RAM sections our compiled ram.o will provide
    sections_in_o = _collect_section_names(repo, spec["ram_files"])
    if not sections_in_o:
        raise RuntimeError(f"No SECTION declarations found in {name} ram files")
    print(f"[{name}] {len(sections_in_o)} RAM sections", file=sys.stderr)

    # The initial HRAM span is executable OAM DMA code emitted by a LOAD block
    # in an engine file. Omitting it shifts every following HRAM label by ten
    # bytes. Assemble the actual pinned block, rather than a guessed reservation.
    dma_file = repo / "engine/gfx" / ("load_push_oam.asm" if name in ("pokecrystal", "pokegold") else "oam_dma.asm")
    blocks = re.findall(r'^LOAD "OAM DMA", HRAM\s*\n.*?^ENDL\s*$',
                        dma_file.read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL)
    if len(blocks) != 1:
        raise RuntimeError(f"{name}: expected exactly one source OAM DMA HRAM LOAD block")
    sections_in_o.add("OAM DMA")
    ram_source = build / "ram_with_dma.asm"
    ram_source.write_text('INCLUDE "ram.asm"\nSECTION "Verifier DMA backing", ROM0\n' + blocks[0] + "\n", encoding="utf-8")

    # Build a trimmed layout.link
    trimmed_layout = build / "ram_layout.link"
    trimmed_layout.write_text(_build_trimmed_layout(repo, sections_in_o), encoding="utf-8")

    rgbasm = rgbds_bin / ("rgbasm.exe" if sys.platform == "win32" else "rgbasm")
    rgblink = rgbds_bin / ("rgblink.exe" if sys.platform == "win32" else "rgblink")

    # 1. rgbasm: compile ram.asm
    ram_o = build / "ram.o"
    rgbasm_cmd = [
        str(rgbasm),
        "-Q8",
        "-E",
        "-o", str(ram_o),
    ]
    # Current pret repos funnel their includes through includes.asm and expect it
    # pre-included. Alchav's AP fork predates that refactor and pulls constants.asm from
    # ram.asm itself, so pre-including anything there double-defines every macro.
    if spec.get("preinclude"):
        rgbasm_cmd[3:3] = ["-P", spec["preinclude"]]
    if spec.get("variant_define"):
        rgbasm_cmd += ["-D", spec["variant_define"]]
    rgbasm_cmd.append(str(ram_source))
    print(f"[{name}] rgbasm ram.asm", file=sys.stderr)
    _run(rgbasm_cmd, cwd=str(repo))

    # 2. rgblink: link to .sym (discard ROM via /dev/null / NUL)
    sym_out = build / f"{name}.sym"
    rgblink_cmd = [str(rgblink)]
    if spec["link_mode"] == "dmg":
        rgblink_cmd.append("-d")  # Game Boy flat 8KB WRAM
    rgblink_cmd += [
        "-l", str(trimmed_layout),
        "-n", str(sym_out),
        "-o", "NUL" if sys.platform == "win32" else "/dev/null",
        str(ram_o),
    ]
    print(f"[{name}] rgblink → {sym_out.name}", file=sys.stderr)
    _run(rgblink_cmd, cwd=str(repo))

    return sym_out


def _parse_sym(sym_path: pathlib.Path) -> dict[str, int]:
    """Parse .sym file → {symbol_name: absolute_address}.

    .sym format: `BB:OOOO symbol_name` where BB is bank, OOOO is offset.
    Keeps WRAM (0xC000-0xDFFF) AND SRAM (0xA000-0xBFFF) symbols. SRAM
    is needed for current-PC-box tracking (Gen 2 stores the active box
    in SRAM at sBox); the SRAM bank context (which 8KB cartridge bank
    is mapped) lives in the Lua profile's `sram_bank` field.

    HRAM (0xFF80-0xFFFE) is also retained for native patch control validation.
    """
    out: dict[str, int] = {}
    line_re = re.compile(r'^([0-9A-Fa-f]+):([0-9A-Fa-f]+)\s+(\S+)\s*$')
    for raw_line in sym_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        m = line_re.match(line)
        if not m:
            continue
        addr_hex, name = m.group(2), m.group(3)  # m.group(1) is the bank, unused
        addr = int(addr_hex, 16)
        # Filter: keep WRAM (0xC000-0xDFFF) + SRAM (0xA000-0xBFFF).
        is_wram = 0xC000 <= addr <= 0xDFFF
        is_sram = 0xA000 <= addr <= 0xBFFF
        is_hram = 0xFF80 <= addr <= 0xFFFE
        if not (is_wram or is_sram or is_hram):
            continue
        # Last-write-wins on duplicates (a few pret symbols are unions/aliases at
        # the same address — `wPartyMon1Species` and `wPartyMon1` for example).
        out[name] = addr
    return out


# Full local builds bind ROM symbols to an actually verified binary.
ROM_SYM_SOURCES = {
    "pokered": {"pokered": "pokered.sym", "pokeblue": "pokeblue.sym"},
    "pokeyellow": {"pokeyellow": "pokeyellow.sym"},
}
ROM_SYMS_OUT = DATA_DIR / "pret_rom_syms.json"


def _parse_rom_sym(text: str) -> dict[str, int]:
    """Parse .sym text → {symbol: (bank << 16) | offset} for ROM-space symbols.

    Keeps only GLOBAL labels. Local sub-labels (`DisableLCD.wait`) are internal jump
    targets — 4.8k of the 17.4k entries, never useful as a hook point — so dropping
    them cuts the artifact by a third for no loss.

    Bank is packed into the high half because a Game Boy ROM address is only meaningful
    with its bank: $4000-$7FFF is whichever bank is currently mapped.
    """
    out: dict[str, int] = {}
    line_re = re.compile(r'^([0-9A-Fa-f]+):([0-9A-Fa-f]+)\s+(\S+)\s*$')
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        m = line_re.match(line)
        if not m:
            continue
        bank, addr, name = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
        if addr > 0x7FFF or "." in name:
            continue
        out[name] = (bank << 16) | addr
    return out


def _expected_rom_sha1(repo: pathlib.Path) -> dict[str, str]:
    """{rom stem: sha1} from the repo's roms.sha1, e.g. {"pokered": "ea9bcae6..."}."""
    path = repo / "roms.sha1"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        name = pathlib.Path(parts[1].lstrip("*"))
        # roms.sha1 also lists VC patch artifacts (`pokered.patch`), which share a stem
        # with the ROM and would otherwise overwrite it — take only real ROM images.
        if name.suffix not in (".gb", ".gbc"):
            continue
        out[name.stem] = parts[0]
    return out


def _tool_record(path: pathlib.Path) -> dict:
    result = _run([str(path), "--version"])
    version = (result.stdout or result.stderr).splitlines()[0].strip()
    resolved = path.resolve()
    return {"path": resolved.relative_to(REPO_ROOT).as_posix()
            if resolved.is_relative_to(REPO_ROOT) else path.name,
            "version": version, "sha256": sha256(resolved)}


def _build_environment(rgbds_bin: pathlib.Path) -> dict[str, str]:
    env = os.environ.copy()
    portable = REPO_ROOT / ".cache" / "build-tools" / "w64devkit" / "bin"
    env["PATH"] = os.pathsep.join([str(rgbds_bin), str(portable), env.get("PATH", "")])
    env["CCACHE_DIR"] = str(REPO_ROOT / ".cache" / "ccache")
    return env


def _toolchain(rgbds_bin: pathlib.Path, *, full: bool) -> dict:
    env = _build_environment(rgbds_bin)
    names = ["rgbasm", "rgblink"] + (["rgbfix", "rgbgfx", "make", "gcc", "sh"] if full else [])
    records = {}
    for name in names:
        found = shutil.which(name, path=env["PATH"])
        if not found:
            raise RuntimeError(f"Missing canonical build dependency: {name}")
        # BusyBox sh does not support --version; hash its binary and query help.
        if name == "sh":
            path = pathlib.Path(found).resolve()
            result = subprocess.run([str(path), "--help"], capture_output=True, text=True)
            records[name] = {"path": path.relative_to(REPO_ROOT).as_posix()
                             if path.is_relative_to(REPO_ROOT) else path.name,
                             "version": (result.stdout or result.stderr).splitlines()[0],
                             "sha256": sha256(path)}
        else:
            records[name] = _tool_record(pathlib.Path(found))
    for name in ("rgbasm", "rgblink", "rgbfix", "rgbgfx"):
        if name in records and records[name]["version"] != f"{name} {load_lock()['rgbds_version']}":
            raise RuntimeError(f"Toolchain version drift: {records[name]['version']}")
    return records


def verify_clean_roms(rom_dir: pathlib.Path) -> dict[str, str]:
    hashes = {}
    for name, spec in load_lock()["clean_roms"].items():
        path = rom_dir / spec["filename"]
        if not path.is_file():
            raise RuntimeError(f"Missing legal clean ROM: {path}")
        actual = hashlib.sha1(path.read_bytes()).hexdigest()
        if actual != spec["sha1"]:
            raise RuntimeError(f"Clean ROM hash drift: {name}; expected {spec['sha1']}, got {actual}")
        hashes[name] = actual
    return hashes


def build_rom_syms(*, update: bool, rom_dir: pathlib.Path,
                   rgbds_bin: pathlib.Path, memory_syms: dict) -> tuple[dict, dict, dict]:
    """Build all canonical binaries; publish nothing unless all hashes agree."""
    lock = load_lock()
    clean_hashes = verify_clean_roms(rom_dir)
    toolchain = _toolchain(rgbds_bin, full=True)
    env = _build_environment(rgbds_bin)
    all_syms, records = {}, {}
    make = shutil.which("make", path=env["PATH"])
    for repo_name, sym_files in ROM_SYM_SOURCES.items():
        repo = _clone_or_pull(repo_name, PRET_REPOS[repo_name]["url"], update=update)
        # Force all inputs to be rebuilt. MAKE=make avoids an unquoted recursive
        # make executable path when the workspace has spaces on Windows.
        args = [make, "MAKE=make", "DEBUG=1", "-B", "-j4"]
        args.extend(f"{name}.gbc" for name in sym_files)
        _run(args, cwd=repo, env=env)
        verify_source(repo, lock["sources"][repo_name]["commit"])
        expected_source_hashes = _expected_rom_sha1(repo)
        for name, filename in sym_files.items():
            rom = repo / f"{name}.gbc"
            actual = hashlib.sha1(rom.read_bytes()).hexdigest()
            if not actual == clean_hashes[name] == expected_source_hashes.get(name):
                raise RuntimeError(f"Canonical built ROM hash mismatch: {name}: {actual}")
            sym = repo / filename
            memory = _parse_sym(sym)
            if memory != memory_syms[repo_name]:
                raise RuntimeError(f"{name}: full-build and RAM-only symbol layout differ")
            symbols = dict(sorted(_parse_rom_sym(sym.read_text(encoding="utf-8")).items()))
            records[name] = {
                "source": repo_name,
                "source_commit": lock["sources"][repo_name]["commit"],
                "build_mode": "full-local",
                "built_rom_path": rom.relative_to(REPO_ROOT).as_posix(),
                "built_rom_sha1": actual,
                "clean_rom_sha1": clean_hashes[name],
                "raw_symbols_path": sym.relative_to(REPO_ROOT).as_posix(),
                "raw_symbols_sha256": sha256(sym),
                "rom_symbols_sha256": symbols_digest(symbols),
                "memory_symbols_sha256": symbols_digest(memory),
            }
            all_syms[name] = {"rom_sha1": actual, "symbols": symbols}
            print(f"[{name}] verified full ROM {actual}; {len(symbols)} ROM labels", file=sys.stderr)
    return all_syms, records, toolchain


def _write_json(path: pathlib.Path, value: dict, *, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=indent) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="fetch only the exact locked source commits")
    parser.add_argument("--clean", action="store_true",
                        help="deprecated; existing checkouts are never erased")
    parser.add_argument("--rom-syms", action="store_true",
                        help="full local canonical builds, including ROM symbols and provenance")
    parser.add_argument("--canonical", action="store_true", help="same as --rom-syms")
    parser.add_argument("--rom-dir", type=pathlib.Path, default=REPO_ROOT,
                        help="directory containing the three user-supplied clean dumps")
    args = parser.parse_args()

    if args.clean:
        parser.error("--clean no longer deletes source checkouts; resolve source drift explicitly")

    rgbds_bin = ensure_rgbds()

    all_syms: dict[str, dict[str, int]] = {}
    lock = load_lock()
    provenance = {"schema_version": 1, "source_lock_sha256": sha256(LOCK_FILE),
                  "sources": {}, "roms": {}, "toolchain": _toolchain(rgbds_bin, full=False)}
    for name, spec in PRET_REPOS.items():
        sym = _build_repo_syms(name, spec, rgbds_bin, update=args.update)
        symbols = _parse_sym(sym)
        print(f"[{name}] {len(symbols)} WRAM symbols extracted", file=sys.stderr)
        all_syms[name] = dict(sorted(symbols.items()))
        repo = PRET_CACHE / name
        provenance["sources"][name] = {
            "commit": lock["sources"][name]["commit"],
            "tree": git_output(repo, "rev-parse", "HEAD^{tree}"),
            "raw_memory_symbols_path": sym.relative_to(REPO_ROOT).as_posix(),
            "raw_memory_symbols_sha256": sha256(sym),
            "memory_symbols_sha256": symbols_digest(symbols),
        }

    rom_syms = None
    if args.canonical or args.rom_syms:
        rom_syms, provenance["roms"], provenance["toolchain"] = build_rom_syms(
            update=args.update, rom_dir=args.rom_dir, rgbds_bin=rgbds_bin, memory_syms=all_syms)
    _write_json(OUT_FILE, all_syms)
    if rom_syms is not None:
        _write_json(ROM_SYMS_OUT, rom_syms, indent=1)
    provenance["artifacts"] = {OUT_FILE.relative_to(REPO_ROOT).as_posix(): sha256(OUT_FILE)}
    if rom_syms is not None:
        provenance["artifacts"][ROM_SYMS_OUT.relative_to(REPO_ROOT).as_posix()] = sha256(ROM_SYMS_OUT)
    _write_json(PROVENANCE_FILE, provenance)
    total = sum(len(s) for s in all_syms.values())
    print(f"\n[done] {total} symbols across {len(all_syms)} repos → {OUT_FILE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
