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
import filecmp
import fnmatch
import hashlib
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
                     "patch/gen1/build/slink.sym",
                     "patch/build/slink_RR.gba"]   # probe_gates (tests/live/test_gen3_probe_gates.py)

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
    deps: list | None = None   # --carry: dependency globs (row_deps); None = never carried

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
    for r in rows:
        r.deps = row_deps(r)
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
    """The verdict of this row's runner receipt at this exact cut, or None -- only a receipt that
    fc_check validates counts (a header-only or wrong-row file never resumes as a PASS)."""
    path = receipt_path(row_id, cut)
    if not os.path.isfile(path):
        return None
    hdr, ok, _why = fc_check(os.path.basename(path), _read(path), PROBES)
    return hdr["verdict"] if ok and hdr["row"] == row_id and hdr["cut"] == cut else None


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
    """Copy each gitignored input the tree lacks (or holds with different CONTENT) from `root`,
    and stage the FR/LG dumps under patch/build. A missing source fails closed."""
    pairs = [(p, p) for p in GITIGNORED_INPUTS] + \
            [(ROOT_DUMPS[t], STAGED[t]) for t in ("firered", "leafgreen")]
    for src_rel, dst_rel in pairs:
        src, dst = os.path.join(root, src_rel), os.path.join(tree, dst_rel)
        if not os.path.isfile(src):
            raise LaneError(f"gitignored input missing from {root}: {src_rel}")
        if os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False):
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
    note = inputs_note(hash_inputs(row_inputs(row, lane)))   # after the run: what it used
    with open(receipt_path(row.id, cut), "w", encoding="utf-8") as f:
        f.write(receipts.run_receipt_text(row=row.id, item=row.item.replace(" ", "_"), cut=cut,
                                          lane=lane, command=row.command(), cwd=row.cwd,
                                          env=row.env, attempts=attempts, verdict=verdict,
                                          note=note))
    return verdict, len(attempts), attempts[-1]["tracked_after"]


def write_summary(cut, results, suffix=""):
    counts = {k: sum(status_of(v) == k for _r, v, _n, _p in results)
              for k in ("RUN", "CARRIED", "FAIL")}
    lines = [f"# G4 final cut {cut} -- tools/gen3_final_cut.py summary "
             f"(written {utcnow():%Y-%m-%dT%H:%M:%SZ})",
             f"# RUN {counts['RUN']} / CARRIED {counts['CARRIED']} / FAIL {counts['FAIL']}", "",
             "| # | row | runbook | verdict | attempts | receipt |", "|---|---|---|---|---|---|"]
    for i, (row, verdict, n, rec) in enumerate(results, 1):
        lines.append(f"| {i} | {row.id} | {row.item} | {verdict} | {n} | {rec} |")
    passed = counts["FAIL"] == 0
    lines += ["", f"OVERALL: {'PASS' if passed and results else 'FAIL'} "
                  f"({counts['RUN'] + counts['CARRIED']}/{len(results)} rows)"]
    path = os.path.join(PROBES, f"fc_SUMMARY_{cut[:8]}{suffix}.txt")
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
# --carry: synthetic evidence (owner-approved, card G4-FINALCUT-FAST, hardened by
# G4-FINALCUT-HARDEN after OMP's review of d9a08f5b). A row is CARRIED, not run, only when ALL of:
#   - a citable PASS receipt for the same row+orientation exists at a cut X (one unambiguous final
#     verdict; a CARRIED fc receipt is citable only through its validated origin);
#   - X is an ancestor of the cut (`git merge-base --is-ancestor X cut`);
#   - `git diff --name-only X cut` touches none of the row's dependency globs (CONSERVATIVE: the
#     client closure, the packs it loads, the harness and carriers, the server, the fixtures, the
#     pret syms -- when in doubt the path is in; `**` crosses directories, `*` does not);
#   - the non-git inputs (staged ROMs, ...) hash the same in this lane as the receipt recorded.
# ---------------------------------------------------------------------------

