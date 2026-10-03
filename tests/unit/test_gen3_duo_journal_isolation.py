"""The Gen 3 duo wrapper keeps a durable journal inside each attempt."""

import argparse
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import e2e_duo as duo  # noqa: E402


def _launch_pair(monkeypatch, tmp_path, attempt):
    config = tmp_path / "config.ini"
    config.write_text(json.dumps({"MainWindowPosition": "1200, -1300", "PathEntries": {"Paths": [
        {"System": "GBA", "Type": "Save RAM", "Path": ""}]}}), encoding="utf-8")
    monkeypatch.setattr(duo, "BUILD", str(tmp_path))
    monkeypatch.setattr(duo, "BIZHAWK_CONFIG", str(config))
    monkeypatch.setattr(duo, "_LANE_ORDINAL", {})
    created = iter([tmp_path / f"attempt-{attempt}"])
    def private_dir(prefix, dir=None):
        path = next(created)
        path.mkdir()
        return str(path)
    monkeypatch.setattr(duo.tempfile, "mkdtemp", private_dir)
    monkeypatch.setattr(duo.subprocess, "Popen", lambda *args, **kwargs: object())
    args = argparse.Namespace(game="gen3_rr", lane=f"t{attempt}", idle_jitter=0,
                              server_flags=[], wire_log=False)
    run = duo.DuoRun("linked_faint_active_whiteout_gen3", args, attempt=attempt)
    monkeypatch.setattr(run, "_rom_for", lambda inst: f"fake-{inst}.gba")
    def path(inst):
        stub = Path(run.stub_path(inst)).read_text(encoding="utf-8")
        match = re.search(r'^  journal_path = "([^"]+)",$', stub, re.M)
        return match.group(1) if match else (ROOT / "slink_gen3_trade").as_posix()
    run.phase_paths = []                                         # [(inst, phase, journal_path)] as each launch wrote it into its stub
    for inst, phase in (("a", "initial"), ("b", "initial"), ("a", "reload"), ("b", "reload")):
        run.launch_instance(inst, phase=phase, seed=False)
        run.phase_paths.append((inst, phase, path(inst)))
    return run, path("a"), path("b")


def test_each_instance_has_its_own_journal_kept_across_its_phases_and_attempts_stay_isolated(monkeypatch, tmp_path):
    """Production has one journal per player: A and B never share a file or its OS guard (shared, one client's read made the other's
    journal 'busy' and hid its captures), the same instance keeps its path across relaunch phases, and attempts stay apart."""
    first, a1, b1 = _launch_pair(monkeypatch, tmp_path, 1)
    second, a2, b2 = _launch_pair(monkeypatch, tmp_path, 2)
    assert a1 == (Path(first.data_dir) / "slink_gen3_trade_a").as_posix()
    assert b1 == (Path(first.data_dir) / "slink_gen3_trade_b").as_posix()
    assert a2 == (Path(second.data_dir) / "slink_gen3_trade_a").as_posix()
    assert b2 == (Path(second.data_dir) / "slink_gen3_trade_b").as_posix()
    assert len({a1, b1, a2, b2}) == 4                                   # four distinct files: per instance AND per attempt
    for run, a, b in ((first, a1, b1), (second, a2, b2)):
        assert [p for i, _ph, p in run.phase_paths if i == "a"] == [a, a]       # initial and reload: the same journal
        assert [p for i, _ph, p in run.phase_paths if i == "b"] == [b, b]


