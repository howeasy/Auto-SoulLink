"""Run Manager lifecycle: start/stop serialize per run, a run is "running" only once its
server answers, and a pid is trusted (or killed) only while its create time still matches.
Every child here is a fake: no server.py, no emulator."""

import asyncio
from types import SimpleNamespace

import pytest

import server.manager as manager

pytest_plugins = ["tests.unit.manager_harness"]


def _stopped_run(**extra):
    run = {"run_id": "r1", "name": "Duo", "tcp_port": 1, "http_port": 2, "status": "stopped", "pid": None}
    run.update(extra)
    manager._save_registry([run])


def _registry_run():
    return manager._find_run(manager._load_registry(), "r1")


def _blocking_spawn(monkeypatch):
    """A _spawn_run that parks until released; returns (spawn log, release event)."""
    spawns, release = [], asyncio.Event()

    async def spawn(run, host, manager_port=0):
        spawns.append(run["run_id"])
        await release.wait()
        return 4242
    monkeypatch.setattr(manager, "_spawn_run", spawn)
    monkeypatch.setattr(manager, "_create_time", lambda pid: 100.0)
    monkeypatch.setattr(manager, "_is_alive", lambda pid, created=None: pid == 4242)
    return spawns, release


@pytest.mark.asyncio
async def test_two_concurrent_starts_spawn_one_server(manager_client, monkeypatch):
    _stopped_run()
    spawns, release = _blocking_spawn(monkeypatch)
    first = asyncio.ensure_future(manager_client.post("/api/runs/r1/start"))
    second = asyncio.ensure_future(manager_client.post("/api/runs/r1/start"))
    await asyncio.sleep(0.1)
    release.set()
    bodies = [await (await r).json() for r in (first, second)]
    assert spawns == ["r1"]
    assert all(b["ok"] for b in bodies)
    assert _registry_run()["status"] == "running" and _registry_run()["pid"] == 4242


@pytest.mark.asyncio
async def test_a_stop_during_a_start_ends_stopped_and_kills_the_child(manager_client, monkeypatch):
    _stopped_run()
    _spawns, release = _blocking_spawn(monkeypatch)
    killed = []
    monkeypatch.setattr(manager, "_kill_run", lambda pid, created=None: killed.append((pid, created)) or True)
    start = asyncio.ensure_future(manager_client.post("/api/runs/r1/start"))
    await asyncio.sleep(0.05)
    stop = asyncio.ensure_future(manager_client.post("/api/runs/r1/stop"))
    await asyncio.sleep(0.05)
    release.set()
    assert (await (await start).json())["ok"]
    assert (await (await stop).json())["ok"]
    assert killed == [(4242, 100.0)]
    run = _registry_run()
    assert run["status"] == "stopped" and run["pid"] is None