GEN3_CLIENT = ["lua/*.lua", "lua/x64/**", "lua/gen3/**", "lua/core/**", "lua/games/**",
               "data/games/gen3_frlg/**", "data/games/gen3_frlge/**"]   # entry.lua:74-78
GEN3_HARNESS = ["tools/run_gate.py", "tools/gen1_playthrough.py", "tools/gen3_fixtures.py",
                "lua/tests/gen3_*.lua", "lua/tests/playlib.lua", "lua/tests/mkstates_gen3*.lua",
                "server/adapters/**", "data/gen3/pret/**"]
FRLG_FIXTURES = ["tests/fixtures/gen3/firered_party_*", "tests/fixtures/gen3/leafgreen_party_*"]
DUO_DEPS = GEN3_CLIENT + GEN3_HARNESS + FRLG_FIXTURES + [
    "server/**", "tools/e2e_duo.py", "lua/tests/duo/**"]
PROBE_DEPS = GEN3_CLIENT + GEN3_HARNESS + FRLG_FIXTURES + [
    "data/games/gen3_rr/**",            # gen3_gatelib.lua / probe_gen3_checkpoint.lua read it
    "lua/tests/probe_gen3_checkpoint.lua", "tools/gen3_probe_receipt.py", "tools/gen3_bw_hashes.py",
    "tools/mkstates_gen3.py", "tools/mkstates_gen3_tutorials.py"]
PROBE_GATES_DEPS = GEN3_CLIENT + GEN3_HARNESS + [
    "data/games/gen3_*/**", "lua/tests/*gen3*", "lua/tests/duo/**", "tools/e2e_duo.py",
    "tests/live/test_gen3_probe_gates.py", "tests/conftest.py"]
ITEM6_DEPS = ["lua/*.lua", "lua/gen1/**", "lua/gen2/**", "lua/core/**", "lua/clients/**",
              "lua/games/**", "lua/tests/*gen1*", "lua/tests/*gb*", "lua/tests/duo/**", "server/**",
              "tools/e2e_duo.py", "tools/run_gate.py", "tools/gen1_*.py", "tools/gen3_final_cut.py",
              "tests/conftest.py", "tests/unit/test_gen1_client.py", "tests/unit/protocol_schema.py",
              "tests/live/test_gen1_gates.py", "tests/fixtures/gen1/**", "tests/fixtures/gen2/**",
              "data/games/gen1_rby/**", "data/games/gen2_crystal/**", "patch/gen1/**"]
# builds are lane-local artifacts, the zip is built from the cut, the source gate IS the cut, and
# the checkpoint probe runs on states this very pass rebuilds (its state hashes cannot be known
# before the rebuild), so none of these is ever carried
NEVER_CARRIED = ("states_*", "tutorials_*", "checkpoint_*", "zip_*", "release_gate_quick")


def row_deps(row):
    """The row's dependency globs, or None for a row that is never carried."""
    if any(fnmatch.fnmatch(row.id, p) for p in NEVER_CARRIED):
        return None
    if row.id.endswith(("_fr_as_a", "_lg_as_a")):
        return DUO_DEPS
    if row.id.startswith("bootcheck_"):
        return GEN3_CLIENT + GEN3_HARNESS + [f"tests/fixtures/gen3/{row.id[len('bootcheck_'):]}.sav"]
    if row.id == "item6_route_diff":
        return ITEM6_DEPS
    if row.id == "probe_gates":
        return PROBE_GATES_DEPS
    return None


