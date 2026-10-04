"""Re-judge retained Gen 1 SYNTH rows without launching a server or emulator.

Original receipts/PYDEC are never rewritten. Run from the oracle-fix checkout:
  python tools/rejudge_gen1_synth.py --lane-root F:/.../gen1-targeted \
    --archive F:/.../targeted_evidence/gen1_new/explode_new \
    --game gen1_new --scenario explode_new --lane g1t-rb
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import subprocess
from pathlib import Path

if __package__:
    from . import e2e_duo as duo
else:
    import e2e_duo as duo

ROWS = ("explode_new", "linked_faint_active_new", "explode_bench_battle_new")


def unique(values, label):
    values = set(values)
    if len(values) != 1:
        raise RuntimeError(f"ambiguous or missing {label}: {values}")
    return values.pop()


def revision(root):
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


class ArchivedRun(duo.DuoRun):
    def _rom_for(self, inst):
        return str(self.roms[inst])

    def check_save_witness(self, results):
        return super().check_save_witness(results, archived_paths=self.witnesses)


@contextlib.contextmanager
def lane_paths(root):
    old = duo.REPO, duo.BUILD
    duo.REPO, duo.BUILD = str(root), str(root / "patch/build")
    try:
        yield
    finally:
        duo.REPO, duo.BUILD = old


def prepare(root, archive, game, scenario, lane):
    """Reconstruct only oracle inputs; never invoke DuoRun's launch constructor."""
    if game not in ("gen1_new", "gen1_pure") or scenario not in ROWS:
        raise ValueError("only the six targeted Gen 1 SYNTH rows are supported")
    run = ArchivedRun.__new__(ArchivedRun)
    run.game, run.scenario, run._lane = game, scenario, lane
    run.cfg, run.gcfg = dict(duo.SCENARIOS[scenario]), dict(duo.GAMES[game])
    run.emus = []
    original = archive / f"e2e_{scenario}_pydec_result.txt"
    text = original.read_text(encoding="utf-8")
    setups = [json.loads(line[len("GEN1_SYNTH_SETUP "):]) for line in text.splitlines()
              if line.startswith("GEN1_SYNTH_SETUP ")]
    if len(setups) != 2 or {row["inst"] for row in setups} != {"a", "b"}:
        raise RuntimeError("need one original setup disclosure per side")
    run.attempt = unique([row["attempt"] for row in setups], "attempt")
    if any(row["scenario"] != scenario for row in setups):
        raise RuntimeError("setup scenario mismatch")
    run.data_dir = str(unique([str(Path(row["fixture"]).parent) for row in setups], "kept data directory"))
    kept = re.findall(r"(?m)^\[duo\] data dir kept: (.+)$", (archive / "stdout.log").read_text(encoding="utf-8"))
    if not kept or Path(kept[-1]) != Path(run.data_dir):
        raise RuntimeError("setup and runner disagree about kept data directory")
    run._gen1_synth_fixtures = {row["inst"]: (row["fixture"], row["fixture_sha256"], row) for row in setups}
    results, run.roms, run.witnesses = {}, {}, {}
    run._boot_keys, run._link_keys = {}, {}
    inputs = [original, archive / "stdout.log", Path(run.data_dir) / "links.json",
              Path(run.data_dir) / "slink.log", Path(run.data_dir) / "events.json"]
    for inst in ("a", "b"):
        path = archive / f"e2e_{scenario}_{inst}_result.txt"
        receipt = path.read_text(encoding="utf-8")
        if f"duo instance {inst} scenario={scenario} game=gen1_new" not in receipt:
            raise RuntimeError(f"{inst}: wrong receipt header")
        verdicts = re.findall(r"(?m)^RESULT: (.+)$", receipt)
        if len(verdicts) != 1 or not verdicts[0].startswith("PASS ("):
            raise RuntimeError(f"{inst}: game-side PASS required")
        attempts = re.findall(r"(?m)^attempt (\d+) of \d+$", receipt)
        if attempts != [str(run.attempt)]:
            raise RuntimeError(f"{inst}: receipt attempt mismatch")
        run._boot_keys[inst] = re.findall(r"(?m)^MYKEY 0 (\S+)$", receipt)[0]
        run._link_keys[inst] = unique(re.findall(r"(?m)^CAUGHT (\S+)$", receipt), f"{inst} captured key")
        rom_rows = re.findall(rf"(?m)^GEN1_ROM_SHA1 inst={inst} rom=(.+) sha1=([0-9a-f]{{40}}) .*match=true$", text)
        rom_rel, expected_sha = unique(rom_rows, f"{inst} original cartridge binding")
        run.roms[inst] = root / rom_rel
        if hashlib.sha1(run.roms[inst].read_bytes()).hexdigest() != expected_sha:
            raise RuntimeError(f"{inst}: original cartridge hash changed")
        run.witnesses[inst] = archive / f"e2e_{scenario}_{inst}_{run.attempt}_witness.bin"
        save = Path(run._saveram_dir(inst)) / run._gen1_save_name(inst)
        inputs.extend([path, run.roms[inst], run.witnesses[inst], save,
                       Path(run._gen1_synth_fixtures[inst][0])])
        results[inst] = receipt
    return run, results, setups, inputs


def rejudge(root, archive, game, scenario, lane):
    root, archive = Path(root).resolve(), Path(archive).resolve()
    fix_root = Path(__file__).resolve().parents[1]
    fix_sha = revision(fix_root)
    if subprocess.check_output(["git", "-C", str(fix_root), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise RuntimeError("commit oracle changes before rejudging")
    with lane_paths(root):
        run, results, setups, inputs = prepare(root, archive, game, scenario, lane)
        hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
        output = archive / f"rejudged_{fix_sha[:8]}_pydec_result.txt"
        with output.open("x", encoding="utf-8") as handle:
            handle.write(f"TARGETED OFFLINE REJUDGMENT rejudged with {fix_sha}\n")
            handle.write(f"live_source={revision(root)} game={game} scenario={scenario} attempt={run.attempt}\n")
            handle.write("INPUT_SHA256 " + json.dumps(hashes, sort_keys=True) + "\n")
            for row in setups:
                handle.write("GEN1_SYNTH_SETUP " + json.dumps(row, sort_keys=True) + "\n")
        run._pydec_path = str(output)
        try:
            run._run_oracle(results)
            if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest for path, digest in hashes.items()):
                raise RuntimeError("input changed during offline rejudgment")
        except Exception as exc:
            run._pydec_note(f"PYDEC: FAIL offline rejudgment: {exc}")
            raise
        run._pydec_note("PYDEC: PASS offline rejudgment; original live verdict retained")
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane-root", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--game", choices=("gen1_new", "gen1_pure"), required=True)
    parser.add_argument("--scenario", choices=ROWS, required=True)
    parser.add_argument("--lane", required=True)
    args = parser.parse_args()
    print(rejudge(args.lane_root, args.archive, args.game, args.scenario, args.lane))


if __name__ == "__main__":
    main()
