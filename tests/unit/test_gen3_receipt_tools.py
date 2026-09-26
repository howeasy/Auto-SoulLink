"""tools/gen3_bw_hashes.py and tools/gen3_probe_receipt.py (card C4-RECEIPT-TOOLS): the missing
SLINK_BW_HASHES producer and the probe receipt wrapper, G4 final-cut runbook §12 items 2/3, plus
the OMP C4-RECEIPT-TOOLS follow-up review's fixes (tracked_clean before/after, stale-result/exit-
code safety, receipt shape vs the committed model, RR refusal). Pure Python -- no emulator, no
real BizHawk launch (the run_gate/run_probe call is monkeypatched away in every test that would
otherwise launch one; gen3_bw_hashes.py's own subprocess IS let run for real in a couple of
tests, since it is plain hashing/JSON with no emulator involved).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import gen3_bw_hashes  # noqa: E402
import gen3_probe_receipt as receipt  # noqa: E402

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
MODEL_RECEIPT = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "gen3", "probes",
                              "checkpoint_fr_clean_2b_rows_2026-09-23.txt")


def _git(lane, *args, **kw):
    return subprocess.run(["git", "-C", str(lane), *args], check=True,
                           capture_output=True, **kw)


def _init_git_lane(lane):
    _git(lane, "init", "-q")
    _git(lane, "config", "user.email", "t@example.com")
    _git(lane, "config", "user.name", "t")


def _commit_all(lane, msg="wip"):
    _git(lane, "add", "-A")
    _git(lane, "commit", "-q", "-m", msg)


# ---------------------------------------------------------------------------
# gen3_bw_hashes.py
# ---------------------------------------------------------------------------

def _seed_bw_states(lane, title="firered"):
    (lane / "data" / "games" / "gen3_frlg").mkdir(parents=True, exist_ok=True)
    (lane / "data" / "games" / "gen3_frlg" / "write_checkpoint.json").write_bytes(b"{}")
    c4p2 = lane / "patch" / "build" / "gen3_probe_states_c4p2" / title
    c4p2.mkdir(parents=True, exist_ok=True)
    (c4p2 / "slink_preintro.State").write_bytes(b"preintro")
    (c4p2 / "slink_prebattle.State").write_bytes(b"prebattle")
    tut = lane / "patch" / "build" / "gen3_probe_states" / title
    tut.mkdir(parents=True, exist_ok=True)
    (tut / "slink_oldman.State").write_bytes(b"oldman")
    (tut / "slink_pokedude.State").write_bytes(b"pokedude")
    fx = lane / "tests" / "fixtures" / "gen3"
    fx.mkdir(parents=True, exist_ok=True)
    (fx / f"{title}_party_battle.sav").write_bytes(b"battle-fixture")
    (fx / f"{title}_party_town.sav").write_bytes(b"town-fixture")


def _make_bw_lane(tmp_path, title="firered"):
    lane = tmp_path / "lane"
    _seed_bw_states(lane, title)
    _init_git_lane(lane)
    _commit_all(lane)
    return lane


def test_bw_hashes_shape_matches_probe_contract(tmp_path):
    lane = _make_bw_lane(tmp_path)
    out, doc = gen3_bw_hashes.build("firered", str(lane))
    assert out == f"{lane}/patch/build/bw_hashes_firered.json"
    assert doc["pack"] == hashlib.sha256(b"{}").hexdigest()
    assert doc["source"] == _git(lane, "rev-parse", "HEAD").stdout.decode().strip()
    for name in ("slink_preintro.State", "slink_prebattle.State",
                 "slink_oldman.State", "slink_pokedude.State"):
        st = doc["states"][name]
        assert set(st) == {"state", "fixture", "prep"}
        assert len(st["state"]) == 64 and len(st["fixture"]) == 64
        assert st["prep"]
    assert doc["states"]["slink_preintro.State"]["fixture"] == hashlib.sha256(
        b"battle-fixture").hexdigest()
    assert doc["states"]["slink_oldman.State"]["fixture"] == hashlib.sha256(
        b"town-fixture").hexdigest()


def test_bw_hashes_missing_state_refuses_falsifier(tmp_path):
    """A missing state file refuses with a clear error, and nothing is written."""
    lane = _make_bw_lane(tmp_path)
    os.remove(lane / "patch" / "build" / "gen3_probe_states" / "firered" / "slink_oldman.State")
    with pytest.raises(FileNotFoundError, match="slink_oldman.State"):
        gen3_bw_hashes.build("firered", str(lane))
    assert not (lane / "patch" / "build" / "bw_hashes_firered.json").exists()


def test_bw_hashes_cli_writes_full_json(tmp_path):
    lane = _make_bw_lane(tmp_path)
    out = subprocess.check_output(
        [sys.executable, os.path.join(TOOLS_DIR, "gen3_bw_hashes.py"), "firered", str(lane)],
        text=True).strip()
    assert os.path.exists(out)
    with open(out, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["states"]["slink_pokedude.State"]["prep"]


# ---------------------------------------------------------------------------
# gen3_probe_receipt.py
# ---------------------------------------------------------------------------

def _make_probe_lane(tmp_path, dirty=False, with_bw_states=False, name="lane2"):
    lane = tmp_path / name
    (lane / "lua" / "tests").mkdir(parents=True)
    (lane / "lua" / "tests" / "probe_gen3_checkpoint.lua").write_bytes(
        b'G.open("probe_gen3_checkpoint")\n')
    (lane / "patch" / "build").mkdir(parents=True)
    rom_path = lane / receipt.staged_rom_rel("firered")
    rom_path.parent.mkdir(parents=True, exist_ok=True)
    rom_path.write_bytes(b"fake-rom-bytes")
    if with_bw_states:
        _seed_bw_states(lane, "firered")
    _init_git_lane(lane)
    _commit_all(lane)
    if dirty:
        (lane / "lua" / "tests" / "probe_gen3_checkpoint.lua").write_bytes(
            b'G.open("probe_gen3_checkpoint")\nextra\n')
    return lane


def _write_result(lane, text):
    (lane / "patch" / "build" / "probe_gen3_checkpoint_result.txt").write_text(
        text, encoding="utf-8")


def _result_path(lane):
    return lane / "patch" / "build" / "probe_gen3_checkpoint_result.txt"


def test_dry_run_prints_env_and_command_and_launches_nothing(tmp_path, monkeypatch, capsys):
    lane = tmp_path / "nolane"  # need not exist -- dry-run touches no filesystem/git
    calls = []
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: calls.append("probe"))
    monkeypatch.setattr(receipt, "run_bw_hashes", lambda *a, **k: calls.append("bw"))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane), "--dry-run",
        "--rows", "script_running,bw_n1_action_draw"])
    rc = receipt.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == []
    assert "SLINK_STATE_DIR=" in out
    assert "SLINK_BW_HASHES=" in out
    assert "SLINK_CHECKPOINT_OLDMAN_STATE=" in out
    assert "tools/run_gate.py" in out
    assert "tools/gen3_bw_hashes.py" in out


def test_dry_run_without_bw_rows_omits_bw_hashes(tmp_path, capsys):
    lane = tmp_path / "nolane"
    sys.argv = ["gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
                "--dry-run", "--rows", "script_running,sound_driver"]
    rc = receipt.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "SLINK_BW_HASHES" not in out
    assert "gen3_bw_hashes.py" not in out


def test_dirty_lane_reports_tracked_clean_false_falsifier(tmp_path):
    lane = _make_probe_lane(tmp_path, dirty=True)
    lines, _env, _rom, before, after = receipt.build_header(
        "firered", "clean", str(lane), receipt.BASE_ROWS, 1200)
    assert before is False and after is False
    assert "tracked_clean=False" in lines[0]


def test_clean_lane_reports_tracked_clean_true(tmp_path):
    lane = _make_probe_lane(tmp_path, dirty=False)
    lines, _env, _rom, before, after = receipt.build_header(
        "firered", "clean", str(lane), receipt.BASE_ROWS, 1200)
    assert before is True and after is True
    assert "tracked_clean=True" in lines[0]


def test_script_sha_is_git_blob_not_crlf_working_file_falsifier(tmp_path):
    lane = _make_probe_lane(tmp_path, dirty=False)
    script_path = lane / "lua" / "tests" / "probe_gen3_checkpoint.lua"
    committed_blob = _git(lane, "show", "HEAD:lua/tests/probe_gen3_checkpoint.lua").stdout
    expected = hashlib.sha256(committed_blob).hexdigest()
    # Mangle the working-tree file into CRLF, as a Windows core.autocrlf checkout would, WITHOUT
    # re-committing -- the header must still report the committed blob's hash, not this one.
    script_path.write_bytes(committed_blob.replace(b"\n", b"\r\n"))
    working_file_hash = hashlib.sha256(script_path.read_bytes()).hexdigest()
    assert working_file_hash != expected
    lines, _env, _rom, _b, _a = receipt.build_header(
        "firered", "clean", str(lane), receipt.BASE_ROWS, 1200)
    header = "\n".join(lines)
    assert f"sha256(git blob, LF)={expected}" in header
    assert working_file_hash not in header


# --- OMP fix 1: tracked_clean sampled before AND after --------------------------------------

def test_lane_going_dirty_during_the_run_fails_falsifier(tmp_path, monkeypatch):
    """A lane that is clean when the run STARTS but has dropped/gained a tracked file by the
    time it ENDS (the observed failure: 22 tracked files missing after a Drive checkout) must
    be recorded as such and must fail, even though the probe itself reported PASS."""
    lane = _make_probe_lane(tmp_path, dirty=False)
    _write_result(lane, "RESULT: PASS all checkpoint controls\n")

    def dirty_the_lane_then_pass(*a, **k):
        (lane / "lua" / "tests" / "probe_gen3_checkpoint.lua").write_bytes(
            b'G.open("probe_gen3_checkpoint")\nmodified-mid-run\n')
        return 0

    monkeypatch.setattr(receipt, "run_probe", dirty_the_lane_then_pass)
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "script_running", "--out", "test_receipt_dirty_mid_run.txt"])
    rc = receipt.main()
    assert rc == 1
    text = (tmp_path / "docs" / "gen3" / "probes" / "test_receipt_dirty_mid_run.txt").read_text(
        encoding="utf-8")
    assert "tracked_clean_before=True" in text
    assert "tracked_clean_after=False" in text
    assert "tracked_clean=False" in text.splitlines()[0]


def test_clean_lane_throughout_keeps_tracked_clean_true(tmp_path, monkeypatch):
    lane = _make_probe_lane(tmp_path, dirty=False)
    _write_result(lane, "RESULT: PASS all checkpoint controls\n")
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: 0)
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "script_running", "--out", "test_receipt_clean.txt"])
    rc = receipt.main()
    assert rc == 0
    text = (tmp_path / "docs" / "gen3" / "probes" / "test_receipt_clean.txt").read_text(
        encoding="utf-8")
    assert "tracked_clean_before=True tracked_clean_after=True tracked_clean=True" in text


# --- OMP fix 2: stale result + child exit code -----------------------------------------------

def test_run_probe_deletes_stale_result_before_launching(tmp_path, monkeypatch):
    lane = _make_probe_lane(tmp_path)
    _write_result(lane, "RESULT: PASS all checkpoint controls\n")
    assert _result_path(lane).exists()

    calls = []

    class _FakeCompleted:
        returncode = 0

    def fake_run(cmd, cwd=None, env=None):
        calls.append(cmd)
        return _FakeCompleted()

    monkeypatch.setattr(receipt.subprocess, "run", fake_run)
    rc = receipt.run_probe(receipt.PROBE_SCRIPT, "patch/build/dummy.gba", 10, str(lane), {})
    assert rc == 0
    assert calls, "run_gate.py was never launched"
    assert not _result_path(lane).exists(), "stale result must be deleted before launch"


def test_stale_pass_file_plus_nonzero_child_exit_fails_falsifier(tmp_path, monkeypatch):
    """The exact OMP scenario: a stale PASS-shaped result file already sits in the lane, and
    the emulator launch itself fails (non-zero child exit). run_probe is monkeypatched here to
    skip real deletion (simulating a launcher that never gets that far), so this isolates
    main()'s own 'a non-zero child exit is always a failure' rule."""
    lane = _make_probe_lane(tmp_path)
    _write_result(lane, "RESULT: PASS all checkpoint controls\n")
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: 1)  # child exited non-zero
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "script_running", "--out", "test_receipt_stale.txt"])
    rc = receipt.main()
    assert rc == 1


