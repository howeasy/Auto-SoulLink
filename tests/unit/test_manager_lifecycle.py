import asyncio
import json
from types import SimpleNamespace

import pytest

from server import manager


class Request:
    def __init__(self, run_id="", body=None):
        self.match_info = {"run_id": run_id}
        self.body = body

    async def json(self):
        return self.body


@pytest.fixture
def service(tmp_path, monkeypatch):
    directory = tmp_path / "runs"
    directory.mkdir()
    monkeypatch.setattr(manager, "MANAGER_DIR", str(directory))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(directory / "registry.json"))
    monkeypatch.setattr(manager, "_is_alive", lambda pid: bool(pid))
    monkeypatch.setattr(manager, "_stop_owned_run", lambda run: manager._kill_run(run["pid"]))
    return manager.RunManager("0.0.0.0"), directory


@pytest.mark.asyncio
async def test_concurrent_creations_preserve_both_records_and_port_allocations(service, monkeypatch):
    app, _ = service
    ready, release = asyncio.Event(), asyncio.Event()
    starts = []

    async def spawn(run, *args, **kwargs):
        pid = 1000 + len(starts)
        starts.append(run)
        if len(starts) == 2:
            ready.set()
        await release.wait()
        return pid

    monkeypatch.setattr(manager, "_spawn_run", spawn)
    tasks = [asyncio.create_task(app.handle_new(Request(body={"name": name}))) for name in ("First", "Second")]
    await asyncio.wait_for(ready.wait(), 2)
    during = manager._load_registry()
    assert len(during) == 2 and len({run["tcp_port"] for run in during}) == 2
    assert len({run["http_port"] for run in during}) == 2
    release.set()
    responses = await asyncio.gather(*tasks)
    assert all(response.status == 200 for response in responses)
    final = manager._load_registry()
    assert {run["name"] for run in final} == {"First", "Second"}
    assert all(run["status"] == "running" and run["pid"] for run in final)


@pytest.mark.asyncio
async def test_same_run_start_requests_share_one_spawn(service, monkeypatch):
    app, _ = service
    response = await app.handle_new(Request(body={"name": "One", "auto_start": False}))
    run_id = json.loads(response.text)["run"]["run_id"]
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(1)
        entered.set()
        await release.wait()
        return 456

    monkeypatch.setattr(manager, "_spawn_run", spawn)
    first = asyncio.create_task(app.handle_start(Request(run_id)))
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(app.handle_start(Request(run_id)))
    release.set()
    assert all(response.status == 200 for response in await asyncio.gather(first, second))
    assert calls == [1]


@pytest.mark.asyncio
async def test_registry_corruption_during_spawn_preserves_file_and_stops_unrecorded_child(service, monkeypatch):
    app, directory = service
    response = await app.handle_new(Request(body={"name": "One", "auto_start": False}))
    run_id = json.loads(response.text)["run"]["run_id"]
    entered, release = asyncio.Event(), asyncio.Event()
    killed = []

    async def spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return 789

    monkeypatch.setattr(manager, "_spawn_run", spawn)
    monkeypatch.setattr(manager, "_kill_run", killed.append)
    task = asyncio.create_task(app.handle_start(Request(run_id)))
    await asyncio.wait_for(entered.wait(), 2)
    (directory / "registry.json").write_bytes(b"{broken")
    release.set()
    with pytest.raises(manager.RegistryError):
        await task
    assert killed == [789] and (directory / "registry.json").read_bytes() == b"{broken"


@pytest.mark.asyncio
async def test_orphan_discovery_is_not_repeated_for_every_read(service, monkeypatch):
    app, _ = service
    calls = []
    monkeypatch.setattr(manager, "_adopt_orphans", lambda runs: calls.append(1) or False)
    await app.initialize()
    for _ in range(5):
        assert app._get() == []
    assert calls == [1]


