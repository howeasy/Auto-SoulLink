"""tools/gen3_final_cut.py (card G4-FINALCUT-RUNNER): the G4 final-cut pass as one command.
Pure Python -- no emulator is launched: every row runner is monkeypatched, and the only real
subprocesses are `git` against throwaway repos under tmp_path.
"""
import json
import os
import re
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
    assert f"rows={len(EXPECTED_ROWS)}" in out and f"# {len(EXPECTED_ROWS)} rows: RUN" in out
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
    """A well-formed runner receipt: one attempt block that supports the verdict."""
    ok = verdict.startswith(("PASS", "SKIP-ALLOWED"))
    attempt = {"load": "cpu=1%", "start_utc": "2026-09-24T12:00:00Z",
               "end_utc": "2026-09-24T12:01:00Z", "rc": 0 if ok else 1, "tracked_before": True,
               "tracked_after": True, "classification": "pass" if ok else "real", "output": "out"}
    text = receipts.run_receipt_text(row=row, item="§x", cut=cut, lane=LANE, command="c",
                                     cwd=".", env={}, attempts=[attempt], verdict=verdict)
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


# ---------------------------------------------------------------------------
# --carry (G4-FINALCUT-FAST, hardened by G4-FINALCUT-HARDEN)
# ---------------------------------------------------------------------------

X, CUT = "a" * 40, "b" * 40
ROMS = {"rom:firered": "1" * 64, "rom:leafgreen": "3" * 64}
DUO_ROWS = [r for r in EXPECTED_ROWS if r.endswith(("_fr_as_a", "_lg_as_a"))]


def _row(row_id):
    return {r.id: r for r in fc.build_plan(CUT, LANE, MASTER)}[row_id]


def _ev(row_id, cut=X, passed=True, inputs=None, **kw):
    return fc.Evidence(row_id, f"ph_{row_id}.txt", cut, passed,
                       inputs=dict(ROMS) if inputs is None else inputs, **kw)


def _decide(row, ev, changed=(), ancestor=True, inputs=None, master=None):
    return fc.carry_decision(row, CUT, ev, lambda x, c: list(changed), master,
                             lambda x, c: ancestor, dict(ROMS) if inputs is None else inputs)


def test_carry_when_nothing_blocks_it():
    row = _row("active_end_gen3_fr_as_a")
    d = _decide(row, [_ev(row.id)], ["docs/gen3/PLAN.md", "lua/gen1/client.lua"])
    assert d.kind == "CARRY" and d.reason == f"CARRIED from ph_{row.id}.txt @{X}"


# the coordinator's list (OMP review of d9a08f5b) plus the obvious client/carrier/server paths
FORCING = ["data/games/gen3_frlge/area_map.json", "data/games/gen3_frlge/gen3_frlge_locations.lua",
           "data/gen3/pret/pokefirered.sym", "lua/tests/playlib.lua",
           "lua/tests/mkstates_gen3_tutorials.lua", "lua/tests/duo/scenario_gen3_whiteout.lua",
           "lua/tests/duo/duo_gen3_main.lua", "tools/e2e_duo.py", "lua/gen3/client.lua",
           "lua/core/deferred.lua", "lua/slink.lua", "data/games/gen3_frlg/write_checkpoint.json",
           "server/state.py", "tests/fixtures/gen3/leafgreen_party_battle_b.sav",
           "lua/tests/gen3_gatelib.lua"]


@pytest.mark.parametrize("row_id", DUO_ROWS)
def test_every_listed_dependency_forces_every_duo_row_to_run(row_id):
    row = _row(row_id)
    for path in FORCING:
        d = _decide(row, [_ev(row_id)], ["docs/a.md", path])
        assert d.kind == "RUN" and path in d.reason, (row_id, path)


def test_probe_gates_depends_on_the_games_table():
    d = _decide(_row("probe_gates"), [_ev("probe_gates", inputs={})],
                ["lua/games/gen3_frlge.lua"], inputs={})
    assert d.kind == "RUN" and "lua/games/gen3_frlge.lua" in d.reason


def test_no_receipt_or_no_pass_or_same_cut_runs():
    row = _row("active_end_gen3_fr_as_a")
    assert _decide(row, []).kind == "RUN"
    assert _decide(row, [_ev(row.id, passed=False)]).kind == "RUN"
    assert _decide(row, [_ev(row.id, cut=CUT)]).kind == "RUN"
    assert _decide(row, [_ev(row.id, cut=None)]).kind == "RUN"
    assert fc.carry_decision(row, CUT, [_ev(row.id)], lambda x, c: None, None,
                             lambda x, c: True, dict(ROMS)).kind == "RUN"


