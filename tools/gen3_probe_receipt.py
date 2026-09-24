#!/usr/bin/env python3
"""gen3_probe_receipt.py -- run probe_gen3_checkpoint.lua for one title at a lane and write a
committed-style receipt to docs/gen3/probes/<name>.txt (G4 final-cut runbook §6, §12 item 3).

Usage:
    python tools/gen3_probe_receipt.py --title firered --lane <lane>
    python tools/gen3_probe_receipt.py --title leafgreen --lane <lane> --dry-run
    python tools/gen3_probe_receipt.py --title firered --lane <lane> --rows script_running,sound_driver

The receipt is a header (title/kind/lane/tracked_clean, the probe script's COMMITTED sha256,
the staged ROM's sha1, every env var used, the exact invocation) followed verbatim by the
probe's own result file -- docs/gen3/probes/checkpoint_fr_clean_2b_rows_2026-09-23.txt is the
model this follows (OLDMAN/POKEDUDE before BW_HASHES, the bw-hashes JSON inlined after its
path, a '# states:' provenance line, then ROWS and the invocation). --dry-run only prints the
env and the two commands (gen3_bw_hashes.py, if any bw_* row is selected, then run_gate.py) --
nothing is launched, nothing is written.

Exit: 0 only if ALL of -- the probe's result file's last non-blank line is exactly
"RESULT: PASS all checkpoint controls", the run_gate.py child exited 0, and the lane's tracked
worktree was clean both before AND after the run. Any other outcome is non-zero (OMP review of
587453bf, C4-RECEIPT-TOOLS follow-up): a stale result file could otherwise "pass" a run whose
launch actually crashed, and a lane that drops tracked files mid-run (observed once on Drive,
22 files) must not be reported as a clean re-take.

radical_red is refused by name, not silently coerced: RR receipts are G5 (its own companion
pack tooling), not this FR/LG party-lane probe.
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import gen3_fixtures  # noqa: E402
import run_gate as _run_gate  # noqa: E402

REPO = os.path.dirname(_HERE)
PROBE_SCRIPT = "lua/tests/probe_gen3_checkpoint.lua"
PASS_LINE = "RESULT: PASS all checkpoint controls"

# The full §6 row list: the eleven core reason rows plus the nine G4 2b battle-window rows (the
# probe's own seven ALWAYS-run phases -- idle/walking/start_menu/dialog/save/battle/fade -- are
# not part of this list; SLINK_CHECKPOINT_ROWS only selects the reason rows).
BASE_ROWS = ["script_running", "battle_input_wild", "battle_input_trainer", "battle_move_menu",
             "battle_animation", "battle_faint_prompt", "battle_intro", "battle_over",
             "battle_commit_state3", "native_absent", "sound_driver"]
BW_ROWS = ["bw_n1_action_draw", "bw_n4_bag", "bw_n5_party", "bw_n6_summary", "bw_n7_switch",
           "bw_n9_run", "bw_u1_oldman", "bw_u2_pokedude", "bw_n8_item"]
DEFAULT_ROWS = BASE_ROWS + BW_ROWS


def staged_rom_rel(title):
    """The staged, space-free ROM path a lane's run_gate invocation uses -- the same naming
    rule as gen3_fixtures.stage_rom (f"patch/build/gen3_{stem}{suffix}"), applied to
    PARTY_TITLES's filename rather than a real dump on disk: this tool never stages a ROM,
    runbook §1/§0.3 does that ahead of time."""
    if title not in gen3_fixtures.PARTY_TITLES:
        raise ValueError(f"title {title!r} not in gen3_fixtures.PARTY_TITLES "
                          f"({sorted(gen3_fixtures.PARTY_TITLES)})")
    dump = str(gen3_fixtures.PARTY_TITLES[title]["rom"])
    stem, suffix = os.path.splitext(dump)
    return f"patch/build/gen3_{stem.replace(' ', '_')}{suffix}"


def build_env(title, lane, rows, kind):
    env = {
        "SLINK_GEN3_CHECKPOINT": f"{lane}/data/games/gen3_frlg/write_checkpoint.json",
        "SLINK_GEN3_TITLE": title,
        "SLINK_GEN3_KIND": kind,
        "SLINK_STATE_DIR": f"{lane}/patch/build/gen3_probe_states_c4p2/{title}",
        "SLINK_CHECKPOINT_ROWS": ",".join(rows),
    }
    if any(r.startswith("bw_") for r in rows):
        # preintro/prebattle already live under SLINK_STATE_DIR (gen3_probe_states_c4p2); the
        # tutorial states do not, so those two need a full path (lua/tests/probe_gen3_checkpoint
        # .lua:276's P.state_path treats any name containing a slash as already-resolved).
        env["SLINK_CHECKPOINT_OLDMAN_STATE"] = \
            f"{lane}/patch/build/gen3_probe_states/{title}/slink_oldman.State"
        env["SLINK_CHECKPOINT_POKEDUDE_STATE"] = \
            f"{lane}/patch/build/gen3_probe_states/{title}/slink_pokedude.State"
        env["SLINK_BW_HASHES"] = f"{lane}/patch/build/bw_hashes_{title}.json"
    return env


def invocation_line(env, rom_rel, timeout):
    return (f"SLINK_GEN3_CHECKPOINT={env['SLINK_GEN3_CHECKPOINT']} "
            f"SLINK_GEN3_TITLE={env['SLINK_GEN3_TITLE']} SLINK_GEN3_KIND={env['SLINK_GEN3_KIND']} "
            f'python tools/run_gate.py {PROBE_SCRIPT} --rom "{rom_rel}" --timeout {timeout}')


def _git(lane, *args):
    return subprocess.run(["git", "-C", lane, *args], capture_output=True, check=True)


def lane_head_sha(lane):
    return _git(lane, "rev-parse", "HEAD").stdout.decode().strip()


def lane_tracked_clean(lane):
    out = _git(lane, "status", "--porcelain", "--untracked-files=no").stdout
    return len(out.strip()) == 0


def git_blob_sha256(lane, relpath):
    """sha256 of the COMMITTED blob (git show HEAD:<relpath>), never the working-tree file --
    a Windows checkout's core.autocrlf/eol can rewrite the file on disk to CRLF without that
    showing up as a diff, so hashing the working copy would silently drift from what HEAD
    actually pins."""
    blob = _git(lane, "show", f"HEAD:{relpath}").stdout
    return hashlib.sha256(blob).hexdigest()


def file_sha1(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def _result_path_for_lane(lane, script):
    """run_gate._result_path_for, reused against the LANE's repo root instead of this tool's
    own -- the regex logic is run_gate's; only REPO/BUILD move.

    NOTE not thread-safe: this rebinds run_gate's own module-level REPO/BUILD globals for the
    duration of the call, so two overlapping calls (from different threads, or a re-entrant
    call from inside the try block) would stomp each other. Fine for this single-threaded,
    one-lane-at-a-time CLI; do not call it from more than one thread."""
    old_repo, old_build = _run_gate.REPO, _run_gate.BUILD
    _run_gate.REPO, _run_gate.BUILD = lane, os.path.join(lane, "patch", "build")
    try:
        return _run_gate._result_path_for(script)
    finally:
        _run_gate.REPO, _run_gate.BUILD = old_repo, old_build


def run_bw_hashes(title, lane):
    """python tools/gen3_bw_hashes.py <title> <lane>, the LANE's own copy (cwd=lane) -- same
    one-lane-at-a-time reproducibility rule as run_probe below."""
    subprocess.run([sys.executable, "tools/gen3_bw_hashes.py", title, lane], cwd=lane, check=True)


def _read_bw_hashes(lane, title):
    """(path, raw text, parsed doc) of the bw-hashes JSON gen3_bw_hashes.py just wrote --
    inlined into the header and mined for the '# states:' provenance line."""
    path = f"{lane}/patch/build/bw_hashes_{title}.json"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return path, text, json.loads(text)


def _bw_states_note(doc):
    """A short '# states:' provenance line built from the bw-hashes doc's own per-state 'prep'
    strings (cheap: no new receipts read, just the unique preps gen3_bw_hashes.py already
    recorded), matching the model receipt's '# states: <builder a> + <builder b>' shape."""
    preps = []
    for st in (doc.get("states") or {}).values():
        p = st.get("prep")
        if p and p not in preps:
            preps.append(p)
    return " + ".join(preps)