def test_full_run_pass_writes_receipt_and_exits_zero(tmp_path, monkeypatch):
    lane = _make_probe_lane(tmp_path)
    _write_result(lane, "phase probe-state frame=1\nRESULT: PASS all checkpoint controls\n")
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: 0)
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "script_running", "--out", "test_receipt.txt"])
    rc = receipt.main()
    assert rc == 0
    written = tmp_path / "docs" / "gen3" / "probes" / "test_receipt.txt"
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    assert text.startswith("# probe_gen3_checkpoint.lua title=firered kind=clean")
    assert "# invocation: SLINK_GEN3_CHECKPOINT=" in text
    assert text.rstrip().endswith("RESULT: PASS all checkpoint controls")


def test_full_run_non_pass_last_line_exits_nonzero_falsifier(tmp_path, monkeypatch):
    lane = _make_probe_lane(tmp_path)
    _write_result(lane, "phase probe-state frame=1\nRESULT: FAIL something broke\n")
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: 0)
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "script_running", "--out", "test_receipt2.txt"])
    rc = receipt.main()
    assert rc == 1
    # still written, so a failed re-take is inspectable -- only the exit code signals PASS/FAIL
    assert (tmp_path / "docs" / "gen3" / "probes" / "test_receipt2.txt").exists()


