#!/usr/bin/env python3
"""run_gate.py — launch ONE headless BizHawk gate script and report PASS/FAIL.

The `lua/tests/test_live_*.lua` / `test_mailbox_*.lua` gates each drive the emulator,
write an incremental `<repo>/patch/build/<something>_result.txt` whose final line is
`RESULT: PASS|FAIL ...`, then `client.exit()`.  This is the single launcher for them —
used both by hand and by `tests/live/test_lua_gates.py`.

    python tools/run_gate.py lua/tests/test_mailbox_ping.lua
    python tools/run_gate.py lua/tests/test_live_memorialize.lua --timeout 300

Why a launcher at all: BizHawk 2.11.1 reports `debug.getinfo(1,"S").source == "main"`
for a `--lua=` script, so a gate cannot self-locate the repo.  `os.getenv` DOES work and
inherits from the parent, so we export SLINK_ROOT here and the gate reads it.

Launch rules (hard-won, same as tools/e2e_duo.py): cwd = repo root with RELATIVE EmuHawk
arg paths — absolute paths containing the "Google Drive" space break BizHawk's CLI parser.
Absolute paths are fine INSIDE Lua.  A per-run --config copy avoids the shared config.ini
write race when gates run back to back.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMUHAWK = os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe")
BIZHAWK_CONFIG = os.environ.get("SLINK_BIZHAWK_CONFIG", "E:/Howard/Bizhawk/config.ini")
BUILD = os.path.join(REPO, "patch", "build")
DEFAULT_ROM = "patch/build/slink_RR.gba"


def _results_snapshot():
    """mtimes of every *_result.txt so we can tell which one THIS run wrote."""
    return {p: os.path.getmtime(p) for p in glob.glob(os.path.join(BUILD, "*_result.txt"))}


def _verdict_in(after, before):
    """True once some *_result.txt this run touched ends in a RESULT: line."""
    for p, m in after.items():
        if before.get(p) == m:
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                if any(ln.strip().startswith("RESULT:") for ln in f):
                    return True
        except OSError:
            pass
    return False


def run_gate(script, rom=DEFAULT_ROM, timeout=240, quiet=False):
    """Run one gate. Returns (passed: bool, result_path: str|None, text: str)."""
    if not os.path.exists(EMUHAWK):
        raise FileNotFoundError(f"EmuHawk not found at {EMUHAWK} (set $SLINK_EMUHAWK)")
    if not os.path.exists(os.path.join(REPO, rom)):
        raise FileNotFoundError(f"ROM not found: {rom} (build it: python patch/tools/build.py)")
    os.makedirs(BUILD, exist_ok=True)
    tag = os.path.splitext(os.path.basename(script))[0]
    cfg_rel = f"patch/build/gate_cfg_{tag}.ini"
    shutil.copyfile(BIZHAWK_CONFIG, os.path.join(REPO, cfg_rel))

    before = _results_snapshot()
    env = dict(os.environ, SLINK_ROOT=REPO.replace("\\", "/"))
    cmd = [EMUHAWK, f"--config={cfg_rel}", f"--lua={script}", rom]
    if not quiet:
        print(f"[gate] {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    while proc.poll() is None and time.time() - t0 < timeout:
        time.sleep(1.0)
        # Don't wait on the process once the gate has published its verdict: a script that
        # fails to exit cleanly would otherwise burn the entire timeout for a finished run.
        if _verdict_in(_results_snapshot(), before):
            break
    hung = proc.poll() is None and not _verdict_in(_results_snapshot(), before)
    if proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    # The gate names its own result file; find whichever one this run touched.
    after = _results_snapshot()
    fresh = [p for p, m in after.items() if before.get(p) != m]
    path = max(fresh, key=os.path.getmtime) if fresh else None
    text = ""
    if path:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    verdict = next((ln for ln in reversed(text.splitlines())
                    if ln.strip().startswith("RESULT:")), "")
    passed = verdict.strip().startswith("RESULT: PASS") and not hung
    if not quiet:
        elapsed = time.time() - t0
        if hung:
            print(f"[gate] TIMEOUT after {timeout}s — killed")
        print(f"[gate] {tag}: {verdict or '(no RESULT line)'}  ({elapsed:.0f}s)")
    return passed, path, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script", help="path to the gate, relative to the repo root")
    ap.add_argument("--rom", default=DEFAULT_ROM)
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()
    passed, path, text = run_gate(args.script, args.rom, args.timeout)
    if text and not passed:
        print("--- result ---")
        print(text[-3000:])
    elif path:
        print(f"--- {os.path.relpath(path, REPO)} ---")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
