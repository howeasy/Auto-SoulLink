import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server import manager
from server.server import SLinkServer, build_app


@pytest.mark.asyncio
async def test_private_execution_routes_require_managed_local_target_and_never_enter_public_proxy(tmp_path, monkeypatch):
    directory = tmp_path / "runs"
    directory.mkdir()
    monkeypatch.setattr(manager, "MANAGER_DIR", str(directory))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(directory / "registry.json"))
    monkeypatch.setattr(manager, "_is_alive", lambda pid: bool(pid))
    server = SLinkServer(data_dir=str(directory / "run_one"), run_id="run_one", manager_port=8090)
    config = {"enabled": False, "connections": {pid: {"host": "", "port": 4455} for pid in ("a", "b")}}
    try:
        async with TestClient(TestServer(build_app(server))) as child:
            assert (await child.post("/_internal/obs/config", json={"revision": 1, "config": config})).status == 404
            headers = {"X-SLink-Target-Run": "run_one"}
            response = await child.post("/_internal/obs/config", json={"revision": 0, "config": config}, headers=headers)
            assert response.status == 200 and (await response.json())["applied_revision"] == 0
            assert (await child.post("/api/obs/config", json=config)).status == 409
            manager._save_registry([{"run_id": "run_one", "name": "One", "status": "running", "pid": 123,
                                     "http_port": child.server.port, "tcp_port": 54321}])
            service = manager.RunManager("127.0.0.1")
            async with TestClient(TestServer(manager.build_app(service))) as client:
                assert (await client.get("/runs/run_one/_internal/obs/status")).status == 404
                assert (await client.post("/runs/run_one/_internal/obs/scene", json={})).status == 404
                status = await (await client.get("/api/obs/status?run_id=run_one")).json()
                assert status["applications"]["run_one"]["applied_revision"] == 0
                assert "password" not in status["config"]["connections"]["a"]
                document = status["config"]
                document["connections"]["a"]["password"] = "secret"
                response = await client.post("/api/obs/config", json=document)
                saved = await response.json()
                assert response.status == 200 and saved["ok"]
                assert saved["applications"]["run_one"]["applied_revision"] == saved["config"]["revision"]
                assert "secret" not in json.dumps(saved)
    finally:
        await server.obs_bridge.close()
        await server.obs.stop_workers()


@pytest.mark.asyncio
async def test_unconfirmed_execution_blocks_further_scene_changes_on_that_endpoint(tmp_path):
    from server.obs_arbitration import OBSArbiter
    from tests.unit.test_obs_arbitration import configured, lookup
    calls = []
    async def execute(decision):
        calls.append(decision["batch_id"])
        return {"ok": False, "confirmed": False, "error": "Connection lost before confirmation"}
    service = OBSArbiter(tmp_path / "obs.json", lookup, execute)
    service.config = configured()
    try:
        await service.submit("run_one", "first", [["capture", "a", {}]])
        await service.submit("run_one", "next", [["capture", "b", {}]])
        await asyncio.gather(*(q.join() for q in service.queues.values()))
        assert calls == ["first"]
        assert len(service.records) == 2
        assert service.status()["blocked_endpoints"][0]["port"] == 4455
        assert "unconfirmed" in service.records[0]["error"]
    finally:
        await service.close()