def test_full_run_missing_result_file_exits_nonzero(tmp_path, monkeypatch):
    lane = _make_probe_lane(tmp_path)  # no result file written at all
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: 0)
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "script_running"])
    rc = receipt.main()
    assert rc == 1


def test_full_run_calls_bw_hashes_before_probe_when_bw_rows_selected(tmp_path, monkeypatch):
    lane = _make_probe_lane(tmp_path, with_bw_states=True)
    _write_result(lane, "RESULT: PASS all checkpoint controls\n")
    order = []

    def fake_bw_hashes(title, lane_):
        order.append(("bw", title, lane_))
        # a real gen3_bw_hashes.py would have written this file by now
        _out, doc = gen3_bw_hashes.build(title, lane_)
        with open(f"{lane_}/patch/build/bw_hashes_{title}.json", "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def fake_probe(*a, **k):
        order.append(("probe",))
        return 0

    monkeypatch.setattr(receipt, "run_bw_hashes", fake_bw_hashes)
    monkeypatch.setattr(receipt, "run_probe", fake_probe)
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "bw_n1_action_draw", "--out", "test_receipt3.txt"])
    rc = receipt.main()
    assert rc == 0
    assert order == [("bw", "firered", str(lane)), ("probe",)]


# --- OMP fix 3: header shape vs the committed model receipt -----------------------------------

