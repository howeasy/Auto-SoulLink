"""Resolve pokeemerald-expansion's compile-time battle-mechanics config VALUES (XC0).

The pinned build's config headers (`include/config/*.h`) are already sha256-pinned
in `data/gen3_exp_sources.lock.json` / `data/games/gen3_exp/28877d73/facts.json`,
but a hash only proves which header *bytes* were compiled -- it says nothing about
what those headers' `B_*`/`P_*`/`I_*`/`GEN_*` macros actually resolve to. Almost
every one is written as `GEN_LATEST`, `TRUE`, or a chained `GEN_N` alias, never a
literal in the header text (see include/config/battle.h). This tool resolves them
with the pinned build's own preprocessor (`arm-none-eabi-cpp`, the exact CPPFLAGS
recorded in facts.json) and records the resulting integers.

Usage:
  python tools/extract_expansion_config.py --host hgbox
      Fresh, dedicated checkout + preprocess on the VM (mirrors build_expansion.py's
      --host pattern; never touches any pre-existing checkout there), scp's the
      result back, and overwrites data/games/gen3_exp/28877d73/config.json.
  python tools/extract_expansion_config.py --host hgbox --check
      Same remote extraction into a temp file; exits non-zero if it differs from
      the committed config.json (a live staleness check).
  python tools/extract_expansion_config.py --check
      Offline: re-validates the committed config.json's header-sha256 pins against
      the lock/facts provenance and recomputes each macro's stored value from its
      stored expansion -- no network, no compiler. Catches a hand-edited/corrupted
      file; does not by itself prove freshness against the live source.
  python tools/extract_expansion_config.py --linux-worker   (internal; runs on the VM)
"""
from __future__ import annotations

import argparse
import ast
import json
import operator
import os
import re
import shlex
import shutil
import sys
import time
import uuid
from pathlib import Path

try:
    from tools import build_expansion as be
except ModuleNotFoundError:
    import build_expansion as be

ROOT = Path(__file__).resolve().parents[1]
PIN = "e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7"
PACK = ROOT / "data/games/gen3_exp/28877d73"
FACTS_PATH = PACK / "facts.json"
OUTPUT = PACK / "config.json"
# species_enabled.h is pinned/hashed (its sha256 still has to match the lock/facts
# provenance) but excluded from EXTRACT_HEADERS: manual inspection of its ~571 P_
# macros (2026-09-26) found every one is a roster/form/cross-evo toggle whose value
# is always TRUE/FALSE or another such toggle (P_GEN_1_POKEMON, P_REGIONAL_FORMS,
# P_FAMILY_BULBASAUR, ...) -- none affect damage or battle mechanics. If a future
# pinned build adds a battle-relevant P_ macro there, this ambiguity should be
# revisited (see the XC0 report for detail).
CONFIG_HEADERS = (
    "include/config/battle.h",
    "include/config/general.h",
    "include/config/pokemon.h",
    "include/config/item.h",
    "include/config/species_enabled.h",
)
EXTRACT_HEADERS = CONFIG_HEADERS[:-1]
PREFIXES = ("B_", "P_", "I_", "GEN_")
# Not a preprocessor macro: SPECIES_* ids are C `enum` members (constants/species.h),
# invisible to `-E`/`-dM` (the preprocessor never sees enum semantics). It also
# picks a cosmetic default breed form, not a damage/mechanics value. See the XC0
# report for how this was found; a future pin adding a similar enum-valued
# battle-relevant macro should get a real resolver, not another name added here.
EXCLUDE_ENUM_VALUED = {"P_SCATTERBUG_LINE_FORM_BREED": "value is the enum member SPECIES_SCATTERBUG_FANCY, not a macro"}
# Object-like macro only: name not immediately followed by '(' (that would be
# function-like, e.g. a helper macro, which has no single resolved value).
DEFINE_RE = re.compile(r"^#define[ \t]+([A-Za-z_]\w*)(?!\()[ \t]+([^\r\n]+)", re.M)
SENTINEL_RE = re.compile(r"SLINK_CFG_BEGIN_(\w+)\s+(.*?)\s+SLINK_CFG_END_\1")


def strip_comment(text: str) -> str:
    return re.sub(r"//.*$", "", text).strip()


def read_macro_candidates(source: Path) -> dict:
    """Object-like B_/P_/I_/GEN_ macros defined directly in the battle-relevant config headers."""
    candidates = {}
    for header in EXTRACT_HEADERS:
        text = (source / header).read_text(encoding="utf-8")
        for name, raw in DEFINE_RE.findall(text):
            if name.startswith(PREFIXES) and name not in EXCLUDE_ENUM_VALUED:
                if name in candidates:
                    raise ValueError(f"macro {name} defined in more than one config header")
                candidates[name] = {"header": header, "raw": strip_comment(raw)}
    if not candidates:
        raise ValueError("no B_/P_/I_/GEN_ macros found in the config headers")
    return candidates