def row_inputs(row, lane, root=None):
    """{key: path} of the NON-git inputs that can change the row's outcome (git sees the rest)."""
    def at(rel):
        return os.path.join(lane, rel)
    rid = row.id
    if rid.endswith(("_fr_as_a", "_lg_as_a")):
        return {f"rom:{t}": at(STAGED[t]) for t in ("firered", "leafgreen")}
    m = re.match(r"(states|tutorials|checkpoint|bootcheck)_(firered|leafgreen)", rid)
    if m:
        out = {f"rom:{m[2]}": at(STAGED[m[2]])}
        if m[1] == "checkpoint":
            for d in ("gen3_probe_states_c4p2", "gen3_probe_states"):
                sd = at(f"patch/build/{d}/{m[2]}")
                for name in sorted(os.listdir(sd)) if os.path.isdir(sd) else []:
                    if name.endswith(".State"):
                        out[f"state:{d}/{name}"] = os.path.join(sd, name)
        return out
    if rid == "probe_gates":   # tests/live/test_gen3_probe_gates.py: the RR build + the root FR dump
        return {"rom:slink_RR": at("patch/build/slink_RR.gba"),
                "rom:firered_root": os.path.join(root or main_checkout(), ROOT_DUMPS["firered"])}
    if rid == "item6_route_diff":
        return {f"input:{p}": at(p) for p in GITIGNORED_INPUTS if p.startswith("patch/")}
    return {}


_HASHES = {}


def file_sha256(path):
    """sha256 of a file, memoised on (path, size, mtime); None when absent."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_size, st.st_mtime_ns)
    if key not in _HASHES:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _HASHES[key] = h.hexdigest()
    return _HASHES[key]


def hash_inputs(paths):
    return {k: file_sha256(p) or "MISSING" for k, p in paths.items()}


def inputs_note(hashes):
    return "inputs: " + (" ".join(f"{k}={v}" for k, v in sorted(hashes.items())) or "(none)")


def parse_inputs(text):
    m = re.search(r"^# inputs: (.*)$", text, re.M)
    if not m or m[1] == "(none)":
        return {}
    return dict(kv.split("=", 1) for kv in m[1].split() if "=" in kv)


def _glob_re(glob):
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**", i):
            out, i = out + ".*", i + 2
        else:
            out += {"*": "[^/]*", "?": "[^/]"}.get(glob[i], re.escape(glob[i]))
            i += 1
    return re.compile(out + r"\Z")


def touched(changed, deps):
    """The changed paths that match any dependency glob."""
    pats = [_glob_re(g) for g in deps]
    return [f for f in changed if any(p.match(f) for p in pats)]


@dataclass
class Evidence:
    row: str
    receipt: str               # basename under docs/gen3/probes/ (a carry's ORIGIN)
    cut: str | None            # the full sha the receipt was taken at (None: not citable)
    passed: bool               # one unambiguous final PASS (never SKIP-ALLOWED)
    seconds: float | None = None
    master: str | None = None  # item 6 only: the master sha8 its baseline side ran at
    inputs: dict = field(default_factory=dict)   # non-git input hashes the receipt recorded


_SHA = r"[0-9a-f]{40}"
_TITLE = {"fr": "firered", "lg": "leafgreen"}
_GAME = {"fr": "gen3_frlg", "lg": "gen3_lgfr"}


def _one_sha(text, keys):
    """The one sha the receipt names under `keys` (source=/sha=/lane=), else None."""
    shas = set(re.findall(rf"\b(?:{'|'.join(keys)})=({_SHA})\b", text))
    return shas.pop() if len(shas) == 1 else None


def _seconds(text, pass_re=None):
    """Summed start_utc..end_utc spans (only spans that show `pass_re`, if given)."""
    total = None
    for sec in re.split(r"(?=start_utc=)", text)[1:]:
        start, end = re.match(r"start_utc=(\S+)", sec), re.search(r"end_utc=(\S+)", sec)
        if end and (pass_re is None or pass_re.search(sec)):
            total = (total or 0) + (parse_utc(end[1]) - parse_utc(start[1])).total_seconds()
    return total


def _identity_roms(text):
    """{rom:<title>: sha256} from e2e_duo's IDENTITY lines; {} when absent or inconsistent."""
    seen = set()
    for line in re.findall(r"IDENTITY (a=\S+ b=\S+)", text):
        seen.add(tuple(re.findall(r"[ab]=(\w+):rom=([0-9a-f]{64})", line)))
    if len(seen) != 1:
        return {}
    return {f"rom:{t}": h for t, h in seen.pop()}