def test_header_shape_matches_model_ordering_item3(tmp_path):
    lane = _make_probe_lane(tmp_path, with_bw_states=True)
    # run_bw_hashes launches "tools/gen3_bw_hashes.py" relative to cwd=lane (the lane's OWN
    # copy, same reproducibility rule as run_gate.py); this fake lane needs one to run for real.
    (lane / "tools").mkdir(exist_ok=True)
    shutil.copy(os.path.join(TOOLS_DIR, "gen3_bw_hashes.py"), lane / "tools" / "gen3_bw_hashes.py")
    receipt.run_bw_hashes("firered", str(lane))  # real gen3_bw_hashes.py, no emulator involved
    bw = receipt._read_bw_hashes(str(lane), "firered")
    lines, _env, _rom, _b, _a = receipt.build_header(
        "firered", "clean", str(lane), receipt.DEFAULT_ROWS, 1200,
        tracked_before=True, bw_hashes=bw)
    order = ["SLINK_CHECKPOINT_OLDMAN_STATE", "SLINK_CHECKPOINT_POKEDUDE_STATE",
             "SLINK_BW_HASHES", "SLINK_CHECKPOINT_ROWS"]
    idx = {}
    for i, ln in enumerate(lines):
        for name in order:
            if ln.startswith(f"# {name}="):
                idx[name] = i
    assert list(idx) == order or sorted(idx, key=idx.get) == order
    assert idx["SLINK_CHECKPOINT_OLDMAN_STATE"] < idx["SLINK_CHECKPOINT_POKEDUDE_STATE"]
    assert idx["SLINK_CHECKPOINT_POKEDUDE_STATE"] < idx["SLINK_BW_HASHES"]
    assert idx["SLINK_BW_HASHES"] < idx["SLINK_CHECKPOINT_ROWS"]

    bw_line = next(ln for ln in lines if ln.startswith("# SLINK_BW_HASHES="))
    assert '"pack"' in bw_line and '"states"' in bw_line  # the JSON is inlined, not just named

    states_line = next((ln for ln in lines if ln.startswith("# states:")), None)
    assert states_line is not None
    assert "mkstates_gen3.py" in states_line
    assert "mkstates_gen3_tutorials.py" in states_line


