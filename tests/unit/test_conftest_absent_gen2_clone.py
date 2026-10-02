"""tests/conftest.py _absent_gen2_clone runs inside the pytest_runtest_makereport hook for every
failing test. A FileNotFoundError whose path cannot be made relative to .cache/gen2-build (on
Windows: another drive, e.g. tmp_path on C: with the repo on E:) is outside that tree, not an
INTERNALERROR that aborts the session."""
import os

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
