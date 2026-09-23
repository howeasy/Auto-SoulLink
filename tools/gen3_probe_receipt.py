#!/usr/bin/env python3
"""gen3_probe_receipt.py -- run probe_gen3_checkpoint.lua for one title at a lane and write a
committed-style receipt to docs/gen3/probes/<name>.txt (G4 final-cut runbook §6, §12 item 3).

Usage:
    python tools/gen3_probe_receipt.py --title firered --lane <lane>
    python tools/gen3_probe_receipt.py --title leafgreen --lane <lane> --dry-run
    python tools/gen3_probe_receipt.py --title firered --lane <lane> --rows script_running,sound_driver

The receipt is a header (title/kind/lane/tracked_clean, the probe script's COMMITTED sha256,
the staged ROM's sha1, every env var used, the exact invocation) followed verbatim by the
probe's own result file -- docs/gen3/probes/checkpoint_fr_clean_c4probe2_2026-09-23.txt is the
model this follows. --dry-run only prints the env and the two commands (gen3_bw_hashes.py, if
any bw_* row is selected, then run_gate.py) -- nothing is launched, nothing is written.

Exit: 0 only if the probe's result file's last non-blank line is exactly
"RESULT: PASS all checkpoint controls"; non-zero otherwise (a failing/incomplete result, a
missing result file, or a failed gen3_bw_hashes.py run).
"""
import argparse
import datetime
import hashlib
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

# The full §6 row list: the eleven core reason rows plus the nine G4 2b battle-window rows.
BASE_ROWS = ["script_running", "battle_input_wild", "battle_input_trainer", "battle_move_menu",
             "battle_animation", "battle_faint_prompt", "battle_intro", "battle_over",
             "battle_commit_state3", "native_absent", "sound_driver"]
BW_ROWS = ["bw_n1_action_draw", "bw_n4_bag", "bw_n5_party", "bw_n6_summary", "bw_n7_switch",
           "bw_n9_run", "bw_u1_oldman", "bw_u2_pokedude", "bw_n8_item"]
DEFAULT_ROWS = BASE_ROWS + BW_ROWS

# Header env lines, in this fixed order -- only the ones actually set are printed.
_HEADER_ENV_KEYS = ("SLINK_STATE_DIR", "SLINK_CHECKPOINT_ROWS", "SLINK_BW_HASHES",
                     "SLINK_CHECKPOINT_OLDMAN_STATE", "SLINK_CHECKPOINT_POKEDUDE_STATE")


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
        # .lua:1004's state_path treats any name containing a slash as already-resolved).
        env["SLINK_BW_HASHES"] = f"{lane}/patch/build/bw_hashes_{title}.json"
        env["SLINK_CHECKPOINT_OLDMAN_STATE"] = \
            f"{lane}/patch/build/gen3_probe_states/{title}/slink_oldman.State"
        env["SLINK_CHECKPOINT_POKEDUDE_STATE"] = \
            f"{lane}/patch/build/gen3_probe_states/{title}/slink_pokedude.State"
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
    own -- the regex logic is run_gate's; only REPO/BUILD move."""
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


def run_probe(script, rom_rel, timeout, lane, env):
    """python tools/run_gate.py <script> --rom <rom_rel> --timeout <timeout>, the LANE's own
    copy (cwd=lane); the emulator launch itself lives in run_gate.py, not here."""
    full_env = dict(os.environ, **env)
    subprocess.run([sys.executable, "tools/run_gate.py", script, "--rom", rom_rel,
                    "--timeout", str(timeout)], cwd=lane, env=full_env)


def build_header(title, kind, lane, rows, timeout):
    """The header lines, the env they were built from, and the staged rom path -- everything
    the receipt needs except the probe's own result text."""
    rom_rel = staged_rom_rel(title)
    env = build_env(title, lane, rows, kind)
    lines = [
        f"# probe_gen3_checkpoint.lua title={title} kind={kind} lane={lane_head_sha(lane)} "
        f"tracked_clean={lane_tracked_clean(lane)}",
        f"# script={PROBE_SCRIPT} sha256(git blob, LF)={git_blob_sha256(lane, PROBE_SCRIPT)}",
        f"# rom={rom_rel} sha1={file_sha1(os.path.join(lane, rom_rel))}",
    ]
    for key in _HEADER_ENV_KEYS:
        if key in env:
            lines.append(f"# {key}={env[key]}")
    lines.append(f"# invocation: {invocation_line(env, rom_rel, timeout)}")
    return lines, env, rom_rel


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", required=True, choices=sorted(gen3_fixtures.PARTY_TITLES))
    ap.add_argument("--lane", required=True)
    ap.add_argument("--kind", default="clean")
    ap.add_argument("--rows", default=",".join(DEFAULT_ROWS),
                     help="comma list (default: the full §6 row list, base + bw)")
    ap.add_argument("--out", default=None,
                     help="filename under docs/gen3/probes/ (default: computed)")
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--dry-run", action="store_true", help="print the env and command, no launch")
    args = ap.parse_args()

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

    if has_bw:
        try:
            run_bw_hashes(args.title, args.lane)
        except subprocess.CalledProcessError as exc:
            print(f"gen3_bw_hashes.py failed (rc={exc.returncode}): refusing to launch the probe",
                  file=sys.stderr)
            return 1

    lines, env, rom_rel = build_header(args.title, args.kind, args.lane, rows, args.timeout)
    run_probe(PROBE_SCRIPT, rom_rel, args.timeout, args.lane, env)

    result_path = _result_path_for_lane(args.lane, PROBE_SCRIPT)
    if not result_path or not os.path.exists(result_path):
        print(f"no result file for {PROBE_SCRIPT} at lane {args.lane}", file=sys.stderr)
        return 1
    with open(result_path, encoding="utf-8", errors="replace") as f:
        result_text = f.read()
    last_line = next((ln for ln in reversed(result_text.splitlines()) if ln.strip()), "")
    passed = last_line.strip() == PASS_LINE

    out_name = (args.out or
                f"checkpoint_{args.title}_{args.kind}_c4receipt_{datetime.date.today():%Y-%m-%d}.txt")
    out_path = os.path.join(REPO, "docs", "gen3", "probes", out_name)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n" + result_text)
    print(out_path)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
