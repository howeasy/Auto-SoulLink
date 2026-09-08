import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server import manager
from server.server import build_app
from tests.dashboard_scenarios import dashboard_scenario


@pytest.mark.asyncio
async def test_ambiguous_source_file_refuses_http_reads_and_writes_without_retargeting(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "MANAGER_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(tmp_path / "registry.json"))
    manager._save_registry([{"run_id": run_id, "name": run_id, "status": "stopped", "pid": None,
                             "http_port": 8081 + index, "tcp_port": 54321 + index}
                            for index, run_id in enumerate(("run_one", "run_two"))])
    service = manager.RunManager("127.0.0.1")
    source = await service.sources.create({"name": "Team", "run_id": "run_one", "preset": "party"})
    original = service.sources.path.read_bytes()
    ambiguous = original.replace(b'"run_id": "run_one"', b'"run_id": "run_one", "run_id": "run_two"')
    assert ambiguous != original
    service.sources.path.write_bytes(ambiguous)

    async def forbidden_projection(*args):
        raise AssertionError("An ambiguous source must never resolve a run projection")

    monkeypatch.setattr(service, "_source_context", forbidden_projection)
    api = "/api/broadcast/sources"
    page = "/broadcast/sources/" + source["id"]
    cases = [("GET", api, None), ("GET", api + "/" + source["id"], None),
             ("POST", api, {"name": "New", "run_id": "run_one", "preset": "party"}),
             ("PATCH", api + "/" + source["id"], {"revision": 1, "run_id": "run_two"}),
             ("DELETE", api + "/" + source["id"], {"revision": 1}),
             ("GET", page, None), ("GET", page + "/fragment?revision=1", None)]
    async with TestClient(TestServer(manager.build_app(service))) as client:
        for method, url, body in cases:
            response = await client.request(method, url, **({"json": body} if body is not None else {}))
            assert response.status == 503
            text = await response.text()
            assert "original file has been preserved" in text
            assert service.sources.path.read_bytes() == ambiguous
        service.sources.path.write_bytes(original)  # Model operator restoration, never automatic repair.
        recovered = await client.get(api + "/" + source["id"])
        assert recovered.status == 200
        assert (await recovered.json())["source"] == source


@pytest.mark.asyncio
async def test_saved_source_retargets_with_revision_and_never_switches_when_run_stops(tmp_path, monkeypatch):
    directory = tmp_path / "runs"
    directory.mkdir()
    monkeypatch.setattr(manager, "MANAGER_DIR", str(directory))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(directory / "registry.json"))
    monkeypatch.setattr(manager, "_is_alive", lambda pid: bool(pid))
    server = dashboard_scenario("gen3", directory / "run_one")
    server._run_id, server._manager_port = "run_one", 8090
    (directory / "run_one" / "links.json").write_text(json.dumps(server.state.to_document()))
    async with TestServer(build_app(server)) as child:
        manager._save_registry([{"run_id": "run_one", "name": "First", "status": "running", "pid": 123, "http_port": child.port, "tcp_port": 54321},
                               {"run_id": "run_two", "name": "Second", "status": "stopped", "pid": None, "http_port": 8082, "tcp_port": 54322}])
        service = manager.RunManager("127.0.0.1")
        async with TestClient(TestServer(manager.build_app(service))) as client:
            response = await client.post("/api/broadcast/sources", json={"name": "Team", "run_id": "run_one", "preset": "linked-party"})
            assert response.status == 201
            source = (await response.json())["source"]
            assert (await client.head("/api/broadcast/sources")).status == 200
            assert (await client.head("/api/broadcast/sources/" + source["id"])).status == 200
            url = "/broadcast/sources/" + source["id"]
            legacy = await client.get("/runs/run_one/stream/party-a/fragment?layout=%20H%20")
            assert legacy.status == 200 and "layout-h" in await legacy.text()
            page = await client.get(url)
            assert page.status == 200 and 'data-availability="live"' in await page.text()
            # Calc's real SSE stream must not monopolize the origin while the
            # board and multiple OBS documents poll independently.
            stream = await client.get("/runs/run_one/api/events")
            try:
                assert await asyncio.wait_for(stream.content.readuntil(b"\n\n"), 2) == b"retry: 3000\n\n"
                paths = ["/runs/run_one/api/status", url + "/fragment?revision=1",
                         "/runs/run_one/stream/party-b/fragment"]
                responses = await asyncio.wait_for(asyncio.gather(*(client.get(path) for path in paths)), 3)
                assert all(response.status == 200 for response in responses)
                assert all(await asyncio.gather(*(response.read() for response in responses)))
                assert b"event: ping" in await asyncio.wait_for(stream.content.readuntil(b"\n\n"), 2)
            finally:
                stream.close()
            await service._mutate_registry(lambda runs: runs[0].update(status="stopped", pid=None))
            stopped = await client.get(url + "/fragment?revision=1")
            content = await stopped.text()
            assert stopped.status == 200 and 'data-availability="stopped"' in content
            assert "Player A" in content and "Player B" in content
            assert "Saved links" in content and 'role="progressbar"' not in content
            update = await client.patch("/api/broadcast/sources/" + source["id"], json={"revision": 1, "run_id": "run_two", "theme": "light"})
            assert update.status == 200
            assert (await client.get(url + "/fragment?revision=1")).status == 409
            current = await client.get(url)
            text = await current.text()
            assert 'theme-light' in text and 'data-source-revision="2"' in text
            assert "Second" in text
            await service._mutate_registry(lambda runs: runs.pop(1))
            assert 'data-availability="deleted"' in await (await client.get(url + "/fragment?revision=2")).text()
            assert service.sources.get(source["id"])["run_id"] == "run_two"


@pytest.mark.asyncio
async def test_late_old_run_response_cannot_restore_a_retargeted_source(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "MANAGER_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(tmp_path / "registry.json"))
    manager._save_registry([{"run_id": name, "name": name, "status": "stopped", "pid": None,
                             "http_port": 8081 + index, "tcp_port": 54321 + index} for index, name in enumerate(("first", "second"))])
    service = manager.RunManager("127.0.0.1")
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow(source):
        entered.set()
        await release.wait()
        return {"secret_old_content": "must not be rendered"}
    service._source_context = slow
    async with TestClient(TestServer(manager.build_app(service))) as client:
        source = await service.sources.create({"name": "Slow", "run_id": "first", "preset": "party"})
        task = asyncio.create_task(client.get("/broadcast/sources/" + source["id"] + "/fragment?revision=1"))
        await asyncio.wait_for(entered.wait(), 2)
        await service.sources.update(source["id"], {"revision": 1, "run_id": "second"})
        release.set()
        response = await task
        assert response.status == 409 and response.headers["X-SLink-Source-Revision"] == "2"
        assert "must not be rendered" not in await response.text()
