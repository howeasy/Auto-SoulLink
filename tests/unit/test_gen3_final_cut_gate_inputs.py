"""Lane provisioning for release_gate_quick's unit lane: the inputs whose absence was a COUNTED SKIP (and a skip fails the gate).

fc_frlgc_release_gate_quick_b6cd75c6: 16 skipped (9 unexplained) -- patch/build/gen3_pokeemerald.gba, the .cache/expansion-src checkout and
patch/vendor/pokefirered existed in the main checkout but not in the lane. Pure Python: throwaway git repos and directories under tmp_path."""
import hashlib
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import gen3_final_cut as fc  # noqa: E402

CUT, LANE, MASTER = "c" * 40, "L:/lane", "L:/master"


# ---- no other row's inputs hash moves ----

# sha256 of {plan: {row id: row_inputs(row)}} (separators normalised, SLINK_GEN3_RAND_ROMS=R:/rand) over the frlg, rr, emerald, exp, frlgc and
# frlgc-rand plans -- 214 rows -- taken BEFORE the gate provisioning existed. It is NOT derived from the code under test.
INPUTS_DIGEST = "cfd581034cf79d219e59b4d68d4e9753ba908d15de76995e593c86f674c9d759"


def _all_row_inputs(monkeypatch):
    monkeypatch.setenv("SLINK_GEN3_RAND_ROMS", "R:/rand")
    out = {}
    for name, plan in (("frlg", fc.build_plan), ("rr", fc.build_plan_rr), ("emerald", fc.build_plan_emerald),
                       ("exp", fc.build_plan_exp), ("frlgc", fc.build_plan_frlgc), ("frlgc-rand", fc.build_plan_frlgc_rand)):
        out[name] = {r.id: {k: v.replace(chr(92), "/") for k, v in fc.row_inputs(r, LANE).items()}
                     for r in plan(CUT, LANE, MASTER)}
    return out


def test_no_existing_rows_inputs_hash_changed(monkeypatch):
    snap = _all_row_inputs(monkeypatch)
    assert sum(len(v) for v in snap.values()) == 214
    assert hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest() == INPUTS_DIGEST
    # in particular the gate rows keep what they had (the three companions for frlgc, nothing for the clean one)
    assert set(snap["frlgc"]["frlgc_release_gate_quick"]) == {f"rom:{t}_companion" for t in fc.GEN3_COMPANION_TITLES}
    assert snap["frlg"]["release_gate_quick"] == {}


# ---- the gate row is recognised, in every plan that has one ----

def test_the_gate_rows_are_recognised_by_their_command_in_every_plan():
    gates = {r.id for plan in (fc.build_plan, fc.build_plan_rr, fc.build_plan_emerald, fc.build_plan_exp,
                               fc.build_plan_frlgc, fc.build_plan_frlgc_rand)
             for r in plan(CUT, LANE, MASTER) if fc.is_gate_row(r)}
    assert gates == {"release_gate_quick", "frlgc_release_gate_quick"}


# ---- the locked expansion source junction ----

