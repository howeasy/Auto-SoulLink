"""tests/conftest.py _absent_gen2_clone runs inside the pytest_runtest_makereport hook for every
failing test. A FileNotFoundError whose path cannot be made relative to .cache/gen2-build (on
Windows: another drive, e.g. tmp_path on C: with the repo on E:) is outside that tree, not an
INTERNALERROR that aborts the session."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import _GEN2_BUILD, _absent_gen2_clone


def _fnf(path):
    return FileNotFoundError(2, "No such file or directory", path)


def test_an_absent_clone_under_gen2_build_is_still_named():
    # known-positive control: the hook still skips a genuinely absent clone
    path = os.path.join(_GEN2_BUILD, "no_such_clone_xyz", "baserom.gbc")
    assert _absent_gen2_clone(_fnf(path)) == f"no_such_clone_xyz not cloned: {os.path.join(_GEN2_BUILD, 'no_such_clone_xyz')}"


def test_a_path_on_another_mount_is_outside_the_tree_not_an_error(monkeypatch):
    def relpath(path, start=None):
        raise ValueError("path is on mount 'C:', start on mount 'E:'")

    monkeypatch.setattr(os.path, "relpath", relpath)
    assert _absent_gen2_clone(_fnf(r"C:\Temp\pytest-of-x\missing.bin")) is None


def test_cross_drive_failures_are_reported_and_the_session_continues(tmp_path):
    """Exercise the real report hook, including its exception-chain traversal."""
    # Copy the actual hook so the child session exercises this checkout's code.
    source = Path(__file__).resolve().parents[1] / "conftest.py"
    (tmp_path / "conftest.py").write_bytes(source.read_bytes())
    (tmp_path / "test_report.py").write_text(
        r"""
import ntpath
import os
from pathlib import Path

import conftest


def _cross_drive_failure(monkeypatch):
    drive = "E:" if Path(conftest._GEN2_BUILD).drive.upper() != "E:" else "F:"
    missing = drive + "/slink-o1-missing/file.bin"
    if os.name != "nt":
        # Reproduce Windows path semantics on other platforms too, without
        # disturbing pytest's own relative paths while it formats the report.
        real_relpath = os.path.relpath

        def relpath(path, start=os.curdir):
            if path == os.path.abspath(missing):
                return ntpath.relpath(r"F:\missing.bin", r"E:\repo")
            return real_relpath(path, start)

        monkeypatch.setattr(os.path, "relpath", relpath)
    raise FileNotFoundError(2, "cross-drive regression sentinel", missing)


def test_direct_cross_drive_failure(monkeypatch):
    _cross_drive_failure(monkeypatch)


def test_chained_cross_drive_failure(monkeypatch):
    try:
        _cross_drive_failure(monkeypatch)
    except FileNotFoundError as exc:
        raise RuntimeError("wrapped cross-drive sentinel") from exc


def test_missing_clone_is_skipped():
    missing = Path(conftest._GEN2_BUILD) / "o1_absent_clone" / "baserom.gbc"
    raise FileNotFoundError(2, "missing clone sentinel", str(missing))


def test_present_clone_missing_file_still_fails():
    clone = Path(conftest._GEN2_BUILD) / "o1_present_clone"
    clone.mkdir(parents=True)
    raise FileNotFoundError(2, "present clone sentinel", str(clone / "baserom.gbc"))


def test_later_test_still_runs():
    assert True
""",
        encoding="utf-8",
    )
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "--tb=short", "test_report.py"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout + result.stderr
    assert result.returncode == pytest.ExitCode.TESTS_FAILED, output
    assert "INTERNALERROR" not in output, output
    assert "3 failed, 1 passed, 1 skipped" in output, output
    assert "cross-drive regression sentinel" in output, output
    assert "wrapped cross-drive sentinel" in output, output
    assert "o1_absent_clone not cloned:" in output, output
    assert "present clone sentinel" in output, output