@pytest.mark.asyncio
async def test_deleted_run_id_is_not_reused_by_a_new_run(service):
    app, _ = service
    first = json.loads((await app.handle_new(Request(body={"name": "One", "auto_start": False}))).text)["run"]
    await app.handle_delete(Request(first["run_id"]))
    second = json.loads((await app.handle_new(Request(body={"name": "Two", "auto_start": False}))).text)["run"]
    assert first["run_id"] != second["run_id"]


@pytest.mark.parametrize("peer,host,allowed", [("127.0.0.1", "localhost:8090", True), ("::1", "[::1]:8090", True),
    ("192.168.1.20", "localhost:8090", False), ("127.0.0.1", "untrusted.example:8090", False),
    ("127.0.0.1", "localhost.evil.example:8090", False), ("127.0.0.1", "user@localhost", False),
    ("127.0.0.1", "localhost/elsewhere", False), ("127.0.0.1", "localhost:99999", False)])
def test_local_file_access_requires_loopback_and_validated_host(peer, host, allowed):
    from server.http_safety import local_operator
    assert local_operator(SimpleNamespace(remote=peer, host=host)) is allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["stop", "archive", "delete"])
async def test_lifecycle_actions_wait_for_a_pending_start(service, monkeypatch, action):
    app, _ = service
    run = json.loads((await app.handle_new(Request(body={"name": "Ordered", "auto_start": False}))).text)["run"]
    entered, release = asyncio.Event(), asyncio.Event()
    killed = []
    async def spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return 321
    monkeypatch.setattr(manager, "_spawn_run", spawn)
    monkeypatch.setattr(manager, "_kill_run", killed.append)
    starting = asyncio.create_task(app.handle_start(Request(run["run_id"])))
    await asyncio.wait_for(entered.wait(), 2)
    stopping = asyncio.create_task(getattr(app, "handle_" + action)(Request(run["run_id"])))
    assert not stopping.done()
    release.set()
    assert all(response.status == 200 for response in await asyncio.gather(starting, stopping))
    assert killed == [321]
    saved = app._get()
    assert saved == [] if action == "delete" else saved[0]["status"] == ("stopped" if action == "stop" else "archived")


@pytest.mark.asyncio
async def test_valid_external_registry_edits_survive_an_awaited_start(service, monkeypatch):
    app, _ = service
    run = json.loads((await app.handle_new(Request(body={"name": "Original", "auto_start": False}))).text)["run"]
    async def spawn(*args, **kwargs):
        fresh = manager._load_registry()
        fresh[0].update(name="Renamed externally", unrelated_setting={"keep": True})
        manager._save_registry(fresh)
        return 654
    monkeypatch.setattr(manager, "_spawn_run", spawn)
    assert (await app.handle_start(Request(run["run_id"]))).status == 200
    assert app._get()[0]["name"] == "Renamed externally"
    assert app._get()[0]["unrelated_setting"] == {"keep": True}


@pytest.mark.asyncio
async def test_browser_cancellation_does_not_interrupt_an_accepted_lifecycle_transaction(service, monkeypatch):
    app, _ = service
    entered, release = asyncio.Event(), asyncio.Event()
    async def spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return 987
    monkeypatch.setattr(manager, "_spawn_run", spawn)
    request = Request(body={"name": "Keep transaction"})
    request.method = "POST"
    task = asyncio.create_task(manager.finish_mutations(request, app.handle_new))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert app._get()[0]["status"] == "running" and app._get()[0]["pid"] == 987


@pytest.mark.asyncio
async def test_spawn_failure_is_visible_on_created_record(service, monkeypatch):
    app, _ = service
    async def fail(*args, **kwargs):
        raise OSError("Cannot launch test child")
    monkeypatch.setattr(manager, "_spawn_run", fail)
    result = json.loads((await app.handle_new(Request(body={"name": "Failure"}))).text)
    assert result["run"]["status"] == "stopped"
    assert result["run"]["last_error"] == "Cannot launch test child"