# --- OMP fix 4: --out sanitised to a basename --------------------------------------------------

def test_out_sanitized_to_basename_item4(tmp_path, monkeypatch, capsys):
    lane = _make_probe_lane(tmp_path)
    _write_result(lane, "RESULT: PASS all checkpoint controls\n")
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: 0)
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "script_running", "--out", os.path.join("..", "..", "evil.txt")])
    rc = receipt.main()
    assert rc == 0
    printed = capsys.readouterr().out.strip().splitlines()[-1]
    expected = os.path.join(str(tmp_path), "docs", "gen3", "probes", "evil.txt")
    assert printed == expected
    assert os.path.exists(expected)
    assert not (tmp_path.parent / "evil.txt").exists()


# --- OMP fix 5: DEFAULT_ROWS vs the committed model receipt (7 core + 20) ---------------------

def test_default_rows_match_committed_model_receipt_item5():
    with open(MODEL_RECEIPT, encoding="utf-8") as f:
        text = f.read()
    pass_names = set(re.findall(r"^PROBE (\S+) PASS", text, re.M))
    core = {"idle", "walking", "start_menu", "dialog", "save", "battle", "fade"}
    assert len(core) == 7
    assert core <= pass_names
    reason_rows = pass_names - core
    assert reason_rows == set(receipt.DEFAULT_ROWS)
    assert len(receipt.DEFAULT_ROWS) == 20


# --- OMP fix 6: radical_red refused by name -----------------------------------------------------

def test_radical_red_refused_with_named_reason(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "radical_red", "--lane", "anywhere"])
    rc = receipt.main()
    err = capsys.readouterr().err
    assert rc == 1
    assert "RR receipts are G5" in err


# ---------------------------------------------------------------------------
# the generic run-receipt header (card G4-FINALCUT-RUNNER)
# ---------------------------------------------------------------------------

def test_run_receipt_round_trip(tmp_path):
    attempt = {"load": "2026-09-24T08:00:00 cpu=90% emuhawk=1 python=9",
               "start_utc": "2026-09-24T12:00:00Z", "end_utc": "2026-09-24T12:01:00Z", "rc": 0,
               "tracked_before": True, "tracked_after": True, "classification": "pass",
               "output": "[duo] active_end_gen3: a=PASS b=PASS\n"}
    text = receipt.run_receipt_text(
        row="active_end_gen3_lg_as_a", item="§5_item2b", cut="a" * 40, lane="L:/lane",
        command="python tools/e2e_duo.py --game gen3_lgfr --scenario active_end_gen3", cwd="L:/lane",
        env={"SLINK_LIVE": "1"}, attempts=[attempt], verdict="PASS")
    assert text.startswith(f"# gen3_final_cut row=active_end_gen3_lg_as_a item=§5_item2b cut={'a' * 40}\n")
    for want in ("# env: SLINK_LIVE=1", "# verdict: PASS", "--- attempt 1 of 1 ---",
                 "LOAD 2026-09-24T08:00:00 cpu=90%", "tracked_clean_before=True",
                 "[duo] active_end_gen3: a=PASS b=PASS",
                 "exit=0 end_utc=2026-09-24T12:01:00Z tracked_clean_after=True classification=pass"):
        assert want in text
    path = tmp_path / "fc.txt"
    path.write_text(text, encoding="utf-8")
    assert receipt.read_run_receipt(str(path)) == {
        "row": "active_end_gen3_lg_as_a", "item": "§5_item2b", "cut": "a" * 40, "verdict": "PASS"}


def test_read_run_receipt_ignores_hand_written_and_missing_files(tmp_path):
    hand = tmp_path / "ph.txt"
    hand.write_text("G4-LANE-2 P+H live row: active_end_gen3\nnote: PASS\n", encoding="utf-8")
    assert receipt.read_run_receipt(str(hand)) is None
    assert receipt.read_run_receipt(str(tmp_path / "nope.txt")) is None