def duo_verdict_ok(text, scenario, orient):
    """One unambiguous final PASS for this scenario and orientation: every summary line for the
    scenario says PASS (a later FAIL/SKIP anywhere in the file makes it not citable), every
    recorded exit is 0, and every IDENTITY names A as the orientation's title."""
    verdicts = re.findall(rf"^  {re.escape(scenario)}: (PASS|FAIL|SKIP)\b", text, re.M)
    exits = re.findall(r"^exit=(\S+)$", text, re.M)
    a_titles = set(re.findall(r"IDENTITY a=(\w+):", text))
    games = set(re.findall(rf"^=== {re.escape(scenario)} --game (\S+)", text, re.M))
    return (bool(verdicts) and set(verdicts) == {"PASS"} and all(e == "0" for e in exits)
            and a_titles == {_TITLE[orient]} and games <= {_GAME[orient]})


def fc_check(name, text, probes, depth=0):
    """(header, ok, why) for a runner receipt: the file name, header row and cut agree; a PASS,
    SKIP-ALLOWED or FAIL has well-formed attempt blocks whose last one supports the verdict; a
    CARRIED one cites an origin that is itself a citable PASS for the same row at the cited cut."""
    m = re.fullmatch(r"fc_(.+)_([0-9a-f]{8})\.txt", name)
    hdr = receipts.parse_run_receipt(text)
    if not (m and hdr):
        return hdr, False, "not a runner receipt"
    if hdr["row"] != m[1] or not re.fullmatch(_SHA, hdr["cut"] or "") or \
            not hdr["cut"].startswith(m[2]):
        return hdr, False, "header row/cut disagree with the file name"
    v = hdr["verdict"]
    c = re.match(rf"CARRIED from (\S+) @({_SHA})", v)
    if c:
        return (hdr, *origin_ok(c[1], hdr["row"], c[2], probes, depth + 1))
    heads = re.findall(r"^--- attempt \d+ of \d+ ---$", text, re.M)
    ends = re.findall(r"^exit=(\S+) end_utc=\S+ tracked_clean_after=(\w+) classification=(\S+)$",
                      text, re.M)
    if not heads or len(heads) != len(ends):
        return hdr, False, "no well-formed attempt blocks"
    rc, clean, cls = ends[-1]
    if v.startswith(("PASS", "SKIP-ALLOWED")) and not (
            cls == "pass" and clean == "True" and (rc == "0" or v.startswith("SKIP-ALLOWED"))):
        return hdr, False, "the last attempt does not support the verdict"
    return hdr, True, ""


def origin_ok(name, row, x, probes, depth):
    """A carry's origin must exist, be a citable PASS for the same row at the cited cut X."""
    if depth > 8:
        return False, "carry chain too deep"
    path = os.path.join(probes, name)
    if os.path.basename(name) != name or not os.path.isfile(path):
        return False, f"origin {name} missing"
    ev = receipt_evidence(name, _read(path), probes, depth)
    if not ev or ev.row != row or ev.cut != x or not ev.passed:
        return False, f"origin {name} is not a citable PASS for {row} @{x[:8]}"
    return True, ""


