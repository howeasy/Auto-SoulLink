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
    for inst, phase in (("a", "initial"), ("b", "initial"), ("a", "reload")):
        run.launch_instance(inst, phase=phase, seed=False)
    def path(inst):
        stub = Path(run.stub_path(inst)).read_text(encoding="utf-8")
        match = re.search(r'^  journal_path = "([^"]+)",$', stub, re.M)
        return match.group(1) if match else (ROOT / "slink_gen3_trade").as_posix()
    return run, path("a"), path("b")


def test_two_attempts_share_only_within_the_attempt(monkeypatch, tmp_path):
    first, a1, b1 = _launch_pair(monkeypatch, tmp_path, 1)
    second, a2, b2 = _launch_pair(monkeypatch, tmp_path, 2)
    assert a1 == b1 == (Path(first.data_dir) / "slink_gen3_trade").as_posix()
    assert a2 == b2 == (Path(second.data_dir) / "slink_gen3_trade").as_posix()
    assert a1 != a2


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
    ("trade_lock_probe_gen3", {}),
    ("native_trade_gen3", {"gen3_native_trade": True}),
])
def test_existing_journal_owners_keep_their_paths(scenario, cfg, tmp_path):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario, run.cfg, run.data_dir = scenario, cfg, str(tmp_path)
    assert run._gen3_duo_journal_path() is None
