from types import SimpleNamespace

import pytest
from aiohttp import web

from server import manager


@pytest.mark.parametrize("module,directory,accepted", [
    ("server.server", "run_one", True), ("unrelated.app", "run_one", False),
    ("server.server", "run_other", False), ("server.server", "../outside", False),
])
def test_stop_only_terminates_the_registered_server_process(tmp_path, monkeypatch, module, directory, accepted):
    monkeypatch.setattr(manager, "MANAGER_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "_is_alive", lambda pid: True)
    monkeypatch.setattr(manager, "PSUTIL_AVAILABLE", True)
    command = ["python", "-m", module, "--data-dir", str(tmp_path / directory)]
    monkeypatch.setattr(manager.psutil, "Process", lambda pid: SimpleNamespace(cmdline=lambda: command))
    killed = []
    monkeypatch.setattr(manager, "_kill_run", lambda pid, **kwargs: killed.append(pid))
    run = {"run_id": "run_one", "pid": 123}
    if accepted:
        manager._stop_owned_run(run)
        assert killed == [123]
    else:
        with pytest.raises(web.HTTPConflict) as error:
            manager._stop_owned_run(run)
        assert "No process was stopped" in error.value.text
        assert not killed


def test_failed_termination_is_not_reported_as_stopped(monkeypatch):
    monkeypatch.setattr(manager, "_is_alive", lambda pid: True)
    monkeypatch.setattr(manager, "PSUTIL_AVAILABLE", True)
    def denied():
        raise PermissionError("denied")
    monkeypatch.setattr(manager.psutil, "Process", lambda pid: SimpleNamespace(terminate=denied))
    with pytest.raises(web.HTTPServiceUnavailable) as error:
        manager._kill_run(123)

    assert "registry state was retained" in error.value.text
