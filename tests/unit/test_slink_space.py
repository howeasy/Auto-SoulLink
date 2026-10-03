"""tools/slink_space.py against real throwaway git repos in tmp_path.

Every refusal rule has a test here that fails when the rule is removed (revert-checked
when the tool landed).  Nothing touches the real repo, C: or the real work root: each test
hands the tool its own repo, work root and location list.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import slink_space as ss  # noqa: E402

DAY = 86400


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout


def _age(path, days=10):
    """Backdate every file and dir in a tree (not through links)."""
    t = time.time() - days * DAY
    for d, dirs, files in os.walk(path):
        dirs[:] = [x for x in dirs if not ss._path_is_link(os.path.join(d, x))]
        for f in files:
            if not ss._path_is_link(os.path.join(d, f)):
                os.utime(os.path.join(d, f), (t, t))
        os.utime(d, (t, t))


def _snapshot(root):
    out = set()
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            out.add(p)
    return out


def _sleeper(cwd):
    """A process that sits in `cwd`; its argv does NOT name the path."""
    p = subprocess.Popen([sys.executable, "-c", "import time; print(1, flush=True); "
                          "time.sleep(120)"], cwd=str(cwd), stdout=subprocess.PIPE)
    p.stdout.readline()  # started and sitting in cwd
    return p


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _link(target, link):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


@pytest.fixture(autouse=True)
def _no_process_scan(monkeypatch):
    """Most tests don't need the (slow) process scan; the in-use tests re-enable it."""
    monkeypatch.setattr(ss, "processes", lambda: [])


@pytest.fixture
def real_processes(monkeypatch):
    monkeypatch.setattr(ss, "processes", _REAL_PROCESSES)
    monkeypatch.setattr(ss, "_PROCS", None)
    monkeypatch.setattr(ss, "_CWDS", None)


_REAL_PROCESSES = ss.processes


