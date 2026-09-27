"""X3: compile tools/expansion_harness_offsets.c on the build host -> harness_facts.json.

The X1 facts pipeline (tools/gen_expansion_facts.py: the ROM's own Makefile CPP/PREPROC/CC1/AS
flags, the pinned compiler checked against the build receipt, the ELF32 object parsed, never
executed) over a second, harness-only probe: the struct offsets and constants the live harness
(battle-bag ball throw) and the make-exp fixture seed read on the reference build.

Build host (the clean pinned tree + its build receipt), like gen_expansion_facts.py:
  python3 gen_expansion_harness_facts.py --source SOURCE --artifacts OUTPUT --work-dir SCRATCH \
      --output harness_facts.json
Local, offline: --check verifies the committed file names this probe (probe_sha256) and the
reference ROM; no compiler is needed or run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from tools import gen_expansion_facts as gf
except ModuleNotFoundError:
    import gen_expansion_facts as gf

PROBE = Path(__file__).with_name("expansion_harness_offsets.c")
OUTPUT = Path(__file__).resolve().parents[1] / "data/games/gen3_exp/28877d73/harness_facts.json"
ROM_SHA1 = "28877d733492299599f2b8fff50493109d72653c"


def pc_options_enum(source: Path) -> dict:
    """The private PC main-menu enum, verbatim (its #if arms included, so the compiler applies
    the build's OW_PC_MOVE_ORDER): the one anonymous enum in src/pokemon_storage_system.c that
    names OPTION_WITHDRAW."""
    import re
    text = (source / "src/pokemon_storage_system.c").read_text(encoding="utf-8")
    found = [m for m in re.finditer(r"enum\s*\{.*?\}\s*;", text, re.S) if "OPTION_WITHDRAW" in m[0]]
    gf.ex.require(len(found) == 1, "PC main-menu enum absent/ambiguous")
    m = found[0]
    return {"source": "src/pokemon_storage_system.c", "line": text[:m.start()].count("\n") + 1,
            "text": m[0], "sha256": gf.sha(m[0].encode())}


def build(source: Path, artifacts: Path, work: Path) -> dict:
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    for name in ("CC", "CXX", "CFLAGS", "CPPFLAGS", "LDFLAGS", "MAKEFLAGS", "DEVKITARM", "CPATH",
                 "LIBRARY_PATH", "PKG_CONFIG_PATH", "GCC_EXEC_PREFIX", "COMPILER_PATH",
                 "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"):
        env.pop(name, None)
    gf.ex.require(gf.run(["git", "rev-parse", "HEAD"], source, env).decode().strip() == gf.PIN,
                  "source commit mismatch")
    gf.ex.require(not gf.run(["git", "status", "--porcelain", "--untracked-files=no"], source, env),
                  "source tracked files are dirty")
    receipt, _rom, _symbols, _elf = gf.read_artifacts(artifacts)
    gf.ex.require(receipt["rom"]["sha1"] == ROM_SHA1, "not the reference build")
    work.mkdir(parents=True, exist_ok=True)
    pc_enum = pc_options_enum(source)
    (work / "x3_pc_options.h").write_text(pc_enum["text"] + "\n", encoding="utf-8")
    obj, manifest = gf.compile_probe(source, PROBE, work, receipt, env)
    facts = gf.parse_probe(gf.elf_symbols(obj.read_bytes(), "x1_"))
    return {"schema": 1, "evidence": "SOURCE/COMPILER only; harness facts, no runtime qualification",
            "rom_sha1": ROM_SHA1, "source_commit": gf.PIN, **facts,
            "provenance": {"probe_sha256": gf.source_sha(PROBE), "pc_options_enum": pc_enum,
                           "object_sha256": manifest["object_sha256"],
                           "preprocessed_sha256": manifest["preprocessed_sha256"],
                           "compiler": receipt["compiler"], "flags": manifest["flags"],
                           "generator_sha256": gf.source_sha(Path(__file__))}}


def check(path: Path = OUTPUT) -> list[str]:
    facts = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    if facts["provenance"]["probe_sha256"] != gf.source_sha(PROBE):
        problems.append("harness_facts.json was not compiled from the current probe")
    if facts["rom_sha1"] != ROM_SHA1 or facts["source_commit"] != gf.PIN:
        problems.append("harness_facts.json is bound to another build")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path)
    ap.add_argument("--artifacts", type=Path)
    ap.add_argument("--work-dir", type=Path)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        problems = check(args.output)
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        if not problems:
            print(f"PASS: {args.output} matches {PROBE.name}")
        return 1 if problems else 0
    facts = build(args.source.resolve(), args.artifacts.resolve(), args.work_dir.resolve())
    args.output.write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v["size"] for k, v in facts["structs"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