def test_a_receipt_from_a_cut_that_is_not_an_ancestor_runs():
    row = _row("active_end_gen3_fr_as_a")
    d = _decide(row, [_ev(row.id)], ancestor=False)
    assert d.kind == "RUN" and "not an ancestor" in d.reason


def test_the_default_ancestor_check_is_git(tmp_path):
    row = _row("active_end_gen3_fr_as_a")    # "a"*40 is no commit: the real git check refuses it
    d = fc.carry_decision(row, CUT, [_ev(row.id)], lambda x, c: [], None, None, dict(ROMS))
    assert d.kind == "RUN" and "not an ancestor" in d.reason


@pytest.mark.parametrize("recorded,current", [
    ({"rom:firered": "9" * 64, "rom:leafgreen": "3" * 64}, ROMS),     # a different ROM
    ({}, ROMS),                                                       # nothing recorded
    (ROMS, {"rom:firered": "MISSING", "rom:leafgreen": "3" * 64}),   # missing in this lane
])
def test_non_git_inputs_must_match_the_lane(recorded, current):
    row = _row("active_end_gen3_fr_as_a")
    assert _decide(row, [_ev(row.id, inputs=recorded)], inputs=current).kind == "RUN"


def test_builds_checkpoint_zip_and_the_source_gate_are_never_carried():
    for rid in ("states_firered_town", "tutorials_leafgreen", "checkpoint_firered",
                "zip_boot_firered", "release_gate_quick"):
        assert _decide(_row(rid), [_ev(rid)]).kind == "RUN"


def test_item6_carries_only_while_master_has_not_moved():
    row = _row("item6_route_diff")
    ev = [_ev(row.id, master="c" * 8, inputs={})]
    assert _decide(row, ev, inputs={}, master="c" * 40).kind == "CARRY"
    assert _decide(row, ev, inputs={}, master="d" * 40).kind == "RUN"


def test_glob_star_stays_in_its_directory():
    assert fc.touched(["lua/slink.lua", "lua/gen1/client.lua", "lua/gen3/a/b.lua"],
                      ["lua/*.lua", "lua/gen3/**"]) == ["lua/slink.lua", "lua/gen3/a/b.lua"]


def test_row_inputs_name_the_staged_roms_and_the_rebuilt_states(tmp_path):
    sd = tmp_path / "patch" / "build" / "gen3_probe_states" / "firered"
    sd.mkdir(parents=True)
    (sd / "slink_oldman.State").write_bytes(b"s")
    got = fc.row_inputs(_row("checkpoint_firered"), str(tmp_path), root=str(tmp_path))
    assert set(got) == {"rom:firered", "state:gen3_probe_states/slink_oldman.State"}
    assert set(fc.row_inputs(_row("whiteout_gen3_lg_as_a"), str(tmp_path))) == set(ROMS)
    h = fc.hash_inputs(got)
    assert h["rom:firered"] == "MISSING" and len(h["state:gen3_probe_states/slink_oldman.State"]) == 64
    assert fc.parse_inputs("# " + fc.inputs_note(h)) == h


# --- receipt -> row mapping ------------------------------------------------------------------

def _ph(scen, o, x=X, tail=""):
    title, other = ("firered", "leafgreen") if o == "fr" else ("leafgreen", "firered")
    game = "gen3_frlg" if o == "fr" else "gen3_lgfr"
    return (f"G4-LANE-2 P+H live row: {scen}\nnote: PASS, attempt 1 of 1\n"
            f"=== {scen} --game {game}  lane=L sha={x} tracked_dirty_before=0\n"
            f"start_utc=2026-09-24T12:00:00Z\n"
            f"[duo] IDENTITY a={title}:rom={ROMS['rom:' + title]}:fixture={'2' * 64} "
            f"b={other}:rom={ROMS['rom:' + other]}:fixture={'4' * 64} source={x}\n"
            f"  {scen}: PASS (attempt 1 of 1)\nexit=0\nend_utc=2026-09-24T12:02:00Z\n{tail}")


