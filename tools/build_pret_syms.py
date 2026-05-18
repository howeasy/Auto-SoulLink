"""
tools/build_pret_syms.py — Phase 10: extract authoritative WRAM addresses from pret

Drives RGBDS v1.0.1 directly (rgbasm + rgblink, no `make` / w64devkit):
  1. Auto-installs RGBDS if missing (via _build_tools_bootstrap).
  2. Clones pret/pokered, pret/pokeyellow, pret/pokecrystal into .cache/pret/<name>/.
  3. For each repo, compiles ram.asm and links against a TRIMMED layout.link
     (WRAM/VRAM/SRAM/HRAM only — no ROM banks, no engine .o files needed).
  4. Parses each .sym file, filters to WRAM symbols, writes data/pret_syms.json.

Why drive rgbasm/rgblink directly instead of `make`:
  - Eliminates the GNU-make + w64devkit dependency on Windows.
  - ~3× faster — no graphics/audio/ROM-bank compilation we don't need.
  - The .sym output is identical to a full ROM build for WRAM symbols.

Usage:
    python tools/build_pret_syms.py               # build with cached pret repos
    python tools/build_pret_syms.py --update      # git pull each repo first
    python tools/build_pret_syms.py --clean       # wipe .cache/pret/ and reclone

Output: data/pret_syms.json
    {
      "pokered":     {"wPartyCount": 53603, ...},
      "pokeyellow":  {"wPartyCount": 53602, ...},
      "pokecrystal": {"wPartyCount": 56535, ...}
    }
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Optional

from _build_tools_bootstrap import ensure_rgbds


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRET_CACHE = REPO_ROOT / ".cache" / "pret"
BUILD_DIR = REPO_ROOT / ".cache" / "pret-build"
DATA_DIR = REPO_ROOT / "data"
OUT_FILE = DATA_DIR / "pret_syms.json"

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
    },
    "pokeyellow": {
        "url": "https://github.com/pret/pokeyellow.git",
        "variant_define": None,
        "ram_files": ["ram/wram.asm", "ram/hram.asm", "ram/sram.asm", "ram/vram.asm"],
        "link_mode": "dmg",
    },
    "pokecrystal": {
        "url": "https://github.com/pret/pokecrystal.git",
        "variant_define": None,
        "ram_files": ["ram/wram.asm", "ram/hram.asm", "ram/sram.asm", "ram/vram.asm"],
        "link_mode": "cgb",
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
    repo = PRET_CACHE / name
    if repo.exists():
        if update:
            print(f"[pret] git pull {name}", file=sys.stderr)
            _git(repo, "fetch", "--depth=1", "origin")
            _git(repo, "reset", "--hard", "origin/HEAD")
        return repo

    PRET_CACHE.mkdir(parents=True, exist_ok=True)
    print(f"[pret] git clone --depth=1 {url} → {repo}", file=sys.stderr)
    subprocess.run(
        ["git", "clone", "--depth=1", url, str(repo)],
        check=True,
        capture_output=False,  # show clone progress
    )
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
    kept_region_lines = 0  # count non-section lines inside the current region

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
                kept_region_lines = 0
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
        "-P", "includes.asm",
        "-E",
        "-o", str(ram_o),
    ]
    if spec.get("variant_define"):
        rgbasm_cmd += ["-D", spec["variant_define"]]
    rgbasm_cmd.append("ram.asm")
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
    We keep only WRAM symbols (0xC000-0xDFFF). For WRAM0 (bank 00), the
    offset IS the absolute address. For WRAMX (banks 01-07), the offset
    is in 0xD000-0xDFFF when mapped, so the offset is also the absolute
    address from a tracker's perspective. Other regions (ROM, VRAM, OAM,
    HRAM, SRAM) are filtered out — we don't track those.
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
        bank_hex, addr_hex, name = m.group(1), m.group(2), m.group(3)
        addr = int(addr_hex, 16)
        # Filter: keep WRAM only (0xC000-0xDFFF). Drop everything else.
        if not (0xC000 <= addr <= 0xDFFF):
            continue
        # Last-write-wins on duplicates (a few pret symbols are unions/aliases at
        # the same address — `wPartyMon1Species` and `wPartyMon1` for example).
        out[name] = addr
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="git pull each cached pret repo before building")
    parser.add_argument("--clean", action="store_true",
                        help="wipe .cache/pret/ and reclone everything")
    args = parser.parse_args()

    if args.clean and PRET_CACHE.exists():
        print(f"[clean] removing {PRET_CACHE}", file=sys.stderr)
        shutil.rmtree(PRET_CACHE)
    if BUILD_DIR.exists():
        # Always wipe build dir to avoid stale .o files
        shutil.rmtree(BUILD_DIR)

    rgbds_bin = ensure_rgbds()

    all_syms: dict[str, dict[str, int]] = {}
    for name, spec in PRET_REPOS.items():
        sym = _build_repo_syms(name, spec, rgbds_bin, update=args.update)
        symbols = _parse_sym(sym)
        print(f"[{name}] {len(symbols)} WRAM symbols extracted", file=sys.stderr)
        all_syms[name] = dict(sorted(symbols.items()))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(all_syms, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    total = sum(len(s) for s in all_syms.values())
    print(f"\n[done] {total} symbols across {len(all_syms)} repos → {OUT_FILE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