# ---------------------------------------------------------------------------
# card E4b-CKPT: build_env() picks the checkpoint pack by title (finding 1 of E4b-FINALCUT's
# report); Emerald has no oldman/pokedude tutorial states, so its default --rows lets the pack's
# own admission table decide (no SLINK_CHECKPOINT_ROWS restriction, matching how E2's scratch
# driver C:/slink-wt/emerald-e2/run_probe.py actually invoked the probe: SLINK_CHECKPOINT_ROWS was
# never set in the two committed evidence receipts, docs/gen3_emerald/probes/checkpoint_emerald_
# {2026-09-25,battle_2026-09-26}.txt) and bw_* rows are refused by name, not pointed at states
# that were never built (tools/mkstates_gen3_tutorials.py and tools/gen3_bw_hashes.py both accept
# only --title firered/leafgreen).
# ---------------------------------------------------------------------------

def test_build_env_picks_the_checkpoint_pack_by_title():
    fr = receipt.build_env("firered", "L:/lane", [], "clean")
    lg = receipt.build_env("leafgreen", "L:/lane", [], "clean")
    em = receipt.build_env("emerald", "L:/lane", [], "clean")
    assert fr["SLINK_GEN3_CHECKPOINT"] == "L:/lane/data/games/gen3_frlg/write_checkpoint.json"
    assert lg["SLINK_GEN3_CHECKPOINT"] == "L:/lane/data/games/gen3_frlg/write_checkpoint.json"
    assert em["SLINK_GEN3_CHECKPOINT"] == "L:/lane/data/games/gen3_emerald/write_checkpoint.json"


def test_emerald_state_dir_is_the_same_directory_the_final_cut_states_rows_write():
    # tools/gen3_final_cut.py's states_emerald_{town,battle,trainer} rows write to exactly this
    # path (card E4b-FINALCUT) -- a future checkpoint_emerald row must read from where they wrote.
    env = receipt.build_env("emerald", "L:/lane", [], "clean")
    assert env["SLINK_STATE_DIR"] == "L:/lane/patch/build/gen3_probe_states_c4p2/emerald"


def test_emerald_default_rows_let_the_pack_decide_no_bw(tmp_path, capsys, monkeypatch):
    """No --rows given for --title emerald: SLINK_CHECKPOINT_ROWS is empty (the E2 driver never
    set it either -- P.planned() in lua/tests/probe_gen3_checkpoint.lua treats nil/"" identically,
    running every row the pack's own artifacts table admits) and no bw_* machinery is touched."""
    lane = tmp_path / "nolane"
    monkeypatch.setattr(sys, "argv",
                        ["gen3_probe_receipt.py", "--title", "emerald", "--lane", str(lane),
                         "--dry-run"])
    rc = receipt.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "SLINK_CHECKPOINT_ROWS=\n" in out   # empty value: no restriction, the pack decides
    assert "gen3_emerald/write_checkpoint.json" in out
    assert "SLINK_BW_HASHES" not in out
    assert "gen3_bw_hashes.py" not in out


def test_firered_default_rows_are_unchanged_by_the_emerald_fix(tmp_path, capsys, monkeypatch):
    lane = tmp_path / "nolane"
    monkeypatch.setattr(sys, "argv",
                        ["gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
                         "--dry-run"])
    rc = receipt.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert f"SLINK_CHECKPOINT_ROWS={','.join(receipt.DEFAULT_ROWS)}" in out
    assert "SLINK_BW_HASHES=" in out   # bw rows are still in FR's default


def test_explicit_bw_row_for_emerald_is_refused_by_name_not_pointed_at_nothing(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(receipt, "run_bw_hashes", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: calls.append(("probe", a)))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "emerald", "--lane", "anywhere",
        "--rows", "script_running,bw_n1_action_draw"])
    rc = receipt.main()
    err = capsys.readouterr().err
    assert rc == 1
    assert "bw_n1_action_draw" in err
    assert "emerald" in err
    assert calls == []   # never reached gen3_bw_hashes.py OR the probe launch


def test_explicit_bw_row_for_emerald_is_refused_in_dry_run_too(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "emerald", "--lane", "anywhere", "--dry-run",
        "--rows", "bw_u1_oldman"])
    rc = receipt.main()
    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    assert rc == 1
    assert "bw_u1_oldman" in err
    assert "SLINK_STATE_DIR" not in out   # refused before printing a misleading dry-run plan


def test_firered_bw_rows_still_work_after_the_emerald_fix(monkeypatch, capsys):
    """The refusal is emerald-specific; FR/LG's own bw_* rows must still be selectable."""
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", "anywhere", "--dry-run",
        "--rows", "script_running,bw_n1_action_draw"])
    rc = receipt.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "SLINK_BW_HASHES=" in out
