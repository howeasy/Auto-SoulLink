"""tools/gen3_final_cut.py (card G4-FINALCUT-RUNNER): the G4 final-cut pass as one command.
Pure Python -- no emulator is launched: every row runner is monkeypatched, and the only real
subprocesses are `git` against throwaway repos under tmp_path.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import gen3_final_cut as fc  # noqa: E402
import gen3_probe_receipt as receipts  # noqa: E402

LANE, MASTER = "L:/lane", "L:/master"

# Runbook §1-§11 in order (G4_final_cut_runbook.md); §5 is mechanism P+H on both orientations.
EXPECTED_ROWS = [
    "states_firered_town", "states_firered_battle", "states_leafgreen_town",
    "states_leafgreen_battle", "tutorials_firered", "tutorials_leafgreen",
    "faint_cmd_gen3_fr_as_a", "link_gen3_fr_as_a", "boxsync_gen3_fr_as_a",
    "reconnect_gen3_fr_as_a", "deadzone_gen3_fr_as_a",
    "whiteout_gen3_fr_as_a", "whiteout_gen3_lg_as_a",
    "center_controls_gen3_fr_as_a", "center_controls_gen3_lg_as_a",
    "linked_faint_active_gen3_fr_as_a", "linked_faint_active_gen3_lg_as_a",
    "active_end_gen3_fr_as_a", "active_end_gen3_lg_as_a",
    "linked_faint_active_whiteout_gen3_fr_as_a", "linked_faint_active_whiteout_gen3_lg_as_a",
    "linked_faint_active_trainer_gen3_fr_as_a", "linked_faint_active_trainer_gen3_lg_as_a",
    "checkpoint_firered", "checkpoint_leafgreen",
    "save_then_write_gen3_fr_as_a", "save_then_write_gen3_lg_as_a",
    "bootcheck_firered_party_town", "bootcheck_firered_party_town_b",
    "bootcheck_firered_party_battle", "bootcheck_firered_party_battle_b",
    "bootcheck_leafgreen_party_town", "bootcheck_leafgreen_party_town_b",
    "bootcheck_leafgreen_party_battle", "bootcheck_leafgreen_party_battle_b",
    "zip_build", "zip_check", "zip_boot_firered",
    "item6_route_diff",
    "release_gate_quick", "probe_gates",
]


def _git(tree, *args):
    return subprocess.run(["git", "-C", str(tree), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def _repo(path):
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "a.txt").write_text("one\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "one")
    return _git(path, "rev-parse", "HEAD")


# ---------------------------------------------------------------------------
# --dry-run plan snapshot
# ---------------------------------------------------------------------------

def test_dry_run_prints_every_runbook_row_in_order(capsys):
    cut = _git(fc.REPO, "rev-parse", "HEAD")
    assert fc.main(["--cut", cut, "--dry-run", "--lane", LANE, "--master", MASTER]) == 0
    out = capsys.readouterr().out
    ids = [ln.split()[1] for ln in out.splitlines() if ln.startswith("[")]
    assert ids == EXPECTED_ROWS
    assert f"rows={len(EXPECTED_ROWS)}" in out and f"# {len(EXPECTED_ROWS)} rows;" in out
    # the runbook commands, verbatim
    assert "$ python tools/e2e_duo.py --game gen3_lgfr --scenario active_end_gen3" in out
    assert "$ python tools/e2e_duo.py --game gen3_frlg --scenario linked_faint_active_trainer_gen3" in out
    assert "--fixture tests/fixtures/gen3/leafgreen_party_battle_b.sav --title leafgreen" in out
    assert f"check_release_zip.py L:/lane/dist/SLink-player-g4-{cut[:8]}.zip --rev {cut}" in out
    assert "$ SLINK_LIVE=1 python -m pytest tests/live/test_gen3_probe_gates.py" in out
    assert f"--out checkpoint_lg_clean_{cut[:8]}.txt" in out
    # the superseded hold rows are gone (P+H, G4_request_draft.md 4aaaee7e)
    assert "trainer_bench_gen3" not in out


def test_dry_run_launches_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry-run must not provision or run")
    monkeypatch.setattr(fc, "provision", boom)
    monkeypatch.setattr(fc, "run_row", boom)
    monkeypatch.setattr(fc, "run_once", boom)
    assert fc.main(["--cut", "HEAD", "--dry-run", "--lane", LANE, "--master", MASTER]) == 0


def test_rows_selects_by_glob_or_item_keeping_order():
    rows = fc.build_plan("c" * 40, LANE, MASTER)
    got = [r.id for r in fc.select_rows(rows, "zip_*,item2b")]
    assert got == EXPECTED_ROWS[15:23] + ["zip_build", "zip_check", "zip_boot_firered"]
    with pytest.raises(SystemExit):
        fc.select_rows(rows, "no_such_row")


# ---------------------------------------------------------------------------
# the retry classifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("output,killed,want", [
    ("PYDEC: FAIL timed out after 900s waiting for both players connected\n"
     "  faint_cmd_gen3: FAIL (attempt 1 of 1) — TimeoutError: timed out after 900s", False,
     "contention"),
    ("[gate] TIMEOUT after 600s — killed\n[gate] mkstates_gen3: (no RESULT line)", False,
     "contention"),
    ("half-way output with no verdict", True, "contention"),
    ("[duo] RESULT_LINE a: RESULT: FAIL (the second save: SAVE failed)\n"
     "timed out after 900s waiting for b", False, "real"),
    ("[duo] x: a client finished before 'READY' (a: no RESULT; b: RESULT: PASS)", False, "real"),
    ("E   AssertionError: queued", False, "real"),
    ("Traceback (most recent call last):\nPermissionError: [WinError 32]", False, "real"),
    ("  faint_cmd_gen3: FAIL (attempt 1 of 1)", False, "real"),
])
def test_classify_failure(output, killed, want):
    assert fc.classify_failure(output, killed) == want


def _stub_row_env(monkeypatch, tmp_path, outputs):
    calls = []

    def fake_run_once(row, deadline):
        calls.append(row.id)
        return outputs[len(calls) - 1]
    monkeypatch.setattr(fc, "run_once", fake_run_once)
    monkeypatch.setattr(fc, "tracked_clean", lambda tree: True)
    monkeypatch.setattr(fc, "load_snapshot", lambda: "cpu=99%")
    monkeypatch.setattr(fc, "rewind_violations", lambda tree, since: [])
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    return calls


def test_contention_timeout_gets_exactly_one_retry(monkeypatch, tmp_path):
    timeout = (1, "timed out after 900s waiting for both players connected", False, False)
    calls = _stub_row_env(monkeypatch, tmp_path, [timeout, timeout, timeout])
    row = fc.build_plan("c" * 40, LANE, MASTER)[6]
    verdict, n, _clean = fc.run_row(row, "c" * 40, LANE, None)
    assert n == 2 and len(calls) == 2 and verdict.startswith("FAIL")
    with open(fc.receipt_path(row.id, "c" * 40), encoding="utf-8") as f:
        text = f.read()
    assert "--- attempt 2 of 2 ---" in text and "classification=contention" in text


def test_contention_then_pass(monkeypatch, tmp_path):
    outs = [(1, "timed out after 900s waiting for x", False, False), (0, "ok", False, False)]
    _stub_row_env(monkeypatch, tmp_path, outs)
    row = fc.build_plan("c" * 40, LANE, MASTER)[6]
    assert fc.run_row(row, "c" * 40, LANE, None)[:2] == ("PASS", 2)


def test_real_failure_is_never_retried(monkeypatch, tmp_path):
    calls = _stub_row_env(monkeypatch, tmp_path, [(1, "[duo] RESULT_LINE a: RESULT: FAIL (x)",
                                                   False, False)])
    row = fc.build_plan("c" * 40, LANE, MASTER)[6]
    verdict, n, _ = fc.run_row(row, "c" * 40, LANE, None)
    assert n == 1 and calls == [row.id] and verdict == "FAIL exit=1"


def test_a_row_that_dirties_the_lane_fails(monkeypatch, tmp_path):
    _stub_row_env(monkeypatch, tmp_path, [(0, "ok", False, False)])
    states = iter([True, False])
    monkeypatch.setattr(fc, "tracked_clean", lambda tree: next(states))
    row = fc.build_plan("c" * 40, LANE, MASTER)[0]
    verdict, _n, clean_after = fc.run_row(row, "c" * 40, LANE, None)
    assert verdict.startswith("FAIL") and not clean_after


def test_rewind_on_fails_a_passing_row(monkeypatch, tmp_path):
    _stub_row_env(monkeypatch, tmp_path, [(0, "ok", False, False)])
    monkeypatch.setattr(fc, "rewind_violations", lambda tree, since: ["x.ini"])
    row = fc.build_plan("c" * 40, LANE, MASTER)[0]
    assert fc.run_row(row, "c" * 40, LANE, None)[0].startswith("FAIL rewind on")


def test_rewind_violations_reads_back_the_configs(tmp_path):
    build = tmp_path / "patch" / "build" / "runs"
    build.mkdir(parents=True)
    (build / "on.ini").write_text(json.dumps({"Rewind": {"Enabled": True}}))
    (build / "off.ini").write_text(json.dumps({"Rewind": {"Enabled": False}}))
    (build / "missing.ini").write_text(json.dumps({"Other": 1}))
    (build / "notjson.ini").write_text("[section]\n")
    got = sorted(os.path.basename(p) for p in fc.rewind_violations(str(tmp_path), 0))
    assert got == ["missing.ini", "on.ini"]


# ---------------------------------------------------------------------------
# the SKIP policy
# ---------------------------------------------------------------------------

def test_a_duo_skip_is_a_failure():
    out = "[duo] faint_cmd_gen3: SKIP (gen3_frlg) — x\n  faint_cmd_gen3: SKIP — x"
    verdict, ok = fc.judge("faint_cmd_gen3_fr_as_a", 3, out)
    assert not ok and "ALLOWED_SKIPS" in verdict


def test_a_pytest_skip_is_a_failure_even_on_exit_0():
    assert fc.judge("probe_gates", 0, "3 passed, 1 skipped in 9s")[1] is False


def test_the_r5_mega_skip_is_allowed_by_ruling_20():
    out = ("  linked_faint_active_mega_gen3: SKIP — BLOCKED: R5 needs an RR trainer route and a "
           "mega-capable party")
    verdict, ok = fc.judge("linked_faint_active_mega_gen3_rr_as_a", 3, out)
    assert ok and verdict.startswith("SKIP-ALLOWED") and "ruling 20" in verdict
    # the same reason on another row is not excused
    assert fc.judge("faint_cmd_gen3_fr_as_a", 3, out)[1] is False


def test_a_gate_that_owns_its_skip_policy_is_judged_by_exit_code():
    rows = {r.id: r for r in fc.build_plan("c" * 40, LANE, MASTER)}
    assert rows["release_gate_quick"].own_verdict and rows["item6_route_diff"].own_verdict
    assert not rows["probe_gates"].own_verdict
    assert fc.judge("release_gate_quick", 0, "unit: 900 passed, 2 skipped", own_verdict=True)[1]


def test_pass_and_plain_failure():
    assert fc.judge("x", 0, "  x: PASS (attempt 1 of 1)") == ("PASS", True)
    assert fc.judge("x", 1, "boom") == ("FAIL exit=1", False)
    assert fc.judge("x", 0, "fine", budget_killed=True)[1] is False


# ---------------------------------------------------------------------------
# --resume receipt matching, and the never-re-run-a-failed-row rule across invocations
# ---------------------------------------------------------------------------

def _receipt(tmp_path, row, cut, verdict):
    text = receipts.run_receipt_text(row=row, item="§x", cut=cut, lane=LANE, command="c",
                                     cwd=".", env={}, attempts=[], verdict=verdict)
    (tmp_path / f"fc_{row}_{cut[:8]}.txt").write_text(text, encoding="utf-8")


@pytest.fixture
def pass_env(monkeypatch, tmp_path):
    cut = _git(fc.REPO, "rev-parse", "HEAD")
    ran = []
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    monkeypatch.setattr(fc, "provision", lambda tree, rev, root: rev)
    monkeypatch.setattr(fc, "copy_inputs", lambda tree, root: None)
    monkeypatch.setattr(fc, "run_row",
                        lambda row, cut, lane, deadline: (ran.append(row.id), ("PASS", 1, True))[1])
    return cut, ran, tmp_path


def _run(cut, *extra):
    return fc.main(["--cut", cut, "--lane", LANE, "--master", MASTER,
                    "--rows", "states_firered_*", *extra])


def test_resume_skips_a_pass_at_the_same_cut_only(pass_env):
    cut, ran, probes = pass_env
    _receipt(probes, "states_firered_town", cut, "PASS")
    # same sha8 in the name but a different full cut in the header: not a match
    _receipt(probes, "states_firered_battle", cut[:8] + "0" * 32, "PASS")
    assert _run(cut, "--resume") == 0
    assert ran == ["states_firered_battle"]
    summary = (probes / f"fc_SUMMARY_{cut[:8]}.txt").read_text(encoding="utf-8")
    assert "PASS (resumed)" in summary and "OVERALL: PASS (2/2 rows)" in summary


def test_without_resume_a_pass_receipt_is_re_taken(pass_env):
    cut, ran, probes = pass_env
    _receipt(probes, "states_firered_town", cut, "PASS")
    assert _run(cut) == 0
    assert ran == ["states_firered_town", "states_firered_battle"]


def test_a_fail_receipt_at_the_same_cut_blocks_the_row(pass_env):
    cut, ran, probes = pass_env
    _receipt(probes, "states_firered_town", cut, "FAIL exit=1")
    assert _run(cut) == 1
    assert _run(cut, "--resume") == 1
    assert ran == ["states_firered_battle", "states_firered_battle"]
    assert "not re-run" in (probes / f"fc_SUMMARY_{cut[:8]}.txt").read_text(encoding="utf-8")


def test_stop_at_in_the_past_runs_nothing(pass_env):
    cut, ran, _probes = pass_env
    assert _run(cut, "--stop-at", "2000-01-01T00:00Z") == 1
    assert ran == []


# ---------------------------------------------------------------------------
# lane provisioning: clean-check failure aborts
# ---------------------------------------------------------------------------

def test_provision_refuses_a_tracked_dirty_lane(tmp_path):
    sha = _repo(tmp_path / "lane")
    (tmp_path / "lane" / "a.txt").write_text("someone else's edit\n")
    with pytest.raises(fc.LaneError, match="tracked-dirty"):
        fc.provision(str(tmp_path / "lane"), sha, str(tmp_path / "lane"))
    assert (tmp_path / "lane" / "a.txt").read_text() == "someone else's edit\n"   # untouched


def test_provision_moves_a_clean_lane_to_the_cut_detached(tmp_path):
    lane = tmp_path / "lane"
    first = _repo(lane)
    (lane / "a.txt").write_text("two\n")
    _git(lane, "commit", "-qam", "two")
    assert fc.provision(str(lane), first, str(lane)) == first
    assert _git(lane, "rev-parse", "HEAD") == first
    assert (lane / "a.txt").read_text() == "one\n"
    assert _git(lane, "status", "--porcelain", "--untracked-files=no") == ""


def test_provision_repairs_a_lane_whose_checkout_died_after_updating(tmp_path):
    """W3's broken-ref case: the tree/index are at the cut but HEAD is not -> update-ref."""
    lane = tmp_path / "lane"
    first = _repo(lane)
    (lane / "a.txt").write_text("two\n")
    _git(lane, "commit", "-qam", "two")
    real_git = fc._git

    def dying_checkout(tree, *args, check=True):
        if args[:1] == ("checkout",):
            real_git(tree, "read-tree", "-u", "--reset", first)   # tree updated, HEAD not moved
            return subprocess.CompletedProcess(args, 128, "", "fatal: bad object")
        return real_git(tree, *args, check=check)
    fc_git = fc._git
    try:
        fc._git = dying_checkout
        assert fc.provision(str(lane), first, str(lane)) == first
    finally:
        fc._git = fc_git
    assert _git(lane, "rev-parse", "HEAD") == first


