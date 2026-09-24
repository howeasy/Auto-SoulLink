"""Gen 2 FINAL EVIDENCE SWEEP: every release-required PHYSICAL cell, N lanes at a time, at one frozen sha.

    python tools/gen2_final_sweep.py --list                      # the cells and their exact commands
    python tools/gen2_final_sweep.py --lanes 4                   # everything (run only after "freeze")
    python tools/gen2_final_sweep.py --lanes 2 --only gen2_new/link gen2_new/gen2_admit_wrong_rom   # a dry run
    python tools/gen2_final_sweep.py --pin <out>                 # after review: install the PASS receipts + repin

Cells: every scenario tools/e2e_duo.py registers for C-C (gen2_new), G-S (gen2_gold_silver) and C-G
(gen2_crystal_gold): the duo matrix, the wave-C/D duos and the native trades. Then the client-path live gates:
engine_sites (frame_align, then U1G) and write_window per title, panel/sfx/w6/phone per title, and the live-new-gates
run attestation (tests/live/test_gen2_new_gates.py over every fixture; tests/live/conftest.py writes it). The
qualification receipts bind fixture bytes, not code, so they are not rerun (tools/gen2_code_digest.py: not client-path).
A scenario newly registered in tools/e2e_duo.py (e.g. gen2_evolution) is a cell automatically.

Each lane is a detached worktree C:/Users/howar/AppData/Local/Temp/fs<k> at --sha, short enough for BizHawk's MAX_PATH
(e2e_duo.BIZHAWK_PATH_LIMIT). .cache/gen2-build and .cache/gen2-fixtures are COPIED in, because the ROM must resolve
inside the repo (run_gb_gate._gen2_plan). .cache/{pret,build-tools,downloads} are junctioned. Before every cell the
lane must show no tracked change: a gate rewrites tracked receipts, and those are copied out and then reset.
A cell is retried ONCE, and only on an RNG stall (RNG_STALL). On a timeout only the cell's own process tree is killed
(taskkill /T on its PID).

Output in --out: receipts/<repo-relative path> uses the committed names (duo_<scenario>_<cc|gs|cg>_*, the gates' own
files). summary.json/summary.txt hold the sha, the CODE_DIGEST and per cell: ok, attempts, seconds, reason and every
receipt with its LF sha256 (the pin value). Nothing is committed here. --pin <out> copies the receipts of the PASS
cells into this checkout and rewrites their sha256 in tests/gen2_release_requirements.json and
tests/gen2_live_gate_requirements.json in place (text edit, formatting kept). It also adds the single inspect_run row
when it is missing and lists every receipt no row names. Then commit the exact paths.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "tools"), str(REPO)]
import e2e_duo  # noqa: E402

LANE_ROOT = Path("C:/Users/howar/AppData/Local/Temp")
COPY = ("gen2-build", "gen2-fixtures")
JUNCTION = ("pret", "build-tools", "downloads")
PAIRS = {"gen2_new": "cc", "gen2_gold_silver": "gs", "gen2_crystal_gold": "cg"}
TITLES = ("crystal", "gold", "silver")
# ponytail: the stall phrases seen in lane logs; widen here if a new RNG stall class shows up
# The trainer poison leg (Bug Catcher Wade, G-S poison and Gold's U1 chain) is capped near 83% a fight by the
# 15-HP target (coordinator, re-run pass): a fight that ends unpoisoned retries once like out-of-balls.
RNG_STALL = re.compile(r"out-of-balls|survived \d+ battles|duplicates-only hunt|clause unobserved"
                       r"|the trainer battle ended without a poisoned party mon|poison_faint did not fire")
GATE_TIMEOUT = 3600
PIN_FILES = ("tests/gen2_release_requirements.json", "tests/gen2_live_gate_requirements.json")
ATTESTATION = "tests/fixtures/gen2/receipts/live_new_gates.inspect_run.json"   # tests/live/conftest.py
INSPECT_ROW = """    {
      "id": "new-gates.inspect-run",
      "stage": "physical-live",
      "description": "R-1/R-2/R-3/R-4/R-5g live-new-gates run attestation (gen2-live-new-gates-attestation-v1): SLINK_LIVE=1 pytest tests/live/test_gen2_new_gates.py over every fixture, every title PASS, passes only (re-run: tools/gen2_final_sweep.py cell gate/inspect_run)",
      "axes": {"kind": "inspect_run", "requirement_ids": ["R-1", "R-2", "R-3", "R-4", "R-5g"]},
      "proofs": [{"receipts": {"receipt": {
        "path": "%s",
        "sha256": "%s"
      }}}]
    }"""


def live(test, title):
    return [sys.executable, "-m", "pytest", f"tests/live/{test}", "-q", "-p", "no:randomly", "-k", title]


def cells():
    out = []
    for game, pair in PAIRS.items():
        for scenario in e2e_duo.scenarios_for(game):
            out.append({"id": f"{game}/{scenario}", "kind": "duo", "game": game, "scenario": scenario, "pair": pair,
                        "timeout": e2e_duo.SCENARIOS[scenario]["timeout"] + 600})
    for title in TITLES:
        out.append({"id": f"gate/engine_sites/{title}", "kind": "gate", "timeout": 2 * GATE_TIMEOUT,
                    "commands": [live("test_gen2_frame_align.py", title), live("test_gen2_u1g.py", title)]})
        if title != "silver":   # Silver's write window is Gold's receipt (O-23)
            out.append({"id": f"gate/write_window/{title}", "kind": "gate", "timeout": GATE_TIMEOUT,
                        "commands": [live("test_gen2_write_windows.py", title)]})
        for kind in ("panel", "sfx", "w6", "phone"):
            out.append({"id": f"gate/{kind}/{title}", "kind": "gate", "timeout": GATE_TIMEOUT,
                        "commands": [live(f"test_gen2_{kind}_gate.py", title)]})
    out.append({"id": "gate/inspect_run", "kind": "gate", "timeout": 13 * 900,   # every fixture, one inspect gate each
                "commands": [[sys.executable, "-m", "pytest", "tests/live/test_gen2_new_gates.py", "-q", "-p", "no:randomly"]]})
    return sorted(out, key=lambda c: -c["timeout"])   # longest first


def duo_command(cell, lane):
    return [sys.executable, "tools/e2e_duo.py", "--game", cell["game"], "--scenario", cell["scenario"],
            "--lane", lane, "--keep-data"]


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def _writable(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def drop_lane(path):
    for name in JUNCTION:   # unlink the junctions FIRST: never recurse through one
        junction = path / ".cache" / name
        if junction.exists() or os.path.lexists(junction):
            os.rmdir(junction)
    if path.exists():
        shutil.rmtree(path, onerror=_writable)
    git(REPO, "worktree", "prune")
    # a Drive checkout leaves the admin dir read-only, so prune cannot delete it (the 14 orphans)
    admin = Path(git(REPO, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()) / "worktrees" / path.name
    if admin.exists():
        shutil.rmtree(admin, onerror=_writable)


def make_lane(index, sha):
    path = LANE_ROOT / f"fs{index}"
    if path.exists():
        drop_lane(path)
    git(REPO, "worktree", "add", "--detach", str(path), sha)
    (path / ".cache").mkdir(exist_ok=True)
    for name in COPY:
        shutil.copytree(REPO / ".cache" / name, path / ".cache" / name, symlinks=True)
    for name in JUNCTION:
        subprocess.run(["cmd", "/c", "mklink", "/J", str(path / ".cache" / name), str(REPO / ".cache" / name)],
                       check=True, capture_output=True)
    return path


def tracked_changes(lane):
    return [line[3:] for line in git(lane, "status", "--porcelain", "--untracked-files=no").splitlines()]


def lf_sha256(path):
    raw = path.read_bytes()
    if path.suffix in (".txt", ".json"):
        raw = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def run(cmd, cwd, timeout, log):
    env = dict(os.environ, SLINK_LIVE="1", PYTHONUNBUFFERED="1")
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(cmd)}\n")
        handle.flush()
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT)
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)   # our tree only
            proc.wait()
            return "timeout"


def collect_duo(cell, lane_id, lane, out):
    artifact = f"{cell['scenario']}_{lane_id}"
    stem = f"duo_{cell['scenario'].removeprefix('gen2_')}_{cell['pair']}_"
    got = {}
    for src in sorted((lane / "patch/build").glob(f"e2e_{artifact}_*")):
        suffix = src.name[len(f"e2e_{artifact}_"):]
        if "attempt" in suffix or suffix.endswith(("_exit.SaveRAM", "_link_save.SaveRAM", "manifest.json")):
            continue
        dest = out / "receipts/tests/fixtures/gen2/receipts" / (stem + suffix)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        got[f"tests/fixtures/gen2/receipts/{stem + suffix}"] = lf_sha256(dest)
    return got


def collect_gate(lane, out):
    """Every receipt the gate wrote (changed or new, the attestation included), copied out; the lane is then reset."""
    got = {}
    rows = git(lane, "status", "--porcelain", "--untracked-files=all", "--", "tests/fixtures/gen2/receipts", "data/games")
    for line in rows.splitlines():
        rel = line[3:].strip('"')
        dest = out / "receipts" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(lane / rel, dest)
        got[rel] = lf_sha256(dest)
        if line.startswith("??"):
            (lane / rel).unlink()
    git(lane, "checkout", "--", ".")
    return got


def pin(out, root=REPO):
    """Install the PASS cells' receipts from a sweep's `out` and repin them; returns the receipts no row names."""
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    pins = {rel: sha for cell in summary["cells"] if cell["ok"] for rel, sha in cell.get("receipts", {}).items()}
    for rel in pins:
        shutil.copyfile(out / "receipts" / rel, root / rel)
    named = set()
    for name in PIN_FILES:
        path = root / name
        text = path.read_text(encoding="utf-8")
        for rel, sha in pins.items():
            pattern = re.compile(r'("path": "' + re.escape(rel) + r'",\s*"sha256": ")[0-9a-f]{64}"')
            text, hits = pattern.subn(lambda m, sha=sha: m.group(1) + sha + '"', text)
            if hits:
                named.add(rel)
        if name.endswith("live_gate_requirements.json") and ATTESTATION in pins and '"kind": "inspect_run"' not in text:
            at = text.rindex("\n  ]")
            text = text[:at] + ",\n" + INSPECT_ROW % (ATTESTATION, pins[ATTESTATION]) + text[at:]
            named.add(ATTESTATION)
        path.write_text(text, encoding="utf-8", newline="\n")
    return sorted(rel for rel in pins if rel not in named and rel.endswith((".txt", ".json")))


def run_commands(commands, lane, timeout, log):
    """Run a cell's commands in order and stop at the first failure. Every gate result file a command wrote
    (patch/build/*_result.txt) is kept next to the log as <log stem>.cmd<i>.<name>. U1G reuses
    gen2_frame_align_result.txt, so without this copy a failing frame_align trace is overwritten."""
    def stamps():   # compared by value: Windows file times tick coarser than time.time()
        return {p: p.stat().st_mtime_ns for p in (lane / "patch/build").glob("*_result.txt")
                if not p.name.startswith("e2e_")}

    codes = []
    for index, cmd in enumerate(commands, 1):
        before = stamps()
        codes.append(run(cmd, lane, timeout, log))
        for result, stamp in stamps().items():
            if before.get(result) != stamp:
                shutil.copyfile(result, log.with_name(f"{log.stem}.cmd{index}.{result.name}"))
        if codes[-1] != 0:
            break
    return codes


def run_cell(cell, lane, n, out, stagger):
    lane_id = f"s{n}"   # unique per cell: e2e_duo refuses to overwrite a lane's archived witnesses
    log = out / "logs" / (cell["id"].replace("/", "__") + ".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    result = {"id": cell["id"], "lane": lane.name, "attempts": 0, "ok": False}
    started = time.time()
    for attempt in (1, 2):
        dirty = tracked_changes(lane)
        if dirty:
            result["reason"] = f"lane not clean: {dirty[:3]}"
            break
        stagger()
        result["attempts"] = attempt
        commands = [duo_command(cell, f"{lane_id}{attempt}")] if cell["kind"] == "duo" else cell["commands"]
        codes = run_commands(commands, lane, cell["timeout"], log)
        result["ok"] = all(code == 0 for code in codes)
        if cell["kind"] == "duo":
            result["receipts"] = collect_duo(cell, f"{lane_id}{attempt}", lane, out)
        else:
            result["receipts"] = collect_gate(lane, out)
        text = log.read_text(encoding="utf-8", errors="replace")
        result["reason"] = "PASS" if result["ok"] else f"exit {codes}"
        if result["ok"] or attempt == 2 or not RNG_STALL.search(text.split(f"$ {' '.join(commands[0])}")[-1]):
            break
        result["retried"] = RNG_STALL.search(text).group(0)
    result["seconds"] = round(time.time() - started)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--list", action="store_true", help="print the cells and their commands, run nothing")
    parser.add_argument("--lanes", type=int, default=4)
    parser.add_argument("--sha", default="HEAD")
    parser.add_argument("--only", nargs="*", help="cell ids (exact) to run instead of all")
    parser.add_argument("--stagger", type=float, default=10.0, help="seconds between cell starts (preflight ~9 s)")
    parser.add_argument("--out", type=Path, default=LANE_ROOT / f"fsw-{time.strftime('%m%d-%H%M')}")
    parser.add_argument("--pin", type=Path, metavar="OUT", help="install and repin a finished sweep's PASS receipts")
    args = parser.parse_args(argv)
    if args.pin:
        loose = pin(args.pin)
        print("[sweep] pinned; receipts no requirement row names:" if loose else "[sweep] pinned; every receipt named")
        print("\n".join(loose))
        return 0
    todo = [c for c in cells() if not args.only or c["id"] in args.only]
    if args.only and len(todo) != len(set(args.only)):
        parser.error(f"unknown cell(s): {sorted(set(args.only) - {c['id'] for c in todo})}")
    if args.list:
        for c in todo:
            cmds = [duo_command(c, "<lane>")] if c["kind"] == "duo" else c["commands"]
            print(c["id"], " && ".join(" ".join(cmd[1:] if cmd[0] == sys.executable else cmd) for cmd in cmds))
        print(f"{len(todo)} cells")
        return 0
    sha = git(REPO, "rev-parse", args.sha).strip()
    from tools import gen2_code_digest
    digest = gen2_code_digest.head_digest(REPO, sha)
    args.out.mkdir(parents=True, exist_ok=True)
    lanes = queue.Queue()
    for index in range(1, min(args.lanes, len(todo)) + 1):
        lanes.put(make_lane(index, sha))
    last, lock = [0.0], threading.Lock()

    def stagger():
        with lock:
            wait = last[0] + args.stagger - time.time()
            if wait > 0:
                time.sleep(wait)
            last[0] = time.time()

    def work(n, cell):
        lane = lanes.get()
        try:
            result = run_cell(cell, lane, n, args.out, stagger)
        finally:
            lanes.put(lane)
        print(f"[sweep] {'PASS' if result['ok'] else 'FAIL'} {cell['id']} {result.get('seconds')}s "
              f"attempts={result['attempts']} {result.get('reason')}", flush=True)
        return result

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=lanes.qsize()) as pool:
            results = list(pool.map(work, range(len(todo)), todo))
    finally:
        while not lanes.empty():
            drop_lane(lanes.get())
    summary = {"sha": sha, "code_digest": digest, "lanes": args.lanes, "cells": results}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8", newline="\n")
    lines = [f"sha {sha}  code_digest {digest}  lanes {args.lanes}"]
    lines += [f"{'PASS' if r['ok'] else 'FAIL'}  {r['id']}  {r.get('seconds')}s  attempts={r['attempts']}  {r.get('reason')}"
              for r in results]
    (args.out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    print(f"[sweep] out: {args.out}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
