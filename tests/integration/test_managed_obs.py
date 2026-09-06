import asyncio
from contextlib import AsyncExitStack

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server import manager
from server.obs_controller import OBSController
from server.obs_run_bridge import OBSRunBridge
from server.server import build_app
from tests.dashboard_scenarios import dashboard_scenario
from tests.obs_fixture import OBSFixture


@pytest.mark.asyncio
async def test_two_runs_share_ordered_obs_execution_over_real_http_and_websockets(tmp_path, monkeypatch):
    directory = tmp_path / "runs"
    directory.mkdir()
    monkeypatch.setattr(manager, "MANAGER_DIR", str(directory))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(directory / "registry.json"))
    monkeypatch.setattr(manager, "_is_alive", lambda pid: bool(pid))
    fixture = OBSFixture()
    servers = []
    async with AsyncExitStack() as stack:
        websocket = await stack.enter_async_context(TestServer(fixture.app))
        registry = []
        for game in ("gen3", "gen1"):
            run_id = "run_" + game
            server = dashboard_scenario(game, directory / run_id)
            server._run_id, server._manager_port = run_id, 8090
            server.obs = OBSController(str(directory / run_id / "obs.json"), managed=True)
            server.obs_bridge = OBSRunBridge(server.obs, run_id, 8090)
            server.obs.event_sink = server.obs_bridge.submit
            servers.append(server)
            child = await stack.enter_async_context(TestServer(build_app(server)))
            registry.append({"run_id": run_id, "name": game, "pid": child.port, "status": "running", "http_port": child.port, "tcp_port": 54321 + len(registry)})
        manager._save_registry(registry)
        service = manager.RunManager("127.0.0.1")
        client = await stack.enter_async_context(TestClient(TestServer(manager.build_app(service))))
        for server in servers:
            server.obs_bridge.manager_url = str(client.make_url("/")).rstrip("/")
        try:
            status = await (await client.get("/api/obs/status")).json()
            config = status["config"]
            config["enabled"] = True
            config["connections"] = {pid: {"host": "127.0.0.1", "port": websocket.port} for pid in ("a", "b")}
            config["rules"] = [{"id": game, "run_id": "run_" + game, "enabled": True, "event": "capture",
                                "player_filter": "any", "target": "both", "scene": scene, "area_id_filter": ""}
                               for game, scene in (("gen3", "Caught"), ("gen1", "Other run"))]
            response = await client.post("/api/obs/config", json=config)
            assert response.status == 200
            applied = await response.json()
            assert all(item.get("ok") for item in applied["applications"].values()), applied["applications"]
            fixture.release.clear()
            servers[0].obs.submit_fired([["capture", "a", {}]])
            await asyncio.wait_for(servers[0].obs_bridge.queue.join(), 5)
            assert servers[0].obs_bridge.forwarding_error is None, servers[0].obs_bridge.forwarding_error
            try:
                await asyncio.wait_for(fixture.received.wait(), 5)
            except TimeoutError:
                pytest.fail(str({"records": service.obs.status()["records"], "controllers": [s.obs.get_status() for s in servers]}))
            servers[1].obs.submit_fired([["capture", "b", {}]])
            await asyncio.wait_for(servers[1].obs_bridge.queue.join(), 5)
            assert fixture.requests == ["Caught"]  # second run is waiting at the shared endpoint
            fixture.release.set()
            await asyncio.wait_for(asyncio.gather(*(q.join() for q in service.obs.queues.values())), 5)
            assert fixture.requests == ["Caught", "Other run"] and fixture.peak == 1
            assert all(record["state"] == "applied" for record in service.obs.records)
            response = await client.post("/api/obs/test", json={"run_id": "run_gen3", "player": "b", "scene": "Missing scene"})
            assert response.status == 202
            await asyncio.wait_for(asyncio.gather(*(q.join() for q in service.obs.queues.values())), 5)
            assert service.obs.records[0]["state"] == "failed"
            assert "Scene unavailable" in service.obs.records[0]["error"]
            assert not service.obs.blocked_endpoints  # a negative OBS acknowledgement is a known failure
        finally:
            fixture.release.set()
            for server in servers:
                await server.obs_bridge.close()
                await server.obs.stop_workers()