def run_probe(script, rom_rel, timeout, lane, env):
    """python tools/run_gate.py <script> --rom <rom_rel> --timeout <timeout>, the LANE's own
    copy (cwd=lane); the emulator launch itself lives in run_gate.py, not here.

    Deletes any EXISTING result file for `script` before launching: run_gate.py only deletes
    the previous run's result file AFTER its own EmuHawk/ROM/config preflight (run_gate.py's
    run_gate(), the os.remove(out_path) a few lines after the ROM-exists check), so a preflight
    failure there would otherwise leave a stale PASS file looking like fresh evidence. Returns
    the child's exit code -- non-zero must be treated as a failed run regardless of whatever a
    (by now nonexistent, but belt-and-braces) result file says."""
    stale = _result_path_for_lane(lane, script)
    if stale and os.path.exists(stale):
        os.remove(stale)
    full_env = dict(os.environ, **env)
    proc = subprocess.run([sys.executable, "tools/run_gate.py", script, "--rom", rom_rel,
                           "--timeout", str(timeout)], cwd=lane, env=full_env)
    return proc.returncode


def build_header(title, kind, lane, rows, timeout, tracked_before=None, bw_hashes=None):
    """The header lines, the env they were built from, the staged rom path, and
    (tracked_before, tracked_after) -- everything the receipt needs except the probe's own
    result text.

    tracked_before: the lane_tracked_clean() sampled before the run started; None means "sample
    it now" (used when build_header is called standalone, with no run in between, so before
    and after are necessarily the same). tracked_after is always sampled fresh here. The
    header's own 'tracked_clean=' field is their AND, per OMP's C4-RECEIPT-TOOLS review: a lane
    that goes clean -> dirty (or the reverse) during the run is not a clean re-take either way.

    bw_hashes, if given, is (path, raw_text, doc) from _read_bw_hashes -- its JSON is inlined
    right after the SLINK_BW_HASHES path and its prep strings become the '# states:' line,
    matching docs/gen3/probes/checkpoint_fr_clean_2b_rows_2026-09-23.txt.
    """
    rom_rel = staged_rom_rel(title)
    env = build_env(title, lane, rows, kind)
    tracked_after = lane_tracked_clean(lane)
    if tracked_before is None:
        tracked_before = tracked_after
    tracked_ok = tracked_before and tracked_after
    lines = [
        f"# probe_gen3_checkpoint.lua title={title} kind={kind} lane={lane_head_sha(lane)} "
        f"tracked_clean_before={tracked_before} tracked_clean_after={tracked_after} "
        f"tracked_clean={tracked_ok}",
        f"# script={PROBE_SCRIPT} sha256(git blob, LF)={git_blob_sha256(lane, PROBE_SCRIPT)}",
        f"# rom={rom_rel} sha1={file_sha1(os.path.join(lane, rom_rel))}",
        f"# SLINK_STATE_DIR={env['SLINK_STATE_DIR']}",
    ]
    if "SLINK_CHECKPOINT_OLDMAN_STATE" in env:
        lines.append(f"# SLINK_CHECKPOINT_OLDMAN_STATE={env['SLINK_CHECKPOINT_OLDMAN_STATE']}")
        lines.append(f"# SLINK_CHECKPOINT_POKEDUDE_STATE={env['SLINK_CHECKPOINT_POKEDUDE_STATE']}")
    if "SLINK_BW_HASHES" in env:
        if bw_hashes:
            _path, raw_text, _doc = bw_hashes
            lines.append(f"# SLINK_BW_HASHES={env['SLINK_BW_HASHES']}: {raw_text}")
        else:
            lines.append(f"# SLINK_BW_HASHES={env['SLINK_BW_HASHES']}")
    lines.append(f"# SLINK_CHECKPOINT_ROWS={env['SLINK_CHECKPOINT_ROWS']}")
    if bw_hashes:
        _path, _raw_text, doc = bw_hashes
        note = _bw_states_note(doc)
        if note:
            lines.append(f"# states: {note}")
    lines.append(f"# invocation: {invocation_line(env, rom_rel, timeout)}")
    return lines, env, rom_rel, tracked_before, tracked_after


