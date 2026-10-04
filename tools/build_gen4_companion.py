#!/usr/bin/env python3
"""Plan Gen 4 companion objects, never compile/link/ssh or qualify a ROM.

Default: print deterministic JSON, touching nothing. --write-plan writes ONLY
companion-plan.json inside the caller's --out (absolute F: directory).
The restricted make reader is not a make interpreter: unsupported variables or
syntax refuse rather than running $(shell ...). hge receives an explicitly
UNVERIFIED pret-template plan, not an invented fork compiler configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
# The pinned pokeheartgold checkout: SLINK_PRET_HGSS overrides the owner-machine default (the same
# variable tests/unit/test_gen4_sound_binding.py reads); absent => the planner refuses by name.
PRET_ROOT = Path(os.environ.get("SLINK_PRET_HGSS", "E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold"))
PRET_PIN = "ad7a3afa0cfc144fe6837c410cb95b2727217f54"
CARDS = ("sound", "panel", "trade")
BUILD_FILES = ("Makefile", "common.mk", "config.mk")


class Refused(ValueError):
    """Named, fail-closed input/source refusal."""


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "--no-optional-locks", "-C", str(root), *args],
            check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Refused("PRET_GIT_UNAVAILABLE") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pret_sources(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    if not root.is_dir():
        raise Refused("PRET_ROOT_MISSING")
    if _git(root, "rev-parse", "HEAD") != PRET_PIN:
        raise Refused("PRET_PIN_MISMATCH")
    texts, hashes = {}, {}
    for name in BUILD_FILES:
        path = root / name
        if not path.is_file():
            raise Refused(f"PRET_FILE_MISSING: {name}")
        data = path.read_bytes()
        text = data.decode("utf-8-sig")
        # HEAD alone does not prove the working file belongs to the pinned tree.
        if text.strip() != _git(root, "show", f"{PRET_PIN}:{name}"):
            raise Refused(f"PRET_FILE_MODIFIED: {name}")
        texts[name], hashes[name] = text, _sha(data)
    return texts, hashes


def _assignment(text: str, name: str, *, append: bool = False) -> str:
    # Makefile:1-7, common.mk:36,123-131, config.mk:35-42 at ad7a3afa.
    pattern = rf"^{re.escape(name)}\s*(\?=|:=|\+=|=)\s*(.*?)\s*$"
    matches = re.findall(pattern, text, re.M)
    bases = [value for op, value in matches if op != "+="]
    if len(bases) != 1 or (not append and len(matches) != 1):
        raise Refused(f"PRET_TEMPLATE_UNSUPPORTED: {name}")
    return " ".join(bases + [v for op, v in matches if op == "+="])


def _expand(value: str, values: dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        name = match[1]
        if name not in values:
            raise Refused(f"PRET_VARIABLE_UNSUPPORTED: {name}")
        return values[name]

    return re.sub(r"\$\(([^)]+)\)", replace, value)


def _tokens(text: str) -> list[str]:
    return shlex.split(text, posix=True)


def _out_dir(out: str | Path) -> str:
    # Owner rule: lanes and temps never live on C:. The rule is "absolute, no traversal, and (on a
    # drive-lettered path) not C:" rather than "exactly F:", so the same planner runs on a Linux CI
    # checkout whose absolute temp dirs have no drive letter. Relative, traversal, UNC and C: refuse.
    text = str(out)
    if os.name == "nt" or re.match(r"^[A-Za-z]:", text):
        path = PureWindowsPath(text)
        if (not re.fullmatch(r"[A-Za-z]:", path.drive) or not path.is_absolute()
                or path.drive.upper() == "C:" or ".." in path.parts):
            raise Refused("OUT_MUST_BE_ABSOLUTE_NON_C_DRIVE")
        if any(":" in part for part in path.parts[1:]):
            raise Refused("OUT_INVALID_PATH")
        # Existing junctions/symlinks must not redirect writes to C: (or elsewhere).
        resolved = PureWindowsPath(str(Path(text).resolve()))
        if sys.platform == "win32" and resolved.drive.upper() == "C:":
            raise Refused("OUT_RESOLVES_TO_C_DRIVE")
        return path.as_posix()
    posix = PurePosixPath(text)
    if not posix.is_absolute() or text.startswith("//") or ".." in posix.parts or ":" in text:
        raise Refused("OUT_MUST_BE_ABSOLUTE_NON_C_DRIVE")
    return posix.as_posix()


def _strip(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", "''", text)
    kept, continuing = [], False
    for line in text.splitlines():
        if continuing or line.lstrip().startswith("#"):
            continuing = line.rstrip().endswith("\\")
            continue
        kept.append(line)
    return "\n".join(kept)


def file_scope_objects(text: str) -> list[str]:
    """Minimum pure C2 detector; tests/unit/test_gen4_c2_beacon_source.py:74-147.

    Reimplemented to keep production planning independent of pytest/test imports.
    Same conservative lexical scope, not a compiler/linker allocation proof.
    """
    statements, cur = [], []
    depth = paren = 0
    for ch in _strip(text):
        if ch == "{":
            depth += 1
            cur.append(ch)
        elif ch == "}":
            depth -= 1
            if depth == 0 and "(" in "".join(cur).split("{")[0]:
                cur.clear()
            else:
                cur.append(ch)
        elif depth == 0:
            if ch == "(":
                paren += 1
            elif ch == ")":
                paren -= 1
            if ch == ";" and paren == 0:
                statements.append(" ".join("".join(cur).split()))
                cur.clear()
            else:
                cur.append(ch)
    statements.append(" ".join("".join(cur).split()))
    prototype = re.compile(
        r"^(?:extern\s+|static\s+)?[A-Za-z_][\w\s]*?\b[A-Za-z_]\w*\s*"
        r"\((?!\s*\*)[^;{}]*\)$"
    )
    return [s for s in statements if s and not (
        re.match(r"^(typedef|struct|union|enum)\b", s) or prototype.match(s)
    )]


def span_literals(text: str) -> list[str]:
    """C2 detector :153-169; census W2 tools/gen4_mailbox_census.py:188-197.

    Includes suffixes and ITCM aliases; raw comments are scanned too, as in C2.
    """
    lo, hi = 0x01FFEC00, 0x01FFFC00
    hits = []
    for m in re.finditer(r"\b0[xX]([0-9A-Fa-f]{7,8})(?![0-9A-Fa-f])", text):
        value = int(m[1], 16)
        alias = (lo & 0x7FFF) <= (value & 0x7FFF) < (hi & 0x7FFF or 0x8000)
        if (lo <= value < hi or (0x01000000 <= value < 0x02000000 and alias)
                or (len(m[1]) == 8 and value < 0x8000 and alias)):
            hits.append(m[0])
    return hits


def _scan(card_dir: Path, units: list[str]) -> dict[str, str]:
    # Scan every title header, even when its card is disabled (beacon.h embeds them).
    paths = sorted({*(card_dir / n for n in units), *card_dir.glob("*.h")})
    hashes = {}
    for path in paths:
        text = path.read_text(encoding="utf-8-sig")
        if file_scope_objects(text):
            raise Refused(f"CENSUS_FILE_SCOPE_OBJECT: {path.name}")
        if span_literals(text):
            raise Refused(f"CENSUS_SPAN_LITERAL: {path.name}")
        if re.search(r"\b(?:OS_ARENA_ITCM|SDK_SECTION_ARENA_DTCM\w*)\b", _strip(text)):
            raise Refused(f"CENSUS_FORBIDDEN_ARENA: {path.name}")
        hashes[path.name] = _sha(path.read_bytes())
    return hashes


def plan(title: str, cards: list[str], out: str | Path, *, pret_root: Path = PRET_ROOT,
         game_version: str | None = None, repo_root: Path = ROOT) -> dict:
    """Return a non-executing, provenance-bound command plan; no writes."""
    if title not in ("hgss", "hge"):
        raise Refused(f"UNKNOWN_TITLE: {title}")
    if len(cards) != len(set(cards)):
        raise Refused("DUPLICATE_CARD")
    if set(cards) - set(CARDS):
        raise Refused("UNKNOWN_CARD")
    if game_version not in (None, "HEARTGOLD", "SOULSILVER"):
        raise Refused("UNKNOWN_GAME_VERSION")
    if title == "hge" and game_version is not None:
        raise Refused("HGE_GAME_VERSION_UNVERIFIED")
    out = _out_dir(out)
    pret_root, repo_root = pret_root.resolve(), repo_root.resolve()
    card_dir = repo_root / "patch/src/nds/gen4"
    common_dir = repo_root / "patch/src/nds/common"
    enabled = [c for c in CARDS if c in cards]
    units = ["beacon.c", "dispatch.c"] + [f"{c}.c" for c in enabled]
    for name in units:
        if not (card_dir / name).is_file():
            raise Refused(f"CARD_SOURCE_MISSING: {name}")
    census_hashes = _scan(card_dir, units)
    texts, source_hashes = _pret_sources(pret_root)
    make, common, config = (texts[n] for n in BUILD_FILES)
    compile_template = _assignment(common, "MW_COMPILE", append=True)
    if compile_template not in ("$(WINE) $(MWCC) $(MWCFLAGS)",
                                "$(WINE) $(MWCC) $(MWCFLAGS) $(DEPFLAGS)"):
        raise Refused("PRET_COMPILE_TEMPLATE_UNSUPPORTED")
    # common.mk:153-170: default NODEP-empty branch appends dependency flags.
    dependency_flags = (_tokens(_assignment(common, "DEPFLAGS"))
                        if "$(DEPFLAGS)" in compile_template else [])
    unknown = {
        "companion_ipa_file": "UNVERIFIED: emit pret value; companion applicability not proved",
        "companion_sym_on": "UNVERIFIED: emit pret value; companion applicability not proved",
        "link_and_registration": "UNVERIFIED: objects only; no linked image or runtime qualification",
        "wine_wrapper": "UNVERIFIED: MW_COMPILE names WINE; host execution wrapper not selected",
        "nodep_branch": "UNVERIFIED: emit pret NODEP-empty dependency flags; no make environment selected",
    }
    version = game_version or _assignment(config, "GAME_VERSION")
    defines_values = {
        "GAME_VERSION": version, "GAME_REMASTER": _assignment(config, "GAME_REMASTER"),
        "GAME_LANGUAGE": _assignment(config, "GAME_LANGUAGE"), "CLI_DEFINES": "",
    }
    if title == "hge":
        # C6_HGE_BUILD_SPEC.md does not establish the fork's MWCC/defines recipe.
        for key in ("GAME_VERSION", "GAME_REMASTER", "GAME_LANGUAGE"):
            defines_values[key] = f"${{{key}_UNVERIFIED}}"
            unknown[key] = "UNVERIFIED: C6 spec does not state hge substitution"
        unknown["hge_toolchain"] = "UNVERIFIED: pret template, not a proved hge build command"
    # config.mk:36-38 enables PM_KEEP_ASSERTS when NO_GF_ASSERT is empty.
    if "ifeq ($(NO_GF_ASSERT),)" not in config:
        raise Refused("PRET_ASSERT_CONDITION_UNSUPPORTED")
    defines_values["GF_DEFINES"] = _expand(_assignment(config, "GF_DEFINES", append=True), defines_values)
    defines_values["GLB_DEFINES"] = _assignment(config, "GLB_DEFINES")
    defines = _expand(_assignment(config, "DEFINES"), defines_values)
    values = {
        "DEFINES": defines, "OPTFLAGS": _assignment(make, "OPTFLAGS"),
        "PROC": _assignment(make, "PROC"), "EXCCFLAGS": _assignment(common, "EXCCFLAGS"),
        # Root compile context: common.mk:22 WORK_DIR is relative PROJECT_ROOT.
        "WORK_DIR": shlex.quote(pret_root.as_posix()),
    }
    flags = _tokens(_expand(_assignment(common, "MWCFLAGS"), values))
    if flags[-2:] != ["-W", "error"]:
        raise Refused("PRET_WARNING_ERROR_MISSING")
    compiler_values = {"TOOLSDIR": (pret_root / "tools").as_posix(),
                       "MWCCVER": _assignment(make, "MWCCVER")}
    compiler = _expand(_assignment(common, "MWCC"), compiler_values)
    include_dirs = [(pret_root / "include").as_posix(), card_dir.as_posix(), common_dir.as_posix()]
    includes = [token for directory in include_dirs for token in ("-i", directory)]
    switches = [f"-DSLINK_GEN4_{c.upper()}" for c in enabled]
    arguments = includes + flags + dependency_flags + switches
    objects = [{"source": (card_dir / name).as_posix(),
                "object": f"{out}/{Path(name).stem}.o",
                "argv": [compiler, *arguments, "-c", "-o", f"{out}/{Path(name).stem}.o",
                         (card_dir / name).as_posix()]} for name in units]
    return {
        "schema": "gen4-companion-plan-v1", "qualified": False, "executes": False,
        "title": title, "cards": enabled, "out": out, "pret_root": pret_root.as_posix(),
        "pret_pin": PRET_PIN, "pret_source_sha256": source_hashes,
        "compiler": compiler, "mwcc_version": compiler_values["MWCCVER"],
        "mw_compile_template": compile_template,
        "dependency_flags": dependency_flags,
        "pret_flags": flags, "switches": switches, "include_dirs": include_dirs,
        "compile_context": pret_root.as_posix(), "objects": objects,
        "census": {"status": "SOURCE_SCAN_PASS", "source_sha256": census_hashes,
                   "scope": "selected TUs plus all title headers; lexical, not linked W2 proof"},
        "unverified": unknown,
        "citations": ["pret Makefile:1-7", "pret common.mk:22,36,123-131,153-172",
                      "pret config.mk:1-3,35-42", "dispatch.c:34-46",
                      "tests/unit/test_gen4_c2_beacon_source.py:74-169"],
    }


def plan_json(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("title")
    parser.add_argument("--card", action="append", default=[])
    parser.add_argument("--out", required=True)
    parser.add_argument("--pret-root", type=Path, default=PRET_ROOT)
    parser.add_argument("--game-version")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--print", action="store_true", help="print only (also the default)")
    mode.add_argument("--write-plan", action="store_true", help="write JSON in --out; never build")
    args = parser.parse_args(argv)
    try:
        data = plan(args.title, args.card, args.out, pret_root=args.pret_root,
                    game_version=args.game_version)
        serialized = plan_json(data)
        if args.write_plan:
            out = Path(_out_dir(args.out))
            out.mkdir(parents=True, exist_ok=True)
            target = out / "companion-plan.json"
            if target.exists() and (target.is_symlink() or target.resolve().parent != out.resolve()):
                raise Refused("PLAN_TARGET_OUTSIDE_OUT")
            # Replacing the file avoids writing through a pre-existing hard link.
            temporary = out / "companion-plan.json.tmp"
            with temporary.open("xb") as stream:
                stream.write(serialized.encode("utf-8"))
            try:
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        if args.print or not args.write_plan:
            print(serialized, end="")
        return 0
    except (Refused, OSError, UnicodeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
