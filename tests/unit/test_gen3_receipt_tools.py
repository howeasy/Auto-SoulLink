"""tools/gen3_bw_hashes.py and tools/gen3_probe_receipt.py (card C4-RECEIPT-TOOLS): the missing
SLINK_BW_HASHES producer and the probe receipt wrapper, G4 final-cut runbook §12 items 2/3.
Pure Python -- no emulator, no real BizHawk launch (the run_gate/run_probe call is monkeypatched
away in every test that would otherwise launch one; gen3_bw_hashes.py's own subprocess IS let
run for real, since it is plain hashing/JSON with no emulator involved).
"""
import hashlib
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import gen3_bw_hashes  # noqa: E402
import gen3_probe_receipt as receipt  # noqa: E402

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "tools")


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

def _make_bw_lane(tmp_path, title="firered"):
    lane = tmp_path / "lane"
    (lane / "data" / "games" / "gen3_frlg").mkdir(parents=True)
    (lane / "data" / "games" / "gen3_frlg" / "write_checkpoint.json").write_bytes(b"{}")
    c4p2 = lane / "patch" / "build" / "gen3_probe_states_c4p2" / title
    c4p2.mkdir(parents=True)
    (c4p2 / "slink_preintro.State").write_bytes(b"preintro")
    (c4p2 / "slink_prebattle.State").write_bytes(b"prebattle")
    tut = lane / "patch" / "build" / "gen3_probe_states" / title
    tut.mkdir(parents=True)
    (tut / "slink_oldman.State").write_bytes(b"oldman")
    (tut / "slink_pokedude.State").write_bytes(b"pokedude")
    fx = lane / "tests" / "fixtures" / "gen3"
    fx.mkdir(parents=True)
    (fx / f"{title}_party_battle.sav").write_bytes(b"battle-fixture")
    (fx / f"{title}_party_town.sav").write_bytes(b"town-fixture")
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

def _make_probe_lane(tmp_path, dirty=False):
    lane = tmp_path / "lane2"
    (lane / "lua" / "tests").mkdir(parents=True)
    (lane / "lua" / "tests" / "probe_gen3_checkpoint.lua").write_bytes(
        b'G.open("probe_gen3_checkpoint")\n')
    (lane / "patch" / "build").mkdir(parents=True)
    rom_path = lane / receipt.staged_rom_rel("firered")
    rom_path.parent.mkdir(parents=True, exist_ok=True)
    rom_path.write_bytes(b"fake-rom-bytes")
    _init_git_lane(lane)
    _commit_all(lane)
    if dirty:
        (lane / "lua" / "tests" / "probe_gen3_checkpoint.lua").write_bytes(
            b'G.open("probe_gen3_checkpoint")\nextra\n')
    return lane


def _write_result(lane, text):
    (lane / "patch" / "build" / "probe_gen3_checkpoint_result.txt").write_text(
        text, encoding="utf-8")


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
    monkeypatch_argv = ["gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
                         "--dry-run", "--rows", "script_running,sound_driver"]
    sys.argv = monkeypatch_argv
    rc = receipt.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "SLINK_BW_HASHES" not in out
    assert "gen3_bw_hashes.py" not in out


def test_dirty_lane_reports_tracked_clean_false_falsifier(tmp_path):
    lane = _make_probe_lane(tmp_path, dirty=True)
    lines, _env, _rom = receipt.build_header("firered", "clean", str(lane),
                                              receipt.BASE_ROWS, 1200)
    assert "tracked_clean=False" in lines[0]


def test_clean_lane_reports_tracked_clean_true(tmp_path):
    lane = _make_probe_lane(tmp_path, dirty=False)
    lines, _env, _rom = receipt.build_header("firered", "clean", str(lane),
                                              receipt.BASE_ROWS, 1200)
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
    lines, _env, _rom = receipt.build_header("firered", "clean", str(lane),
                                              receipt.BASE_ROWS, 1200)
    header = "\n".join(lines)
    assert f"sha256(git blob, LF)={expected}" in header
    assert working_file_hash not in header


def test_full_run_pass_writes_receipt_and_exits_zero(tmp_path, monkeypatch):
    lane = _make_probe_lane(tmp_path)
    _write_result(lane, "phase probe-state frame=1\nRESULT: PASS all checkpoint controls\n")
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: None)
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
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: None)
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
    monkeypatch.setattr(receipt, "run_probe", lambda *a, **k: None)
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "script_running"])
    rc = receipt.main()
    assert rc == 1


def test_full_run_calls_bw_hashes_before_probe_when_bw_rows_selected(tmp_path, monkeypatch):
    lane = _make_probe_lane(tmp_path)
    _write_result(lane, "RESULT: PASS all checkpoint controls\n")
    order = []
    monkeypatch.setattr(receipt, "run_bw_hashes",
                         lambda title, lane_: order.append(("bw", title, lane_)))
    monkeypatch.setattr(receipt, "run_probe",
                         lambda *a, **k: order.append(("probe",)))
    monkeypatch.setattr(receipt, "REPO", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "gen3_probe_receipt.py", "--title", "firered", "--lane", str(lane),
        "--rows", "bw_n1_action_draw", "--out", "test_receipt3.txt"])
    rc = receipt.main()
    assert rc == 0
    assert order == [("bw", "firered", str(lane)), ("probe",)]
