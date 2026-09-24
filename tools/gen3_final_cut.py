#!/usr/bin/env python3
"""gen3_final_cut.py -- the G4 final-cut pass as one command (card G4-FINALCUT-RUNNER).

    python tools/gen3_final_cut.py --cut <sha>                     # the whole pass
    python tools/gen3_final_cut.py --cut <sha> --dry-run           # print the plan, launch nothing
    python tools/gen3_final_cut.py --cut <sha> --resume            # skip rows already PASSed at <sha>
    python tools/gen3_final_cut.py --cut <sha> --rows 'item2b*,checkpoint_*' --stop-at 2026-09-25T06:00Z
    python tools/gen3_final_cut.py --cut <sha> --list              # the row ids

docs/gen3/G4_final_cut_runbook.md §0-§11 is the source of every row; §12 names the gaps this closes.
Sequential, one emulator lane (docs/gen3/PLAN.md:23). Order: provision the lane at --cut (and the
master tree when item 6 is selected), then every selected row in runbook order. Each row writes
docs/gen3/probes/fc_<row>_<cut8>.txt through gen3_probe_receipt.run_receipt_text, and the pass
rewrites docs/gen3/probes/fc_SUMMARY_<cut8>.txt after every row.

Rules this runner enforces itself:
  - the lane must be at --cut with `git status --porcelain --untracked-files=no` empty, or the
    pass aborts before any row; a row that leaves the lane tracked-dirty fails and aborts the pass;
  - an unchanged failed row is never re-run automatically: one retry only when the failure is a
    CPU-contention timeout (classify_failure), and a FAIL receipt at the same cut blocks the row
    on later invocations too (move the receipt aside to re-run it deliberately);
  - it kills only the process trees it launched (taskkill /PID <its own child> /T), never by name;
  - rewind off: every BizHawk config a row wrote under the lane's patch/build is read back and a
    `Rewind.Enabled` that is not false fails the row;
  - a SKIP is a failure unless ALLOWED_SKIPS names the row with an owner ruling.

Helper subcommands the plan itself calls (they are rows like any other):
    python tools/gen3_final_cut.py zip-boot --zip <zip> --lane <lane>        (runbook §9 boot step)
    python tools/gen3_final_cut.py item6 --branch <lane> --master <tree>     (runbook §10)
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fnmatch
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import gen3_probe_receipt as receipts  # noqa: E402

REPO = os.path.dirname(_HERE)
PROBES = os.path.join(REPO, "docs", "gen3", "probes")
PY = sys.executable

STAGED = {"firered": "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba",
          "leafgreen": "patch/build/gen3_Pokemon_-_LeafGreen_Version_(USA).gba"}
ROOT_DUMPS = {"firered": "Pokemon - FireRed Version (USA).gba",
              "leafgreen": "Pokemon - LeafGreen Version (USA).gba"}
# Runbook §0.3 plus item 6's inputs (item6_route_diff_{branch,master}_2026-09-24.txt): gitignored,
# copied from the main checkout by the same relative path when the tree lacks them. No .cache item
# is read by any row here (the only .cache consumer in e2e_duo is the Gen 1 randomizer's UPR jar).
GITIGNORED_INPUTS = [ROOT_DUMPS["firered"], ROOT_DUMPS["leafgreen"],
                     "Pokemon - Crystal Version (USA).gbc",
                     "patch/build/gen1_red.gb", "patch/build/gen1_blue.gb",
                     "patch/build/gen1_yellow.gbc", "patch/build/gen2_crystal.gbc",
                     "patch/gen1/build/slink_red.gb", "patch/gen1/build/slink_blue.gb",
                     "patch/gen1/build/slink.sym"]

# (row-id glob, reason substring the output must carry, the owner ruling that signs it)
ALLOWED_SKIPS = [
    ("linked_faint_active_mega_gen3_*", "R5 needs an RR trainer route",
     "owner ruling 20 (G4_request_draft.md §6): RR row R5 is a signed G5 limit, kept as a named SKIP"),
]

ORIENT = {"gen3_frlg": "fr_as_a", "gen3_lgfr": "lg_as_a"}


@dataclass
class Row:
    id: str
    item: str              # runbook section tag, e.g. "§5 item2b"
    argv: list
    cwd: str
    budget: int            # seconds before the runner kills the row's own process tree
    env: dict = field(default_factory=dict)
    emulator: bool = True
    # True: the tool applies its own fail-closed skip policy and its exit code is the verdict
    # (verify_gen3_release's ALLOWED_SKIPS; item6, whose case outputs may legitimately skip)
    own_verdict: bool = False

    def command(self):
        return shlex.join(["python" if a == PY else a for a in self.argv])


# ---------------------------------------------------------------------------
# the plan (runbook §1-§11, in order)
# ---------------------------------------------------------------------------

FALLBACK_DUO_BUDGET = 4 * 3600


def duo_budget(scenario, game):
    """The runner's backstop for one duo row: e2e_duo's own per-attempt timeout x its attempt
    limit, plus 15 min of boot/teardown. e2e_duo enforces the real bound itself; this only has to
    be above it. Read lazily from this repo's copy -- if that copy does not import (another worker
    mid-edit), a flat 4 h backstop keeps --dry-run and the plan usable."""
    try:
        import e2e_duo
        limit = e2e_duo.scenario_attempt_limit(scenario, e2e_duo.GAMES[game]["game"])
        return e2e_duo.SCENARIOS[scenario]["timeout"] * limit + 900
    except Exception:
        return FALLBACK_DUO_BUDGET


def _duo(scenario, game, item, lane):
    return Row(f"{scenario}_{ORIENT[game]}", item,
               [PY, "tools/e2e_duo.py", "--game", game, "--scenario", scenario], lane,
               duo_budget(scenario, game))


def build_plan(cut, lane, master):
    cut8 = cut[:8]
    rows = []
    # §1.1 probe states, §1.2 tutorial states (the bw rows' SLINK_BW_HASHES is hashed from these
    # by gen3_bw_hashes.py, which gen3_probe_receipt.py runs before each probe row)
    for title in ("firered", "leafgreen"):
        for kind in ("town", "battle"):
            rows.append(Row(f"states_{title}_{kind}", "§1.1 build",
                            [PY, "tools/mkstates_gen3.py", "--title", title, "--kind", kind,
                             "--out-dir", f"{lane}/patch/build/gen3_probe_states_c4p2/{title}",
                             "--rom", STAGED[title]], lane, 600))
    for title in ("firered", "leafgreen"):
        rows.append(Row(f"tutorials_{title}", "§1.2 build",
                        [PY, "tools/mkstates_gen3_tutorials.py", "--title", title,
                         "--out-dir", f"{lane}/patch/build/gen3_probe_states/{title}"], lane, 900))
    # §2 item 1 + §3 item 2 (faint_cmd is §2's row; whiteout moves to §4, linked_faint_active to §5)
    for s in ("faint_cmd_gen3", "link_gen3", "boxsync_gen3", "reconnect_gen3", "deadzone_gen3"):
        rows.append(_duo(s, "gen3_frlg", "§2-3 item1-2", lane))
    # §4 item 2a, both orientations
    for s in ("whiteout_gen3", "center_controls_gen3"):
        for game in ("gen3_frlg", "gen3_lgfr"):
            rows.append(_duo(s, game, "§4 item2a", lane))
    # §5 item 2b: mechanism P+H (owner rulings 15-16/19/21) supersedes the T2/A2 hold plan
    # (G4_request_draft.md, 4aaaee7e): A1, A2 and the new whiteout/trainer rows, both orientations
    for s in ("linked_faint_active_gen3", "active_end_gen3", "linked_faint_active_whiteout_gen3",
              "linked_faint_active_trainer_gen3"):
        for game in ("gen3_frlg", "gen3_lgfr"):
            rows.append(_duo(s, game, "§5 item2b", lane))
    # §6 item 3: the full FRLG checkpoint probe (base + bw rows) via the receipt wrapper
    for title, short in (("firered", "fr"), ("leafgreen", "lg")):
        rows.append(Row(f"checkpoint_{title}", "§6 item3",
                        [PY, "tools/gen3_probe_receipt.py", "--title", title, "--lane", lane,
                         "--out", f"checkpoint_{short}_clean_{cut8}.txt"], REPO, 1800))
    # §7 §3.2 save rows (rows 3/6 ride §4's center_controls runs)
    for game in ("gen3_frlg", "gen3_lgfr"):
        rows.append(_duo("save_then_write_gen3", game, "§7 save-rows", lane))
    # §8 item 4: cold-boot admission 8/8
    for title in ("firered", "leafgreen"):
        for scene in ("town", "battle"):
            for side in ("", "_b"):
                fx = f"{title}_party_{scene}{side}"
                rows.append(Row(f"bootcheck_{fx}", "§8 item4",
                                [PY, "tools/gen3_fixtures.py", "boot-check", "--rom", STAGED[title],
                                 "--fixture", f"tests/fixtures/gen3/{fx}.sav", "--title", title],
                                lane, 600))
    # §9 item 5: the zip built FROM the cut, checked AT the cut, then booted
    zip_path = f"{lane}/dist/SLink-player-g4-{cut8}.zip"
    rows += [Row("zip_build", "§9 item5",
                 [PY, "tools/make_release.py", "--version", f"g4-{cut8}", "--out", f"{lane}/dist",
                  "--skip-generators"], lane, 600, emulator=False),
             Row("zip_check", "§9 item5",
                 [PY, "tools/check_release_zip.py", zip_path, "--rev", cut], lane, 300,
                 emulator=False),
             Row("zip_boot_firered", "§9 item5",
                 [PY, "tools/gen3_final_cut.py", "zip-boot", "--zip", zip_path, "--lane", lane],
                 REPO, 600)]
    # §10 item 6: route-differential against master
    rows.append(Row("item6_route_diff", "§10 item6",
                    [PY, "tools/gen3_final_cut.py", "item6", "--branch", lane, "--master", master],
                    REPO, 5400, own_verdict=True))
    # §11: the release gate's source lanes, then its P1 hook-probe lane (the duo lane is the
    # rows above, run one scenario at a time instead of through its pytest wrapper)
    rows += [Row("release_gate_quick", "§11 gate",
                 [PY, "tools/verify_gen3_release.py", "--quick"], lane, 3600, emulator=False,
                 own_verdict=True),
             Row("probe_gates", "§11 gate",
                 [PY, "-m", "pytest", "tests/live/test_gen3_probe_gates.py", "-q", "-p",
                  "no:randomly", "-rs"], lane, 3600, env={"SLINK_LIVE": "1"})]
    return rows


def select_rows(rows, spec):
    """--rows: comma list of row-id globs or item tags (e.g. 'item2b'); runbook order kept."""
    if not spec:
        return rows
    pats = [p.strip() for p in spec.split(",") if p.strip()]
    picked = [r for r in rows
              if any(fnmatch.fnmatch(r.id, p) or p in r.item.split() for p in pats)]
    unknown = [p for p in pats
               if not any(fnmatch.fnmatch(r.id, p) or p in r.item.split() for r in rows)]
    if unknown:
        raise SystemExit(f"--rows: nothing matches {', '.join(unknown)}")
    return picked


# ---------------------------------------------------------------------------
# verdicts: the SKIP policy and the retry classifier
# ---------------------------------------------------------------------------

_TIMEOUT_SIGNS = ("timed out after", "[gate] TIMEOUT after", "[final_cut] BUDGET EXCEEDED")
# a side or oracle that reached a verdict failed: the run was not starved, it was wrong
_REAL_SIGNS = ("RESULT: FAIL", "AssertionError", "a client finished before", "BOOT-CHECK FAIL")


def classify_failure(output, budget_killed=False):
    """'contention' only for a timeout (a harness wait or the runner's own budget) with no
    failing verdict anywhere in the output; everything else is 'real' and is never retried.
    ponytail: CPU load is recorded in the receipt, not gated on -- the shared machine sits at
    90%+ on good runs too; gate on it if a real failure ever gets classified as contention."""
    text = output or ""
    timed_out = budget_killed or any(s in text for s in _TIMEOUT_SIGNS)
    # a crash is real too, unless the traceback is the harness's own TimeoutError
    real = any(s in text for s in _REAL_SIGNS) or \
        ("Traceback (most recent call last)" in text and "TimeoutError" not in text)
    return "contention" if timed_out and not real else "real"


def detect_skip(rc, output):
    """True when the row skipped instead of running: e2e_duo's exit 3 / 'name: SKIP' summary
    line, or a pytest summary that counts a skip."""
    text = output or ""
    return (rc == 3 or bool(re.search(r"^\s+\S+: SKIP\b", text, re.M))
            or bool(re.search(r"\b\d+ skipped\b", text)))


def allowed_skip(row_id, output):
    """The ruling that excuses this row's SKIP, or None (then the SKIP is a failure)."""
    for pat, reason, ruling in ALLOWED_SKIPS:
        if fnmatch.fnmatch(row_id, pat) and reason in (output or ""):
            return ruling
    return None


def judge(row_id, rc, output, budget_killed=False, own_verdict=False):
    """(verdict, passed). PASS needs exit 0 with no skip; a SKIP passes only via ALLOWED_SKIPS."""
    if budget_killed:
        return "FAIL budget exceeded (runner killed its own process tree)", False
    if not own_verdict and detect_skip(rc, output):
        ruling = allowed_skip(row_id, output)
        if ruling and rc in (0, 3):
            return f"SKIP-ALLOWED {ruling}", True
        return "FAIL skipped, and ALLOWED_SKIPS does not excuse it", False
    if rc == 0:
        return "PASS", True
    return f"FAIL exit={rc}", False


def receipt_path(row_id, cut):
    return os.path.join(PROBES, f"fc_{row_id}_{cut[:8]}.txt")


def prior_verdict(row_id, cut):
    """The verdict of this row's runner receipt at this exact cut, or None."""
    got = receipts.read_run_receipt(receipt_path(row_id, cut))
    return got["verdict"] if got and got["cut"] == cut else None


# ---------------------------------------------------------------------------
# the lane: provision/verify, gitignored inputs
# ---------------------------------------------------------------------------

class LaneError(RuntimeError):
    pass


def _git(tree, *args, check=True):
    p = subprocess.run(["git", "-C", tree, *args], capture_output=True, text=True)
    if check and p.returncode:
        raise LaneError(f"git -C {tree} {' '.join(args)}: {p.stderr.strip() or p.returncode}")
    return p


def tracked_clean(tree):
    return _git(tree, "status", "--porcelain", "--untracked-files=no").stdout.strip() == ""


def head(tree):
    return _git(tree, "rev-parse", "HEAD").stdout.strip()


def main_checkout():
    common = _git(REPO, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return os.path.dirname(common)


def provision_plan(tree, rev):
    """The commands provision() may run, for --dry-run."""
    return [f"git worktree add --detach {tree} {rev}   (only if {tree} does not exist)",
            f"git -C {tree} status --porcelain --untracked-files=no   (must be empty, else abort)",
            f"git -C {tree} checkout --detach {rev}   (if HEAD differs)",
            f"git -C {tree} update-ref --no-deref HEAD {rev}   (fallback: the broken shared ref)",
            f"git -C {tree} read-tree {rev} && git -C {tree} checkout-index -a -f   (fallback)",
            f"copy missing gitignored inputs from the main checkout: {', '.join(GITIGNORED_INPUTS)}",
            f"stage {STAGED['firered']} / {STAGED['leafgreen']} from the root dumps"]


def provision(tree, rev, root):
    """Put `tree` detached at `rev`, tracked-clean. A tree that is already tracked-dirty is never
    touched (someone else's work, or a broken lane): LaneError, and the pass aborts.

    The fallbacks are W3's (item6_route_diff_branch_2026-09-24.txt): the shared repo's broken ref
    refs/heads/codex/gen2-foundation (1) makes checkout die AFTER it updated index and tree, so
    HEAD is moved with update-ref; a tree that is still off afterwards is re-read from the commit."""
    sha = _git(root, "rev-parse", f"{rev}^{{commit}}").stdout.strip()
    if not os.path.isdir(tree):
        _git(root, "worktree", "add", "--detach", tree, sha, check=False)
        if not os.path.isdir(tree):
            raise LaneError(f"git worktree add could not create {tree}")
    elif not tracked_clean(tree):
        raise LaneError(f"{tree} is tracked-dirty before provisioning; refusing to touch it")
    elif head(tree) != sha:
        _git(tree, "checkout", "--detach", sha, check=False)
    if head(tree) != sha:
        _git(tree, "update-ref", "--no-deref", "HEAD", sha)
    if not tracked_clean(tree) or _git(tree, "diff", "--quiet", sha, check=False).returncode:
        _git(tree, "read-tree", sha)
        _git(tree, "checkout-index", "-a", "-f")
    if head(tree) != sha or not tracked_clean(tree):
        raise LaneError(f"{tree} is not a clean detached checkout of {sha} after provisioning")
    return sha


def copy_inputs(tree, root):
    """Copy each gitignored input the tree lacks (or has at a different size) from `root`, and
    stage the FR/LG dumps under patch/build. A missing source fails closed."""
    pairs = [(p, p) for p in GITIGNORED_INPUTS] + \
            [(ROOT_DUMPS[t], STAGED[t]) for t in ("firered", "leafgreen")]
    for src_rel, dst_rel in pairs:
        src, dst = os.path.join(root, src_rel), os.path.join(tree, dst_rel)
        if not os.path.isfile(src):
            raise LaneError(f"gitignored input missing from {root}: {src_rel}")
        if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)


# ---------------------------------------------------------------------------
# running one row
# ---------------------------------------------------------------------------

def utcnow():
    return dt.datetime.now(dt.UTC)


def parse_utc(text):
    t = dt.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def load_snapshot():
    """cpu%, EmuHawk and python counts, the ph_* receipts' LOAD line. Best effort."""
    ps = ("$c=(Get-CimInstance Win32_Processor|Measure-Object LoadPercentage -Average).Average;"
          "$e=@(Get-Process EmuHawk -EA SilentlyContinue).Count;"
          "$p=@(Get-Process python -EA SilentlyContinue).Count;"
          "\"cpu=$c% emuhawk=$e python=$p\"")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, timeout=20).stdout.strip()
    except Exception:
        out = ""
    return f"{dt.datetime.now():%Y-%m-%dT%H:%M:%S} {out or '(unavailable)'}"