def build_probe(candidates: dict) -> str:
    lines = [
        '#include "global.h"',  # pulls in config/general.h (GEN_1..GEN_LATEST, TRUE/FALSE) and config/battle.h.
        '#include "config/pokemon.h"',
        '#include "config/item.h"',  # item.h's I_ORAS_DOWSING_COLOR_* use RGB2GBA(), defined in constants/rgb.h.
        '#include "constants/rgb.h"',
        "",
    ]
    for name in sorted(candidates):
        lines.append(f"SLINK_CFG_BEGIN_{name} {name} SLINK_CFG_END_{name}")
    return "\n".join(lines) + "\n"


def eval_int(expr: str) -> int:
    """A fully cpp-expanded integer constant expression (+-*/%, bit ops, parens)."""
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.FloorDiv: operator.floordiv, ast.Div: operator.floordiv, ast.Mod: operator.mod,
           ast.LShift: operator.lshift, ast.RShift: operator.rshift,
           ast.BitOr: operator.or_, ast.BitAnd: operator.and_, ast.BitXor: operator.xor}

    def walk(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        raise ValueError(f"unresolved/unsupported constant expression: {expr!r}")

    return walk(ast.parse(expr.strip(), mode="eval").body)


def parse_expanded(preprocessed: str, names) -> dict:
    found = dict(SENTINEL_RE.findall(preprocessed))
    missing = sorted(set(names) - set(found))
    if missing:
        raise ValueError(f"preprocessor did not emit a value for: {missing[:5]}")
    return found


def linux_worker(args) -> int:
    lock = be.load_lock()
    if lock["source"]["commit"] != PIN:
        raise ValueError("lock source commit differs from this tool's pin")
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    if facts["provenance"]["source_commit"] != PIN:
        raise ValueError("facts.json source commit differs from this tool's pin")
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    for name in ("CC", "CXX", "CFLAGS", "CPPFLAGS", "LDFLAGS", "MAKEFLAGS", "DEVKITARM", "CPATH",
                 "LIBRARY_PATH", "PKG_CONFIG_PATH", "GCC_EXEC_PREFIX", "COMPILER_PATH",
                 "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"):
        env.pop(name, None)
    deadline = time.monotonic() + args.timeout_minutes * 60
    source = be.checkout(lock, env, deadline)  # fresh dedicated clone; verified against the lock.
    # global.h pulls in the generated include/constants/map_groups.h (built from
    # data/maps/map_groups.json by the native `mapjson` host tool); ask make for
    # exactly that one file rather than a full ROM build.
    be.run(["make"] + [f"{k}={v}" for k, v in lock["make_variables"].items()] + ["include/constants/map_groups.h"],
           source, env, deadline)

    candidates = read_macro_candidates(source)
    header_sha256 = {}
    for header in CONFIG_HEADERS:
        digest = be.digest(source / header)
        for provenance_name, provenance in (("lock", lock["config_headers"]), ("facts", facts["provenance"]["config_sha256"])):
            if provenance.get(header) != digest:
                raise ValueError(f"{header} sha256 does not match the {provenance_name} provenance")
        header_sha256[header] = digest

    flags = facts["provenance"]["compile"]["flags"]
    cpp_path = Path(shutil.which(shlex.split(flags["CPP"])[0], path=env["PATH"]) or shlex.split(flags["CPP"])[0]).resolve()
    cpp_sha256 = be.digest(cpp_path)
    if facts["provenance"]["compile"]["executables"].get(str(cpp_path)) not in (cpp_sha256, None):
        raise ValueError("arm-none-eabi-cpp binary differs from the pinned build's own facts.json")

    work = ROOT / "work"
    work.mkdir(parents=True, exist_ok=True)
    probe = work / "config_probe.c"
    probe.write_text(build_probe(candidates), encoding="utf-8")
    argv = shlex.split(flags["CPP"]) + shlex.split(flags["CPPFLAGS"]) + [str(probe)]
    preprocessed = be.run(argv, source, env, deadline)
    expanded = parse_expanded(preprocessed, candidates)
    # Record a path relative to this run's own scratch root: the absolute scratch
    # directory has a fresh uuid every run (be.checkout/remote_extract), which would
    # otherwise make config.json non-deterministic between two identical extractions.
    recorded_argv = argv[:-1] + [str(probe.relative_to(ROOT))]

    macros = {}
    for name, info in sorted(candidates.items()):
        macros[name] = {"header": info["header"], "raw": info["raw"],
                         "expanded": expanded[name], "value": eval_int(expanded[name])}

    config = {
        "schema": 1,
        "macros": macros,
        "provenance": {
            "source_commit": PIN,
            "rom_sha1": facts["provenance"]["rom_sha1"],
            "compiler": {"path": str(cpp_path), "sha256": cpp_sha256},
            "cpp_command": recorded_argv,
            "config_sha256": header_sha256,
            "generator_sha256": be.digest(Path(__file__)),
            "excluded": {"enum_valued": EXCLUDE_ENUM_VALUED, "non_battle_headers": [CONFIG_HEADERS[-1]]},
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"macros_captured": len(macros)}, indent=2))
    return 0