@pytest.fixture
def W(tmp_path, monkeypatch):
    cfg = tmp_path / "gitconfig"
    cfg.write_text("[user]\n\tname = t\n\temail = t@t\n[init]\n\tdefaultBranch = master\n"
                   "[commit]\n\tgpgsign = false\n[core]\n\tautocrlf = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / ".gitignore").write_text("cache_link\n")
    (repo / "a.txt").write_text("v1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    c = tmp_path / "c"
    for sub in ("slink-wt", "slink", "temp"):
        (c / sub).mkdir(parents=True)
    w = SimpleNamespace(repo=repo, c=c, root=tmp_path / "root", tmp=tmp_path)
    w.locations = [["slink-wt", f"{c.as_posix()}/slink-wt/*", "checkouts", True],
                   ["slink", f"{c.as_posix()}/slink/*", "lane", True],
                   ["temp", f"{c.as_posix()}/temp/pytest-of-*", "pytest", False]]
    return w


def add_wt(w, name, commits=0, merge=False, old=True, where=None):
    path = (where or w.c / "slink-wt") / name
    _git(w.repo, "worktree", "add", "-q", "-b", name, str(path), "master")
    for i in range(commits):
        (path / f"{name}{i}.txt").write_text(f"{i}\n")
        _git(path, "add", ".")
        _git(path, "commit", "-qm", f"{name} {i}")
    if merge:
        _git(w.repo, "merge", "-q", "--ff-only", name)
    if old:
        _age(path)
    return path


def plan(w, kind="prune"):
    return ss.build_plan(kind, repo=w.repo, root=w.root, locations=w.locations,
                         lane_age=DAY, tmp_age=2 * 3600)


def item(p, path):
    n = ss._norm(path)
    return next(i for i in p["items"] if ss._norm(i["path"]) == n)


def apply(w, p, **cli):
    """Apply as the CLI would: repo/root/locations/thresholds come from the command, not
    from the plan file."""
    f = w.tmp / f"{p['kind']}-plan.json"
    f.write_text(json.dumps(p), encoding="utf-8")
    kw = {"repo": w.repo, "root": w.root, "locations": w.locations, "lane_age": DAY,
          "tmp_age": 2 * 3600, **cli}
    return ss.apply_plan(f, **kw)


def branches(w):
    return set(_git(w.repo, "branch", "--format=%(refname:short)").split())


# ---------------------------------------------------------------- work_root

def test_work_root_honours_env_creates_lazily_and_rejects_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("SLINK_WORK_ROOT", str(tmp_path / "wr"))
    assert not (tmp_path / "wr").exists()
    assert ss.work_root("lanes") == tmp_path / "wr" / "lanes"
    assert (tmp_path / "wr" / "lanes").is_dir()
    assert not (tmp_path / "wr" / "tmp").exists()
    with pytest.raises(ValueError):
        ss.work_root("scratch")
    monkeypatch.delenv("SLINK_WORK_ROOT")
    assert ss.DEFAULT_WORK_ROOT == "F:/slink-work"


# ---------------------------------------------------------------- worktree rules

def test_merged_clean_old_worktree_is_stale(W):
    p = add_wt(W, "done", commits=1, merge=True)
    it = item(plan(W), p)
    assert it["status"] == "stale" and it["merged"] and it["ahead"] == 0


def test_recent_merged_worktree_is_kept(W):
    p = add_wt(W, "fresh", old=False)
    assert item(plan(W), p)["status"] == "keep"


def test_unmerged_worktree_refused(W):
    p = add_wt(W, "wip", commits=2)
    it = item(plan(W), p)
    assert it["status"] == "refuse" and "not merged" in it["reason"] and it["ahead"] == 2


def test_dirty_tracked_worktree_refused(W):
    p = add_wt(W, "edit")
    (p / "a.txt").write_text("changed\n")
    _age(p)
    it = item(plan(W), p)
    assert it["status"] == "refuse" and it["tracked"] == 1 and "dirty" in it["reason"]


def test_dirty_untracked_worktree_refused(W):
    p = add_wt(W, "new")
    (p / "notes.txt").write_text("x\n")
    _age(p)
    it = item(plan(W), p)
    assert it["status"] == "refuse" and it["untracked"] == 1


def test_locked_worktree_with_live_pid_refused(W):
    p = add_wt(W, "busy")
    _git(W.repo, "worktree", "lock", "--reason", f"claude agent x (pid {os.getpid()})", str(p))
    it = item(plan(W), p)
    assert it["status"] == "refuse" and "live pid" in it["reason"]


def test_locked_worktree_without_pid_refused(W):
    p = add_wt(W, "init")
    _git(W.repo, "worktree", "lock", "--reason", "initializing", str(p))
    assert item(plan(W), p)["status"] == "refuse"


def test_locked_worktree_with_dead_pid_is_stale_and_unlocked_on_apply(W):
    p = add_wt(W, "gone")
    _git(W.repo, "worktree", "lock", "--reason", f"claude agent y (pid {_dead_pid()})", str(p))
    pl = plan(W)
    assert item(pl, p)["status"] == "stale"
    apply(W, pl)
    assert not p.exists() and "gone" not in branches(W)


def test_worktree_outside_scanned_set_refused(W):
    elsewhere = W.tmp / "elsewhere"
    elsewhere.mkdir()
    p = add_wt(W, "codex", where=elsewhere)
    it = item(plan(W), p)
    assert it["status"] == "refuse" and "outside" in it["reason"]


# ---------------------------------------------------------------- dry run and apply

def test_dry_run_deletes_nothing(W):
    add_wt(W, "done", commits=1, merge=True)
    add_wt(W, "wip", commits=1)
    lane = W.c / "slink" / "old-lane"
    lane.mkdir()
    (lane / "state.bin").write_bytes(b"x" * 100)
    _age(lane)
    before, refs = _snapshot(W.tmp), branches(W)
    p = plan(W)
    m = plan(W, "move")
    assert p["actions"] and m["actions"] is not None
    assert before <= _snapshot(W.tmp) and branches(W) == refs  # nothing removed


def test_apply_removes_only_stale_and_deletes_merged_branch(W):
    done = add_wt(W, "done", commits=1, merge=True)
    wip = add_wt(W, "wip", commits=1)
    dirty = add_wt(W, "dirty")
    (dirty / "x.txt").write_text("x")
    _age(dirty)
    done_lines = apply(W, plan(W))
    assert any("remove-worktree" in line for line in done_lines)
    assert not done.exists() and "done" not in branches(W)
    assert wip.exists() and dirty.exists() and {"wip", "dirty"} <= branches(W)
    assert ss._norm(done) not in {ss._norm(x["path"]) for x in ss.list_worktrees(W.repo)}


def test_apply_aborts_when_state_changed_since_plan(W):
    done = add_wt(W, "done", commits=1, merge=True)
    p = plan(W)
    (done / "late.txt").write_text("work arrived after the plan")
    with pytest.raises(ss.PlanChanged):
        apply(W, p)
    assert (done / "late.txt").exists() and "done" in branches(W)


def test_apply_aborts_on_tampered_plan(W):
    outside = W.tmp / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("k")
    p = plan(W)
    p["actions"].append({"op": "remove-dir", "path": outside.as_posix(), "size": 1,
                         "fp": "1:1:0", "reason": "tampered"})
    with pytest.raises(ss.PlanChanged):
        apply(W, p)
    assert (outside / "keep.txt").exists()


def _remove_action(p):
    return {"path": p.as_posix(), "unlock": False, "branch": None,
            "admin": ss._admin_dir(p)}


def test_remove_worktree_rechecks_dirty_at_execution(W):
    p = add_wt(W, "late")
    (p / "a.txt").write_text("edited after planning\n")
    with pytest.raises(RuntimeError, match="dirty"):
        ss._remove_worktree(W.repo, _remove_action(p))
    assert (p / "a.txt").read_text() == "edited after planning\n"


def test_remove_worktree_fallback_spares_a_live_unregistered_checkout(W):
    # git no longer lists it (admin gitdir gone), so `worktree remove` fails and the old
    # fallback rmtree'd it, dirty work included.
    p = add_wt(W, "ghost")
    (Path(ss._admin_dir(p)) / "gitdir").unlink()
    (p / "a.txt").write_text("uncommitted\n")
    with pytest.raises(RuntimeError):
        ss._remove_worktree(W.repo, _remove_action(p))
    assert (p / "a.txt").read_text() == "uncommitted\n"


def test_remove_worktree_refuses_a_locked_one(W):
    p = add_wt(W, "held")
    _git(W.repo, "worktree", "lock", "--reason", "pid 1", str(p))
    with pytest.raises(RuntimeError):
        ss._remove_worktree(W.repo, _remove_action(p))
    assert (p / "a.txt").exists()


def test_apply_refuses_a_plan_built_with_other_params(W):
    # Review vector: a plan whose own params widen the scan (and whose actions are
    # self-consistent with them) must not be replayed.
    precious = W.tmp / "precious-lane"
    precious.mkdir()
    (precious / "keep.txt").write_text("k")
    _age(precious)
    evil = ss.build_plan("prune", repo=W.repo, root=W.root, lane_age=DAY, tmp_age=2 * 3600,
                         locations=[*W.locations, ["x", f"{W.tmp.as_posix()}/precious*", "tmp",
                                                   False]])
    assert any("precious" in a["path"] for a in evil["actions"])
    with pytest.raises(ss.PlanChanged, match="params"):
        apply(W, evil)
    assert (precious / "keep.txt").exists()


def test_apply_refuses_different_thresholds(W):
    lane = W.c / "slink" / "old"
    lane.mkdir()
    _age(lane)
    p = plan(W)
    with pytest.raises(ss.PlanChanged, match="params"):
        apply(W, p, lane_age=5 * DAY)
    assert lane.exists()


def test_branch_git_will_not_delete_survives_apply(W):
    # `git branch -d` re-checks the merge against the main checkout's HEAD. With the main
    # checkout on a branch that lacks the commit, -d refuses; -D would have deleted it.
    _git(W.repo, "branch", "dev")
    done = add_wt(W, "done", commits=1, merge=True)
    _git(W.repo, "checkout", "-q", "dev")
    p = plan(W)
    assert item(p, done)["status"] == "stale"
    with pytest.raises(RuntimeError, match="not fully merged"):
        apply(W, p)
    assert "done" in branches(W)


def test_norm_strips_long_path_prefixes():
    assert ss._norm("\\\\?\\C:\\Slink\\x\\") == ss._norm("C:/Slink/x")
    assert ss._norm("\\??\\C:\\Slink\\x") == ss._norm("C:/Slink/x")


# ---------------------------------------------------------------- lanes and temps

def test_temp_and_lane_age_rules(W):
    pyt = W.c / "temp" / "pytest-of-me"
    old_t, new_t = pyt / "pytest-1", pyt / "pytest-2"
    for d in (old_t, new_t):
        d.mkdir(parents=True)
        (d / "f").write_text("x")
    t = time.time() - 3 * 3600
    for f in (old_t / "f", old_t):
        os.utime(f, (t, t))
    lane = W.c / "slink" / "lane1"
    lane.mkdir()
    (lane / "s").write_text("s")
    young = W.c / "slink" / "lane2"
    young.mkdir()
    _age(lane)
    p = plan(W)
    assert item(p, old_t)["status"] == "stale"
    assert item(p, new_t)["status"] == "keep"
    assert item(p, lane)["status"] == "stale"
    assert item(p, young)["status"] == "keep"
    apply(W, p)
    assert not old_t.exists() and not lane.exists() and new_t.exists() and young.exists()


def test_lane_in_use_by_a_process_refused(W, real_processes):
    lane = W.c / "slink" / "running"
    lane.mkdir()
    (lane / "s").write_text("s")
    _age(lane)
    proc = _sleeper(lane)
    try:
        it = item(plan(W), lane)
        assert it["status"] == "refuse" and "in use" in it["reason"]
    finally:
        proc.kill()
        proc.wait()


def test_old_temp_with_a_process_inside_refused(W, real_processes):
    pyt = W.c / "temp" / "pytest-of-me" / "pytest-7"
    (pyt / "deep").mkdir(parents=True)
    t = time.time() - 3 * 3600
    for f in (pyt / "deep", pyt):
        os.utime(f, (t, t))
    if not ss.cwd_scan_available():
        pytest.skip("no cwd scan on this platform (the 24h floor test covers it)")
    proc = _sleeper(pyt / "deep")
    try:
        it = item(plan(W), pyt)
        assert it["status"] == "refuse" and str(proc.pid) in it["reason"]
    finally:
        proc.kill()
        proc.wait()


def test_without_cwd_scan_temps_get_a_24h_floor(W, monkeypatch):
    monkeypatch.setattr(ss, "cwd_scan_available", lambda: False)
    pyt = W.c / "temp" / "pytest-of-me" / "pytest-8"
    pyt.mkdir(parents=True)
    t = time.time() - 3 * 3600
    os.utime(pyt, (t, t))
    assert item(plan(W), pyt)["status"] == "keep"
    t = time.time() - 25 * 3600
    os.utime(pyt, (t, t))
    assert item(plan(W), pyt)["status"] == "stale"


def test_users_of_matches_whole_path_components(W, monkeypatch):
    base = W.c.as_posix()
    monkeypatch.setattr(ss, "processes", lambda: [(4242, f"tool {base}/slink-cache/f.bin"),
                                                  (4243, f'tool "{base}\\slink\\run.py"')])
    monkeypatch.setattr(ss, "_CWDS", {})
    assert ss.users_of(f"{base}/slink-cache") == [4242]
    assert ss.users_of(f"{base}/slink") == [4243]
    assert ss.users_of(f"{base}/slin") == []


def test_lane_holding_a_git_entry_refused(W):
    lane = W.c / "slink" / "looks-like-a-lane"
    lane.mkdir()
    (lane / ".git").write_text("gitdir: /somewhere\n")
    (lane / "work.c").write_text("w")
    _age(lane)
    p = plan(W)
    assert item(p, lane)["status"] == "refuse"
    apply(W, p)
    assert (lane / "work.c").exists()


def test_evidence_and_unregistered_checkouts_kept(W):
    ev = W.c / "slink-wt" / "rr-final-evidence"
    ev.mkdir()
    (ev / "log").write_text("l")
    co = W.c / "slink-wt" / "orphan-checkout"
    co.mkdir()
    (co / ".git").write_text("gitdir: /nowhere\n")
    _age(ev)
    _age(co)
    p = plan(W)
    assert item(p, ev)["status"] == "keep" and item(p, co)["status"] == "keep"


# ---------------------------------------------------------------- Drive hazards

def test_drive_conflict_ref_flagged_and_refused_when_it_holds_unique_commits(W):
    master = _git(W.repo, "rev-parse", "master").strip()
    heads = W.repo / ".git" / "refs" / "heads"
    (heads / "master (1)").write_text(master + "\n")
    _git(W.repo, "checkout", "-q", "-b", "side")
    (W.repo / "side.txt").write_text("s")
    _git(W.repo, "add", ".")
    _git(W.repo, "commit", "-qm", "side")
    orphan = _git(W.repo, "rev-parse", "HEAD").strip()
    _git(W.repo, "checkout", "-q", "master")
    _git(W.repo, "update-ref", "-d", "refs/heads/side")
    (heads / "side (1)").write_text(orphan + "\n")
    p = plan(W)
    assert item(p, heads / "master (1)")["status"] == "stale"
    assert item(p, heads / "side (1)")["status"] == "refuse"


def test_known_drive_restores_and_conflict_copies_are_stale(W):
    known = W.repo / "lua" / "memory_gba.lua"
    known.parent.mkdir()
    known.write_text("old gba\n")
    (W.repo / "b.txt").write_text("bee\n")
    _git(W.repo, "add", ".")
    _git(W.repo, "commit", "-qm", "add")
    _git(W.repo, "rm", "-q", "lua/memory_gba.lua")
    _git(W.repo, "commit", "-qm", "drop gba")
    known.parent.mkdir(exist_ok=True)
    known.write_text("old gba\n")
    (W.repo / "b (1).txt").write_text("bee\n")
    (W.repo / "novel.txt").write_text("brand new\n")
    # The real repo carries one of these, and it makes `git log --all` fatal.
    master = _git(W.repo, "rev-parse", "master").strip()
    (W.repo / ".git" / "refs" / "heads" / "master (1)").write_text(master + "\n")
    p = plan(W)
    assert item(p, known)["status"] == "stale"
    assert item(p, W.repo / "b (1).txt")["status"] == "stale"
    paths = {ss._norm(i["path"]) for i in p["items"] if i["kind"] == "drive-copy"}
    assert ss._norm(W.repo / "novel.txt") not in paths


def test_other_untracked_old_revision_is_refused_and_survives(W):
    _git(W.repo, "rm", "-q", "--cached", "a.txt")  # benign: someone untracking a file
    p = plan(W)
    it = item(p, W.repo / "a.txt")
    assert it["status"] == "refuse"
    apply(W, p)
    assert (W.repo / "a.txt").read_text() == "v1\n"


def test_orphan_admin_dir_detected_and_pruned(W):
    p = add_wt(W, "vanished")
    ss._rmtree(p)
    pl = plan(W)
    admin = [i for i in pl["items"] if i["kind"] == "admin"]
    assert len(admin) == 1 and admin[0]["status"] == "stale"
    apply(W, pl)
    assert not Path(admin[0]["path"]).exists()


def test_orphan_admin_still_named_by_a_checkout_refused(W):
    # Drive ate the admin dir's gitdir file: git calls it prunable, but the checkout's
    # .git still points at it (C:/slink-wt/rr-complete on the real machine).
    p = add_wt(W, "half")
    admin = Path(ss._admin_dir(p))
    (admin / "gitdir").unlink()
    other = add_wt(W, "fine")
    ss._rmtree(other)  # a genuinely orphaned one alongside
    pl = plan(W)
    it = item(pl, admin)
    assert it["status"] == "refuse" and "half" in it["reason"]
    apply(W, pl)
    assert admin.is_dir() and (p / "a.txt").exists()


def test_unregistered_dir_in_worktree_location_kept_unless_empty(W):
    W.locations.append(["claude-wt", f"{W.tmp.as_posix()}/cwt/*", "worktrees", False])
    full, empty = W.tmp / "cwt" / "leftover", W.tmp / "cwt" / "gutted"
    full.mkdir(parents=True)
    (full / "work.txt").write_text("w")
    empty.mkdir()
    _age(full)
    _age(empty)
    p = plan(W)
    assert item(p, full)["status"] == "keep"
    assert item(p, empty)["status"] == "stale"


# ---------------------------------------------------------------- links

@pytest.fixture
def shared_cache(W):
    target = W.tmp / "shared-cache"
    target.mkdir()
    (target / "rom.bin").write_bytes(b"r" * 4096)
    return target


def _junction_wt(W, shared_cache, name, **kw):
    p = add_wt(W, name, old=False, **kw)
    try:
        _link(shared_cache, p / "cache_link")
    except OSError as e:
        pytest.skip(f"cannot create a junction/symlink here: {e}")
    _age(p)
    return p


def test_prune_never_follows_a_junction(W, shared_cache):
    p = _junction_wt(W, shared_cache, "linked")
    pl = plan(W)
    it = item(pl, p)
    assert it["status"] == "stale" and it["size"] < 4096 and it["links"]
    apply(W, pl)
    assert not p.exists()
    assert (shared_cache / "rom.bin").is_file()  # not stat(): an OSError trips conftest
    assert (shared_cache / "rom.bin").stat().st_size == 4096


@pytest.fixture
def pre312(monkeypatch):
    """Python < 3.12 has no os.path.isjunction / DirEntry.is_junction."""
    monkeypatch.delattr(os.path, "isjunction", raising=False)


def _plain_link(W, shared_cache, name):
    link = W.tmp / name
    try:
        _link(shared_cache, link)
    except OSError as e:
        pytest.skip(f"cannot create a junction/symlink here: {e}")
    return link


def test_rmtree_on_a_top_level_junction_unlinks_it_only(W, shared_cache, pre312):
    link = _plain_link(W, shared_cache, "top-link")
    ss._rmtree(link)
    assert not os.path.lexists(link)
    assert (shared_cache / "rom.bin").is_file()


def test_tree_stats_lists_links_without_their_bytes(W, shared_cache, pre312):
    d = W.tmp / "holder"
    d.mkdir()
    (d / "own.txt").write_bytes(b"o" * 10)
    _link(shared_cache, d / "inner")
    st = ss.tree_stats(d)
    assert st["size"] == 10 and st["files"] == 1
    assert [x[0] for x in st["links"]] == ["inner"]
    assert st["links"][0][2] == ("junction" if os.name == "nt" else "symlink")
    top = ss.tree_stats(_plain_link(W, shared_cache, "top2"))
    assert top["size"] == 0 and top["files"] == 0


def test_deleters_refuse_when_link_detection_is_unavailable(W, monkeypatch):
    d = W.tmp / "victim"
    d.mkdir()
    (d / "f").write_text("f")
    monkeypatch.setattr(ss, "link_detection_available", lambda: False)
    with pytest.raises(RuntimeError, match="link detection"):
        ss._rmtree(d)
    with pytest.raises(RuntimeError, match="link detection"):
        ss._copy_tree(str(d), str(W.tmp / "copy"))
    assert (d / "f").exists() and not (W.tmp / "copy").exists()


# ---------------------------------------------------------------- move-to-work-root

def test_c_drive_content_is_moved_not_deleted(W, monkeypatch):
    monkeypatch.setattr(ss, "_on_c", lambda p: ss._norm(p).startswith(ss._norm(W.c)))
    lane = W.c / "slink" / "old-state"
    lane.mkdir()
    (lane / "s").write_text("s")
    _age(lane)
    wt = add_wt(W, "c-done", commits=1, merge=True)
    pyt = W.c / "temp" / "pytest-of-me" / "pytest-3"
    pyt.mkdir(parents=True)
    t = time.time() - 30 * 3600
    os.utime(pyt, (t, t))
    gone = add_wt(W, "c-gone")
    ss._rmtree(gone)  # orphan admin dir: pure junk, still pruned
    pr = plan(W)
    pruned = {ss._norm(a["path"]) for a in pr["actions"]}
    assert ss._norm(lane) not in pruned and ss._norm(wt) not in pruned
    assert ss._norm(pyt) in pruned
    assert any(a["op"] == "prune-admin" for a in pr["actions"])
    mv = plan(W, "move")
    dst = {ss._norm(a["src"]): a["dst"] for a in mv["actions"]}
    assert dst[ss._norm(lane)] == (W.root / "evidence" / "slink" / "old-state").as_posix()
    assert ss._norm(wt) in dst and ss._norm(pyt) not in dst
    apply(W, pr)
    assert (lane / "s").exists() and wt.exists() and not pyt.exists()


def _readd_setup(W, name):
    p = add_wt(W, name, commits=1, old=False)
    head = _git(p, "rev-parse", "HEAD").strip()
    m = plan(W, "move")
    assert next(a for a in m["actions"] if ss._norm(a["src"]) == ss._norm(p))["op"] == \
        "move-worktree-readd"
    return p, head, m, W.root / "wt" / name


def _assert_rolled_back(W, p, head, new, name):
    assert _git(p, "rev-parse", "HEAD").strip() == head
    assert _git(p, "branch", "--show-current").strip() == name
    assert _git(p, "status", "--porcelain") == ""
    assert not new.exists()
    listed = {ss._norm(w["path"]) for w in ss.list_worktrees(W.repo)}
    assert ss._norm(p) in listed and ss._norm(new) not in listed


def test_readd_rolls_back_when_relink_fails(W, monkeypatch):
    p, head, m, new = _readd_setup(W, "rb1")

    def boom(*_a):
        raise OSError("relink failed")
    monkeypatch.setattr(ss, "_relink", boom)
    with pytest.raises(OSError):
        apply(W, m)
    _assert_rolled_back(W, p, head, new, "rb1")


def test_readd_rolls_back_when_branch_checkout_fails(W, monkeypatch):
    p, head, m, new = _readd_setup(W, "rb2")
    real = ss.git

    def git(cwd, *args):
        if args[:1] == ("checkout",):
            raise RuntimeError("checkout failed")
        return real(cwd, *args)
    monkeypatch.setattr(ss, "git", git)
    with pytest.raises(RuntimeError, match="checkout failed"):
        apply(W, m)
    _assert_rolled_back(W, p, head, new, "rb2")


def test_apply_takes_a_mutex(W):
    lane = W.c / "slink" / "old"
    lane.mkdir()
    _age(lane)
    lock = W.root / "tmp" / "slink-space-apply.lock"
    p = plan(W)
    lock.write_text(str(os.getpid()))
    with pytest.raises(ss.PlanChanged, match="another"):
        apply(W, p)
    assert lane.exists()
    lock.write_text(str(_dead_pid()))  # a crashed run's lock is taken over
    apply(W, p)
    assert not lane.exists() and not lock.exists()


def test_move_refuses_live_lock_and_in_use(W, real_processes):
    locked = add_wt(W, "locked", commits=1)
    _git(W.repo, "worktree", "lock", "--reason", f"agent (pid {os.getpid()})", str(locked))
    lane = W.c / "slink" / "hot"
    lane.mkdir()
    proc = _sleeper(lane)
    try:
        m = plan(W, "move")
        refused = {ss._norm(r["path"]): r["reason"] for r in m["refused"]}
        assert "locked" in refused[ss._norm(locked)]
        assert "in use" in refused[ss._norm(lane)]
        assert not any(ss._norm(a["src"]) in refused for a in m["actions"])
    finally:
        proc.kill()
        proc.wait()


def test_move_dirty_worktree_copy_keeps_status_and_links(W, shared_cache):
    p = _junction_wt(W, shared_cache, "dirtywt", commits=1)
    (p / "a.txt").write_text("edited\n")
    (p / "scratch.txt").write_text("u\n")
    before = _git(p, "status", "--porcelain")
    m = plan(W, "move")
    act = next(a for a in m["actions"] if ss._norm(a["src"]) == ss._norm(p))
    assert act["op"] == "move-worktree-copy"
    apply(W, m)
    new = W.root / "wt" / "dirtywt"
    assert not p.exists() and new.is_dir()
    assert _git(new, "status", "--porcelain") == before
    assert ss._path_is_link(new / "cache_link")
    assert (shared_cache / "rom.bin").is_file()  # not stat(): an OSError trips conftest
    assert (shared_cache / "rom.bin").stat().st_size == 4096
    listed = {ss._norm(w["path"]) for w in ss.list_worktrees(W.repo)}
    assert ss._norm(new) in listed and ss._norm(p) not in listed


def test_move_clean_worktree_readds_and_plain_dirs_move(W):
    p = add_wt(W, "unmerged", commits=1, old=False)
    head = _git(p, "rev-parse", "HEAD").strip()
    lane = W.c / "slink" / "lane-young"
    lane.mkdir()
    (lane / "s").write_text("state")
    loose = W.c / "slink-wt" / "run.log"
    loose.write_text("log")
    (W.repo / "doc.md").write_text(f"see {p.as_posix()} for the run\n")
    _git(W.repo, "add", "doc.md")
    _git(W.repo, "commit", "-qm", "doc")
    m = plan(W, "move")
    ops = {ss._norm(a["src"]): a["op"] for a in m["actions"]}
    assert ops[ss._norm(p)] == "move-worktree-readd"
    assert ops[ss._norm(lane)] == "move-dir" and ops[ss._norm(loose)] == "move-file"
    assert any("doc.md" in f for f in m["followups"])
    apply(W, m)
    new = W.root / "wt" / "unmerged"
    assert _git(new, "rev-parse", "HEAD").strip() == head
    assert _git(new, "branch", "--show-current").strip() == "unmerged"
    assert _git(new, "status", "--porcelain") == ""
    assert not p.exists() and not lane.exists() and not loose.exists()
    assert (W.root / "lanes" / "lane-young" / "s").read_text() == "state"
    assert (W.root / "evidence" / "slink-wt" / "run.log").read_text() == "log"