@pytest.mark.parametrize("name,row,cut8", [
    ("ph_active_end_gen3_fr_as_a_b0483efe.txt", "active_end_gen3_fr_as_a", "b0483efe"),
    ("ph_linked_faint_active_whiteout_gen3_lg_as_a_28e48c9c.txt",
     "linked_faint_active_whiteout_gen3_lg_as_a", "28e48c9c"),
])
def test_ph_receipts_map_to_their_rows(name, row, cut8):
    with open(os.path.join(fc.PROBES, name), encoding="utf-8") as f:
        ev = fc.receipt_evidence(name, f.read())
    assert ev.row == row and ev.passed and ev.cut.startswith(cut8) and len(ev.cut) == 40
    assert set(ev.inputs) == set(ROMS)          # the ROM sha256s from e2e_duo's IDENTITY line


def test_the_mixed_trainer_receipt_is_not_citable():
    """It PASSed, then an aborted overlapping launch appended a FAIL/exit=1: no single final
    verdict, so it cannot be carried (its duration still counts for the estimate)."""
    name = "ph_linked_faint_active_trainer_gen3_fr_as_a_b0483efe.txt"
    with open(os.path.join(fc.PROBES, name), encoding="utf-8") as f:
        ev = fc.receipt_evidence(name, f.read())
    assert ev.row == "linked_faint_active_trainer_gen3_fr_as_a" and not ev.passed
    assert ev.seconds == 42 * 60


@pytest.mark.parametrize("text,ok", [
    (_ph("active_end_gen3", "fr"), True),
    (_ph("active_end_gen3", "fr", tail="  active_end_gen3: FAIL (attempt 1 of 1)\nexit=1\n"), False),
    (_ph("active_end_gen3", "fr", tail="exit=1\n"), False),
    (_ph("active_end_gen3", "fr", tail="note: PASS again\n"), False),
    (_ph("active_end_gen3", "lg"), False),       # an LG-as-A run in an fr_as_a file
])
def test_ph_needs_one_unambiguous_final_verdict_for_its_orientation(text, ok):
    ev = fc.receipt_evidence("ph_active_end_gen3_fr_as_a_aaaaaaaa.txt", text)
    assert ev.passed is ok


def test_every_ph_receipt_maps_to_a_plan_row():
    ids = {r.id for r in fc.build_plan(CUT, LANE, MASTER)}
    names = [n for n in os.listdir(fc.PROBES)
             if re.fullmatch(r"ph_.+_(fr|lg)_as_a_[0-9a-f]{8}\.txt", n)]   # RR rows are G5
    assert names
    for name in names:
        with open(os.path.join(fc.PROBES, name), encoding="utf-8") as f:
            ev = fc.receipt_evidence(name, f.read())
        assert ev and ev.row in ids and ev.cut, name


def test_a_legacy_receipt_without_a_cut_sha_is_not_citable():
    text = "========== summary ==========\n  link_gen3: PASS (attempt 2 of 3)\n"
    ev = fc.receipt_evidence("duo_frlg_link_gen3_clean_2026-09-23b.txt", text)
    assert ev.row == "link_gen3_fr_as_a" and ev.cut is None


# --- CARRIED fc receipts must authenticate through their origin --------------------------------

def _carried(probes, row_id, origin, x=X, cut=CUT):
    d = fc.Decision("CARRY", f"CARRIED from {origin} @{x}", fc.Evidence(row_id, origin, x, True),
                    ["docs/a.md"], dict(ROMS))
    name = f"fc_{row_id}_{cut[:8]}.txt"
    (probes / name).write_text(fc.carried_receipt(_row(row_id), cut, LANE, d), encoding="utf-8")
    return name


def _ev_of(probes, name):
    return fc.receipt_evidence(name, (probes / name).read_text(encoding="utf-8"), str(probes))


def test_a_carried_receipt_cites_its_validated_origin(tmp_path):
    rid = "active_end_gen3_fr_as_a"
    (tmp_path / "ph_active_end_gen3_fr_as_a_aaaaaaaa.txt").write_text(_ph("active_end_gen3", "fr"))
    name = _carried(tmp_path, rid, "ph_active_end_gen3_fr_as_a_aaaaaaaa.txt")
    text = (tmp_path / name).read_text(encoding="utf-8")
    assert "none a dependency): docs/a.md" in text and "# inputs: rom:firered=" in text
    ev = _ev_of(tmp_path, name)
    assert (ev.receipt, ev.cut, ev.passed, ev.inputs) == (
        "ph_active_end_gen3_fr_as_a_aaaaaaaa.txt", X, True, ROMS)