# ---------------------------------------------------------------------------
# The generic run-receipt header (card G4-FINALCUT-RUNNER): every row tools/gen3_final_cut.py
# runs -- a duo scenario, a state build, a boot-check, the zip rows, item 6 -- is written through
# this, the same shape the G4-LANE-2 ph_* receipts were written by hand (lane, cut, tracked_clean
# before/after, LOAD snapshot, start/end UTC, the command, the output verbatim, exit code).
# ---------------------------------------------------------------------------

RUN_RECEIPT_TAG = "# gen3_final_cut"


def run_receipt_text(*, row, item, cut, lane, command, cwd, env, attempts, verdict, note=""):
    """The receipt text. `attempts` is a list of dicts with start_utc, end_utc, rc, load,
    tracked_before, tracked_after, classification and output (verbatim); `verdict` is the
    row's final word (PASS / FAIL <why> / SKIP-ALLOWED <ruling> / STOPPED / CARRIED from ...).
    `note` lines follow the verdict, each as a '# ' line (a CARRIED row's checked evidence)."""
    lines = [f"{RUN_RECEIPT_TAG} row={row} item={item} cut={cut}",
             f"# lane={lane}",
             f"# command: {command}   (cwd={cwd})",
             f"# env: {' '.join(f'{k}={v}' for k, v in env.items()) or '(none)'}",
             f"# verdict: {verdict}"]
    lines += [f"# {ln}" for ln in note.splitlines()]
    for i, a in enumerate(attempts, 1):
        lines += [f"--- attempt {i} of {len(attempts)} ---",
                  f"LOAD {a['load']}",
                  f"start_utc={a['start_utc']} tracked_clean_before={a['tracked_before']}",
                  a["output"].rstrip("\n"),
                  f"exit={a['rc']} end_utc={a['end_utc']} tracked_clean_after={a['tracked_after']}"
                  f" classification={a['classification']}"]
    return "\n".join(lines) + "\n"