def receipt_evidence(name, text, probes=None, depth=0):
    """Map one receipt file to Evidence (row, cut, citable PASS?, duration, inputs), or None.
    The shapes in the tree: fc_<row>_<cut8> (this runner), ph_<scenario>_<fr|lg>_as_a_<cut8>
    (G4-LANE-2), duo_frlg_<scenario>[_clean]_<date>, {center_controls,save_then_write}_<o>_as_a_*,
    center_receipt_whiteout_<o>_as_a_*, and, for durations only, checkpoint_<fr|lg>_clean_* and
    mkstates_gen3_<title>_<kind>_*. A receipt that names no single cut sha is not citable."""
    probes = probes or PROBES
    m = re.fullmatch(r"fc_(.+)_[0-9a-f]{8}\.txt", name)
    if m and not name.startswith("fc_SUMMARY_"):
        hdr, ok, _why = fc_check(name, text, probes, depth)
        if not ok:
            return Evidence(m[1], name, None, False)
        v = hdr["verdict"]
        c = re.match(rf"CARRIED from (\S+) @({_SHA})", v)
        if c:   # a carry cites its (validated) origin, never itself
            return Evidence(hdr["row"], c[1], c[2], True, inputs=parse_inputs(text))
        mm = re.search(r"on master \(([0-9a-f]{8})\)", text)
        return Evidence(hdr["row"], name, hdr["cut"], v.startswith("PASS"), _seconds(text),
                        mm[1] if mm else None, parse_inputs(text))
    m = re.fullmatch(r"ph_(.+)_(fr|lg)_as_a_[0-9a-f]{8}\.txt", name)
    if m:
        scen, o = m[1], m[2]
        notes = re.findall(r"^note: (.*)$", text, re.M)
        passed = len(notes) == 1 and notes[0].startswith("PASS") and duo_verdict_ok(text, scen, o)
        secs = _seconds(text, re.compile(rf"^  {re.escape(scen)}: PASS", re.M))
        note = re.search(r"~(\d+) min", notes[0]) if notes else None
        if secs is None and note:
            secs = int(note[1]) * 60
        return Evidence(f"{scen}_{o}_as_a", name, _one_sha(text, ("sha", "source")), passed,
                        secs, inputs=_identity_roms(text))
    for pat, scen_of in (
            (r"duo_frlg_(.+?)_(?:clean_)?\d{4}-\d\d-\d\d[a-z]?\.txt", lambda m: (m[1], "fr")),
            (r"(center_controls|save_then_write)_(fr|lg)_as_a_.*\.txt",
             lambda m: (m[1] + "_gen3", m[2])),
            (r"center_receipt_whiteout_(fr|lg)_as_a_.*\.txt", lambda m: ("whiteout_gen3", m[1]))):
        m = re.fullmatch(pat, name)
        if m:
            scen, o = scen_of(m)
            return Evidence(f"{scen}_{o}_as_a", name, _one_sha(text, ("source",)),
                            duo_verdict_ok(text, scen, o), inputs=_identity_roms(text))
    m = re.fullmatch(r"mkstates_gen3_(firered|leafgreen)_(town|battle)_.*\.txt", name)
    if m:
        g = re.search(r"\[gate\] \S+: RESULT: PASS.*\((\d+)s\)", text)
        return Evidence(f"states_{m[1]}_{m[2]}", name, None, False, int(g[1]) if g else None)
    return None


def collect_evidence(probes=None):
    """{row: [Evidence, ...]} over every receipt in docs/gen3/probes/."""
    probes = probes or PROBES
    out = {}
    for name in sorted(os.listdir(probes)):
        if name.endswith(".txt"):
            ev = receipt_evidence(name, _read(os.path.join(probes, name)), probes)
            if ev:
                out.setdefault(ev.row, []).append(ev)
    return out


@dataclass
class Decision:
    kind: str                       # "CARRY" or "RUN"
    reason: str
    evidence: Evidence | None = None
    checked: list = field(default_factory=list)   # the diff X..cut that was checked
    inputs: dict = field(default_factory=dict)    # this lane's non-git input hashes


def git_is_ancestor(x, cut):
    return subprocess.run(["git", "-C", REPO, "merge-base", "--is-ancestor", x, cut],
                          capture_output=True).returncode == 0