def kill_tree(pid):
    """Only the tree rooted at a PID this runner launched -- never an image-name kill (a
    `taskkill /IM EmuHawk.exe` wiped five Gen 2 runs on 2026-09-23)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        with contextlib.suppress(OSError):
            os.killpg(pid, 9)


def rewind_violations(tree, since):
    """BizHawk configs under <tree>/patch/build written since `since` whose rewind is not off."""
    bad = []
    for dirpath, _dirs, files in os.walk(os.path.join(tree, "patch", "build")):
        for name in files:
            path = os.path.join(dirpath, name)
            if not name.endswith(".ini") or os.path.getmtime(path) < since:
                continue
            try:
                with open(path, encoding="utf-8-sig") as f:
                    cfg = json.load(f)
            except (OSError, ValueError):
                continue           # not a BizHawk JSON config
            if (cfg.get("Rewind") or {}).get("Enabled") is not False:
                bad.append(path)
    return bad


def run_once(row, deadline):
    """(rc, output, budget_killed, stopped). Streams the child's output to our stdout."""
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
        else {"start_new_session": True}
    proc = subprocess.Popen(row.argv, cwd=row.cwd, env=dict(os.environ, **row.env),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", **kw)
    chunks = []

    def pump():
        for line in proc.stdout:
            chunks.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()
    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    budget_end = time.time() + row.budget
    killed = stopped = False
    while proc.poll() is None:
        now = time.time()
        if now >= budget_end or (deadline and now >= deadline):
            stopped = not (now >= budget_end)
            killed = not stopped
            kill_tree(proc.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=60)
            break
        time.sleep(1.0)
    reader.join(timeout=30)
    out = "".join(chunks)
    if killed:
        out += f"\n[final_cut] BUDGET EXCEEDED after {row.budget}s: killed PID {proc.pid} tree\n"
    if stopped:
        out += f"\n[final_cut] --stop-at reached: killed PID {proc.pid} tree\n"
    return proc.returncode, out, killed, stopped


def run_row(row, cut, lane, deadline):
    """Run one row (plus at most one contention retry), write its receipt, return the verdict."""
    attempts, verdict = [], ""
    for attempt in (1, 2):
        before = tracked_clean(lane)
        start, t0 = utcnow(), time.time()
        a = {"load": load_snapshot(), "start_utc": f"{start:%Y-%m-%dT%H:%M:%SZ}",
             "tracked_before": before}
        print(f"\n[final_cut] === {row.id} attempt {attempt}  $ {row.command()}  (cwd={row.cwd})")
        rc, out, killed, stopped = run_once(row, deadline)
        a.update(rc=rc, output=out, end_utc=f"{utcnow():%Y-%m-%dT%H:%M:%SZ}",
                 tracked_after=tracked_clean(lane))
        rewind = rewind_violations(lane, t0 - 2)
        if stopped:
            verdict, cls = "STOPPED (--stop-at)", "stopped"
        else:
            verdict, ok = judge(row.id, rc, out, killed, row.own_verdict)
            cls = "pass" if ok else classify_failure(out, killed)
            if ok and rewind:
                verdict, cls = f"FAIL rewind on in {', '.join(rewind)}", "real"
            if not a["tracked_after"]:
                verdict, cls = "FAIL the lane is tracked-dirty after the row", "real"
        a["classification"] = cls
        attempts.append(a)
        if cls != "contention" or attempt == 2 or (deadline and time.time() >= deadline):
            break
        print(f"[final_cut] {row.id}: contention timeout -> the one allowed retry")
    with open(receipt_path(row.id, cut), "w", encoding="utf-8") as f:
        f.write(receipts.run_receipt_text(row=row.id, item=row.item.replace(" ", "_"), cut=cut,
                                          lane=lane, command=row.command(), cwd=row.cwd,
                                          env=row.env, attempts=attempts, verdict=verdict))
    return verdict, len(attempts), attempts[-1]["tracked_after"]


def write_summary(cut, results):
    lines = [f"# G4 final cut {cut} -- tools/gen3_final_cut.py summary "
             f"(written {utcnow():%Y-%m-%dT%H:%M:%SZ})", "",
             "| # | row | runbook | verdict | attempts | receipt |", "|---|---|---|---|---|---|"]
    for i, (row, verdict, n, rec) in enumerate(results, 1):
        lines.append(f"| {i} | {row.id} | {row.item} | {verdict} | {n} | {rec} |")
    passed = all(v.startswith(("PASS", "SKIP-ALLOWED")) for _r, v, _n, _p in results)
    lines += ["", f"OVERALL: {'PASS' if passed and results else 'FAIL'} "
                  f"({sum(v.startswith(('PASS', 'SKIP-ALLOWED')) for _r, v, _n, _p in results)}"
                  f"/{len(results)} rows)"]
    path = os.path.join(PROBES, f"fc_SUMMARY_{cut[:8]}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path, passed


# ---------------------------------------------------------------------------
# helper subcommand: §9's zip boot
# ---------------------------------------------------------------------------

_BOOT_LUA = """-- gen3_final_cut zip-boot bootstrap: tap A through the title/CONTINUE, then the shipped entry
for f = 1, 1500 do
  if f >= 300 and f % 30 < 3 then joypad.set({A = true}) end
  emu.frameadvance()
end
dofile(os.getenv("SLINK_ZIPBOOT_ENTRY"))
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def zip_boot(zip_path, lane, timeout=300):
    """Extract the zip to a space-free temp dir, run the cut's server from the lane, boot the
    FR dump on the extracted lua/slink.lua with the FR town fixture seeded, and PASS on the
    client's `(clean by hash) player a` + `TCP connected` and the server's `hello rom=firered`
    (release_zip_boot_fr_rehearsal_2026-09-23.txt). Kills only the two PIDs it launched."""
    import gen3_fixtures
    import run_gate
    tmp = tempfile.mkdtemp(prefix="slink_zipboot_")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(os.path.join(tmp, "extract"))
    entry = next((os.path.join(d, "slink.lua") for d, _s, fs in os.walk(os.path.join(tmp, "extract"))
                  if "slink.lua" in fs and d.replace("\\", "/").endswith("/lua")), None)
    if not entry:
        print("RESULT: FAIL the zip has no lua/slink.lua")
        return 1
    lua_log = os.path.join(os.path.dirname(os.path.dirname(entry)), "slink_lua.log")
    saveram = os.path.join(tmp, "saveram")
    os.makedirs(saveram)
    fixture = os.path.join(lane, "tests", "fixtures", "gen3", "firered_party_town.sav")
    with open(fixture, "rb") as f:
        body = gen3_fixtures.codec.split_rtc(f.read())[0]
    with open(os.path.join(saveram, gen3_fixtures.PARTY_TITLES["firered"]["saveram"]), "wb") as f:
        f.write(body)
    cfg = os.path.join(tmp, "config.ini")
    gen3_fixtures.write_gba_run_config(run_gate.BIZHAWK_CONFIG, cfg, saveram)
    with open(cfg, encoding="utf-8") as f:
        if (json.load(f).get("Rewind") or {}).get("Enabled") is not False:
            print("RESULT: FAIL the generated config does not have rewind off")
            return 1
    shutil.copyfile(os.path.join(lane, STAGED["firered"]), os.path.join(tmp, "fr.gba"))
    with open(os.path.join(tmp, "boot.lua"), "w", encoding="utf-8") as f:
        f.write(_BOOT_LUA)
    tcp, http = _free_port(), _free_port()
    server_log = os.path.join(tmp, "server.log")
    print(f"zip={zip_path}\nextract={tmp}\\extract entry={entry}\nfixture={fixture}\n"
          f"server: python -m server.server --port {tcp} --http-port {http} (cwd={lane})")
    procs = []
    try:
        with open(server_log, "w", encoding="utf-8") as log:
            procs.append(subprocess.Popen(
                [PY, "-m", "server.server", "--host", "127.0.0.1", "--port", str(tcp),
                 "--http-port", str(http), "--data-dir", os.path.join(tmp, "data")],
                cwd=lane, stdout=log, stderr=subprocess.STDOUT))
        time.sleep(3)
        env = dict(os.environ, SLINK_HOST="127.0.0.1", SLINK_PORT=str(tcp), SLINK_PLAYER="a",
                   SLINK_ZIPBOOT_ENTRY=entry.replace("\\", "/"))
        cmd = [run_gate.EMUHAWK, "--config=config.ini", "--lua=boot.lua", "fr.gba"]
        print(f"[zip-boot] {' '.join(cmd)}  (cwd={tmp})")
        procs.append(subprocess.Popen(cmd, cwd=tmp, env=env, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
        client_re = re.compile(r"\[SLink-gen3\] gen3_frlg/firered \(clean by hash\) player a ")
        end, ok = time.time() + timeout, False
        while time.time() < end and not ok:
            time.sleep(2)
            ltxt = _read(lua_log)
            ok = bool(client_re.search(ltxt)) and "TCP connected" in ltxt and \
                "hello rom=firered" in _read(server_log)
    finally:
        for p in reversed(procs):
            if p.poll() is None:
                kill_tree(p.pid)
    print(f"--- {lua_log} ---\n{_read(lua_log)}\n--- server log ---\n{_read(server_log)}")
    print("RESULT: PASS the extracted zip booted FireRed on the new client" if ok else
          f"RESULT: FAIL no client/server boot evidence within {timeout}s")
    return 0 if ok else 1


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# helper subcommand: §10's item 6 route-differential
# ---------------------------------------------------------------------------

ITEM6_FIX = "3941198c"      # the Gen 1 ordering fix that stays with the post-G4 convergence card
ITEM6_SCRATCH = "tests/unit/test_zz_item6_gen1_ordering_scratch.py"


def item6_scratch_source(root):
    """3941198c's named test, verbatim, importing the tree's own `world` fixture -- W3's case 1."""
    src = _git(root, "show", f"{ITEM6_FIX}:tests/unit/test_gen1_client.py").stdout
    m = re.search(r'@pytest\.mark\.parametrize\("special", \[False, True\]\)\n'
                  r"def test_a_battle_held_force_faint_keeps_its_place.*?(?=\n\n\n)", src, re.S)
    if not m:
        raise LaneError(f"{ITEM6_FIX}'s ordering test not found")
    return ("import pytest\n\nfrom server.adapters import gen1_codec as codec  # noqa: F401\n"
            "from tests.unit.test_gen1_client import world  # noqa: F401  (this tree's fixture)\n"
            "\n\n" + m.group(0) + "\n")


def item6_cases():
    """(name, argv, env, restore-after) -- the three cases of item6_route_diff_*_2026-09-24.txt."""
    cases = [("gen1_ordering", [PY, "-m", "pytest", ITEM6_SCRATCH, "-q", "-p", "no:randomly"], {}),
             ("gen1_sfx_town", [PY, "-m", "pytest", "tests/live/test_gen1_gates.py::test_gen1_sfx_matrix",
                                "-k", "town", "-q", "-p", "no:randomly", "-rs"], {"SLINK_LIVE": "1"})]
    cases += [(f"gen2_legacy_{s}", [PY, "tools/e2e_duo.py", "--game", "gen2", "--scenario", s], {})
              for s in ("faint", "boxsync", "memorialize")]
    return cases


def item6_verdict(table):
    """table: {case: {"master": ok, "branch": ok}}. A regression is master PASS, branch FAIL;
    the claim is no regression vs master, not full correctness (owner ruling 10)."""
    return [c for c, sides in table.items() if sides["master"] and not sides["branch"]]


def item6(branch, master):
    root = main_checkout()
    scratch = item6_scratch_source(root)
    table = {}
    for name, argv, env in item6_cases():
        table[name] = {}
        for side, tree in (("master", master), ("branch", branch)):   # paired back to back
            print(f"\n[item6] {name} on {side} ({head(tree)[:8]})  $ "
                  f"{shlex.join(['python' if a == PY else a for a in argv])}")
            scratch_path = os.path.join(tree, ITEM6_SCRATCH)
            if name == "gen1_ordering":
                with open(scratch_path, "w", encoding="utf-8") as f:
                    f.write(scratch)
            try:
                p = subprocess.run(argv, cwd=tree, env=dict(os.environ, **env),
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace")
            finally:
                if name == "gen1_ordering" and os.path.exists(scratch_path):
                    os.remove(scratch_path)
                if name == "gen1_sfx_town":   # the gate rewrites tracked fixture receipts
                    _git(tree, "checkout", "--", "tests/fixtures/gen1/receipts", check=False)
            out = p.stdout + p.stderr
            print(out[-4000:])
            table[name][side] = p.returncode == 0 and not detect_skip(p.returncode, out)
    print("\n[item6] case                  master  branch")
    for name, sides in table.items():
        print(f"[item6] {name:<22}{'PASS' if sides['master'] else 'FAIL':<8}"
              f"{'PASS' if sides['branch'] else 'FAIL'}")
    regressed = item6_verdict(table)
    print(f"RESULT: {'FAIL regression in ' + ', '.join(regressed) if regressed else 'PASS no case regressed vs master'}")
    return 1 if regressed else 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def run_pass(args):
    root = main_checkout()
    lane = os.path.abspath(args.lane).replace("\\", "/")
    master = os.path.abspath(args.master).replace("\\", "/")
    try:
        # resolved HERE, not in the main checkout: `--cut HEAD` means this branch's head
        cut = _git(REPO, "rev-parse", f"{args.cut}^{{commit}}").stdout.strip()
    except LaneError:
        if not args.dry_run:
            raise
        cut = args.cut
    rows = select_rows(build_plan(cut, lane, master), args.rows)
    if args.list:
        for r in rows:
            print(f"{r.id:<48} {r.item}")
        return 0
    if args.dry_run:
        print(f"# G4 final cut {cut}  lane={lane}  master={master}  rows={len(rows)}")
        for step in provision_plan(lane, cut):
            print(f"# provision: {step}")
        if any(r.id == "item6_route_diff" for r in rows):
            print(f"# provision: the same for {master} at master")
        for i, r in enumerate(rows, 1):
            env = " ".join(f"{k}={v}" for k, v in r.env.items())
            print(f"[{i:02d}] {r.id}  ({r.item}, budget {r.budget}s, cwd={r.cwd})\n"
                  f"     $ {(env + ' ') if env else ''}{r.command()}")
        print(f"# {len(rows)} rows; receipts docs/gen3/probes/fc_<row>_{cut[:8]}.txt, "
              f"summary fc_SUMMARY_{cut[:8]}.txt")
        return 0
    deadline = parse_utc(args.stop_at).timestamp() if args.stop_at else None
    try:
        provision(lane, cut, root)
        copy_inputs(lane, root)
        if any(r.id == "item6_route_diff" for r in rows):
            provision(master, "master", root)
            copy_inputs(master, root)
    except LaneError as exc:
        print(f"[final_cut] ABORT: {exc}", file=sys.stderr)
        return 2
    results = []
    for row in rows:
        prior = prior_verdict(row.id, cut)
        rec = os.path.basename(receipt_path(row.id, cut))
        if prior and prior.startswith("FAIL"):
            # never re-run an unchanged failed row automatically
            results.append((row, f"{prior} (prior receipt at this cut; not re-run)", 0, rec))
        elif prior and args.resume and prior.startswith(("PASS", "SKIP-ALLOWED")):
            results.append((row, f"{prior} (resumed)", 0, rec))
        elif deadline and time.time() >= deadline:
            results.append((row, "NOT RUN (--stop-at)", 0, "-"))
        else:
            verdict, n, clean_after = run_row(row, cut, lane, deadline)
            results.append((row, verdict, n, rec))
            if not clean_after:
                write_summary(cut, results)
                print("[final_cut] ABORT: the lane went tracked-dirty", file=sys.stderr)
                return 2
        path, _ok = write_summary(cut, results)
    path, ok = write_summary(cut, results)
    print(f"\n[final_cut] summary: {path}")
    print(_read(path))
    return 0 if ok else 1


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    wt = os.path.join(main_checkout(), ".claude", "worktrees")
    if argv[:1] == ["zip-boot"]:
        ap = argparse.ArgumentParser(prog="gen3_final_cut.py zip-boot")
        ap.add_argument("--zip", required=True)
        ap.add_argument("--lane", required=True)
        ap.add_argument("--timeout", type=int, default=300)
        a = ap.parse_args(argv[1:])
        return zip_boot(a.zip, a.lane, a.timeout)
    if argv[:1] == ["item6"]:
        ap = argparse.ArgumentParser(prog="gen3_final_cut.py item6")
        ap.add_argument("--branch", required=True)
        ap.add_argument("--master", required=True)
        a = ap.parse_args(argv[1:])
        return item6(a.branch, a.master)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cut", required=True, help="the frozen cut (any rev; resolved to a sha)")
    ap.add_argument("--lane", default=os.path.join(wt, "gen3-lane-clean"))
    ap.add_argument("--master", default=os.path.join(wt, "gen3-lane-master"),
                    help="item 6's baseline tree, provisioned at `master`")
    ap.add_argument("--rows", default=None, help="comma list of row-id globs or item tags")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; launch nothing")
    ap.add_argument("--list", action="store_true", help="print the selected row ids")
    ap.add_argument("--resume", action="store_true",
                    help="skip rows whose receipt at this cut already says PASS")
    ap.add_argument("--stop-at", default=None,
                    help="UTC time (ISO 8601): no row starts after it, a running row is killed")
    return run_pass(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
