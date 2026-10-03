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


def _sleeper(path):
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", str(path)])


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


def apply(w, p):
    f = w.tmp / f"{p['kind']}-plan.json"
    f.write_text(json.dumps(p), encoding="utf-8")
    return ss.apply_plan(f)


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


def test_branch_delete_is_lowercase_d_only():
    src = (REPO / "tools" / "slink_space.py").read_text(encoding="utf-8")
    assert '"branch", "-d"' in src
    assert '"-D"' not in src and '"--force"' not in src  # no forced remove/add anywhere


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


def test_untracked_copy_of_old_revision_flagged(W):
    _git(W.repo, "rm", "-q", "a.txt")
    _git(W.repo, "commit", "-qm", "drop a")
    (W.repo / "a.txt").write_text("v1\n")
    (W.repo / "novel.txt").write_text("brand new\n")
    # The real repo carries one of these, and it makes `git log --all` fatal.
    master = _git(W.repo, "rev-parse", "master").strip()
    (W.repo / ".git" / "refs" / "heads" / "master (1)").write_text(master + "\n")
    paths = {ss._norm(i["path"]) for i in plan(W)["items"] if i["kind"] == "drive-copy"}
    assert ss._norm(W.repo / "a.txt") in paths
    assert ss._norm(W.repo / "novel.txt") not in paths


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