def read_run_receipt(path):
    """{row, item, cut, verdict} from a run receipt's header, or None when `path` is missing or
    is not one (a hand-written receipt never counts as a runner PASS)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return parse_run_receipt(f.read())
    except OSError:
        return None


def parse_run_receipt(text):
    """read_run_receipt on text already in hand."""
    head = (text.splitlines() + [""] * 5)[:5]
    if not head[0].startswith(RUN_RECEIPT_TAG + " "):
        return None
    fields = dict(kv.split("=", 1) for kv in head[0][len(RUN_RECEIPT_TAG):].split() if "=" in kv)
    verdict = next((ln[len("# verdict: "):].strip() for ln in head
                    if ln.startswith("# verdict: ")), "")
    return {"row": fields.get("row"), "item": fields.get("item"), "cut": fields.get("cut"),
            "verdict": verdict}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", required=True,
                     choices=sorted(gen3_fixtures.PARTY_TITLES) + ["radical_red"])
    ap.add_argument("--lane", required=True)
    ap.add_argument("--kind", default="clean")
    ap.add_argument("--rows", default=",".join(DEFAULT_ROWS),
                     help="comma list (default: the full §6 row list, base + bw)")
    ap.add_argument("--out", default=None,
                     help="filename under docs/gen3/probes/ (default: computed; sanitised to "
                          "a bare basename either way)")
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--dry-run", action="store_true", help="print the env and command, no launch")
    args = ap.parse_args()

    if args.title == "radical_red":
        print("radical_red refused: RR receipts are G5; use the companion pack tooling",
              file=sys.stderr)
        return 1

    rows = [r.strip() for r in args.rows.split(",") if r.strip()]
    has_bw = any(r.startswith("bw_") for r in rows)

    if args.dry_run:
        env = build_env(args.title, args.lane, rows, args.kind)
        rom_rel = staged_rom_rel(args.title)
        if has_bw:
            print(f"[dry-run] python tools/gen3_bw_hashes.py {args.title} {args.lane}"
                  f"  (cwd={args.lane})")
        for k, v in env.items():
            print(f"{k}={v}")
        print(f"[dry-run] {invocation_line(env, rom_rel, args.timeout)}  (cwd={args.lane})")
        return 0

    tracked_before = lane_tracked_clean(args.lane)

    bw_hashes = None
    if has_bw:
        try:
            run_bw_hashes(args.title, args.lane)
        except subprocess.CalledProcessError as exc:
            print(f"gen3_bw_hashes.py failed (rc={exc.returncode}): refusing to launch the probe",
                  file=sys.stderr)
            return 1
        bw_hashes = _read_bw_hashes(args.lane, args.title)

    env = build_env(args.title, args.lane, rows, args.kind)
    rom_rel = staged_rom_rel(args.title)
    rc = run_probe(PROBE_SCRIPT, rom_rel, args.timeout, args.lane, env)

    lines, env, rom_rel, tracked_before, tracked_after = build_header(
        args.title, args.kind, args.lane, rows, args.timeout, tracked_before, bw_hashes)

    result_path = _result_path_for_lane(args.lane, PROBE_SCRIPT)
    if result_path and os.path.exists(result_path):
        with open(result_path, encoding="utf-8", errors="replace") as f:
            result_text = f.read()
        last_line = next((ln for ln in reversed(result_text.splitlines()) if ln.strip()), "")
        passed = last_line.strip() == PASS_LINE
    else:
        print(f"no result file for {PROBE_SCRIPT} at lane {args.lane}", file=sys.stderr)
        result_text, passed = "", False

    if rc != 0:
        print(f"run_gate.py exited {rc}: treating as failure regardless of result content",
              file=sys.stderr)
        passed = False
    if not (tracked_before and tracked_after):
        print(f"tracked_clean changed during the run (before={tracked_before} "
              f"after={tracked_after}): treating as failure", file=sys.stderr)
        passed = False

    out_name = os.path.basename(
        args.out or f"checkpoint_{args.title}_{args.kind}_c4receipt_"
                     f"{datetime.date.today():%Y-%m-%d}.txt")
    out_path = os.path.join(REPO, "docs", "gen3", "probes", out_name)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n" + result_text)
    print(out_path)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