def remote_extract(lock: dict, host: str, timeout_minutes: float, out: Path) -> None:
    """Mirror build_expansion.remote_build: fresh scratch dir, scp up, run, scp back."""
    relative = f"slink-exp/{lock['source']['commit']}/{uuid.uuid4().hex}"
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host]
    env = os.environ.copy()
    deadline = time.monotonic() + timeout_minutes * 60 + 120
    be.run(ssh + [f"mkdir -p ~/{relative}/tools ~/{relative}/data/games/gen3_exp/28877d73"], ROOT, env, deadline)
    for local, remote in (
        (Path(__file__), f"tools/{Path(__file__).name}"),
        (ROOT / "tools/build_expansion.py", "tools/build_expansion.py"),
        (be.LOCK_PATH, "data/gen3_exp_sources.lock.json"),
        (FACTS_PATH, "data/games/gen3_exp/28877d73/facts.json"),
    ):
        be.run(["scp", "-q", str(local), f"{host}:{relative}/{remote}"], ROOT, env, deadline)
    command = (f"cd ~/{relative} && timeout --signal=TERM --kill-after=15s "
               f"{int(timeout_minutes * 60 + 30)}s python3 tools/extract_expansion_config.py --linux-worker "
               f"--timeout-minutes {timeout_minutes}")
    print(f"[expansion-config] remote directory: ~/{relative}", flush=True)
    be.run(ssh + [command], ROOT, env, deadline)
    out.parent.mkdir(parents=True, exist_ok=True)
    be.run(["scp", "-q", f"{host}:{relative}/data/games/gen3_exp/28877d73/config.json", str(out)], ROOT, env, deadline)


def offline_check(output: Path) -> dict:
    """No network, no compiler: re-validate pins and recompute stored values."""
    lock = be.load_lock()
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    config = json.loads(output.read_text(encoding="utf-8"))
    provenance = config["provenance"]
    if provenance["source_commit"] != PIN:
        raise ValueError("config.json source commit differs from this tool's pin")
    for header, digest in provenance["config_sha256"].items():
        if lock["config_headers"].get(header) != digest or facts["provenance"]["config_sha256"].get(header) != digest:
            raise ValueError(f"stale header pin: {header}")
    if set(provenance["config_sha256"]) != set(CONFIG_HEADERS):
        raise ValueError("config.json does not cover the expected 5 config headers")
    for name, entry in config["macros"].items():
        if eval_int(entry["expanded"]) != entry["value"]:
            raise ValueError(f"stale/corrupted macro: {name}")
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", choices=["hgbox"])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--timeout-minutes", type=float, default=10)
    parser.add_argument("--linux-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.linux_worker:
            return linux_worker(args)
        if not args.host and not args.check:
            parser.error("pass --host hgbox to (re)generate, and/or --check to validate")
        if args.host:
            lock = be.load_lock()
            if args.check:
                import tempfile
                with tempfile.TemporaryDirectory() as tmp:
                    candidate = Path(tmp) / "config.json"
                    remote_extract(lock, args.host, args.timeout_minutes, candidate)
                    fresh, committed = json.loads(candidate.read_text()), json.loads(args.output.read_text())
                    if fresh != committed:
                        print(f"FAIL: {args.output} is stale relative to the pinned build", file=sys.stderr)
                        return 1
                    print(f"PASS: {args.output} matches a fresh extraction; macros={len(fresh['macros'])}")
                    return 0
            remote_extract(lock, args.host, args.timeout_minutes, args.output)
            config = json.loads(args.output.read_text())
            print(f"PASS: wrote {args.output}; macros={len(config['macros'])}")
            return 0
        config = offline_check(args.output)
        print(f"PASS: offline pin/value check; macros={len(config['macros'])}")
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