def carry_decision(row, cut, evidence, diff_names, master_sha=None, ancestor=None, inputs=None):
    """CARRY when some citable PASS receipt at a cut X != `cut` has X an ancestor of `cut`, the
    same non-git input hashes as `inputs` (this lane's), and a diff X..cut that touches none of
    the row's dependency globs; RUN otherwise, with the reason. `diff_names(x, cut)` returns the
    changed paths, or None when x is not in the repo. Receipts at `cut` itself are resume
    material, not carry material."""
    ancestor = ancestor or git_is_ancestor
    inputs = inputs or {}
    if row.deps is None:
        return Decision("RUN", "never carried (built/checked at the cut itself)")
    missing = sorted(k for k, v in inputs.items() if v == "MISSING")
    if missing:
        return Decision("RUN", f"non-git input missing in this lane: {', '.join(missing)}")
    cands = [e for e in evidence if e.passed and e.cut and e.cut != cut]
    if not cands:
        return Decision("RUN", "no citable PASS receipt")
    blocked = []
    for e in cands:
        if row.id == "item6_route_diff" and not (e.master and master_sha
                                                  and master_sha.startswith(e.master)):
            blocked.append(f"{e.receipt}: master moved or unrecorded")
            continue
        if not ancestor(e.cut, cut):
            blocked.append(f"{e.receipt}: {e.cut[:8]} is not an ancestor of the cut")
            continue
        differ = sorted(k for k, v in inputs.items() if e.inputs.get(k) != v)
        if differ:
            blocked.append(f"{e.receipt}: non-git inputs differ or unrecorded "
                           f"({', '.join(differ[:3])})")
            continue
        changed = diff_names(e.cut, cut)
        if changed is None:
            blocked.append(f"{e.receipt}: cut {e.cut[:8]} not in this repo")
            continue
        hit = touched(changed, row.deps)
        if not hit:
            return Decision("CARRY", f"CARRIED from {e.receipt} @{e.cut}", e, changed, inputs)
        blocked.append(f"{e.receipt} @{e.cut[:8]}: {', '.join(hit[:3])}"
                       f"{f' (+{len(hit) - 3})' if len(hit) > 3 else ''}")
    return Decision("RUN", "cannot carry -- " + "; ".join(blocked))


_DIFFS = {}


def git_diff_names(x, cut):
    if (x, cut) not in _DIFFS:
        p = subprocess.run(["git", "-C", REPO, "diff", "--name-only", x, cut],
                           capture_output=True, text=True)
        _DIFFS[x, cut] = p.stdout.split() if p.returncode == 0 else None
    return _DIFFS[x, cut]


def estimate_seconds(evidence, cut):
    """The row's historical duration: the longest recorded span among its receipts at other
    cuts (receipts at `cut` are left out, so two shards compute the same estimate)."""
    spans = [e.seconds for e in evidence if e.seconds and e.cut != cut]
    return max(spans) if spans else None


def carried_receipt(row, cut, lane, d):
    """The CARRIED row's fc receipt: the cited receipt, its cut, the checked diff and inputs."""
    deps = row.deps or []
    x = d.evidence.cut
    note = (f"CARRIED from {d.evidence.receipt} @{x}; diff {x[:8]}..{cut[:8]} touches no "
            f"dependency (list checked)\n"
            f"dependencies checked ({len(deps)}): {' '.join(deps)}\n"
            f"diff {x[:8]}..{cut[:8]} ({len(d.checked)} paths, none a dependency): "
            f"{' '.join(d.checked) or '(empty)'}\n" + inputs_note(d.inputs))
    return receipts.run_receipt_text(row=row.id, item=row.item.replace(" ", "_"), cut=cut,
                                     lane=lane, command=row.command(), cwd=row.cwd, env=row.env,
                                     attempts=[], verdict=d.reason, note=note)


# ---------------------------------------------------------------------------
# --shard i/n: two runner instances split the RUN rows across two lanes
# ---------------------------------------------------------------------------

def parse_shard(text):
    i, n = (int(x) for x in text.split("/"))
    if not 1 <= i <= n:
        raise SystemExit(f"--shard {text}: need 1 <= i <= n")
    return i, n


def chain_of(row_id):
    """Rows that must share a shard, in plan order: a title's state/tutorial builds feed its
    checkpoint probe (SLINK_STATE_DIR, the bw hashes), and zip_build feeds zip_check/zip_boot."""
    m = re.match(r"(?:states|tutorials|checkpoint)_(firered|leafgreen)", row_id)
    if m:
        return f"probe_{m[1]}"
    return "zip" if row_id.startswith("zip_") else row_id


