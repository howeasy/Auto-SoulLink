"""
tools/run_unit_shards.py -- run tests/unit as N parallel pytest shards.

Why it exists: the full unit suite is too slow as one process, and hand-rolled
sharding went wrong twice: no UTF-8 mode (unicode output crashed on the Windows
console) and a pipe into `tail`/`head` hid pytest's exit code. This runner forces
PYTHONUTF8, gives every shard its own log and --basetemp, and exits 0 only if
every shard's pytest returned 0. pytest rc 5 ("no tests collected") is a failure.

Standard library only; no pytest-xdist.

Usage:
    python -B tools/run_unit_shards.py --shards 6
    python -B tools/run_unit_shards.py --shards 4 --out F:/slink-work/tmp/shards/x -- -k gen2

Output (OUT is the default F:/slink-work/tmp/shards/<timestamp>):
    OUT/sK.files     test files for shard K
    OUT/sK.log       pytest output for shard K
    OUT/failures.txt every FAILED/ERROR line, prefixed with its shard
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
import time

DEFAULT_WORK = "F:/slink-work"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SUMMARY_RE = re.compile(r"\bin \d+(?:\.\d+)?s\b")


def split_round_robin(files, n):
    """Deal files into n groups round-robin; empty groups are dropped."""
    groups = [files[i::n] for i in range(n)]
    return [g for g in groups if g]


def build_env(base=None):
    """Child env: UTF-8 forced, work roots defaulted only when unset."""
    env = dict(os.environ if base is None else base)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("SLINK_WORK_ROOT", DEFAULT_WORK)
    env.setdefault("PYTEST_DEBUG_TEMPROOT", DEFAULT_WORK + "/tmp")
    return env


def _summary(log_text):
    lines = log_text.splitlines()
    timed = [ln.strip() for ln in lines if SUMMARY_RE.search(ln)]
    if timed:
        return timed[-1]
    nonblank = [ln.strip() for ln in lines if ln.strip()]
    return nonblank[-1] if nonblank else "(empty log)"


def run(root, shards, out, extra):
    unit = root / "tests" / "unit"
    files = sorted(p.relative_to(root).as_posix() for p in unit.glob("test_*.py"))
    if not files:
        print(f"no test_*.py under {unit}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    groups = split_round_robin(files, shards)
    env = build_env()
    running = []
    for k, group in enumerate(groups, start=1):
        (out / f"s{k}.files").write_text("\n".join(group) + "\n", encoding="utf-8")
        basetemp = f"--basetemp={out / f'bt{k}'}"
        cmd = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
               basetemp, *group, *extra]
        log = open(out / f"s{k}.log", "wb")  # noqa: SIM115 -- closed after wait
        proc = subprocess.Popen(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT, env=env)
        running.append((k, group, log, proc))

    failures = []
    all_ok = True
    for k, group, log, proc in running:
        rc = proc.wait()
        log.close()
        text = (out / f"s{k}.log").read_text(encoding="utf-8", errors="replace")
        print(f"s{k}: rc={rc} files={len(group)} {_summary(text)}")
        hits = [ln.strip() for ln in text.splitlines() if ln.startswith(("FAILED ", "ERROR "))]
        failures += [f"s{k}: {ln}" for ln in hits]
        if rc != 0 and not hits:
            failures.append(f"s{k}: rc={rc} (no FAILED/ERROR lines; see s{k}.log)")
        all_ok = all_ok and rc == 0

    (out / "failures.txt").write_text("\n".join(failures) + ("\n" if failures else ""),
                                      encoding="utf-8")
    print(f"failures: {len(failures)} -> {out / 'failures.txt'}")
    print("ALL SHARDS PASSED" if all_ok else "SHARD FAILURE")
    return 0 if all_ok else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    p = argparse.ArgumentParser(description="Run tests/unit as parallel pytest shards.")
    p.add_argument("--shards", type=int, default=6)
    p.add_argument("--root", type=pathlib.Path, default=REPO_ROOT)
    p.add_argument("--out", type=pathlib.Path, default=None)
    args = p.parse_args(argv)
    if args.shards < 1:
        p.error("--shards must be >= 1")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = args.out or pathlib.Path(DEFAULT_WORK) / "tmp" / "shards" / stamp
    return run(args.root.resolve(), args.shards, out.resolve(), extra)


if __name__ == "__main__":
    sys.exit(main())