def test_actual_duo_lua_wrapper_redirects_only_the_store_path(tmp_path):
    lupa = pytest.importorskip("lupa")
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text(encoding="utf-8")
    match = re.search(r"(?ms)^local function isolated_journal_module\([^\n]+\).*?^end$", source)
    assert match, "the test must execute the duo wrapper's actual journal composition"
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    wrap = lua.execute(match.group() + "\nreturn isolated_journal_module")
    seen = []
    module = lua.table(file_store=lambda deps: seen.append(deps.path) or lua.table(ok=True))
    private = (tmp_path / "run" / "slink_gen3_trade").as_posix()
    wrapped = wrap(module, private, None, lambda *_: None)
    deps = lua.table(path="production-root/slink_gen3_trade", fs="real-host-adapter")
    assert wrapped.file_store(deps).ok
    assert seen == [private] and deps.fs == "real-host-adapter"
    untouched = lua.table(file_store=lambda deps: seen.append(deps.path) or lua.table(ok=True))
    wrap(untouched, None, None, lambda *_: None).file_store(lua.table(path="production-root/slink_gen3_trade"))
    assert seen[-1] == "production-root/slink_gen3_trade"
    manifest_path = "manifest-owned/slink_gen3_trade"
    def bind_candidate(module):
        original = module.file_store
        module.file_store = lambda deps: original(lua.table(path=manifest_path, fs=deps.fs))
    candidate = lua.table(bind_journal=bind_candidate)
    carrier = lua.table(file_store=lambda deps: seen.append(deps.path) or lua.table(ok=True))
    wrap(carrier, private, candidate, lambda *_: None).file_store(lua.table(path="production-root/slink_gen3_trade"))
    assert seen[-1] == manifest_path  # the candidate owns this override


def test_real_guarded_journal_keeps_attempt_one_intent_out_of_attempt_two(tmp_path):
    lupa = pytest.importorskip("lupa")
    from tests.unit.test_gen3_trade_journal import Files
    from gen3_trade_duo import journal_state

    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text(encoding="utf-8")
    body = re.search(r"(?ms)^local function isolated_journal_module\([^\n]+\).*?^end$", source)
    assert body
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    wrap = lua.execute(body.group() + "\nreturn isolated_journal_module")
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    files = Files()
    def journal(path, player):
        module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text(encoding="utf-8"))
        wrap(module, path, None, lambda *_: None)
        backend = module.file_store(lua.table(json=codec, fs=files.table(lua), path="production-root/slink_gen3_trade"))
        obj = module.new(lua.table(json=codec, store=backend, rom_sha1="a" * 40, player=player))
        assert obj.bind(obj, "run-" + path, "12345678")
        return obj

    first = (tmp_path / "attempt-1" / "slink_gen3_trade").as_posix()
    second = (tmp_path / "attempt-2" / "slink_gen3_trade").as_posix()
    a = journal(first, "a")
    b = journal(first, "b")
    epoch = a.allocate(a)
    assert a.arm(a, "pending", epoch) is True
    assert a.hidden(a) is True and b.ready(b) is True
    next_run = journal(second, "a")
    assert next_run.ready(next_run) is True and next_run.hidden(next_run) is False
    assert first + ".log" in files.files and first + ".guard" in files.files
    assert second + ".log" in files.files and second + ".guard" in files.files
    def independent_read(path):
        return journal_state(files.files[path + ".log"].encode("utf-8"),
                             files.files[path + ".guard"].encode("utf-8"))
    assert len(independent_read(first)["records"]) == 1
    assert independent_read(second)["records"] == []
    assert a.hidden(a) is True  # isolation did not delete or bypass the old guard


@pytest.mark.parametrize("scenario,cfg", [
    ("trade_lock_probe_gen3", {"journal_lock_probe": True}),
    ("native_trade_gen3", {"gen3_native_trade": True}),
])
def test_existing_journal_owners_keep_their_paths(scenario, cfg, tmp_path):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario, run.cfg, run.data_dir = scenario, cfg, str(tmp_path)
    assert run._gen3_duo_journal_path("a") is None and run._gen3_duo_journal_path("b") is None


def test_journal_probe_flag_survives_scenario_rename(tmp_path):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario, run.cfg, run.data_dir = "renamed_probe", {"journal_lock_probe": True}, str(tmp_path)
    assert run._gen3_duo_journal_path("a") is None