def shard_rows(rows, n, est):
    """Deterministic longest-first split of `rows` into n lists, with each prerequisite chain
    (chain_of) an atomic unit; plan order inside each shard, so a chain keeps its order. Every
    row lands in exactly one shard. `est` maps row id -> seconds."""
    order = {r.id: k for k, r in enumerate(rows)}
    units = {}
    for r in rows:
        units.setdefault(chain_of(r.id), []).append(r)
    loads, out = [0.0] * n, [[] for _ in range(n)]
    for unit in sorted(units.values(),
                       key=lambda u: (-sum(est[r.id] for r in u), order[u[0].id])):
        k = min(range(n), key=lambda j: (loads[j], j))
        out[k] += unit
        loads[k] += sum(est[r.id] for r in unit)
    return [sorted(o, key=lambda r: order[r.id]) for o in out]


def status_of(verdict):
    if verdict.startswith("CARRIED"):
        return "CARRIED"
    return "RUN" if verdict.startswith(("PASS", "SKIP-ALLOWED")) else "FAIL"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def plan_decisions(rows, cut, carry, lane):
    """({row id: Decision}, {row id: est seconds or None}). Without --carry every row RUNs."""
    ev = collect_evidence()
    est = {r.id: estimate_seconds(ev.get(r.id, []), cut) for r in rows}
    if not carry:
        return {r.id: Decision("RUN", "no --carry") for r in rows}, est
    master = _git(REPO, "rev-parse", "master", check=False).stdout.strip() or None
    return {r.id: carry_decision(r, cut, ev.get(r.id, []), git_diff_names, master,
                                 git_is_ancestor,
                                 hash_inputs(row_inputs(r, lane)) if r.deps else {})
            for r in rows}, est


def _mins(s):
    return f"{s / 60:.0f}m"