def _fake_child(monkeypatch, *, exits_after: float | None, log_line: str = ""):
    """A child that never answers HTTP; it exits (code 1) after `exits_after` s, or never."""
    killed = []

    async def create(*_cmd, **kwargs):
        if log_line:
            kwargs["stderr"].write(log_line.encode())
        child = SimpleNamespace(pid=4242, returncode=None, kill=lambda: killed.append(4242))

        async def wait():
            if exits_after is None:
                await asyncio.Event().wait()
            await asyncio.sleep(exits_after)
            child.returncode = 1
            return 1
        child.wait = wait
        return child

    async def silent(*_args):
        return False
    monkeypatch.setattr(manager.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(manager, "_http_ready", silent, raising=False)
    monkeypatch.setattr(manager, "SPAWN_POLL_S", 0.02, raising=False)
    return killed


@pytest.mark.asyncio
async def test_a_child_that_dies_after_the_old_grace_is_an_error_not_running(manager_client, monkeypatch):
    """Alive at 1.5 s is not ready: a server that dies later (a slow import, then a taken
    HTTP port) must not leave the registry saying running."""
    _stopped_run()
    _fake_child(monkeypatch, exits_after=1.7, log_line="Cannot listen on HTTP 127.0.0.1:2 -- in use\n")
    response = await manager_client.post("/api/runs/r1/start")
    body = await response.json()
    assert response.status == 500 and not body["ok"]
    assert "exited on startup" in body["error"] and "Cannot listen on HTTP" in body["error"]
    assert _registry_run()["status"] == "stopped" and _registry_run()["pid"] is None


@pytest.mark.asyncio
async def test_a_child_that_never_answers_is_killed_and_reported(manager_dir, monkeypatch):
    killed = _fake_child(monkeypatch, exits_after=None)
    monkeypatch.setattr(manager, "SPAWN_READY_S", 0.1)
    with pytest.raises(RuntimeError, match="did not answer on HTTP 2"):
        await manager._spawn_run({"run_id": "r1", "tcp_port": 1, "http_port": 2}, "0.0.0.0")
    assert killed == [4242]


def _fake_psutil(monkeypatch, *, started: float, terminate_fails: bool = False):
    """psutil with one live process, pid 4242, started at `started`."""
    terminated = []

    class Error(Exception):
        pass

    class AccessDenied(Error):
        pass

    class Process:
        def __init__(self, pid):
            if pid != 4242:
                raise Error(pid)

        def create_time(self):
            return started

        def terminate(self):
            if terminate_fails:
                raise AccessDenied("denied")
            terminated.append(4242)

        kill = terminate

        def wait(self, timeout=None):
            pass

    monkeypatch.setattr(manager, "psutil", SimpleNamespace(
        Process=Process, Error=Error, TimeoutExpired=Error, pid_exists=lambda pid: pid == 4242), raising=False)
    monkeypatch.setattr(manager, "PSUTIL_AVAILABLE", True)
    return terminated


@pytest.mark.asyncio
async def test_a_reused_pid_is_not_killed(manager_client, monkeypatch):
    """The recorded pid now belongs to a process started at another time: not ours."""
    _stopped_run(status="running", pid=4242, pid_created=100.0)
    terminated = _fake_psutil(monkeypatch, started=200.0)
    response = await manager_client.post("/api/runs/r1/stop")
    assert (await response.json())["ok"]
    assert terminated == []
    assert _registry_run()["status"] == "stopped" and _registry_run()["pid"] is None


@pytest.mark.asyncio
async def test_a_kill_that_fails_reports_an_error_and_keeps_the_pid(manager_client, monkeypatch):
    _stopped_run(status="running", pid=4242, pid_created=100.0)
    _fake_psutil(monkeypatch, started=100.0, terminate_fails=True)
    response = await manager_client.post("/api/runs/r1/stop")
    body = await response.json()
    assert response.status == 500 and not body["ok"] and "4242" in body["error"]
    assert _registry_run()["status"] == "running" and _registry_run()["pid"] == 4242


@pytest.mark.asyncio
async def test_the_board_poll_reconciles_a_dead_pid(manager_client, monkeypatch):
    _stopped_run(status="running", pid=4242, pid_created=100.0)
    monkeypatch.setattr(manager, "_is_alive", lambda pid, created=None: False)
    assert (await manager_client.get("/runs/r1/board")).status == 200
    assert _registry_run()["status"] == "stopped" and _registry_run()["pid"] is None


@pytest.mark.asyncio
async def test_new_run_form_is_accessible(manager_client):
    body = await (await manager_client.get("/new")).text()
    games = body[body.index('id="game-label"'):]
    assert 'role="radiogroup" aria-labelledby="game-label"' in games
    assert 'role="radio" :aria-checked="draft.game === g.key"' in games
    assert '@keydown="radioKeys($event)"' in games
    assert '<span class="mk-sub" role="alert" x-text="error"' in body
    assert ":aria-describedby=\"draft.name.trim() ? null : 'run-name-hint'\"" in body
    assert 'id="run-name-hint"' in body and ':aria-invalid="tried && !draft.name.trim()"' in body
    assert ":aria-describedby=\"'opt-' + key + '-desc'" in body
    assert ":id=\"'opt-' + key + '-desc'\"" in body and ":id=\"'opt-' + key + '-why'\"" in body