def test_a_carried_receipt_with_a_bad_origin_is_not_citable(tmp_path):
    rid = "active_end_gen3_fr_as_a"
    # missing origin
    assert not _ev_of(tmp_path, _carried(tmp_path, rid, "ph_nope_fr_as_a_aaaaaaaa.txt")).passed
    # origin for another row
    (tmp_path / "ph_whiteout_gen3_fr_as_a_aaaaaaaa.txt").write_text(_ph("whiteout_gen3", "fr"))
    assert not _ev_of(tmp_path, _carried(tmp_path, rid, "ph_whiteout_gen3_fr_as_a_aaaaaaaa.txt")).passed
    # origin at a different cut than the one cited
    (tmp_path / "ph_active_end_gen3_fr_as_a_aaaaaaaa.txt").write_text(
        _ph("active_end_gen3", "fr", x="c" * 40))
    assert not _ev_of(tmp_path, _carried(tmp_path, rid, "ph_active_end_gen3_fr_as_a_aaaaaaaa.txt")).passed
    # origin that is a SKIP-ALLOWED runner receipt: never citable for carry
    _receipt(tmp_path, rid, X, "SKIP-ALLOWED owner ruling 20")
    assert not _ev_of(tmp_path, _carried(tmp_path, rid, f"fc_{rid}_{X[:8]}.txt")).passed


def test_a_header_only_or_wrong_row_fc_receipt_is_not_citable(tmp_path):
    rid = "active_end_gen3_fr_as_a"
    text = receipts.run_receipt_text(row=rid, item="x", cut=X, lane=LANE, command="c", cwd=".",
                                     env={}, attempts=[], verdict="PASS")
    (tmp_path / f"fc_{rid}_{X[:8]}.txt").write_text(text, encoding="utf-8")
    assert not _ev_of(tmp_path, f"fc_{rid}_{X[:8]}.txt").passed
    _receipt(tmp_path, "whiteout_gen3_fr_as_a", X, "PASS")
    os.replace(tmp_path / f"fc_whiteout_gen3_fr_as_a_{X[:8]}.txt", tmp_path / f"fc_{rid}_{X[:8]}.txt")
    assert not _ev_of(tmp_path, f"fc_{rid}_{X[:8]}.txt").passed
    _receipt(tmp_path, rid, X, "PASS")
    assert _ev_of(tmp_path, f"fc_{rid}_{X[:8]}.txt").passed


def test_a_carried_row_writes_its_receipt_and_is_counted_as_carried(pass_env, monkeypatch):
    cut, ran, probes = pass_env
    rid = "faint_cmd_gen3_fr_as_a"
    (probes / f"ph_{rid}_{X[:8]}.txt").write_text(_ph("faint_cmd_gen3", "fr"))
    monkeypatch.setattr(fc, "git_diff_names", lambda x, c: ["docs/gen3/PLAN.md"])
    monkeypatch.setattr(fc, "git_is_ancestor", lambda x, c: True)
    monkeypatch.setattr(fc, "hash_inputs", lambda paths: {k: ROMS.get(k, "0" * 64) for k in paths})
    assert fc.main(["--cut", cut, "--lane", LANE, "--master", MASTER, "--carry",
                    "--rows", "faint_cmd_*,states_firered_town"]) == 0
    assert ran == ["states_firered_town"]
    got = receipts.read_run_receipt(str(probes / f"fc_{rid}_{cut[:8]}.txt"))
    assert got["verdict"].startswith(f"CARRIED from ph_{rid}_{X[:8]}.txt @{X}")
    summary = (probes / f"fc_SUMMARY_{cut[:8]}.txt").read_text(encoding="utf-8")
    assert "# RUN 1 / CARRIED 1 / FAIL 0" in summary


# ---------------------------------------------------------------------------
# --shard i/n and --merge-summary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_sharding_covers_each_row_exactly_once(n):
    rows = fc.build_plan(CUT, LANE, MASTER)
    est = {r.id: r.budget for r in rows}
    shards = fc.shard_rows(rows, n, est)
    ids = [r.id for s in shards for r in s]
    assert sorted(ids) == sorted(r.id for r in rows) and len(ids) == len(set(ids))
    assert [[r.id for r in s] for s in fc.shard_rows(rows, n, est)] == \
        [[r.id for r in s] for s in shards]                     # deterministic
    order = [r.id for r in rows]
    for s in shards:                                            # plan order inside a shard
        assert [r.id for r in s] == sorted((r.id for r in s), key=order.index)


