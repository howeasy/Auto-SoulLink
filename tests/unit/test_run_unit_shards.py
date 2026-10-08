"""Tests for tools/run_unit_shards.py. They use a tmp repo with two tiny test files,
never the real unit suite."""

from __future__ import annotations

from tools import run_unit_shards as rus


def _make_root(root, *, second_passes: bool):
    unit = root / "tests" / "unit"
    unit.mkdir(parents=True)
    (unit / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    body = "assert True" if second_passes else "assert False"
    (unit / "test_b.py").write_text(f"def test_b():\n    {body}\n", encoding="utf-8")
    return root


def test_split_round_robin_and_env_forcing(monkeypatch):
    assert rus.split_round_robin(list("abcde"), 2) == [list("ace"), list("bd")]
    assert rus.split_round_robin(["x"], 4) == [["x"]]  # empty groups dropped

    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONIOENCODING", "latin-1")
    monkeypatch.setenv("SLINK_WORK_ROOT", "G:/custom")
    monkeypatch.delenv("PYTEST_DEBUG_TEMPROOT", raising=False)
    env = rus.build_env()
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["SLINK_WORK_ROOT"] == "G:/custom"  # set value kept
    assert env["PYTEST_DEBUG_TEMPROOT"] == "F:/slink-work/tmp"  # unset value defaulted


def test_failing_shard_gives_exit_1_and_failures_file(tmp_path):
    root = _make_root(tmp_path / "repo", second_passes=False)
    out = tmp_path / "out"
    rc = rus.run(root, 2, out, [])
    assert rc == 1
    assert (out / "s1.files").read_text(encoding="utf-8").split() == ["tests/unit/test_a.py"]
    failures = (out / "failures.txt").read_text(encoding="utf-8")
    assert "FAILED" in failures and "test_b.py::test_b" in failures


def test_all_passing_shards_exit_0(tmp_path):
    root = _make_root(tmp_path / "repo", second_passes=True)
    out = tmp_path / "out"
    assert rus.run(root, 2, out, []) == 0
    assert (out / "failures.txt").read_text(encoding="utf-8") == ""