def _git(tree, *args):
    return subprocess.run(["git", "-C", str(tree), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def exp_world(tmp_path, monkeypatch):
    """A tiny 'pinned expansion checkout' (a real git repo), a lock naming it, and an empty lane tree."""
    source = tmp_path / "src"
    (source / "include" / "config").mkdir(parents=True)
    (source / "include" / "config" / "x.h").write_bytes(b"#define X 1")
    _git(source, "init", "-q")
    _git(source, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(source, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "pin")
    commit = _git(source, "rev-parse", "HEAD")
    lane = tmp_path / "lane"
    (lane / "data").mkdir(parents=True)
    lock = {"source": {"commit": commit},
            "config_headers": {"include/config/x.h": hashlib.sha256(b"#define X 1").hexdigest()}}
    (lane / "data" / "gen3_exp_sources.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setenv("SLINK_EXPANSION_SRC", str(source))
    return source, lane, lock


def test_the_expansion_source_is_junctioned_after_the_lock_checks(exp_world, tmp_path):
    source, lane, _lock = exp_world
    fc.link_expansion_source(str(lane), str(tmp_path / "root"))
    link = lane / ".cache" / "expansion-src"
    assert os.path.realpath(link) == os.path.realpath(source)
    assert (link / "include" / "config" / "x.h").read_bytes() == b"#define X 1"   # the same files, not a copy
    fc.link_expansion_source(str(lane), str(tmp_path / "root"))                                   # idempotent
    assert os.path.realpath(link) == os.path.realpath(source)


@pytest.mark.parametrize("break_it, why", [
    (lambda src, lane, lock: (src / "include" / "config" / "x.h").write_bytes(b"#define X 2"), "tracked-clean"),
    (lambda src, lane, lock: (lane / "data" / "gen3_exp_sources.lock.json").write_text(
        json.dumps({**lock, "source": {"commit": "0" * 40}}), encoding="utf-8"), "locked commit"),
    (lambda src, lane, lock: (lane / "data" / "gen3_exp_sources.lock.json").write_text(
        json.dumps({**lock, "config_headers": {"include/config/x.h": "0" * 64}}), encoding="utf-8"), "differs from lock"),
])
def test_a_wrong_or_dirty_expansion_source_fails_closed(exp_world, tmp_path, break_it, why):
    source, lane, lock = exp_world
    break_it(source, lane, lock)
    with pytest.raises(fc.LaneError, match=why):
        fc.link_expansion_source(str(lane), str(tmp_path / "root"))
    assert not (lane / ".cache" / "expansion-src").exists()          # nothing half-provisioned


def test_a_missing_expansion_source_fails_closed(exp_world, tmp_path, monkeypatch):
    _source, lane, _lock = exp_world
    monkeypatch.delenv("SLINK_EXPANSION_SRC")
    with pytest.raises(fc.LaneError, match="expansion source missing"):
        fc.link_expansion_source(str(lane), str(tmp_path / "root"), repo=str(tmp_path / "no-repo"))


def test_a_lane_link_to_another_source_is_refused(exp_world, tmp_path):
    source, lane, _lock = exp_world
    other = tmp_path / "other"
    other.mkdir()
    fc._link_dir(str(other), str(lane / ".cache" / "expansion-src"))
    with pytest.raises(fc.LaneError, match="differs from SLINK_EXPANSION_SRC"):
        fc.link_expansion_source(str(lane), str(tmp_path / "root"))


# ---- the vendored decomp ----

def test_the_vendored_decomp_is_junctioned_from_the_first_source_that_holds_it(tmp_path):
    root, lane, repo = tmp_path / "root", tmp_path / "lane", tmp_path / "repo"
    (root / "patch" / "vendor" / "pokefirered").mkdir(parents=True)
    (root / "patch" / "vendor" / "pokefirered" / "charmap.txt").write_text("' ' = 00\n", encoding="utf-8")
    lane.mkdir()
    repo.mkdir()
    dest = fc.link_vendored_decomp(str(lane), str(root), str(repo))
    assert os.path.realpath(dest) == os.path.realpath(root / "patch" / "vendor" / "pokefirered")
    assert (lane / "patch" / "vendor" / "pokefirered" / "charmap.txt").read_text(encoding="utf-8") == "' ' = 00\n"
    assert fc.link_vendored_decomp(str(lane), str(root), str(repo)) == dest                  # idempotent


def test_a_missing_or_empty_vendored_decomp_fails_closed(tmp_path):
    root, lane, repo = tmp_path / "root", tmp_path / "lane", tmp_path / "repo"
    for d in (root, lane, repo):
        d.mkdir()
    with pytest.raises(fc.LaneError, match="patch/vendor/pokefirered is missing"):
        fc.link_vendored_decomp(str(lane), str(root), str(repo))
    (lane / "patch" / "vendor" / "pokefirered").mkdir(parents=True)                           # a lane dir holding no charmap
    with pytest.raises(fc.LaneError, match="holds no charmap.txt"):
        fc.link_vendored_decomp(str(lane), str(root), str(repo))


# ---- the pinned expansion ROM and its bundle, then everything together ----

def test_provision_gate_inputs_supplies_all_three_and_fails_closed_on_a_wrong_rom(exp_world, tmp_path, monkeypatch):
    _source, lane, _lock = exp_world
    root = tmp_path / "root"
    rom = b"the pinned expansion reference rom"
    pin = hashlib.sha1(rom).hexdigest()
    monkeypatch.setattr(fc, "expansion_rom_pin", lambda tree: pin)
    (root / "patch" / "build").mkdir(parents=True)
    (root / "patch" / "build" / "gen3_pokeemerald.gba").write_bytes(b"a stale rom")
    (root / ".cache" / "expansion-output" / "reference").mkdir(parents=True)
    (root / ".cache" / "expansion-output" / "reference" / "pokeemerald.sym").write_text("sym", encoding="utf-8")
    (root / "patch" / "vendor" / "pokefirered").mkdir(parents=True)
    (root / "patch" / "vendor" / "pokefirered" / "charmap.txt").write_text("c", encoding="utf-8")
    (root / ".cache" / "pret" / "pokeemerald").mkdir(parents=True)
    with pytest.raises(fc.LaneError, match="no source matches pin exp"):                       # the ROM is NOT the pin: BLOCKED
        fc.provision_gate_inputs(str(lane), str(root), repo=str(tmp_path / "no-repo"))
    assert not (lane / "patch" / "vendor").exists() and not (lane / ".cache" / "expansion-src").exists()
    (root / "patch" / "build" / "gen3_pokeemerald.gba").write_bytes(rom)
    (root / ".cache" / "expansion-output" / "reference" / "pokeemerald.gba").write_bytes(rom)
    fc.provision_gate_inputs(str(lane), str(root), repo=str(tmp_path / "no-repo"))
    assert (lane / "patch" / "build" / "gen3_pokeemerald.gba").read_bytes() == rom             # the pinned ROM, copied
    assert (lane / ".cache" / "expansion-output" / "reference" / "pokeemerald.sym").read_text(encoding="utf-8") == "sym"
    assert os.path.realpath(lane / ".cache" / "expansion-src")                                # junctions, not copies
    assert (lane / ".cache" / "expansion-src" / "include" / "config" / "x.h").is_file()
    assert (lane / "patch" / "vendor" / "pokefirered" / "charmap.txt").is_file()


# ---- the wiring: only a pass that RUNS the gate pays for it ----

def _run_pass(monkeypatch, tmp_path, title, calls):
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    monkeypatch.setattr(fc, "rom_pins", lambda *a, **k: {})
    monkeypatch.setattr(fc, "provision", lambda tree, rev, root: calls.append("provision"))
    monkeypatch.setattr(fc, "copy_inputs", lambda *a, **k: calls.append("copy_inputs"))
    monkeypatch.setattr(fc, "provision_gate_inputs", lambda *a, **k: calls.append("gate_inputs"))
    monkeypatch.setattr(fc, "copy_expansion_inputs", lambda *a, **k: calls.append("expansion_inputs"))
    monkeypatch.setattr(fc, "run_row", lambda row, cut, lane, deadline: (calls.append(row.id), ("PASS", 1, True))[1])
    cut = _git(fc.REPO, "rev-parse", "HEAD")
    rows = "frlgc_release_gate_quick,frlgc_source_firered" if title == "frlgc" else "*source_firered"
    return fc.main(["--cut", cut, "--title", title, "--lane", LANE, "--master", MASTER, "--rows", rows])


def test_the_gate_inputs_are_provisioned_after_the_plans_own_inputs_when_the_gate_row_runs(monkeypatch, tmp_path):
    calls = []
    assert _run_pass(monkeypatch, tmp_path, "frlgc", calls) == 0
    assert calls[:3] == ["provision", "copy_inputs", "gate_inputs"]
    calls.clear()
    (tmp_path / "b").mkdir()
    assert _run_pass(monkeypatch, tmp_path / "b", "frlgc-rand", calls) == 0
    assert "gate_inputs" not in calls                                                          # a plan without the gate row pays nothing


def test_only_a_selected_gate_row_triggers_it_and_a_provisioning_error_aborts_the_pass(monkeypatch, tmp_path, capsys):
    (tmp_path / "a").mkdir()
    calls = []
    assert _run_pass(monkeypatch, tmp_path / "a", "frlgc", calls) == 0 and "gate_inputs" in calls
    cut = _git(fc.REPO, "rev-parse", "HEAD")
    calls.clear()
    assert fc.main(["--cut", cut, "--title", "frlgc", "--lane", LANE, "--master", MASTER, "--rows", "frlgc_source_firered"]) == 0
    assert "gate_inputs" not in calls                                                          # the gate row was not selected

    def blocked(*a, **k):
        raise fc.LaneError("patch/vendor/pokefirered is missing")
    monkeypatch.setattr(fc, "provision_gate_inputs", blocked)
    calls.clear()
    assert fc.main(["--cut", cut, "--title", "frlgc", "--lane", LANE, "--master", MASTER,
                    "--rows", "frlgc_release_gate_quick"]) == 2
    assert "ABORT" in capsys.readouterr().err and not any(c.startswith("frlgc_") for c in calls)


def test_the_dry_run_names_the_gate_inputs(monkeypatch, capsys):
    cut = _git(fc.REPO, "rev-parse", "HEAD")
    assert fc.main(["--cut", cut, "--title", "frlgc", "--lane", LANE, "--master", MASTER, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "# provision: gate inputs" in out and "patch/vendor/pokefirered" in out and "expansion-src" in out
    assert fc.main(["--cut", cut, "--title", "exp", "--lane", LANE, "--master", MASTER, "--dry-run"]) == 0
    assert "# provision: gate inputs" not in capsys.readouterr().out                           # exp has its own provisioning