def test_new_private_server_data_identity_gets_its_own_journal(tmp_path):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario, run.cfg, run.data_dir = "admit_randomized_frlg", {"gen3_rand": True}, str(tmp_path / "controls")
    controls = {inst: run._gen3_duo_journal_path(inst) for inst in "ab"}
    run.data_dir = str(tmp_path / "controls" / "randomized_pair")
    randomized = {inst: run._gen3_duo_journal_path(inst) for inst in "ab"}
    assert len({*controls.values(), *randomized.values()}) == 4          # a new data identity: new files for BOTH instances
    assert all(p.parent.name == "controls" for p in controls.values())
    assert all(p.parent.name == "randomized_pair" for p in randomized.values())
    assert controls["a"].name.endswith("_a") and controls["b"].name.endswith("_b")


def test_the_rr_reset_archive_keeps_both_instances_journals_under_distinct_names(tmp_path):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario, run.cfg, run.data_dir = "rr_trade_reset_gen3", {}, str(tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    archive = tmp_path / "archive"
    archive.mkdir()
    for inst in "ab":
        for suffix in ("log", "guard"):
            Path(run._gen3_duo_journal_path(inst).as_posix() + "." + suffix).write_bytes(f"{inst}-{suffix}".encode())
    run._archive_gen3_duo_journals(archive)
    assert sorted(p.name for p in archive.iterdir()) == ["slink_gen3_trade_a.guard", "slink_gen3_trade_a.log",
                                                         "slink_gen3_trade_b.guard", "slink_gen3_trade_b.log"]
    assert (archive / "slink_gen3_trade_b.log").read_bytes() == b"b-log"
    Path(run._gen3_duo_journal_path("b").as_posix() + ".guard").unlink()
    with pytest.raises(RuntimeError, match="RR reset missing durable trade journal"):          # the old check survives, per instance
        run._archive_gen3_duo_journals(tmp_path / "again")
    run.cfg = {"gen3_native_trade": True}
    with pytest.raises(RuntimeError, match="no private durable journal path"):
        run._archive_gen3_duo_journals(archive)


def test_actual_dofile_interception_reaches_run_lua_journal_load(tmp_path):
    lupa = pytest.importorskip("lupa")
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text(encoding="utf-8")
    run_source = (ROOT / "lua/gen3/run.lua").read_text(encoding="utf-8")
    assert 'dofile(ROOT .. "/lua/gen3/trade_journal.lua")' in run_source
    assert 'path=ROOT .. "/slink_gen3_trade"' in run_source
    helper = re.search(r"(?ms)^local function isolated_journal_module\([^\n]+\).*?^end$", source)
    interception = re.search(
        r"(?ms)^do\n    dofile = function\(path\).*?^if not okrun then finish\(false, .*?\n", source)
    assert helper and interception, "execute the wrapper installed around the run.lua dofile"
    private = (tmp_path / "attempt" / "slink_gen3_trade").as_posix()

    def selected_path(interceptor):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        prelude = '''
local ROOT = "fixture-root"
local D = {journal_path = PRIVATE_PATH}
local title = "radical_red"
local native_candidate = nil
local battle_parts = nil
local log = function(_) end
local test_admission_codec = function(_, _, value) return value end
local finish = function(_, message) error(message) end
local seen = {}
local dofile
local original_dofile = function(path)
    if path == ROOT .. "/lua/gen3/trade_journal.lua" then
        return {file_store = function(deps) seen[#seen + 1] = deps.path; return {} end}
    end
    if path == ROOT .. "/lua/gen3/run.lua" then
        local module = dofile(ROOT .. "/lua/gen3/trade_journal.lua")
        module.file_store({path = ROOT .. "/slink_gen3_trade"})
        return true
    end
    error("unexpected dofile " .. path)
end
dofile = original_dofile
'''.replace("PRIVATE_PATH", json.dumps(private))
        return lua.execute(prelude + helper.group() + "\n" + interceptor + "\nreturn seen[1]")

    assert selected_path(interception.group()) == private
    misplaced = interception.group().replace(
        'if path == ROOT .. "/lua/gen3/trade_journal.lua" then',
        'if path == ROOT .. "/lua/gen3/wrong_journal.lua" then', 1)
    assert misplaced != interception.group()
    assert selected_path(misplaced) == "fixture-root/slink_gen3_trade"  # would fail the private-path assertion