def test_a_dirty_lane_aborts_the_pass_before_any_row(monkeypatch, tmp_path):
    lane = tmp_path / "lane"
    sha = _repo(lane)
    (lane / "a.txt").write_text("dirty\n")
    monkeypatch.setattr(fc, "REPO", str(lane))
    monkeypatch.setattr(fc, "main_checkout", lambda: str(lane))
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))

    def must_not_run(*a, **k):
        raise AssertionError("no row may run on a dirty lane")
    monkeypatch.setattr(fc, "run_row", must_not_run)
    assert fc.main(["--cut", sha, "--lane", str(lane), "--master", str(tmp_path / "m"),
                    "--rows", "states_*"]) == 2


def test_copy_inputs_fails_closed_on_a_missing_source(tmp_path):
    (tmp_path / "root").mkdir()
    with pytest.raises(fc.LaneError, match="gitignored input missing"):
        fc.copy_inputs(str(tmp_path / "lane"), str(tmp_path / "root"))


# ---------------------------------------------------------------------------
# item 6
# ---------------------------------------------------------------------------

def test_item6_flags_only_a_regression_vs_master():
    table = {"gen1_ordering": {"master": False, "branch": False},     # identical FAIL: no delta
             "gen1_sfx_town": {"master": False, "branch": True},      # branch better
             "gen2_legacy_faint": {"master": True, "branch": False}}  # regression
    assert fc.item6_verdict(table) == ["gen2_legacy_faint"]


def test_item6_runs_the_three_cases_of_the_2026_09_24_receipts():
    names = [c[0] for c in fc.item6_cases()]
    assert names == ["gen1_ordering", "gen1_sfx_town", "gen2_legacy_faint",
                     "gen2_legacy_boxsync", "gen2_legacy_memorialize"]