EDGES = [("states_firered_town", "checkpoint_firered"), ("states_firered_battle", "checkpoint_firered"),
         ("tutorials_firered", "checkpoint_firered"), ("states_leafgreen_town", "checkpoint_leafgreen"),
         ("states_leafgreen_battle", "checkpoint_leafgreen"),
         ("tutorials_leafgreen", "checkpoint_leafgreen"),
         ("zip_build", "zip_check"), ("zip_build", "zip_boot_firered")]


@pytest.mark.parametrize("n", [2, 3, 4, 8])
def test_a_prerequisite_and_its_dependent_share_a_shard_in_order(n):
    rows = fc.build_plan(CUT, LANE, MASTER)
    # adversarial estimates: make the builds and the probes look like the biggest units
    est = {r.id: (10**6 if r.id.startswith(("states_", "tutorials_", "zip_")) else r.budget)
           for r in rows}
    for shard in fc.shard_rows(rows, n, est):
        ids = [r.id for r in shard]
        for pre, dep in EDGES:
            if dep in ids or pre in ids:
                assert pre in ids and dep in ids and ids.index(pre) < ids.index(dep), (pre, dep)


def test_two_shards_run_disjoint_rows_and_their_union_is_the_plan(pass_env):
    cut, ran, probes = pass_env
    base = ["--cut", cut, "--lane", LANE, "--master", MASTER,
            "--rows", "states_*,tutorials_*,faint_cmd_*,link_gen3_*"]
    assert fc.main(base + ["--shard", "1/2"]) == 0
    first = list(ran)
    assert fc.main(base + ["--shard", "2/2"]) == 0
    second = ran[len(first):]
    assert first and second and not set(first) & set(second)
    assert sorted(first + second) == sorted(EXPECTED_ROWS[:8])
    for i in (1, 2):
        assert (probes / f"fc_SUMMARY_{cut[:8]}_shard{i}of2.txt").exists()


def test_merge_summary_validates_every_row_receipt(pass_env):
    cut, _ran, probes = pass_env
    rows = "--rows", "faint_cmd_gen3_fr_as_a,link_gen3_fr_as_a"
    base = ["--cut", cut, "--lane", LANE, "--master", MASTER, *rows, "--merge-summary"]
    _receipt(probes, "faint_cmd_gen3_fr_as_a", cut, "PASS")
    (probes / f"ph_link_gen3_fr_as_a_{X[:8]}.txt").write_text(_ph("link_gen3", "fr"))
    _carried(probes, "link_gen3_fr_as_a", f"ph_link_gen3_fr_as_a_{X[:8]}.txt", cut=cut)
    assert fc.main(base) == 0
    s = (probes / f"fc_SUMMARY_{cut[:8]}.txt").read_text(encoding="utf-8")
    assert "# RUN 1 / CARRIED 1 / FAIL 0" in s
    # the origin disappears: the carried receipt no longer authenticates
    (probes / f"ph_link_gen3_fr_as_a_{X[:8]}.txt").unlink()
    assert fc.main(base) == 1
    # a header-only PASS
    text = receipts.run_receipt_text(row="link_gen3_fr_as_a", item="x", cut=cut, lane=LANE,
                                     command="c", cwd=".", env={}, attempts=[], verdict="PASS")
    (probes / f"fc_link_gen3_fr_as_a_{cut[:8]}.txt").write_text(text, encoding="utf-8")
    assert fc.main(base) == 1
    # a well-formed PASS for ANOTHER row under this row's name
    _receipt(probes, "whiteout_gen3_fr_as_a", cut, "PASS")
    os.replace(probes / f"fc_whiteout_gen3_fr_as_a_{cut[:8]}.txt",
               probes / f"fc_link_gen3_fr_as_a_{cut[:8]}.txt")
    assert fc.main(base) == 1
    assert "FAIL invalid receipt" in (probes / f"fc_SUMMARY_{cut[:8]}.txt").read_text(encoding="utf-8")
    # and a missing receipt is NOT RUN
    assert fc.main(["--cut", cut, "--lane", LANE, "--master", MASTER,
                    "--rows", "states_*", "--merge-summary"]) == 1