def merge_summary(cut, rows):
    """--merge-summary: one fc_SUMMARY_<cut8>.txt from every row's receipt at `cut`, whichever
    shard (or lane) wrote it; a row with no receipt is NOT RUN, i.e. a failure."""
    results = []
    for row in rows:
        path = receipt_path(row.id, cut)
        name = os.path.basename(path)
        if not os.path.isfile(path):
            results.append((row, "NOT RUN (no receipt at this cut)", 0, "-"))
            continue
        text = _read(path)
        hdr, ok, why = fc_check(name, text, PROBES)
        if not ok or hdr["row"] != row.id or hdr["cut"] != cut:
            results.append((row, f"FAIL invalid receipt ({why or 'wrong row/cut'})", 0, name))
        else:
            results.append((row, hdr["verdict"], text.count("\n--- attempt "), name))
    path, ok = write_summary(cut, results)
    print(_read(path))
    return 0 if ok else 1


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
    if args.merge_summary:
        return merge_summary(cut, rows)
    decisions, est = plan_decisions(rows, cut, args.carry, lane)
    run_rows = [r for r in rows if decisions[r.id].kind == "RUN"]
    carry_rows = [r for r in rows if decisions[r.id].kind == "CARRY"]
    suffix, plan = "", None
    if args.shard:
        i, n = parse_shard(args.shard)
        plan = shard_rows(run_rows, n, {r.id: est[r.id] or r.budget for r in run_rows})
        run_rows = plan[i - 1]
        carry_rows = carry_rows if i == 1 else []   # shard 1 writes the CARRIED receipts
        suffix = f"_shard{i}of{n}"
    mine = {r.id for r in run_rows + carry_rows}
    rows_here = [r for r in rows if r.id in mine]
    if args.dry_run:
        print(f"# G4 final cut {cut}  lane={lane}  master={master}  rows={len(rows)}"
              f"{f'  shard={args.shard}' if args.shard else ''}  carry={bool(args.carry)}")
        for step in provision_plan(lane, cut):
            print(f"# provision: {step}")
        if any(r.id == "item6_route_diff" for r in run_rows):
            print(f"# provision: the same for {master} at master")
        for k, r in enumerate(rows, 1):
            d, env = decisions[r.id], " ".join(f"{a}={b}" for a, b in r.env.items())
            where = "" if r.id in mine else "  [other shard]"
            e = est[r.id]
            print(f"[{k:02d}] {r.id}  {d.kind}{where}  ({r.item}, "
                  f"{'est ' + _mins(e) if e else 'no history, budget ' + _mins(r.budget)}, "
                  f"cwd={r.cwd})\n     $ {(env + ' ') if env else ''}{r.command()}\n"
                  f"     {d.reason}")
        known = [est[r.id] for r in run_rows if est[r.id]]
        unknown = [r for r in run_rows if not est[r.id]]
        print(f"# {len(rows)} rows: RUN {len(run_rows)} (this shard) / CARRY {len(carry_rows)}"
              f" -- lane time: {_mins(sum(known))} from {len(known)} rows' receipts + "
              f"{len(unknown)} rows with no history (budget ceiling "
              f"{_mins(sum(r.budget for r in unknown))})")
        for k, rs in enumerate(plan or [], 1):
            secs = sum(est[r.id] or r.budget for r in rs)
            print(f"# shard {k}/{len(plan)} ({len(rs)} rows, ~{_mins(secs)} with budget for "
                  f"rows without history): {' '.join(r.id for r in rs)}")
        print(f"# receipts docs/gen3/probes/fc_<row>_{cut[:8]}.txt, summary "
              f"fc_SUMMARY_{cut[:8]}{suffix}.txt")
        return 0
    deadline = parse_utc(args.stop_at).timestamp() if args.stop_at else None
    try:
        if run_rows:
            provision(lane, cut, root)
            copy_inputs(lane, root)
        if any(r.id == "item6_route_diff" for r in run_rows):
            provision(master, "master", root)
            copy_inputs(master, root)
    except LaneError as exc:
        print(f"[final_cut] ABORT: {exc}", file=sys.stderr)
        return 2
    results = []
    for row in rows_here:
        prior = prior_verdict(row.id, cut)
        rec = os.path.basename(receipt_path(row.id, cut))
        if prior and prior.startswith("FAIL"):
            # never re-run an unchanged failed row automatically, and never paper over it
            results.append((row, f"{prior} (prior receipt at this cut; not re-run)", 0, rec))
        elif prior and (args.resume or decisions[row.id].kind == "CARRY") and \
                prior.startswith(("PASS", "SKIP-ALLOWED", "CARRIED")):
            results.append((row, f"{prior} (resumed)", 0, rec))
        elif decisions[row.id].kind == "CARRY":
            with open(receipt_path(row.id, cut), "w", encoding="utf-8") as f:
                f.write(carried_receipt(row, cut, lane, decisions[row.id]))
            results.append((row, decisions[row.id].reason, 0, rec))
        elif deadline and time.time() >= deadline:
            results.append((row, "NOT RUN (--stop-at)", 0, "-"))
        else:
            verdict, n, clean_after = run_row(row, cut, lane, deadline)
            results.append((row, verdict, n, rec))
            if not clean_after:
                write_summary(cut, results, suffix)
                print("[final_cut] ABORT: the lane went tracked-dirty", file=sys.stderr)
                return 2
        write_summary(cut, results, suffix)
    path, ok = write_summary(cut, results, suffix)
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
    ap.add_argument("--carry", action="store_true",
                    help="CARRY a row whose PASS receipt at an earlier cut has no dependency in "
                         "the diff to --cut (owner-approved synthetic evidence)")
    ap.add_argument("--shard", default=None,
                    help="i/n: run only this instance's share of the RUN rows (use a distinct "
                         "--lane per shard); shard 1 also writes the CARRIED receipts")
    ap.add_argument("--merge-summary", action="store_true",
                    help="write fc_SUMMARY_<cut8>.txt from every row's receipt at --cut, then exit")
    return run_pass(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
